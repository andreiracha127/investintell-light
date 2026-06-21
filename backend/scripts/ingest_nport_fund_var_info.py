"""Ingest SEC N-PORT designated benchmark rows from FUND_VAR_INFO.tsv.

The SEC feed stores the benchmark declaration in ``FUND_VAR_INFO.tsv`` keyed by
ACCESSION_NUMBER. To make it useful for the Light fund dossier we join it to:

- ``FUND_REPORTED_INFO.tsv`` for SERIES_ID / SERIES_NAME
- ``SUBMISSION.tsv`` for filing/report dates

Run from backend/:
    uv run python scripts/ingest_nport_fund_var_info.py \
        --nport-root "E:/Edgard/2026q1_nport" --dry-run

    $env:DATALAKE_DB_URL = "postgresql://..."
    uv run python scripts/ingest_nport_fund_var_info.py \
        --nport-root "E:/Edgard/2026q1_nport"
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DDL = """
CREATE TABLE IF NOT EXISTS sec_nport_fund_var_info (
    accession_number text PRIMARY KEY,
    series_id text NOT NULL,
    series_name text,
    report_date date,
    filing_date date,
    designated_index_name text,
    designated_index_identifier text,
    designated_index_quality text NOT NULL DEFAULT 'unknown',
    source_file text NOT NULL DEFAULT 'FUND_VAR_INFO.tsv',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT sec_nport_fund_var_info_quality_check
        CHECK (
            designated_index_quality IN (
                'declared_index',
                'missing',
                'self_reference',
                'unknown'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_sec_nport_fund_var_info_series_report
    ON sec_nport_fund_var_info (
        series_id,
        report_date DESC NULLS LAST,
        filing_date DESC NULLS LAST
    );

CREATE INDEX IF NOT EXISTS idx_sec_nport_fund_var_info_identifier
    ON sec_nport_fund_var_info (designated_index_identifier)
    WHERE designated_index_identifier IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sec_nport_fund_var_info_quality
    ON sec_nport_fund_var_info (designated_index_quality, series_id);
"""

_UPSERT = """
INSERT INTO sec_nport_fund_var_info (
    accession_number,
    series_id,
    series_name,
    report_date,
    filing_date,
    designated_index_name,
    designated_index_identifier,
    designated_index_quality,
    source_file,
    updated_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
ON CONFLICT (accession_number) DO UPDATE SET
    series_id = EXCLUDED.series_id,
    series_name = EXCLUDED.series_name,
    report_date = EXCLUDED.report_date,
    filing_date = EXCLUDED.filing_date,
    designated_index_name = EXCLUDED.designated_index_name,
    designated_index_identifier = EXCLUDED.designated_index_identifier,
    designated_index_quality = EXCLUDED.designated_index_quality,
    source_file = EXCLUDED.source_file,
    updated_at = now()
"""

_QUALITY_VALUES = {"declared_index", "missing", "self_reference", "unknown"}
_NA_VALUES = {"", "N/A", "NA", "N.A.", "NONE", "NULL", "NOT APPLICABLE"}


@dataclass(frozen=True)
class NportVarRow:
    accession_number: str
    series_id: str
    series_name: str | None
    report_date: date | None
    filing_date: date | None
    designated_index_name: str | None
    designated_index_identifier: str | None
    designated_index_quality: str
    source_file: str

    def as_db_tuple(self) -> tuple[object, ...]:
        return (
            self.accession_number,
            self.series_id,
            self.series_name,
            self.report_date,
            self.filing_date,
            self.designated_index_name,
            self.designated_index_identifier,
            self.designated_index_quality,
            self.source_file,
        )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _is_na(value: str | None) -> bool:
    return value is None or value.strip().upper() in _NA_VALUES


def _compact(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _parse_sec_date(value: str | None) -> date | None:
    clean = _clean(value)
    if clean is None:
        return None
    return datetime.strptime(clean.title(), "%d-%b-%Y").date()


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _quality(
    designated_index_name: str | None,
    designated_index_identifier: str | None,
    series_name: str | None,
) -> str:
    if _is_na(designated_index_name) and _is_na(designated_index_identifier):
        return "missing"

    name = designated_index_name or ""
    name_compact = _compact(name)
    series_compact = _compact(series_name)
    lowered = name.casefold()
    self_reference_terms = (
        "securities portfolio",
        "security portfolio",
        "fund securities portfolio",
        "designated reference portfolio",
        "designated reference portfolio is the fund",
    )

    if any(term in lowered for term in self_reference_terms):
        return "self_reference"
    if series_compact and name_compact == series_compact:
        return "self_reference"
    return "declared_index"


def build_rows(nport_root: Path) -> tuple[list[NportVarRow], Counter[str], int]:
    var_path = nport_root / "FUND_VAR_INFO.tsv"
    info_path = nport_root / "FUND_REPORTED_INFO.tsv"
    submission_path = nport_root / "SUBMISSION.tsv"

    reported_info = {
        row["ACCESSION_NUMBER"]: row
        for row in _read_tsv(info_path)
        if _clean(row.get("ACCESSION_NUMBER"))
    }
    submissions = {
        row["ACCESSION_NUMBER"]: row
        for row in _read_tsv(submission_path)
        if _clean(row.get("ACCESSION_NUMBER"))
    }

    rows: list[NportVarRow] = []
    skipped_missing_series = 0
    for row in _read_tsv(var_path):
        accession = _clean(row.get("ACCESSION_NUMBER"))
        if accession is None:
            continue
        info = reported_info.get(accession)
        series_id = _clean(info.get("SERIES_ID") if info else None)
        if series_id is None:
            skipped_missing_series += 1
            continue

        submission = submissions.get(accession, {})
        series_name = _clean(info.get("SERIES_NAME") if info else None)
        benchmark_name = _clean(row.get("DESIGNATED_INDEX_NAME"))
        benchmark_identifier = _clean(row.get("DESIGNATED_INDEX_IDENTIFIER"))
        quality = _quality(benchmark_name, benchmark_identifier, series_name)
        if quality not in _QUALITY_VALUES:
            quality = "unknown"

        rows.append(
            NportVarRow(
                accession_number=accession,
                series_id=series_id,
                series_name=series_name,
                report_date=_parse_sec_date(submission.get("REPORT_DATE")),
                filing_date=_parse_sec_date(submission.get("FILING_DATE")),
                designated_index_name=benchmark_name,
                designated_index_identifier=benchmark_identifier,
                designated_index_quality=quality,
                source_file=str(var_path.name),
            )
        )

    return rows, Counter(row.designated_index_quality for row in rows), skipped_missing_series


def _normalize_asyncpg_dsn(dsn: str) -> tuple[str, str | None]:
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = "postgresql://" + dsn.removeprefix("postgresql+asyncpg://")
    if dsn.startswith("postgresql+psycopg://"):
        dsn = "postgresql://" + dsn.removeprefix("postgresql+psycopg://")

    parts = urlsplit(dsn)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    ssl_required = False
    kept_pairs: list[tuple[str, str]] = []
    for key, value in query_pairs:
        if key in {"sslmode", "ssl"}:
            ssl_required = value in {"require", "verify-ca", "verify-full"}
            continue
        kept_pairs.append((key, value))
    normalized = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query and urlencode(kept_pairs), "")
    )
    return normalized, "require" if ssl_required else None


async def ingest_rows(rows: list[NportVarRow], dsn: str, chunk_size: int) -> None:
    import asyncpg

    normalized_dsn, ssl_mode = _normalize_asyncpg_dsn(dsn)
    connect_kwargs: dict[str, object] = {"dsn": normalized_dsn}
    if ssl_mode is not None:
        connect_kwargs["ssl"] = ssl_mode

    conn = await asyncpg.connect(**connect_kwargs)
    try:
        await conn.execute(_DDL)
        for index in range(0, len(rows), chunk_size):
            chunk = [row.as_db_tuple() for row in rows[index : index + chunk_size]]
            await conn.executemany(_UPSERT, chunk)
        total = await conn.fetchval("SELECT count(*) FROM sec_nport_fund_var_info")
        usable = await conn.fetchval(
            """
            SELECT count(*)
            FROM sec_nport_fund_var_info
            WHERE designated_index_quality = 'declared_index'
            """
        )
        print(f"sec_nport_fund_var_info rows: {total} (declared_index: {usable})")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nport-root", required=True, type=Path)
    parser.add_argument("--dsn-env", default="DATALAKE_DB_URL")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=1000)
    args = parser.parse_args()

    rows, quality_counts, skipped_missing_series = build_rows(args.nport_root)
    print(f"resolved {len(rows)} FUND_VAR_INFO rows")
    print(f"quality counts: {dict(sorted(quality_counts.items()))}")
    if skipped_missing_series:
        print(f"skipped rows without SERIES_ID: {skipped_missing_series}")

    if args.dry_run:
        return

    dsn = os.environ.get(args.dsn_env, "")
    if not dsn:
        raise SystemExit(f"{args.dsn_env} env var required (or use --dry-run)")
    asyncio.run(ingest_rows(rows, dsn, args.chunk_size))


if __name__ == "__main__":
    main()
