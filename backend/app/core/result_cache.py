"""Cache de RESULTADO por hash (E2) — Redis com fail-open, namespace próprio.

Separado do middleware de catálogo (app/core/cache.py): aqui cacheiam-se as
respostas DETERMINÍSTICAS das ferramentas interativas (statistics/*, backtest/
walk-forward, correlation-regime, monte-carlo COM seed). A chave é um hash dos
parâmetros normalizados; entradas que envolvem portfólio do usuário incluem o
HASH DE VERSÃO do portfólio (posições + cash + updated_at), preservando
isolamento e invalidando ao editar.

Fail-open: qualquer falha/ausência do Redis é tratada como MISS (a rota recalcula).
Diferente do catálogo, NÃO há fallback em memória — um cache de resultado por
processo daria pouca taxa de acerto e arriscaria divergência entre workers.

Guard de versão (_RESULT_CACHE_VERSION): bump manual do schema_version em qualquer
mudança de SHAPE de resposta cacheada, + RAILWAY_DEPLOYMENT_ID que rotaciona o
namespace a cada deploy (espelha _CACHE_VERSION em app/core/cache.py).
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RESULT_CACHE_SCHEMA_VERSION = "1"
_RESULT_CACHE_VERSION = (
    f"{_RESULT_CACHE_SCHEMA_VERSION}."
    f"{(os.getenv('RAILWAY_DEPLOYMENT_ID') or 'base')[:20]}"
)


class ResultCache:
    """Fachada Redis-only com fail-open para respostas de resultado."""

    def __init__(self) -> None:
        self._redis: Any | None = None
        self._redis_failed_logged = False

    def _redis_client(self) -> Any | None:
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

    def _log_failure_once(self, exc: Exception) -> None:
        if not self._redis_failed_logged:
            self._redis_failed_logged = True
            logger.warning(
                "Redis indisponível (%s: %s) — result cache em modo fail-open "
                "(tratando como miss). Próximas falhas não serão logadas.",
                type(exc).__name__,
                exc,
            )

    async def get(self, key: str) -> bytes | None:
        try:
            client = self._redis_client()
        except Exception as exc:
            self._log_failure_once(exc)
            return None
        if client is None:
            return None
        try:
            raw = await client.get(key)
            return bytes(raw) if raw is not None else None
        except Exception as exc:
            self._log_failure_once(exc)
            return None

    async def set(self, key: str, body: bytes, ttl: float) -> None:
        try:
            client = self._redis_client()
        except Exception as exc:
            self._log_failure_once(exc)
            return
        if client is None:
            return
        try:
            await client.set(key, body, ex=int(ttl))
        except Exception as exc:
            self._log_failure_once(exc)

    async def active_backend(self) -> str:
        try:
            client = self._redis_client()
            if client is not None:
                await client.ping()
                return "redis"
        except Exception as exc:
            self._log_failure_once(exc)
        return "disabled"


result_cache = ResultCache()


def result_cache_key(kind: str, payload: BaseModel) -> str:
    """Chave determinística: namespace de versão + kind + sha256 do JSON canônico.

    model_dump_json(...) reserializado com sort_keys torna a chave invariante à
    ordem dos campos.
    """
    canonical = payload.model_dump_json()
    # Reserializa ordenado para invariância de ordem de campos.
    canonical = json.dumps(json.loads(canonical), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"result:{_RESULT_CACHE_VERSION}:{kind}:{digest}"


def portfolio_version_hash(portfolio: Any) -> str:
    """Hash de versão de um portfólio: posições (ticker, qty, acq_price) ordenadas
    + cash + updated_at. Inclui o conteúdo, não só o id — assim editar o portfólio
    muda a chave de cache (spec §15: derivar versão de posições + timestamp).
    """
    positions = sorted(
        (
            (
                p.ticker,
                float(p.quantity),
                None if p.acq_price is None else float(p.acq_price),
            )
            for p in portfolio.positions
        ),
        key=lambda t: t[0],
    )
    blob = json.dumps(
        {
            "id": portfolio.id,
            "cash": float(portfolio.cash),
            "updated_at": portfolio.updated_at.isoformat() if portfolio.updated_at else None,
            "positions": positions,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_M = TypeVar("_M", bound=BaseModel)


def cached_result(
    kind: str,
    *,
    ttl_setting: str = "result_cache_ttl_seconds",
    cacheable: Callable[[BaseModel], bool] | None = None,
) -> Callable[[Callable[..., Awaitable[_M]]], Callable[..., Awaitable[_M]]]:
    """Decorator: cacheia o retorno (Pydantic model) de um serviço async.

    A função decorada tem assinatura (session, payload: BaseModel, *args, **kwargs)
    e retorna um Pydantic model. Comportamento:
      * settings.use_result_cache False → passa direto (sem tocar Redis);
      * cacheable(payload) False (ex.: monte-carlo sem seed) → passa direto;
      * senão: chave = result_cache_key(kind, payload); hit → reidrata o model
        da classe de retorno; miss → computa, serializa, grava, retorna.
    Fail-open garantido por ResultCache (erro de Redis = miss).
    """

    def _decorate(fn: Callable[..., Awaitable[_M]]) -> Callable[..., Awaitable[_M]]:
        # A classe de retorno é resolvida da anotação de retorno da função.
        return_model = fn.__annotations__.get("return")

        @functools.wraps(fn)
        async def _wrapper(session: Any, payload: BaseModel, *args: Any, **kwargs: Any) -> _M:
            settings = get_settings()
            if not getattr(settings, "use_result_cache", False):
                return await fn(session, payload, *args, **kwargs)
            if cacheable is not None and not cacheable(payload):
                return await fn(session, payload, *args, **kwargs)

            key = result_cache_key(kind, payload)
            hit = await result_cache.get(key)
            if hit is not None and return_model is not None:
                return return_model.model_validate_json(hit)  # type: ignore[no-any-return]

            result = await fn(session, payload, *args, **kwargs)
            ttl = float(getattr(settings, ttl_setting))
            await result_cache.set(key, result.model_dump_json().encode("utf-8"), ttl)
            return result

        return _wrapper

    return _decorate
