from typing import Any, Generator, List, Optional, Tuple, Union

from psycopg2.extensions import AsIs, register_adapter
from pydantic import AnyUrl, HttpUrl
from sqlalchemy import (
    ForeignKey,
    and_,
    case,
    create_engine,
    distinct,
    func,
    or_,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.orm.query import RowReturningQuery
from sqlalchemy.types import CHAR, DECIMAL, JSON, Integer, String, Text, Uuid

from .logger import get_logger
from .models import (
    BinaryBool,
    LanguageIdentifier,
)
from .models import Link as LinkModel
from .models import (
    LinkId,
    Media,
    MediaDetails,
    MediaType,
    NonNegativeInt,
)
from .models import Note as NoteModel
from .models import (
    NoteId,
    NotesClassification,
    NotesHarmful,
    NoteStatusHistory,
    ParticipantId,
)
from .models import Post as PostModel
from .models import (
    PostId,
    SummaryString,
)
from .models import Topic as TopicModel
from .models import (
    TopicId,
    TopicLabel,
    TwitterTimestamp,
    UserEnrollment,
    UserId,
    UserName,
)
from .models import XUser as XUserModel
from .settings import GlobalSettings


def adapt_pydantic_http_url(url: AnyUrl) -> AsIs:
    return AsIs(repr(str(url)))


register_adapter(AnyUrl, adapt_pydantic_http_url)


class Base(DeclarativeBase):
    type_annotation_map = {
        LinkId: Uuid,
        TopicId: Integer,
        TopicLabel: JSON,
        NoteId: String,
        ParticipantId: String,
        PostId: String,
        LanguageIdentifier: String,
        TwitterTimestamp: DECIMAL,
        SummaryString: String,
        UserId: String,
        UserName: String,
        HttpUrl: String,
        NonNegativeInt: DECIMAL,
        MediaDetails: JSON,
        BinaryBool: CHAR,
        String: String,
    }


class NoteTopicAssociation(Base):
    __tablename__ = "note_topic"

    note_id: Mapped[NoteId] = mapped_column(ForeignKey("notes.note_id"), primary_key=True)
    topic_id: Mapped[TopicId] = mapped_column(ForeignKey("topics.topic_id"), primary_key=True)
    topic: Mapped["TopicRecord"] = relationship()


class NoteRecord(Base):
    __tablename__ = "notes"

    note_id: Mapped[NoteId] = mapped_column(primary_key=True)
    note_author_participant_id: Mapped[Optional[ParticipantId]] = mapped_column(nullable=True)
    post_id: Mapped[Optional[PostId]] = mapped_column(nullable=True)
    topics: Mapped[List[NoteTopicAssociation]] = relationship()
    language: Mapped[Optional[LanguageIdentifier]] = mapped_column(nullable=True)
    summary: Mapped[SummaryString] = mapped_column(nullable=False)
    current_status: Mapped[Optional[String]] = mapped_column(nullable=True)
    locked_status: Mapped[Optional[String]] = mapped_column(nullable=True)
    created_at: Mapped[Optional[TwitterTimestamp]] = mapped_column(nullable=True)
    has_been_helpfuled: Mapped[bool] = mapped_column(nullable=True, default=False)
    rate_count: Mapped[NonNegativeInt] = mapped_column(nullable=True, default=0)
    helpful_count: Mapped[int] = mapped_column(nullable=True, default=0)
    not_helpful_count: Mapped[int] = mapped_column(nullable=True, default=0)
    somewhat_helpful_count: Mapped[int] = mapped_column(nullable=True, default=0)
    current_status_history: Mapped[str] = mapped_column(Text, nullable=True, default="[]")


class TopicRecord(Base):
    __tablename__ = "topics"

    topic_id: Mapped[TopicId] = mapped_column(primary_key=True)
    label: Mapped[TopicLabel] = mapped_column(nullable=False)


class XUserRecord(Base):
    __tablename__ = "x_users"

    user_id: Mapped[UserId] = mapped_column(primary_key=True)
    name: Mapped[UserName] = mapped_column(nullable=False)
    profile_image: Mapped[HttpUrl] = mapped_column(nullable=False)
    followers_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    following_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)


class LinkRecord(Base):
    __tablename__ = "links"

    link_id: Mapped[LinkId] = mapped_column(primary_key=True)
    url: Mapped[HttpUrl] = mapped_column(nullable=False, index=True)


class PostLinkAssociation(Base):
    __tablename__ = "post_link"

    post_id: Mapped[PostId] = mapped_column(ForeignKey("posts.post_id"), primary_key=True)
    link_id: Mapped[LinkId] = mapped_column(ForeignKey("links.link_id"), primary_key=True)
    link: Mapped[LinkRecord] = relationship()


class PostMediaAssociation(Base):
    __tablename__ = "post_media"

    post_id: Mapped[PostId] = mapped_column(ForeignKey("posts.post_id"), primary_key=True)
    media_key: Mapped[str] = mapped_column(ForeignKey("media.media_key"), primary_key=True)

    # このテーブルにアクセスした時点でほぼ間違いなく MediaRecord も必要なので一気に引っ張る
    media: Mapped["MediaRecord"] = relationship(back_populates="post_media_association", lazy="joined")


class MediaRecord(Base):
    __tablename__ = "media"

    media_key: Mapped[str] = mapped_column(primary_key=True)

    type: Mapped[MediaType] = mapped_column(nullable=False)
    url: Mapped[HttpUrl] = mapped_column(nullable=False)
    width: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    height: Mapped[NonNegativeInt] = mapped_column(nullable=False)

    post_media_association: Mapped["PostMediaAssociation"] = relationship(back_populates="media")


class PostRecord(Base):
    __tablename__ = "posts"

    post_id: Mapped[PostId] = mapped_column(primary_key=True)
    user_id: Mapped[UserId] = mapped_column(ForeignKey("x_users.user_id"), nullable=False)
    user: Mapped[XUserRecord] = relationship()
    text: Mapped[SummaryString] = mapped_column(nullable=False)
    media_details: Mapped[List[PostMediaAssociation]] = relationship()
    created_at: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    aggregated_at: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    like_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    repost_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    impression_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    links: Mapped[List[PostLinkAssociation]] = relationship()


class RowNoteRecord(Base):
    __tablename__ = "row_notes"

    note_id: Mapped[NoteId] = mapped_column(primary_key=True)
    note_author_participant_id: Mapped[Optional[ParticipantId]] = mapped_column(nullable=True)
    created_at_millis: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    tweet_id: Mapped[PostId] = mapped_column(nullable=False)
    believable: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    misleading_other: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    misleading_factual_error: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    misleading_manipulated_media: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    misleading_outdated_information: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    misleading_missing_important_context: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    misleading_unverified_claim_as_fact: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    misleading_satire: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    not_misleading_other: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    not_misleading_factually_correct: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    not_misleading_outdated_but_not_when_written: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    not_misleading_clearly_satire: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    not_misleading_personal_opinion: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    trustworthy_sources: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    is_media_note: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    is_collaborative_note: Mapped[Optional[BinaryBool]] = mapped_column(nullable=True)
    classification: Mapped[Optional[NotesClassification]] = mapped_column(nullable=True)
    harmful: Mapped[Optional[NotesHarmful]] = mapped_column(nullable=True)
    validation_difficulty: Mapped[Optional[SummaryString]] = mapped_column(nullable=True)
    summary: Mapped[SummaryString] = mapped_column(nullable=False)
    language: Mapped[Optional[LanguageIdentifier]] = mapped_column(nullable=True)
    row_post_id: Mapped[Optional[PostId]] = mapped_column(ForeignKey("row_posts.post_id"), nullable=True)
    row_post: Mapped[Optional["RowPostRecord"]] = relationship("RowPostRecord", back_populates="row_notes")


class RowNoteStatusRecord(Base):
    __tablename__ = "row_note_status"

    note_id: Mapped[NoteId] = mapped_column(ForeignKey("row_notes.note_id"), primary_key=True)
    note_author_participant_id: Mapped[ParticipantId] = mapped_column(nullable=False)
    created_at_millis: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    timestamp_millis_of_first_non_n_m_r_status: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    first_non_n_m_r_status: Mapped[String] = mapped_column(nullable=True)
    timestamp_millis_of_current_status: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    current_status: Mapped[String] = mapped_column(nullable=True)
    timestamp_millis_of_latest_non_n_m_r_status: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    most_recent_non_n_m_r_status: Mapped[String] = mapped_column(nullable=True)
    timestamp_millis_of_status_lock: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    locked_status: Mapped[String] = mapped_column(nullable=True)
    timestamp_millis_of_retro_lock: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    current_core_status: Mapped[String] = mapped_column(nullable=True)
    current_expansion_status: Mapped[String] = mapped_column(nullable=True)
    current_group_status: Mapped[String] = mapped_column(nullable=True)
    current_decided_by: Mapped[String] = mapped_column(nullable=True)
    current_modeling_group: Mapped[int] = mapped_column(nullable=True)
    timestamp_millis_of_most_recent_status_change: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    timestamp_millis_of_nmr_due_to_min_stable_crh_time: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    current_multi_group_status: Mapped[String] = mapped_column(nullable=True)
    current_modeling_multi_group: Mapped[int] = mapped_column(nullable=True)
    timestamp_minute_of_final_scoring_output: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    timestamp_millis_of_first_nmr_due_to_min_stable_crh_time: Mapped[TwitterTimestamp] = mapped_column(nullable=True)


class RowNoteRatingRecord(Base):
    __tablename__ = "row_note_ratings"

    note_id: Mapped[NoteId] = mapped_column(primary_key=True)
    rater_participant_id: Mapped[ParticipantId] = mapped_column(primary_key=True)
    created_at_millis: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    agree: Mapped[BinaryBool] = mapped_column(nullable=False)
    disagree: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpfulness_level: Mapped[String] = mapped_column(nullable=False)
    helpful_other: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful_informative: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful_clear: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful_empathetic: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful_good_sources: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful_unique_context: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful_addresses_claim: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful_important_context: Mapped[BinaryBool] = mapped_column(nullable=False)
    helpful_unbiased_language: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_other: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_incorrect: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_sources_missing_or_unreliable: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_opinion_speculation_or_bias: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_missing_key_points: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_outdated: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_hard_to_understand: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_argumentative_or_biased: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_off_topic: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_spam_harassment_or_abuse: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_irrelevant_sources: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_opinion_speculation: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_helpful_note_not_needed: Mapped[BinaryBool] = mapped_column(nullable=False)
    rated_on_tweet_id: Mapped[PostId] = mapped_column(nullable=False)


class RowPostRecord(Base):
    __tablename__ = "row_posts"

    post_id: Mapped[PostId] = mapped_column(primary_key=True)
    author_id: Mapped[UserId] = mapped_column(ForeignKey("row_users.user_id"), nullable=False)
    text: Mapped[SummaryString] = mapped_column(nullable=False)
    created_at: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    aggregated_at: Mapped[TwitterTimestamp] = mapped_column(nullable=True)
    like_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    repost_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    bookmark_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    impression_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    quote_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    reply_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    lang: Mapped[String] = mapped_column()
    row_notes: Mapped["RowNoteRecord"] = relationship("RowNoteRecord", back_populates="row_post")
    user: Mapped["RowUserRecord"] = relationship("RowUserRecord", back_populates="row_post")
    extracted_at: Mapped[TwitterTimestamp] = mapped_column(nullable=False)


class RowPostMediaRecord(Base):
    __tablename__ = "row_post_media"

    media_key: Mapped[String] = mapped_column(primary_key=True, unique=True)

    url: Mapped[String] = mapped_column(nullable=False)
    type: Mapped[MediaType] = mapped_column(nullable=False)
    width: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    height: Mapped[NonNegativeInt] = mapped_column(nullable=False)

    post_id: Mapped[PostId] = mapped_column(ForeignKey("row_posts.post_id"), nullable=False)


class RowPostEmbedURLRecord(Base):
    __tablename__ = "row_post_embed_urls"

    post_id: Mapped[PostId] = mapped_column(ForeignKey("row_posts.post_id"), primary_key=True)
    url: Mapped[String] = mapped_column(primary_key=True)
    expanded_url: Mapped[String] = mapped_column(nullable=False)
    unwound_url: Mapped[String] = mapped_column(nullable=False)


class RowUserRecord(Base):
    __tablename__ = "row_users"

    user_id: Mapped[UserId] = mapped_column(primary_key=True)
    name: Mapped[UserName] = mapped_column(nullable=False)
    user_name: Mapped[UserName] = mapped_column(nullable=False)
    description: Mapped[SummaryString] = mapped_column(nullable=False)
    profile_image_url: Mapped[String] = mapped_column(nullable=False)
    followers_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    following_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    tweet_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False)
    verified_type: Mapped[String] = mapped_column(nullable=False)
    location: Mapped[String] = mapped_column(nullable=False)
    url: Mapped[String] = mapped_column(nullable=False)
    row_post: Mapped["RowPostRecord"] = relationship("RowPostRecord", back_populates="user")


class Storage:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

    @classmethod
    def _parse_status_history(cls, status_history_json: str) -> List[NoteStatusHistory]:
        """Parse JSON string to list of NoteStatusHistory objects."""
        import json

        from .models import NoteStatus, NoteStatusHistory

        try:
            status_history_data = json.loads(status_history_json)
            return [
                NoteStatusHistory(status=NoteStatus(item["status"]), date=item["date"]) for item in status_history_data
            ]
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return []

    @classmethod
    def _get_publication_status_case(cls) -> Any:
        """Reusable CASE expression for publication status derivation.

        Calculates publication status from NoteRecord.current_status and NoteRecord.has_been_helpfuled:
        - published: current_status = CURRENTLY_RATED_HELPFUL
        - temporarilyPublished: has_been_helpfuled = True AND current_status IN
          (NEEDS_MORE_RATINGS, CURRENTLY_RATED_NOT_HELPFUL)
        - evaluating: current_status = NEEDS_MORE_RATINGS AND has_been_helpfuled = False
        - unpublished: all other cases

        Returns:
            SQLAlchemy CASE expression that can be used in queries for aggregation or filtering
        """
        return case(
            (NoteRecord.current_status == "CURRENTLY_RATED_HELPFUL", "published"),
            (
                and_(
                    NoteRecord.has_been_helpfuled == True,  # noqa: E712
                    NoteRecord.current_status.in_(["NEEDS_MORE_RATINGS", "CURRENTLY_RATED_NOT_HELPFUL"]),
                ),
                "temporarilyPublished",
            ),
            (
                and_(
                    NoteRecord.current_status == "NEEDS_MORE_RATINGS",
                    NoteRecord.has_been_helpfuled == False,  # noqa: E712
                ),
                "evaluating",
            ),
            else_="unpublished",
        )

    @classmethod
    def _fill_daily_gaps(
        cls,
        data: List[dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> List[dict[str, Any]]:
        """Fill missing dates with zero counts for continuous daily time series.

        Args:
            data: List of dictionaries with 'date' key (YYYY-MM-DD format) and count fields
            start_date: Start date string in YYYY-MM-DD format
            end_date: End date string in YYYY-MM-DD format

        Returns:
            List of dictionaries with all dates filled, gaps set to zero counts

        Examples:
            >>> data = [
            ...     {"date": "2025-01-01", "published": 5, "evaluating": 10,
            ...      "unpublished": 2, "temporarilyPublished": 1}
            ... ]
            >>> result = Storage._fill_daily_gaps(data, "2025-01-01", "2025-01-03")
            >>> len(result)
            3
            >>> result[0]["date"]
            '2025-01-01'
            >>> result[1]["published"]
            0
        """
        from datetime import date as date_type
        from datetime import timedelta

        # Convert string dates to date objects
        start = date_type.fromisoformat(start_date)
        end = date_type.fromisoformat(end_date)

        # Create map of existing dates
        by_date = {item["date"]: item for item in data}

        # Generate complete range with zero-filled gaps
        result = []
        current = start
        while current <= end:
            date_str = current.isoformat()
            if date_str in by_date:
                result.append(by_date[date_str])
            else:
                # Fill with zeros for missing date
                # Detect data structure from first item if available
                if data and len(data) > 0:
                    first_item = data[0]
                    zero_item: dict[str, Any] = {"date": date_str}
                    # Copy structure from first item, setting numeric values to 0
                    for key, value in first_item.items():
                        if key != "date":
                            if isinstance(value, int):
                                zero_item[key] = 0
                            elif isinstance(value, float):
                                zero_item[key] = 0.0
                            else:
                                zero_item[key] = value  # Preserve non-numeric values
                    result.append(zero_item)
                else:
                    # Default structure for notes data
                    result.append(
                        {
                            "date": date_str,
                            "published": 0,
                            "evaluating": 0,
                            "unpublished": 0,
                            "temporarilyPublished": 0,
                        }
                    )
            current += timedelta(days=1)

        return result

    @classmethod
    def _fill_monthly_gaps(
        cls,
        data: List[dict[str, Any]],
        start_month: str,
        end_month: str,
    ) -> List[dict[str, Any]]:
        """Fill missing months with zero counts for continuous monthly time series.

        Args:
            data: List of dictionaries with 'month' key (YYYY-MM format) and count fields
            start_month: Start month string in YYYY-MM format
            end_month: End month string in YYYY-MM format

        Returns:
            List of dictionaries with all months filled, gaps set to zero counts

        Examples:
            >>> data = [
            ...     {"month": "2025-01", "published": 10, "evaluating": 20, "unpublished": 5,
            ...      "temporarilyPublished": 2, "publication_rate": 0.27}
            ... ]
            >>> result = Storage._fill_monthly_gaps(data, "2025-01", "2025-03")
            >>> len(result)
            3
            >>> result[0]["month"]
            '2025-01'
            >>> result[1]["published"]
            0
        """
        from datetime import date as date_type

        # Parse month strings (YYYY-MM) to first day of month
        start = date_type.fromisoformat(f"{start_month}-01")
        end = date_type.fromisoformat(f"{end_month}-01")

        # Create map of existing months
        by_month = {item["month"]: item for item in data}

        # Generate complete range with zero-filled gaps
        result = []
        current = start
        while current <= end:
            month_str = current.strftime("%Y-%m")
            if month_str in by_month:
                result.append(by_month[month_str])
            else:
                # Fill with zeros for missing month
                result.append(
                    {
                        "month": month_str,
                        "published": 0,
                        "evaluating": 0,
                        "unpublished": 0,
                        "temporarilyPublished": 0,
                        "publication_rate": 0.0,
                    }
                )
            # Move to next month
            if current.month == 12:
                current = date_type(current.year + 1, 1, 1)
            else:
                current = date_type(current.year, current.month + 1, 1)

        return result

    def get_graph_updated_at(self, table: str) -> str:
        """Get last update timestamp for graph data.

        Args:
            table: Table name ("notes" or "posts")

        Returns:
            Last update timestamp in YYYY-MM-DD format (UTC), derived from MAX(created_at)

        Raises:
            ValueError: If table name is invalid
        """
        if table not in ["notes", "posts"]:
            raise ValueError(f"Invalid table name: {table}. Must be 'notes' or 'posts'")

        table_class = NoteRecord if table == "notes" else PostRecord

        with Session(self._engine) as session:
            # Get MAX(created_at) from the table
            result = session.execute(select(func.max(table_class.created_at))).scalar_one_or_none()

            if result is None:
                # No data in table, return current date
                from datetime import datetime, timezone

                return datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Convert TwitterTimestamp (milliseconds) to date
            from datetime import datetime, timezone

            timestamp_seconds = float(result) / 1000
            dt = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")

    def get_daily_note_counts(
        self,
        start_date: str,
        end_date: str,
        status_filter: Optional[str] = None,
        language_filter: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[dict[str, Any]]:
        """Get daily aggregated note creation counts by publication status.

        Args:
            start_date: Start date in YYYY-MM-DD format (inclusive)
            end_date: End date in YYYY-MM-DD format (inclusive)
            status_filter: Optional status filter
                ("all", "published", "evaluating", "unpublished", "temporarilyPublished")

        Returns:
            List of dictionaries with keys: date, published, evaluating, unpublished, temporarilyPublished

        Example response format:
            [
                {"date": "2025-01-01", "published": 5, "evaluating": 10, "unpublished": 2, "temporarilyPublished": 1},
                {"date": "2025-01-02", "published": 3, "evaluating": 12, "unpublished": 4, "temporarilyPublished": 0},
                ...
            ]
        """
        from datetime import datetime, timezone

        # Convert date strings to TwitterTimestamp (milliseconds)
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        start_ts = int(start_dt.timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)

        # Get publication status CASE expression
        status_expr = self._get_publication_status_case()

        # Build aggregation query
        query = select(
            func.date_trunc("day", func.to_timestamp(NoteRecord.created_at / 1000)).label("day"),
            func.count().filter(status_expr == "published").label("published"),
            func.count().filter(status_expr == "evaluating").label("evaluating"),
            func.count().filter(status_expr == "unpublished").label("unpublished"),
            func.count().filter(status_expr == "temporarilyPublished").label("temporarilyPublished"),
        ).where(
            NoteRecord.created_at >= start_ts,
            NoteRecord.created_at <= end_ts,
        )

        # Add status filter if specified
        if status_filter and status_filter != "all":
            query = query.where(status_expr == status_filter)

        # Add language filter (OR across specified languages)
        if language_filter:
            query = query.where(NoteRecord.language.in_(language_filter))

        # Add keywords filter (AND across all keywords, ILIKE search in note summary)
        if keywords:
            for kw in keywords:
                query = query.where(NoteRecord.summary.ilike(f"%{kw}%"))

        query = query.group_by("day").order_by("day")

        # Execute query
        with Session(self._engine) as session:
            result = session.execute(query)
            rows = result.fetchall()

            # Convert to list of dictionaries
            data = []
            for row in rows:
                # Convert timestamp to date string
                date_str = row.day.strftime("%Y-%m-%d")
                data.append(
                    {
                        "date": date_str,
                        "published": int(row.published),
                        "evaluating": int(row.evaluating),
                        "unpublished": int(row.unpublished),
                        "temporarilyPublished": int(row.temporarilyPublished),
                    }
                )

            return data

    def get_daily_post_counts(
        self,
        start_date: str,
        end_date: str,
        status_filter: Optional[str] = None,
        language_filter: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[dict[str, Any]]:
        """Get daily aggregated post counts with optional note status filter.

        Args:
            start_date: Start date in YYYY-MM-DD format (inclusive)
            end_date: End date in YYYY-MM-DD format (inclusive)
            status_filter: Optional status filter for associated notes
                ("all", "published", "evaluating", "unpublished", "temporarilyPublished")

        Returns:
            List of dictionaries with keys: date, post_count, status (optional)

        Example response format:
            [
                {"date": "2025-01-01", "post_count": 150, "status": "published"},
                {"date": "2025-01-02", "post_count": 142, "status": "published"},
                ...
            ]
        """
        from datetime import datetime, timezone

        # Convert date strings to TwitterTimestamp (milliseconds)
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        start_ts = int(start_dt.timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)

        # Get publication status CASE expression
        status_expr = self._get_publication_status_case()

        # Build query - join with notes when status/language/keywords filter is needed
        needs_note_join = (status_filter and status_filter != "all") or language_filter or keywords

        if not needs_note_join:
            # When no filter, just count all posts
            query = (
                select(
                    func.date_trunc("day", func.to_timestamp(PostRecord.created_at / 1000)).label("day"),
                    func.count(PostRecord.post_id).label("post_count"),
                )
                .where(
                    PostRecord.created_at >= start_ts,
                    PostRecord.created_at <= end_ts,
                )
                .group_by("day")
                .order_by("day")
            )
        else:
            # Join with notes for status/language/keywords filtering
            query = (
                select(
                    func.date_trunc("day", func.to_timestamp(PostRecord.created_at / 1000)).label("day"),
                    func.count(distinct(PostRecord.post_id)).label("post_count"),
                )
                .select_from(PostRecord)
                .outerjoin(NoteRecord, PostRecord.post_id == NoteRecord.post_id)
                .where(
                    PostRecord.created_at >= start_ts,
                    PostRecord.created_at <= end_ts,
                )
            )

            # Apply status filter
            # Posts without notes are considered "unpublished"
            if status_filter and status_filter != "all":
                if status_filter == "unpublished":
                    query = query.where(or_(NoteRecord.note_id.is_(None), status_expr == "unpublished"))
                else:
                    query = query.where(status_expr == status_filter)

            # Apply language filter (OR across specified languages)
            if language_filter:
                query = query.where(NoteRecord.language.in_(language_filter))

            # Apply keywords filter (AND across all keywords, ILIKE search in note summary)
            if keywords:
                for kw in keywords:
                    query = query.where(NoteRecord.summary.ilike(f"%{kw}%"))

            query = query.group_by("day").order_by("day")

        # Execute query
        with Session(self._engine) as session:
            result = session.execute(query)
            rows = result.fetchall()

            # Convert to list of dictionaries
            data = []
            for row in rows:
                # Convert timestamp to date string
                date_str = row.day.strftime("%Y-%m-%d")
                item: dict[str, Any] = {
                    "date": date_str,
                    "post_count": int(row.post_count),
                }

                # Add status only if filtering by specific status
                if status_filter and status_filter != "all":
                    item["status"] = status_filter

                data.append(item)

            return data

    def get_monthly_note_counts(
        self,
        start_month: str,
        end_month: str,
        status_filter: Optional[str] = None,
        language_filter: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[dict[str, Any]]:
        """Get monthly aggregated note creation counts with publication rate.

        Args:
            start_month: Start month in YYYY-MM format (inclusive)
            end_month: End month in YYYY-MM format (inclusive)
            status_filter: Optional status filter
                ("all", "published", "evaluating", "unpublished", "temporarilyPublished")

        Returns:
            List of dictionaries with keys: month, published, evaluating, unpublished,
            temporarilyPublished, publication_rate

        Example response format:
            [
                {
                    "month": "2025-01",
                    "published": 342,
                    "evaluating": 687,
                    "unpublished": 125,
                    "temporarilyPublished": 98,
                    "publication_rate": 0.273
                },
                ...
            ]
        """
        from datetime import datetime, timezone

        # Convert month strings to dates (first day of each month)
        start_date = datetime.strptime(start_month, "%Y-%m").replace(day=1, tzinfo=timezone.utc)
        # Get last day of end month
        from calendar import monthrange

        end_year, end_month_num = map(int, end_month.split("-"))
        last_day = monthrange(end_year, end_month_num)[1]
        end_date = datetime.strptime(end_month, "%Y-%m").replace(
            day=last_day, hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

        # Convert to TwitterTimestamp (milliseconds)
        start_ts = int(start_date.timestamp() * 1000)
        end_ts = int(end_date.timestamp() * 1000)

        # Get publication status CASE expression
        status_expr = self._get_publication_status_case()

        # Build aggregation query
        query = select(
            func.date_trunc("month", func.to_timestamp(NoteRecord.created_at / 1000)).label("month"),
            func.count().filter(status_expr == "published").label("published"),
            func.count().filter(status_expr == "evaluating").label("evaluating"),
            func.count().filter(status_expr == "unpublished").label("unpublished"),
            func.count().filter(status_expr == "temporarilyPublished").label("temporarilyPublished"),
        ).where(
            NoteRecord.created_at >= start_ts,
            NoteRecord.created_at <= end_ts,
        )

        # Add status filter if specified
        if status_filter and status_filter != "all":
            query = query.where(status_expr == status_filter)

        # Add language filter (OR across specified languages)
        if language_filter:
            query = query.where(NoteRecord.language.in_(language_filter))

        # Add keywords filter (AND across all keywords, ILIKE search in note summary)
        if keywords:
            for kw in keywords:
                query = query.where(NoteRecord.summary.ilike(f"%{kw}%"))

        query = query.group_by("month").order_by("month")

        # Execute query
        with Session(self._engine) as session:
            result = session.execute(query)
            rows = result.fetchall()

            # Convert to list of dictionaries with publication rate
            data = []
            for row in rows:
                # Convert timestamp to month string
                month_str = row.month.strftime("%Y-%m")

                published = int(row.published)
                evaluating = int(row.evaluating)
                unpublished = int(row.unpublished)
                temporarily_published = int(row.temporarilyPublished)

                # Calculate publication rate (avoid division by zero)
                total = published + evaluating + unpublished + temporarily_published
                publication_rate = published / total if total > 0 else 0.0

                data.append(
                    {
                        "month": month_str,
                        "published": published,
                        "evaluating": evaluating,
                        "unpublished": unpublished,
                        "temporarilyPublished": temporarily_published,
                        "publication_rate": publication_rate,
                    }
                )

            return data

    def get_note_evaluation_points(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 200,
        order_by: str = "impression_count",
        language_filter: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[dict[str, Any]]:
        """Get individual note evaluation metrics with configurable ordering.

        Args:
            start_date: Optional start date filter (ISO format YYYY-MM-DD)
            end_date: Optional end date filter (ISO format YYYY-MM-DD)
            status_filter: Optional status filter
                ("all", "published", "evaluating", "unpublished", "temporarilyPublished")
            limit: Maximum number of results to return (default: 200, max: 200)
            order_by: Field to order by - "impression_count" (default) or "helpful_count"

        Returns:
            List of dictionaries with keys: note_id, name, helpful_count, not_helpful_count,
            impression_count, status. Ordered by specified field DESC.

        Example response format:
            [
                {
                    "note_id": "1234567890123456789",
                    "name": "Note about...",
                    "helpful_count": 127,
                    "not_helpful_count": 8,
                    "impression_count": 45623,
                    "status": "published"
                },
                ...
            ]
        """
        from datetime import datetime, timezone

        # Validate and cap limit
        if limit > 200:
            limit = 200

        # Get publication status CASE expression
        status_expr = self._get_publication_status_case()

        # Build query with notes-posts JOIN
        query = (
            select(
                NoteRecord.note_id,
                NoteRecord.summary.label("name"),
                NoteRecord.helpful_count.label("helpful_count"),
                NoteRecord.not_helpful_count.label("not_helpful_count"),
                PostRecord.impression_count.label("impression_count"),
                status_expr.label("status"),
            )
            .select_from(NoteRecord)
            .join(PostRecord, NoteRecord.post_id == PostRecord.post_id)
        )

        # Add date range filter if specified
        if start_date and end_date:
            # Convert ISO date strings to TwitterTimestamp (milliseconds)
            start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            start_ts = int(start_dt.timestamp() * 1000)
            end_ts = int(end_dt.timestamp() * 1000)

            query = query.where(
                NoteRecord.created_at >= start_ts,
                NoteRecord.created_at <= end_ts,
            )

        # Add status filter if specified
        if status_filter and status_filter != "all":
            query = query.where(status_expr == status_filter)

        # Add language filter (OR across specified languages)
        if language_filter:
            query = query.where(NoteRecord.language.in_(language_filter))

        # Add keywords filter (AND across all keywords, ILIKE search in note summary)
        if keywords:
            for kw in keywords:
                query = query.where(NoteRecord.summary.ilike(f"%{kw}%"))

        # Order by specified field descending and apply limit
        if order_by == "helpful_count":
            query = query.order_by(NoteRecord.helpful_count.desc()).limit(limit)
        else:  # Default to impression_count
            query = query.order_by(PostRecord.impression_count.desc()).limit(limit)

        # Execute query
        with Session(self._engine) as session:
            result = session.execute(query)
            rows = result.fetchall()

            # Convert to list of dictionaries
            data = []
            for row in rows:
                data.append(
                    {
                        "note_id": str(row.note_id),
                        "name": row.name[:100] if row.name else "",  # Truncate to 100 chars
                        "helpful_count": int(row.helpful_count) if row.helpful_count else 0,
                        "not_helpful_count": int(row.not_helpful_count) if row.not_helpful_count else 0,
                        "impression_count": int(row.impression_count) if row.impression_count else 0,
                        "status": row.status,
                    }
                )

            return data

    def get_post_influence_points(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 200,
        language_filter: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[dict[str, Any]]:
        """Get individual post influence metrics ordered by impression count.

        Args:
            start_date: Optional start date filter (ISO format YYYY-MM-DD)
            end_date: Optional end date filter (ISO format YYYY-MM-DD)
            status_filter: Optional status filter for associated notes
                ("all", "published", "evaluating", "unpublished", "temporarilyPublished")
            limit: Maximum number of results to return (default: 200, max: 200)

        Returns:
            List of dictionaries with keys: post_id, name, repost_count, like_count,
            impression_count, status (optional). Ordered by impression_count DESC.

        Example response format:
            [
                {
                    "post_id": "1234567890123456789",
                    "name": "Post about...",
                    "repost_count": 3421,
                    "like_count": 8765,
                    "impression_count": 234567,
                    "status": "published"
                },
                ...
            ]
        """
        from datetime import datetime, timezone

        # Validate and cap limit
        if limit > 200:
            limit = 200

        # Get publication status CASE expression
        status_expr = self._get_publication_status_case()

        # Build query - join with notes when status/language/keywords filter is needed
        needs_note_join = (status_filter and status_filter != "all") or language_filter or keywords

        if not needs_note_join:
            # No filter requiring note join - just get posts
            query = select(
                PostRecord.post_id,
                PostRecord.text.label("name"),
                PostRecord.repost_count,
                PostRecord.like_count,
                PostRecord.impression_count,
            ).select_from(PostRecord)
        else:
            # Join with notes for status/language/keywords filtering
            query = (
                select(
                    PostRecord.post_id,
                    PostRecord.text.label("name"),
                    PostRecord.repost_count,
                    PostRecord.like_count,
                    PostRecord.impression_count,
                    status_expr.label("status"),
                )
                .select_from(PostRecord)
                .outerjoin(NoteRecord, PostRecord.post_id == NoteRecord.post_id)
            )

        # Add date range filter if specified
        if start_date and end_date:
            # Convert ISO date strings to TwitterTimestamp (milliseconds)
            start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            start_ts = int(start_dt.timestamp() * 1000)
            end_ts = int(end_dt.timestamp() * 1000)

            query = query.where(
                PostRecord.created_at >= start_ts,
                PostRecord.created_at <= end_ts,
            )

        # Add status filter if specified
        if status_filter and status_filter != "all":
            if status_filter == "unpublished":
                # Posts without notes or with unpublished notes
                query = query.where(or_(NoteRecord.note_id.is_(None), status_expr == "unpublished"))
            else:
                query = query.where(status_expr == status_filter)

        # Add language filter (OR across specified languages)
        if language_filter:
            query = query.where(NoteRecord.language.in_(language_filter))

        # Add keywords filter (AND across all keywords, ILIKE search in note summary)
        if keywords:
            for kw in keywords:
                query = query.where(NoteRecord.summary.ilike(f"%{kw}%"))

        # Order by impression count descending and apply limit
        query = query.order_by(PostRecord.impression_count.desc()).limit(limit)

        # Execute query
        with Session(self._engine) as session:
            result = session.execute(query)
            rows = result.fetchall()

            # Convert to list of dictionaries
            data = []
            for row in rows:
                item: dict[str, Any] = {
                    "post_id": str(row.post_id),
                    "name": row.name[:100] if row.name else "",  # Truncate to 100 chars
                    "repost_count": int(row.repost_count) if row.repost_count else 0,
                    "like_count": int(row.like_count) if row.like_count else 0,
                    "impression_count": int(row.impression_count) if row.impression_count else 0,
                }

                # Add status only if filtering by specific status
                if status_filter and status_filter != "all":
                    item["status"] = getattr(row, "status", None)

                data.append(item)

            return data

    def get_top_note_accounts(
        self,
        start_date: str,
        end_date: str,
        prev_start_date: str,
        prev_end_date: str,
        status_filter: str = "all",
        limit: int = 10,
        language_filter: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[dict[str, Any]]:
        """Get top accounts by note count for a period with period-over-period comparison.

        Args:
            start_date: Current period start date in YYYY-MM-DD format (inclusive)
            end_date: Current period end date in YYYY-MM-DD format (inclusive)
            prev_start_date: Previous period start date in YYYY-MM-DD format (inclusive)
            prev_end_date: Previous period end date in YYYY-MM-DD format (inclusive)
            status_filter: Optional status filter
                ("all", "published", "evaluating", "unpublished", "temporarilyPublished")
            limit: Maximum number of top accounts to return (default: 10)

        Returns:
            List of dictionaries with keys: rank, username, note_count, note_count_change.
            Ordered by note_count descending.

        Example response format:
            [
                {"rank": 1, "username": "User1", "note_count": 42, "note_count_change": 10},
                {"rank": 2, "username": "User2", "note_count": 35, "note_count_change": -3},
                ...
            ]
        """
        from datetime import datetime, timezone

        def _to_ts_range(s: str, e: str) -> Tuple[int, int]:
            s_dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
            e_dt = datetime.fromisoformat(e).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            return int(s_dt.timestamp() * 1000), int(e_dt.timestamp() * 1000)

        cur_start_ts, cur_end_ts = _to_ts_range(start_date, end_date)
        prev_start_ts, prev_end_ts = _to_ts_range(prev_start_date, prev_end_date)

        status_expr = self._get_publication_status_case()

        def _build_count_query(start_ts: int, end_ts: int) -> Any:
            q = (
                select(
                    XUserRecord.user_id,
                    XUserRecord.name,
                    func.count(NoteRecord.note_id).label("note_count"),
                )
                .select_from(NoteRecord)
                .join(PostRecord, NoteRecord.post_id == PostRecord.post_id)
                .join(XUserRecord, PostRecord.user_id == XUserRecord.user_id)
                .where(
                    NoteRecord.created_at >= start_ts,
                    NoteRecord.created_at <= end_ts,
                )
            )
            if status_filter and status_filter != "all":
                q = q.where(status_expr == status_filter)
            if language_filter:
                q = q.where(NoteRecord.language.in_(language_filter))
            if keywords:
                for kw in keywords:
                    q = q.where(NoteRecord.summary.ilike(f"%{kw}%"))
            return q.group_by(XUserRecord.user_id, XUserRecord.name)

        with Session(self._engine) as session:
            cur_rows = session.execute(_build_count_query(cur_start_ts, cur_end_ts)).fetchall()
            prev_rows = session.execute(_build_count_query(prev_start_ts, prev_end_ts)).fetchall()

        # Build prev lookup: user_id → note_count
        prev_counts: dict[str, int] = {str(row.user_id): int(row.note_count) for row in prev_rows}

        # Sort current by note_count descending and take top limit
        sorted_cur = sorted(cur_rows, key=lambda r: int(r.note_count), reverse=True)[:limit]

        data = []
        for rank_idx, row in enumerate(sorted_cur, start=1):
            user_id_str = str(row.user_id)
            cur_count = int(row.note_count)
            prev_count = prev_counts.get(user_id_str, 0)
            data.append(
                {
                    "rank": rank_idx,
                    "username": str(row.name),
                    "note_count": cur_count,
                    "note_count_change": cur_count - prev_count,
                }
            )

        return data

    @classmethod
    def _media_record_to_model(cls, media_record: MediaRecord) -> Media:
        return Media(
            media_key=media_record.media_key,
            type=media_record.type,
            url=media_record.url,
            width=media_record.width,
            height=media_record.height,
        )

    @classmethod
    def _post_record_media_details_to_model(cls, post_record: PostRecord) -> MediaDetails:
        if post_record.media_details == []:
            return []
        return [cls._media_record_to_model(post_media.media) for post_media in post_record.media_details]

    @classmethod
    def _post_record_to_model(cls, post_record: PostRecord, *, with_media: Union[bool, None]) -> PostModel:
        # post_record.media_detailsにアクセスしたタイミングでメディア情報を一気に引っ張るクエリが発行される
        # media情報がいらない場合はクエリを発行したくないので先にwith_mediaをチェック
        media_details = cls._post_record_media_details_to_model(post_record) if with_media else []

        # created_atとaggregated_atのデフォルト値設定
        DEFAULT_TIMESTAMP = 1152921600001
        created_at = post_record.created_at if post_record.created_at is not None else DEFAULT_TIMESTAMP
        aggregated_at = post_record.aggregated_at if post_record.aggregated_at is not None else created_at

        return PostModel(
            post_id=post_record.post_id,
            x_user_id=post_record.user_id,
            x_user=XUserModel(
                user_id=post_record.user.user_id,
                name=post_record.user.name,
                profile_image=post_record.user.profile_image,
                followers_count=post_record.user.followers_count,
                following_count=post_record.user.following_count,
            ),
            text=post_record.text,
            media_details=media_details,
            created_at=created_at,
            aggregated_at=aggregated_at,
            like_count=post_record.like_count,
            repost_count=post_record.repost_count,
            impression_count=post_record.impression_count,
            links=[LinkModel(link_id=link.link_id, url=link.link.url) for link in post_record.links],
        )

    def get_user_enrollment_by_participant_id(self, participant_id: ParticipantId) -> UserEnrollment:
        raise NotImplementedError

    def get_topics(self) -> Generator[TopicModel, None, None]:
        with Session(self.engine) as sess:
            subq = (
                select(NoteTopicAssociation.topic_id, func.count().label("reference_count"))
                .group_by(NoteTopicAssociation.topic_id)
                .subquery()
            )
            for topic_record, reference_count in (
                sess.query(TopicRecord, subq.c.reference_count)
                .outerjoin(subq, TopicRecord.topic_id == subq.c.topic_id)
                .all()
            ):
                yield TopicModel(
                    topic_id=topic_record.topic_id,
                    label=topic_record.label,
                    reference_count=reference_count or 0,
                )

    def get_notes(
        self,
        note_ids: Union[List[NoteId], None] = None,
        created_at_from: Union[None, TwitterTimestamp] = None,
        created_at_to: Union[None, TwitterTimestamp] = None,
        topic_ids: Union[List[TopicId], None] = None,
        post_ids: Union[List[PostId], None] = None,
        current_status: Union[None, List[str]] = None,
        language: Union[LanguageIdentifier, None] = None,
        search_text: Union[str, None] = None,
        offset: Union[int, None] = None,
        limit: int = 100,
    ) -> Generator[NoteModel, None, None]:
        with Session(self.engine) as sess:
            query = sess.query(NoteRecord)
            if note_ids is not None:
                query = query.filter(NoteRecord.note_id.in_(note_ids))
            if created_at_from is not None:
                query = query.filter(NoteRecord.created_at >= created_at_from)
            if created_at_to is not None:
                query = query.filter(NoteRecord.created_at <= created_at_to)
            if topic_ids is not None:
                # 同じトピックIDを持つノートを取得するためのサブクエリ
                # とりあえずANDを実装
                subq = (
                    select(NoteTopicAssociation.note_id)
                    .group_by(NoteTopicAssociation.note_id)
                    .having(func.bool_or(NoteTopicAssociation.topic_id.in_(topic_ids)))
                    .subquery()
                )
                query = query.join(subq, NoteRecord.note_id == subq.c.note_id)
            if post_ids is not None:
                query = query.filter(NoteRecord.post_id.in_(post_ids))
            if language is not None:
                query = query.filter(NoteRecord.language == language)
            if current_status is not None:
                query = query.filter(NoteRecord.current_status.in_(current_status))
            if search_text is not None:
                query = query.filter(NoteRecord.summary.like(f"%{search_text}%"))
            if offset is not None:
                query = query.offset(offset)
            query = query.limit(limit)
            for note_record in query.all():
                try:
                    yield NoteModel(
                        note_id=note_record.note_id,
                        note_author_participant_id=note_record.note_author_participant_id,
                        post_id=note_record.post_id,
                        topics=[
                            TopicModel(
                                topic_id=topic.topic_id,
                                label=topic.topic.label,
                                reference_count=0,
                                # reference_count=sess.query(func.count(NoteTopicAssociation.note_id))
                                # .filter(NoteTopicAssociation.topic_id == topic.topic_id)
                                # .scalar()
                                # or 0,
                            )
                            for topic in note_record.topics
                        ],
                        language=(
                            LanguageIdentifier.normalize(note_record.language)
                            if note_record.language
                            else LanguageIdentifier.OTHER
                        ),
                        summary=note_record.summary,
                        current_status=note_record.current_status,
                        created_at=note_record.created_at,
                        has_been_helpfuled=(
                            note_record.has_been_helpfuled if note_record.has_been_helpfuled is not None else False
                        ),
                        rate_count=note_record.rate_count if note_record.rate_count is not None else 0,
                        helpful_count=note_record.helpful_count if note_record.helpful_count is not None else 0,
                        not_helpful_count=(
                            note_record.not_helpful_count if note_record.not_helpful_count is not None else 0
                        ),
                        somewhat_helpful_count=(
                            note_record.somewhat_helpful_count if note_record.somewhat_helpful_count is not None else 0
                        ),
                        current_status_history=self._parse_status_history(note_record.current_status_history),
                    )
                except Exception as e:
                    # Skip invalid records and log warning
                    logger = get_logger()
                    logger.warning(f"Skipping invalid note record (note_id={note_record.note_id}): {str(e)}")
                    continue

    def get_number_of_notes(
        self,
        note_ids: Union[List[NoteId], None] = None,
        created_at_from: Union[None, TwitterTimestamp] = None,
        created_at_to: Union[None, TwitterTimestamp] = None,
        topic_ids: Union[List[TopicId], None] = None,
        post_ids: Union[List[PostId], None] = None,
        current_status: Union[None, List[str]] = None,
        language: Union[LanguageIdentifier, None] = None,
        search_text: Union[str, None] = None,
    ) -> int:
        with Session(self.engine) as sess:
            query = sess.query(NoteRecord)
            if note_ids is not None:
                query = query.filter(NoteRecord.note_id.in_(note_ids))
            if created_at_from is not None:
                query = query.filter(NoteRecord.created_at >= created_at_from)
            if created_at_to is not None:
                query = query.filter(NoteRecord.created_at <= created_at_to)
            if topic_ids is not None:
                # 同じトピックIDを持つノートを取得するためのサブクエリ
                # とりあえずANDを実装
                subq = (
                    select(NoteTopicAssociation.note_id)
                    .group_by(NoteTopicAssociation.note_id)
                    .having(func.bool_or(NoteTopicAssociation.topic_id.in_(topic_ids)))
                    .subquery()
                )
                query = query.join(subq, NoteRecord.note_id == subq.c.note_id)
            if post_ids is not None:
                query = query.filter(NoteRecord.post_id.in_(post_ids))
            if language is not None:
                query = query.filter(NoteRecord.language == language)
            if current_status is not None:
                query = query.filter(NoteRecord.current_status.in_(current_status))
            if search_text is not None:
                query = query.filter(NoteRecord.summary.like(f"%{search_text}%"))
            return query.count()

    def get_posts(
        self,
        post_ids: Union[List[PostId], None] = None,
        note_ids: Union[List[NoteId], None] = None,
        user_ids: Union[List[UserId], None] = None,
        start: Union[TwitterTimestamp, None] = None,
        end: Union[TwitterTimestamp, None] = None,
        search_text: Union[str, None] = None,
        search_url: Union[HttpUrl, None] = None,
        offset: Union[int, None] = None,
        limit: int = 100,
        with_media: bool = True,
    ) -> Generator[PostModel, None, None]:
        with Session(self.engine) as sess:
            query = sess.query(PostRecord)
            if post_ids is not None:
                query = query.filter(PostRecord.post_id.in_(post_ids))
            if note_ids is not None:
                query = query.join(NoteRecord, NoteRecord.post_id == PostRecord.post_id).filter(
                    NoteRecord.note_id.in_(note_ids)
                )
            if user_ids is not None:
                query = query.filter(PostRecord.user_id.in_(user_ids))
            if start is not None:
                query = query.filter(PostRecord.created_at >= start)
            if end is not None:
                query = query.filter(PostRecord.created_at < end)
            if search_text is not None:
                query = query.filter(PostRecord.text.like(f"%{search_text}%"))
            if search_url is not None:
                query = (
                    query.join(
                        PostLinkAssociation,
                        PostLinkAssociation.post_id == PostRecord.post_id,
                    )
                    .join(LinkRecord, LinkRecord.link_id == PostLinkAssociation.link_id)
                    .filter(LinkRecord.url == search_url)
                )
            if offset is not None:
                query = query.offset(offset)
            query = query.limit(limit)
            for post_record in query.all():
                yield self._post_record_to_model(post_record, with_media=with_media)

    def get_number_of_posts(
        self,
        post_ids: Union[List[PostId], None] = None,
        note_ids: Union[List[NoteId], None] = None,
        user_ids: Union[List[UserId], None] = None,
        start: Union[TwitterTimestamp, None] = None,
        end: Union[TwitterTimestamp, None] = None,
        search_text: Union[str, None] = None,
        search_url: Union[HttpUrl, None] = None,
    ) -> int:
        with Session(self.engine) as sess:
            query = sess.query(PostRecord)
            if post_ids is not None:
                query = query.filter(PostRecord.post_id.in_(post_ids))
            if note_ids is not None:
                query = query.join(NoteRecord, NoteRecord.post_id == PostRecord.post_id).filter(
                    NoteRecord.note_id.in_(note_ids)
                )
            if user_ids is not None:
                query = query.filter(PostRecord.user_id.in_(user_ids))
            if start is not None:
                query = query.filter(PostRecord.created_at >= start)
            if end is not None:
                query = query.filter(PostRecord.created_at < end)
            if search_text is not None:
                query = query.filter(PostRecord.text.like(f"%{search_text}%"))
            if search_url is not None:
                query = (
                    query.join(
                        PostLinkAssociation,
                        PostLinkAssociation.post_id == PostRecord.post_id,
                    )
                    .join(LinkRecord, LinkRecord.link_id == PostLinkAssociation.link_id)
                    .filter(LinkRecord.url == search_url)
                )
            return query.count()

    def _apply_filters(
        self,
        query: RowReturningQuery[Tuple[Any, ...]],
        note_includes_text: Union[str, None] = None,
        note_excludes_text: Union[str, None] = None,
        post_includes_text: Union[str, None] = None,
        post_excludes_text: Union[str, None] = None,
        language: Union[LanguageIdentifier, None] = None,
        topic_ids: Union[List[TopicId], None] = None,
        note_status: Union[List[str], None] = None,
        note_created_at_from: Union[TwitterTimestamp, None] = None,
        note_created_at_to: Union[TwitterTimestamp, None] = None,
        x_user_names: Union[List[str], None] = None,
        x_user_followers_count_from: Union[int, None] = None,
        x_user_follow_count_from: Union[int, None] = None,
        post_like_count_from: Union[int, None] = None,
        post_repost_count_from: Union[int, None] = None,
        post_impression_count_from: Union[int, None] = None,
        post_includes_media: Union[bool, None] = None,
    ) -> RowReturningQuery[Tuple[Any, ...]]:
        # Apply note filters
        if note_includes_text:
            query = query.filter(NoteRecord.summary.like(f"%{note_includes_text}%"))
        if note_excludes_text:
            query = query.filter(~NoteRecord.summary.like(f"%{note_excludes_text}%"))
        if language:
            query = query.filter(NoteRecord.language == language)
        if topic_ids:
            subq = (
                select(NoteTopicAssociation.note_id)
                .filter(NoteTopicAssociation.topic_id.in_(topic_ids))
                .group_by(NoteTopicAssociation.note_id)
                .subquery()
            )
            query = query.join(subq, NoteRecord.note_id == subq.c.note_id)
        if note_status:
            query = query.filter(NoteRecord.current_status.in_(note_status))
        if note_created_at_from:
            query = query.filter(NoteRecord.created_at >= note_created_at_from)
        if note_created_at_to:
            query = query.filter(NoteRecord.created_at <= note_created_at_to)

        # Apply post filters
        if post_includes_text:
            query = query.filter(PostRecord.text.like(f"%{post_includes_text}%"))
        if post_excludes_text:
            query = query.filter(~PostRecord.text.like(f"%{post_excludes_text}%"))
        if x_user_names:
            query = query.filter(XUserRecord.name.in_(x_user_names))
        if x_user_followers_count_from:
            query = query.filter(XUserRecord.followers_count >= x_user_followers_count_from)
        if x_user_follow_count_from:
            query = query.filter(XUserRecord.following_count >= x_user_follow_count_from)
        if post_like_count_from:
            query = query.filter(PostRecord.like_count >= post_like_count_from)
        if post_repost_count_from:
            query = query.filter(PostRecord.repost_count >= post_repost_count_from)
        if post_impression_count_from:
            query = query.filter(PostRecord.impression_count >= post_impression_count_from)
        if post_includes_media:
            query = query.filter(PostRecord.media_details.any())
        elif post_includes_media is False:
            query = query.filter(~PostRecord.media_details.any())

        return query

    def search_notes_with_posts(
        self,
        note_includes_text: Union[str, None] = None,
        note_excludes_text: Union[str, None] = None,
        post_includes_text: Union[str, None] = None,
        post_excludes_text: Union[str, None] = None,
        language: Union[LanguageIdentifier, None] = None,
        topic_ids: Union[List[TopicId], None] = None,
        note_status: Union[List[str], None] = None,
        note_created_at_from: Union[TwitterTimestamp, None] = None,
        note_created_at_to: Union[TwitterTimestamp, None] = None,
        x_user_names: Union[List[str], None] = None,
        x_user_followers_count_from: Union[int, None] = None,
        x_user_follow_count_from: Union[int, None] = None,
        post_like_count_from: Union[int, None] = None,
        post_repost_count_from: Union[int, None] = None,
        post_impression_count_from: Union[int, None] = None,
        post_includes_media: Union[bool, None] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Generator[Tuple[NoteModel, PostModel | None], None, None]:
        with Session(self.engine) as sess:
            query = (
                sess.query(NoteRecord, PostRecord)
                .outerjoin(PostRecord, NoteRecord.post_id == PostRecord.post_id)
                .outerjoin(XUserRecord, PostRecord.user_id == XUserRecord.user_id)
            )

            query = self._apply_filters(
                query,
                note_includes_text,
                note_excludes_text,
                post_includes_text,
                post_excludes_text,
                language,
                topic_ids,
                note_status,
                note_created_at_from,
                note_created_at_to,
                x_user_names,
                x_user_followers_count_from,
                x_user_follow_count_from,
                post_like_count_from,
                post_repost_count_from,
                post_impression_count_from,
                post_includes_media,
            )

            query = query.offset(offset).limit(limit)

            results = query.all()

            for note_record, post_record in results:
                try:
                    note = NoteModel(
                        note_id=note_record.note_id,
                        note_author_participant_id=note_record.note_author_participant_id,
                        post_id=note_record.post_id,
                        topics=[
                            TopicModel(
                                topic_id=topic.topic_id,
                                label=topic.topic.label,
                                reference_count=0,
                            )
                            for topic in note_record.topics
                        ],
                        language=note_record.language,
                        summary=note_record.summary,
                        current_status=note_record.current_status,
                        created_at=note_record.created_at,
                        has_been_helpfuled=(
                            note_record.has_been_helpfuled if note_record.has_been_helpfuled is not None else False
                        ),
                        rate_count=note_record.rate_count if note_record.rate_count is not None else 0,
                        helpful_count=note_record.helpful_count if note_record.helpful_count is not None else 0,
                        not_helpful_count=(
                            note_record.not_helpful_count if note_record.not_helpful_count is not None else 0
                        ),
                        somewhat_helpful_count=(
                            note_record.somewhat_helpful_count if note_record.somewhat_helpful_count is not None else 0
                        ),
                        current_status_history=self._parse_status_history(note_record.current_status_history),
                    )

                    post = (
                        self._post_record_to_model(post_record, with_media=post_includes_media) if post_record else None
                    )
                    yield note, post
                except Exception as e:
                    # Skip invalid records and log warning
                    logger = get_logger()
                    logger.warning(f"Skipping invalid note/post record (note_id={note_record.note_id}): {str(e)}")
                    continue

    def count_search_results(
        self,
        note_includes_text: Union[str, None] = None,
        note_excludes_text: Union[str, None] = None,
        post_includes_text: Union[str, None] = None,
        post_excludes_text: Union[str, None] = None,
        language: Union[LanguageIdentifier, None] = None,
        topic_ids: Union[List[TopicId], None] = None,
        note_status: Union[List[str], None] = None,
        note_created_at_from: Union[TwitterTimestamp, None] = None,
        note_created_at_to: Union[TwitterTimestamp, None] = None,
        x_user_names: Union[List[str], None] = None,
        x_user_followers_count_from: Union[int, None] = None,
        x_user_follow_count_from: Union[int, None] = None,
        post_like_count_from: Union[int, None] = None,
        post_repost_count_from: Union[int, None] = None,
        post_impression_count_from: Union[int, None] = None,
        post_includes_media: Union[bool, None] = None,
    ) -> int:
        with Session(self.engine) as sess:
            query = (
                sess.query(func.count(NoteRecord.note_id))
                .outerjoin(PostRecord, NoteRecord.post_id == PostRecord.post_id)
                .outerjoin(XUserRecord, PostRecord.user_id == XUserRecord.user_id)
            )

            query = self._apply_filters(
                query,
                note_includes_text,
                note_excludes_text,
                post_includes_text,
                post_excludes_text,
                language,
                topic_ids,
                note_status,
                note_created_at_from,
                note_created_at_to,
                x_user_names,
                x_user_followers_count_from,
                x_user_follow_count_from,
                post_like_count_from,
                post_repost_count_from,
                post_impression_count_from,
                post_includes_media,
            )

            return query.scalar() or 0

    def upsert_note(
        self,
        note_id: NoteId,
        summary: SummaryString,
        post_id: Optional[PostId] = None,
        created_at: Optional[TwitterTimestamp] = None,
        note_author_participant_id: Optional[ParticipantId] = None,
        language: Optional[LanguageIdentifier] = None,
        current_status: Optional[str] = None,
    ) -> None:
        """
        Insert or update a note in the database.

        Args:
            note_id: Note ID (required)
            summary: Note summary (required)
            post_id: Post ID (optional)
            created_at: Creation timestamp (optional)
            note_author_participant_id: Note author participant ID (optional)
            language: Language identifier (optional)
            current_status: Current status (optional)
        """
        from sqlalchemy.dialects.postgresql import insert

        with Session(self.engine) as sess:
            stmt = insert(NoteRecord).values(
                note_id=note_id,
                summary=summary,
                post_id=post_id,
                created_at=created_at,
                note_author_participant_id=note_author_participant_id,
                language=language,
                current_status=current_status,
            )

            # On conflict, update the fields
            stmt = stmt.on_conflict_do_update(
                index_elements=["note_id"],
                set_={
                    "summary": stmt.excluded.summary,
                    "post_id": stmt.excluded.post_id,
                    "created_at": stmt.excluded.created_at,
                    "note_author_participant_id": stmt.excluded.note_author_participant_id,
                    "language": stmt.excluded.language,
                    "current_status": stmt.excluded.current_status,
                },
            )

            sess.execute(stmt)
            sess.commit()


def gen_storage(settings: GlobalSettings) -> Storage:
    engine = create_engine(settings.storage_settings.sqlalchemy_database_url)
    return Storage(engine=engine)
