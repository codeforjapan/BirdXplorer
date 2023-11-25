from collections.abc import Generator
from typing import Dict, List, Type, Union

from polyfactory.factories.pydantic_factory import ModelFactory
from pytest import fixture
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from birdxplorer.settings import GlobalSettings, PostgresStorageSettings
from birdxplorer.storage import Base, UserEnrollmentT

TEST_DATABASE_NAME = "test"


@fixture
def global_settings_factory_class() -> Generator[Type[ModelFactory[GlobalSettings]], None, None]:
    class GlobalSettingsFactory(ModelFactory[GlobalSettings]):
        __model__ = GlobalSettings

    yield GlobalSettingsFactory


def create_engine_from_settings(settings: PostgresStorageSettings) -> Engine:
    if not settings.sqlalchemy_database_url:
        raise ValueError("SQLAlchemy database URL is not set")
    return create_engine(settings.sqlalchemy_database_url.unicode_string())


@fixture(scope="session")
def settings_for_default() -> Generator[PostgresStorageSettings, None, None]:
    settings = PostgresStorageSettings(
        host="127.0.0.1", port=5432, username="postgres", password="postgres", database="postgres"
    )
    yield settings


@fixture(scope="session")
def settings_for_test() -> Generator[PostgresStorageSettings, None, None]:
    settings = PostgresStorageSettings(
        host="127.0.0.1", port=5432, username="postgres", password="postgres", database=TEST_DATABASE_NAME
    )
    yield settings


@fixture(scope="session")
def db_for_test(settings_for_default: PostgresStorageSettings) -> Generator[int, None, None]:
    engine = create_engine_from_settings(settings_for_default)
    conn = engine.connect()
    conn.execute(text("commit"))
    try:
        conn.execute(text(f"drop database {TEST_DATABASE_NAME}"))
    except SQLAlchemyError:
        pass
    finally:
        conn.close()

    conn = engine.connect()
    conn.execute(text("commit"))
    conn.execute(text(f"create database {TEST_DATABASE_NAME}"))
    conn.close()
    yield 1

    conn = engine.connect()
    conn.execute(text("commit"))
    conn.execute(text(f"drop database {TEST_DATABASE_NAME}"))
    conn.close()

    engine.dispose()


@fixture(scope="session")
def engine_for_test(settings_for_test: PostgresStorageSettings, db_for_test: int) -> Generator[Engine, None, None]:
    engine = create_engine_from_settings(settings_for_test)
    yield engine
    engine.dispose()


@fixture(scope="session")
def schema_for_test(settings_for_test: PostgresStorageSettings, db_for_test: int) -> Generator[int, None, None]:
    engine = create_engine_from_settings(settings_for_test)
    Base.metadata.create_all(engine)

    yield 1
    engine.dispose()


@fixture(scope="session")
def user_enrollment_data_list() -> Generator[List[Dict[str, Union[int, str, float]]], None, None]:
    yield [
        {
            "participantId": "D1B8692FB8A8E940F231F606D316881740AF41D73909FE28D5555DA36760A215",
            "enrollmentState": "newUser",
            "successfulRatingNeededToEarnIn": 5,
            "timestampOfLastStateChange": 1679950000000,
            "timestampOfLastEarnOut": 1,
            "modelingPopulation": "CORE",
            "modelingGroup": 13.0,
        },
        {
            "participantId": "49A4DF10193C2FD2D189515D21CEB0BE30F1D2F4297B7D45021A74EF830241A1",
            "enrollmentState": "earnedIn",
            "successfulRatingNeededToEarnIn": 5,
            "timestampOfLastStateChange": 1679960000000,
            "timestampOfLastEarnOut": 1,
            "modelingPopulation": "CORE",
            "modelingGroup": 13.0,
        },
        {
            "participantId": "34166A0D0B81720C6797EF9CD7896EAAD777C140FE718BB9A3CF3236234469A7",
            "enrollmentState": "newUser",
            "successfulRatingNeededToEarnIn": 5,
            "timestampOfLastStateChange": 1679970000000,
            "timestampOfLastEarnOut": 1,
            "modelingPopulation": "CORE",
            "modelingGroup": 13.0,
        },
        {
            "participantId": "C571B31494AC67D57F269B340D689A23B62E5BD73DC51538A6EE917A1EA1D633",
            "enrollmentState": "earnedIn",
            "successfulRatingNeededToEarnIn": 5,
            "timestampOfLastStateChange": 1679980000000,
            "timestampOfLastEarnOut": 1,
            "modelingPopulation": "CORE",
            "modelingGroup": 13.0,
        },
        {
            "participantId": "0EB851180C7BC42F126573C062EC735A3FF073089499A856BE6FC3E2BE823AAD",
            "enrollmentState": "newUser",
            "successfulRatingNeededToEarnIn": 5,
            "timestampOfLastStateChange": 1679990000000,
            "timestampOfLastEarnOut": 1,
            "modelingPopulation": "CORE",
            "modelingGroup": 13.0,
        },
    ]


@fixture(scope="session")
def user_enrollment_records(
    user_enrollment_data_list: List[Dict[str, Union[int, str, float]]], engine_for_test: Engine, schema_for_test: int
) -> Generator[int, None, None]:
    with Session(engine_for_test) as session:
        session.query(UserEnrollmentT).delete()
        for data in user_enrollment_data_list:
            session.execute(
                text(
                    """
                    insert into user_enrollment (
                        participant_id,
                        enrollment_state,
                        successful_rating_needed_to_earn_in,
                        timestamp_of_last_state_change,
                        timestamp_of_last_earn_out,
                        modeling_population,
                        modeling_group
                    ) values (
                        :participantId,
                        :enrollmentState,
                        :successfulRatingNeededToEarnIn,
                        :timestampOfLastStateChange,
                        :timestampOfLastEarnOut,
                        :modelingPopulation,
                        :modelingGroup
                    )
                    """,
                ),
                data,
            )
        session.commit()
    yield 1
