-- optimize_jobs: async broad-universe optimization jobs (Sprint A, Task 3).
--
-- Broad-universe POST /builder/optimize runs in the background. A request is
-- persisted here, a background task advances it through
-- pending -> running -> succeeded|failed, and a polling endpoint reads it back.
-- State lives in this table (never in process memory) so polling works across
-- pods. Rows are org-scoped (organization_id NOT NULL); the (organization_id,
-- created_at DESC) index serves the per-org "my recent jobs" listing.
--
-- Constraint/index names match the SQLAlchemy naming convention (app/models/base.py)
-- so the ORM model and this DDL stay in lockstep:
--   pk_optimize_jobs, ck_optimize_jobs_status,
--   ix_optimize_jobs_organization_id_created_at.

CREATE TABLE IF NOT EXISTS optimize_jobs (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    organization_id uuid        NOT NULL,
    status          text        NOT NULL DEFAULT 'pending',
    request         jsonb       NOT NULL,
    result          jsonb,
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_optimize_jobs PRIMARY KEY (id),
    CONSTRAINT ck_optimize_jobs_status
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed'))
);

CREATE INDEX IF NOT EXISTS ix_optimize_jobs_organization_id_created_at
    ON optimize_jobs (organization_id, created_at DESC);
