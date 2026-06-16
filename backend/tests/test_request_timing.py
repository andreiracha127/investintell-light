"""Middleware de timing por rota (app/core/timing.py).

Captura a duração de cada request (path + ms) para (a) correlacionar com o
``http_response_time`` do edge do Railway e (b) medir o efeito das mudanças
DB-first (baseline antes/depois). Não toca no corpo da resposta — só mede.
"""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.timing import RequestTimingMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestTimingMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "ok"}

    return app


def test_server_timing_header_present_and_numeric() -> None:
    app = _build_app()
    with TestClient(app) as client:
        resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.json() == {"pong": "ok"}  # corpo intacto
    header = resp.headers.get("server-timing")
    assert header is not None
    # formato padrão: "app;dur=<float>"
    assert header.startswith("app;dur=")
    dur = float(header.split("=", 1)[1])
    assert dur >= 0.0


def test_emits_structured_timing_log(caplog: "pytest.LogCaptureFixture") -> None:  # noqa: F821
    app = _build_app()
    with caplog.at_level(logging.INFO, logger="app.request_timing"):
        with TestClient(app) as client:
            client.get("/ping")
    records = [r for r in caplog.records if r.name == "app.request_timing"]
    assert records, "esperado ao menos um log de request_timing"
    rec = records[-1]
    assert rec.path == "/ping"
    assert rec.method == "GET"
    assert rec.status_code == 200
    assert isinstance(rec.duration_ms, float)
    assert rec.duration_ms >= 0.0
