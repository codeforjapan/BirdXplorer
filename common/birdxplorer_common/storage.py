from typing import Generator, List, Union

from psycopg2.extensions import AsIs, register_adapter
from pydantic import AnyUrl, HttpUrl
from sqlalchemy import ForeignKey, create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.types import CHAR, DECIMAL, JSON, Integer, String

from .models import BinaryBool, LanguageIdentifier, MediaDetails, NonNegativeInt
from .models import Note as NoteModel
from .models import NoteId, NotesClassification, NotesHarmful, ParticipantId
from .models import Post as PostModel
from .models import PostId, SummaryString
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
    post_id: Mapped[PostId] = mapped_column(nullable=False)
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

    post_id: Mapped[PostId] = mapped_column(primary_key=True)
    user_id: Mapped[UserId] = mapped_column(ForeignKey("x_users.user_id"), nullable=False)
    user: Mapped[XUserRecord] = relationship()
    text: Mapped[SummaryString] = mapped_column(nullable=False)
    media_details: Mapped[MediaDetails] = mapped_column()
    created_at: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    like_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    repost_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    impression_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)


class RowNoteRecord(Base):
    __tablename__ = "row_notes"

    note_id: Mapped[NoteId] = mapped_column(primary_key=True)
    note_author_participant_id: Mapped[ParticipantId] = mapped_column(nullable=False)
    created_at_millis: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    tweet_id: Mapped[PostId] = mapped_column(nullable=False)
    believable: Mapped[BinaryBool] = mapped_column(nullable=False)
    misleading_other: Mapped[BinaryBool] = mapped_column(nullable=False)
    misleading_factual_error: Mapped[BinaryBool] = mapped_column(nullable=False)
    misleading_manipulated_media: Mapped[BinaryBool] = mapped_column(nullable=False)
    misleading_outdated_information: Mapped[BinaryBool] = mapped_column(nullable=False)
    misleading_missing_important_context: Mapped[BinaryBool] = mapped_column(nullable=False)
    misleading_unverified_claim_as_fact: Mapped[BinaryBool] = mapped_column(nullable=False)
    misleading_satire: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_misleading_other: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_misleading_factually_correct: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_misleading_outdated_but_not_when_written: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_misleading_clearly_satire: Mapped[BinaryBool] = mapped_column(nullable=False)
    not_misleading_personal_opinion: Mapped[BinaryBool] = mapped_column(nullable=False)
    trustworthy_sources: Mapped[BinaryBool] = mapped_column(nullable=False)
    is_media_note: Mapped[BinaryBool] = mapped_column(nullable=False)
    classification: Mapped[NotesClassification] = mapped_column(nullable=False)
    harmful: Mapped[NotesHarmful] = mapped_column(nullable=False)
    validation_difficulty: Mapped[SummaryString] = mapped_column(nullable=False)
    summary: Mapped[SummaryString] = mapped_column(nullable=False)
    row_post_id: Mapped[PostId] = mapped_column(ForeignKey("row_posts.post_id"), nullable=True)
    row_post: Mapped["RowPostRecord"] = relationship("RowPostRecord", back_populates="row_notes")


class RowPostRecord(Base):
    __tablename__ = "row_posts"

    post_id: Mapped[PostId] = mapped_column(primary_key=True)
    author_id: Mapped[UserId] = mapped_column(ForeignKey("row_users.user_id"), nullable=False)
    text: Mapped[SummaryString] = mapped_column(nullable=False)
    media_type: Mapped[String] = mapped_column(nullable=True)
    media_url: Mapped[String] = mapped_column(nullable=True)
    created_at: Mapped[TwitterTimestamp] = mapped_column(nullable=False)
    like_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    repost_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    bookmark_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    impression_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    quote_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    reply_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    lang: Mapped[String] = mapped_column()
    row_notes: Mapped["RowNoteRecord"] = relationship("RowNoteRecord", back_populates="row_post")
    user: Mapped["RowUserRecord"] = relationship("RowUserRecord", back_populates="row_post")


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
    verified: Mapped[BinaryBool] = mapped_column(nullable=False)
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
    def _post_record_to_model(cls, post_record: PostRecord) -> PostModel:
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
            media_details=post_record.media_details,
            created_at=post_record.created_at,
            like_count=post_record.like_count,
            repost_count=post_record.repost_count,
            impression_count=post_record.impression_count,
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
                    topic_id=topic_record.topic_id, label=topic_record.label, reference_count=reference_count or 0
                )

    def get_notes(
        self,
        note_ids: Union[List[NoteId], None] = None,
        created_at_from: Union[None, TwitterTimestamp] = None,
        created_at_to: Union[None, TwitterTimestamp] = None,
        topic_ids: Union[List[TopicId], None] = None,
        post_ids: Union[List[PostId], None] = None,
        language: Union[LanguageIdentifier, None] = None,
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
            for note_record in query.all():
                yield NoteModel(
                    note_id=note_record.note_id,
                    post_id=note_record.post_id,
                    topics=[
                        TopicModel(
                            topic_id=topic.topic_id,
                            label=topic.topic.label,
                            reference_count=sess.query(func.count(NoteTopicAssociation.note_id))
                            .filter(NoteTopicAssociation.topic_id == topic.topic_id)
                            .scalar()
                            or 0,
                        )
                        for topic in note_record.topics
                    ],
                    language=LanguageIdentifier.normalize(note_record.language),
                    summary=note_record.summary,
                    created_at=note_record.created_at,
                )

    def get_posts(self) -> Generator[PostModel, None, None]:
        with Session(self.engine) as sess:
            for post_record in sess.query(PostRecord).all():
                yield self._post_record_to_model(post_record)

    def get_posts_by_ids(self, post_ids: List[PostId]) -> Generator[PostModel, None, None]:
        with Session(self.engine) as sess:
            for post_record in sess.query(PostRecord).filter(PostRecord.post_id.in_(post_ids)).all():
                yield self._post_record_to_model(post_record)

    def get_posts_by_created_at_range(
        self, start: TwitterTimestamp, end: TwitterTimestamp
    ) -> Generator[PostModel, None, None]:
        with Session(self.engine) as sess:
            for post_record in sess.query(PostRecord).filter(PostRecord.created_at.between(start, end)).all():
                yield self._post_record_to_model(post_record)

    def get_posts_by_created_at_start(self, start: TwitterTimestamp) -> Generator[PostModel, None, None]:
        with Session(self.engine) as sess:
            for post_record in sess.query(PostRecord).filter(PostRecord.created_at >= start).all():
                yield self._post_record_to_model(post_record)

    def get_posts_by_created_at_end(self, end: TwitterTimestamp) -> Generator[PostModel, None, None]:
        with Session(self.engine) as sess:
            for post_record in sess.query(PostRecord).filter(PostRecord.created_at < end).all():
                yield self._post_record_to_model(post_record)

    def get_posts_by_note_ids(self, note_ids: List[NoteId]) -> Generator[PostModel, None, None]:
        query = (
            select(PostRecord)
            .join(NoteRecord, NoteRecord.post_id == PostRecord.post_id)
            .where(NoteRecord.note_id.in_(note_ids))
        )
        with Session(self.engine) as sess:
            for post_record in sess.execute(query).scalars().all():
                yield self._post_record_to_model(post_record)


def gen_storage(settings: GlobalSettings) -> Storage:
    engine = create_engine(settings.storage_settings.sqlalchemy_database_url)
    return Storage(engine=engine)
