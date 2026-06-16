"""Middleware leve de timing por rota.

Mede a duração de parede de cada request e (a) emite um log estruturado no
logger ``app.request_timing`` e (b) seta o header padrão ``Server-Timing``.
Serve para capturar o baseline por rota antes/depois das mudanças DB-first e
correlacionar com os percentis ``http_response_time`` do edge do Railway.

Não consome nem reescreve o corpo da resposta — apenas mede e anota um header,
de modo a não interferir no streaming nem no cache de catálogo.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.request_timing")


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Loga ``method``/``path``/``status_code``/``duration_ms`` por request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0

        logger.info(
            "request_timing",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        # Header padrão Server-Timing — visível via curl/edge para medição.
        response.headers["server-timing"] = f"app;dur={duration_ms:.1f}"
        return response
