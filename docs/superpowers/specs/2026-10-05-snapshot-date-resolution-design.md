# スナップショット日付解決の設計（issue #299）

**作成日**: 2026-10-05
**対象**: `etl/src/birdxplorer_etl/extract_ecs.py` の日次 extract
**関連**: codeforjapan/BirdXplorer#299、`docs/superpowers/specs/2026-10-01-ratings-copy-silent-loss.md`

## 解決する問題

ETL が X の公開前にデータを取りに行き、404 を踏んで**その日の更新が丸ごと飛ぶ**。

```
Ratings file 00000 not found (404), stopping ratings download for 2026/10/03
No ratings loaded, skipping table swap
[PHASE_COMPLETE] Ratings: 0.2s
```

飛ぶのは ratings だけではない。`recalculate_rating_counts` は**古い ratings に対して走り**、
noteStatusHistory も同時に 404 になることが多く `row_note_status` も更新されない。
2026-10-03 は Ratings 0.2s / Status 0.3s で、両方が空振りした。

### 原因は性能改善の副作用

Notes フェーズの所要時間が 2026-09-19 を境に 30〜108分 → 4〜12分に短縮され、
ratings に到達する時刻が約40分前倒しになった。

| 期間 | ratings 到達 | 404 の頻度 |
|---|---|---|
| 〜09-18 | 15:46〜20:54 | 16回中 **0回** |
| 09-19〜10-03（起動 15:15） | 15:19〜15:27 | 10回中 **4回** |
| 10-03〜（起動 16:30） | 16:36 | 3回中 **1回** |

### 固定スケジュールでは解決しない

起動を 15:15 → 16:30 に後ろ倒ししたが（BirdXplorer-cdk#39、デプロイ済み）、
初日の 10-03 に再び 404 を踏んだ。公開時刻の実測はこうだった。

| 日付 | ETL が叩いた時刻 | 公開を確認した時刻 |
|---|---|---|
| 10-02 | 15:21（404） | 15:45 には 200（24分以内） |
| 10-03 | 16:36（404） | 16:41 には 200（5分以内） |

**公開時刻は1日で1時間以上動く。**待ち時間自体は5〜24分と短い。
時刻をずらす対応では追いつけず、リトライが要る。

### 3種の公開時刻はずれる

2026-10-03 16:41 時点の実測。

```
2026/10/03  notes              200
2026/10/03  noteRatings        200
2026/10/03  noteStatusHistory  404   ← 16:44 時点でもまだ
2026/10/02  notes / noteRatings / noteStatusHistory  すべて 200
```

公開は notes → noteRatings → noteStatusHistory の順にずれて出る。
現在のコードは notes が取れた日付を ratings と status にも流用するため、この時間差に構造的に弱い。

### 前日フォールバックが存在しない

`extract_data` は `for days_ago in range(3)` のループを持つが、**notes が取れた時点で日付を確定**し、
その日付を全フェーズに渡して `break` する。ratings が 404 でも前日を試さない。
2026-10-02 の時点で `2026/10/01` の ratings は 200 で取得可能だったが、取りに行っていない。

### フィード自体が約2日遅れ

2026-10-02 のデータを取り込んだ時点で、`row_note_ratings` 内の最新評価は **2026-09-30 13:01 JST**。
前日へフォールバックしても、実質的に失う鮮度は1日ぶんにすぎない。

## 決定事項

| 論点 | 決定 |
|---|---|
| 成功の定義 | リトライして当日分を狙い、駄目なら前日以前へフォールバック |
| 日付の決め方 | notes / noteRatings / noteStatusHistory が**それぞれ独立に**決める |
| リトライ | 当日分のみ。10分間隔 × 最大6回（1種あたり最大1時間） |
| フォールバック | 最大3日前まで。過去日はリトライせず1回ずつ試す |
| 後退防止 | ratings で**フォールバックしたときだけ**、staging < live × 0.9995 なら swap 中止 |
| 全滅時 | 例外を投げ、既存の `EXTRACT_PHASE_FAILED` アラームに乗せる |
| cdk 変更 | 不要 |

実装中に加わった決定は「実装時に加わった決定」の節にまとめてある。

## 設計

### 日付解決の分離

「どの日付を使うか」を決める責務を切り出す。ダウンロードと処理のコードは触らない。

```python
def _probe_snapshot(kind: str, date_string: str) -> bool:
    """そのファミリーの 00000 が公開されているかを HEAD で確認する。"""

def _resolve_snapshot_date(
    kind: str,
    base: datetime,
    *,
    probe: Callable[[str, str], bool] = _probe_snapshot,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """当日→リトライ→前日→2日前→3日前 の順に解決する。全滅なら None。"""
```

`kind` は URL の階層名そのもの（`notes` / `noteRatings` / `noteStatusHistory`）。

解決の順序:

```
当日   ○ → 採用
       × → 10分待って再試行（最大6回）
            → ○ なら採用
            → 6回とも × なら前日へ
前日   ○ → 採用 / × → 2日前へ
2日前  ○ → 採用 / × → 3日前へ
3日前  ○ → 採用 / × → None
```

**リトライは当日分にだけ掛ける。**過去日は公開済みか否かが確定しており、待つ意味がない。

3種が独立に待つため、**最悪で run 全体が +3時間**伸びる（1種あたり最大1時間 × 3）。
ratings フェーズ自体が3〜4時間なので、全滅時の総実行時間は7〜8時間になる。
日次 run は 16:30 起動で、翌日の run まで24時間あるため重複はしない。
実測では待ち時間は5〜24分であり、この最悪ケースに到達するのは X の公開が1時間以上遅れた日に限られる。

`probe` と `sleep` を注入可能にするのは、テストで HTTP も実時間の待機も使わないため。

**プローブが例外を投げた場合（接続断など）はフォールバックしない。**例外をそのまま伝播させ、
そのフェーズを失敗させる。404（未公開）とネットワーク障害は別物で、後者で前日に流れると
ratings のフルスワップ込みで前日分を丸ごと再処理して1時間規模を浪費する。
既存テスト `test_fetch_failure_does_not_fall_back_to_the_previous_day` が固定している契約であり、維持する。

このため**日付解決はフェーズの内側で行う**。`_run_phase` の外で解決すると、解決中の例外が
Backfill / NoteRequests まで巻き添えにする。各フェーズは次の形になる。

```python
def _run_notes_phase(postgresql: Session, existing_row_note_ids: set, now: datetime) -> None:
    date_string = _resolve_snapshot_date("notes", now)
    if date_string is None:
        raise RuntimeError(f"SNAPSHOT_UNAVAILABLE kind=notes ...")
    _extract_notes_files(postgresql, date_string, existing_row_note_ids)
```

日付解決が不要になるため、`_extract_notes_files` の第4引数 `state`（`date_has_notes`）は削除する。
この引数を参照しているのは `extract_data` のループだけで、テストからの参照はない。

### `extract_data` の組み替え

現在の `for days_ago in range(3)` ループと `notes_state["date_has_notes"]` による分岐を廃止し、
各フェーズが自分の日付を解決してから走る形にする。

```
notes  : _resolve_snapshot_date("notes", today)              → _extract_notes_files(date)
ratings: _resolve_snapshot_date("noteRatings", today)        → extract_ratings(date)
status : _resolve_snapshot_date("noteStatusHistory", today)  → _extract_note_status_files(date)
```

各フェーズは従来どおり `_run_phase` で包む。1つが失敗しても後続は走る（既存の契約を維持）。

`existing_row_note_ids` の扱いは変えない。notes フェーズが先に走って集合を更新し、
ratings と status がそれを使う順序も維持する。

### 後退防止ガード

`row_note_ratings` は全置換なので、古いスナップショットを取り込むと**新しいデータを古いデータで上書きする**。
2026-10-05 時点の live は 10-04 の 218,398,084 行で、ここに 10-02 の 217,924,158 行を入れれば後退する。

`notes` と `noteStatusHistory` は upsert なので後退しない。ガードは ratings にのみ要る。

**フォールバックが起きたときだけ**適用する。当日分を普通に取り込んだ日は既存の `min_rows` ガードに任せる。
こうすれば通常日に許容誤差を調整する必要がなく、評価の取り下げ（実測で約1,500件）による
わずかな減少で誤って止まることもない。

```
解決した日付が当日    → 既存の min_rows ガードのみ
解決した日付が過去日  → 加えて staging_count >= live_count * 0.9995 を要求。下回れば swap 中止
```

`live_count` は `pg_class.reltuples`（既存の `min_rows` 算出で使っているもの）を流用する。

**判定に使う `staging_count` は dedup 後の値**（`_build_staging_pk_with_dedup_fallback` の戻り値）とし、
チェックは `_swap_ratings_table` を呼ぶ直前に置く。dedup が走った日に行数が減ることを織り込むため。

**許容誤差は 0.05%（`_RATINGS_BACKWARDS_SLACK = 0.9995`）。**`reltuples` は推定値なので厳密一致にはしない。
ただし広げすぎるとガードが静かに無効化される: 実測の増加率は 217,924,158 → 218,398,084（2日間）で
約 0.11%/日、最深のフォールバック（3日前）でも live 比 -0.33% にすぎない。当初 2% を置いたところ
この範囲を丸ごと吸収してしまい、**対象とするどのフォールバックに対しても発火しない状態だった**
（後退検知に約18日分のレグレッションが必要）。**1日分の増加率より広げてはいけない。**

推定値の実際の精度は実測済み: 2026-10-06 時点で swap ログの 218,556,095 行に対し `reltuples` は
218,556,096（誤差1行 = 0.0000%）。staging 側で `CREATE INDEX` と autoanalyze が走った統計が
rename でそのまま live へ引き継がれるため、`SET LOGGED` のヒープ書き換えを経ても実運用ではずれない。

### シャード終端の判定（実装時に追加）

**この節は当初の設計には無く、実装中の計測で必要になった。**

`extract_ratings` は `ratings-00000` から順に取得し、最初の 404 を終端とみなす。本設計は ETL を
X の公開窓の中心へ移動させるため、この前提が初めて到達可能になる。シャードは順不同に、
広い窓をかけて到着するためである（実測）。

```
2026/10/04  00003 06:03:11 / 00002 06:07:51 / 00000 06:18:42 / 00001 06:32:18   （29分、00000 は3番目）
2026/10/05  00008 05:54:50 / 00003 06:11:54 / 00001 06:21:55 / 00000 06:27:13 / 00002 06:42:29   （48分、00000 は4番目）
```

**`ratings-00000` の存在は、そのファミリーが揃っている証拠にならない。**欠損が50%未満なら
`min_rows` も `_verify_staging_row_count`（COPY の忠実性しか見ない）も通過し、
**部分スナップショットが無言で live に入る。**直後に `recalculate_rating_counts` がそれで全ノートを書き換える。

対策: 404 を見た時点では終端と断定せず、`k+1` と `k+2` をプローブする。

```
どちらも 404      → 真の終端。従来どおり break
いずれかが 200    → リストが未完成。待って同じ index をやり直す（最大 _SNAPSHOT_MAX_RETRIES 回）
リトライ使い切り  → RATINGS_SHARD_LISTING_INCOMPLETE で中止（部分スナップショットを swap しない）
```

ratings にのみ適用する。`notes` と `noteStatusHistory` は upsert で、部分取り込みでもデータは
破壊されず翌日の実行で追いつく。全置換するのは ratings だけである。

**既知の限界**: 先読みは2つ分なので、3つ以上連続した穴は依然として終端と誤認する
（実測で `00008` と `00003` の間に4つ分の開きがあった）。follow-up。

### ログトークン

```
SNAPSHOT_WAITING                 kind=noteRatings attempt=3/6 date=2026/10/05
SNAPSHOT_FALLBACK                kind=noteRatings requested=2026/10/05 resolved=2026/10/04
SNAPSHOT_UNAVAILABLE             kind=noteRatings tried=2026/10/05..2026/10/02
RATINGS_SHARD_LISTING_INCOMPLETE 未完成なリストを終端と誤認せず中止した（実装時に追加）
RATINGS_BACKWARDS_CHECK_SKIPPED  live の推定値が取れず後退ガードを飛ばした（実装時に追加）
RATINGS_NO_SHARDS_LOADED         1シャードも取り込めなかった（実装時に追加）
```

- `SNAPSHOT_WAITING` は、最大1時間の待機中に run が無言にならないために出す。
- `SNAPSHOT_FALLBACK` は当面アラームにしない。リトライが効けば稀になるはずで、まず頻度を観測する。
  常態化していたら後から cdk 側でメトリクスフィルタを足せる。
- `SNAPSHOT_UNAVAILABLE` は例外メッセージに含める。`_run_phase` が `EXTRACT_PHASE_FAILED` を出すので
  既存のアラームで気づける。「データ未公開」と他の失敗を後から切り分けるための識別子。

既存トークン `RATING_DUPLICATES_FOUND` / `NOTE_INSERT_CONFLICT` / `RATINGS_STAGING_COUNT_*` とは
前方一致しない命名にしてある。

## テスト

`_resolve_snapshot_date` は `probe` と `sleep` を注入してテストする。HTTP も実時間の待機も使わない。

- 当日分が最初から取れる（`sleep` が1回も呼ばれない）
- リトライ3回目で取れる（`sleep` が2回呼ばれる）
- 6回とも駄目で前日にフォールバックする
- 前日も駄目で2日前、さらに3日前まで落ちる
- 4日前は試さない（全滅して `None`）
- `SNAPSHOT_WAITING` / `SNAPSHOT_FALLBACK` / `SNAPSHOT_UNAVAILABLE` が所定の書式で出る

後退防止ガード:

- フォールバック時に `staging_count < live_count` なら swap を中止する
- フォールバック時でも `staging_count >= live_count` なら swap する
- **当日取り込み時は、`staging_count < live_count` でもこのガードは発火しない**

### 既存テストへの影響

`TestExtractDataPhaseIsolation`（`extract_ecs.py` の `days_ago` ループと `date_has_notes` の挙動を
固定している5件程度）は、ループが無くなるため作り替えが必要。今回いちばん既存テストに影響する箇所。

`TestExtractRatingsErrorRecovery` と `TestExtractRatingsSkipsDedup` は `extract_ratings` を直接呼ぶため、
日付解決の変更の影響を受けない。ただし後退防止ガードの追加で `scalar` のモックが増える点に注意
（PR #298 で `_verify_staging_row_count` を足したときに `test_cleanup_on_swap_failure` が
巻き込まれたのと同じ構造）。

## 実装時に加わった決定

当初の設計に無く、実装・レビュー中に判明して採用したもの。いずれも理由は本文の各節に記載。

| 決定 | きっかけ |
|---|---|
| シャード終端の判定を直す（上記の節） | 計測でシャードが順不同・最大48分かけて到着すると判明 |
| `probe` / `sleep` の既定値を呼び出し時に解決する | 既定値が定義時に束縛され `@patch` が効かず、テストが実ネットワークを叩き最大1時間 real sleep する状態だった |
| 当日分リトライ中の例外は再試行する | 1時間の待機中の一時的な接続断で、その日のフェーズが落ちていた。**フォールバック中の例外は従来どおり即伝播**（接続断でフォールバックしない契約は維持） |
| `requests.head` にタイムアウト | 半開きソケットで無制限に待つ、この設計で唯一縛りの無い待ち時間だった |
| 日付解決の直前に `postgresql.rollback()` | 最大1時間のスリープを開いたトランザクションの中で行うと xmin horizon が固定され autovacuum が止まる |
| Notes フェーズが失敗したら Ratings と Status を飛ばす | 書き換えで旧挙動が落ちていた。`existing_row_note_ids` に当日の新規ノートが無いまま ratings を全置換すると、その評価が `unknown_note` で捨てられ、`recalculate_rating_counts` が低い集計値を公開する |
| `total_loaded == 0` を return から raise へ | warning を出して `[PHASE_COMPLETE]` を記録しており、**本設計が消そうとしている症状そのもの**が残っていた |

### 最悪実行時間（当初の見積もりは誤り）

当初「3種 × 最大1時間 = +3時間」としたが、シャード終端の待ちが**シャードごとにリトライ枠を持つ**ため
これを超える。9シャードなら最大9時間が積みうる。ratings 自体の3〜4時間と合わせて最悪で約16時間。

実行時間に上限は無く、重複実行を防ぐ advisory lock も無い。24時間を超えた場合、次の run の
`_create_staging_table` が `DROP TABLE IF EXISTS row_note_ratings_new` を実行し、走行中のロードを壊す。
実測の待ち時間は5〜24分でありこの最悪値に到達するのは X の公開が大幅に遅れた日に限られるが、
**上限が無いこと自体が未解決**。follow-up。

## 範囲外

- 先読みが2シャードのみで、3つ以上連続した穴を終端と誤認する件（上記の既知の限界）。
- 最悪実行時間に上限が無く、重複実行に対する advisory lock が無い件（上記）。
- `extract_ecs.py` の `requests.get` の例外ハンドラが同じ index を再試行せず `file_index += 1` する件。
  新しい終端判定との相互作用が新しい: 落としたシャードは「読み込み済み」に見えるため、
  終端判定がその穴を検出できない。
- `recalculate_rating_counts` のゼロ落ちと差分ゲート化。Ratings が失敗した日も走る点を含む。
- `SNAPSHOT_FALLBACK` のアラーム化（頻度を観測してから判断する）。
