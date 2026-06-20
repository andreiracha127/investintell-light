from pathlib import Path

DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-13_dynamic_catalog.sql"
)


def test_stage_labels_sql_prefers_manual_overrides() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")
    stage_start = sql.index("-- STAGE_LABELS_SQL")
    stage_end = sql.index("-- merge_risk_duplicates", stage_start)
    stage_sql = sql[stage_start:stage_end]

    override_order = "(classification_source = 'manual_override') DESC"
    latest_order = "classified_at DESC"

    assert override_order in stage_sql
    assert stage_sql.index(override_order) < stage_sql.index(latest_order)
