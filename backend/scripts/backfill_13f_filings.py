#!/usr/bin/env python3
"""Backfill sec_13f_filings + sec_13f_other_managers a partir dos bulks 13F da SEC.

Os arquivos INFOTABLE (holdings) ja alimentam sec_13f_holdings; este script
adiciona os metadados de *filing* que faltavam (report_type, contagem/lista de
"other managers" e manager_family_id).

manager_family_id: definido como o CIK do filing manager (decisao do dono). O grafo
filer<->other-managers (para um eventual agrupamento de familias por entity
resolution) fica preservado cru em sec_13f_other_managers. NB: connected-components
sobre esse grafo degenera (a relacao other-manager no 13F e dominada por
sub-advisory/wrap/custodia), por isso nao e usado para a familia.

Fase LOCAL (default): parseia os 53 trimestres e grava CSVs.
Fase LOAD (--load --dsn ...): cria as tabelas e carrega via COPY (TRUNCATE+COPY,
idempotente). Os 5 arquivos usados (SUBMISSION/COVERPAGE/SUMMARYPAGE/OTHERMANAGER/
OTHERMANAGER2) tem cabecalho estavel de 2013q2 ate hoje; o parser mapeia por NOME
de coluna, nao por posicao.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from collections import Counter
from datetime import datetime

csv.field_size_limit(1 << 24)

BASE = r"E:\Edgard\13-F"

FILINGS_COLS = [
    "accession_number", "cik", "report_date", "filing_date", "submission_type",
    "report_type", "is_amendment", "amendment_no", "amendment_type",
    "filing_manager_name", "form13f_filenumber", "crd_number", "sec_filenumber",
    "other_managers_count", "table_entry_total", "table_value_total",
    "is_confidential_omitted", "manager_family_id", "source_quarter",
]
OM_COLS = [
    "accession_number", "source", "seq", "cik",
    "form13f_filenumber", "crd_number", "sec_filenumber", "name",
]


def read_tsv(path):
    """Itera (col_index_map, row) mapeando por NOME de coluna (robusto a schema)."""
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = next(reader, None)
        if not header:
            return
        idx = {name.strip(): i for i, name in enumerate(header)}
        for row in reader:
            if row:
                yield idx, row


def g(idx, row, col):
    i = idx.get(col)
    return row[i].strip() if (i is not None and i < len(row)) else ""


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def norm_cik(s):
    s = (s or "").strip()
    if not s.isdigit() or int(s) == 0:
        return None  # "0"/"0000000000" e placeholder de "sem CIK", nao um CIK real
    return s.zfill(10)


def to_int(s):
    s = (s or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def to_bool(s):
    return (s or "").strip().upper() in ("Y", "YES", "TRUE", "1")


def parse_all(base):
    quarters = sorted(glob.glob(os.path.join(base, "*_form13f")))
    if not quarters:
        sys.exit(f"Nenhuma pasta *_form13f em {base}")

    filings = {}
    other_mgrs = []

    for qdir in quarters:
        qname = os.path.basename(qdir)
        subs = {}
        p = os.path.join(qdir, "SUBMISSION.tsv")
        if os.path.exists(p):
            for idx, row in read_tsv(p):
                acc = g(idx, row, "ACCESSION_NUMBER")
                subs[acc] = {
                    "cik": norm_cik(g(idx, row, "CIK")),
                    "filing_date": parse_date(g(idx, row, "FILING_DATE")),
                    "submission_type": g(idx, row, "SUBMISSIONTYPE"),
                    "report_date": parse_date(g(idx, row, "PERIODOFREPORT")),
                }
        cps = {}
        p = os.path.join(qdir, "COVERPAGE.tsv")
        if os.path.exists(p):
            for idx, row in read_tsv(p):
                acc = g(idx, row, "ACCESSION_NUMBER")
                cps[acc] = {
                    "report_type": g(idx, row, "REPORTTYPE"),
                    "is_amendment": to_bool(g(idx, row, "ISAMENDMENT")),
                    "amendment_no": to_int(g(idx, row, "AMENDMENTNO")),
                    "amendment_type": g(idx, row, "AMENDMENTTYPE"),
                    "filing_manager_name": g(idx, row, "FILINGMANAGER_NAME"),
                    "form13f_filenumber": g(idx, row, "FORM13FFILENUMBER"),
                    "crd_number": g(idx, row, "CRDNUMBER"),
                    "sec_filenumber": g(idx, row, "SECFILENUMBER"),
                }
        sps = {}
        p = os.path.join(qdir, "SUMMARYPAGE.tsv")
        if os.path.exists(p):
            for idx, row in read_tsv(p):
                acc = g(idx, row, "ACCESSION_NUMBER")
                sps[acc] = {
                    "other_managers_count": to_int(g(idx, row, "OTHERINCLUDEDMANAGERSCOUNT")),
                    "table_entry_total": to_int(g(idx, row, "TABLEENTRYTOTAL")),
                    "table_value_total": to_int(g(idx, row, "TABLEVALUETOTAL")),
                    "is_confidential_omitted": to_bool(g(idx, row, "ISCONFIDENTIALOMITTED")),
                }
        for acc, s in subs.items():
            rec = {"accession_number": acc, "source_quarter": qname}
            rec.update(s)
            rec.update(cps.get(acc, {}))
            rec.update(sps.get(acc, {}))
            cik = rec.get("cik")
            rec["manager_family_id"] = int(cik) if cik else None
            filings[acc] = rec

        for fn, seqcol, src in (
            ("OTHERMANAGER.tsv", "OTHERMANAGER_SK", "OTHERMANAGER"),
            ("OTHERMANAGER2.tsv", "SEQUENCENUMBER", "OTHERMANAGER2"),
        ):
            p = os.path.join(qdir, fn)
            if not os.path.exists(p):
                continue
            for idx, row in read_tsv(p):
                other_mgrs.append({
                    "accession_number": g(idx, row, "ACCESSION_NUMBER"),
                    "source": src, "seq": g(idx, row, seqcol),
                    "cik": norm_cik(g(idx, row, "CIK")),
                    "form13f_filenumber": g(idx, row, "FORM13FFILENUMBER"),
                    "crd_number": g(idx, row, "CRDNUMBER"),
                    "sec_filenumber": g(idx, row, "SECFILENUMBER"),
                    "name": g(idx, row, "NAME"),
                })

    return quarters, filings, other_mgrs


def write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])


def print_stats(quarters, filings, other_mgrs):
    rt = Counter(f.get("report_type") or "(vazio)" for f in filings.values())
    st = Counter(f.get("submission_type") or "(vazio)" for f in filings.values())
    distinct_filers = {f["cik"] for f in filings.values() if f.get("cik")}
    with_om = sum(1 for f in filings.values() if (f.get("other_managers_count") or 0) > 0)
    print(f"trimestres            : {len(quarters)}")
    print(f"filings (accessions)  : {len(filings):,}")
    print(f"other-manager rows    : {len(other_mgrs):,}")
    print(f"filings c/ other mgrs : {with_om:,}")
    print(f"filers distintos (CIK): {len(distinct_filers):,}  (= nro de manager_family_id)")
    print("report_type:")
    for k, v in rt.most_common():
        print(f"  {v:>8,}  {k}")
    print("submission_type:")
    for k, v in st.most_common(12):
        print(f"  {v:>8,}  {k}")


DDL = """
CREATE TABLE IF NOT EXISTS sec_13f_filings (
  accession_number        text PRIMARY KEY,
  cik                     text,
  report_date             date,
  filing_date             date,
  submission_type         text,
  report_type             text,
  is_amendment            boolean,
  amendment_no            integer,
  amendment_type          text,
  filing_manager_name     text,
  form13f_filenumber      text,
  crd_number              text,
  sec_filenumber          text,
  other_managers_count    integer,
  table_entry_total       bigint,
  table_value_total       bigint,
  is_confidential_omitted boolean,
  manager_family_id       bigint,
  source_quarter          text,
  created_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sec_13f_filings_cik_idx        ON sec_13f_filings (cik);
CREATE INDEX IF NOT EXISTS sec_13f_filings_family_idx     ON sec_13f_filings (manager_family_id);
CREATE INDEX IF NOT EXISTS sec_13f_filings_reportdate_idx ON sec_13f_filings (report_date);

CREATE TABLE IF NOT EXISTS sec_13f_other_managers (
  accession_number   text NOT NULL,
  source             text NOT NULL,
  seq                text,
  cik                text,
  form13f_filenumber text,
  crd_number         text,
  sec_filenumber     text,
  name               text
);
CREATE INDEX IF NOT EXISTS sec_13f_other_managers_acc_idx
  ON sec_13f_other_managers (accession_number);
CREATE INDEX IF NOT EXISTS sec_13f_other_managers_cik_idx ON sec_13f_other_managers (cik);
"""


def load(dsn, out):
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute(DDL)
        cur.execute("TRUNCATE sec_13f_filings;")
        with open(os.path.join(out, "filings.csv"), encoding="utf-8") as f:
            cur.copy_expert(
                "COPY sec_13f_filings ({}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')".format(",".join(FILINGS_COLS)), f)  # noqa: E501
        cur.execute("TRUNCATE sec_13f_other_managers;")
        with open(os.path.join(out, "other_managers.csv"), encoding="utf-8") as f:
            cur.copy_expert(
                "COPY sec_13f_other_managers ({}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')".format(",".join(OM_COLS)), f)  # noqa: E501
        conn.commit()
        cur.execute("SELECT count(*) FROM sec_13f_filings;")
        nf = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sec_13f_other_managers;")
        no = cur.fetchone()[0]
        print(f"LOADED sec_13f_filings={nf:,}  sec_13f_other_managers={no:,}")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "13f_out"))
    ap.add_argument("--load", action="store_true", help="cria tabelas e carrega via COPY")
    ap.add_argument("--dsn", default=os.environ.get("TIGER_DSN"))
    args = ap.parse_args()

    quarters, filings, other_mgrs = parse_all(args.base)
    os.makedirs(args.out, exist_ok=True)
    write_csv(os.path.join(args.out, "filings.csv"), FILINGS_COLS, filings.values())
    write_csv(os.path.join(args.out, "other_managers.csv"), OM_COLS, other_mgrs)
    print(f"CSVs em {args.out}")
    print_stats(quarters, filings, other_mgrs)

    if args.load:
        if not args.dsn:
            sys.exit("--load exige --dsn ou env TIGER_DSN")
        load(args.dsn, args.out)


if __name__ == "__main__":
    main()
