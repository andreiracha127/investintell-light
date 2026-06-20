"""ORM model for the ``optimize_jobs`` table (Sprint A, Task 3).

Broad-universe ``POST /builder/optimize`` runs asynchronously: a request is
persisted here as a job, a background task (Task 4) advances it through the
``pending -> running -> succeeded|failed`` state machine, and a polling
endpoint reads the row back. State lives in this table — never in process
memory — so polling works across pods.

Tenancy: rows are scoped by ``organization_id`` (the org-scoped/RLS direction
the publish target uses), unlike the single-tenant portfolio tables. The
column is NOT NULL; the caller (the route) supplies the org from the verified
identity. The (organization_id, created_at DESC) index serves the per-org
"my recent jobs" listing.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Allowed job states — kept in sync with the CHECK constraint below and the
# service helpers in app/services/optimize_jobs.py.
JOB_STATUSES = ("pending", "running", "succeeded", "failed")


class OptimizeJob(Base):
    __tablename__ = "optimize_jobs"

    # Application-generated UUID PK. A Python-side default mirrors the DDL's
    # gen_random_uuid() so an ORM insert never needs a DB round-trip to learn
    # its own id (the background task references it immediately).
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )

    # Owning organization — org-scoped tenancy (NOT NULL, route-supplied).
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    # Job lifecycle state; CHECK-constrained to JOB_STATUSES. New jobs start
    # 'pending' (server default matches create_job's explicit set).
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )

    # The original optimize request payload (objective, universe, caps, ...).
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # The optimizer output on success; NULL while pending/running or on failure.
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Failure message on a failed run; NULL otherwise.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit timestamps — tz-aware, server-set. updated_at also bumps via
    # onupdate on ORM updates; the service helpers set it explicitly too so a
    # Core-level update path stays correct (same caveat as the portfolio
    # tables).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # Convention-expanded to ck_optimize_jobs_status.
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="status",
        ),
        # Per-org recency listing: WHERE organization_id = ? ORDER BY created_at.
        Index(
            "ix_optimize_jobs_organization_id_created_at",
            "organization_id",
            "created_at",
        ),
    )
