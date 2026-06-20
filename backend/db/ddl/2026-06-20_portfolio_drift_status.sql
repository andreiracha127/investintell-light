-- portfolio_drift_status: latest per-portfolio drift evaluation (Sprint C, Task 1).
--
-- Sprint C adds a drift monitor: a daily worker evaluates each portfolio's
-- position-drift / asset-class / overlap breaches and persists the latest
-- status here — one row per portfolio. Single-tenant (scoped by portfolio_id,
-- no owner column — same as the portfolio / constraint tables). The portfolio
-- id IS the primary key (1:1 with a portfolio) and FKs to portfolios.id with
-- ON DELETE CASCADE (deleting a portfolio drops its drift status). The PK
-- follows the portfolio-family int convention.
--
-- breaches jsonb holds:
--   {position_drifts: [...], class_breaches: [...], overlap_breaches: [...],
--    overlap_report_date: <date-string|null>}
--
-- Constraint names match the SQLAlchemy naming convention (app/models/base.py)
-- so the ORM model and this DDL stay in lockstep:
--   pk_portfolio_drift_status,
--   fk_portfolio_drift_status_portfolio_id_portfolios,
--   ck_portfolio_drift_status_worst_status.

CREATE TABLE IF NOT EXISTS portfolio_drift_status (
    portfolio_id integer     NOT NULL,
    evaluated_at timestamptz NOT NULL,
    worst_status text        NOT NULL,
    breaches     jsonb       NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_portfolio_drift_status PRIMARY KEY (portfolio_id),
    CONSTRAINT fk_portfolio_drift_status_portfolio_id_portfolios
        FOREIGN KEY (portfolio_id) REFERENCES portfolios (id) ON DELETE CASCADE,
    CONSTRAINT ck_portfolio_drift_status_worst_status
        CHECK (worst_status IN ('ok', 'maintenance', 'urgent'))
);
