-- backend/db/ddl/2026-06-21_holding_reverse_lookup_mv.sql
-- B3 read-model (datalake DB), LADO INSTITUCIONAL apenas: holders 13F por cusip
-- no período mais recente daquele cusip. Espelha _REVERSE_LOOKUP_SQL de
-- backend/app/services/fund_dossier_tier_b.py (COALESCE de 2 níveis, CIK casado
-- direto sem zero-pad, sem filer-name crosswalk — paridade exata). O LIMIT 100
-- é aplicado na leitura,
-- não aqui. O lado de exposições de fundo (fund_holdings/funds_v) permanece no
-- app DB, on-demand (catálogo dinâmico, não materializado). Refrescado por
-- matview_refresh (passo datalake).

CREATE MATERIALIZED VIEW IF NOT EXISTS holding_reverse_lookup_mv AS
WITH latest AS (
    SELECT upper(cusip) AS cusip, max(report_date) AS period
    FROM sec_13f_holdings
    GROUP BY upper(cusip)
)
SELECT
    upper(h.cusip) AS cusip,
    h.cik,
    COALESCE(mgr.firm_name, 'CIK ' || h.cik) AS manager_name,
    h.report_date AS period,
    h.report_date,
    h.issuer_name AS name,
    h.market_value AS value_usd,
    h.shares
FROM sec_13f_holdings h
JOIN latest l ON l.cusip = upper(h.cusip) AND l.period = h.report_date
LEFT JOIN LATERAL (
    SELECT m.firm_name
    FROM sec_managers m
    WHERE m.cik = h.cik AND m.firm_name IS NOT NULL
    ORDER BY m.aum_total DESC NULLS LAST
    LIMIT 1
) mgr ON true
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS holding_reverse_lookup_mv_pk
    ON holding_reverse_lookup_mv (cusip, cik);

REFRESH MATERIALIZED VIEW holding_reverse_lookup_mv;
