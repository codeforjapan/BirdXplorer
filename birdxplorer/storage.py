from sqlalchemy import BigInteger, Column, Float, Integer, String
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from .exceptions import UserEnrollmentNotFoundError
from .models import ParticipantId, UserEnrollment
from .settings import GlobalSettings


class Base(DeclarativeBase):
    ...


class UserEnrollmentT(Base):
    __tablename__ = "user_enrollment"
    participant_id = Column(String, primary_key=True)
    enrollment_state = Column(String)
    successful_rating_needed_to_earn_in = Column(Integer)
    timestamp_of_last_state_change = Column(BigInteger)
    timestamp_of_last_earn_out = Column(BigInteger)
    modeling_population = Column(String)
    modeling_group = Column(Float)


class Storage:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __delete__(self) -> None:
        self._engine.dispose()

    @property
    def engine(self) -> Engine:
        return self._engine

    def get_user_enrollment_by_participant_id(self, participant_id: ParticipantId) -> UserEnrollment:
        with Session(self.engine) as sess:
            row = sess.get(UserEnrollmentT, str(participant_id))
            if row is None:
                raise UserEnrollmentNotFoundError(participant_id=participant_id)
            return UserEnrollment(
                participant_id=ParticipantId.from_str(str(row.participant_id)),
                enrollment_state=row.enrollment_state,
                successful_rating_needed_to_earn_in=row.successful_rating_needed_to_earn_in,
                timestamp_of_last_state_change=row.timestamp_of_last_state_change,
                timestamp_of_last_earn_out=row.timestamp_of_last_earn_out,
                modeling_population=row.modeling_population,
                modeling_group=row.modeling_group,
            )


def gen_storage(settings: GlobalSettings) -> Storage:
    engine = create_engine(settings.storage_settings.sqlalchemy_database_url.unicode_string())
    return Storage(engine=engine)
