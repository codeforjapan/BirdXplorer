"""
Pytest configuration and fixtures for ETL tests
"""

import os
from collections.abc import Generator
from pathlib import Path
from typing import Type

from polyfactory.factories.pydantic_factory import ModelFactory
from pytest import fixture
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from birdxplorer_common.settings import GlobalSettings, PostgresStorageSettings
from birdxplorer_common.storage import Base


def load_env_file():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip() == "BX_STORAGE_SETTINGS__PASSWORD":
                        os.environ[key.strip()] = value.strip()


def clean_env_vars():
    """Remove environment variables that are not needed for GlobalSettings"""
    vars_to_remove = [
        "X_BEARER_TOKEN",
        "x_bearer_token",
        "COMMUNITY_NOTE_DAYS_AGO",
        "community_note_days_ago",
        "TARGET_TWITTER_POST_START_UNIX_MILLISECOND",
        "target_twitter_post_start_unix_millisecond",
        "TARGET_TWITTER_POST_END_UNIX_MILLISECOND",
        "target_twitter_post_end_unix_millisecond",
        "AI_MODEL",
        "ai_model",
        "OPENAPI_TOKEN",
        "openapi_token",
        "CLAUDE_TOKEN",
        "claude_token",
        "TARGET_NOTE_ESTIMATE_TOPIC_START_UNIX_MILLISECOND",
        "target_note_estimate_topic_start_unix_millisecond",
        "TARGET_NOTE_ESTIMATE_TOPIC_END_UNIX_MILLISECOND",
        "target_note_estimate_topic_end_unix_millisecond",
        "USE_DUMMY_DATA",
        "use_dummy_data",
        "DB_PORT",
        "db_port",
        "X_TEST_USERNAME",
        "x_test_username",
        "X_TEST_PASSWORD",
        "x_test_password",
        "X_TEST_EMAIL",
        "x_test_email",
        "X_TEST_EMAIL_PASSWORD",
        "x_test_email_password",
        "X_TEST_COOKIES",
        "x_test_cookies",
    ]
    for var in vars_to_remove:
        os.environ.pop(var, None)


load_env_file()
clean_env_vars()

TEST_DATABASE_NAME = "bx_test"


@fixture
def postgres_storage_settings_factory() -> Type[ModelFactory[PostgresStorageSettings]]:
    class PostgresStorageSettingsFactory(ModelFactory[PostgresStorageSettings]):
        __model__ = PostgresStorageSettings
        __check_model__ = False

        host = "localhost"
        username = "postgres"
        port = 5432
        database = "postgres"
        password = os.environ.get("BX_STORAGE_SETTINGS__PASSWORD", "")

    return PostgresStorageSettingsFactory


@fixture
def global_settings_factory(
    postgres_storage_settings_factory: Type[ModelFactory[PostgresStorageSettings]],
) -> Type[ModelFactory[GlobalSettings]]:
    class GlobalSettingsFactory(ModelFactory[GlobalSettings]):
        __model__ = GlobalSettings
        __check_model__ = False

        storage_settings = postgres_storage_settings_factory.build()

    return GlobalSettingsFactory


@fixture
def default_settings(
    global_settings_factory: Type[ModelFactory[GlobalSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory.build()


@fixture
def settings_for_test(
    global_settings_factory: Type[ModelFactory[GlobalSettings]],
    postgres_storage_settings_factory: Type[ModelFactory[PostgresStorageSettings]],
) -> Generator[GlobalSettings, None, None]:
    yield global_settings_factory.build(
        storage_settings=postgres_storage_settings_factory.build(database=TEST_DATABASE_NAME)
    )


@fixture
def engine_for_test(
    default_settings: GlobalSettings, settings_for_test: GlobalSettings
) -> Generator[Engine, None, None]:
    """Create a test database engine with clean state"""
    default_engine = create_engine(default_settings.storage_settings.sqlalchemy_database_url)
    with default_engine.connect() as conn:
        conn.execute(text("COMMIT"))
        try:
            conn.execute(text(f"DROP DATABASE {TEST_DATABASE_NAME}"))
        except SQLAlchemyError:
            pass

    with default_engine.connect() as conn:
        conn.execute(text("COMMIT"))
        conn.execute(text(f"CREATE DATABASE {TEST_DATABASE_NAME}"))

    engine = create_engine(settings_for_test.storage_settings.sqlalchemy_database_url)

    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()
    del engine

    with default_engine.connect() as conn:
        conn.execute(text("COMMIT"))
        conn.execute(text(f"DROP DATABASE {TEST_DATABASE_NAME}"))

    default_engine.dispose()


@fixture
def db_session(engine_for_test: Engine) -> Generator[Session, None, None]:
    """Create a database session for testing"""
    session = Session(engine_for_test)
    yield session
    session.close()
