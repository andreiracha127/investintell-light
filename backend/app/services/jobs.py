"""Async job orchestration (E3): enqueue heavy computations, poll, serve via E2.

Sem broker externo (YAGNI): o enqueue grava a linha pending e dispara uma
asyncio task que executa o runner numa SESSION NOVA (a do request fecha ao
responder 202). O resultado é gravado em optimize_jobs.result, para o caminho
de polling servir e o cache E2 reaproveitar (o runner chama serviços cacheados).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.optimize_jobs import OptimizeJob

logger = logging.getLogger(__name__)

JOB_KIND_WALK_FORWARD = "walk_forward"
JOB_KIND_PORTFOLIO_MC = "portfolio_mc"


def should_run_async(
    *, n_simulations: int | None = None, n_splits: int | None = None
) -> bool:
    settings = get_settings()
    if not getattr(settings, "use_async_jobs", False):
        return False
    if (
        n_simulations is not None
        and n_simulations >= settings.async_job_threshold_n_simulations
    ):
        return True
    if n_splits is not None and n_splits >= settings.async_job_threshold_n_splits:
        return True
    return False


def params_hash(kind: str, payload: BaseModel) -> str:
    canonical = json.dumps(
        json.loads(payload.model_dump_json()), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(f"{kind}:{canonical}".encode()).hexdigest()


async def get_job(session: Any, job_id: uuid.UUID) -> OptimizeJob | None:
    job = (
        await session.execute(select(OptimizeJob).where(OptimizeJob.id == job_id))
    ).scalar_one_or_none()
    return cast(OptimizeJob | None, job)


async def enqueue_job(
    session: Any,
    *,
    kind: str,
    params_hash: str,
    portfolio_id: int | None,
    runner: Callable[[Any], Awaitable[BaseModel]],
) -> OptimizeJob:
    """Cria a linha pending, retorna o job, e dispara a execução em background.

    ``runner(session)`` recebe uma session NOVA e retorna o Pydantic model do
    resultado. A task de fundo marca running → succeeded/failed e persiste.
    """
    job = OptimizeJob(
        id=uuid.uuid4(),
        kind=kind,
        params_hash=params_hash,
        portfolio_id=portfolio_id,
        status="pending",
    )
    session.add(job)
    await session.commit()
    job_id = job.id
    asyncio.create_task(_run_job_body(job_id, runner))
    return job


async def _run_job_body(
    job_id: uuid.UUID, runner: Callable[[Any], Awaitable[BaseModel]]
) -> None:
    async with AsyncSessionLocal() as session:
        job = await get_job(session, job_id)
        if job is None:
            return
        job.status = "running"
        await session.commit()
        try:
            result_model = await runner(session)
            job.status = "succeeded"
            job.result = json.loads(result_model.model_dump_json())
        except Exception as exc:  # noqa: BLE001 — capturar p/ persistir como failed
            logger.exception("job %s failed", job_id)
            job.status = "failed"
            job.error = str(exc)
        await session.commit()
