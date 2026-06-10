from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health as health_router
from app.core.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Investintell Light API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router.router)
    return application


app = create_app()
