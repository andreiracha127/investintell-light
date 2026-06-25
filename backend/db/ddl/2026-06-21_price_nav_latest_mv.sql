-- backend/db/ddl/2026-06-21_price_nav_latest_mv.sql
-- Read-model MVs servidos pelo Light no DB principal. Achatam as DUAS
-- observações diárias mais recentes por entidade em uma linha (last_* + prev_*),
-- lendo dos CAGGs diários. Refrescados pelo worker matview_refresh
-- (REFRESH … CONCURRENTLY exige os índices UNIQUE abaixo).

-- Fonte primária = CAGGs diários canônicos (cagg_eod_daily / cagg_nav_daily).
-- Para preço, tickers presentes em eod_prices mas ausentes do CAGG (ex. proxy
-- ETFs carregados fora do universo principal) entram pelo fallback base-table.
-- Isso preserva o contrato DB-first e evita que o overview volte ao fallback
-- request-time em eod_prices para esses tickers. bucket é o time_bucket diário;
-- cast ::date para casar com PositionOverview.as_of (dt.date).

CREATE MATERIALIZED VIEW IF NOT EXISTS price_latest_mv AS
WITH cagg_tickers AS (
    SELECT DISTINCT ticker
    FROM cagg_eod_daily
    WHERE close IS NOT NULL
),
daily AS (
    SELECT ticker, bucket::date AS as_of, close
    FROM cagg_eod_daily
    WHERE close IS NOT NULL
    UNION ALL
    SELECT ticker, date AS as_of, close
    FROM eod_prices
    WHERE close IS NOT NULL
      AND ticker NOT IN (SELECT ticker FROM cagg_tickers)
),
ranked AS (
    SELECT ticker, as_of, close,
           row_number() OVER (PARTITION BY ticker ORDER BY as_of DESC) AS rn
    FROM daily
)
SELECT
    ticker,
    max(as_of)   FILTER (WHERE rn = 1)        AS as_of,
    max(close)   FILTER (WHERE rn = 1)        AS last_close,
    max(as_of)   FILTER (WHERE rn = 2)        AS prev_date,
    max(close)   FILTER (WHERE rn = 2)        AS prev_close
FROM ranked
WHERE rn <= 2
GROUP BY ticker
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS price_latest_mv_pk ON price_latest_mv (ticker);

CREATE MATERIALIZED VIEW IF NOT EXISTS nav_latest_mv AS
WITH ranked AS (
    SELECT instrument_id, bucket, nav,
           row_number() OVER (PARTITION BY instrument_id ORDER BY bucket DESC) AS rn
    FROM cagg_nav_daily
    WHERE nav IS NOT NULL
)
SELECT
    instrument_id,
    (max(bucket) FILTER (WHERE rn = 1))::date AS as_of,
    max(nav)     FILTER (WHERE rn = 1)        AS last_nav,
    (max(bucket) FILTER (WHERE rn = 2))::date AS prev_date,
    max(nav)     FILTER (WHERE rn = 2)        AS prev_nav
FROM ranked
WHERE rn <= 2
GROUP BY instrument_id
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS nav_latest_mv_pk ON nav_latest_mv (instrument_id);

-- Populate inicial NÃO-concorrente: CONCURRENTLY falha enquanto o MV nunca
-- foi populado. O worker matview_refresh usa CONCURRENTLY a partir daqui.
REFRESH MATERIALIZED VIEW price_latest_mv;
REFRESH MATERIALIZED VIEW nav_latest_mv;
