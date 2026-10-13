import csv
import io
import json
import logging
import os
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Callable, Iterable, Iterator, Optional

import boto3
import requests
import settings
import stringcase
from sqlalchemy import case, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from birdxplorer_common.models import NoteStatus
from birdxplorer_common.storage import (
    NoteRecord,
    RowNoteRatingRecord,
    RowNoteRecord,
    RowNoteRequestRecord,
    RowNoteStatusRecord,
)

# batSignals の suggestions フィールドは JSON がノートリクエスト提案の蓄積で肥大化し、
# csv デフォルト上限 (131072 バイト) を超える行がある。上限を上げないと
# `_csv.Error: field larger than field limit` で読み取りが途中で落ちる（毎日発生していた）。
csv.field_size_limit(sys.maxsize)

# モジュールレベル SQS クライアント（再生成コスト排除）
_sqs_client = None


def _get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))
    return _sqs_client


def _send_sqs_batch(queue_url: str, messages: list, max_retries: int = 3):
    """
    SQS send_message_batch で最大10件ずつ送信。
    messages: [{"MessageBody": "..."}, ...] — Idは内部で振り直す。
    """
    client = _get_sqs_client()
    for i in range(0, len(messages), 10):
        chunk = messages[i : i + 10]
        # 各チャンクに一意のIdを振る（SQS batch APIの要件）
        batch = [{"Id": str(j), "MessageBody": e["MessageBody"]} for j, e in enumerate(chunk)]
        for attempt in range(max_retries):
            try:
                response = client.send_message_batch(QueueUrl=queue_url, Entries=batch)
                failed = response.get("Failed", [])
                if failed:
                    if attempt < max_retries - 1:
                        logging.warning(
                            f"SQS batch: {len(failed)} failed messages "
                            f"(attempt {attempt + 1}/{max_retries}), retrying"
                        )
                        failed_ids = {f["Id"] for f in failed}
                        batch = [e for e in batch if e["Id"] in failed_ids]
                        time.sleep((attempt + 1) * 0.5)
                        continue
                    else:
                        logging.error(f"SQS batch: {len(failed)} messages failed after {max_retries} attempts")
                        raise RuntimeError(
                            f"SQS send_message_batch failed for {len(failed)} messages after {max_retries} attempts"
                        )
                break
            except RuntimeError:
                raise
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 1.0)
                else:
                    raise


def enqueue_notes_batch(notes: list):
    """notes: [(note_id, summary, post_id, language), ...]"""
    if not notes:
        return
    messages = []
    for note_id, summary, post_id, language in notes:
        body = {"note_id": note_id, "summary": summary, "post_id": post_id, "processing_type": "language_detect"}
        if language:
            body["language"] = language
        messages.append({"MessageBody": json.dumps(body)})
    _send_sqs_batch(settings.LANG_DETECT_QUEUE_URL, messages)
    logging.info(f"Batch enqueued {len(notes)} notes to lang-detect queue")


def enqueue_note_status_batch(note_ids: list):
    """note_ids: [note_id, ...]"""
    if not note_ids or not settings.NOTE_STATUS_UPDATE_QUEUE_URL:
        return
    messages = [
        {"MessageBody": json.dumps({"note_id": nid, "processing_type": "note_status_update"})} for nid in note_ids
    ]
    _send_sqs_batch(settings.NOTE_STATUS_UPDATE_QUEUE_URL, messages)
    logging.info(f"Batch enqueued {len(note_ids)} notes to status-update queue")


# 一度警告した (テーブル, 未知列) の組み合わせ。毎バッチ出すと1日数千行のノイズになる。
_warned_unknown_columns: set = set()

# X のスコアリング実行時刻。公式ドキュメントに "For internal use. Timestamp of scoring run."
# とあるとおりノート単位の情報ではなく、実測でも全行が同一値（2026-09-25 時点で
# TSV 331万行・本番 DB 296万行のいずれも distinct=1）。値は毎日変わる。
_SCORING_RUN_COLUMN = "timestamp_minute_of_final_scoring_output"

# 観測用に集める値の上限。1種類でないと分かれば十分で、全件集める必要はない。
_SCORING_RUN_SAMPLE_CAP = 10

# モデルには在るが意図的に保存しない列。書き込みからも差分比較からも外す。
# _SCORING_RUN_COLUMN を残すと全行が毎日「真に差分あり」になり、差分ゲートが
# 丸ごと無意味になる（WAL 1.67 GB/日）。除くと日次の変化は 1.56% に落ちる。
# ここに入れた列は UNKNOWN_TSV_COLUMNS の警告対象からも外れる。上流が勝手に足した
# 未知の列と、こちらが意図して捨てている列を混同しないため。
_INTENTIONALLY_IGNORED_COLUMNS: dict = {
    "row_note_status": frozenset({_SCORING_RUN_COLUMN}),
}


@lru_cache(maxsize=None)
def _model_columns(model) -> frozenset:
    """モデルの列名。

    hasattr は列でない属性(row_post のようなリレーション、metadata / registry /
    type_annotation_map、_sa_* の内部属性)にも True を返す。TSV 由来のキーを
    振り分けるときに hasattr を使うと、増えた列の名前がそれらと衝突した場合に
    素通りして setattr され、リレーションや SQLAlchemy の内部構造が壊れる。
    """
    return frozenset(c.name for c in model.__table__.columns)


@lru_cache(maxsize=None)
def _writable_columns(model) -> frozenset:
    """実際に書き込む列。モデルの列から、意図的に保存しない列を除いたもの。"""
    return _model_columns(model) - _INTENTIONALLY_IGNORED_COLUMNS.get(model.__tablename__, frozenset())


def _drop_unknown_columns(rows: list[dict], model, warned: set) -> list[dict]:
    """モデルに無い列を落とす。TSV に列が増えても止まらないようにするため。

    2026-09-19、X が noteStatusHistory に timestampMillisAbovePcrhThreshold を足した
    (23列 -> 24列)だけで Status フェーズが KeyError で全滅した。上流のスキーマは
    予告なく増えるので、知らない列は捨てて処理を続ける。

    ただし無言で捨てると列の追加に永久に気付けない。組み合わせごとに1度だけ警告を出す。
    保存したくなったらモデルに足せばよく、そのとき警告も自然に消える。
    """
    known = _writable_columns(model)
    ignored = _INTENTIONALLY_IGNORED_COLUMNS.get(model.__tablename__, frozenset())
    surplus = [c for c in rows[0].keys() if c not in known]
    unknown = [c for c in surplus if c not in ignored]
    if not surplus:
        return rows

    key = (model.__tablename__, tuple(sorted(unknown)))
    if unknown and key not in warned:
        warned.add(key)
        logging.warning(
            f"UNKNOWN_TSV_COLUMNS table={model.__tablename__} ignored={sorted(unknown)} "
            "upstream added columns the model does not have; they are dropped"
        )
    return [{k: v for k, v in row.items() if k in known} for row in rows]


def _upsert_note_status_batch(postgresql: Session, rows: list[dict]):
    """row_note_status を UPSERT（DELETE→INSERT による dead tuples を回避）"""
    if not rows:
        return
    rows = _drop_unknown_columns(rows, RowNoteStatusRecord, _warned_unknown_columns)

    # 書き込む列と比較する列は必ず同じ集合から作る。ズレると、ズレた列の変更が
    # WHERE に引っかからず黙って書かれなくなる（静かなデータ欠損）。
    cols = [col for col in rows[0].keys() if col != "note_id"]
    if not cols:
        return

    # 値が同じ行は書かない。PostgreSQL の DO UPDATE は同値でも新タプルを書くため、
    # ゲートが無いと毎日全行ぶんの WAL と dead tuples が出る。
    # 判定を PG 側に任せるので Python 側で型を揃える必要が無い（この表には
    # str/Decimal の不一致が10列ほどある）。
    # ★ `!=` ではなく IS DISTINCT FROM を使うこと。SQL の `NULL != 5` は UNKNOWN で
    # WHERE では偽になるため、`!=` にすると NULL から値・値から NULL への変更が
    # 静かに書かれなくなる。このコミットが最悪と定義しているのがまさにその方向。
    table = RowNoteStatusRecord.__table__
    stmt = insert(RowNoteStatusRecord)
    stmt = stmt.on_conflict_do_update(
        index_elements=["note_id"],
        set_={col: stmt.excluded[col] for col in cols},
        where=or_(*[table.c[col].is_distinct_from(stmt.excluded[col]) for col in cols]),
    )
    postgresql.execute(stmt, rows)


def _detect_status_changes(postgresql: Session, rows: list[dict]) -> list[str]:
    """ステータスが実際に変更された note_id のリストを返す（新規も含む）"""
    note_ids = [r["note_id"] for r in rows]
    if not note_ids:
        return []

    results = postgresql.execute(
        select(
            RowNoteStatusRecord.note_id,
            RowNoteStatusRecord.current_status,
            RowNoteStatusRecord.locked_status,
            RowNoteStatusRecord.timestamp_millis_of_current_status,
        ).filter(RowNoteStatusRecord.note_id.in_(note_ids))
    ).all()
    existing = {r.note_id: (r.current_status, r.locked_status, r.timestamp_millis_of_current_status) for r in results}

    changed = []
    for row in rows:
        nid = row["note_id"]
        old = existing.get(nid)
        if old is None:
            changed.append(nid)
        else:
            new = (row.get("current_status"), row.get("locked_status"), row.get("timestamp_millis_of_current_status"))
            if old != new:
                changed.append(nid)
    return changed


def _run_phase(name: str, postgresql: Session, phase: Callable[[], None]) -> bool:
    """1フェーズを実行し、失敗しても後続フェーズを止めない。成功なら True。

    フェーズを直列に裸で呼ぶと、前段の例外が extract_data を貫通してプロセスごと落ち、
    後段のフェーズが一度も走らない。2026-09-02 からの6日間、ratings の COPY 失敗が
    run_note_requests_phase を巻き添えにして tweet-lookup への enqueue を止めていた。

    ただし握りつぶしを無音にすると劣化に気付けないので、CloudWatch メトリクスフィルタ用に
    EXTRACT_PHASE_FAILED トークンを必ず出す（NOTE_REQUEST_ROW_SKIPPED と同じ方式）。
    例外後のセッションは InFailedSqlTransaction のままなので rollback して後段に渡す。

    トークンの出力は rollback より必ず先に行う。RDS のフェイルオーバーや接続断で
    フェーズが落ちた場合は rollback 自体も例外を投げるため、順序を逆にすると
    トークンを取りこぼしたうえでプロセスが死ぬ。アラームが最も必要な場面で無音になる。
    """
    phase_start = time.time()
    try:
        phase()
    except Exception as e:
        logging.exception(f"EXTRACT_PHASE_FAILED phase={name} elapsed={time.time() - phase_start:.1f}s reason={e}")
        try:
            postgresql.rollback()
        except Exception:
            # 接続が死んでいると rollback もできない。後段フェーズはそれぞれ失敗して
            # 個別にトークンを出すので、ここで打ち切らず契約（例外を投げない）を守る。
            logging.exception(f"EXTRACT_PHASE_FAILED phase={name} rollback also failed")
        return False
    logging.info(f"[PHASE_COMPLETE] {name}: {time.time() - phase_start:.1f}s")
    return True


# 各ファミリーの先頭ファイル。公開済みかの判定はこれ1つの HEAD で足りる。
_SNAPSHOT_FIRST_FILE = {
    "notes": "notes-00000.zip",
    "noteRatings": "ratings-00000.zip",
    "noteStatusHistory": "noteStatusHistory-00000.zip",
}
_SNAPSHOT_RETRY_INTERVAL_SECONDS = 600
_SNAPSHOT_MAX_RETRIES = 6
_SNAPSHOT_MAX_FALLBACK_DAYS = 3
# HEAD/GET の接続待ち上限。半開ソケットに当たると requests はデフォルトで無期限に待つ。
# この設計の中で唯一の無制限待機になる箇所なので、必ず上限を付ける。
_SNAPSHOT_PROBE_TIMEOUT_SECONDS = 30


def _snapshot_file_url(kind: str, date_string: str, file_index: int) -> str:
    """kind ファミリーの file_index 番目のファイル URL を組み立てる。

    _probe_snapshot(常に index 0 を見る)と ratings のシャード欠番チェック(任意の index を見る)が
    URL の組み立てを別々に持たないよう、ここに一本化する。
    """
    prefix = _SNAPSHOT_FIRST_FILE[kind].removesuffix("-00000.zip")
    return f"https://ton.twimg.com/birdwatch-public-data/{date_string}/{kind}/{prefix}-{file_index:05d}.zip"


def _probe_snapshot(kind: str, date_string: str) -> bool:
    """そのファミリーの 00000 が公開されているかを HEAD で確認する。

    例外は握りつぶさない。404(未公開)とネットワーク障害は別物で、後者で前日に流れると
    ratings のフルスワップ込みで前日分を丸ごと再処理して1時間規模を浪費する。
    """
    url = _snapshot_file_url(kind, date_string, 0)
    return requests.head(url, timeout=_SNAPSHOT_PROBE_TIMEOUT_SECONDS).status_code == 200


def _probe_ratings_shard(date_string: str, file_index: int) -> bool:
    """ratings の file_index 番目のシャードが公開されているかを HEAD で確認する。

    X のシャードは公開順がバラバラで ratings-00000 が最後に揃うとは限らない。
    extract_ratings の 404 判定が「シャードの欠番」を「ファミリー全体の終端」と
    取り違えないための先読み専用。_probe_snapshot と同じ URL の組み立てを使う。
    """
    url = _snapshot_file_url("noteRatings", date_string, file_index)
    return requests.head(url, timeout=_SNAPSHOT_PROBE_TIMEOUT_SECONDS).status_code == 200


def _check_ratings_shard_listing_complete(date_string: str, missing_index: int) -> list[int]:
    """missing_index の直後2つのシャードのうち、実在するものの番号を返す。

    空リストなら両方とも存在せず、missing_index が本当の終端だと確認できたことを意味する。
    1つでも存在すれば、シャードの公開がまだ進行中で、この 404 は歯抜けに過ぎない。
    """
    return [idx for idx in (missing_index + 1, missing_index + 2) if _probe_ratings_shard(date_string, idx)]


def _snapshot_tried_range(base: datetime) -> str:
    """全滅時のログ/例外メッセージに使う `tried=<当日>..<最古の候補日>` の範囲文字列。"""
    today = base.strftime("%Y/%m/%d")
    oldest = (base - timedelta(days=_SNAPSHOT_MAX_FALLBACK_DAYS)).strftime("%Y/%m/%d")
    return f"{today}..{oldest}"


def _resolve_snapshot_date(
    kind: str,
    base: datetime,
    *,
    probe: Optional[Callable[[str, str], bool]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> Optional[str]:
    """当日→リトライ→過去日 の順にスナップショットの日付を解決する。全滅なら None。

    リトライは当日分にだけ掛ける。過去日は公開済みか否かが確定しており、待つ意味がない。

    probe/sleep の既定値はここで（呼び出し時に）解決する。デフォルト引数として直接
    `= _probe_snapshot` のように束縛すると、その参照は定義時に固定され、
    `@patch("...._probe_snapshot")` で module 属性を差し替えてもここには反映されない。

    当日のリトライ中に起きた例外(接続断など)は 404 と同じ扱いでリトライする(同じ間隔・
    同じ回数)。最初の1回だけは別で、ここで起きた例外はまだ待機に入っていないため即座に
    伝播させる。リトライを使い切り、最後の試行が例外で終わった場合は、フォールバックせず
    その例外をそのまま送出する。接続障害で前日に流れると ratings のフルスワップ込みで
    前日分を丸ごと再処理して1時間規模を浪費するため。過去日の探索中に起きた例外は
    リトライせず即座に伝播させる(既存契約の維持)。
    """
    probe = probe or _probe_snapshot
    sleep = sleep or time.sleep
    today = base.strftime("%Y/%m/%d")
    if probe(kind, today):
        return today

    last_exception: Optional[Exception] = None
    for attempt in range(1, _SNAPSHOT_MAX_RETRIES + 1):
        logging.info(f"SNAPSHOT_WAITING kind={kind} attempt={attempt}/{_SNAPSHOT_MAX_RETRIES} date={today}")
        sleep(_SNAPSHOT_RETRY_INTERVAL_SECONDS)
        try:
            if probe(kind, today):
                return today
            last_exception = None
        except Exception as e:
            last_exception = e

    if last_exception is not None:
        raise last_exception

    for days_ago in range(1, _SNAPSHOT_MAX_FALLBACK_DAYS + 1):
        candidate = (base - timedelta(days=days_ago)).strftime("%Y/%m/%d")
        if probe(kind, candidate):
            logging.warning(f"SNAPSHOT_FALLBACK kind={kind} requested={today} resolved={candidate}")
            return candidate

    logging.error(f"SNAPSHOT_UNAVAILABLE kind={kind} tried={_snapshot_tried_range(base)}")
    return None


def _run_notes_phase(postgresql: Session, existing_row_note_ids: set, now: datetime) -> None:
    # 解決待ちは最大1時間ブロックしうる。セッションが read transaction を握ったまま待つと
    # xmin horizon が固定されて autovacuum を妨げるため、待機に入る前に手放す。
    postgresql.rollback()
    date_string = _resolve_snapshot_date("notes", now)
    if date_string is None:
        raise RuntimeError(f"SNAPSHOT_UNAVAILABLE kind=notes tried={_snapshot_tried_range(now)}")
    _extract_notes_files(postgresql, date_string, existing_row_note_ids)


def _run_ratings_phase(postgresql: Session, existing_row_note_ids: set, now: datetime) -> None:
    postgresql.rollback()
    date_string = _resolve_snapshot_date("noteRatings", now)
    if date_string is None:
        raise RuntimeError(f"SNAPSHOT_UNAVAILABLE kind=noteRatings tried={_snapshot_tried_range(now)}")
    is_fallback = date_string != now.strftime("%Y/%m/%d")
    extract_ratings(postgresql, date_string, existing_row_note_ids, is_fallback=is_fallback)


def _run_status_phase(postgresql: Session, existing_row_note_ids: set, now: datetime) -> None:
    postgresql.rollback()
    date_string = _resolve_snapshot_date("noteStatusHistory", now)
    if date_string is None:
        raise RuntimeError(f"SNAPSHOT_UNAVAILABLE kind=noteStatusHistory tried={_snapshot_tried_range(now)}")
    _extract_note_status_files(postgresql, date_string, existing_row_note_ids)


def extract_data(postgresql: Session):
    logging.info("Downloading community notes data")

    # 既存のrow_notesのnote_idをメモリに読み込み（1行ずつのDBクエリを削減）
    existing_row_note_ids = set(r[0] for r in postgresql.query(RowNoteRecord.note_id).all())
    logging.info(f"Loaded {len(existing_row_note_ids)} existing note IDs from row_notes")

    now = datetime.now()

    # 日付解決はフェーズの内側で行う。_run_phase の外で解決すると、解決中の例外が
    # Backfill / NoteRequests まで巻き添えにする。
    notes_ok = _run_phase("Notes", postgresql, lambda: _run_notes_phase(postgresql, existing_row_note_ids, now))

    if notes_ok:
        # Notes が失敗した日に Ratings の全置換 swap を走らせると、existing_row_note_ids が
        # その日の新規ノートを含まないまま unknown_note としてふるい落とし、
        # recalculate_rating_counts がそのぶん低い集計値を全ノートに書き込んでしまう。
        # 旧実装(839af64 より前)と同じく、Notes が失敗した日は Ratings/Rating recalculation/
        # Status をまとめてスキップする(Backfill/NoteRequests は常に走らせる)。

        # 評価データを取得して保存（noteStatus処理より先に実行することで集計タイミングを保証）
        _run_phase("Ratings", postgresql, lambda: _run_ratings_phase(postgresql, existing_row_note_ids, now))

        # notesテーブルの評価集計カラムを再計算
        _run_phase("Rating recalculation", postgresql, lambda: recalculate_rating_counts(postgresql))

        _run_phase("Status", postgresql, lambda: _run_status_phase(postgresql, existing_row_note_ids, now))

        # has_been_helpfuled は row_note_status を見るので Status フェーズより後に回す
        _run_phase("Helpfuled flag recalculation", postgresql, lambda: recalculate_has_been_helpfuled(postgresql))

    postgresql.commit()

    # row_notesにあるがnotesにないレコードをバックフィル
    _run_phase("Backfill", postgresql, lambda: backfill_missing_notes(postgresql))

    # Note Requests (batSignals) の取り込みと投稿 lookup の enqueue
    _run_phase("NoteRequests", postgresql, lambda: run_note_requests_phase(postgresql))

    return


def _extract_notes_files(postgresql: Session, dateString: str, existing_row_note_ids: set) -> None:
    """notes-XXXXX.zip を 404 まで順に取得して取り込む。"""
    file_index = 0

    while True:
        if settings.USE_DUMMY_DATA:
            note_url = (
                "https://raw.githubusercontent.com/codeforjapan/BirdXplorer"
                "/refs/heads/main/etl/data/notes_sample.tsv"
            )
        else:
            note_url = f"https://ton.twimg.com/birdwatch-public-data/{dateString}/notes/notes-{file_index:05d}.zip"

        logging.info(f"Fetching notes from: {note_url}")
        res = requests.get(note_url)

        if res.status_code == 404:
            if file_index == 0:
                # 前日フォールバックは _resolve_snapshot_date が事前に行う。ここに来る時点で
                # dateString は公開確認済みのはずなので、この 404 は取得対象が無いことだけを
                # 意味し、別の日付を試すことはしない。
                logging.info(f"No notes data available for {dateString} (404 on the first file), nothing to fetch")
            else:
                logging.info(f"Notes file {file_index:05d} not found (404), stopping notes download for {dateString}")
            break

        if res.status_code != 200:
            logging.warning(f"Unexpected status code {res.status_code} for notes file {file_index:05d}, skipping")
            file_index += 1
            continue

        # TSVを読み込む
        if settings.USE_DUMMY_DATA:
            # ダミーデータの場合はTSVファイルを直接処理
            tsv_data = res.content.decode("utf-8").splitlines()
            reader = csv.DictReader(_iter_lines_without_nul(tsv_data), delimiter="\t")
            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
            _process_note_rows(reader, postgresql, existing_row_note_ids)
        else:
            with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                tsv_filename = f"notes-{file_index:05d}.tsv"
                if tsv_filename not in zip_file.namelist():
                    logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                    break

                # 展開後の TSV は 1.8GB 規模。read().decode().splitlines() は
                # bytes / str / str のリストで3重にメモリへ載せ、8GB を超えて OOM した。
                # ratings と同じくストリームのまま渡し、消費もこの with の内側で行う。
                with zip_file.open(tsv_filename) as tsv_file:
                    text_file = io.TextIOWrapper(tsv_file, encoding="utf-8", newline="")
                    reader = csv.DictReader(_iter_lines_without_nul(text_file), delimiter="\t")
                    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                    _process_note_rows(reader, postgresql, existing_row_note_ids)

        logging.info(f"Successfully processed notes file {file_index:05d} for {dateString}")

        # ダミーデータの場合は1ファイルのみなのでループを抜ける
        if settings.USE_DUMMY_DATA:
            break

        file_index += 1


def _extract_note_status_files(postgresql: Session, dateString: str, existing_row_note_ids: set) -> None:
    """noteStatusHistory-XXXXX.zip を 404 まで順に取得して取り込む。"""
    file_index = 0

    while True:
        if settings.USE_DUMMY_DATA:
            status_url = (
                "https://raw.githubusercontent.com/codeforjapan/BirdXplorer/"
                "refs/heads/main/etl/data/noteStatus_sample.tsv"
            )
        else:
            status_url = (
                f"https://ton.twimg.com/birdwatch-public-data/{dateString}/"
                f"noteStatusHistory/noteStatusHistory-{file_index:05d}.zip"
            )

        logging.info(f"Fetching note status from: {status_url}")
        res = requests.get(status_url)

        if res.status_code == 404:
            logging.info(
                f"Note status file {file_index:05d} not found (404), stopping status download for {dateString}"
            )
            break

        if res.status_code != 200:
            logging.warning(f"Unexpected status code {res.status_code} for status file {file_index:05d}, skipping")
            file_index += 1
            continue

        # TSVを読み込む
        if settings.USE_DUMMY_DATA:
            # Handle dummy data as TSV
            tsv_data = res.content.decode("utf-8").splitlines()
            reader = csv.DictReader(_iter_lines_without_nul(tsv_data), delimiter="\t")
            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
            _process_note_status_rows(reader, postgresql, existing_row_note_ids)
        else:
            # Handle real data as zip file
            with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                tsv_filename = f"noteStatusHistory-{file_index:05d}.tsv"
                if tsv_filename not in zip_file.namelist():
                    logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                    break

                # notes と同じ理由でストリームのまま渡す(172MB の zip = 展開後 700MB 規模)
                with zip_file.open(tsv_filename) as tsv_file:
                    text_file = io.TextIOWrapper(tsv_file, encoding="utf-8", newline="")
                    reader = csv.DictReader(_iter_lines_without_nul(text_file), delimiter="\t")
                    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                    _process_note_status_rows(reader, postgresql, existing_row_note_ids)

        logging.info(f"Successfully processed note status file {file_index:05d} for {dateString}")

        # ダミーデータの場合は1ファイルのみなのでループを抜ける
        if settings.USE_DUMMY_DATA:
            break

        file_index += 1


def _log_scoring_run_observation(values: set) -> None:
    """保存しない scoring 列について、前提が崩れていないかだけ記録する。

    この列は全行が同一値のはずで、それが「ノート単位の情報を持たないから捨ててよい」
    という判断の根拠になっている。値が複数種類になったら前提が崩れており、
    無視し続けてよいか再判断が要る。
    """
    if not values:
        return
    if len(values) == 1:
        logging.info(f"SCORING_RUN_TIMESTAMP value={next(iter(values))}")
        return
    # 空文字は行ループで None になるので値に None が混ざりうる。str を挟まずに
    # sorted すると TypeError になり、「前提が崩れた」ことを報せるはずの監視が
    # 逆にフェーズを落とす。
    sample = sorted(map(repr, values))[:5]
    # 収集は上限で打ち切っているので、到達していたら実際の種類数はこれ以上ある。
    distinct = f">={len(values)}" if len(values) >= _SCORING_RUN_SAMPLE_CAP else str(len(values))
    logging.warning(
        f"SCORING_RUN_TIMESTAMP_NOT_CONSTANT distinct={distinct} sample={sample} "
        f"column={_SCORING_RUN_COLUMN} is no longer uniform; revisit whether it can stay ignored"
    )


def _process_note_status_rows(reader, postgresql: Session, existing_row_note_ids: set) -> None:
    """noteStatusHistory の TSV 行を1行ずつ処理し、1000件ごとに差分検出・UPSERT・enqueue する。

    notes 側と同じ理由で `with zip_file.open(...)` の内側から呼ぶ。
    """
    existing_note_record_ids = set(r[0] for r in postgresql.query(NoteRecord.note_id).all())
    logging.info(f"Loaded {len(existing_note_record_ids)} existing note IDs from notes table")

    rows_to_process = []
    # 保存しない列(_SCORING_RUN_COLUMN)の値だけは毎回観測する。無視リストに入れた列を
    # 完全に見なくすると、上流が per-note の意味に変えても永久に気付けないため。
    scoring_run_values: set = set()
    for index, row in enumerate(reader):
        for key, value in list(row.items()):
            if value == "":
                row[key] = None

        # 対応するnote_idがrow_notesテーブルに存在するかをセットで確認
        if row["note_id"] not in existing_row_note_ids:
            continue

        # 上流が per-note の値に変えると 331万件たまって数百MB になる。
        # 前提が崩れたことさえ分かればよいので、少し集めたら打ち切る。
        if _SCORING_RUN_COLUMN in row and len(scoring_run_values) < _SCORING_RUN_SAMPLE_CAP:
            scoring_run_values.add(row[_SCORING_RUN_COLUMN])

        # _detect_status_changes が比較する3列のうち、この列だけ DB 側が Decimal になる。
        # 揃えないとタプル比較が常に不一致になり、全行が「変更あり」として enqueue される。
        row["timestamp_millis_of_current_status"] = _to_timestamp_decimal(
            row.get("timestamp_millis_of_current_status"),
            "timestamp_millis_of_current_status",
            row["note_id"],
        )

        rows_to_process.append(row)

        if len(rows_to_process) >= 1000:
            # 差分検出 → UPSERT → 変更分のみ enqueue
            changed_note_ids = _detect_status_changes(postgresql, rows_to_process)
            _upsert_note_status_batch(postgresql, [dict(r) for r in rows_to_process])
            postgresql.commit()

            notes_to_update_status = [nid for nid in changed_note_ids if nid in existing_note_record_ids]
            enqueue_note_status_batch(notes_to_update_status)

            rows_to_process = []

    # 最後のバッチを処理
    if rows_to_process:
        changed_note_ids = _detect_status_changes(postgresql, rows_to_process)
        _upsert_note_status_batch(postgresql, [dict(r) for r in rows_to_process])
        postgresql.commit()

        notes_to_update_status = [nid for nid in changed_note_ids if nid in existing_note_record_ids]
        enqueue_note_status_batch(notes_to_update_status)

    # 観測は全バッチを書き終えてから行う。ここで落ちても取り込み済みのデータは失われない。
    _log_scoring_run_observation(scoring_run_values)


def _to_timestamp_decimal(value: Optional[str], field: str, note_id: str) -> Optional[Decimal]:
    """TwitterTimestamp 列の TSV 値を、ORM が返すのと同じ Decimal に揃える。

    storage.py の type_annotation_map が `TwitterTimestamp: DECIMAL` をマップしているため
    ORM 側は Decimal を返す。TSV 側を str のままにすると `Decimal(...) != '...'` が常に真になり、
    「変わった行だけ書く」はずの差分判定が全行を素通しする。

    非数値は握りつぶさずに落とす。タイムスタンプに代わりに置ける正しい既定値が無いためで、
    無言で None にすれば値が消え、素通しすれば flush 時の DataError になってどの行が原因か
    分からなくなる。落ちたあとは _run_phase が EXTRACT_PHASE_FAILED を出す。
    (row_notes.created_at_millis は NOT NULL、row_note_status 側は nullable だが方針は同じ)
    """
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        logging.error(f"TIMESTAMP_PARSE_FAILED note_id={note_id} field={field} value={value!r}")
        raise


def _process_note_rows(reader, postgresql: Session, existing_row_note_ids: set) -> None:
    """notes の TSV 行を1行ずつ処理し、1000件ごとに DB へフラッシュする。

    reader は zip 内ファイルを直接ラップしたストリームなので、呼び出しは
    `with zip_file.open(...)` の内側で行う必要がある。以前はここが while ループ側に
    あったため reader を作る時点で全件をメモリに載せるしかなく、それが
    2026-09-08 の OOM(exit 137) の原因になっていた。
    """
    # 新規か既存かはここでは振り分けない。_flush_notes_batch が直前に DB へ問い合わせて決める。
    # 重複 note_id は1バッチ(1000件)の中では先勝ち。バッチ境界を跨いだ同一 note_id は
    # 次のバッチで既存扱いになり UPDATE 経路に回るため後勝ちになる(main と同じ挙動)。
    rows = {}
    for row in reader:
        note_id = row["note_id"]
        if note_id in rows:
            continue

        # BinaryBoolフィールドの値を正規化
        binary_bool_fields = [
            "believable",
            "misleading_other",
            "misleading_factual_error",
            "misleading_manipulated_media",
            "misleading_outdated_information",
            "misleading_missing_important_context",
            "misleading_unverified_claim_as_fact",
            "misleading_satire",
            "not_misleading_other",
            "not_misleading_factually_correct",
            "not_misleading_outdated_but_not_when_written",
            "not_misleading_clearly_satire",
            "not_misleading_personal_opinion",
            "trustworthy_sources",
            "is_media_note",
            "is_collaborative_note",
        ]

        for field in binary_bool_fields:
            if field in row:
                value = row[field]
                if field == "believable":
                    # believableフィールドの特別な処理
                    if value == "BELIEVABLE_BY_MANY":
                        row[field] = "1"
                    elif value == "BELIEVABLE_BY_FEW":
                        row[field] = "0"
                    elif value == "" or value is None or value == "empty":
                        row[field] = "0"
                    elif value not in ["0", "1"]:
                        note_id = row.get("note_id", "unknown")
                        logging.warning(
                            f"Unexpected value '{value}' for believable field in note {note_id}. " f"Setting to '0'."
                        )
                        row[field] = "0"
                else:
                    # 他のBinaryBoolフィールドの処理
                    if value == "" or value is None or value == "empty":
                        row[field] = "0"
                    elif value not in ["0", "1"]:
                        # 予期しない値の場合はログに記録して0に設定
                        note_id = row.get("note_id", "unknown")
                        logging.warning(
                            f"Unexpected value '{value}' for field '{field}' in note {note_id}. " f"Setting to '0'."
                        )
                        row[field] = "0"

        # harmfulフィールドの処理
        if "harmful" in row:
            value = row["harmful"]
            if value == "" or value is None or value == "empty":
                row["harmful"] = "LITTLE_HARM"  # デフォルト値
            elif value not in ["LITTLE_HARM", "CONSIDERABLE_HARM"]:
                note_id = row.get("note_id", "unknown")
                logging.warning(
                    f"Unexpected value '{value}' for harmful field in note {note_id}. " f"Setting to 'LITTLE_HARM'."
                )
                row["harmful"] = "LITTLE_HARM"

        # classificationフィールドの処理
        if "classification" in row:
            value = row["classification"]
            if value == "" or value is None or value == "empty":
                row["classification"] = "NOT_MISLEADING"  # デフォルト値
            elif value not in ["NOT_MISLEADING", "MISINFORMED_OR_POTENTIALLY_MISLEADING"]:
                note_id = row.get("note_id", "unknown")
                logging.warning(
                    f"Unexpected value '{value}' for classification field in note {note_id}. "
                    f"Setting to 'NOT_MISLEADING'."
                )
                row["classification"] = "NOT_MISLEADING"

        # validation_difficultyフィールドの処理（データベースではSummaryString型）
        if "validation_difficulty" in row:
            value = row["validation_difficulty"]
            if value == "" or value is None or value == "empty":
                row["validation_difficulty"] = ""  # 空文字列として保存

        # その他の空文字列フィールドの処理（harmful と validation_difficulty 以外）
        for key, value in row.items():
            if value == "" and key not in ["harmful", "validation_difficulty"]:
                row[key] = None

        # 差分判定の相手は ORM から読んだ Decimal なので、ここで型を揃える。
        row["created_at_millis"] = _to_timestamp_decimal(row.get("created_at_millis"), "created_at_millis", note_id)

        rows[note_id] = dict(row)

        # 境界は「溜まった件数」で判定する。enumerate の index で判定すると、
        # 重複 note_id の continue が 1000 の倍数を飛ばし、次の境界まで溜め込み続ける。
        if len(rows) >= 1000:
            _flush_notes_batch(postgresql, rows, existing_row_note_ids)
            rows = {}

    # 最後のバッチを処理
    _flush_notes_batch(postgresql, rows, existing_row_note_ids)


def _flush_notes_batch(postgresql: Session, rows: dict, existing_row_note_ids: set) -> None:
    """ノート処理の1バッチ分をDB保存+SQS送信する。

    新規か既存かは、起動時のスナップショットではなく**このフラッシュの直前に DB へ問い合わせて**
    判断する。row_notes には書き手が2つある(日次 Extract と、realtime_notes_extraction 経由の
    db_writer)。起動時スナップショットで31分間ずっと振り分けていたため、その間に db_writer が
    入れたノートを新規と誤認して素の INSERT を投げ、UniqueViolation で Notes フェーズごと
    落ちた(2026-09-15)。この照会で競合窓は31分からミリ秒に縮む。
    """
    if not rows:
        return

    ids = list(rows.keys())
    existing = {r.note_id: r for r in postgresql.query(RowNoteRecord).filter(RowNoteRecord.note_id.in_(ids)).all()}

    # 既存レコードの更新。変わった列だけ setattr する差分ガードを通す。
    # このガードは created_at_millis の型が揃っていて初めて機能する。ORM 側は DECIMAL
    # (storage.py の type_annotation_map)で Decimal を返すため、TSV 由来の str をそのまま
    # 比べると常に不一致になり、全行が毎日 UPDATE される。揃えるのは _process_note_rows の
    # 入口(_to_timestamp_decimal)の役目で、ここで型を意識する必要はない。
    # 振り分けは hasattr ではなく列集合で行う(理由は _model_columns)。INSERT 側と揃える。
    known = _model_columns(RowNoteRecord)
    for note_id, record in existing.items():
        for key, value in rows[note_id].items():
            if key in known and getattr(record, key) != value:
                setattr(record, key, value)

    # 新規レコードの挿入。SELECT と INSERT の隙間は残るので ON CONFLICT を保険に置く。
    # DO UPDATE にしてはいけない。rowcount が更新行も数えるため下の警告が構造的に発火せず、
    # 振り分けが大規模に壊れても無音になる。
    to_insert = [rows[note_id] for note_id in ids if note_id not in existing]
    if to_insert:
        # 更新側は hasattr で弾けるが、INSERT はモデルに無い列が1つ混じるだけで
        # CompileError: Unconsumed column names になりフェーズごと落ちる。
        to_insert = _drop_unknown_columns(to_insert, RowNoteRecord, _warned_unknown_columns)
        stmt = insert(RowNoteRecord).values(to_insert).on_conflict_do_nothing(index_elements=["note_id"])
        result = postgresql.execute(stmt)
        skipped = len(to_insert) - (result.rowcount or 0)
        if skipped > 0:
            logging.warning(
                f"NOTE_INSERT_CONFLICT skipped={skipped} of={len(to_insert)} "
                "rows were inserted by another writer between the SELECT and the INSERT"
            )

    postgresql.flush()
    postgresql.commit()

    # ratings(_validate_rating_row)と status(_process_note_status_rows)がこのセットを使う。
    # 更新を落とすとその日の新規ノートの評価とステータスが無言でスキップされる。
    # flush 後はバッチの全 ID が DB に実在するので全件入れる。
    existing_row_note_ids.update(ids)

    # SQSバッチ送信（新規追加のみ）。TSV に language 列は無いので get で読む。
    if to_insert:
        batch = [(d["note_id"], d.get("summary") or "", d["tweet_id"], d.get("language")) for d in to_insert]
        enqueue_notes_batch(batch)


def backfill_missing_notes(postgresql: Session, batch_limit: int = 50000):
    """
    row_notesに存在するがnotesテーブルに存在しないレコードをlang-detect-queueに再投入する。
    毎日のextractジョブの最後に呼ばれ、batch_limit件ずつ処理する。
    """
    missing_notes = (
        postgresql.query(RowNoteRecord)
        .outerjoin(NoteRecord, RowNoteRecord.note_id == NoteRecord.note_id)
        .filter(NoteRecord.note_id.is_(None))
        .limit(batch_limit)
        .all()
    )

    if not missing_notes:
        logging.info("Backfill: no missing notes found")
        return

    logging.info(f"Backfill: found {len(missing_notes)} notes in row_notes missing from notes, re-enqueuing")

    batch = [(n.note_id, n.summary or "", n.tweet_id, n.language) for n in missing_notes]
    enqueue_notes_batch(batch)

    logging.info(f"Backfill complete: enqueued {len(batch)} notes")


def _validate_rating_row(row: dict, existing_row_note_ids: set, skipped: Counter | None = None) -> bool:
    """rating行を検証・正規化する。有効ならTrue、スキップならFalseを返す。rowは破壊的に更新される。

    skipped を渡すと落選理由を加算する。捨てた行数を記録しないと、
    正常な落選（削除済みノートの評価）と異常な欠損を区別できない。
    """

    def _skip(reason: str) -> bool:
        if skipped is not None:
            skipped[reason] += 1
        return False

    binary_bool_fields = [
        "agree",
        "disagree",
        "helpful",
        "not_helpful",
        "helpful_other",
        "helpful_informative",
        "helpful_clear",
        "helpful_empathetic",
        "helpful_good_sources",
        "helpful_unique_context",
        "helpful_addresses_claim",
        "helpful_important_context",
        "helpful_unbiased_language",
        "not_helpful_other",
        "not_helpful_incorrect",
        "not_helpful_sources_missing_or_unreliable",
        "not_helpful_opinion_speculation_or_bias",
        "not_helpful_missing_key_points",
        "not_helpful_outdated",
        "not_helpful_hard_to_understand",
        "not_helpful_argumentative_or_biased",
        "not_helpful_off_topic",
        "not_helpful_spam_harassment_or_abuse",
        "not_helpful_irrelevant_sources",
        "not_helpful_opinion_speculation",
        "not_helpful_note_not_needed",
    ]

    note_id = row.get("note_id")
    rater_participant_id = row.get("rater_participant_id")

    if not note_id or not rater_participant_id:
        return _skip("missing_ids")

    if note_id not in existing_row_note_ids:
        return _skip("unknown_note")

    # BinaryBoolフィールドの正規化
    for field in binary_bool_fields:
        if field in row:
            value = row[field]
            if value == "" or value is None or value == "empty":
                row[field] = "0"
            elif value not in ["0", "1"]:
                logging.warning(
                    f"Unexpected value '{value}' for field '{field}' in rating " f"(note_id={note_id}). Setting to '0'."
                )
                row[field] = "0"

    # helpfulness_levelフィールドのバリデーション
    if "helpfulness_level" in row:
        value = row["helpfulness_level"]
        if value not in HELPFULNESS_LEVELS:
            # ここだけ無言で NULL に落としていた。上流が語彙を変えると全件が静かに NULL になり、
            # helpful 系3列が全ノートで 0 になる。ただし ratings は2.19億行あるので per-row の
            # warning は出せない(語彙変更時に数千万行ぶん出てアラームのトークンを埋める)。
            # 既存の skipped Counter に積んでファイル単位で1行にまとめる。
            if value and skipped is not None:
                skipped[f"unknown_level:{value}"] += 1
            row["helpfulness_level"] = None

    # rating_source_bucketedフィールドのバリデーション
    if "rating_source_bucketed" in row:
        value = row["rating_source_bucketed"]
        if value not in ["DEFAULT", "POPULATION_SAMPLED"]:
            row["rating_source_bucketed"] = None

    # 空文字列フィールドをNoneに変換
    for key, value in row.items():
        if value == "" and key not in ["helpfulness_level"]:
            row[key] = None

    # NOT NULLカラム（BinaryBool以外）が空の行はスキップ
    for field in ("created_at_millis", "version", "rated_on_tweet_id"):
        if not row.get(field):
            return _skip("missing_required")

    return True


# COPY TEXT 形式の特殊文字。素通しすると値が壊れるだけでなく COPY 自体が失敗する。
# 特に行頭の `\.` は終端マーカーとみなされ、psycopg2 が
# BadCopyFileFormat: end-of-copy marker corrupt を送出してファイル全体の取り込みが落ちる。
# ratings の suggestion はユーザ入力のフリーテキストなので、これらは実際に混入する。
_COPY_TEXT_ESCAPES = str.maketrans({"\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"})


def _escape_copy_text(value: str) -> str:
    """COPY TEXT 形式に合わせてバックスラッシュ・改行・復帰・タブをエスケープする。"""
    return value.translate(_COPY_TEXT_ESCAPES)


def _iter_lines_without_nul(lines: Iterable[str]) -> Iterator[str]:
    """NUL(0x00) を除去しながら行を流す。

    PostgreSQL のテキスト型は NUL を保存できず、COPY TEXT にも表現が無いので除去しかない。
    さらに csv は NUL を含む行で ``_csv.Error: line contains NUL`` を投げるため、
    パーサに渡す手前で落とす必要がある。X のフリーテキストにはまれに混入する。
    """
    for line in lines:
        yield line.replace("\x00", "") if "\x00" in line else line


# COPY のバッチサイズ。テストから差し替えられるようモジュール定数にする。
BATCH_SIZE = 50000


def _copy_buffer_to_staging(postgresql: Session, buffer: io.StringIO, columns_csv: str) -> None:
    """buffer を staging table へ COPY して commit する。

    ★ コネクションは COPY の直前に毎回取り直すこと。ループの外で1回だけ掴むと、
    Session.commit() でプールへ返却された後の COPY が Session のトランザクション
    外で走り、プールの reset-on-return でロールバックされて無言で消える。
    2026-10-01 に 2.17億行中 5,200万行がこれで失われていたことが判明している。
    """
    buffer.seek(0)
    dbapi_conn = postgresql.connection().connection.dbapi_connection
    with dbapi_conn.cursor() as cur:
        cur.copy_expert(f"COPY {_STAGING_TABLE} ({columns_csv}) FROM STDIN", buffer)
    postgresql.commit()


def _process_rating_rows(reader, postgresql: Session, existing_row_note_ids: set, file_index: int) -> int:
    """ratingsのTSV行をバリデーションし、COPYでstaging tableにバルクロードする。"""
    buffer = io.StringIO()
    row_count = 0
    total_rows = 0
    skipped: Counter = Counter()
    read_rows = 0

    columns_csv = ",".join(_RATING_COLUMNS)

    for index, row in enumerate(reader):
        read_rows += 1
        if not _validate_rating_row(row, existing_row_note_ids, skipped):
            continue

        values = []
        for col in _RATING_COLUMNS:
            val = row.get(col)
            if val is None:
                values.append("\\N")
            else:
                values.append(_escape_copy_text(str(val)))
        buffer.write("\t".join(values) + "\n")
        row_count += 1

        if row_count >= BATCH_SIZE:
            _copy_buffer_to_staging(postgresql, buffer, columns_csv)
            total_rows += row_count
            logging.info(f"COPY {row_count} rows (total: {total_rows}, file {file_index:05d})")
            buffer = io.StringIO()
            row_count = 0

    if row_count > 0:
        _copy_buffer_to_staging(postgresql, buffer, columns_csv)
        total_rows += row_count
        logging.info(f"COPY final {row_count} rows (total: {total_rows}, file {file_index:05d})")

    skipped_total = sum(skipped.values())
    unknown_levels = ",".join(
        f"{k.split(':', 1)[1]}={v}" for k, v in sorted(skipped.items()) if k.startswith("unknown_level:")
    )
    breakdown = (
        f"missing_ids={skipped['missing_ids']} "
        f"unknown_note={skipped['unknown_note']} "
        f"missing_required={skipped['missing_required']} "
        f"unknown_levels={unknown_levels or 'none'}"
    )
    logging.info(
        f"RATINGS_FILE_ROWS file={file_index:05d} read={read_rows} "
        f"kept={total_rows} skipped={skipped_total} {breakdown}"
    )
    return total_rows


def extract_ratings(postgresql: Session, dateString: str, existing_row_note_ids: set, *, is_fallback: bool = False):
    """
    指定日付の評価データをダウンロードし、staging table経由でrow_note_ratingsを全置換する。

    Community Notesの日次スナップショット（全期間分）をstaging tableにCOPYで高速ロードし、
    PK構築後にアトミックなRENAME swapで本番テーブルと入れ替える。重複排除は PK 構築が
    UniqueViolation で失敗したときだけフォールバックとして走る（無条件には走らない）。

    Args:
        postgresql: データベースセッション
        dateString: 日付文字列 (YYYY/MM/DD形式)
        existing_row_note_ids: row_notesテーブルに存在するnote_idのセット（存在チェック用）
        is_fallback: この日付が当日ではなく前日以前へのフォールバック結果かどうか
    """
    _create_staging_table(postgresql)
    total_loaded = 0

    try:
        # ratings-00000.zip から順に404が返るまでダウンロード
        file_index = 0
        # シャードは公開順がバラバラで ratings-00000 が最後に揃うとは限らない。404 をそのまま
        # 終端と見なすと、まだ公開中の後続シャードを欠いた部分スナップショットを取り込んでしまう。
        # 404 に当たるたびに直後2つを HEAD で確認し、どちらか存在すれば「歯抜け」と判断して
        # リトライする(これは notes/noteStatusHistory には適用しない。upsert なので部分取り込みが
        # 何も破壊しないが、ratings は全置換なので歯抜けがそのまま swap されうる)。
        shard_listing_retries = 0
        while True:
            if settings.USE_DUMMY_DATA:
                ratings_url = (
                    "https://raw.githubusercontent.com/codeforjapan/BirdXplorer"
                    "/refs/heads/main/etl/data/notesRating_sample.tsv"
                )
            else:
                ratings_url = (
                    f"https://ton.twimg.com/birdwatch-public-data/{dateString}/noteRatings/ratings-{file_index:05d}.zip"
                )
            logging.info(f"Fetching ratings from: {ratings_url}")

            try:
                res = requests.get(ratings_url)
            except Exception as e:
                logging.error(f"Failed to download ratings data (file {file_index:05d}): {e}")
                file_index += 1
                continue

            if res.status_code == 404:
                found_beyond = _check_ratings_shard_listing_complete(dateString, file_index)
                if not found_beyond:
                    logging.info(
                        f"Ratings file {file_index:05d} not found (404), stopping ratings download for {dateString}"
                    )
                    break

                found_beyond_fmt = [f"{idx:05d}" for idx in found_beyond]
                if shard_listing_retries >= _SNAPSHOT_MAX_RETRIES:
                    raise RuntimeError(
                        f"RATINGS_SHARD_LISTING_INCOMPLETE date={dateString} missing={file_index:05d} "
                        f"found_beyond={found_beyond_fmt} after {_SNAPSHOT_MAX_RETRIES} retries; "
                        "aborting rather than swapping a partial ratings snapshot"
                    )
                shard_listing_retries += 1
                logging.warning(
                    f"Ratings shard {file_index:05d} missing for {dateString} but {found_beyond_fmt} exist "
                    "beyond it; the family is still being published. Waiting before retrying "
                    f"(attempt {shard_listing_retries}/{_SNAPSHOT_MAX_RETRIES})"
                )
                time.sleep(_SNAPSHOT_RETRY_INTERVAL_SECONDS)
                continue

            if res.status_code != 200:
                logging.warning(
                    f"Ratings data not available for {dateString} file {file_index:05d} "
                    f"(status code: {res.status_code})"
                )
                file_index += 1
                continue

            try:
                if settings.USE_DUMMY_DATA:
                    tsv_data = res.content.decode("utf-8").splitlines()
                    reader = csv.DictReader(_iter_lines_without_nul(tsv_data), delimiter="\t")
                    reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                    total_loaded += _process_rating_rows(reader, postgresql, existing_row_note_ids, file_index)
                else:
                    with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                        tsv_filename = f"ratings-{file_index:05d}.tsv"
                        if tsv_filename not in zip_file.namelist():
                            logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                            file_index += 1
                            continue

                        with zip_file.open(tsv_filename) as tsv_file:
                            text_file = io.TextIOWrapper(tsv_file, encoding="utf-8", newline="")
                            reader = csv.DictReader(_iter_lines_without_nul(text_file), delimiter="\t")
                            reader.fieldnames = [stringcase.snakecase(field) for field in reader.fieldnames]
                            total_loaded += _process_rating_rows(reader, postgresql, existing_row_note_ids, file_index)

                logging.info(f"Successfully processed ratings file {file_index:05d} for {dateString}")

            except Exception as e:
                logging.error(f"Error processing ratings data for {dateString} file {file_index:05d}: {e}")
                raise

            # シャードが見つかったので、以降の欠番検知のためにリトライ回数をリセットする
            shard_listing_retries = 0

            # ダミーデータの場合は1ファイルのみなのでループを抜ける
            if settings.USE_DUMMY_DATA:
                break

            file_index += 1

    except Exception as e:
        logging.error(f"Rating extraction failed, cleaning up staging table: {e}")
        _cleanup_staging_table(postgresql)
        raise

    if total_loaded == 0:
        logging.warning("No ratings loaded, skipping table swap")
        _cleanup_staging_table(postgresql)
        # 歯抜け検知があっても、retry と3日分のフォールバックを使い切って1シャードも
        # ロードできない日はありうる。ここで黙って return すると swap がスキップされた
        # まま _run_phase が [PHASE_COMPLETE] を記録し、アラームも鳴らない
        # ——このブランチが潰そうとしていた「サイレントスキップ」そのものになる。
        # 呼び出し元(_run_phase)に例外として伝え、EXTRACT_PHASE_FAILED を鳴らす。
        raise RuntimeError(
            f"RATINGS_NO_SHARDS_LOADED date={dateString} "
            "ratings シャードを1件もロードできなかった。swap を中止する。"
        )

    try:
        # 最低行数: 現在テーブルの推定行数の50%（COUNT(*)はタイムアウトするのでreltuples使用）
        # reltuples はANALYZE未実行時に-1を返すため、その場合はtotal_loadedをフォールバックとして使用
        # （この時点では dedup 前なので staging_count はまだ確定しておらず total_loaded しかない）
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
            # 「reltuples が取れない」かつ「dedup が50%超を削除する」が同時に成立した日だけ、
            # 旧コードなら通った swap が _swap_ratings_table 内の最終チェックで落ちうる。
            # 過去30日19回すべて dedup は0行で、かつ live テーブルは毎日 swap されるため
            # reltuples が長期間 -1/0 のまま放置される状況とは両立しにくい。
            # 万一両立しても、フェイルセーフ（前日データが残り EXTRACT_PHASE_FAILED が鳴る）
            # として働くだけなのでここでは許容する。
            current_count = total_loaded
        min_rows = max(int(current_count * 0.5), 1)

        # 高価な PK 構築（失敗時は dedup で約20分）の前に、行数不足が分かっている日を早期に落とす
        _check_staging_row_count(staging_count=total_loaded, min_rows=min_rows)

        # COPY が無言で失われていないかを、PK 構築に入る前に厳密一致で止める
        _verify_staging_row_count(postgresql, total_loaded)

        # dedup は PK 構築が UniqueViolation で落ちたときだけ走る(_build_staging_pk_with_dedup_fallback)
        staging_count = _build_staging_pk_with_dedup_fallback(postgresql, total_loaded)

        # フォールバックした日だけ、古いスナップショットでの上書きを防ぐ
        if is_fallback:
            _check_not_going_backwards(postgresql, staging_count)

        _swap_ratings_table(postgresql, min_rows=min_rows, staging_count=staging_count)

        logging.info(f"Rating table swap complete: {staging_count} rows loaded")

    except Exception as e:
        logging.error(f"Rating extraction failed, cleaning up staging table: {e}")
        _cleanup_staging_table(postgresql)
        raise


# X が配布する helpfulness_level の値。ここが変わると helpful 系3列が全ノートで 0 になる。
# いまは _validate_rating_row の正規化にのみ使う(集計側の case() はリテラルのまま)。
HELPFULNESS_LEVELS = ("HELPFUL", "SOMEWHAT_HELPFUL", "NOT_HELPFUL")


def recalculate_rating_counts(postgresql: Session) -> int:
    """
    row_note_ratingsテーブルからnotesテーブルの評価集計カラムを再計算する。
    毎日のECS extractタスク内でratings抽出後に呼ばれ、全ノートの集計値を最新化する。

    値が変わる行だけに UPDATE を絞る。以前は無条件に上書きしており、2026-10-07 の実行では
    2,936,582 行を書いて 38.9 分かかっていた。日次で実際に値が変わるのは新しい評価が付いた
    ノートだけなので、大半の書き込みは無駄になる(実数は初回稼働後のログで確認すること。
    無条件 UPDATE の直後に残差を測っても 0 にしかならず、日次の変化量の根拠にはならない)。
    notes は本体 4.4GB で
    rate_count 等はどのインデックスにも入っていないため HOT 更新にはなるが、行の実体は
    毎回書き直されるので WAL が無駄に出る。row_notes で踏んだのと同じ問題。

    Returns:
        更新された行数
    """
    subq = (
        select(
            RowNoteRatingRecord.note_id,
            func.count(RowNoteRatingRecord.note_id).label("rate_count"),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "HELPFUL", 1), else_=0)).label("helpful_count"),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "SOMEWHAT_HELPFUL", 1), else_=0)).label(
                "somewhat_helpful_count"
            ),
            func.sum(case((RowNoteRatingRecord.helpfulness_level == "NOT_HELPFUL", 1), else_=0)).label(
                "not_helpful_count"
            ),
        )
        .group_by(RowNoteRatingRecord.note_id)
        .subquery()
    )

    stmt = (
        update(NoteRecord)
        .where(
            NoteRecord.note_id == subq.c.note_id,
            # 4列のどれかが実際に変わる行だけ書く。= ではなく IS DISTINCT FROM なのは、
            # 既存行の NULL(初期値未設定)を取りこぼさないため。
            # 型は subquery 側が count()/sum() の bigint、notes 側は rate_count だけ
            # numeric(DECIMAL) で残り3列は integer。numeric と bigint の比較は値が等しければ
            # false を返すのでゲートは正しく効く(scale の差も無視される)。
            or_(
                NoteRecord.rate_count.is_distinct_from(subq.c.rate_count),
                NoteRecord.helpful_count.is_distinct_from(subq.c.helpful_count),
                NoteRecord.somewhat_helpful_count.is_distinct_from(subq.c.somewhat_helpful_count),
                NoteRecord.not_helpful_count.is_distinct_from(subq.c.not_helpful_count),
            ),
        )
        .values(
            rate_count=subq.c.rate_count,
            helpful_count=subq.c.helpful_count,
            somewhat_helpful_count=subq.c.somewhat_helpful_count,
            not_helpful_count=subq.c.not_helpful_count,
        )
        # 既定の synchronize_session="auto" は subquery 相関の WHERE を Python 側で評価できず
        # "fetch" に落ちて、更新した全行の note_id を RETURNING で返す(従来は毎日293万件)。
        # この関数は ORM オブジェクトを一切触らないので同期は不要。
        .execution_options(synchronize_session=False)
    )

    result = postgresql.execute(stmt)
    postgresql.commit()
    row_count = result.rowcount

    # 差分ゲートで updated=0 が平常運転になるので、母数を併記して「差分が無い正常日」と
    # 「join が壊れた日」を区別できるようにしたいが、母数の算出は本番実測で7分15秒かかり、
    # しかも主要な故障モード(ゲートが常に偽)では鳴らないことが分かったため見送った。
    # 観測性の作り直しは別途対応する。トークンだけ先に用意しておく。
    logging.info(f"RATING_RECALC updated={row_count}")
    return row_count


# 検知を有効にする母数の下限。row_note_status の行数で測る(検証したい JOIN とは独立な参照)。
# dev 実測で row_note_status は約300万行、うち CRH 到達は 348,354 件(約11.6%)。
# 10万行あれば期待値は約1.2万件なので「1件も無い」は構造的に起こり得ない。
# 新規ステージや小規模な検証環境を誤って落とさないための足切り。
HELPFULED_CHECK_MIN_ROWS = 100_000


def recalculate_has_been_helpfuled(postgresql: Session) -> int:
    """row_note_status から notes.has_been_helpfuled を再計算する。

    このフラグは「HELPFUL 評価が1件でも付いたか」ではなく
    「HELPFUL ステータスに到達したことがあるか」を表す。前者は helpful_count で足りるうえ、
    row_note_ratings 上では大半のノートが該当してしまい、一時公開の判別に使えない。

    note_transform も INSERT 時に同じ条件で値を入れるが、ノートのステータスはその後も動くので
    追随する経路が要る。recalculate_rating_counts は集計カラム4つしか更新しないため、
    このフラグだけが取り残されていた(helpful_count が大きいのに False という行が大量にできる)。

    row_note_status を読むため、必ず Status フェーズより後に呼ぶこと。先に呼ぶと前日の
    ステータスで判定することになる。なお Status が途中で失敗した日に走っても問題ない。
    _process_note_status_rows は 1000 行ごとに commit するので row_note_status は行単位では
    整合しており、行ごとの再計算は正しい値になる(全体としては一部が前日のまま＝翌日収束する)。

    ★単調ではない。first_non_n_m_r_status は不変だが most_recent_non_n_m_r_status は可変で、
    NMR→CRNH→CRH→CRNH と動いたノートは CRH を通過した事実がどちらの列にも残らず False に戻る。
    X 側が中間のステータスを保持しないので、どう実装しても拾えない情報ではある。
    そのうえでスティッキーにせず絶対上書きを選んでいるのは、row_note_status の現在値をそのまま
    写して冪等に保つため。スティッキーにすると一度でも誤って True を書いた行を二度と戻せない。
    巻き戻りの実数は構造上測れないので、代わりに regressed(True→False の件数)をログに出す。

    対象は notes 全件ではなく row_note_status に行があるノートだけ(UPDATE ... FROM は内部結合)。

    has_been_helpfuled は nullable で、NULL 行は _get_publication_status_case のどの分岐にも
    当たらず unpublished に落ちていた。この再計算で False に正規化されるため、それらは
    evaluating に移る。/api/v1/graphs/* の内訳が初回実行で動く点に注意。

    値が変わる行だけに UPDATE を絞る。notes は数百万行あり、毎日全行を書き換えると
    WAL が無駄に膨らむ（row_notes で同じ問題を踏んでいる）。初回だけ大量に更新され、
    以降は差分のみになる。

    Returns:
        更新された行数
    """
    reached_helpful = func.coalesce(
        or_(
            RowNoteStatusRecord.first_non_n_m_r_status == NoteStatus.CURRENTLY_RATED_HELPFUL.value,
            RowNoteStatusRecord.most_recent_non_n_m_r_status == NoteStatus.CURRENTLY_RATED_HELPFUL.value,
        ),
        # 両方 NULL(NMR から一度も抜けていない)だと or_ は NULL を返す。false に倒さないと
        # NULL が書き込まれ、差分ゲートが永久に効かず毎日書き換え続けることになる。
        False,
    )

    # True だった行が False に戻る件数。巻き戻りは異常の兆候なので更新件数とは別に数える
    # (rowcount は両方向の合算なので、ここが跳ねても updated だけ見ていると気付けない)。
    # 初回だけは旧実装(helpful_count > 0)で誤って立っていた行の掃除で跳ねる(dev 実測 6,728 件)。
    # 大規模な巻き戻りにアラームを張るなら、この初回ぶんを除外してから閾値を決めること。
    regressed = postgresql.execute(
        select(func.count())
        .select_from(NoteRecord)
        .join(RowNoteStatusRecord, NoteRecord.note_id == RowNoteStatusRecord.note_id)
        .where(NoteRecord.has_been_helpfuled.is_(True), reached_helpful.is_(False))
    ).scalar_one()

    stmt = (
        update(NoteRecord)
        .where(
            NoteRecord.note_id == RowNoteStatusRecord.note_id,
            NoteRecord.has_been_helpfuled.is_distinct_from(reached_helpful),
        )
        .values(has_been_helpfuled=reached_helpful)
        # 既定の synchronize_session="auto" は、別エンティティの列を含む WHERE や
        # is_distinct_from を Python 側で評価できず "fetch" に落ちて、更新した全行の
        # note_id を RETURNING で返させる。このセッションに NoteRecord の ORM
        # インスタンスは載せていないので同期は不要。
        .execution_options(synchronize_session=False)
    )

    result = postgresql.execute(stmt)
    postgresql.commit()
    row_count = result.rowcount

    # 差分件数だけでは「毎日0件(＝式が1行も当たらず壊れている)」と「差分が無いだけの正常日」を
    # 区別できない。元のバグの症状が temporarilyPublished の恒久的な0件だったので、絶対値も出す。
    total_true, total_scanned = postgresql.execute(
        select(
            func.count().filter(NoteRecord.has_been_helpfuled.is_(True)),
            func.count(),
        )
        .select_from(NoteRecord)
        .join(RowNoteStatusRecord, NoteRecord.note_id == RowNoteStatusRecord.note_id)
    ).one()
    # 検知の母数は row_note_status 単体から取る。JOIN そのものが壊れた場合に
    # 「対象0件だから正常」と誤って安全側に倒れるのを防ぐため(total_scanned は JOIN 由来)。
    first_helpful, recent_helpful, total_status = postgresql.execute(
        select(
            func.count().filter(RowNoteStatusRecord.first_non_n_m_r_status == NoteStatus.CURRENTLY_RATED_HELPFUL.value),
            func.count().filter(
                RowNoteStatusRecord.most_recent_non_n_m_r_status == NoteStatus.CURRENTLY_RATED_HELPFUL.value
            ),
            func.count(),
        ).select_from(RowNoteStatusRecord)
    ).one()

    # 足切り未満だと検知は黙って無効になる。「武装している」と「眠っている」をログで区別できないと
    # 欠陥クラス1(ログは出ているが誰も読まない)の裏返しになるので、状態を明示する。
    armed = total_status >= HELPFULED_CHECK_MIN_ROWS
    logging.info(
        f"HELPFULED_RECALC updated={row_count} regressed={regressed} "
        f"total_true={total_true} total_scanned={total_scanned} "
        f"first_helpful={first_helpful} recent_helpful={recent_helpful} "
        f"empty_check={'armed' if armed else 'skipped'}"
    )

    problem = None
    if armed:
        if total_scanned == 0:
            # notes と row_note_status が1行も結合しない。note_id の型や照合順序が変わるとこうなる。
            # UPDATE も INSERT 側も同じ結合に依存するので、放置すると静かに劣化し続ける。
            problem = f"notes x row_note_status matched 0 rows while row_note_status has {total_status}"
        elif first_helpful == 0 or recent_helpful == 0:
            # 片方の列だけ語彙が変わると total_true は0にならず部分的にしか落ちない。
            # 列ごとに見ればその部分劣化を初日に捕まえられる。
            problem = (
                f"status vocabulary looks changed " f"(first_helpful={first_helpful} recent_helpful={recent_helpful})"
            )
        elif total_true == 0:
            # ★判定に regressed(この実行で消した件数)を使ってはいけない。語彙が変わると INSERT 側も
            # 同じ定数を使うので新たに True になる行が現れず、初日に全部消えたあとは regressed=0 に
            # なって二度と鳴らない。元のバグ(毎日静かに0件)の再現になる。
            problem = "no note is flagged as having reached CURRENTLY_RATED_HELPFUL"

    if problem:
        # ログだけ出しても誰も読まない(それがこのバグが放置された理由そのもの)ので、
        # _run_phase に投げて既存の EXTRACT_PHASE_FAILED アラームに乗せる。
        # UPDATE は commit 済みなので巻き戻らない。検知が目的で、巻き戻しは目的ではない。
        # ここを commit の前に移すと、その日の正当な UPDATE が rollback で毎日捨てられる。
        raise RuntimeError(
            f"HELPFULED_RECALC_EMPTY {problem}. temporarilyPublished becomes zero across all "
            "/api/v1/graphs/* endpoints. The UPDATE itself committed; retrying the task will NOT clear this. "
            "Check the upstream vocabulary: "
            "SELECT first_non_n_m_r_status, count(*) FROM row_note_status GROUP BY 1 ORDER BY 2 DESC;"
        )
    return row_count


# ---------------------------------------------------------------------------
# Staging table helpers for ratings bulk reload
# ---------------------------------------------------------------------------

_STAGING_TABLE = "row_note_ratings_new"
_OLD_TABLE = "row_note_ratings_old"

# テーブルの PK インデックス名を引く。indexdef の文字列マッチは使わない
# （理由は _swap_ratings_table のコメントを参照）。
_PK_NAME_SQL = (
    "SELECT i.relname FROM pg_index x "
    "JOIN pg_class i ON i.oid = x.indexrelid "
    "JOIN pg_class t ON t.oid = x.indrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE t.relname = :table_name AND n.nspname = current_schema() AND x.indisprimary"
)

# _process_rating_rows で COPY に使うカラム順
_RATING_COLUMNS = [
    "note_id",
    "rater_participant_id",
    "created_at_millis",
    "version",
    "agree",
    "disagree",
    "helpful",
    "not_helpful",
    "helpfulness_level",
    "helpful_other",
    "helpful_informative",
    "helpful_clear",
    "helpful_empathetic",
    "helpful_good_sources",
    "helpful_unique_context",
    "helpful_addresses_claim",
    "helpful_important_context",
    "helpful_unbiased_language",
    "not_helpful_other",
    "not_helpful_incorrect",
    "not_helpful_sources_missing_or_unreliable",
    "not_helpful_opinion_speculation_or_bias",
    "not_helpful_missing_key_points",
    "not_helpful_outdated",
    "not_helpful_hard_to_understand",
    "not_helpful_argumentative_or_biased",
    "not_helpful_off_topic",
    "not_helpful_spam_harassment_or_abuse",
    "not_helpful_irrelevant_sources",
    "not_helpful_opinion_speculation",
    "not_helpful_note_not_needed",
    "rated_on_tweet_id",
    "rating_source_bucketed",
    "suggestion",
    "suggestion_id",
]


def _create_staging_table(postgresql: Session) -> None:
    """PKなしのUNLOGGED staging tableを作成する（高速INSERT用）。"""
    postgresql.execute(text(f"DROP TABLE IF EXISTS {_STAGING_TABLE}"))
    postgresql.execute(text(f"DROP TABLE IF EXISTS {_OLD_TABLE}"))
    # INCLUDING ALL でNOT NULL等の制約をコピーし、PKとインデックスだけ除外
    postgresql.execute(
        text(f"CREATE UNLOGGED TABLE {_STAGING_TABLE} " f"(LIKE row_note_ratings INCLUDING ALL EXCLUDING INDEXES)")
    )
    postgresql.commit()
    logging.info("Created staging table for ratings bulk load")


def _deduplicate_staging_table(postgresql: Session) -> int:
    """staging table内の重複PKを除去し、created_at_millisが最新の行を残す。"""
    result = postgresql.execute(text(f"""
            DELETE FROM {_STAGING_TABLE} a USING (
                SELECT ctid, ROW_NUMBER() OVER (
                    PARTITION BY note_id, rater_participant_id
                    ORDER BY created_at_millis DESC, ctid DESC
                ) AS rn
                FROM {_STAGING_TABLE}
            ) b
            WHERE a.ctid = b.ctid AND b.rn > 1
        """))
    deleted = result.rowcount
    postgresql.commit()
    logging.info(f"Deduplicated staging table: removed {deleted} duplicate rows")
    return deleted


def _check_staging_row_count(*, staging_count: int, min_rows: int) -> None:
    """staging table の行数を最低行数と比較。不足なら例外を送出。

    この同じ check は extract_ratings で早期終了用と、_swap_ratings_table で
    最終確認用の2箇所で呼ばれる。フォールバックで dedup が走ると行数が減るため、
    両方の check が意味を持つ。
    """
    if staging_count < min_rows:
        raise RuntimeError(
            f"Staging table has {staging_count} rows, expected at least {min_rows}. "
            "Aborting swap to prevent data loss from incomplete snapshot."
        )


def _verify_staging_row_count(postgresql: Session, expected: int) -> int:
    """staging の実 COUNT(*) と取り込み側のカウントの厳密一致を確認する。

    COPY が無言で失われても total_loaded は増え続けるため、ログだけでは
    欠損が分からない（2026-10-01 の本番欠損はこれで半年規模で見逃された）。
    min_rows の 50% ガードは live の reltuples 基準で、欠損のたびに基準が
    下がるラチェットなので、こちらを厳密一致の最終防衛線として置く。
    """
    actual = postgresql.execute(text(f"SELECT count(*) FROM {_STAGING_TABLE}")).scalar() or 0
    if actual != expected:
        raise RuntimeError(
            f"RATINGS_STAGING_COUNT_MISMATCH expected={expected} actual={actual} "
            "COPY された行が staging に入っていない。swap を中止する。"
        )
    logging.info(f"RATINGS_STAGING_COUNT_VERIFIED rows={actual}")
    return actual


# live_count は reltuples(プランナ推定値)で、原則として実カウントからわずかにずれうる。
# ただし本パイプラインでは、staging テーブル作成時に _build_staging_pk が CREATE INDEX を張り、
# その直後に ANALYZE が実行される。これで作られた統計情報は RENAME を通じて live テーブルに引き継がれ、
# その後の _swap_ratings_table の `ALTER TABLE ... SET LOGGED` 書き換えでも有意に乱されない。
# 実測（2026-10-06）は swap ログが 218,556,095 行、reltuples が 218,556,096 行で、差は 1 行
# = 0.0000% となり、統計情報が実際には高精度であることが確認されている。
# スラックはこの推定値の特性を考慮して非ゼロに保つが、観測された誤差の大きさによってではなく、
# あくまでスナップショット特性のリスク回避としている。
#
# 実測: live テーブルは 217,924,158 → 218,398,084 行(2日間)で、1日あたり約0.11%の増加。
# このブランチが許す最深のフォールバック(3日前)でも live比で約0.33%下回るだけで、旧来の
# 2% 許容ではこの範囲を常に吸収してしまい、ガードが対象とするどのフォールバックに対しても
# 発火しなかった(後退を検知するには約18日分のレグレッションが必要だった)。
#
# 許容を1日分の増加率(約0.11%)より広げると、このガードは対象の後退を検知できなくなり
# 静かに無効化される。次に広げる前に、必ず live テーブルの実測増加率を取り直すこと。
_RATINGS_BACKWARDS_SLACK = 0.9995


def _check_not_going_backwards(postgresql: Session, staging_count: int) -> None:
    """古いスナップショットで新しい live を上書きしないことを確認する。

    row_note_ratings は全置換のため、フォールバックで過去日を取り込むと、より新しい
    データを古いデータで上書きしうる。ratings は累積スナップショットで行数がほぼ単調増加
    するため、行数の比較で後退を検出できる。評価の取り下げによる微減で通常日を止めないよう、
    この判定はフォールバックした日にだけ呼ぶこと。

    live_count は推定値なので _RATINGS_BACKWARDS_SLACK ぶんの許容誤差を見る。
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
    if live_count <= 0:
        # reltuples が取れない（table が未分析、または CREATE UNLOGGED → DROP 後の残骸）場合、
        # 本当に空なのか単に stats が古いのかは区別できない。この場合、後退検出はできず、
        # 他の防衛線（COPY の厳密一致 _verify_staging_row_count、min_rows の 50% ガード）が
        # 動く。フォールバックで本当に古いデータなら、いずれかのガードで落ちる。
        logging.warning(f"RATINGS_BACKWARDS_CHECK_SKIPPED live table estimate unavailable, loaded {staging_count}")
        return
    if staging_count < live_count * _RATINGS_BACKWARDS_SLACK:
        raise RuntimeError(
            f"RATINGS_SNAPSHOT_OLDER_THAN_LIVE staging={staging_count} live={live_count} "
            "フォールバックで取り込んだスナップショットが現在のデータより古い。swap を中止する。"
        )


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
    except DBAPIError as e:
        # psycopg2 は SQLSTATE 23xxx (integrity_constraint_violation) を丸ごと
        # IntegrityError にマップする。dedup で解決できるのは unique_violation (23505)
        # だけなので、pgcode で判別してそれ以外は再送出する。ここを IntegrityError で
        # 素通しすると、無関係な integrity エラーでも32分の dedup を払ったうえで
        # RATING_DUPLICATES_FOUND removed=0 という偽陽性を出す。このトークンは
        # CloudWatch のメトリクスフィルタとアラームに繋がっている(BirdXplorer-cdk #37、
        # dev-bird-xplorer-RatingDuplicatesFound)ので、偽陽性はそのままアラーム誤発火になる。
        if getattr(e.orig, "pgcode", None) != "23505":
            raise
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


def _swap_ratings_table(postgresql: Session, min_rows: int, staging_count: int) -> None:
    """PK 構築済みの staging table を本番テーブルとアトミックにswapする。

    PK は呼び出し前に _build_staging_pk で張っておくこと。
    """
    # 最低行数チェック（不完全スナップショット防止）
    # フォールバックで dedup が走ると行数が減るため、dedup 後の最終確認として意味を持つ。
    _check_staging_row_count(staging_count=staging_count, min_rows=min_rows)
    logging.info(f"Staging table row count: {staging_count} (minimum: {min_rows})")

    # UNLOGGED → LOGGED に変換（crash safety確保）
    logged_start = time.time()
    postgresql.execute(text(f"ALTER TABLE {_STAGING_TABLE} SET LOGGED"))
    postgresql.commit()
    logging.info(f"Staging table SET LOGGED in {time.time() - logged_start:.1f}s")

    # アトミックswap: RENAME + PK制約名の正規化を1トランザクションで実行
    postgresql.execute(text(f"DROP TABLE IF EXISTS {_OLD_TABLE}"))
    postgresql.execute(text(f"ALTER TABLE row_note_ratings RENAME TO {_OLD_TABLE}"))
    postgresql.execute(text(f"ALTER TABLE {_STAGING_TABLE} RENAME TO row_note_ratings"))

    # RENAME TABLE はインデックス名を追随させないので、swap 直後は
    #   live(row_note_ratings)      -> row_note_ratings_new_pkey   (staging のときの名前)
    #   旧(row_note_ratings_old)    -> row_note_ratings_pkey       (正規名を持っていってしまう)
    # という捻れが残る。旧テーブルを先に退かさないと live を正規名にできない（名前衝突）。
    #
    # PK の特定に pg_indexes.indexdef の文字列マッチを使ってはいけない。indexdef は
    # `CREATE UNIQUE INDEX ... USING btree (...)` で "PRIMARY KEY" を含まないため
    # LIKE '%PRIMARY KEY%' は常に何も返さず、この正規化は毎日 no-op になっていた。
    # その結果 live の PK は row_note_ratings_new_pkey のまま残り、翌日
    # _build_staging_pk の「過去の swap 失敗時のみ」のはずの回避リネームが毎日発火していた。
    old_pk_name = postgresql.execute(text(_PK_NAME_SQL), {"table_name": _OLD_TABLE}).scalar()
    if old_pk_name and old_pk_name != f"{_OLD_TABLE}_pkey":
        postgresql.execute(text(f'ALTER INDEX "{old_pk_name}" RENAME TO {_OLD_TABLE}_pkey'))

    new_pk_name = postgresql.execute(text(_PK_NAME_SQL), {"table_name": "row_note_ratings"}).scalar()
    if new_pk_name and new_pk_name != "row_note_ratings_pkey":
        postgresql.execute(text(f'ALTER INDEX "{new_pk_name}" RENAME TO row_note_ratings_pkey'))

    postgresql.commit()
    logging.info("Swapped staging table into production")

    # 旧テーブル削除（ディスク回収）
    postgresql.execute(text(f"DROP TABLE IF EXISTS {_OLD_TABLE}"))
    postgresql.commit()
    logging.info("Dropped old ratings table")


def _cleanup_staging_table(postgresql: Session) -> None:
    """障害時のクリーンアップ: staging/old tableの残骸を削除。"""
    try:
        # abortedトランザクション状態の場合に備えてrollbackしてからDROP
        postgresql.rollback()
        postgresql.execute(text(f"DROP TABLE IF EXISTS {_STAGING_TABLE}"))
        postgresql.execute(text(f"DROP TABLE IF EXISTS {_OLD_TABLE}"))
        postgresql.commit()
    except Exception as e:
        logging.warning(f"Staging table cleanup failed: {e}")
        postgresql.rollback()


# ---- Note Requests (batSignals) ----

TWITTER_SNOWFLAKE_EPOCH_MILLIS = 1288834974657
# snowflake 以前の連番 ID は最大 ~3.0e10。1e12 はその上に余裕を持たせた閾値
# (snowflake 移行直後の数分間に採番された極小 ID は None 側に倒れるが実害なし)
_MIN_SNOWFLAKE_TWEET_ID = 1_000_000_000_000
# 2026-07-01T00:00:00Z。これ以降に作成された tweet のみ X API lookup 対象にする
NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT = 1782864000000


def tweet_created_at_from_id(tweet_id: int) -> Optional[int]:
    """snowflake ID から作成時刻 (ミリ秒 UNIX EPOCH) を算出する。snowflake 以前の旧 ID は None。"""
    if tweet_id < _MIN_SNOWFLAKE_TWEET_ID:
        return None
    return (tweet_id >> 22) + TWITTER_SNOWFLAKE_EPOCH_MILLIS


def _parse_note_request_millis(value):
    if value is None or value == "":
        return None
    try:
        millis = int(value)
    except ValueError:
        return None
    return millis if millis > 0 else None


def _parse_note_request_source_links(value):
    # sourceLinks は公式ドキュメントに反して JSON ではなくカンマ区切りの URL 文字列
    if value is None or value.strip() == "":
        return None
    return [u for u in (s.strip() for s in value.split(",")) if u]


def _parse_note_request_suggestions(value, tweet_id: str):
    if value is None or value.strip() == "":
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        logging.warning(f"Failed to parse suggestions for tweet {tweet_id}: {value[:100]}")
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    return parsed


def parse_note_request_row(row: dict):
    """snake_case 化済みの batSignals TSV 行を row_note_requests のカラム dict に変換する。"""
    tweet_id = (row.get("tweet_id") or "").strip()
    if not tweet_id.isdigit():
        return None
    return {
        "tweet_id": tweet_id,
        "note_request_feed_eligible_at_millis": _parse_note_request_millis(
            row.get("note_request_feed_eligible_at_millis")
        ),
        "api_small_feed_eligible_at_millis": _parse_note_request_millis(row.get("api_small_feed_eligible_at_millis")),
        "api_large_feed_eligible_at_millis": _parse_note_request_millis(row.get("api_large_feed_eligible_at_millis")),
        "api_xl_feed_eligible_at_millis": _parse_note_request_millis(row.get("api_xl_feed_eligible_at_millis")),
        "source_links": _parse_note_request_source_links(row.get("source_links")),
        "suggestions": _parse_note_request_suggestions(row.get("suggestions"), tweet_id),
        "tweet_created_at": tweet_created_at_from_id(int(tweet_id)),
    }


_NOTE_REQUEST_UPDATE_COLUMNS = [
    "note_request_feed_eligible_at_millis",
    "api_small_feed_eligible_at_millis",
    "api_large_feed_eligible_at_millis",
    "api_xl_feed_eligible_at_millis",
    "source_links",
    "suggestions",
]


def _flush_note_request_batch(postgresql: Session, batch: list):
    if not batch:
        return
    stmt = insert(RowNoteRequestRecord).values(batch)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tweet_id"],
        set_={col: getattr(stmt.excluded, col) for col in _NOTE_REQUEST_UPDATE_COLUMNS},
    )
    postgresql.execute(stmt)
    postgresql.commit()


def _log_skipped_note_request_row(file_index: int, line_no: int, line: str, header: list[str], exc: Exception) -> None:
    """毒行を skip する際、根本調査用の識別情報を WARN 出力する。

    `NOTE_REQUEST_ROW_SKIPPED` トークンで CloudWatch メトリクスフィルタ/アラームに接続し、
    tweet_id・例外種別・最長フィールド（肥大の疑いが濃い箇所）を残して原因追跡を可能にする。
    """
    fields = line.split("\t")
    tweet_id = fields[0][:32] if fields else ""
    max_idx = max(range(len(fields)), key=lambda i: len(fields[i])) if fields else -1
    max_len = len(fields[max_idx]) if max_idx >= 0 else 0
    field_name = header[max_idx] if 0 <= max_idx < len(header) else f"col{max_idx}"
    logging.warning(
        f"NOTE_REQUEST_ROW_SKIPPED file={file_index:05d} line={line_no} tweet_id={tweet_id} "
        f"reason={type(exc).__name__}: {str(exc)[:200]} field={field_name} field_len={max_len}"
    )


def extract_note_requests(postgresql: Session):
    """batSignals (Note Requests) の日次スナップショットを row_note_requests に UPSERT する。

    1行/1ファイルの異常はそれぞれ skip して継続し、フェーズ全体を中断させない
    （毒行1件で以降のツイートが取り込まれなくなる silent truncation を構造的に防ぐ）。
    """
    phase_start = time.time()
    for days_ago in range(3):  # 今日、昨日、一昨日
        date = datetime.now() - timedelta(days=days_ago)
        dateString = date.strftime("%Y/%m/%d")

        # batSignals-00000.zip から順に404が返るまでダウンロード（notes/ratings と同じ連番方式）
        file_index = 0
        date_has_data = False
        rows_by_id = {}
        total = 0
        skipped = 0

        while True:
            url = (
                f"https://ton.twimg.com/birdwatch-public-data/{dateString}/"
                f"batSignals/batSignals-{file_index:05d}.zip"
            )
            logging.info(f"Fetching note requests from: {url}")
            res = requests.get(url)

            if res.status_code == 404:
                if file_index == 0:
                    logging.info(f"No note requests data available for {dateString}, trying previous day")
                else:
                    logging.info(
                        f"Note requests file {file_index:05d} not found (404), "
                        f"stopping note requests download for {dateString}"
                    )
                break

            if res.status_code != 200:
                logging.warning(
                    f"Unexpected status code {res.status_code} for note requests file {file_index:05d}, skipping"
                )
                file_index += 1
                continue

            tsv_filename = f"batSignals-{file_index:05d}.tsv"
            try:
                with zipfile.ZipFile(io.BytesIO(res.content)) as zip_file:
                    if tsv_filename not in zip_file.namelist():
                        logging.error(f"TSV file {tsv_filename} not found in the zip file.")
                        file_index += 1
                        continue
                    with zip_file.open(tsv_filename) as tsv_file:
                        tsv_data = tsv_file.read().decode("utf-8").splitlines()
            except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
                # 壊れた zip / 不正 UTF-8 は 1 ファイルに閉じ込めて skip（他ファイル・他日は継続）
                logging.error(
                    f"NOTE_REQUEST_FILE_SKIPPED file={file_index:05d} date={dateString} "
                    f"reason={type(exc).__name__}: {str(exc)[:200]}"
                )
                file_index += 1
                continue

            if not tsv_data:
                logging.warning(f"Empty note requests file {file_index:05d} for {dateString}, skipping")
                file_index += 1
                continue

            # ヘッダ行のパースも 1 ファイルに閉じ込める（行の隔離と同じく phase 全体を止めない）
            try:
                header = [stringcase.snakecase(field) for field in next(csv.reader([tsv_data[0]], delimiter="\t"))]
            except csv.Error as exc:
                logging.error(
                    f"NOTE_REQUEST_FILE_SKIPPED file={file_index:05d} date={dateString} "
                    f"reason=header_{type(exc).__name__}: {str(exc)[:200]}"
                )
                file_index += 1
                continue

            date_has_data = True
            for line_no, line in enumerate(tsv_data[1:], start=2):
                # 1行のパース失敗（csv.Error/JSON/値異常）は skip して継続。フラッシュ(DBエラー)は隔離しない。
                try:
                    values = next(csv.reader([line], delimiter="\t"))
                    parsed = parse_note_request_row(dict(zip(header, values)))
                except Exception as exc:
                    skipped += 1
                    _log_skipped_note_request_row(file_index, line_no, line, header, exc)
                    continue
                if parsed is None:
                    continue
                rows_by_id[parsed["tweet_id"]] = parsed
                if len(rows_by_id) >= 10000:
                    _flush_note_request_batch(postgresql, list(rows_by_id.values()))
                    total += len(rows_by_id)
                    rows_by_id = {}

            file_index += 1

        if date_has_data:
            # 全ファイル処理後、残りをフラッシュ
            _flush_note_request_batch(postgresql, list(rows_by_id.values()))
            total += len(rows_by_id)
            logging.info(
                f"[PHASE_COMPLETE] NoteRequests: {total} rows ({skipped} skipped) "
                f"in {time.time() - phase_start:.1f}s"
            )
            return

    logging.warning("No note requests data found in the last 3 days")


def enqueue_note_request_lookups(postgresql: Session, batch_limit: int = 10000):
    """2026-07-01 以降に作成され、投稿未取得かつ未 enqueue の tweet を tweet-lookup-queue に流す。"""
    if not settings.TWEET_LOOKUP_QUEUE_URL:
        logging.info("TWEET_LOOKUP_QUEUE_URL not set, skipping note request lookups")
        return
    now_millis = int(time.time() * 1000)
    total = 0
    while True:
        rows = postgresql.execute(
            text(
                "SELECT r.tweet_id FROM row_note_requests r "
                "WHERE r.tweet_created_at >= :min_created_at "
                "AND r.lookup_enqueued_at IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM row_posts p WHERE p.post_id = r.tweet_id) "
                "ORDER BY r.tweet_id LIMIT :batch_limit"
            ),
            {
                "min_created_at": NOTE_REQUEST_LOOKUP_MIN_TWEET_CREATED_AT,
                "batch_limit": batch_limit,
            },
        ).fetchall()
        if not rows:
            break
        tweet_ids = [r[0] for r in rows]
        messages = [{"MessageBody": json.dumps({"tweet_id": tweet_id})} for tweet_id in tweet_ids]
        _send_sqs_batch(settings.TWEET_LOOKUP_QUEUE_URL, messages)
        postgresql.execute(
            update(RowNoteRequestRecord)
            .where(RowNoteRequestRecord.tweet_id.in_(tweet_ids))
            .values(lookup_enqueued_at=now_millis)
        )
        postgresql.commit()
        total += len(tweet_ids)
    logging.info(f"Enqueued {total} note request tweet lookups")


def run_note_requests_phase(postgresql: Session):
    """Note Requests の取り込みと lookup enqueue。

    失敗の握りつぶしは _run_phase に集約している。ここで独自に握りつぶすと
    EXTRACT_PHASE_FAILED トークンが出ずアラームに乗らないので、例外はそのまま送出する。
    """
    extract_note_requests(postgresql)
    enqueue_note_request_lookups(postgresql)
