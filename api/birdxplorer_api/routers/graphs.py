"""Graph API Router for analytics endpoints.

Provides time-series aggregations and evaluation metrics for community notes and posts.
"""

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from birdxplorer_common.models import (
    DailyNotesCreationDataItem,
    DailyPostCountDataItem,
    GraphListResponse,
    MonthlyNoteDataItem,
    NoteEvaluationDataItem,
)
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
        >>> _parse_month_range("2025-01_2025-03")  # doctest: +ELLIPSIS
        (datetime.date(2025, 1, 1), datetime.date(2025, 3, 1))
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

    return start_date, end_date


def gen_router(storage: Storage) -> APIRouter:
    """Generate graphs router with dependency-injected storage.

    Args:
        storage: Storage instance for database access

    Returns:
        Configured APIRouter for graph endpoints
    """
    router = APIRouter()

    @router.get("/daily-notes", response_model=GraphListResponse[DailyNotesCreationDataItem])
    def get_daily_notes(
        period: PeriodType = Query(..., description="Time period for data aggregation"),
        status: StatusType = Query("all", description="Filter by note publication status"),
    ) -> GraphListResponse[DailyNotesCreationDataItem]:
        """Get daily community note creation trends.

        Returns aggregated daily counts of community notes grouped by publication status
        for the specified time period.

        **Publication Status Categories:**
        - `published`: Notes with status CURRENTLY_RATED_HELPFUL
        - `temporarilyPublished`: Notes that were previously helpful but now need more ratings or are not helpful
        - `evaluating`: Notes currently being evaluated (NEEDS_MORE_RATINGS, never been helpful)
        - `unpublished`: All other notes

        **Time Periods:**
        - `1week`: Last 7 days
        - `1month`: Last 30 days
        - `3months`: Last 90 days
        - `6months`: Last 180 days
        - `1year`: Last 365 days

        Args:
            period: Time period for aggregation (required)
            status: Filter by specific status or "all" for all statuses (default: "all")

        Returns:
            GraphListResponse containing:
            - data: List of daily aggregated note counts
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if parameters are invalid
        """
        try:
            # Calculate date range from period
            end_date = date.today()
            days = _period_to_days(period)
            start_date = end_date - timedelta(days=days - 1)  # -1 to include today

            # Fetch data from storage
            raw_data = storage.get_daily_note_counts(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                status_filter=status,
            )

            # Fill gaps for continuous time series
            filled_data = storage._fill_daily_gaps(
                data=raw_data,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )

            # Convert to Pydantic models
            items = [DailyNotesCreationDataItem(**item) for item in filled_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("notes")

            return GraphListResponse(data=items, updated_at=updated_at)

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/daily-posts", response_model=GraphListResponse[DailyPostCountDataItem])
    def get_daily_posts(
        range: str = Query(..., description="Month range in format YYYY-MM_YYYY-MM"),
        status: StatusType = Query("all", description="Filter by note publication status"),
    ) -> GraphListResponse[DailyPostCountDataItem]:
        """Get daily post volume trends.

        Returns aggregated daily counts of posts for the specified month range,
        optionally filtered by associated community note status.

        **Status Filter:**
        - `all`: All posts regardless of note status (default)
        - `published`: Posts with published notes
        - `temporarilyPublished`: Posts with temporarily published notes
        - `evaluating`: Posts with notes being evaluated
        - `unpublished`: Posts with no notes or unpublished notes

        **Date Range Format:**
        - Format: `YYYY-MM_YYYY-MM` (e.g., "2025-01_2025-03")
        - Maximum range: 1 year (12 months)
        - Both months inclusive

        Args:
            range: Month range for aggregation (required)
            status: Filter by specific note status or "all" (default: "all")

        Returns:
            GraphListResponse containing:
            - data: List of daily aggregated post counts
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if range format is invalid or exceeds limits
        """
        try:
            # Parse and validate month range
            start_month, end_month = _parse_month_range(range)

            # Calculate actual date range (first day to last day of months)
            from calendar import monthrange

            start_date = start_month
            # Get last day of end month
            last_day = monthrange(end_month.year, end_month.month)[1]
            end_date = end_month.replace(day=last_day)

            # Validate range doesn't exceed 1 year
            days_diff = (end_date - start_date).days
            if days_diff > 365:
                raise ValueError("Date range cannot exceed 1 year (365 days)")

            # Fetch data from storage
            raw_data = storage.get_daily_post_counts(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                status_filter=status,
            )

            # Fill gaps for continuous time series
            # If no data, create template for post structure
            if not raw_data:
                template = {"date": start_date.isoformat(), "post_count": 0}
                if status != "all":
                    template["status"] = status
                raw_data = [template]

            filled_data = storage._fill_daily_gaps(
                data=raw_data,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )

            # Convert to Pydantic models
            items = [DailyPostCountDataItem(**item) for item in filled_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("posts")

            return GraphListResponse(data=items, updated_at=updated_at)

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/notes-annual", response_model=GraphListResponse[MonthlyNoteDataItem])
    def get_notes_annual(
        range: str = Query(..., description="Month range in format YYYY-MM_YYYY-MM"),
        status: StatusType = Query("all", description="Filter by note publication status"),
    ) -> GraphListResponse[MonthlyNoteDataItem]:
        """Get monthly note publication rates.

        Returns aggregated monthly counts of community notes with publication rate
        (ratio of published notes to total notes) for the specified month range.

        **Publication Rate**: published_count / total_notes (0.0 if no notes)

        **Status Filter:**
        - `all`: All notes regardless of status (default)
        - `published`: Only published notes
        - `temporarilyPublished`: Only temporarily published notes
        - `evaluating`: Only notes being evaluated
        - `unpublished`: Only unpublished notes

        **Date Range Format:**
        - Format: `YYYY-MM_YYYY-MM` (e.g., "2024-01_2024-12")
        - Maximum range: 24 months
        - Both months inclusive

        Args:
            range: Month range for aggregation (required)
            status: Filter by specific note status or "all" (default: "all")

        Returns:
            GraphListResponse containing:
            - data: List of monthly aggregated note counts with publication rates
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if range format is invalid or exceeds limits
        """
        try:
            # Parse and validate month range
            start_month, end_month = _parse_month_range(range)

            # Validate range doesn't exceed 24 months
            months_diff = (end_month.year - start_month.year) * 12 + (end_month.month - start_month.month)
            if months_diff > 24:
                raise ValueError("Date range cannot exceed 24 months")

            # Fetch data from storage
            raw_data = storage.get_monthly_note_counts(
                start_month=start_month.strftime("%Y-%m"),
                end_month=end_month.strftime("%Y-%m"),
                status_filter=status,
            )

            # Fill gaps for continuous time series
            # If no data, create template for monthly note structure
            if not raw_data:
                template = {
                    "month": start_month.strftime("%Y-%m"),
                    "published": 0,
                    "evaluating": 0,
                    "unpublished": 0,
                    "temporarilyPublished": 0,
                    "publication_rate": 0.0,
                }
                raw_data = [template]

            filled_data = storage._fill_monthly_gaps(
                data=raw_data,
                start_month=start_month.strftime("%Y-%m"),
                end_month=end_month.strftime("%Y-%m"),
            )

            # Convert to Pydantic models
            items = [MonthlyNoteDataItem(**item) for item in filled_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("notes")

            return GraphListResponse(data=items, updated_at=updated_at)

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/notes-evaluation", response_model=GraphListResponse[NoteEvaluationDataItem])
    def get_notes_evaluation(
        period: PeriodType = Query(..., description="Time period for data aggregation"),
        status: StatusType = Query("all", description="Filter by note publication status"),
        limit: int = Query(200, ge=1, le=200, description="Maximum number of results (max 200)"),
    ) -> GraphListResponse[NoteEvaluationDataItem]:
        """Get individual note evaluation metrics.

        Returns top notes by impression count with helpfulness ratings,
        ordered descending by impression count for moderation review.

        **Metrics:**
        - helpfulCount: Number of helpful ratings
        - notHelpfulCount: Number of not-helpful ratings
        - impressionCount: Number of times note was displayed

        **Ordering**: Results ordered by impressionCount DESC

        **Status Filter:**
        - `all`: All notes regardless of status (default)
        - `published`: Only published notes
        - `temporarilyPublished`: Only temporarily published notes
        - `evaluating`: Only notes being evaluated
        - `unpublished`: Only unpublished notes

        **Time Periods:**
        - `1week`: Last 7 days
        - `1month`: Last 30 days
        - `3months`: Last 90 days
        - `6months`: Last 180 days
        - `1year`: Last 365 days

        Args:
            period: Time period for filtering (required)
            status: Filter by specific status or "all" (default: "all")
            limit: Maximum number of results (default: 200, max: 200)

        Returns:
            GraphListResponse containing:
            - data: List of individual note evaluation metrics
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if parameters are invalid
        """
        try:
            # Validate limit
            if limit > 200:
                raise ValueError("Limit cannot exceed 200")

            # Fetch data from storage
            raw_data = storage.get_note_evaluation_points(
                period=period,
                status_filter=status,
                limit=limit,
            )

            # Convert to Pydantic models
            items = [NoteEvaluationDataItem(**item) for item in raw_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("notes")

            return GraphListResponse(data=items, updated_at=updated_at)

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/notes-evaluation-status", response_model=GraphListResponse[NoteEvaluationDataItem])
    def get_notes_evaluation_status(
        period: PeriodType = Query(..., description="Time period for data aggregation"),
        status: StatusType = Query("all", description="Filter by note publication status"),
        limit: int = Query(200, ge=1, le=200, description="Maximum number of results (max 200)"),
    ) -> GraphListResponse[NoteEvaluationDataItem]:
        """Get individual note evaluation metrics ordered by helpful count.

        Alternative sorting to notes-evaluation endpoint - orders by helpfulCount instead
        of impressionCount for moderation review workflows.

        **Metrics:**
        - helpfulCount: Number of helpful ratings
        - notHelpfulCount: Number of not-helpful ratings
        - impressionCount: Number of times note was displayed

        **Ordering**: Results ordered by helpfulCount DESC (different from /notes-evaluation)

        **Status Filter:**
        - `all`: All notes regardless of status (default)
        - `published`: Only published notes
        - `temporarilyPublished`: Only temporarily published notes
        - `evaluating`: Only notes being evaluated
        - `unpublished`: Only unpublished notes

        **Time Periods:**
        - `1week`: Last 7 days
        - `1month`: Last 30 days
        - `3months`: Last 90 days
        - `6months`: Last 180 days
        - `1year`: Last 365 days

        Args:
            period: Time period for filtering (required)
            status: Filter by specific status or "all" (default: "all")
            limit: Maximum number of results (default: 200, max: 200)

        Returns:
            GraphListResponse containing:
            - data: List of individual note evaluation metrics
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if parameters are invalid
        """
        try:
            # Validate limit
            if limit > 200:
                raise ValueError("Limit cannot exceed 200")

            # Fetch data from storage with helpful_count ordering
            raw_data = storage.get_note_evaluation_points(
                period=period,
                status_filter=status,
                limit=limit,
                order_by="helpful_count",
            )

            # Convert to Pydantic models
            items = [NoteEvaluationDataItem(**item) for item in raw_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("notes")

            return GraphListResponse(data=items, updated_at=updated_at)

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    # TODO: Add remaining endpoint implementations
    # T084: GET /api/v1/graphs/post-influence

    return router
