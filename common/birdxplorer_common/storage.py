from typing import Generator, List, Union

from psycopg2.extensions import AsIs, register_adapter
from pydantic import AnyUrl, HttpUrl
from sqlalchemy import ForeignKey, create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.types import CHAR, DECIMAL, JSON, Integer, String, Uuid

from .models import BinaryBool, LanguageIdentifier
from .models import Link as LinkModel
from .models import LinkId, Media, MediaDetails, MediaType, NonNegativeInt
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
    post_id: Mapped[PostId] = mapped_column(nullable=False)
    topics: Mapped[List[NoteTopicAssociation]] = relationship()
    language: Mapped[LanguageIdentifier] = mapped_column(nullable=False)
    summary: Mapped[SummaryString] = mapped_column(nullable=False)
    current_status: Mapped[String] = mapped_column(nullable=True)
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
    like_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    repost_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    impression_count: Mapped[NonNegativeInt] = mapped_column(nullable=False)
    links: Mapped[List[PostLinkAssociation]] = relationship()


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


class RowPostRecord(Base):
    __tablename__ = "row_posts"

    post_id: Mapped[PostId] = mapped_column(primary_key=True)
    author_id: Mapped[UserId] = mapped_column(ForeignKey("row_users.user_id"), nullable=False)
    text: Mapped[SummaryString] = mapped_column(nullable=False)
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
    def _post_record_to_model(cls, post_record: PostRecord, *, with_media: bool) -> PostModel:
        # post_record.media_detailsにアクセスしたタイミングでメディア情報を一気に引っ張るクエリが発行される
        # media情報がいらない場合はクエリを発行したくないので先にwith_mediaをチェック
        media_details = cls._post_record_media_details_to_model(post_record) if with_media else []

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
            created_at=post_record.created_at,
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
                    topic_id=topic_record.topic_id, label=topic_record.label, reference_count=reference_count or 0
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
                yield NoteModel(
                    note_id=note_record.note_id,
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
                    language=LanguageIdentifier.normalize(note_record.language),
                    summary=note_record.summary,
                    current_status=note_record.current_status,
                    created_at=note_record.created_at,
                )

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
            if start is not None:
                query = query.filter(PostRecord.created_at >= start)
            if end is not None:
                query = query.filter(PostRecord.created_at < end)
            if search_text is not None:
                query = query.filter(PostRecord.text.like(f"%{search_text}%"))
            if search_url is not None:
                query = (
                    query.join(PostLinkAssociation, PostLinkAssociation.post_id == PostRecord.post_id)
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
            if start is not None:
                query = query.filter(PostRecord.created_at >= start)
            if end is not None:
                query = query.filter(PostRecord.created_at < end)
            if search_text is not None:
                query = query.filter(PostRecord.text.like(f"%{search_text}%"))
            if search_url is not None:
                query = (
                    query.join(PostLinkAssociation, PostLinkAssociation.post_id == PostRecord.post_id)
                    .join(LinkRecord, LinkRecord.link_id == PostLinkAssociation.link_id)
                    .filter(LinkRecord.url == search_url)
                )
            return query.count()


def gen_storage(settings: GlobalSettings) -> Storage:
    engine = create_engine(settings.storage_settings.sqlalchemy_database_url)
    return Storage(engine=engine)
