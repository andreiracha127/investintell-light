-- backend/db/ddl/2026-06-21_price_nav_latest_mv.sql
-- Read-model MVs servidos pelo Light no DB principal. Achatam as DUAS
-- observações diárias mais recentes por entidade em uma linha (last_* + prev_*),
-- lendo dos CAGGs diários. Refrescados pelo worker matview_refresh
-- (REFRESH … CONCURRENTLY exige os índices UNIQUE abaixo).

-- Fonte = CAGGs diários canônicos (cagg_eod_daily / cagg_nav_daily), não as
-- tabelas cruas: alinha com a leitura db-first das rotas (38dbdb4), é mais
-- barato e tem real-time aggregation (inclui o dia corrente). Como eod_prices /
-- nav_timeseries são diários e os CAGGs usam last(... , <date>) por bucket, os
-- valores são idênticos aos da leitura legada (paridade). bucket é o time_bucket
-- diário; cast ::date para casar com PositionOverview.as_of (dt.date).

CREATE MATERIALIZED VIEW IF NOT EXISTS price_latest_mv AS
WITH ranked AS (
    SELECT ticker, bucket, close,
           row_number() OVER (PARTITION BY ticker ORDER BY bucket DESC) AS rn
    FROM cagg_eod_daily
    WHERE close IS NOT NULL
)
SELECT
    ticker,
    (max(bucket) FILTER (WHERE rn = 1))::date AS as_of,
    max(close)   FILTER (WHERE rn = 1)        AS last_close,
    (max(bucket) FILTER (WHERE rn = 2))::date AS prev_date,
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
