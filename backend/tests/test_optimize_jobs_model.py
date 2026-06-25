from app.models.optimize_jobs import OptimizeJob


def test_optimize_jobs_columns_and_pk():
    assert OptimizeJob.__tablename__ == "optimize_jobs"
    cols = set(OptimizeJob.__table__.columns.keys())
    assert {
        "id", "portfolio_id", "kind", "params_hash",
        "status", "result", "error", "created_at", "updated_at",
    } <= cols
    assert "id" in OptimizeJob.__table__.primary_key.columns.keys()


def test_status_check_constraint_present():
    cks = [
        c for c in OptimizeJob.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    ]
    assert any("status" in (c.name or "") for c in cks)
