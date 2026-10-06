# ratings フェーズのコスト削減

作成: 2026-09-14 / 改訂: 2026-09-14（Fable のレビューを反映してスコープを縮小）

## 背景

日次 Extract の ratings フェーズは4時間05分かかっている（2026-09-13 の実測、ログから）。

| 区間 | 所要 | 中身 |
|---|---|---|
| ダウンロード＋パース＋COPY | 2h33m | zip 約12.6GB の取得・展開、Python のパース、COPY |
| dedup（`DELETE ... ROW_NUMBER`） | 32m | **削除 0 行**。0行でも全件スキャン＋ソート |
| PK index 構築 | 20m | |
| SET LOGGED | 40m | 214M 行の書き換え＋WAL |
| swap / drop | 1s | |

処理行数は 214,984,620 行。`CpuUtilized` は ratings 区間で最大 960/1024（1 vCPU の 93.7%）で、
他フェーズ（Notes 313、Status 264）と比べて突出している。単一スレッドの Python なので
cpu 2048 を割り当てても 2 コア目は使えていない。

## 今回のスコープ：dedup の楽観化のみ

**dedup を先に走らせず、まず PK 構築を試す。`UniqueViolation` が出たときだけ dedup して作り直す。**

### 根拠

過去30日の dedup 実行19回すべてが `removed 0 duplicate rows`（CloudWatch Logs で確認、
08-16〜09-13。欠けている日は6日間停止などで実行自体が無い日）。
**32分かけて毎日ゼロ行を消している。**

- 重複0の日: **−32分**、追加コストゼロ
- 重複が出た日: 失敗した PK 構築ぶん **+20分**（`ALTER TABLE ADD CONSTRAINT` の失敗はロールバックされ staging は無傷）
- 「`created_at_millis` が最新の行を残す」意味論はフォールバック経路でそのまま維持される

### なぜこれが最もリスクが低いか

- **データ変換に一切触らない。** 変えるのは「dedup をいつ走らせるか」だけで、値が壊れる経路が無い
- **失敗モードがフェイルセーフ。** PK 構築が失敗すれば ratings フェーズが失敗し、swap されないので
  前日のデータがそのまま残る。`EXTRACT_PHASE_FAILED` も出る。#290 のフェーズ隔離により
  後続の Status / Backfill / NoteRequests も巻き添えにならない
- **観測性はむしろ上がる。** 現行は重複が来ても dedup が黙って直してしまうが、
  楽観方式なら「重複が実在した」ことが一度エラーとして表に出る

### 残る注意点

1. **フォールバック経路が本番で一度も実行されない。** 19/19 ゼロということは、dedup 再実行のコードは
   動く機会がないまま眠る。ユニットテストで実際に `IntegrityError` を起こして経路を通すこと
2. **失敗したトランザクションの後始末。** `UniqueViolation` の後、セッションは
   `InFailedSqlTransaction` になる。rollback してから dedup を走らせないと以降が全部失敗する
   （`_run_phase` のコメントに書かれている既知の罠）

## 効果の見積もり

```
ratings フェーズ  4h05m → 3h33m      （−32分）
日次 Extract 全体  7h42m → 7h10m
終了時刻          22:57 → 22:25 頃
```

## 見送った案と、その理由

### B. Python ホットループの位置ベース化（見送り。効果は最大）

`csv.DictReader` が 214M 行それぞれに 35 キーの dict を生成しており、これが CPU を支配している。
位置ベースに書き換えると **2.9倍**（本番コードを写した20万行のベンチを2者が独立に再現）。

**本番での効果は −45〜70分と推定される。** ダウンロード区間の内訳を測ると、zip 展開＋UTF-8 デコード＋
行イテレートは 214M 行換算で2.0分（346MB/s）に過ぎず、`CpuUtilized` が1コアに張り付いている以上、
2h33m の大半は csv パースとホットループである。

見送る理由は効果ではなく**変更面積**。214M 行すべての値の生成経路を書き換えるため、
dedup 楽観化（数行）とはリスクの桁が違う。A をデプロイして実績を作ってから着手する。

設計と実装プランは `docs/superpowers/plans/2026-09-14-ratings-hot-loop-and-index-build.md` に
そのまま残してある（**未着手・要改訂**）。着手時は次の指摘を反映すること:

- `TestValidateRatingRowNewFields`（8件）の削除・移植がプランから漏れている。
  未移植の3ケース（`rating_source_bucketed` の正値保持、`suggestion` / `suggestion_id` の値保持）も足す
- 新旧どちらにも「binary bool の `"1"` が `"1"` のまま出る」テストが無い。
  全 bool を `"0"` に潰すバグが全テストを通過する
- ベンチの2.9倍は**通過率100%が前提**。50%なら2.0倍、10%なら0.70倍（新実装の方が遅い）。
  本番は staging 行数＝処理行数で通過率ほぼ100%なので成立するが、row_notes のカバレッジが
  落ちる運用変更をすると前提が崩れる
- 空の TSV でフェイル挙動が変わる。現行は `reader.fieldnames` が None で TypeError → フェーズ失敗 →
  swap されず前日データ維持（フェイルセーフ）。位置ベース版は0行で続行するため、
  9本中1本が空でも89%で min_rows ガード（50%）を通過し、**約11%欠けたスナップショットが黙って swap される**
- 短い行（ragged row）の安全性が `_RATING_COLUMNS` の**列順に暗黙依存**している
  （NOT NULL の `rated_on_tweet_id` が26個の bool より後ろにあるため、bool が欠けるほど短い行は
  必ず required チェックでスキップされる）。テストかコメントで固定すること

### D. staging を最初から LOGGED でロードする（未検証）

`SET LOGGED` の40分は、staging を最初から LOGGED にすれば消える。総書き込み量はむしろ減る可能性があり
**推定 −30分**。ただし実測がなく、WAL 増によるバックアップ/レプリケーションへの影響は AWS 側の確認が要る。

なお「`row_note_ratings` を恒久 UNLOGGED にする」案は却下。RDS のフェイルオーバーで truncate され、
次の日次実行まで API の評価数が 0 になる。

### E. `maintenance_work_mem` の引き上げ（却下）

当初は「PK 構築のソートをメモリ内に収める」として1GBへの引き上げを計画したが、**根拠が成立しない**。
インデックスのソートデータ量は 215M 行 ×（note_id 約20B ＋ rater 65B ＋ タプルヘッダ）≒ **約20GB** で、
1GB にしても外部マージのままである。さらに既定の約134MB でも run 数 ≒ 160 本はマージ順序の上限を
下回るため**すでに1パスマージ**で、temp I/O の総量はほとんど変わらない。

PK 構築の20分を本気で縮めるなら `CREATE UNIQUE INDEX`（並列ビルド可）→
`ADD CONSTRAINT ... PRIMARY KEY USING INDEX` ＋ `max_parallel_maintenance_workers` の評価が筋。
ただし 2 vCPU なので上限は1.7倍程度（未検証）。

なお、dedup を残す場合の window ソートに効くのは `maintenance_work_mem` ではなく `work_mem` である。

### 増分ロード（不可能）

`ratings-00000.zip` の Content-Length は 2026-09-13 が 1,431,027,508 バイト、
2026-09-14 が 1,430,993,279 バイトだった。**同じファイル名でも日々内容が変わる**ため
「前日と同じファイルは skip」は成立しない。行単位の watermark なら可能だが、
ダウンロード（12.6GB）とパースは残る。

### `existing_row_note_ids` の SQL 化（別件）

set membership は測定上ボトルネックではない。常駐メモリの話として別途扱う。

## 成功基準

1. `Deduplicated staging table` のログが**通常日には出ないこと**
2. ratings フェーズが **4h05m から約32分短縮**されていること（`[PHASE_COMPLETE] Ratings:` の秒数）
3. `Staging table row count` が従来と同水準（214,984,620 前後）で、min_rows ガードを通過すること
4. `PK index built on staging table in <秒数>` が従来（1,184s）と大きく変わらないこと

## フォローアップ（今回の PR には含めない）

重複が実在した日を検知できるよう、`RATING_DUPLICATES_FOUND` を CloudWatch のメトリクスフィルタに
追加する（cdk の `monitoring-stack.ts` に `filterKeyword` の仕組みが既にある）。
現状このトークンは眠ったままなので、発火した事実に気付ける経路を用意しておく価値がある。
