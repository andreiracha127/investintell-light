import functools
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root is three levels above this file's directory:
# backend/app/core/config.py → backend/app/core → backend/app → backend → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Both .env locations are listed; backend/.env takes precedence (later files win in
    # pydantic-settings). The .env may live at repo root OR at backend/.env — both are read.
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT / ".env"), str(_BACKEND_ROOT / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://light:light@localhost:5436/investintell_light"
    )
    # Tiingo API token — used from F1 onward. NEVER expose to frontend or logs.
    tiingo_token: str | None = None
    # Read-only connection to the investintell-allocation mother DB — used from F6 onward.
    investintell_db_url: str | None = None
    # Read-only connection to the TimescaleDB Cloud data-lake (Tiger
    # Investintell-Prod) — consumed by the look-through endpoints (Frente C):
    # the Light READS the tables materialized by the nport_lookthrough worker
    # there; it never computes look-through in a request path.
    datalake_db_url: str | None = None

    # --- InsForge auth (JWT validated locally; Auth stays on InsForge) ---
    # InsForge issues HS256 access tokens signed with a shared secret (no JWKS,
    # no iss/aud claims). The FastAPI verifies them LOCALLY with this secret —
    # no round-trip per request. Unset → protected routes return 503 (declared).
    insforge_jwt_secret: str | None = None

    # --- Catalog response cache (2026-06-12) ---
    # Optional Redis DSN (redis://[:pass@]host:port/db). Unset or unreachable
    # → in-process memory cache (fail-open by design: caching must never
    # break a request). Only PUBLIC catalog routes are cached (see
    # app/core/cache.py CACHED_GET_PREFIXES) — never portfolio/user data.
    redis_url: str | None = None
    # TTL for cached catalog responses. The mirror refreshes once a day
    # (fund-catalog-sync 09:00 UTC), so minutes-level TTL is conservative.
    catalog_cache_ttl_seconds: int = 900

    # --- API / CORS settings (F2) ---
    # Browser origins allowed to call the API. Dev = Next.js local server;
    # prod = the public site (www + apex). Em produção o InsForge compute
    # sobrescreve via env var CORS_ALLOW_ORIGINS (JSON list), mas o domínio
    # oficial fica versionado aqui para sobreviver a redeploys sem a env var.
    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://www.investintell.com",
        "https://investintell.com",
    ]

    # --- Tiingo client settings (F1) ---
    tiingo_base_url: str = "https://api.tiingo.com"
    tiingo_rate_per_sec: float = 2.0
    tiingo_burst: int = 10
    tiingo_hourly_cap: int = 9000
    tiingo_daily_cap: int = 90000
    tiingo_timeout_seconds: float = 15.0
    tiingo_max_retries: int = 3

    # --- EOD ingestion / price-series settings (F1.3) ---
    # An instrument is "fresh" when eod_last_fetched_at is within this window.
    eod_staleness_hours: float = 24.0
    # Hard cap on cold/stale tickers ingested per request (fail loud — never a subset).
    max_cold_tickers_per_request: int = 5
    # Deadline (seconds) for the synchronous cold-ticker Tiingo fetch that may
    # still happen on the request path under Strategy B. Caps the latency tail:
    # a slow/hung provider call is turned into a 503 instead of hanging the
    # request. Only bites when a cold ticker (no DB rows) is fetched inline.
    ensure_cold_fetch_deadline_seconds: float = 5.0
    # Hard cap on data points returned by the price-series endpoint.
    price_series_max_points: int = 7000

    # --- DB connection pool (latency-tail hardening) ---
    # Sized against the TimescaleDB Cloud ceiling (max_connections=200, shared
    # with the datalake workers + exporters). pool_size+max_overflow per API
    # process stays far under that even across replicas. pre_ping is disabled in
    # db.py (it adds +1 RTT per checkout, painful cross-region); pool_recycle
    # handles stale connections instead. pool_timeout fails a stuck checkout fast
    # rather than hanging the request.
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_seconds: float = 10.0
    db_pool_recycle_seconds: int = 1800

    # --- News ingestion settings (F2.4) ---
    # Per-ticker news is "fresh" when max(fetched_at) over the ticker's rows
    # is within this window.
    news_staleness_minutes: float = 30.0
    # How many articles to request from Tiingo per refresh (Tiingo caps at 100).
    news_fetch_limit: int = 50

    # DB-first Grupo D: quando True, leituras de preço/NAV usam os
    # *_latest_mv (com fallback à tabela base p/ entidades ainda ausentes).
    use_latest_mv_prices: bool = False

    # DB-first Group C: when True, the interactive series endpoints
    # (funds/stock analysis, entity-analytics series, risk-timeseries) compute
    # rolling/distribution/drawdown/VaR-CVaR series via on-demand SQL functions
    # instead of pandas. Legacy pandas path runs when False (default).
    use_series_db_first: bool = False


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
