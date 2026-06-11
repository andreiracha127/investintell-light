"""ORM models for persisted screens (F6.4): `screens` and `screen_filters`.

A screen is a named, persisted set of metric filters over the screener
universe. Single-tenant: no owner column. ``metric_code`` is validated
against the backend metric catalog at the API layer (422 on unknown codes) —
deliberately a plain string, not an enum column, so adding a catalog metric
never requires a migration.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Screen(Base):
    __tablename__ = "screens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Display name — unique across the (single-tenant) installation.
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    # Audit timestamps — both tz-aware, server-set (same conventions and
    # Core-update caveat as Portfolio).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Filters collection — lazy="raise" per project conventions: load
    # explicitly via selectinload. passive_deletes delegates child removal to
    # the DB-level ON DELETE CASCADE. Ordered by position (filter add order),
    # which also drives the results-column order.
    filters: Mapped[list["ScreenFilter"]] = relationship(
        back_populates="screen",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScreenFilter.position, ScreenFilter.id",
    )


class ScreenFilter(Base):
    __tablename__ = "screen_filters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    screen_id: Mapped[int] = mapped_column(
        ForeignKey("screens.id", ondelete="CASCADE"), nullable=False
    )

    # Catalog metric code == screener_metrics column name (whitelisted at the
    # API layer; the service re-asserts before any SQL is built).
    metric_code: Mapped[str] = mapped_column(String, nullable=False)

    # Filter bounds — null = unbounded on that side. A filter with BOTH
    # bounds null still selects the metric as a results column and still
    # excludes NULL metric values (the screener's NULL-exclusion contract).
    min_value: Mapped[float | None] = mapped_column(nullable=True)
    max_value: Mapped[float | None] = mapped_column(nullable=True)

    # Stable ordering: assigned max(position)+1 on insert, preserved on
    # upsert — drives filter and results-column order.
    position: Mapped[int] = mapped_column(nullable=False, server_default="0")

    screen: Mapped[Screen] = relationship(back_populates="filters", lazy="raise")

    __table_args__ = (
        # One filter per metric within a screen — the PUT upsert target.
        UniqueConstraint(
            "screen_id", "metric_code", name="uq_screen_filters_screen_id_metric_code"
        ),
        # Child-side FK index: selectinload and ON DELETE CASCADE scan by screen_id.
        Index("ix_screen_filters_screen_id", "screen_id"),
    )
