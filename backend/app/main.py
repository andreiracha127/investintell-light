from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health as health_router
from app.api.routes import stocks as stocks_router
from app.core.db import engine
from app.core.tiingo_provider import provider as tiingo_provider


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # The TiingoClient is created lazily on first dependency use (the app must
    # boot without a token so /health works); if created, close it here.
    yield
    await tiingo_provider.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Investintell Light API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router.router)
    application.include_router(stocks_router.router)
    return application


app = create_app()
