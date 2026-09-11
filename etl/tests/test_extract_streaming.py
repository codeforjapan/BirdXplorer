"""notes / noteStatus の TSV をストリーミングで読むことのテスト。

2026-09-08 の OOM は、展開後 1.8GB の TSV を read().decode().splitlines() で
3段階(bytes / str / str のリスト)にわたってメモリへ載せていたことが原因。
ratings だけは以前からストリーミングしており、1.26GB の TSV でも落ちていなかった。
"""

import csv
import io
import sys
import zipfile
from unittest.mock import MagicMock, patch

# extract_ecs.py は psycopg2 と settings をランタイム前提で import する
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extensions = MagicMock()
sys.modules.setdefault("psycopg2", _mock_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _mock_psycopg2.extensions)
sys.modules.setdefault("settings", MagicMock())

import stringcase  # noqa: E402

from birdxplorer_etl.extract_ecs import (  # noqa: E402
    _iter_lines_without_nul,
    _process_note_rows,
    _process_note_status_rows,
)


def _reader_over_zip(tsv_text: str, member: str = "notes-00000.tsv") -> csv.DictReader:
    """production と同じ経路(zip -> TextIOWrapper -> NUL 除去 -> DictReader)で reader を作る。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, tsv_text)
    buf.seek(0)
    zip_file = zipfile.ZipFile(buf)
    tsv_file = zip_file.open(member)
    text_file = io.TextIOWrapper(tsv_file, encoding="utf-8", newline="")
    reader = csv.DictReader(_iter_lines_without_nul(text_file), delimiter="\t")
    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
    return reader


class TestProcessNoteRows:
    def test_accepts_a_one_shot_iterator(self) -> None:
        """リストではなくイテレータで処理できること。

        len() や添字を使っていると全件をメモリに載せる実装に戻ってしまう。
        """
        reader = _reader_over_zip("noteId\tsummary\nn1\thello\n")
        session = MagicMock()

        with patch("birdxplorer_etl.extract_ecs._flush_notes_batch") as flush:
            _process_note_rows(reader, session, {"n1"})

        pending = flush.call_args_list[-1].args[2]
        assert list(pending) == ["n1"]

    def test_a_quoted_newline_is_preserved(self) -> None:
        """クォート内の改行が値として保たれること。

        旧実装(splitlines())でも行数は変わらない。splitlines() がクォート内で割った断片を
        csv.reader が再結合するため。ただし改行そのものは落ちるので値は "line oneline two"
        になっていた。ストリーミングでは "line one\nline two" のまま保たれる。
        つまり行数ではなく summary の値が変わる挙動変化であり、次のフル再取り込みで
        改行を含む summary は全件値が更新される。
        """
        tsv = 'noteId\tsummary\nn1\t"line one\nline two"\n'
        reader = _reader_over_zip(tsv)
        session = MagicMock()

        with patch("birdxplorer_etl.extract_ecs._flush_notes_batch") as flush:
            _process_note_rows(reader, session, {"n1"})

        pending = flush.call_args_list[-1].args[2]
        assert list(pending) == ["n1"]
        assert pending["n1"]["summary"] == "line one\nline two"

    def test_nul_byte_does_not_crash(self) -> None:
        """csv は NUL を含む行で _csv.Error を投げる。読み取り前に落とす。"""
        reader = _reader_over_zip("noteId\tsummary\nn1\tbad\x00value\n")
        session = MagicMock()

        with patch("birdxplorer_etl.extract_ecs._flush_notes_batch") as flush:
            _process_note_rows(reader, session, {"n1"})

        pending = flush.call_args_list[-1].args[2]
        assert pending["n1"]["summary"] == "badvalue"

    def test_flushes_every_1000_rows(self) -> None:
        """バッチ境界を保つ。1回にまとめると結局メモリに全件溜まる。"""
        rows = "".join(f"n{i}\ts{i}\n" for i in range(2500))
        reader = _reader_over_zip("noteId\tsummary\n" + rows)
        session = MagicMock()
        existing = {f"n{i}" for i in range(2500)}

        with patch("birdxplorer_etl.extract_ecs._flush_notes_batch") as flush:
            _process_note_rows(reader, session, existing)

        # 1000, 2000 の2回 + 末尾の1回
        assert flush.call_count == 3


class TestProcessNoteStatusRows:
    def test_accepts_a_one_shot_iterator(self) -> None:
        reader = _reader_over_zip("noteId\tcurrentStatus\nn1\tHELPFUL\n", member="noteStatusHistory-00000.tsv")
        session = MagicMock()
        session.query.return_value.all.return_value = []

        with patch("birdxplorer_etl.extract_ecs._detect_status_changes", return_value=["n1"]):
            with patch("birdxplorer_etl.extract_ecs._upsert_note_status_batch") as upsert:
                with patch("birdxplorer_etl.extract_ecs.enqueue_note_status_batch"):
                    _process_note_status_rows(reader, session, {"n1"})

        assert upsert.call_args.args[1][0]["note_id"] == "n1"

    def test_skips_notes_absent_from_row_notes(self) -> None:
        reader = _reader_over_zip(
            "noteId\tcurrentStatus\nn1\tHELPFUL\nother\tHELPFUL\n",
            member="noteStatusHistory-00000.tsv",
        )
        session = MagicMock()
        session.query.return_value.all.return_value = []

        with patch("birdxplorer_etl.extract_ecs._detect_status_changes", return_value=[]):
            with patch("birdxplorer_etl.extract_ecs._upsert_note_status_batch") as upsert:
                with patch("birdxplorer_etl.extract_ecs.enqueue_note_status_batch"):
                    _process_note_status_rows(reader, session, {"n1"})

        assert [r["note_id"] for r in upsert.call_args.args[1]] == ["n1"]


class TestFlushBoundary:
    def test_a_duplicate_row_does_not_skip_the_flush_boundary(self) -> None:
        """重複行で境界を踏み外してバッチが膨らまないこと。

        フラッシュ判定を enumerate の index に依存させると、重複 note_id の
        `continue` が 1000 の倍数を飛ばし、次の境界まで溜め込み続ける。
        毎1000行目が重複する入力ではファイル全体がメモリに載る＝潰したはずの OOM 形状。
        """
        note_ids = [f"n{i}" for i in range(1999)]
        lines = [f"{note_id}\ts\n" for note_id in note_ids]
        lines.insert(999, "n0\ts\n")  # 1000行目を重複させ、境界の判定を踏み外させる
        reader = _reader_over_zip("noteId\tsummary\n" + "".join(lines))
        session = MagicMock()

        with patch("birdxplorer_etl.extract_ecs._flush_notes_batch") as flush:
            _process_note_rows(reader, session, set(note_ids))

        batch_sizes = [len(call.args[1]) + len(call.args[2]) for call in flush.call_args_list]
        assert max(batch_sizes) <= 1000, f"バッチが 1000 件を超えた: {batch_sizes}"
        # 境界を直した副作用で行を取りこぼしていないこと（重複1件を除いた全件）
        assert sum(batch_sizes) == 1999, f"フラッシュされた件数が合わない: {batch_sizes}"


class TestProductionReaderWiring:
    """extract_data から実際の zip を通し、production の配線そのものを検証する。"""

    @patch("birdxplorer_etl.extract_ecs.run_note_requests_phase")
    @patch("birdxplorer_etl.extract_ecs.backfill_missing_notes")
    @patch("birdxplorer_etl.extract_ecs.recalculate_rating_counts")
    @patch("birdxplorer_etl.extract_ecs.extract_ratings")
    @patch("birdxplorer_etl.extract_ecs._process_note_status_rows")
    @patch("birdxplorer_etl.extract_ecs._process_note_rows")
    @patch("birdxplorer_etl.extract_ecs.requests")
    def test_crlf_inside_a_quoted_field_is_not_rewritten(
        self,
        mock_requests: MagicMock,
        mock_process_note_rows: MagicMock,
        mock_process_note_status_rows: MagicMock,
        mock_extract_ratings: MagicMock,
        mock_recalculate: MagicMock,
        mock_backfill: MagicMock,
        mock_note_requests: MagicMock,
    ) -> None:
        """TextIOWrapper に newline="" を渡さないと、csv より前に CRLF が LF へ書き換わる。

        行ズレは起きないが、summary の値が黙って変わる。csv のドキュメントが
        newline="" を要求しているのはこのため。
        """
        import settings

        from birdxplorer_etl.extract_ecs import extract_data

        tsv = 'noteId\tsummary\nn1\t"line one\r\nline two"\r\n'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("notes-00000.tsv", tsv)
        zip_bytes = buf.getvalue()

        def fake_get(url: str) -> MagicMock:
            res = MagicMock()
            if "notes-00000.zip" in url:
                res.status_code = 200
                res.content = zip_bytes
            else:
                res.status_code = 404
            return res

        captured: list = []
        mock_process_note_rows.side_effect = lambda reader, _session, _ids: captured.extend(reader)
        mock_requests.get.side_effect = fake_get

        original = settings.USE_DUMMY_DATA
        settings.USE_DUMMY_DATA = False
        try:
            mock_session = MagicMock()
            mock_session.query.return_value.all.return_value = []
            extract_data(mock_session)
        finally:
            settings.USE_DUMMY_DATA = original

        assert [row["summary"] for row in captured] == ["line one\r\nline two"]
