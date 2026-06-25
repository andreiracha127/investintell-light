"""Cache de respostas do catálogo (2026-06-12) — Redis com fail-open.

Middleware HTTP que cacheia respostas 200 de rotas GET de CATÁLOGO PÚBLICO
(lista/perfil/look-through de fundos, regime macro). Dados de portfólio ou
de usuário NUNCA passam por aqui — a lista de prefixos é explícita e curta.

Backend em duas camadas, decidido em runtime por requisição:
  * Redis (``REDIS_URL``) quando configurado e alcançável;
  * fallback automático para um cache em memória do processo quando o Redis
    está ausente ou falha (fail-open: cachear nunca pode derrubar request).

No InsForge o Redis roda como compute service (imagem bitnami/redis com
senha) alcançado pela rede privada Fly (.internal). Esse caminho é preview /
não documentado — exatamente por isso o fail-open é obrigatório aqui, e o
``/health`` expõe qual backend está ativo para verificação externa.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Cache namespace. The middleware stores ALREADY-SERIALIZED bodies, so a deploy
# that changes the response SHAPE/FORMATTING (e.g. title-casing manager_name)
# must NOT keep serving bodies serialized by the previous build. Two guards:
#   * ``_CACHE_SCHEMA_VERSION`` — bump by hand on any cached-response format
#     change (deterministic, works even off-platform);
#   * ``RAILWAY_DEPLOYMENT_ID`` — rotates the namespace on every deploy when
#     present (automatic). Old keys fall out by TTL.
_CACHE_SCHEMA_VERSION = "2"
_CACHE_VERSION = f"{_CACHE_SCHEMA_VERSION}.{(os.getenv('RAILWAY_DEPLOYMENT_ID') or 'base')[:20]}"

# Rotas GET cacheáveis — dados PÚBLICOS, somente leitura. Fundos e regime macro
# são espelho atualizado 1×/dia; os endpoints sob /stocks são DB-first EOD
# (preço/análise/holders mudam 1×/dia — ver o "DB-first contract" em
# stocks.py), então a resposta é estável durante o dia. /stocks/{t}/news também
# cai aqui: aceita-se até `catalog_cache_ttl_seconds` (15min) de atraso nas
# notícias em troca de cortar a latência de toda a família de stocks.
# NUNCA adicionar aqui rotas de portfólio/usuário/screener.
CACHED_GET_PREFIXES: tuple[str, ...] = (
    "/funds",
    "/macro/regime",
    "/stocks",
)

# Limite do cache em memória (entradas) — descarta o mais antigo ao exceder.
_MEMORY_MAX_ENTRIES = 512


class MemoryCache:
    """Cache processo-local com TTL; eviction FIFO simples ao exceder o cap."""

    def __init__(self, max_entries: int = _MEMORY_MAX_ENTRIES) -> None:
        self._data: dict[str, tuple[float, bytes, str]] = {}
        self._max = max_entries

    def get(self, key: str) -> tuple[bytes, str] | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, body, media_type = item
        if time.monotonic() >= expires_at:
            self._data.pop(key, None)
            return None
        return body, media_type

    def set(self, key: str, body: bytes, media_type: str, ttl: float) -> None:
        if len(self._data) >= self._max:
            self._data.pop(next(iter(self._data)), None)
        self._data[key] = (time.monotonic() + ttl, body, media_type)

    def delete_prefix(self, prefix: str) -> None:
        for key in list(self._data):
            if key.startswith(prefix):
                self._data.pop(key, None)


class CatalogCache:
    """Fachada Redis-com-fallback usada pelo middleware e pelo /health."""

    def __init__(self, label: str = "cache de catálogo") -> None:
        self._label = label
        self._memory = MemoryCache()
        self._redis: Any | None = None
        self._redis_failed_logged = False

    def _redis_client(self) -> Any | None:
        """Cliente lazy; None quando REDIS_URL não está configurada."""
        if self._redis is None:
            url = get_settings().redis_url
            if not url:
                return None
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                url,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                decode_responses=False,
            )
        return self._redis

    def _log_redis_failure_once(self, exc: Exception) -> None:
        if not self._redis_failed_logged:
            self._redis_failed_logged = True
            logger.warning(
                "Redis indisponível (%s: %s) — %s seguindo "
                "em memória (fail-open). Próximas falhas não serão logadas.",
                type(exc).__name__,
                exc,
                self._label,
            )

    async def get(self, key: str) -> tuple[bytes, str] | None:
        client = None
        try:
            client = self._redis_client()
        except Exception as exc:  # URL inválida etc. — nunca derruba request
            self._log_redis_failure_once(exc)
        if client is not None:
            try:
                raw = await client.get(key)
                if raw is not None:
                    media_type, _, body = bytes(raw).partition(b"\x00")
                    return body, media_type.decode("ascii", "replace")
                return None  # Redis saudável: miss é miss (sem olhar memória)
            except Exception as exc:
                self._log_redis_failure_once(exc)
        return self._memory.get(key)

    async def set(self, key: str, body: bytes, media_type: str, ttl: float) -> None:
        client = None
        try:
            client = self._redis_client()
        except Exception as exc:
            self._log_redis_failure_once(exc)
        if client is not None:
            try:
                await client.set(
                    key, media_type.encode("ascii") + b"\x00" + body, ex=int(ttl)
                )
                return
            except Exception as exc:
                self._log_redis_failure_once(exc)
        self._memory.set(key, body, media_type, ttl)

    async def delete_prefix(self, prefix: str) -> None:
        client = None
        try:
            client = self._redis_client()
        except Exception as exc:
            self._log_redis_failure_once(exc)
        if client is not None:
            try:
                cursor = 0
                while True:
                    cursor, keys = await client.scan(
                        cursor=cursor, match=f"{prefix}*", count=100
                    )
                    if keys:
                        await client.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as exc:
                self._log_redis_failure_once(exc)
        self._memory.delete_prefix(prefix)

    async def active_backend(self) -> str:
        """'redis' | 'memory' — exposto no /health para verificação externa."""
        try:
            client = self._redis_client()
            if client is not None:
                await client.ping()
                return "redis"
        except Exception as exc:
            self._log_redis_failure_once(exc)
        return "memory"


# Instância única do processo (o middleware e o /health compartilham).
catalog_cache = CatalogCache()
portfolio_response_cache = CatalogCache("cache privado de portfolio")


def response_cache_version() -> str:
    return _CACHE_VERSION


def cache_key(request: Request) -> str:
    """Chave determinística: namespace de versão + path + querystring ordenada.

    O namespace (``_CACHE_VERSION``) isola o cache por build/deploy, de modo que
    uma mudança de formato da resposta nunca seja servida de uma versão antiga.
    """
    query = "&".join(sorted(request.url.query.split("&"))) if request.url.query else ""
    return f"catalog:{_CACHE_VERSION}:{request.url.path}?{query}"


class CatalogCacheMiddleware(BaseHTTPMiddleware):
    """Cacheia respostas 200 das rotas GET listadas em CACHED_GET_PREFIXES."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method != "GET" or not request.url.path.startswith(
            CACHED_GET_PREFIXES
        ):
            return await call_next(request)

        key = cache_key(request)
        hit = await catalog_cache.get(key)
        if hit is not None:
            body, media_type = hit
            return Response(
                content=body, media_type=media_type, headers={"x-cache": "hit"}
            )

        response = await call_next(request)
        if response.status_code != 200:
            return response

        # Consome o body iterator UMA vez e reconstrói a resposta.
        chunks = [chunk async for chunk in response.body_iterator]  # type: ignore[attr-defined]
        body = b"".join(chunks)
        media_type = response.headers.get("content-type", "application/json")
        await catalog_cache.set(
            key, body, media_type, get_settings().catalog_cache_ttl_seconds
        )
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers["x-cache"] = "miss"
        return Response(
            content=body, status_code=200, media_type=media_type, headers=headers
        )
