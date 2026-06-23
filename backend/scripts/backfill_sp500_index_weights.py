#!/usr/bin/env python3
"""Pipeline de pesos historicos do S&P 500 via holdings do IVV arquivados no Wayback.

A iShares removeu o acesso a holdings historicos do IVV (site novo so da a data
atual). Mas o endpoint .ajax legado foi arquivado pelo archive.org. Este script:
  1. lista as capturas (CDX), 1 por asOfDate (preferindo CSV > JSON);
  2. baixa o conteudo raw (web/<ts>id_/<orig>);
  3. parseia (CSV com header nomeado OU JSON aaData posicional);
  4. carrega em sp500_index_weights.

Modos:
  --inspect : lista distribuicao + despeja a estrutura crua de algumas epocas
  --load    : baixa tudo e carrega (DSN via env TIGER_DSN ou --dsn)
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request

CDX = ("http://web.archive.org/cdx/search/cdx?url=ishares.com/us/products/239726/"
       "ishares-core-sp-500-etf/1467271812596.ajax&matchType=prefix"
       "&filter=statuscode:200&output=json&collapse=digest&limit=6000")

CUSIP_RE = re.compile(r'^[0-9A-Z]{8}[0-9]$')
ISIN_RE = re.compile(r'^[A-Z]{2}[0-9A-Z]{9}[0-9]$')


def http_get(url, retries=4, timeout=90):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last


def list_captures():
    rows = json.loads(http_get(CDX).decode("utf-8"))[1:]
    caps = []
    for row in rows:
        ts, original = row[1], row[2]
        m = re.search(r'asOfDate=(\d{8})', original)
        ft = re.search(r'fileType=(\w+)', original)
        caps.append({"ts": ts, "original": original,
                     "as_of": m.group(1) if m else None,
                     "filetype": ft.group(1).lower() if ft else None})
    return caps


def pick_by_date(caps):
    rank = {"csv": 2, "json": 1}
    by = {}
    for c in caps:
        if not c["as_of"]:
            continue
        cur = by.get(c["as_of"])
        if cur is None or rank.get(c["filetype"], 0) > rank.get(cur["filetype"], 0):
            by[c["as_of"]] = c
    return dict(sorted(by.items()))


def fetch_text(cap):
    raw = http_get(f"http://web.archive.org/web/{cap['ts']}id_/{cap['original']}")
    return raw.decode("utf-8", errors="replace").lstrip("﻿").strip()


def num(v):
    if isinstance(v, dict):
        v = v.get("raw")
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def derive_cusip(cusip, isin):
    """Feed da iShares as vezes deixa CUSIP vazio mas traz ISIN; p/ ISIN US o
    CUSIP sao os chars 3..11 (US + 9 do cusip + check digit)."""
    if cusip:
        return cusip
    if isin and len(isin) == 12 and isin[:2] == "US":
        return isin[2:11]
    return None


def parse_csv(text):
    lines = text.splitlines()
    hi = next((i for i, l in enumerate(lines)
               if l.lower().lstrip('"').startswith("ticker")), None)
    if hi is None:
        return []
    out = []
    for r in csv.DictReader(lines[hi:]):
        tk = (r.get("Ticker") or "").strip()
        if not tk or tk == "-":
            continue
        isin = (r.get("ISIN") or "").strip() or None
        out.append({
            "ticker": tk, "name": (r.get("Name") or "").strip(),
            "sector": (r.get("Sector") or "").strip(),
            "asset_class": (r.get("Asset Class") or "").strip(),
            "weight": num(r.get("Weight (%)")),
            "market_value": num(r.get("Market Value")),
            "shares": num(r.get("Shares")),
            "cusip": derive_cusip((r.get("CUSIP") or "").strip() or None, isin),
            "isin": isin,
        })
    return out


def parse_json(text):
    obj = json.loads(text)
    data = obj.get("aaData") or obj.get("data") or []
    out = []
    for arr in data:
        if not isinstance(arr, list) or len(arr) < 6:
            continue
        cusip = isin = None
        for el in arr:
            if isinstance(el, str):
                s = el.strip()
                if cusip is None and CUSIP_RE.match(s):
                    cusip = s
                elif isin is None and ISIN_RE.match(s):
                    isin = s
        objs = [e for e in arr if isinstance(e, dict)]
        mv = next((num(e) for e in objs if "$" in str(e.get("display", ""))), None)
        wcands = [num(e) for e in objs
                  if "$" not in str(e.get("display", "")) and num(e) is not None
                  and 0 <= num(e) <= 15]
        weight = min(wcands) if wcands else None
        out.append({
            "ticker": str(arr[0]).strip(), "name": str(arr[1]).strip(),
            "sector": str(arr[2]).strip() if len(arr) > 2 else "",
            "asset_class": str(arr[3]).strip() if len(arr) > 3 else "",
            "weight": weight, "market_value": mv, "shares": None,
            "cusip": derive_cusip(cusip, isin), "isin": isin,
        })
    return out


def parse_any(text):
    return parse_json(text) if text[:1] == "{" else parse_csv(text)


def inspect():
    caps = list_captures()
    picked = pick_by_date(caps)
    fts = {}
    for c in picked.values():
        fts[c["filetype"]] = fts.get(c["filetype"], 0) + 1
    by_decade = {}
    for d in picked:
        by_decade[d[:3] + "x"] = by_decade.get(d[:3] + "x", 0) + 1
    print(f"capturas totais: {len(caps)}  |  datas distintas: {len(picked)}")
    print(f"por fileType (apos pick): {fts}")
    print(f"por periodo: {dict(sorted(by_decade.items()))}")
    print(f"range: {min(picked)} .. {max(picked)}")
    sample_dates = list(picked)[:: max(1, len(picked) // 6)][:6]
    for d in sample_dates:
        c = picked[d]
        try:
            text = fetch_text(c)
            rows = parse_any(text)
            wsum = sum(r["weight"] for r in rows if r["weight"]) if rows else 0
            print(f"\n--- {d} ft={c['filetype']} kind={'json' if text[:1]=='{' else 'csv'} "
                  f"rows={len(rows)} wsum={wsum:.1f}% ---")
            for r in rows[:3]:
                print(f"   {r['ticker']:6} cusip={r['cusip']} w={r['weight']} "
                      f"mv={r['market_value']} sec={r['sector'][:18]}")
        except Exception as e:  # noqa: BLE001
            print(f"\n--- {d} ERRO: {e}")


DDL = """
CREATE TABLE IF NOT EXISTS sp500_index_weights (
  as_of_date   date NOT NULL,
  ticker       text,
  cusip        text,
  name         text,
  sector       text,
  asset_class  text,
  weight       double precision,
  market_value double precision,
  shares       double precision,
  isin         text,
  source       text NOT NULL DEFAULT 'ishares-ivv-wayback',
  loaded_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sp500_iw_date_idx   ON sp500_index_weights (as_of_date);
CREATE INDEX IF NOT EXISTS sp500_iw_cusip_idx  ON sp500_index_weights (cusip);
CREATE INDEX IF NOT EXISTS sp500_iw_ticker_idx ON sp500_index_weights (ticker);
"""


def group_by_date(caps):
    from collections import defaultdict
    by = defaultdict(list)
    for c in caps:
        if c["as_of"]:
            by[c["as_of"]].append(c)
    for d in by:  # CSV (header nomeado) antes de JSON
        by[d].sort(key=lambda c: 0 if c["filetype"] == "csv" else 1)
    return dict(sorted(by.items()))


def is_holding(r):
    """Constituinte do indice: tem peso e ticker, e nao e caixa/derivativo.
    cusip pode ser None (acoes de ISIN estrangeiro listadas nos EUA) - mantemos
    no benchmark para a soma de pesos fechar ~100%, mesmo sem casar por cusip."""
    if r["weight"] is None or not r["ticker"] or r["ticker"] in ("-",):
        return False
    ac = (r["asset_class"] or "").lower()
    return "cash" not in ac and "money market" not in ac


def best_rows_for_date(clist, max_try=6):
    """Tenta as capturas da data; usa a com mais linhas validas (algumas capturas
    do Wayback sao HTML ou aaData vazio)."""
    best = []
    for c in clist[:max_try]:
        try:
            rows = [r for r in parse_any(fetch_text(c)) if is_holding(r)]
        except Exception:  # noqa: BLE001
            rows = []
        if len(rows) > len(best):
            best = rows
        if len(best) >= 450:
            break
    return best


def load(dsn):
    import psycopg2
    from psycopg2.extras import execute_values
    groups = group_by_date(list_captures())
    print(f"datas a baixar: {len(groups)}")
    all_rows = []
    failures = []
    for i, (d, clist) in enumerate(groups.items(), 1):
        eq = best_rows_for_date(clist)
        if len(eq) < 50:
            failures.append((d, f"{len(eq)} linhas (capturas vazias/HTML)"))
            continue
        iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        for r in eq:
            all_rows.append((iso, r["ticker"], r["cusip"], r["name"], r["sector"],
                             r["asset_class"], r["weight"], r["market_value"],
                             r["shares"], r["isin"]))
        if i % 20 == 0:
            print(f"  {i}/{len(groups)} ... {d} ({len(eq)} holdings)")
    print(f"linhas coletadas: {len(all_rows):,}  | falhas: {len(failures)}")
    for d, why in failures:
        print(f"   FALHA {d}: {why}")

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute(DDL)
        cur.execute("TRUNCATE sp500_index_weights;")
        execute_values(
            cur,
            "INSERT INTO sp500_index_weights (as_of_date,ticker,cusip,name,sector,"
            "asset_class,weight,market_value,shares,isin) VALUES %s",
            all_rows, page_size=2000)
        conn.commit()
        cur.execute("SELECT count(*), count(DISTINCT as_of_date), "
                    "min(as_of_date), max(as_of_date) FROM sp500_index_weights;")
        print("LOADED rows=%s dates=%s range=%s..%s" % cur.fetchone())
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--dsn", default=os.environ.get("TIGER_DSN"))
    args = ap.parse_args()
    if args.inspect:
        inspect()
    if args.load:
        if not args.dsn:
            sys.exit("--load exige --dsn ou env TIGER_DSN")
        load(args.dsn)
    if not (args.inspect or args.load):
        inspect()


if __name__ == "__main__":
    main()
