"""Real isolation tests for the screener service — exercises owner-scoped CRUD
functions against an in-memory SQLite database so a regression that drops an
owner filter will turn these tests RED.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.screen import Screen, ScreenFilter
from app.services import screener
from app.services.screener import DuplicateScreenNameError


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
                c, tables=[Screen.__table__, ScreenFilter.__table__]
            )
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# 1. get_screen: owner-scoped read
# ---------------------------------------------------------------------------


async def test_get_screen_owner_can_read(session):
    s = await screener.create_screen(session, "Alpha", "u-A", None)
    result = await screener.get_screen(session, s.id, "u-A")
    assert result is not None
    assert result.id == s.id


async def test_get_screen_other_owner_gets_none(session):
    s = await screener.create_screen(session, "Alpha", "u-A", None)
    result = await screener.get_screen(session, s.id, "u-B")
    assert result is None


# ---------------------------------------------------------------------------
# 2. list_screens: returns only the caller's rows
# ---------------------------------------------------------------------------


async def test_list_screens_scoped_to_owner(session):
    await screener.create_screen(session, "A-Screen", "u-A", None)
    await screener.create_screen(session, "B-Screen", "u-B", None)

    rows_a = await screener.list_screens(session, "u-A")
    rows_b = await screener.list_screens(session, "u-B")

    assert len(rows_a) == 1
    assert rows_a[0].name == "A-Screen"
    assert len(rows_b) == 1
    assert rows_b[0].name == "B-Screen"


# ---------------------------------------------------------------------------
# 3. delete_screen: cross-owner delete denied; owner delete succeeds
# ---------------------------------------------------------------------------


async def test_delete_screen_cross_owner_denied(session):
    s = await screener.create_screen(session, "Guarded", "u-A", None)

    deleted = await screener.delete_screen(session, s.id, "u-B")
    assert deleted is False

    # Row still exists for u-A
    still_there = await screener.get_screen(session, s.id, "u-A")
    assert still_there is not None


async def test_delete_screen_owner_succeeds(session):
    s = await screener.create_screen(session, "Mine", "u-A", None)

    deleted = await screener.delete_screen(session, s.id, "u-A")
    assert deleted is True

    gone = await screener.get_screen(session, s.id, "u-A")
    assert gone is None


# ---------------------------------------------------------------------------
# 4. rename_screen: cross-owner returns None (no change); owner renames
# ---------------------------------------------------------------------------


async def test_rename_screen_cross_owner_returns_none(session):
    s = await screener.create_screen(session, "Original", "u-A", None)

    result = await screener.rename_screen(session, s.id, "u-B", "Hijacked")
    assert result is None

    # Name unchanged for the real owner
    unchanged = await screener.get_screen(session, s.id, "u-A")
    assert unchanged is not None
    assert unchanged.name == "Original"


async def test_rename_screen_owner_succeeds(session):
    s = await screener.create_screen(session, "OldName", "u-A", None)

    renamed = await screener.rename_screen(session, s.id, "u-A", "NewName")
    assert renamed is not None
    assert renamed.name == "NewName"


# ---------------------------------------------------------------------------
# 5. create_screen: stamps owner_sub and org_id
# ---------------------------------------------------------------------------


async def test_create_screen_stamps_owner(session):
    s = await screener.create_screen(session, "Stamped", "u-X", "org-99")
    assert s.owner_sub == "u-X"
    assert s.org_id == "org-99"


# ---------------------------------------------------------------------------
# 6. Same name allowed across owners; duplicate within same owner raises
# ---------------------------------------------------------------------------


async def test_same_name_allowed_across_owners(session):
    # Both should succeed without raising
    await screener.create_screen(session, "Growth", "u-A", None)
    await screener.create_screen(session, "Growth", "u-B", None)


async def test_duplicate_name_within_owner_raises(session):
    await screener.create_screen(session, "Growth", "u-A", None)
    with pytest.raises(DuplicateScreenNameError):
        await screener.create_screen(session, "Growth", "u-A", None)
