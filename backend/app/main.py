from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import backtest as backtest_router
from app.api.routes import builder as builder_router
from app.api.routes import correlation_regime as correlation_regime_router
from app.api.routes import funds as funds_router
from app.api.routes import health as health_router
from app.api.routes import macro as macro_router
from app.api.routes import monte_carlo as monte_carlo_router
from app.api.routes import portfolio as portfolio_router
from app.api.routes import portfolios as portfolios_router
from app.api.routes import rebalance as rebalance_router
from app.api.routes import screener as screener_router
from app.api.routes import search as search_router
from app.api.routes import statistics as statistics_router
from app.api.routes import stocks as stocks_router
from app.api.routes import treasury as treasury_router
from app.core.cache import CatalogCacheMiddleware
from app.core.config import get_settings
from app.core.db import engine
from app.core.policy_startup import validate_combo_startup
from app.core.tiingo_provider import provider as tiingo_provider
from app.core.timing import RequestTimingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # COMBO regime_aware policy core: fail-loud at boot if any of the 12 policies,
    # the gate shape/ladder, or the legacy-symbol scan fails (spec §37). Raising
    # here aborts the boot — the service must not serve an invalid policy set.
    validate_combo_startup()
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
    # Cache de respostas das rotas de catálogo público (Redis fail-open →
    # memória). Registrado ANTES do CORS na pilha (CORS por fora) para que
    # hits cacheados também recebam os headers de CORS.
    application.add_middleware(CatalogCacheMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_allow_origins,
        # POST is required by /portfolio/analysis (ad-hoc body, no persistence);
        # PATCH/PUT/DELETE by the persisted-portfolio CRUD (/portfolios, F4).
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    # Camada mais externa (registrada por último): mede o tempo total de
    # servidor por rota, inclusive cache hits e o custo do próprio CORS.
    application.add_middleware(RequestTimingMiddleware)
    application.include_router(health_router.router)
    application.include_router(stocks_router.router)
    application.include_router(portfolio_router.router)
    application.include_router(portfolios_router.router)
    application.include_router(statistics_router.router)
    application.include_router(screener_router.router)
    application.include_router(funds_router.router)
    application.include_router(backtest_router.router)
    application.include_router(builder_router.router)
    application.include_router(macro_router.router)
    application.include_router(correlation_regime_router.router)
    application.include_router(treasury_router.router)
    application.include_router(monte_carlo_router.router)
    application.include_router(rebalance_router.router)
    application.include_router(search_router.router)
    return application


app = create_app()
