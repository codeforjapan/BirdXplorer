import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from birdxplorer_common.logger import get_logger

RELEVANT_PARAMS: Tuple[str, ...] = (
    "start_date",
    "end_date",
    "created_at_from",
    "created_at_to",
    "limit",
    "offset",
    "topic_ids",
    "current_status",
    "language",
    "search_text",
)


def _decode_query_string(scope: Scope) -> str:
    raw = scope.get("query_string")
    if not isinstance(raw, bytes):
        return ""
    return raw.decode("utf-8", errors="replace")


def _extract_filter_params(query_string: str) -> Dict[str, str]:
    if not query_string:
        return {}
    parsed = parse_qs(query_string, keep_blank_values=False)
    out: Dict[str, str] = {}
    for key in RELEVANT_PARAMS:
        values = parsed.get(key)
        if values:
            out[key] = values[0]
    return out


def _compute_period_days(filter_params: Dict[str, str]) -> Optional[int]:
    start = filter_params.get("start_date") or filter_params.get("created_at_from")
    end = filter_params.get("end_date") or filter_params.get("created_at_to")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


class TimingMiddleware:
    """ASGI middleware that records per-request handling time.

    Adds an ``X-Response-Time-ms`` response header and emits a structured
    ``request_timing`` log line carrying method, path, status_code,
    duration_ms, the relevant filter query params, and the requested period
    in days when start/end dates are supplied.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._logger = get_logger()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        start_perf = time.perf_counter()
        state: Dict[str, int] = {"status": 500}

        async def send_with_timing(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = int(message.get("status", 500))
                elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
                headers: List[Tuple[bytes, bytes]] = list(message.get("headers") or [])
                headers.append(
                    (b"x-response-time-ms", f"{elapsed_ms:.2f}".encode("ascii")),
                )
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, send_with_timing)
        finally:
            duration_ms = round((time.perf_counter() - start_perf) * 1000.0, 3)
            self._emit_log(scope, state["status"], duration_ms)

    def _emit_log(self, scope: Scope, status_code: int, duration_ms: float) -> None:
        query_string = _decode_query_string(scope)
        filter_params = _extract_filter_params(query_string)
        record: Dict[str, Any] = {
            "method": str(scope.get("method", "")),
            "path": str(scope.get("path", "")),
            "status_code": status_code,
            "duration_ms": duration_ms,
            "filter_params": filter_params,
        }
        period_days = _compute_period_days(filter_params)
        if period_days is not None:
            record["period_days"] = period_days
        self._logger.info("request_timing", extra=record)
