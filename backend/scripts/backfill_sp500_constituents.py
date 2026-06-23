#!/usr/bin/env python3
"""Cria e carrega sp500_constituents (membership historico do S&P 500) no Tiger.

Fonte: github.com/fja05680/sp500 -> sp500_ticker_start_end.csv (licenca MIT).
Formato de intervalos: ticker, start_date, end_date (end vazio = ainda no indice;
um ticker pode ter varios intervalos). Consulta point-in-time:
  ticker no indice em D  <=>  start_date <= D AND (end_date IS NULL OR end_date >= D)

Idempotente (TRUNCATE+reinsert). DSN via env TIGER_DSN ou --dsn. Tambem mede a
taxa de match ticker->cusip contra sec_cusip_ticker_map (ponte p/ holdings).
"""
import argparse
import csv
import io
import os
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"

DDL = """
CREATE TABLE IF NOT EXISTS sp500_constituents (
  ticker     text NOT NULL,
  start_date date NOT NULL,
  end_date   date,
  source     text NOT NULL DEFAULT 'fja05680/sp500',
  loaded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sp500_constituents_ticker_idx ON sp500_constituents (ticker);
CREATE INDEX IF NOT EXISTS sp500_constituents_range_idx  ON sp500_constituents (start_date, end_date);
"""

MATCH_SQL = """
WITH t AS (SELECT DISTINCT ticker FROM sp500_constituents),
m AS (
  SELECT t.ticker,
    EXISTS (SELECT 1 FROM sec_cusip_ticker_map x WHERE x.ticker = t.ticker)                  AS exact,
    EXISTS (SELECT 1 FROM sec_cusip_ticker_map x WHERE x.ticker = replace(t.ticker,'.','/')) AS slash,
    EXISTS (SELECT 1 FROM sec_cusip_ticker_map x WHERE x.ticker = replace(t.ticker,'.','-')) AS dash,
    EXISTS (SELECT 1 FROM sec_cusip_ticker_map x WHERE x.ticker = replace(t.ticker,'.',''))  AS glued
  FROM t)
SELECT count(*)                                                       AS total,
       count(*) FILTER (WHERE exact)                                  AS exact_match,
       count(*) FILTER (WHERE exact OR slash OR dash OR glued)        AS any_match
FROM m;
"""


def fetch_rows():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8")
    rows = []
    for rec in csv.DictReader(io.StringIO(text)):
        t = (rec.get("ticker") or "").strip()
        s = (rec.get("start_date") or "").strip()
        e = (rec.get("end_date") or "").strip()
        if t and s:
            rows.append((t, s, e or None))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("TIGER_DSN"))
    args = ap.parse_args()
    if not args.dsn:
        sys.exit("faltou --dsn ou env TIGER_DSN")

    rows = fetch_rows()
    print(f"CSV: {len(rows)} intervalos")

    import psycopg2
    from psycopg2.extras import execute_values
    conn = psycopg2.connect(args.dsn)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute(DDL)
        cur.execute("TRUNCATE sp500_constituents;")
        execute_values(
            cur,
            "INSERT INTO sp500_constituents (ticker, start_date, end_date) VALUES %s",
            rows, template="(%s,%s,%s)", page_size=1000,
        )
        conn.commit()
        cur.execute(
            "SELECT count(*), count(DISTINCT ticker), "
            "count(*) FILTER (WHERE end_date IS NULL) FROM sp500_constituents;")
        n, tk, active = cur.fetchone()
        print(f"carregado: {n} intervalos, {tk} tickers, {active} ativos hoje")
        cur.execute(MATCH_SQL)
        total, exact_m, any_m = cur.fetchone()
        print(f"match ticker->cusip (sec_cusip_ticker_map): "
              f"exato {exact_m}/{total}, com normalizacao {any_m}/{total}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
