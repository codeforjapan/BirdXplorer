# ratings の dedup 楽観化 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 毎日32分かけて0行を消している dedup をやめ、PK 構築を先に試して `UniqueViolation` が出たときだけ dedup する。

**Architecture:** `_swap_ratings_table` に埋まっている PK 構築を `_build_staging_pk` に切り出し、その上に楽観リトライ層 `_build_staging_pk_with_dedup_fallback` を重ねる。`extract_ratings` は無条件の `_deduplicate_staging_table` 呼び出しをやめ、この新しい入口を呼ぶ。`_deduplicate_staging_table` 自体は一切変更せず、フォールバック経路から呼ばれるだけになる。

**Tech Stack:** Python 3.10 / SQLAlchemy 2.x（`sqlalchemy.exc.IntegrityError`）/ PostgreSQL 16.8 (RDS db.m6g.large)

**Spec:** `docs/superpowers/specs/2026-09-14-ratings-phase-cost-reduction.md`

## Global Constraints

- 行長 120 文字、Black / isort（Black プロファイル）/ pflake8（E203, E701 無視）
- Python 3.10+。型ヒントを付ける
- テストは `cd etl && .tox/py310/bin/pytest`。**`etl/.tox/py310` の black は壊れている**ので、
  フォーマッタは `common/.tox/py310/bin/{black,isort,pflake8}` を使う
- `_deduplicate_staging_table`（`extract_ecs.py:950`）の SQL は**一文字も変えない**。
  「`created_at_millis` が最新の行を残す」意味論をフォールバック経路でそのまま維持するため
- 作業ブランチは**更新済みの main から切る**（PR #290 マージ後の main）
- 出発点のテストは **56 passed**

---

### Task 0: ブランチ作成

**Files:** なし（git 操作のみ）

- [ ] **Step 1: main を最新にしてブランチを切る**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git checkout main
git pull
git checkout -b perf/ratings-optimistic-dedup
```

- [ ] **Step 2: 出発点でテストが通ることを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/ -q`
Expected: `56 passed`（失敗 0）

---

### Task 1: PK 構築を `_build_staging_pk` に切り出す（純粋な移動）

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（`_swap_ratings_table` から PK 構築部を抽出）
- Test: `etl/tests/test_extract_ratings_swap.py`（`TestSwapRatingsTable` の scalar モックを調整、`TestBuildStagingPk` を新設）

**Interfaces:**
- Consumes: `_STAGING_TABLE`（既存の定数）
- Produces: `_build_staging_pk(postgresql: Session) -> None` —
  staging table に PK 制約を張る。同名インデックスが他テーブルに残っていれば事前にリネームする。
  重複があれば `sqlalchemy.exc.IntegrityError` を送出する（これが Task 2 の分岐点になる）

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_extract_ratings_swap.py` の `class TestSwapRatingsTable` の直前に新しいクラスを足す。
冒頭の import に `_build_staging_pk` を追加すること。

```python
class TestBuildStagingPk:
    """_build_staging_pk のユニットテスト"""

    def test_adds_primary_key_constraint(self) -> None:
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = None

        _build_staging_pk(mock_session)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        assert any("ADD CONSTRAINT" in s and "PRIMARY KEY (note_id, rater_participant_id)" in s for s in sql_calls)
        mock_session.commit.assert_called_once()

    def test_renames_a_leftover_index_owned_by_another_table(self) -> None:
        """過去の swap 失敗で本番テーブルに同名 PK が残っていると、新しい PK が張れない。"""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = "row_note_ratings"

        _build_staging_pk(mock_session)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        rename_at = next(i for i, s in enumerate(sql_calls) if "RENAME TO" in s and "_pkey_old" in s)
        pk_at = next(i for i, s in enumerate(sql_calls) if "ADD CONSTRAINT" in s)
        assert rename_at < pk_at, "リネームは PK 構築より前でなければ意味がない"

    def test_does_not_rename_when_the_index_belongs_to_the_staging_table(self) -> None:
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = _STAGING_TABLE

        _build_staging_pk(mock_session)

        sql_calls = [str(c.args[0].text) for c in mock_session.execute.call_args_list]
        assert not any("_pkey_old" in s for s in sql_calls)
```

- [ ] **Step 2: テストを実行して失敗することを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/test_extract_ratings_swap.py -k BuildStagingPk -q`
Expected: FAIL（`ImportError: cannot import name '_build_staging_pk'`）

- [ ] **Step 3: `_swap_ratings_table` から PK 構築部を切り出す**

`extract_ecs.py` の `_swap_ratings_table` から、以下のブロック（`# PK構築（シーケンシャルビルド…` の
コメントから `logging.info(f"PK index built on staging table in …")` まで）を丸ごと削除し、
`_swap_ratings_table` の**直前**に新しい関数として置く。

```python
def _build_staging_pk(postgresql: Session) -> None:
    """staging table に PK を張る（シーケンシャルビルド — ランダムI/Oなし）。

    重複があると IntegrityError(UniqueViolation) を送出する。呼び出し側はこれを
    「重複が実在した」シグナルとして使う（_build_staging_pk_with_dedup_fallback）。

    過去のswapでPKリネームが失敗した場合、同名の制約が本番テーブルに残っている可能性があるため
    事前にインデックスの存在をチェックし、存在すればリネームして名前衝突を回避する。
    """
    existing_owner = postgresql.execute(
        text("SELECT tablename FROM pg_indexes " f"WHERE indexname = '{_STAGING_TABLE}_pkey'")
    ).scalar()
    if existing_owner and existing_owner != _STAGING_TABLE:
        logging.warning(
            f"PK index '{_STAGING_TABLE}_pkey' already exists on table '{existing_owner}', "
            "renaming to avoid conflict"
        )
        postgresql.execute(text(f'ALTER INDEX "{_STAGING_TABLE}_pkey" RENAME TO "{_STAGING_TABLE}_pkey_old"'))
        postgresql.commit()

    pk_start = time.time()
    postgresql.execute(
        text(
            f"ALTER TABLE {_STAGING_TABLE} ADD CONSTRAINT {_STAGING_TABLE}_pkey "
            f"PRIMARY KEY (note_id, rater_participant_id)"
        )
    )
    postgresql.commit()
    logging.info(f"PK index built on staging table in {time.time() - pk_start:.1f}s")
```

`_swap_ratings_table` は min_rows チェックの直後から `SET LOGGED` に続く形になる。
docstring も実態に合わせる。

```python
def _swap_ratings_table(postgresql: Session, min_rows: int, staging_count: int) -> None:
    """PK 構築済みの staging table を本番テーブルとアトミックにswapする。

    PK は呼び出し前に _build_staging_pk で張っておくこと。
    """
    # 最低行数チェック（不完全スナップショット防止）
    if staging_count < min_rows:
        raise RuntimeError(
            f"Staging table has {staging_count} rows, expected at least {min_rows}. "
            "Aborting swap to prevent data loss from incomplete snapshot."
        )
    logging.info(f"Staging table row count: {staging_count} (minimum: {min_rows})")

    # UNLOGGED → LOGGED に変換（crash safety確保）
    logged_start = time.time()
    ...
```

- [ ] **Step 4: `extract_ratings` に `_build_staging_pk` の呼び出しを足す**

この時点では**挙動を変えない**（dedup は従来どおり無条件に走る）。
`_swap_ratings_table(...)` の直前に1行足すだけ。

```python
        _build_staging_pk(postgresql)
        _swap_ratings_table(postgresql, min_rows=min_rows, staging_count=staging_count)
```

- [ ] **Step 5: 既存の `_swap_ratings_table` テストを新しい責務に合わせる**

`TestSwapRatingsTable` の2つのテストは、`scalar()` の side_effect に
「PK衝突チェック」ぶんを含めている。PK 構築が外に出たので、その1件目を取り除く。

`test_succeeds_when_above_min_rows` と `test_swap_sql_sequence` の両方で、次のように変える。

```python
        # scalar()呼び出し順: 旧PK名, 新PK名（PK衝突チェックは _build_staging_pk へ移動した）
        mock_session.execute.return_value.scalar.side_effect = [
            "row_note_ratings_pkey",  # 旧テーブルのPK名
            "row_note_ratings_new_pkey",  # 新テーブルのPK名
        ]
```

`test_swap_sql_sequence` の `assert any("ADD CONSTRAINT" in s and "PRIMARY KEY" in s for s in sql_calls)`
の行は削除する（PK 構築はもうこの関数の責務ではない）。代わりに次を足す。

```python
        assert not any("ADD CONSTRAINT" in s for s in sql_calls), "PK 構築は _build_staging_pk の責務"
```

- [ ] **Step 6: テストが通ることを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/ -q`
Expected: PASS（56 + 新規3 = 59 passed）

- [ ] **Step 7: 移動が忠実であることを確認**

Run:
```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git diff -U0 etl/src/birdxplorer_etl/extract_ecs.py | grep '^[-+]' | grep -v '^[-+][-+]' | sort | uniq -c | sort -rn | head -30
```
Expected: 追加行と削除行が対応していること（関数定義・docstring・`_build_staging_pk(postgresql)` の
呼び出し行以外は、同じ行が `-` と `+` の両方に現れる）

- [ ] **Step 8: フォーマット・lint してコミット**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
../common/.tox/py310/bin/black . -q && ../common/.tox/py310/bin/isort . -q && ../common/.tox/py310/bin/pflake8 src/ tests/
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "refactor(etl): ratings の PK 構築を _build_staging_pk に切り出す

挙動は変えない。次のコミットで PK 構築を dedup より先に試せるようにするための準備。
swap の責務は SET LOGGED と RENAME に絞る。"
```

---

### Task 2: dedup を楽観化する

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（import に `IntegrityError`、新関数、`extract_ratings` の呼び出し）
- Test: `etl/tests/test_extract_ratings_swap.py`（`TestOptimisticDedup` を新設）

**Interfaces:**
- Consumes: `_build_staging_pk`（Task 1）、`_deduplicate_staging_table`（既存・無変更）
- Produces: `_build_staging_pk_with_dedup_fallback(postgresql: Session, staging_count: int) -> int` —
  PK 構築を試し、`IntegrityError` が出たときだけ rollback → dedup → 再構築する。
  戻り値は dedup で削除した行数を差し引いた staging の行数（min_rows チェックに使う）

- [ ] **Step 1: 失敗するテストを書く**

冒頭の import に `_build_staging_pk_with_dedup_fallback` を追加する。
`from sqlalchemy.exc import IntegrityError` もテストファイルに追加する。

```python
class TestOptimisticDedup:
    """_build_staging_pk_with_dedup_fallback のユニットテスト

    過去30日の dedup 19回はすべて removed 0 rows だった。32分かけて0行を消すのをやめ、
    PK 構築を先に試して重複が実在したときだけ dedup する。
    """

    def _integrity_error(self) -> IntegrityError:
        return IntegrityError("ALTER TABLE ...", {}, Exception("duplicate key value violates unique constraint"))

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_skips_dedup_when_there_are_no_duplicates(
        self, mock_build: MagicMock, mock_dedup: MagicMock
    ) -> None:
        """通常日(重複0)は dedup を一度も呼ばない。これが 32分/日 の削減そのもの。"""
        mock_session = MagicMock()

        result = _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert result == 1000
        mock_build.assert_called_once()
        mock_dedup.assert_not_called()
        mock_session.rollback.assert_not_called()

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_deduplicates_and_retries_when_duplicates_exist(
        self, mock_build: MagicMock, mock_dedup: MagicMock
    ) -> None:
        """重複があれば dedup して作り直す。行数は削除ぶんを差し引く。"""
        mock_session = MagicMock()
        mock_build.side_effect = [self._integrity_error(), None]
        mock_dedup.return_value = 7

        result = _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert result == 993, "min_rows チェックに使う行数から削除ぶんを引いていない"
        assert mock_build.call_count == 2
        mock_dedup.assert_called_once()

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_rolls_back_before_deduplicating(self, mock_build: MagicMock, mock_dedup: MagicMock) -> None:
        """UniqueViolation 後のセッションは InFailedSqlTransaction。

        rollback せずに dedup を投げると以降が全部失敗する(_run_phase のコメントにある既知の罠)。
        """
        mock_session = MagicMock()
        order: list = []
        mock_session.rollback.side_effect = lambda: order.append("rollback")
        mock_dedup.side_effect = lambda _session: order.append("dedup") or 0
        mock_build.side_effect = [self._integrity_error(), None]

        _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert order == ["rollback", "dedup"], f"rollback が dedup より前にない: {order}"

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_logs_an_alarm_token_when_duplicates_exist(
        self, mock_build: MagicMock, mock_dedup: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """重複は19日間一度も起きていない。起きたら気付けるようトークンを出す。"""
        mock_session = MagicMock()
        mock_build.side_effect = [self._integrity_error(), None]
        mock_dedup.return_value = 3

        with caplog.at_level(logging.WARNING):
            _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert "RATING_DUPLICATES_FOUND" in caplog.text
        assert "3" in caplog.text

    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk")
    def test_propagates_when_the_retry_also_fails(self, mock_build: MagicMock, mock_dedup: MagicMock) -> None:
        """dedup 後も落ちるなら諦めて例外を投げる。無限ループやリトライの繰り返しをしない。

        フェーズは失敗するが swap されないので前日のデータが残る(フェイルセーフ)。
        """
        mock_session = MagicMock()
        mock_build.side_effect = [self._integrity_error(), self._integrity_error()]
        mock_dedup.return_value = 0

        with pytest.raises(IntegrityError):
            _build_staging_pk_with_dedup_fallback(mock_session, staging_count=1000)

        assert mock_build.call_count == 2


class TestExtractRatingsSkipsDedup:
    """extract_ratings が無条件 dedup を呼ばなくなったことの確認"""

    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._swap_ratings_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk_with_dedup_fallback")
    @patch("birdxplorer_etl.extract_ecs._deduplicate_staging_table")
    @patch("birdxplorer_etl.extract_ecs._process_rating_rows")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_does_not_call_deduplicate_directly(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_process: MagicMock,
        mock_dedup: MagicMock,
        mock_fallback: MagicMock,
        mock_swap: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            response = MagicMock()
            response.status_code = 200
            response.content = b"noteId\traterParticipantId\n"
            mock_requests.get.return_value = response
            mock_process.return_value = 1000
            mock_fallback.return_value = 1000

            mock_session = MagicMock()
            mock_session.execute.return_value.scalar.return_value = 1000

            extract_ratings(mock_session, "2026/09/14", {"n1"})
        finally:
            settings.USE_DUMMY_DATA = original

        # dedup は fallback 経路からしか呼ばれない
        mock_dedup.assert_not_called()
        mock_fallback.assert_called_once()
        mock_swap.assert_called_once()
```

- [ ] **Step 2: テストを実行して失敗することを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/test_extract_ratings_swap.py -k "OptimisticDedup or SkipsDedup" -q`
Expected: FAIL（`ImportError: cannot import name '_build_staging_pk_with_dedup_fallback'`）

- [ ] **Step 3: import を足す**

`extract_ecs.py` の import 群（`from sqlalchemy import ...` の隣）に追加する。

```python
from sqlalchemy.exc import IntegrityError
```

- [ ] **Step 4: 楽観リトライ層を実装する**

`_build_staging_pk` の直後に置く。

```python
def _build_staging_pk_with_dedup_fallback(postgresql: Session, staging_count: int) -> int:
    """PK 構築を先に試し、重複が実在したときだけ dedup して作り直す。

    dedup(_deduplicate_staging_table)は 215M 行を全件ソートするので32分かかる。
    過去30日の19回はすべて removed 0 rows だった。毎日0行のために32分払う代わりに、
    PK 構築を先に投げて UniqueViolation が出たときだけ払う。

    重複が出た日は失敗した PK 構築ぶん(約20分)を余計に払うが、ALTER TABLE の失敗は
    ロールバックされるだけで staging table は無傷なので、やり直せる。

    戻り値は min_rows チェックに使う行数(dedup で削除したぶんを差し引いたもの)。
    """
    try:
        _build_staging_pk(postgresql)
        return staging_count
    except IntegrityError:
        # UniqueViolation 後のセッションは InFailedSqlTransaction のままなので、
        # rollback してからでないと dedup の DELETE も落ちる。
        postgresql.rollback()
        dedup_start = time.time()
        deleted = _deduplicate_staging_table(postgresql)
        logging.warning(
            f"RATING_DUPLICATES_FOUND removed={deleted} elapsed={time.time() - dedup_start:.1f}s "
            "PK build failed on duplicates; deduplicated and rebuilding"
        )
        _build_staging_pk(postgresql)
        return staging_count - deleted
```

- [ ] **Step 5: `extract_ratings` から無条件 dedup を外す**

`if total_loaded == 0:` のブロックの直後、`# 重複排除` から
`_swap_ratings_table(...)` までを次のように書き換える。

```python
        # 安全チェック + PK構築 + swap
        # dedup は PK 構築が UniqueViolation で落ちたときだけ走る(_build_staging_pk_with_dedup_fallback)
        staging_count = _build_staging_pk_with_dedup_fallback(postgresql, total_loaded)
        # 最低行数: 現在テーブルの推定行数の50%（COUNT(*)はタイムアウトするのでreltuples使用）
        # reltuples はANALYZE未実行時に-1を返すため、その場合はstaging_countの50%をフォールバックとして使用
        current_count = (
            postgresql.execute(
                text(
                    "SELECT reltuples::bigint FROM pg_class "
                    "WHERE relname='row_note_ratings' AND relnamespace = current_schema()::regnamespace"
                )
            ).scalar()
            or 0
        )
        if current_count <= 0:
            current_count = staging_count
        min_rows = max(int(current_count * 0.5), 1)
        _swap_ratings_table(postgresql, min_rows=min_rows, staging_count=staging_count)
```

Task 1 Step 4 で足した `_build_staging_pk(postgresql)` の行は削除する（fallback 側が呼ぶため）。

- [ ] **Step 6: テストが通ることを確認**

Run: `cd etl && .tox/py310/bin/pytest tests/ -q`
Expected: PASS（59 + 新規6 = 65 passed）

- [ ] **Step 7: dedup の SQL に手が入っていないことを確認**

Run: `git diff main -- etl/src/birdxplorer_etl/extract_ecs.py | grep -A5 "ROW_NUMBER"`
Expected: 何も出ない（`_deduplicate_staging_table` は無変更）

- [ ] **Step 8: フォーマット・lint してコミット**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
../common/.tox/py310/bin/black . -q && ../common/.tox/py310/bin/isort . -q && ../common/.tox/py310/bin/pflake8 src/ tests/
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "perf(etl): ratings の dedup を楽観化して日次32分を削る

_deduplicate_staging_table は 215M 行を全件ソートするので32分かかる。
過去30日の実行19回はすべて removed 0 duplicate rows だった(CloudWatch Logs)。
毎日0行のために32分払うのをやめ、PK 構築を先に投げて UniqueViolation が
出たときだけ dedup する。

重複が出た日は失敗した PK 構築ぶん(約20分)を余計に払うが、ALTER TABLE の失敗は
ロールバックされるだけで staging table は無傷。dedup 後も落ちる場合は例外を投げ、
ratings フェーズが失敗して swap されない(=前日のデータが残る)。

重複が実在した日に気付けるよう RATING_DUPLICATES_FOUND を出す。"
```

---

### Task 3: PR 作成とデプロイ後の検証

**Files:** なし（運用手順）

- [ ] **Step 1: push と PR 作成の前に、人間の確認を取る**

**PR を作った時点で CI が dev（実質本番）にデプロイする。** 勝手に作らないこと。
push と PR 作成はそれぞれ別に確認を取る。

- [ ] **Step 2: PR 本文に入れる内容**

- 過去30日の dedup 19回すべてが `removed 0 duplicate rows` だった事実（これが唯一の根拠）
- 重複が出た日のコスト（+20分）と、失敗してもフェイルセーフであること
- `RATING_DUPLICATES_FOUND` を出すこと。**まだ CloudWatch のアラームには繋いでいない**ので、
  cdk 側でメトリクスフィルタを足すフォローアップが要ること
- 検証計画（下記 Step 3）

- [ ] **Step 3: デプロイ後、翌日の日次実行で4点を確認する**

日次 Extract は毎日 15:15 JST 開始。ratings フェーズは 20:00 JST 頃までに終わる。

```bash
LG=dev-bird-xplorer-etlExtractLogGroup
ST=$(aws logs describe-log-streams --profile birdxplorer --log-group-name "$LG" \
  --order-by LastEventTime --descending --max-items 1 \
  --query 'logStreams[0].logStreamName' --output text | head -1)

aws logs filter-log-events --profile birdxplorer --log-group-name "$LG" --log-stream-names "$ST" \
  --filter-pattern '?"Deduplicated staging table" ?"RATING_DUPLICATES_FOUND" ?"PK index built" ?"Staging table row count" ?"PHASE_COMPLETE] Ratings"' \
  --output json | python3 -c "
import sys, json, datetime
for e in json.load(sys.stdin)['events']:
    print(datetime.datetime.fromtimestamp(e['timestamp']/1000).strftime('%H:%M:%S'), e['message'].strip()[:100])
"
```

確認する4点:

1. `Deduplicated staging table` が**出ていないこと**（出ていたら重複が実在した日。
   `RATING_DUPLICATES_FOUND` も出ているはずなので、その removed 件数を見る）
2. `[PHASE_COMPLETE] Ratings:` が **14,697s から約1,900s 短縮**されていること（3h33m 前後）
3. `Staging table row count` が 214,984,620 前後で、min_rows を上回っていること
4. `PK index built on staging table in <秒数>` が従来（1,184s）と大きく変わらないこと

- [ ] **Step 4: 行数が大きく減っていたら即座にロールバックする**

3 が従来の9割を下回る場合、min_rows ガード（従来の約44%）は通ってしまうので**人間が数字を見て判断する**。
ロールバックは該当コミットの revert → PR → デプロイ。

- [ ] **Step 5: フォローアップを起票する**

`RATING_DUPLICATES_FOUND` を cdk の `monitoring-stack.ts` にメトリクスフィルタとして追加する
（`filterKeyword` の仕組みが既にある。`NOTE_REQUEST_ROW_SKIPPED` が同じ形）。
このトークンは通常眠ったままなので、発火に気付ける経路が無いと意味がない。
