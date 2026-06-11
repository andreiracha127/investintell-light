"""Sync the screener universe from the SEC crosswalk + mother DB (F6.2).

Run from backend/:
    uv run python scripts/sync_universe.py            # real run (writes)
    uv run python scripts/sync_universe.py --dry-run  # counts only, no writes

Requires INVESTINTELL_DB_URL (read-only mother DB) in the environment/.env.
The mother-DB DSN is never printed.
"""

import argparse
import asyncio
import logging
import pathlib
import sys

# Ensure the backend root (parent of scripts/) is on sys.path so `app` is importable
# when running as a plain script rather than an installed package.
_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.sync.mother_db import run_sync  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print counts without writing anything (no seeds "
        "snapshot, no local DB writes).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    report = asyncio.run(run_sync(dry_run=args.dry_run))

    print()
    print("=== Universe sync report ===")
    for line in report.lines():
        print(line)


if __name__ == "__main__":
    main()
