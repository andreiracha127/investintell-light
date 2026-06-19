"""Parse N-CEN ADVISER.tsv across all local quarters and resolve the PRIMARY
investment adviser per fund series (newest-first wins). Analysis only — writes a
JSON map and prints coverage. No DB writes.

Usage:
    python -m scripts.ncen_adviser_analyze --ncen-root "F:/EDGAR FILES/ncen"
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _norm_crd(value: str | None) -> str | None:
    """Normalize a CRD number to match sec_managers.crd_number (no leading 0s)."""
    if not value:
        return None
    digits = "".join(c for c in value if c.isdigit())
    if not digits:
        return None
    return digits.lstrip("0") or "0"


def _quarter_dirs(root: Path) -> list[Path]:
    """N-CEN quarter dirs containing ADVISER.tsv, ordered NEWEST-first."""
    dirs = [d for d in root.iterdir() if d.is_dir() and "ncen" in d.name.lower()]
    # Names like 2025q3_ncen / 2024q4_ncen_0 sort lexically ~ chronologically.
    return sorted(dirs, key=lambda d: d.name, reverse=True)


def resolve_primary_advisers(root: Path) -> dict[str, dict[str, Any]]:
    """series_id -> {cik, adviser_name, crd, file_num} for the PRIMARY adviser.

    Only ADVISER_TYPE == 'Advisor' (not Subadvisor / Terminated). Newest quarter
    wins (first seen, since dirs are newest-first).
    """
    primary: dict[str, dict[str, Any]] = {}
    quarters = _quarter_dirs(root)
    print(f"quarters: {[d.name for d in quarters]}")
    for d in quarters:
        path = d / "ADVISER.tsv"
        if not path.exists():
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                if (r.get("ADVISER_TYPE") or "").strip() != "Advisor":
                    continue
                fund_id = r.get("FUND_ID") or ""
                parts = fund_id.split("_")
                if len(parts) < 3:
                    continue
                cik = parts[1].lstrip("0")
                series_id = parts[2]
                if not series_id.startswith("S"):
                    continue
                if series_id in primary:
                    continue  # newest-first already captured
                primary[series_id] = {
                    "cik": cik,
                    "adviser_name": (r.get("ADVISER_NAME") or "").strip() or None,
                    "crd": _norm_crd(r.get("CRD_NUM")),
                    "file_num": (r.get("FILE_NUM") or "").strip() or None,
                }
    return primary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ncen-root", required=True)
    ap.add_argument("--out", default="ncen_advisers.json")
    args = ap.parse_args()

    primary = resolve_primary_advisers(Path(args.ncen_root))
    with_crd = sum(1 for v in primary.values() if v["crd"])
    print(f"series with PRIMARY adviser: {len(primary)}")
    print(f"  ...with a CRD number:      {with_crd}")
    # A few samples
    for sid in list(primary)[:5]:
        print("  sample", sid, "->", primary[sid]["adviser_name"], primary[sid]["crd"])
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(primary, fh)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
