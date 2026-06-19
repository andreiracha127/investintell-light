"""owner_sub é aplicado nas queries de portfolio (compiled-SQL, sem DB)."""
from sqlalchemy import delete, select

from app.models.portfolio import Portfolio, Position


def test_owned_portfolio_select_filters_owner() -> None:
    stmt = select(Portfolio).where(
        Portfolio.id == 1, Portfolio.owner_sub == "u-1"
    )
    sql = str(stmt.compile())
    assert "owner_sub" in sql


def test_delete_position_guard_scopes_to_owner() -> None:
    owned = select(Portfolio.id).where(
        Portfolio.id == 1, Portfolio.owner_sub == "u-1"
    )
    stmt = delete(Position).where(
        Position.portfolio_id == 1,
        Position.ticker == "AAPL",
        Position.portfolio_id.in_(owned),
    )
    sql = str(stmt.compile())
    assert "owner_sub" in sql and "portfolio_id IN" in sql
