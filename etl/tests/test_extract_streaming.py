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
    text_file = io.TextIOWrapper(tsv_file, encoding="utf-8")
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

    def test_a_quoted_newline_stays_one_row(self) -> None:
        """splitlines() はクォート内の改行でも行を割ってしまう。

        ストリーミング + csv なら1行として扱われる。取り込み行数が変わる挙動変化。
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
