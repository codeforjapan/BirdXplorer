from typing import Optional

from pydantic import Field, PostgresDsn, computed_field
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
    # 1 クエリの上限時間。ここを超えると PostgreSQL 側でクエリが打ち切られる。
    # 応答を返したあともクエリが走り続けて CPU とコネクションを占有するのを防ぐ。
    # 0 を指定すると無制限（PostgreSQL の既定の扱い）。
    statement_timeout_ms: int = Field(default=30000, ge=0)
    # CSV エクスポートだけは上の既定では足りないことがある。前方ワイルドカードの
    # LIKE + JOIN でインデックスが効かず、仕様上の目標（5,000 件を 10 秒以内、
    # specs/002-csv-export-api/spec.md SC-001）を大きく外れる可能性があるため。
    # この経路のトランザクションでだけ statement_timeout を差し替える。
    # 0 を指定すると無制限だが、公開エンドポイントなので既定は有限値にしている。
    csv_export_statement_timeout_ms: int = Field(default=120000, ge=0)

    @computed_field  # type: ignore[prop-decorator]
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

    allow_origins: list[str] = ["*"]


class GlobalSettings(BaseSettings):
    cors_settings: CORSSettings = Field(default_factory=CORSSettings)
    model_config = SettingsConfigDict(env_file=".env")
    logger_settings: LoggerSettings = Field(default_factory=LoggerSettings)
    storage_settings: PostgresStorageSettings
    export_api_key: Optional[str] = None
