"""Graph API Router for analytics endpoints.

Provides time-series aggregations and evaluation metrics for community notes and posts.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from birdxplorer_common.models import (
    DailyNotesCreationDataItem,
    DailyPostCountDataItem,
    GraphListResponse,
    MonthlyNoteDataItem,
    NoteEvaluationDataItem,
    PostInfluenceDataItem,
    TwitterTimestamp,
)
from birdxplorer_common.storage import Storage

# Type definitions for query parameters
StatusType = Literal["all", "published", "evaluating", "unpublished", "temporarilyPublished"]


def twitter_timestamp_to_iso_date(ts: int) -> str:
    """Convert TwitterTimestamp (milliseconds) to ISO date string.

    Args:
        ts: Twitter timestamp in milliseconds (Unix epoch, UTC)

    Returns:
        ISO formatted date string (YYYY-MM-DD) in UTC

    Examples:
        >>> twitter_timestamp_to_iso_date(1704067200000)
        '2024-01-01'
    """
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def validate_timestamp_range(
    start_date: int,
    end_date: int,
    max_days: int,
) -> None:
    """Validate timestamp range is within limits.

    Args:
        start_date: Start timestamp in milliseconds
        end_date: End timestamp in milliseconds
        max_days: Maximum allowed range in days

    Raises:
        HTTPException: 400 if validation fails

    Examples:
        >>> validate_timestamp_range(1704067200000, 1704672000000, 30)
        >>> validate_timestamp_range(1704672000000, 1704067200000, 30)
        Traceback (most recent call last):
         ...
        fastapi.exceptions.HTTPException: 400...
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be before or equal to end_date")

    days_diff = (end_date - start_date) / (1000 * 60 * 60 * 24)
    if days_diff > max_days:
        raise HTTPException(status_code=400, detail=f"Date range cannot exceed {max_days} days")


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
        start_date: TwitterTimestamp = Query(..., description="Start timestamp in milliseconds (Unix epoch, UTC)"),
        end_date: TwitterTimestamp = Query(..., description="End timestamp in milliseconds (Unix epoch, UTC)"),
        status: StatusType = Query("all", description="Filter by note publication status"),
    ) -> GraphListResponse[DailyNotesCreationDataItem]:
        """Get daily community note creation trends.

        Returns aggregated daily counts of community notes grouped by publication status
        for the specified date range (maximum 30 days).

        **Publication Status Categories:**
        - `published`: Notes with status CURRENTLY_RATED_HELPFUL
        - `temporarilyPublished`: Notes that were previously helpful but now need more ratings or are not helpful
        - `evaluating`: Notes currently being evaluated (NEEDS_MORE_RATINGS, never been helpful)
        - `unpublished`: All other notes

        **Date Range:**
        - Timestamps must be in milliseconds (Unix epoch, UTC)
        - Maximum range: 30 days
        - start_date must be <= end_date
        - Timestamps must be >= 2006-07-15 (Twitter founding) and <= current time

        Args:
            start_date: Start timestamp in milliseconds (required)
            end_date: End timestamp in milliseconds (required)
            status: Filter by specific status or "all" for all statuses (default: "all")

        Returns:
            GraphListResponse containing:
            - data: List of daily aggregated note counts
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if validation fails, 422 if timestamp format invalid
        """
        try:
            # Validate timestamp range
            validate_timestamp_range(start_date, end_date, max_days=30)

            # Convert timestamps to ISO date strings
            start_date_str = twitter_timestamp_to_iso_date(start_date)
            end_date_str = twitter_timestamp_to_iso_date(end_date)

            # Fetch data from storage
            raw_data = storage.get_daily_note_counts(
                start_date=start_date_str,
                end_date=end_date_str,
                status_filter=status,
            )

            # Fill gaps for continuous time series
            filled_data = storage._fill_daily_gaps(
                data=raw_data,
                start_date=start_date_str,
                end_date=end_date_str,
            )

            # Convert to Pydantic models
            items = [DailyNotesCreationDataItem(**item) for item in filled_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("notes")

            return GraphListResponse(data=items, updated_at=updated_at)

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/daily-posts", response_model=GraphListResponse[DailyPostCountDataItem])
    def get_daily_posts(
        start_date: TwitterTimestamp = Query(..., description="Start timestamp in milliseconds (Unix epoch, UTC)"),
        end_date: TwitterTimestamp = Query(..., description="End timestamp in milliseconds (Unix epoch, UTC)"),
        status: StatusType = Query("all", description="Filter by note publication status"),
    ) -> GraphListResponse[DailyPostCountDataItem]:
        """Get daily post volume trends.

        Returns aggregated daily counts of posts for the specified date range (maximum 30 days),
        optionally filtered by associated community note status.

        **Status Filter:**
        - `all`: All posts regardless of note status (default)
        - `published`: Posts with published notes
        - `temporarilyPublished`: Posts with temporarily published notes
        - `evaluating`: Posts with notes being evaluated
        - `unpublished`: Posts with no notes or unpublished notes

        **Date Range:**
        - Timestamps must be in milliseconds (Unix epoch, UTC)
        - Maximum range: 30 days
        - start_date must be <= end_date
        - Timestamps must be >= 2006-07-15 (Twitter founding) and <= current time

        Args:
            start_date: Start timestamp in milliseconds (required)
            end_date: End timestamp in milliseconds (required)
            status: Filter by specific note status or "all" (default: "all")

        Returns:
            GraphListResponse containing:
            - data: List of daily aggregated post counts
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if validation fails, 422 if timestamp format invalid
        """
        try:
            # Validate timestamp range
            validate_timestamp_range(start_date, end_date, max_days=30)

            # Convert timestamps to ISO date strings
            start_date_str = twitter_timestamp_to_iso_date(start_date)
            end_date_str = twitter_timestamp_to_iso_date(end_date)

            # Fetch data from storage
            raw_data = storage.get_daily_post_counts(
                start_date=start_date_str,
                end_date=end_date_str,
                status_filter=status,
            )

            # Fill gaps for continuous time series
            # If no data, create template for post structure
            if not raw_data:
                template = {"date": start_date_str, "post_count": 0}
                if status != "all":
                    template["status"] = status
                raw_data = [template]

            filled_data = storage._fill_daily_gaps(
                data=raw_data,
                start_date=start_date_str,
                end_date=end_date_str,
            )

            # Convert to Pydantic models
            items = [DailyPostCountDataItem(**item) for item in filled_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("posts")

            return GraphListResponse(data=items, updated_at=updated_at)

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/notes-annual", response_model=GraphListResponse[MonthlyNoteDataItem])
    def get_notes_annual(
        start_date: TwitterTimestamp = Query(..., description="Start timestamp in milliseconds (Unix epoch, UTC)"),
        end_date: TwitterTimestamp = Query(..., description="End timestamp in milliseconds (Unix epoch, UTC)"),
        status: StatusType = Query("all", description="Filter by note publication status"),
    ) -> GraphListResponse[MonthlyNoteDataItem]:
        """Get monthly note publication rates.

        Returns aggregated monthly counts of community notes with publication rate
        (ratio of published notes to total notes) for the specified date range (maximum 365 days).

        **Publication Rate**: published_count / total_notes (0.0 if no notes)

        **Status Filter:**
        - `all`: All notes regardless of status (default)
        - `published`: Only published notes
        - `temporarilyPublished`: Only temporarily published notes
        - `evaluating`: Only notes being evaluated
        - `unpublished`: Only unpublished notes

        **Date Range:**
        - Timestamps must be in milliseconds (Unix epoch, UTC)
        - Maximum range: 365 days (approximately 12 months)
        - start_date must be <= end_date
        - Timestamps must be >= 2006-07-15 (Twitter founding) and <= current time
        - Results are automatically aggregated by month

        Args:
            start_date: Start timestamp in milliseconds (required)
            end_date: End timestamp in milliseconds (required)
            status: Filter by specific note status or "all" (default: "all")

        Returns:
            GraphListResponse containing:
            - data: List of monthly aggregated note counts with publication rates
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if validation fails, 422 if timestamp format invalid
        """
        try:
            # Validate timestamp range (max 365 days for ~12 months)
            validate_timestamp_range(start_date, end_date, max_days=365)

            # Convert timestamps to datetime objects for month extraction
            from datetime import datetime, timezone

            start_dt = datetime.fromtimestamp(int(start_date) / 1000, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(int(end_date) / 1000, tz=timezone.utc)

            # Format as YYYY-MM for storage method
            start_month = start_dt.strftime("%Y-%m")
            end_month = end_dt.strftime("%Y-%m")

            # Fetch data from storage
            raw_data = storage.get_monthly_note_counts(
                start_month=start_month,
                end_month=end_month,
                status_filter=status,
            )

            # Fill gaps for continuous time series
            # If no data, create template for monthly note structure
            if not raw_data:
                template = {
                    "month": start_month,
                    "published": 0,
                    "evaluating": 0,
                    "unpublished": 0,
                    "temporarilyPublished": 0,
                    "publication_rate": 0.0,
                }
                raw_data = [template]

            filled_data = storage._fill_monthly_gaps(
                data=raw_data,
                start_month=start_month,
                end_month=end_month,
            )

            # Convert to Pydantic models
            items = [MonthlyNoteDataItem(**item) for item in filled_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("notes")

            return GraphListResponse(data=items, updated_at=updated_at)

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/notes-evaluation", response_model=GraphListResponse[NoteEvaluationDataItem])
    def get_notes_evaluation(
        start_date: TwitterTimestamp = Query(..., description="Start timestamp in milliseconds (Unix epoch, UTC)"),
        end_date: TwitterTimestamp = Query(..., description="End timestamp in milliseconds (Unix epoch, UTC)"),
        status: StatusType = Query("all", description="Filter by note publication status"),
        limit: int = Query(200, ge=1, le=200, description="Maximum number of results (max 200)"),
    ) -> GraphListResponse[NoteEvaluationDataItem]:
        """Get individual note evaluation metrics.

        Returns top notes by impression count with helpfulness ratings,
        ordered descending by impression count for moderation review (maximum 30 days range).

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

        **Date Range:**
        - Timestamps must be in milliseconds (Unix epoch, UTC)
        - Maximum range: 30 days
        - start_date must be <= end_date
        - Timestamps must be >= 2006-07-15 (Twitter founding) and <= current time

        Args:
            start_date: Start timestamp in milliseconds (required)
            end_date: End timestamp in milliseconds (required)
            status: Filter by specific status or "all" (default: "all")
            limit: Maximum number of results (default: 200, max: 200)

        Returns:
            GraphListResponse containing:
            - data: List of individual note evaluation metrics
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if validation fails, 422 if timestamp format invalid
        """
        try:
            # Validate timestamp range
            validate_timestamp_range(start_date, end_date, max_days=30)

            # Validate limit
            if limit > 200:
                raise ValueError("Limit cannot exceed 200")

            # Convert timestamps to ISO date strings
            start_date_str = twitter_timestamp_to_iso_date(start_date)
            end_date_str = twitter_timestamp_to_iso_date(end_date)

            # Fetch data from storage
            raw_data = storage.get_note_evaluation_points(
                start_date=start_date_str,
                end_date=end_date_str,
                status_filter=status,
                limit=limit,
            )

            # Convert to Pydantic models
            items = [NoteEvaluationDataItem(**item) for item in raw_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("notes")

            return GraphListResponse(data=items, updated_at=updated_at)

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/notes-evaluation-status", response_model=GraphListResponse[NoteEvaluationDataItem])
    def get_notes_evaluation_status(
        start_date: TwitterTimestamp = Query(..., description="Start timestamp in milliseconds (Unix epoch, UTC)"),
        end_date: TwitterTimestamp = Query(..., description="End timestamp in milliseconds (Unix epoch, UTC)"),
        status: StatusType = Query("all", description="Filter by note publication status"),
        limit: int = Query(200, ge=1, le=200, description="Maximum number of results (max 200)"),
    ) -> GraphListResponse[NoteEvaluationDataItem]:
        """Get individual note evaluation metrics ordered by helpful count.

        Alternative sorting to notes-evaluation endpoint - orders by helpfulCount instead
        of impressionCount for moderation review workflows (maximum 30 days range).

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

        **Date Range:**
        - Timestamps must be in milliseconds (Unix epoch, UTC)
        - Maximum range: 30 days
        - start_date must be <= end_date
        - Timestamps must be >= 2006-07-15 (Twitter founding) and <= current time

        Args:
            start_date: Start timestamp in milliseconds (required)
            end_date: End timestamp in milliseconds (required)
            status: Filter by specific status or "all" (default: "all")
            limit: Maximum number of results (default: 200, max: 200)

        Returns:
            GraphListResponse containing:
            - data: List of individual note evaluation metrics
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if validation fails, 422 if timestamp format invalid
        """
        try:
            # Validate timestamp range
            validate_timestamp_range(start_date, end_date, max_days=30)

            # Validate limit
            if limit > 200:
                raise ValueError("Limit cannot exceed 200")

            # Convert timestamps to ISO date strings
            start_date_str = twitter_timestamp_to_iso_date(start_date)
            end_date_str = twitter_timestamp_to_iso_date(end_date)

            # Fetch data from storage with helpful_count ordering
            raw_data = storage.get_note_evaluation_points(
                start_date=start_date_str,
                end_date=end_date_str,
                status_filter=status,
                limit=limit,
                order_by="helpful_count",
            )

            # Convert to Pydantic models
            items = [NoteEvaluationDataItem(**item) for item in raw_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("notes")

            return GraphListResponse(data=items, updated_at=updated_at)

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @router.get("/post-influence", response_model=GraphListResponse[PostInfluenceDataItem])
    def get_post_influence(
        start_date: TwitterTimestamp = Query(..., description="Start timestamp in milliseconds (Unix epoch, UTC)"),
        end_date: TwitterTimestamp = Query(..., description="End timestamp in milliseconds (Unix epoch, UTC)"),
        status: StatusType = Query("all", description="Filter by note publication status"),
        limit: int = Query(200, ge=1, le=200, description="Maximum number of results (max 200)"),
    ) -> GraphListResponse[PostInfluenceDataItem]:
        """Get individual post influence metrics.

        Returns top posts by impression count with engagement metrics (reposts, likes),
        ordered descending by impression count for analyzing viral content (maximum 30 days range).

        **Metrics:**
        - repostCount: Number of times post was reposted
        - likeCount: Number of likes on the post
        - impressionCount: Number of times post was displayed

        **Ordering**: Results ordered by impressionCount DESC

        **Status Filter:**
        - `all`: All posts regardless of note status (default)
        - `published`: Posts with published notes
        - `temporarilyPublished`: Posts with temporarily published notes
        - `evaluating`: Posts with notes being evaluated
        - `unpublished`: Posts with no notes or unpublished notes

        **Date Range:**
        - Timestamps must be in milliseconds (Unix epoch, UTC)
        - Maximum range: 30 days
        - start_date must be <= end_date
        - Timestamps must be >= 2006-07-15 (Twitter founding) and <= current time

        Args:
            start_date: Start timestamp in milliseconds (required)
            end_date: End timestamp in milliseconds (required)
            status: Filter by specific note status or "all" (default: "all")
            limit: Maximum number of results (default: 200, max: 200)

        Returns:
            GraphListResponse containing:
            - data: List of individual post influence metrics
            - updatedAt: Last data update timestamp (YYYY-MM-DD format)

        Raises:
            HTTPException: 400 if validation fails, 422 if timestamp format invalid
        """
        try:
            # Validate timestamp range
            validate_timestamp_range(start_date, end_date, max_days=30)

            # Validate limit
            if limit > 200:
                raise ValueError("Limit cannot exceed 200")

            # Convert timestamps to ISO date strings
            start_date_str = twitter_timestamp_to_iso_date(start_date)
            end_date_str = twitter_timestamp_to_iso_date(end_date)

            # Fetch data from storage
            raw_data = storage.get_post_influence_points(
                start_date=start_date_str,
                end_date=end_date_str,
                status_filter=status,
                limit=limit,
            )

            # Convert to Pydantic models
            items = [PostInfluenceDataItem(**item) for item in raw_data]

            # Get metadata timestamp
            updated_at = storage.get_graph_updated_at("posts")

            return GraphListResponse(data=items, updated_at=updated_at)

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    return router
