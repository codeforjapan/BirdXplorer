import calendar
from datetime import datetime
from typing import Tuple
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def _to_ms(dt: datetime) -> int:
    return round(dt.timestamp() * 1000)


def ms_to_jst_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, JST).strftime("%Y-%m-%d")


def ms_to_jst_month(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, JST).strftime("%Y-%m")


def jst_day_range_ms(start_date: str, end_date: str) -> Tuple[int, int]:
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=JST)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999000, tzinfo=JST)
    return _to_ms(start), _to_ms(end)


def jst_month_range_ms(start_month: str, end_month: str) -> Tuple[int, int]:
    start = datetime.strptime(start_month, "%Y-%m").replace(tzinfo=JST)
    end_first = datetime.strptime(end_month, "%Y-%m")
    last_day = calendar.monthrange(end_first.year, end_first.month)[1]
    end = end_first.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999000, tzinfo=JST)
    return _to_ms(start), _to_ms(end)


def jst_today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")
