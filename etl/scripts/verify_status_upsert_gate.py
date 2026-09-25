"""差分ゲート導入後、「変わったのに書かれなかった」行が無いことを本番で直接確かめる。

ゲートの最悪の壊れ方は静かなデータ欠損で、症状が出ない。単体テストと実 PG テストで
両方向を固定してあるが、本番の実データに対する直接検査は別に要る。

★ 無作為サンプリングでは検査にならない。変化行は noteId 昇順ファイルの末尾に極端に
偏っており（実測: 変化行の p10 でファイルの 98.5% 地点、先頭 54,109 行に含まれるのは
51,719 件中わずか 8 件）、先頭から 500 行取っても変化行が入る期待値は 0.07 件。
ゲートが全変更を取りこぼしていても「不一致 0」が出てしまう。
そこで前日と当日の TSV を突き合わせ、**実際に変化した行だけ**を DB と照合する。

  export PROD_DB_URL='postgresql://USER:PASS@HOST:5432/postgres'
  cd etl && PYTHONPATH=../common python scripts/verify_status_upsert_gate.py [sample_size]

全量2日分（各183MB）をダウンロードするため数分かかる。--cache-dir で再利用できる。

効果の測定は所要時間では見ない。3.3M 行の転送と PK プローブは残るので Status の時間は
ほぼ変わらず、得られるのは WAL・dead tuples・autovacuum・バックアップ帯域である。
  SELECT n_tup_upd, n_dead_tup FROM pg_stat_user_tables WHERE relname='row_note_status';
を ETL の前後で取り、増分が全行数ではなく数万件に収まっていることを見る。
"""

import argparse
import csv
import datetime
import hashlib
import io
import os
import random
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "birdxplorer_etl"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("BX_DATA_DIR", "/tmp")

import stringcase  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from birdxplorer_common.storage import RowNoteStatusRecord  # noqa: E402

URL = "https://ton.twimg.com/birdwatch-public-data/{day}/noteStatusHistory/noteStatusHistory-00000.zip"


def _download(day: str, cache_dir: str) -> str:
    path = os.path.join(cache_dir, f"nsh-{day.replace('/', '')}.zip")
    if not os.path.exists(path):
        print(f"  downloading {day} ...", flush=True)
        # 中断すると壊れた zip がキャッシュに残り、次回以降 BadZipFile で落ち続ける。
        tmp = path + ".part"
        urllib.request.urlretrieve(URL.format(day=day), tmp)
        os.replace(tmp, path)
    return path


def _iter_rows(path: str):
    with zipfile.ZipFile(path) as z:
        with z.open(z.namelist()[0]) as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8"), delimiter="\t")
            reader.fieldnames = [stringcase.snakecase(f) for f in reader.fieldnames]
            yield from reader


def _fingerprints(path: str, cols: list) -> dict:
    out = {}
    for row in _iter_rows(path):
        key = "\t".join(row.get(c) or "" for c in cols)
        out[row["note_id"]] = hashlib.blake2b(key.encode(), digest_size=8).digest()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample", nargs="?", type=int, default=500)
    ap.add_argument("--day", default=datetime.date.today().strftime("%Y/%m/%d"))
    ap.add_argument("--prev")
    ap.add_argument("--cache-dir", default="/tmp")
    args = ap.parse_args()
    prev = args.prev or (datetime.datetime.strptime(args.day, "%Y/%m/%d").date() - datetime.timedelta(days=1)).strftime(
        "%Y/%m/%d"
    )

    engine = create_engine(os.environ["PROD_DB_URL"])
    ptypes = {c.name: c.type.python_type for c in sa_inspect(RowNoteStatusRecord).columns}

    from birdxplorer_etl.extract_ecs import _writable_columns  # noqa: E402

    cols = sorted(_writable_columns(RowNoteStatusRecord) - {"note_id"})

    today_path, prev_path = _download(args.day, args.cache_dir), _download(prev, args.cache_dir)
    before = _fingerprints(prev_path, cols)
    changed_ids = set()
    today_rows = {}
    for row in _iter_rows(today_path):
        key = "\t".join(row.get(c) or "" for c in cols)
        fp = hashlib.blake2b(key.encode(), digest_size=8).digest()
        note_id = row["note_id"]
        if note_id not in before or before[note_id] != fp:
            changed_ids.add(note_id)
            today_rows[note_id] = row
    print(f"{prev} -> {args.day} で変化した(または新規の)行: {len(changed_ids):,}")
    if not changed_ids:
        print("変化行が無い。検査対象が無いので判定できない。")
        sys.exit(2)

    picked = random.sample(sorted(changed_ids), min(args.sample, len(changed_ids)))
    with Session(engine) as sess:
        db = {
            rec.note_id: rec
            for rec in sess.query(RowNoteStatusRecord).filter(RowNoteStatusRecord.note_id.in_(picked)).all()
        }
    print(f"うち無作為 {len(picked):,} 件を照合、DB に在るもの: {len(db):,}")

    # ★ 照合できた行が少ないまま「不一致 0」を出してはいけない。ETL が一切書いていない、
    # 接続先を間違えた、といった最悪ケースで合格判定になる（実際にそうなっていた）。
    # 変化行は当日 TSV に在る以上ほぼ全て DB に在るはずなので、大きく欠けていたら異常。
    floor = max(1, len(picked) // 2)
    if len(db) < floor:
        print(
            f"\n!! 照合できた行が {len(db):,} 件しかない（抽出 {len(picked):,} 件、下限 {floor:,}）。"
            "\n   ETL がこれらの行を書いていないか、接続先が違う。判定を保留する。"
        )
        sys.exit(2)

    def coerce(col, value):
        if value in (None, ""):
            return None
        target = ptypes.get(col, str)
        try:
            return value if target is str else target(value)
        except Exception:
            return value

    mismatches = []
    for note_id in picked:
        rec = db.get(note_id)
        if rec is None:
            continue
        for col in cols:
            want, got = coerce(col, today_rows[note_id].get(col)), getattr(rec, col)
            if want != got:
                mismatches.append((note_id, col, want, got))

    if mismatches:
        print(f"\n!! 不一致 {len(mismatches)} 件 — ゲートが本物の変更を取りこぼしている")
        for note_id, col, want, got in mismatches[:15]:
            print(f"   {note_id} {col}: TSV={want!r} DB={got!r}")
        sys.exit(1)
    print(f"\n不一致 0（変化行 {len(db):,} 行 x {len(cols)} 列を実照合）。取りこぼしは無い。")


if __name__ == "__main__":
    main()
