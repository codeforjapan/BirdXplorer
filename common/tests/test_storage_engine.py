import os
from typing import Any, Dict

import pytest
from pydantic import ValidationError
from pytest_mock import MockerFixture

from birdxplorer_common.settings import GlobalSettings
from birdxplorer_common.storage import gen_storage

BASE_ENV = {"BX_STORAGE_SETTINGS__PASSWORD": "s0m6S+ron9P@55w0rd"}


def _connect_args(mocker: MockerFixture, env: Dict[str, str], **kwargs: Any) -> Dict[str, str]:
    mocker.patch.dict(os.environ, env, clear=True)
    create_engine = mocker.patch("birdxplorer_common.storage.create_engine")
    gen_storage(GlobalSettings(), **kwargs)
    connect_args: Dict[str, str] = create_engine.call_args.kwargs["connect_args"]
    return connect_args


def test_gen_storage_sets_statement_timeout_by_default(mocker: MockerFixture) -> None:
    # 504 を返したあとも PostgreSQL 側でクエリが走り続け、CPU とコネクションを
    # 占有するのを防ぐ。既定値は 30 秒。
    assert _connect_args(mocker, BASE_ENV) == {"options": "-c statement_timeout=30000"}


def test_gen_storage_uses_configured_statement_timeout(mocker: MockerFixture) -> None:
    env = dict(BASE_ENV, BX_STORAGE_SETTINGS__STATEMENT_TIMEOUT_MS="5000")
    assert _connect_args(mocker, env) == {"options": "-c statement_timeout=5000"}


def test_gen_storage_can_disable_statement_timeout_per_call(mocker: MockerFixture) -> None:
    # マイグレーションのように時間のかかる処理は、呼び出し側で無効化できる
    # （PostgreSQL は statement_timeout=0 を無制限として扱う）。
    assert _connect_args(mocker, BASE_ENV, statement_timeout_ms=0) == {"options": "-c statement_timeout=0"}


def test_gen_storage_rejects_negative_statement_timeout(mocker: MockerFixture) -> None:
    # 負の値は PostgreSQL が接続時に弾くので、渡される前に落とす
    mocker.patch.dict(os.environ, BASE_ENV, clear=True)
    mocker.patch("birdxplorer_common.storage.create_engine")

    with pytest.raises(ValueError):
        gen_storage(GlobalSettings(), statement_timeout_ms=-1)


def test_settings_rejects_negative_statement_timeout(mocker: MockerFixture) -> None:
    mocker.patch.dict(os.environ, dict(BASE_ENV, BX_STORAGE_SETTINGS__STATEMENT_TIMEOUT_MS="-1"), clear=True)

    with pytest.raises(ValidationError):
        GlobalSettings()


def test_gen_storage_keeps_database_url(mocker: MockerFixture) -> None:
    mocker.patch.dict(os.environ, BASE_ENV, clear=True)
    create_engine = mocker.patch("birdxplorer_common.storage.create_engine")
    settings = GlobalSettings()

    gen_storage(settings)

    assert create_engine.call_args.args[0] == settings.storage_settings.sqlalchemy_database_url


def test_gen_storage_passes_csv_export_statement_timeout(mocker: MockerFixture) -> None:
    # CSV エクスポート用の上限はトランザクション単位で使うので、接続ではなく
    # Storage 側へ渡る。
    env = dict(BASE_ENV, BX_STORAGE_SETTINGS__CSV_EXPORT_STATEMENT_TIMEOUT_MS="45000")
    mocker.patch.dict(os.environ, env, clear=True)
    mocker.patch("birdxplorer_common.storage.create_engine")

    storage = gen_storage(GlobalSettings())

    assert storage.csv_export_statement_timeout_ms == 45000


def test_gen_storage_csv_export_timeout_does_not_change_connection_default(mocker: MockerFixture) -> None:
    # CSV 用の値を上げても、接続全体（＝他の全クエリ）は既定 30 秒のまま。
    env = dict(BASE_ENV, BX_STORAGE_SETTINGS__CSV_EXPORT_STATEMENT_TIMEOUT_MS="45000")
    assert _connect_args(mocker, env) == {"options": "-c statement_timeout=30000"}


def test_settings_rejects_negative_csv_export_statement_timeout(mocker: MockerFixture) -> None:
    env = dict(BASE_ENV, BX_STORAGE_SETTINGS__CSV_EXPORT_STATEMENT_TIMEOUT_MS="-1")
    mocker.patch.dict(os.environ, env, clear=True)

    with pytest.raises(ValidationError):
        GlobalSettings()
