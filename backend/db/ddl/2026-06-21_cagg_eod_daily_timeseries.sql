-- DB-first stock timeseries: every visible range should read one persisted
-- daily CAGG instead of choosing daily/weekly/monthly sources by request range.

CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_daily
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 day', date) AS bucket,
       first(open,  date) AS open,
       max(high)          AS high,
       min(low)           AS low,
       last(close, date)  AS close,
       sum(volume)        AS volume,
       first(adj_open,  date) AS adj_open,
       max(adj_high)          AS adj_high,
       min(adj_low)           AS adj_low,
       last(adj_close, date)  AS adj_close,
       sum(adj_volume)        AS adj_volume
FROM eod_prices
GROUP BY ticker, time_bucket('1 day', date)
WITH NO DATA;

CREATE INDEX IF NOT EXISTS cagg_eod_daily_ticker_bucket_idx
  ON cagg_eod_daily (ticker, bucket);

CALL refresh_continuous_aggregate('cagg_eod_daily', NULL, NULL);

SELECT add_continuous_aggregate_policy('cagg_eod_daily',
  start_offset => INTERVAL '90 days',
  end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day',
  if_not_exists => true);
