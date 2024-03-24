from typing import Generator, List

from psycopg2.extensions import AsIs, register_adapter
from pydantic import AnyUrl, HttpUrl
from sqlalchemy import ForeignKey, create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.types import DECIMAL, JSON, Integer, String

from .models import (
    LanguageIdentifier,
    MediaDetails,
    NonNegativeInt,
    NoteId,
    ParticipantId,
)
from .models import Post as PostModel
from .models import PostId, SummaryString
from .models import Topic as TopicModel
from .models import (
    TopicId,
    TopicLabel,
    TweetId,
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
        TopicId: Integer,
        TopicLabel: JSON,
        NoteId: String,
        ParticipantId: String,
        TweetId: String,
        LanguageIdentifier: String,
        TwitterTimestamp: DECIMAL,
        SummaryString: String,
        UserId: String,
        UserName: String,
        HttpUrl: String,
        NonNegativeInt: DECIMAL,
        MediaDetails: JSON,
    }


class NoteTopicAssociation(Base):
    __tablename__ = "note_topic"

    note_id: Mapped[NoteId] = mapped_column(ForeignKey("notes.note_id"), primary_key=True)
    topic_id: Mapped[TopicId] = mapped_column(ForeignKey("topics.topic_id"), primary_key=True)
    topic: Mapped["TopicRecord"] = relationship()


class NoteRecord(Base):
    __tablename__ = "notes"

    note_id: Mapped[NoteId] = mapped_column(primary_key=True)
    post_id: Mapped[TweetId] = mapped_column(nullable=False)
    topics: Mapped[List[NoteTopicAssociation]] = relationship()
    language: Mapped[LanguageIdentifier] = mapped_column(nullable=False)
    summary: Mapped[SummaryString] = mapped_column(nullable=False)
    created_at: Mapped[TwitterTimestamp] = mapped_column(nullable=False)


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


class PostRecord(Base):
    __tablename__ = "posts"

    post_id: Mapped[TweetId] = mapped_column(primary_key=True)
    user_id: Mapped[UserId] = mapped_column(ForeignKey("x_users.user_id"), nullable=False)
    user: Mapped[XUserRecord] = relationship()
    text: Mapped[SummaryString] = mapped_column(nullable=False)
    media_details: Mapped[MediaDetails] = mapped_column()
    created_at: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    like_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    repost_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    impression_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)


class Storage:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

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
                    topic_id=topic_record.topic_id, label=topic_record.label, reference_count=reference_count or 0
                )

    def get_posts(self) -> Generator[PostModel, None, None]:
        with Session(self.engine) as sess:
            for post_record in sess.query(PostRecord).all():
                yield PostModel(
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
                    media_details=post_record.media_details,
                    created_at=post_record.created_at,
                    like_count=post_record.like_count,
                    repost_count=post_record.repost_count,
                    impression_count=post_record.impression_count,
                )

    def get_posts_by_ids(self, post_ids: List[PostId]) -> Generator[PostModel, None, None]:
        raise NotImplementedError

    def get_posts_by_created_at_range(
        self, start: TwitterTimestamp, end: TwitterTimestamp
    ) -> Generator[PostModel, None, None]:
        raise NotImplementedError

    def get_posts_by_created_at_start(self, start: TwitterTimestamp) -> Generator[PostModel, None, None]:
        raise NotImplementedError

    def get_posts_by_created_at_end(self, end: TwitterTimestamp) -> Generator[PostModel, None, None]:
        raise NotImplementedError


def gen_storage(settings: GlobalSettings) -> Storage:
    engine = create_engine(settings.storage_settings.sqlalchemy_database_url)
    return Storage(engine=engine)
