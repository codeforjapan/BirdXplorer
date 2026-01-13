"""Graph API Router for analytics endpoints.

Provides time-series aggregations and evaluation metrics for community notes and posts.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, HTTPException, Query
from typing_extensions import Annotated

from birdxplorer_common.storage import Storage

# Type definitions for query parameters
PeriodType = Literal["1week", "1month", "3months", "6months", "1year"]
StatusType = Literal["all", "published", "evaluating", "unpublished", "temporarilyPublished"]


def _period_to_days(period: PeriodType) -> int:
    """Convert period string to number of days.

    Args:
        period: Time period enum value

    Returns:
        Number of days for the period

    Examples:
        >>> _period_to_days("1week")
        7
        >>> _period_to_days("1year")
        365
    """
    period_map = {
        "1week": 7,
        "1month": 30,
        "3months": 90,
        "6months": 180,
        "1year": 365,
    }
    return period_map[period]


def _parse_month_range(range_str: str) -> tuple[date, date]:
    """Parse YYYY-MM_YYYY-MM format into (start, end) date tuple.

    Args:
        range_str: Month range in format "YYYY-MM_YYYY-MM"

    Returns:
        Tuple of (start_date, end_date) as date objects (first day of each month)

    Raises:
        ValueError: If format is invalid or start > end

    Examples:
        >>> _parse_month_range("2025-01_2025-03")
        (date(2025, 1, 1), date(2025, 3, 1))
    """
    from datetime import datetime

    parts = range_str.split("_")
    if len(parts) != 2:
        raise ValueError(f"Invalid range format. Expected YYYY-MM_YYYY-MM, got: {range_str}")

    try:
        start_date = datetime.strptime(parts[0], "%Y-%m").date()
        end_date = datetime.strptime(parts[1], "%Y-%m").date()
    except ValueError as e:
        raise ValueError(f"Invalid month format: {e}")

    if start_date > end_date:
        raise ValueError("Start month must be before or equal to end month")

    # Calculate month difference
    month_diff = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)

    # Check constraints based on the endpoint using this
    # daily-posts: max 1 year (12 months)
    # notes-annual: max 24 months
    # We'll validate in the endpoint itself, just return the parsed dates here

    return start_date, end_date


def gen_router(storage: Storage) -> APIRouter:
    """Generate graphs router with dependency-injected storage.

    Args:
        storage: Storage instance for database access

    Returns:
        Configured APIRouter for graph endpoints
    """
    router = APIRouter()

    # TODO: Add endpoint implementations here
    # T022: GET /api/v1/graphs/daily-notes
    # T034: GET /api/v1/graphs/daily-posts
    # T047: GET /api/v1/graphs/notes-annual
    # T062: GET /api/v1/graphs/notes-evaluation
    # T071: GET /api/v1/graphs/notes-evaluation-status
    # T084: GET /api/v1/graphs/post-influence

    return router
