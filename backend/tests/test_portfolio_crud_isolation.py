"""Real isolation tests for portfolio_crud — exercises owner-scoped functions
against an in-memory SQLite database so a regression that drops an owner filter
will turn these tests RED.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.portfolio import Portfolio, Position
from app.services import portfolio_crud
from app.services.portfolio_crud import DuplicatePortfolioNameError
from app.schemas.portfolios import PortfolioCreate, PositionCreate


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Portfolio.__table__, Position.__table__]
            )
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _portfolio(name: str, *, positions: list[PositionCreate] | None = None) -> PortfolioCreate:
    return PortfolioCreate(name=name, cash=0.0, positions=positions or [])


def _with_aapl() -> list[PositionCreate]:
    return [PositionCreate(ticker="AAPL", quantity=1.0, acq_price=10.0)]


# ---------------------------------------------------------------------------
# 1. get_portfolio: owner-scoped read
# ---------------------------------------------------------------------------

async def test_get_portfolio_owner_can_read(session):
    p = await portfolio_crud.create_portfolio(session, _portfolio("Alpha"), "u-A", None)
    result = await portfolio_crud.get_portfolio(session, p.id, "u-A")
    assert result is not None
    assert result.id == p.id


async def test_get_portfolio_other_owner_gets_none(session):
    p = await portfolio_crud.create_portfolio(session, _portfolio("Alpha"), "u-A", None)
    result = await portfolio_crud.get_portfolio(session, p.id, "u-B")
    assert result is None


# ---------------------------------------------------------------------------
# 2. list_portfolios: returns only the caller's rows
# ---------------------------------------------------------------------------

async def test_list_portfolios_scoped_to_owner(session):
    await portfolio_crud.create_portfolio(session, _portfolio("A-Port"), "u-A", None)
    await portfolio_crud.create_portfolio(session, _portfolio("B-Port"), "u-B", None)

    rows_a = await portfolio_crud.list_portfolios(session, "u-A")
    rows_b = await portfolio_crud.list_portfolios(session, "u-B")

    assert len(rows_a) == 1
    assert rows_a[0].name == "A-Port"
    assert len(rows_b) == 1
    assert rows_b[0].name == "B-Port"


# ---------------------------------------------------------------------------
# 3. portfolio_exists: True for owner, False for other
# ---------------------------------------------------------------------------

async def test_portfolio_exists_owner(session):
    p = await portfolio_crud.create_portfolio(session, _portfolio("Exists"), "u-A", None)
    assert await portfolio_crud.portfolio_exists(session, p.id, "u-A") is True
    assert await portfolio_crud.portfolio_exists(session, p.id, "u-B") is False


# ---------------------------------------------------------------------------
# 4. delete_portfolio: cross-owner delete is denied; owner delete succeeds
# ---------------------------------------------------------------------------

async def test_delete_portfolio_cross_owner_denied(session):
    p = await portfolio_crud.create_portfolio(session, _portfolio("Guarded"), "u-A", None)

    # u-B cannot delete u-A's portfolio
    deleted = await portfolio_crud.delete_portfolio(session, p.id, "u-B")
    assert deleted is False

    # Row still exists for u-A
    still_there = await portfolio_crud.get_portfolio(session, p.id, "u-A")
    assert still_there is not None


async def test_delete_portfolio_owner_succeeds(session):
    p = await portfolio_crud.create_portfolio(session, _portfolio("Mine"), "u-A", None)

    deleted = await portfolio_crud.delete_portfolio(session, p.id, "u-A")
    assert deleted is True

    gone = await portfolio_crud.get_portfolio(session, p.id, "u-A")
    assert gone is None


# ---------------------------------------------------------------------------
# 5. delete_position: cross-owner delete is denied; owner delete succeeds
# ---------------------------------------------------------------------------

async def test_delete_position_cross_owner_denied(session):
    p = await portfolio_crud.create_portfolio(
        session, _portfolio("PortA", positions=_with_aapl()), "u-A", None
    )

    # u-B cannot delete a position in u-A's portfolio
    deleted = await portfolio_crud.delete_position(session, p.id, "AAPL", "u-B")
    assert deleted is False

    # Position still exists
    pos = await portfolio_crud.get_position(session, p.id, "AAPL")
    assert pos is not None


async def test_delete_position_owner_succeeds(session):
    p = await portfolio_crud.create_portfolio(
        session, _portfolio("PortA", positions=_with_aapl()), "u-A", None
    )

    deleted = await portfolio_crud.delete_position(session, p.id, "AAPL", "u-A")
    assert deleted is True

    pos = await portfolio_crud.get_position(session, p.id, "AAPL")
    assert pos is None


# ---------------------------------------------------------------------------
# 6. create_portfolio: stamps owner_sub and org_id
# ---------------------------------------------------------------------------

async def test_create_portfolio_stamps_owner(session):
    p = await portfolio_crud.create_portfolio(
        session, _portfolio("Stamped"), "u-X", "org-99"
    )
    assert p.owner_sub == "u-X"
    assert p.org_id == "org-99"


# ---------------------------------------------------------------------------
# 7. Same name allowed across different owners; duplicate within same owner raises
# ---------------------------------------------------------------------------

async def test_same_name_allowed_across_owners(session):
    # Both should succeed without raising
    await portfolio_crud.create_portfolio(session, _portfolio("Growth"), "u-A", None)
    await portfolio_crud.create_portfolio(session, _portfolio("Growth"), "u-B", None)


async def test_duplicate_name_within_owner_raises(session):
    await portfolio_crud.create_portfolio(session, _portfolio("Growth"), "u-A", None)
    with pytest.raises(DuplicatePortfolioNameError):
        await portfolio_crud.create_portfolio(session, _portfolio("Growth"), "u-A", None)
