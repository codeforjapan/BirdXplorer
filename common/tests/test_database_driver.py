"""接続 URL がドライバを明示していることのテスト。

2026-09-24 に SQLAlchemy 2.1.0 がリリースされ、`postgresql://` の既定ドライバが
psycopg2 から psycopg(v3) に変わった。pyproject で sqlalchemy をバージョン未指定に
していたため 09-25 のイメージビルドで 2.1 が混入し、依存は psycopg2-binary しか
無いので ModuleNotFoundError で以下が全滅した:

  日次 Extract       09-25 から4日連続で起動即死（全フェーズ未実行）
  DbWriter Lambda    1日あたり約2,500件のエラー、db-write-dlq に 17,364件 滞留
  NoteTransform      同 約1,900件、note-transform-dlq に 8,682件 滞留

URL でドライバを明示していれば、SQLAlchemy の既定が何に変わっても影響を受けない。
バージョン固定（sqlalchemy<2.1）と両方入れる。固定だけだと将来 2.1 に上げる際に
同じ穴が開き、明示だけだと 2.1 の他の非互換を踏みうる。
"""

from birdxplorer_common.settings import PostgresStorageSettings


def _settings() -> PostgresStorageSettings:
    return PostgresStorageSettings(host="db.example.com", username="u", password="p", port=5432, database="postgres")


class TestDriverIsExplicit:
    def test_the_url_names_psycopg2(self) -> None:
        """ドライバを省くと SQLAlchemy の既定に左右される。2.1 でそれが psycopg(v3) に変わった。"""
        assert _settings().sqlalchemy_database_url.startswith("postgresql+psycopg2://")

    def test_the_rest_of_the_url_is_unchanged(self) -> None:
        """ドライバを足すついでに他を壊していないこと。"""
        url = _settings().sqlalchemy_database_url
        assert "://u:p@db.example.com:5432/postgres" in url

    def test_an_at_sign_in_the_password_is_still_escaped(self) -> None:
        s = PostgresStorageSettings(host="h", username="u", password="pa@ss", port=5432, database="postgres")
        assert "pa%40ss" in s.sqlalchemy_database_url
