"""Tests for the optimize_jobs persistence layer (Sprint A, Task 3).

Two layers are covered without a live database:

- Model metadata: the ``optimize_jobs`` table is registered with the expected
  columns, types, CHECK constraint and (organization_id, created_at) index.
  These are offline inspections of ``Base.metadata`` (same style as
  test_models.py).
- CRUD service: ``create_job`` / ``get_job`` / ``mark_running`` /
  ``mark_succeeded`` / ``mark_failed`` are exercised against a small in-memory
  fake AsyncSession. The fake mimics the ORM identity map closely enough to
  assert the state-machine contract (status transitions, result/error storage,
  updated_at bumps) that Task 4's background runner depends on.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import JSON, CheckConstraint, Uuid

# Importing Base triggers app.models.__init__, registering every ORM model.
from app.models import Base
from app.models.optimize_job import OptimizeJob
from app.services import optimize_jobs as svc

# ---------------------------------------------------------------------------
# Fake AsyncSession — dict-backed identity map keyed by primary key.
# ---------------------------------------------------------------------------


class FakeAsyncSession:
    """Minimal async session: add()/get()/flush()/commit() over a dict store.

    Mirrors the slice of AsyncSession the optimize_jobs service uses. ``add``
    applies the model's Python-side defaults (id default + server_default for
    status/timestamps) so freshly created rows look like a real INSERT
    round-trip. ``get`` returns the same instance (identity map).
    """

    def __init__(self) -> None:
        self.store: dict[Any, OptimizeJob] = {}

    def add(self, obj: OptimizeJob) -> None:
        if obj.id is None:
            default = OptimizeJob.id.default
            obj.id = default.arg(None) if default is not None else uuid.uuid4()
        if obj.status is None:
            obj.status = "pending"
        now = dt.datetime.now(dt.UTC)
        if obj.created_at is None:
            obj.created_at = now
        if obj.updated_at is None:
            obj.updated_at = now
        self.store[obj.id] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def get(self, model: type[OptimizeJob], pk: Any) -> OptimizeJob | None:
        return self.store.get(pk)


@pytest.fixture
def session() -> FakeAsyncSession:
    return FakeAsyncSession()


_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
_REQUEST = {"objective": "max_return_cvar", "universe": "fixed_income", "n": 25}


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------


def test_optimize_jobs_table_registered() -> None:
    assert "optimize_jobs" in Base.metadata.tables


def test_optimize_jobs_pk_is_uuid_named_by_convention() -> None:
    table = Base.metadata.tables["optimize_jobs"]
    pk = table.primary_key
    assert pk.name == "pk_optimize_jobs"
    pk_cols = list(pk.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "id"
    assert isinstance(pk_cols[0].type, Uuid)


def test_optimize_jobs_columns_and_nullability() -> None:
    table = Base.metadata.tables["optimize_jobs"]
    assert isinstance(table.c["organization_id"].type, Uuid)
    assert table.c["organization_id"].nullable is False
    assert table.c["status"].nullable is False
    assert isinstance(table.c["request"].type, JSON)
    assert table.c["request"].nullable is False
    assert isinstance(table.c["result"].type, JSON)
    assert table.c["result"].nullable is True
    assert table.c["error"].nullable is True
    for col in ("created_at", "updated_at"):
        assert table.c[col].nullable is False
        assert table.c[col].type.timezone is True  # type: ignore[attr-defined]


def test_optimize_jobs_status_check_constraint() -> None:
    table = Base.metadata.tables["optimize_jobs"]
    checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
    assert "ck_optimize_jobs_status" in checks


def test_optimize_jobs_org_created_index() -> None:
    table = Base.metadata.tables["optimize_jobs"]
    index_names = {idx.name for idx in table.indexes}
    assert "ix_optimize_jobs_organization_id_created_at" in index_names


# ---------------------------------------------------------------------------
# CRUD service — state machine
# ---------------------------------------------------------------------------


async def test_create_job_is_pending_and_stores_request(
    session: FakeAsyncSession,
) -> None:
    job = await svc.create_job(session, _ORG, _REQUEST)
    assert job.id is not None
    assert job.organization_id == _ORG
    assert job.status == "pending"
    assert job.request == _REQUEST
    assert job.result is None
    assert job.error is None


async def test_get_job_recovers_created_job(session: FakeAsyncSession) -> None:
    job = await svc.create_job(session, _ORG, _REQUEST)
    fetched = await svc.get_job(session, job.id)
    assert fetched is job


async def test_get_job_missing_returns_none(session: FakeAsyncSession) -> None:
    assert await svc.get_job(session, uuid.uuid4()) is None


async def test_mark_running_transitions_status(session: FakeAsyncSession) -> None:
    job = await svc.create_job(session, _ORG, _REQUEST)
    before = job.updated_at
    updated = await svc.mark_running(session, job.id)
    assert updated is not None
    assert updated.status == "running"
    assert updated.updated_at >= before


async def test_mark_succeeded_stores_result(session: FakeAsyncSession) -> None:
    job = await svc.create_job(session, _ORG, _REQUEST)
    result = {"weights": {"AGG": 0.6, "BND": 0.4}, "sharpe": 1.2}
    updated = await svc.mark_succeeded(session, job.id, result)
    assert updated is not None
    assert updated.status == "succeeded"
    assert updated.result == result
    assert updated.error is None


async def test_mark_failed_stores_error(session: FakeAsyncSession) -> None:
    job = await svc.create_job(session, _ORG, _REQUEST)
    updated = await svc.mark_failed(session, job.id, "solver infeasible")
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error == "solver infeasible"
    assert updated.result is None


async def test_mark_helpers_on_missing_job_return_none(
    session: FakeAsyncSession,
) -> None:
    missing = uuid.uuid4()
    assert await svc.mark_running(session, missing) is None
    assert await svc.mark_succeeded(session, missing, {"x": 1}) is None
    assert await svc.mark_failed(session, missing, "boom") is None
