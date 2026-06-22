"""Schemas for async job enqueue/polling (E3)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class JobEnqueuedResponse(BaseModel):
    """Returned with HTTP 202 when a heavy computation is queued."""

    job_id: uuid.UUID
    status: str = Field(description="pending | running | succeeded | failed")
    kind: str


class JobStatusResponse(BaseModel):
    """Polling payload for GET /jobs/{job_id}."""

    job_id: uuid.UUID
    status: str
    kind: str
    result: dict | None = Field(default=None, description="Serviço result quando succeeded.")
    error: str | None = Field(default=None, description="Mensagem quando failed.")
