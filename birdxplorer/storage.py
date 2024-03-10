from typing import Generator, List

from sqlalchemy import ForeignKey, create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.types import DECIMAL, JSON, Integer, String

from .models import LanguageIdentifier, NoteId, ParticipantId, SummaryString
from .models import Topic as TopicModel
from .models import TopicId, TopicLabel, TweetId, TwitterTimestamp, UserEnrollment
from .settings import GlobalSettings


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
    def get_notes(self, created_at_from, created_at_to, topic_id, post_id, language) -> Generator[NoteRecord, None, None]:
        with Session(self.engine) as sess:
            query = sess.query(NoteRecord)
            if created_at_from:
                query = query.filter(NoteRecord.created_at >= created_at_from)
            if created_at_to:
                query = query.filter(NoteRecord.created_at <= created_at_to)
            if topic_id:
                query = query.join(NoteTopicAssociation).filter(NoteTopicAssociation.topic_id == topic_id)
            if post_id:
                query = query.filter(NoteRecord.post_id == post_id)
            if language:
                query = query.filter(NoteRecord.language == language)
            for note_record in query.all():
                yield note_record


def gen_storage(settings: GlobalSettings) -> Storage:
    engine = create_engine(settings.storage_settings.sqlalchemy_database_url)
    return Storage(engine=engine)
