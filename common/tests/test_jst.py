import re
from datetime import datetime

from birdxplorer_common.jst import (
    JST,
    jst_day_range_ms,
    jst_month_range_ms,
    jst_today,
    ms_to_jst_date,
    ms_to_jst_month,
)


def test_ms_to_jst_date_boundaries() -> None:
    assert ms_to_jst_date(1764514800000) == "2025-12-01"  # 2025-12-01T00:00:00+09:00
    assert ms_to_jst_date(1764514799999) == "2025-11-30"  # その1ms前
    assert ms_to_jst_date(1764601199999) == "2025-12-01"  # 2025-12-01T23:59:59.999+09:00


def test_ms_to_jst_month_boundaries() -> None:
    assert ms_to_jst_month(1764514800000) == "2025-12"
    assert ms_to_jst_month(1764514799999) == "2025-11"


def test_jst_day_range_ms_end_inclusive() -> None:
    assert jst_day_range_ms("2025-12-01", "2025-12-01") == (1764514800000, 1764601199999)


def test_jst_month_range_ms() -> None:
    # 2025-12-01T00:00+09:00 〜 2026-01-31T23:59:59.999+09:00
    assert jst_month_range_ms("2025-12", "2026-01") == (1764514800000, 1769871599999)


def test_jst_today_matches_now_in_jst() -> None:
    before = datetime.now(JST).strftime("%Y-%m-%d")
    today = jst_today()
    after = datetime.now(JST).strftime("%Y-%m-%d")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today)
    assert before <= today <= after
