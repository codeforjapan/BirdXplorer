import logging
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from birdxplorer_api.middlewares.timing import TimingMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TimingMiddleware)

    @app.get("/items")
    def list_items(  # pragma: no cover - exercised through TestClient
        limit: int = 100,
        offset: int = 0,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Dict[str, Any]:
        return {"limit": limit, "offset": offset, "start_date": start_date, "end_date": end_date}

    @app.get("/boom")
    def boom() -> Dict[str, Any]:  # pragma: no cover - exercised through TestClient
        raise RuntimeError("explode")

    return app


def test_timing_middleware_adds_response_time_header() -> None:
    client = TestClient(_build_app())
    response = client.get("/items")

    assert response.status_code == 200
    assert "x-response-time-ms" in response.headers
    assert float(response.headers["x-response-time-ms"]) >= 0.0


def test_timing_middleware_logs_request_with_relevant_query_params(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_build_app())
    with caplog.at_level(logging.INFO, logger="birdxplorer_common.logger"):
        response = client.get(
            "/items",
            params={
                "limit": 50,
                "offset": 10,
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "irrelevant": "ignore-me",
            },
        )

    assert response.status_code == 200
    records = [r for r in caplog.records if r.getMessage() == "request_timing"]
    assert len(records) == 1

    record = records[0]
    assert record.method == "GET"  # type: ignore[attr-defined]
    assert record.path == "/items"  # type: ignore[attr-defined]
    assert record.status_code == 200  # type: ignore[attr-defined]
    assert record.duration_ms >= 0.0  # type: ignore[attr-defined]

    filter_params = record.filter_params  # type: ignore[attr-defined]
    assert filter_params["limit"] == "50"
    assert filter_params["offset"] == "10"
    assert filter_params["start_date"] == "2026-01-01"
    assert filter_params["end_date"] == "2026-01-31"
    assert "irrelevant" not in filter_params


def test_timing_middleware_logs_period_days_when_dates_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_build_app())
    with caplog.at_level(logging.INFO, logger="birdxplorer_common.logger"):
        response = client.get(
            "/items",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )

    assert response.status_code == 200
    records = [r for r in caplog.records if r.getMessage() == "request_timing"]
    assert len(records) == 1
    assert records[0].period_days == 30  # type: ignore[attr-defined]


def test_timing_middleware_logs_error_status_on_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="birdxplorer_common.logger"):
        response = client.get("/boom")

    assert response.status_code == 500
    records = [r for r in caplog.records if r.getMessage() == "request_timing"]
    assert len(records) == 1
    assert records[0].status_code == 500  # type: ignore[attr-defined]
    assert records[0].duration_ms >= 0.0  # type: ignore[attr-defined]
