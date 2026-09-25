"""TwitterTimestamp 列の型を揃える修正が効いていることを、実データと実 PostgreSQL で確認する。

CI には PostgreSQL が無く、xmin と WAL は単体テストでは測れないので手動で回す。
デプロイ後に一度実行して、notes / status の両経路が「同じデータなら書かない」ことを見る。

準備:
    docker run -d --name pg16-verify -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=bx \
        -p 5437:5432 postgres:16

    D=$(date -v-1d +%Y/%m/%d)   # Linux は date -d yesterday +%Y/%m/%d
    curl -s -r 0-600000 -o notes-part.zip \
        "https://ton.twimg.com/birdwatch-public-data/$D/notes/notes-00000.zip"
    curl -s -r 0-900000 -o status-part.zip \
        "https://ton.twimg.com/birdwatch-public-data/$D/noteStatusHistory/noteStatusHistory-00000.zip"
    python3 - <<'EOF'
    import struct, zlib, pathlib
    for src, dst in (("notes-part.zip", "notes-sample.tsv"), ("status-part.zip", "status-sample.tsv")):
        raw = pathlib.Path(src).read_bytes()
        nlen, elen = struct.unpack("<HH", raw[26:30])
        data = zlib.decompressobj(-15).decompress(raw[30 + nlen + elen:])
        lines = data.decode("utf-8", errors="replace").split("\n")[:-1]
        pathlib.Path(dst).write_text("\n".join(lines) + "\n")
    EOF

実行:
    cd etl && PYTHONPATH=../common python scripts/verify_timestamp_normalization.py <TSVのあるディレクトリ>

期待する出力:
    notes  再投入: xmin 変化 0 / N   WAL 0 bytes
    status 再投入: 変更あり判定 0 / M

xmin が動いたり「変更あり」が出たら、入口の型変換が効いていない。
"""

import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "birdxplorer_etl"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("BX_DATA_DIR", "/tmp")

import extract_ecs  # noqa: E402
import stringcase  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from birdxplorer_common.storage import Base  # noqa: E402

DATA_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
DB_URL = os.environ.get("VERIFY_DB_URL", "postgresql://postgres:pw@localhost:5437/bx")

extract_ecs.enqueue_notes_batch = lambda batch: None
extract_ecs.enqueue_note_status_batch = lambda ids: None
engine = create_engine(DB_URL)


def _reader(name):
    handle = open(os.path.join(DATA_DIR, name), newline="")
    reader = csv.DictReader(extract_ecs._iter_lines_without_nul(handle), delimiter="\t")
    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
    return handle, reader


def _measure(table, load):
    """load を1回走らせ、その間に table の行が書き換わったかを見る。"""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f"VACUUM FULL {table}"))
        conn.execute(text(f"ANALYZE {table}"))
    with engine.connect() as conn:
        before = dict(conn.execute(text(f"SELECT note_id, xmin::text FROM {table}")).all())
        start = conn.execute(text("SELECT pg_current_wal_lsn()")).scalar()
    load()
    with engine.connect() as conn:
        after = dict(conn.execute(text(f"SELECT note_id, xmin::text FROM {table}")).all())
        end = conn.execute(text("SELECT pg_current_wal_lsn()")).scalar()
        wal = int(conn.execute(text("SELECT pg_wal_lsn_diff(:a,:b)"), {"a": end, "b": start}).scalar())
    moved = sum(1 for note_id, xmin in before.items() if after.get(note_id) != xmin)
    return moved, len(before), wal


def main() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    def load_notes():
        handle, reader = _reader("notes-sample.tsv")
        with Session(engine) as session:
            extract_ecs._process_note_rows(reader, session, set())
        handle.close()

    load_notes()
    moved, total, wal = _measure("row_notes", load_notes)
    print(f"notes  再投入: xmin 変化 {moved:,} / {total:,}   WAL {wal:,} bytes")

    with open(os.path.join(DATA_DIR, "status-sample.tsv")) as handle:
        note_ids = [line.split("\t")[0] for index, line in enumerate(handle) if index]
    # status の差分判定は row_note_status しか読まない。FK を満たすためだけのスタブ。
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO row_notes (note_id, created_at_millis, tweet_id, summary)"
                " SELECT x, 1, 'stub', '' FROM unnest(CAST(:ids AS text[])) AS x"
                " ON CONFLICT (note_id) DO NOTHING"
            ),
            {"ids": note_ids},
        )

    changed: list = []
    original = extract_ecs._detect_status_changes

    def spy(postgresql, rows):
        result = original(postgresql, rows)
        changed.extend(result)
        return result

    extract_ecs._detect_status_changes = spy

    def load_status():
        handle, reader = _reader("status-sample.tsv")
        with Session(engine) as session:
            extract_ecs._process_note_status_rows(reader, session, set(note_ids))
        handle.close()

    load_status()
    print(f"status 初回  : 変更あり判定 {len(changed):,} / {len(note_ids):,}  (全件新規なので正しい)")
    changed.clear()
    load_status()
    print(f"status 再投入: 変更あり判定 {len(changed):,} / {len(note_ids):,}")


if __name__ == "__main__":
    main()
