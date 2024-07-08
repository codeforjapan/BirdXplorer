from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, computed_field
from pydantic_settings import BaseSettings as PydanticBaseSettings
from pydantic_settings import SettingsConfigDict


class BaseSettings(PydanticBaseSettings):
    model_config = SettingsConfigDict(env_prefix="BX_", env_file_encoding="utf-8", env_nested_delimiter="__")


class LoggerSettings(BaseSettings):
    level: int = 20


class PostgresStorageSettings(BaseSettings):
    host: str = "db"
    username: str = "postgres"
    password: str
    port: int = 5432
    database: str = "postgres"

    @computed_field  # type: ignore[misc]
    @property
    def sqlalchemy_database_url(self) -> str:
        return PostgresDsn(
            url=f"postgresql://{self.username}:"
            f"{self.password.replace('@', '%40')}@{self.host}:{self.port}/{self.database}"
        ).unicode_string()


class CORSSettings(BaseSettings):
    allow_credentials: bool = True
    allow_methods: list[str] = ["GET"]
    allow_headers: list[str] = ["*"]

    allow_origins: list[str] = []


class GlobalSettings(BaseSettings):
    cors_settings: CORSSettings = Field(default_factory=CORSSettings)
    model_config = SettingsConfigDict(env_file=".env")
    logger_settings: LoggerSettings = Field(default_factory=LoggerSettings)
    storage_settings: PostgresStorageSettings
