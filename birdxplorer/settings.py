from pydantic import Field
from pydantic_settings import BaseSettings as PydanticBaseSettings
from pydantic_settings import SettingsConfigDict


class BaseSettings(PydanticBaseSettings):
    model_config = SettingsConfigDict(env_prefix="BX_", env_file_encoding="utf-8", env_nested_delimiter="__")


class LoggerSettings(BaseSettings):
    level: int = 20


class GlobalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    logger_settings: LoggerSettings = Field(default_factory=LoggerSettings)
