from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    # Backend ativo do cache de catálogo: "redis" ou "memory" (fail-open).
    cache: str = "memory"
