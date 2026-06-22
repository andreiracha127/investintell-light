"""Measure Group C fn_* latency on long windows before removing the pandas path.

Run against a DB that has the functions applied (Task 1, Step 5) and a populated
cagg_eod_daily / cagg_nav_daily. Reads DATABASE_URL; self-skips if unset.

Usage:
    DATABASE_URL=... python -m backend.scripts.group_c_function_perf SPY <fund_uuid>

Rollout sequence (spec §12) for flipping use_series_db_first:
    1. Apply backend/db/ddl/2026-06-21_group_c_functions.sql to the main DB.
    2. Run this perf gate; confirm each fn_* is well under the request budget on
       5Y/MAX (target < ~150 ms on MAX for a single entity).
    3. Set use_series_db_first=True in staging; diff each endpoint's payload
       (flag on vs off) on a representative entity sample within the documented
       tolerances (~1e-10 rolling/drawdown/growth, ~1e-8 VaR/CVaR, ~1e-6 hist).
    4. Flip the default in production.
    5. In a follow-up branch remove the legacy pandas series math
       (_rolling_sharpe, rolling_volatility/rolling_beta/rolling_correlation call
       sites, return_histogram/historical_var/historical_cvar call sites on the
       migrated paths, _max_drawdown_series series emission) once the flag is
       permanently on.
"""
from __future__ import annotations

import os
import sys
import time

import psycopg


def _timed(cur, label: str, sql: str, params: tuple) -> None:
    t0 = time.perf_counter()
    cur.execute(sql, params)
    cur.fetchall()
    ms = (time.perf_counter() - t0) * 1000.0
    print(f"{label:32s} {ms:8.1f} ms")


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL unset — skipping perf measurement.")
        return 0
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    instrument = sys.argv[2] if len(sys.argv) > 2 else None
    start_5y, end = "2021-06-01", "2026-06-18"
    start_max = "1990-01-01"

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for label, start in (("5Y", start_5y), ("MAX", start_max)):
            _timed(cur, f"rolling_metrics({label}) {ticker}",
                   "SELECT * FROM fn_rolling_metrics(%s, NULL, 252, %s, %s)",
                   (ticker, start, end))
            _timed(cur, f"rolling_beta_corr({label})",
                   "SELECT * FROM fn_rolling_beta_corr(%s, 'SPY', 252, %s, %s)",
                   (ticker, start, end))
            _timed(cur, f"drawdown({label})",
                   "SELECT * FROM fn_drawdown(%s, NULL, %s, %s)",
                   (ticker, start, end))
            _timed(cur, f"histogram({label})",
                   "SELECT * FROM fn_histogram(%s, NULL, 20, %s, %s)",
                   (ticker, start, end))
            _timed(cur, f"var_cvar({label})",
                   "SELECT * FROM fn_var_cvar(%s, NULL, 0.95, %s, %s)",
                   (ticker, start, end))
            if instrument:
                _timed(cur, f"drawdown(fund {label})",
                       "SELECT * FROM fn_drawdown(NULL, %s, %s, %s)",
                       (instrument, start, end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
