-- Production scheduling for universe_constituents.sector enrichment.
--
-- The Stocks "Sector performance" chart reads universe_constituents.sector
-- (market_overview.fetch_overview_rows). That column is bridged, per ticker,
-- from the data-lake GICS maps — SEC CUSIP→GICS first, ISIN→GICS
-- (sec_isin_sector, the OpenFIGI/YFinance enrichment) as fallback.
--
-- This is the SAME logic as scripts/enrich_sectors.py (kept for manual /
-- portable runs), but scheduled INSIDE TimescaleDB Cloud as a native job so it
-- self-maintains with no extra service. Applied via the Tiger MCP / tsdbadmin
-- (Light migrations do not go through local alembic). Idempotent: re-running
-- replaces the procedure and re-creates a single daily job.

CREATE OR REPLACE PROCEDURE public.refresh_universe_sectors(job_id integer, config jsonb)
LANGUAGE plpgsql AS $proc$
BEGIN
  UPDATE universe_constituents u
  SET sector = src.sector
  FROM (
    WITH cusip AS (
      SELECT ticker, mode() WITHIN GROUP (ORDER BY gics_sector) AS sector
      FROM sec_cusip_ticker_map
      WHERE ticker IS NOT NULL AND gics_sector IS NOT NULL
      GROUP BY ticker
    ),
    isin AS (
      SELECT ticker, mode() WITHIN GROUP (ORDER BY gics_sector) AS sector
      FROM sec_isin_sector
      WHERE ticker IS NOT NULL AND gics_sector IS NOT NULL
      GROUP BY ticker
    )
    SELECT t.ticker, COALESCE(c.sector, i.sector) AS sector
    FROM (SELECT ticker FROM cusip UNION SELECT ticker FROM isin) t
    LEFT JOIN cusip c USING (ticker)
    LEFT JOIN isin i USING (ticker)
  ) src
  WHERE u.ticker = src.ticker AND src.sector IS NOT NULL AND u.sector IS DISTINCT FROM src.sector;
END;
$proc$;

-- Schedule daily at 06:00 UTC (idempotent: drop any prior job for this proc first).
SELECT delete_job(job_id)
FROM timescaledb_information.jobs
WHERE proc_name = 'refresh_universe_sectors';

SELECT add_job(
  'public.refresh_universe_sectors',
  schedule_interval => INTERVAL '24 hours',
  initial_start     => TIMESTAMPTZ '2026-06-20 06:00:00+00',
  fixed_schedule    => true
);
