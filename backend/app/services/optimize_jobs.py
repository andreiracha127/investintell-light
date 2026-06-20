"""Persistence service for ``optimize_jobs`` (Sprint A, Task 3).

Async CRUD helpers that drive the job state machine. Routes own HTTP mapping;
this module owns the SQL/ORM. Contract:

- ``create_job`` inserts a ``pending`` job and returns it (id populated).
- ``get_job`` returns the row or ``None`` ("not found" → route 404).
- ``mark_running`` / ``mark_succeeded`` / ``mark_failed`` advance an existing
  job and return the updated row, or ``None`` if the id is unknown.

Every mutation stamps ``updated_at`` explicitly (the ORM ``onupdate`` hook only
fires on ORM updates; setting it here keeps the timestamp correct regardless of
how the update is emitted — same caveat as the portfolio tables). Callers own
the transaction boundary; these helpers ``flush`` so the row/changes are visible
within the session but do not ``commit``.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.optimize_job import OptimizeJob


async def create_job(
    session: AsyncSession, org_id: uuid.UUID | None, request: dict
) -> OptimizeJob:
    """Insert a new ``pending`` job for ``org_id`` and return it (id populated).

    ``org_id`` is nullable: ``POST /builder/optimize`` is public and the app is
    single-tenant today, so the async path creates jobs with ``org_id=None``.
    """
    job = OptimizeJob(
        organization_id=org_id,
        status="pending",
        request=request,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(
    session: AsyncSession, job_id: uuid.UUID
) -> OptimizeJob | None:
    """Return the job by id, or ``None`` if it does not exist."""
    return await session.get(OptimizeJob, job_id)


async def mark_running(
    session: AsyncSession, job_id: uuid.UUID
) -> OptimizeJob | None:
    """Transition a job to ``running``; return it, or ``None`` if missing."""
    job = await session.get(OptimizeJob, job_id)
    if job is None:
        return None
    job.status = "running"
    job.updated_at = dt.datetime.now(dt.UTC)
    await session.flush()
    return job


async def mark_succeeded(
    session: AsyncSession, job_id: uuid.UUID, result: dict
) -> OptimizeJob | None:
    """Mark a job ``succeeded`` with its result; return it, or ``None`` if missing."""
    job = await session.get(OptimizeJob, job_id)
    if job is None:
        return None
    job.status = "succeeded"
    job.result = result
    job.error = None
    job.updated_at = dt.datetime.now(dt.UTC)
    await session.flush()
    return job


async def mark_failed(
    session: AsyncSession, job_id: uuid.UUID, error: str
) -> OptimizeJob | None:
    """Mark a job ``failed`` with an error message; return it, or ``None`` if missing."""
    job = await session.get(OptimizeJob, job_id)
    if job is None:
        return None
    job.status = "failed"
    job.error = error
    job.updated_at = dt.datetime.now(dt.UTC)
    await session.flush()
    return job
