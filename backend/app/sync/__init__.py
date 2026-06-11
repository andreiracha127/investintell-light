"""Batch synchronization with external sources (SEC crosswalk, mother DB).

Nothing in this package may be imported from any request path — sync and
backfill run exclusively as batch scripts (scripts/sync_universe.py,
scripts/backfill_universe_eod.py).
"""
