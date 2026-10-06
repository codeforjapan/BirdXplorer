# スナップショット日付解決 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** X の公開前に取りに行って 404 を踏み、1日分の更新が丸ごと飛ぶのをやめる。当日分をリトライで待ち、駄目なら過去日へフォールバックする。

**Architecture:** 「どの日付のスナップショットを使うか」を決める責務を `_resolve_snapshot_date` に切り出し、notes / noteRatings / noteStatusHistory が各自で解決する。解決はフェーズの内側で行い、接続断は例外としてそのフェーズだけを失敗させる。ratings は全置換なので、フォールバックした日に限り「現在の live より行数が少なければ swap しない」後退防止ガードを足す。

**Tech Stack:** Python 3.10 / requests / SQLAlchemy 2.0（psycopg2 ドライバ明示）/ pytest / PostgreSQL 16

**Spec:** `docs/superpowers/specs/2026-10-05-snapshot-date-resolution-design.md`

## Global Constraints

- 行長 120 文字。Black / isort（Black プロファイル）/ pflake8（E203, E701 無視）。
- 接続 URL のドライバ指定 `postgresql+psycopg2://` を変更しない。
- `sqlalchemy` は `<2.1` 固定を維持する。
- 既存のログトークン `RATING_DUPLICATES_FOUND` / `NOTE_INSERT_CONFLICT` / `EXTRACT_PHASE_FAILED` / `RATINGS_STAGING_COUNT_VERIFIED` / `RATINGS_STAGING_COUNT_MISMATCH` / `RATINGS_FILE_ROWS` の文言を変更しない（CloudWatch のメトリクスフィルタが参照している）。
- 新規トークンは `SNAPSHOT_WAITING` / `SNAPSHOT_FALLBACK` / `SNAPSHOT_UNAVAILABLE` の3つのみ。既存トークンと前方一致しないこと。
- リトライ定数: 間隔 600秒、最大6回（初回プローブ＋6回のリトライ＝最大7プローブ・最大60分）。フォールバックは最大3日前まで。
- コミットメッセージに `Co-Authored-By` 行を付けない。
- テスト実行は `cd etl && .tox/py310/bin/pytest`（pytest は PATH に無い）。
- `.tox/py310` の black/isort/pflake8 は `mypy_extensions` 欠落で起動しない。実行しないこと。整形は目視で合わせる。

## Review Focus

仕様が前提にしているが、素では触らない入力・失敗モード。各行に対応するテストを担当タスクに組み込んである。

1. **プローブが例外を投げる（接続断）** — フォールバックせず伝播し、そのフェーズだけが失敗すること（Task 1・Task 2）。
2. **当日分が最初から公開済み** — `sleep` が1回も呼ばれないこと。常に待つ実装になっていないことの確認（Task 1）。
3. **ratings だけ公開され status は未公開** — 3種が独立に解決し、片方だけ過去日になり得ること（Task 2）。
4. **フォールバックしていない通常日に staging が live を下回る** — 後退防止ガードが発火しないこと。評価の取り下げによる微減で日次処理を止めない（Task 3）。
5. **日付解決が全滅したフェーズがあっても Backfill / NoteRequests は走る** — 既存のフェーズ隔離契約（Task 2）。

---

### Task 1: 日付解決の切り出し

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（`extract_data` の直前に追加）
- Test: `etl/tests/test_extract_ratings_swap.py`（新規クラスを追加）

**Interfaces:**
- Consumes: なし
- Produces:
  - `_SNAPSHOT_FIRST_FILE: dict[str, str]` — kind → 00000 のファイル名
  - `_SNAPSHOT_RETRY_INTERVAL_SECONDS = 600` / `_SNAPSHOT_MAX_RETRIES = 6` / `_SNAPSHOT_MAX_FALLBACK_DAYS = 3`
  - `_probe_snapshot(kind: str, date_string: str) -> bool`
  - `_resolve_snapshot_date(kind, base, *, probe=_probe_snapshot, sleep=time.sleep) -> Optional[str]`

- [ ] **Step 1: 失敗するテストを書く**

`etl/tests/test_extract_ratings_swap.py` の末尾に追加する。

```python
class TestResolveSnapshotDate:
    """日付解決のユニットテスト。HTTP も実時間の待機も使わない。"""

    BASE = datetime(2026, 10, 5, 16, 30, 0)

    def _recorder(self, results):
        """results の順に返すプローブと、呼ばれた回数を数える sleep を返す。"""
        calls = []
        slept = []

        def probe(kind, date_string):
            calls.append((kind, date_string))
            return results[len(calls) - 1]

        def sleep(seconds):
            slept.append(seconds)

        return probe, sleep, calls, slept

    def test_today_available_on_first_probe(self) -> None:
        probe, sleep, calls, slept = self._recorder([True])
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got == "2026/10/05"
        assert len(calls) == 1
        assert slept == [], "公開済みなのに待機している"

    def test_today_available_on_third_probe(self) -> None:
        probe, sleep, calls, slept = self._recorder([False, False, True])
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got == "2026/10/05"
        assert len(calls) == 3
        assert slept == [600, 600]

    def test_falls_back_to_yesterday_after_all_retries(self) -> None:
        # 当日は初回＋6回のリトライで計7回すべて False、翌の候補(前日)で True
        probe, sleep, calls, slept = self._recorder([False] * 7 + [True])
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got == "2026/10/04"
        assert len(slept) == 6, "リトライ回数が 6 ではない"
        assert calls[-1] == ("noteRatings", "2026/10/04")

    def test_falls_back_up_to_three_days(self) -> None:
        probe, sleep, calls, slept = self._recorder([False] * 7 + [False, False, True])
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got == "2026/10/02"

    def test_returns_none_when_nothing_is_available(self) -> None:
        probe, sleep, calls, slept = self._recorder([False] * 10)
        got = _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert got is None
        assert len(calls) == 10, "4日前まで試している、または3日前を試していない"

    def test_probe_exception_propagates_without_falling_back(self) -> None:
        """接続断でフォールバックすると前日分を丸ごと再処理して1時間規模を浪費する。"""
        calls = []

        def probe(kind, date_string):
            calls.append(date_string)
            raise OSError("Connection reset by peer")

        with pytest.raises(OSError):
            _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=lambda s: None)
        assert len(calls) == 1, "例外のあとも別の日付を試している"

    def test_logs_waiting_fallback_and_unavailable(self, caplog: pytest.LogCaptureFixture) -> None:
        probe, sleep, _, _ = self._recorder([False] * 7 + [True])
        with caplog.at_level(logging.INFO):
            _resolve_snapshot_date("noteRatings", self.BASE, probe=probe, sleep=sleep)
        assert "SNAPSHOT_WAITING kind=noteRatings attempt=1/6 date=2026/10/05" in caplog.text
        assert "SNAPSHOT_FALLBACK kind=noteRatings requested=2026/10/05 resolved=2026/10/04" in caplog.text

        probe2, sleep2, _, _ = self._recorder([False] * 10)
        with caplog.at_level(logging.INFO):
            _resolve_snapshot_date("notes", self.BASE, probe=probe2, sleep=sleep2)
        assert "SNAPSHOT_UNAVAILABLE kind=notes tried=2026/10/05..2026/10/02" in caplog.text


class TestProbeSnapshot:
    def test_builds_the_expected_url_and_returns_true_on_200(self) -> None:
        with patch("birdxplorer_etl.extract_ecs.requests") as mock_requests:
            mock_requests.head.return_value = MagicMock(status_code=200)
            assert _probe_snapshot("noteRatings", "2026/10/05") is True
        url = mock_requests.head.call_args[0][0]
        assert url == (
            "https://ton.twimg.com/birdwatch-public-data/2026/10/05/noteRatings/ratings-00000.zip"
        )

    def test_returns_false_on_404(self) -> None:
        with patch("birdxplorer_etl.extract_ecs.requests") as mock_requests:
            mock_requests.head.return_value = MagicMock(status_code=404)
            assert _probe_snapshot("notes", "2026/10/05") is False

    def test_knows_all_three_families(self) -> None:
        assert _SNAPSHOT_FIRST_FILE == {
            "notes": "notes-00000.zip",
            "noteRatings": "ratings-00000.zip",
            "noteStatusHistory": "noteStatusHistory-00000.zip",
        }
```

テストファイル先頭に次を追加する（Task 2 のテストで `timedelta` も使う）。

```python
from datetime import datetime, timedelta
```

`extract_ecs` からの import には `_SNAPSHOT_FIRST_FILE`, `_probe_snapshot`, `_resolve_snapshot_date` を足す
（アルファベット順を保つこと。isort が並べ替える位置に合わせる）。

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
.tox/py310/bin/pytest tests/test_extract_ratings_swap.py::TestResolveSnapshotDate -v
```

期待: FAIL（`ImportError: cannot import name '_resolve_snapshot_date'`）。

- [ ] **Step 3: 最小の実装を書く**

`extract_data` の定義の直前に追加する。必要な import（`time` / `datetime` / `timedelta` /
`Callable` / `Optional` / `requests`）は `extract_ecs.py:1-21` にすべて既にある。追加は不要。

```python
# 各ファミリーの先頭ファイル。公開済みかの判定はこれ1つの HEAD で足りる。
_SNAPSHOT_FIRST_FILE = {
    "notes": "notes-00000.zip",
    "noteRatings": "ratings-00000.zip",
    "noteStatusHistory": "noteStatusHistory-00000.zip",
}
_SNAPSHOT_RETRY_INTERVAL_SECONDS = 600
_SNAPSHOT_MAX_RETRIES = 6
_SNAPSHOT_MAX_FALLBACK_DAYS = 3


def _probe_snapshot(kind: str, date_string: str) -> bool:
    """そのファミリーの 00000 が公開されているかを HEAD で確認する。

    例外は握りつぶさない。404(未公開)とネットワーク障害は別物で、後者で前日に流れると
    ratings のフルスワップ込みで前日分を丸ごと再処理して1時間規模を浪費する。
    """
    url = (
        f"https://ton.twimg.com/birdwatch-public-data/{date_string}/{kind}/{_SNAPSHOT_FIRST_FILE[kind]}"
    )
    return requests.head(url).status_code == 200


def _resolve_snapshot_date(
    kind: str,
    base: datetime,
    *,
    probe: Callable[[str, str], bool] = _probe_snapshot,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[str]:
    """当日→リトライ→過去日 の順にスナップショットの日付を解決する。全滅なら None。

    リトライは当日分にだけ掛ける。過去日は公開済みか否かが確定しており、待つ意味がない。
    """
    today = base.strftime("%Y/%m/%d")
    if probe(kind, today):
        return today
    for attempt in range(1, _SNAPSHOT_MAX_RETRIES + 1):
        logging.info(f"SNAPSHOT_WAITING kind={kind} attempt={attempt}/{_SNAPSHOT_MAX_RETRIES} date={today}")
        sleep(_SNAPSHOT_RETRY_INTERVAL_SECONDS)
        if probe(kind, today):
            return today

    for days_ago in range(1, _SNAPSHOT_MAX_FALLBACK_DAYS + 1):
        candidate = (base - timedelta(days=days_ago)).strftime("%Y/%m/%d")
        if probe(kind, candidate):
            logging.warning(f"SNAPSHOT_FALLBACK kind={kind} requested={today} resolved={candidate}")
            return candidate

    oldest = (base - timedelta(days=_SNAPSHOT_MAX_FALLBACK_DAYS)).strftime("%Y/%m/%d")
    logging.error(f"SNAPSHOT_UNAVAILABLE kind={kind} tried={today}..{oldest}")
    return None
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
.tox/py310/bin/pytest tests/test_extract_ratings_swap.py -v
```

期待: 新規10件を含め全て PASS。既存テストはこの時点では1件も壊れない（`extract_data` を変えていないため）。

- [ ] **Step 5: コミットする**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "feat(etl): スナップショット日付の解決をリトライ付きで切り出す

当日分を10分間隔で最大6回待ち、駄目なら最大3日前まで遡る。
接続断はフォールバックせず伝播させる。"
```

---

### Task 2: `extract_data` を3種独立の解決に組み替える

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（`extract_data` と `_extract_notes_files`）
- Test: `etl/tests/test_extract_ratings_swap.py`（`TestExtractDataPhaseIsolation` の作り替え）

**Interfaces:**
- Consumes: Task 1 の `_resolve_snapshot_date(kind, base, *, probe, sleep) -> Optional[str]`
- Produces:
  - `_run_notes_phase(postgresql, existing_row_note_ids, now) -> None`
  - `_run_ratings_phase(postgresql, existing_row_note_ids, now) -> None`
  - `_run_status_phase(postgresql, existing_row_note_ids, now) -> None`
  - `extract_ratings(postgresql, dateString, existing_row_note_ids, *, is_fallback: bool = False)`
  - `_extract_notes_files(postgresql, dateString, existing_row_note_ids) -> None`（第4引数 `state` を削除）

- [ ] **Step 1: 失敗するテストを書く**

既存の `TestExtractDataPhaseIsolation` の末尾2件（`test_fetch_failure_does_not_fall_back_to_the_previous_day` と
`test_404_still_falls_back_to_the_previous_day`）を**削除し**、以下に置き換える。
同クラスの前4件（ratings / notes / status の失敗がフェーズ隔離されることを確認するもの）は残す。

```python
    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs._extract_note_status_files")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._extract_notes_files")
    @patch("birdxplorer_etl.extract_ecs._resolve_snapshot_date")
    def test_each_family_resolves_its_own_date(
        self,
        mock_resolve: MagicMock,
        mock_notes: MagicMock,
        mock_ratings: MagicMock,
        mock_status: MagicMock,
        mock_recalc: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
    ) -> None:
        """ratings だけ当日、status は前日、という混在が起き得ること。"""
        mock_resolve.side_effect = lambda kind, base: {
            "notes": "2026/10/05",
            "noteRatings": "2026/10/05",
            "noteStatusHistory": "2026/10/04",
        }[kind]

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        extract_data(mock_session)

        assert mock_notes.call_args[0][1] == "2026/10/05"
        assert mock_ratings.call_args[0][1] == "2026/10/05"
        assert mock_status.call_args[0][1] == "2026/10/04"
        assert mock_ratings.call_args.kwargs["is_fallback"] is False

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs._extract_note_status_files")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._extract_notes_files")
    @patch("birdxplorer_etl.extract_ecs._resolve_snapshot_date")
    def test_marks_is_fallback_when_ratings_date_is_not_today(
        self,
        mock_resolve: MagicMock,
        mock_notes: MagicMock,
        mock_ratings: MagicMock,
        mock_status: MagicMock,
        mock_recalc: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
    ) -> None:
        today = datetime.now().strftime("%Y/%m/%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
        mock_resolve.side_effect = lambda kind, base: yesterday if kind == "noteRatings" else today

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        extract_data(mock_session)

        assert mock_ratings.call_args.kwargs["is_fallback"] is True

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs._extract_note_status_files")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._extract_notes_files")
    @patch("birdxplorer_etl.extract_ecs._resolve_snapshot_date")
    def test_unavailable_family_fails_only_its_own_phase(
        self,
        mock_resolve: MagicMock,
        mock_notes: MagicMock,
        mock_ratings: MagicMock,
        mock_status: MagicMock,
        mock_recalc: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ratings が全滅しても Backfill / NoteRequests は走ること。"""
        mock_resolve.side_effect = lambda kind, base: None if kind == "noteRatings" else "2026/10/05"

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        with caplog.at_level(logging.INFO):
            extract_data(mock_session)

        mock_ratings.assert_not_called()
        assert "EXTRACT_PHASE_FAILED" in caplog.text
        assert "phase=Ratings" in caplog.text
        mock_notes.assert_called_once()
        mock_status.assert_called_once()
        mock_backfill.assert_called_once()
        mock_note_requests.assert_called_once()

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs._extract_note_status_files")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._extract_notes_files")
    @patch("birdxplorer_etl.extract_ecs._probe_snapshot")
    def test_probe_connection_error_fails_the_phase_without_falling_back(
        self,
        mock_probe: MagicMock,
        mock_notes: MagicMock,
        mock_ratings: MagicMock,
        mock_status: MagicMock,
        mock_recalc: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """接続断は前日へ流さず、そのフェーズを失敗させる（既存契約の維持）。"""
        mock_probe.side_effect = OSError("Connection reset by peer")

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        with caplog.at_level(logging.INFO):
            extract_data(mock_session)

        assert mock_probe.call_count == 3, "1フェーズあたり1回を超えて試している"
        mock_notes.assert_not_called()
        mock_ratings.assert_not_called()
        assert "EXTRACT_PHASE_FAILED" in caplog.text
        mock_backfill.assert_called_once()
        mock_note_requests.assert_called_once()
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
.tox/py310/bin/pytest tests/test_extract_ratings_swap.py::TestExtractDataPhaseIsolation -v
```

期待: 新規4件が FAIL（`_resolve_snapshot_date` が `extract_data` から呼ばれていない、`is_fallback` が渡っていない）。

- [ ] **Step 3: 最小の実装を書く**

`_extract_notes_files` の第4引数 `state` と、その代入箇所（`state["date_has_notes"] = True`）を削除し、
docstring から `state` の説明を落とす。

`extract_data` を次の形に置き換える（`for days_ago in range(3)` のループごと差し替える）。

```python
def _run_notes_phase(postgresql: Session, existing_row_note_ids: set, now: datetime) -> None:
    date_string = _resolve_snapshot_date("notes", now)
    if date_string is None:
        raise RuntimeError("SNAPSHOT_UNAVAILABLE kind=notes")
    _extract_notes_files(postgresql, date_string, existing_row_note_ids)


def _run_ratings_phase(postgresql: Session, existing_row_note_ids: set, now: datetime) -> None:
    date_string = _resolve_snapshot_date("noteRatings", now)
    if date_string is None:
        raise RuntimeError("SNAPSHOT_UNAVAILABLE kind=noteRatings")
    is_fallback = date_string != now.strftime("%Y/%m/%d")
    extract_ratings(postgresql, date_string, existing_row_note_ids, is_fallback=is_fallback)


def _run_status_phase(postgresql: Session, existing_row_note_ids: set, now: datetime) -> None:
    date_string = _resolve_snapshot_date("noteStatusHistory", now)
    if date_string is None:
        raise RuntimeError("SNAPSHOT_UNAVAILABLE kind=noteStatusHistory")
    _extract_note_status_files(postgresql, date_string, existing_row_note_ids)


def extract_data(postgresql: Session):
    logging.info("Downloading community notes data")

    # 既存のrow_notesのnote_idをメモリに読み込み（1行ずつのDBクエリを削減）
    existing_row_note_ids = set(r[0] for r in postgresql.query(RowNoteRecord.note_id).all())
    logging.info(f"Loaded {len(existing_row_note_ids)} existing note IDs from row_notes")

    now = datetime.now()

    # 日付解決はフェーズの内側で行う。_run_phase の外で解決すると、解決中の例外が
    # Backfill / NoteRequests まで巻き添えにする。
    _run_phase("Notes", postgresql, lambda: _run_notes_phase(postgresql, existing_row_note_ids, now))

    # 評価データを取得して保存（noteStatus処理より先に実行することで集計タイミングを保証）
    _run_phase("Ratings", postgresql, lambda: _run_ratings_phase(postgresql, existing_row_note_ids, now))

    # notesテーブルの評価集計カラムを再計算
    _run_phase("Rating recalculation", postgresql, lambda: recalculate_rating_counts(postgresql))

    _run_phase("Status", postgresql, lambda: _run_status_phase(postgresql, existing_row_note_ids, now))

    postgresql.commit()

    # row_notesにあるがnotesにないレコードをバックフィル
    _run_phase("Backfill", postgresql, lambda: backfill_missing_notes(postgresql))

    # Note Requests (batSignals) の取り込みと投稿 lookup の enqueue
    _run_phase("NoteRequests", postgresql, lambda: run_note_requests_phase(postgresql))
```

`extract_ratings` のシグネチャに `*, is_fallback: bool = False` を足す。この時点では受け取るだけで使わない
（Task 3 で使う）。

```python
def extract_ratings(
    postgresql: Session, dateString: str, existing_row_note_ids: set, *, is_fallback: bool = False
):
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
.tox/py310/bin/pytest tests/test_extract_ratings_swap.py -v
```

期待: 全て PASS。`TestExtractRatingsErrorRecovery` と `TestExtractRatingsSkipsDedup` は
`extract_ratings` を直接呼ぶため影響を受けない。

- [ ] **Step 5: ETL 全体のテストを流す**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
.tox/py310/bin/pytest tests/ -q
```

期待: 失敗ゼロ。`test_extract_streaming.py` が `_extract_notes_files` を呼んでいる場合は
第4引数の削除に合わせて修正する。

- [ ] **Step 6: コミットする**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "feat(etl): notes/ratings/status が各自でスナップショット日付を解決する

公開は notes → ratings → noteStatusHistory の順にずれて出るため、
1つの日付を全フェーズに流用する構造では時間差に対応できなかった。"
```

---

### Task 3: ratings の後退防止ガード

**Files:**
- Modify: `etl/src/birdxplorer_etl/extract_ecs.py`（`extract_ratings` の swap 直前）
- Test: `etl/tests/test_extract_ratings_swap.py`

**Interfaces:**
- Consumes: Task 2 の `extract_ratings(..., *, is_fallback: bool = False)`
- Produces: `_check_not_going_backwards(postgresql: Session, staging_count: int) -> None`

- [ ] **Step 1: 失敗するテストを書く**

```python
class TestNotGoingBackwards:
    """フォールバック時に、古いスナップショットで新しい live を上書きしないこと。"""

    def test_raises_when_staging_is_smaller_than_live(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 218398084
        with pytest.raises(RuntimeError, match="RATINGS_SNAPSHOT_OLDER_THAN_LIVE"):
            _check_not_going_backwards(session, 217924158)

    def test_passes_when_staging_is_equal_or_larger(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 218398084
        _check_not_going_backwards(session, 218398084)
        _check_not_going_backwards(session, 218400000)

    def test_error_message_contains_both_numbers(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 218398084
        with pytest.raises(RuntimeError) as exc:
            _check_not_going_backwards(session, 217924158)
        assert "staging=217924158" in str(exc.value)
        assert "live=218398084" in str(exc.value)


class TestExtractRatingsBackwardsGuard:
    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._swap_ratings_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk_with_dedup_fallback")
    @patch("birdxplorer_etl.extract_ecs._verify_staging_row_count")
    @patch("birdxplorer_etl.extract_ecs._process_rating_rows")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_guard_does_not_fire_on_a_same_day_load(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_process: MagicMock,
        mock_verify: MagicMock,
        mock_fallback: MagicMock,
        mock_swap: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """当日分の取り込みでは、staging が live を下回っても止めない。

        評価の取り下げ(実測で約1,500件)で行数がわずかに減る日があるため。
        """
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            mock_requests.get.return_value = MagicMock(
                status_code=200, content=b"noteId\traterParticipantId\n"
            )
            mock_process.return_value = 1000
            mock_fallback.return_value = 1000

            mock_session = MagicMock()
            # reltuples=2000 → min_rows=1000 を通過し、後退判定に使えば 1000 < 2000 で落ちる値
            mock_session.execute.return_value.scalar.return_value = 2000

            extract_ratings(mock_session, "2026/10/05", {"n1"}, is_fallback=False)
        finally:
            settings.USE_DUMMY_DATA = original

        mock_swap.assert_called_once()

    @patch("birdxplorer_etl.extract_ecs._cleanup_staging_table")
    @patch("birdxplorer_etl.extract_ecs._swap_ratings_table")
    @patch("birdxplorer_etl.extract_ecs._build_staging_pk_with_dedup_fallback")
    @patch("birdxplorer_etl.extract_ecs._verify_staging_row_count")
    @patch("birdxplorer_etl.extract_ecs._process_rating_rows")
    @patch("birdxplorer_etl.extract_ecs._create_staging_table")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_guard_fires_on_a_fallback_load(
        self,
        mock_requests: MagicMock,
        mock_create: MagicMock,
        mock_process: MagicMock,
        mock_verify: MagicMock,
        mock_fallback: MagicMock,
        mock_swap: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        import settings

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = True
        try:
            mock_requests.get.return_value = MagicMock(
                status_code=200, content=b"noteId\traterParticipantId\n"
            )
            mock_process.return_value = 1000
            mock_fallback.return_value = 1000

            mock_session = MagicMock()
            mock_session.execute.return_value.scalar.return_value = 2000

            with pytest.raises(RuntimeError, match="RATINGS_SNAPSHOT_OLDER_THAN_LIVE"):
                extract_ratings(mock_session, "2026/10/04", {"n1"}, is_fallback=True)
        finally:
            settings.USE_DUMMY_DATA = original

        mock_swap.assert_not_called()
        mock_cleanup.assert_called_once_with(mock_session)
```

テストファイル先頭の import に `_check_not_going_backwards` を追加する。

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
.tox/py310/bin/pytest tests/test_extract_ratings_swap.py::TestNotGoingBackwards -v
```

期待: FAIL（`ImportError: cannot import name '_check_not_going_backwards'`）。

- [ ] **Step 3: 最小の実装を書く**

`_verify_staging_row_count` の隣に追加する。

```python
def _check_not_going_backwards(postgresql: Session, staging_count: int) -> None:
    """古いスナップショットで新しい live を上書きしないことを確認する。

    row_note_ratings は全置換なので、フォールバックで過去日を取り込むと、より新しい
    データを古いデータで上書きしうる。ratings は累積スナップショットで行数がほぼ単調増加
    するため、行数の比較で後退を検出できる。評価の取り下げによる微減で通常日を止めないよう、
    この判定はフォールバックした日にだけ呼ぶこと。
    """
    live_count = (
        postgresql.execute(
            text(
                "SELECT reltuples::bigint FROM pg_class "
                "WHERE relname='row_note_ratings' AND relnamespace = current_schema()::regnamespace"
            )
        ).scalar()
        or 0
    )
    if live_count > 0 and staging_count < live_count:
        raise RuntimeError(
            f"RATINGS_SNAPSHOT_OLDER_THAN_LIVE staging={staging_count} live={live_count} "
            "フォールバックで取り込んだスナップショットが現在のデータより古い。swap を中止する。"
        )
```

`extract_ratings` の中で、`staging_count` を得たあと `_swap_ratings_table` を呼ぶ直前に挿す。

```python
        # dedup は PK 構築が UniqueViolation で落ちたときだけ走る
        staging_count = _build_staging_pk_with_dedup_fallback(postgresql, total_loaded)

        # フォールバックした日だけ、古いスナップショットでの上書きを防ぐ
        if is_fallback:
            _check_not_going_backwards(postgresql, staging_count)

        _swap_ratings_table(postgresql, min_rows=min_rows, staging_count=staging_count)
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
.tox/py310/bin/pytest tests/ -q
```

期待: 失敗ゼロ。

- [ ] **Step 5: コミットする**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git add etl/src/birdxplorer_etl/extract_ecs.py etl/tests/test_extract_ratings_swap.py
git commit -m "feat(etl): フォールバック時に古いスナップショットでの上書きを防ぐ

row_note_ratings は全置換のため、過去日を取り込むと新しいデータを
古いデータで上書きしうる。行数の後退を検出して swap を中止する。"
```

---

### Task 4: 本番で効果を確認する

**Files:** 変更なし（デプロイと実機確認のみ）

**Interfaces:**
- Consumes: Task 1〜3 すべて
- Produces: なし

- [ ] **Step 1: PR を作る**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
git push -u origin fix/snapshot-date-resolution
gh pr create --title "fix(etl): X の公開前に取りに行って1日分の更新が飛ぶのを直す" --body "$(cat <<'EOF'
## 問題

日次 extract が X の公開前にデータを取りに行き、404 を踏んでその日の更新が丸ごと飛ぶ。
起動を 15:15 → 16:30 に後ろ倒ししても解消しなかった（10-03 に再発）。
公開時刻は1日で1時間以上動くため、固定スケジュールでは追いつけない。

飛ぶのは ratings だけではない。`recalculate_rating_counts` は古い ratings に対して走り、
noteStatusHistory も同時に 404 になることが多く `row_note_status` も更新されない。

## 変更

- notes / noteRatings / noteStatusHistory が**各自でスナップショット日付を解決**する
- 当日分は 10分間隔で最大6回リトライ（最大1時間）
- それでも駄目なら最大3日前までフォールバック
- 接続断はフォールバックせず、そのフェーズだけを失敗させる（既存契約の維持）
- ratings はフォールバック時のみ、行数の後退を検出して swap を中止

新しいログトークン: `SNAPSHOT_WAITING` / `SNAPSHOT_FALLBACK` / `SNAPSHOT_UNAVAILABLE`。
全滅時は既存の `EXTRACT_PHASE_FAILED` アラームに乗るため、cdk 側の変更は不要。

詳細: `docs/superpowers/specs/2026-10-05-snapshot-date-resolution-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**注意**: このリポジトリの PR CI は dev に直接デプロイする。dev は実質本番なので、
ETL の走行時間帯（16:30〜22:00 JST）を避けること。

- [ ] **Step 2: 次回 run のログで新トークンを確認する**

```bash
aws logs filter-log-events --profile birdxplorer \
  --log-group-name dev-bird-xplorer-etlExtractLogGroup \
  --start-time $(python3 -c "import time;print(int((time.time()-86400)*1000))") \
  --filter-pattern '?SNAPSHOT_WAITING ?SNAPSHOT_FALLBACK ?SNAPSHOT_UNAVAILABLE ?"No ratings loaded"' \
  --query 'events[].message' --output text
```

期待: `No ratings loaded` が出ないこと。404 を踏んだ日は `SNAPSHOT_WAITING` が出て、
その後 ratings の取り込みが成功していること。

- [ ] **Step 3: 1週間の頻度を集計する**

```bash
aws logs filter-log-events --profile birdxplorer \
  --log-group-name dev-bird-xplorer-etlExtractLogGroup \
  --start-time $(python3 -c "import time;print(int((time.time()-7*86400)*1000))") \
  --filter-pattern 'SNAPSHOT_FALLBACK' --query 'length(events)' --output text
```

`SNAPSHOT_FALLBACK` が常態化していれば（週に3回以上）、リトライ回数を増やすか、
cdk 側でアラーム化するかを判断する。ゼロなら現状の設定で十分。

- [ ] **Step 4: 起動時刻を戻すか判断する**

リトライが効いていれば、起動を 16:30 に後ろ倒ししている必要は無くなる。
15:15 に戻すと ratings フェーズの完了も早まる。戻す場合は BirdXplorer-cdk の
`lib/bird_xplorer-stack.ts` の `DailyExtractRule` を `cron({ minute: '15', hour: '6' })` に戻し、
`npx cdk deploy devbird-xplorerStack --exclusively --profile birdxplorer -c stage=dev -c tag=<稼働中のタグ>`
で反映する。タグは実機から取ること（`aws ecs describe-tasks` の `containers[0].image`）。

---

## 完了後に残る宿題（このプランの範囲外）

- 404 以外でシャードを丸ごとスキップする経路（`extract_ecs.py:354/417/940/952/967`）。
- `extract_ecs.py:968` で `requests.get` が毎回例外だと `file_index` が増え続けて無限ループしうる件。
- `recalculate_rating_counts` のゼロ落ちと差分ゲート化（実測値は
  `project_rate_count_high_water_mark` のメモリにある）。
- `SNAPSHOT_FALLBACK` のアラーム化（Task 4 Step 3 の頻度次第）。
