from datetime import datetime, timezone, tzinfo
from typing import Optional

import pytest

from birdxplorer_common import jst as jst_module
from birdxplorer_common.jst import (
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


def test_jst_today_uses_jst_not_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: Optional[tzinfo] = None) -> "_FrozenDatetime":
            return cls.fromtimestamp(datetime(2025, 12, 1, 23, 30, tzinfo=timezone.utc).timestamp(), tz)

    monkeypatch.setattr(jst_module, "datetime", _FrozenDatetime)

    assert jst_today() == "2025-12-02"
