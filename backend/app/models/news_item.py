"""
ORM model for the `news_items` table.

Stores news articles sourced from Tiingo. The `id` is Tiingo's own integer news ID
(not auto-incremented by us). The `tickers` column is a Postgres ARRAY so a single
article can be associated with multiple tickers; a GIN index on that column makes
per-ticker lookups fast.
"""

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NewsItem(Base):
    __tablename__ = "news_items"

    # Tiingo's own news ID — used as PK directly (no autoincrement here).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    # Article content fields.
    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When the article was published (tz-aware, indexed for time-range queries).
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Postgres ARRAY of ticker symbols linked to this article.
    # Default is an empty array; a GIN index enables containment lookups (@>).
    tickers: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default="{}",
    )

    # When this row was written to our DB.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (Index("ix_news_items_tickers", "tickers", postgresql_using="gin"),)
