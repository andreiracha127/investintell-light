"""create instruments, eod_prices, news_items tables

Revision ID: 0001
Revises:
Create Date: 2026-06-10

Creates three tables:
  - instruments   — ticker master with Tiingo metadata
  - eod_prices    — OHLCV prices; converted to a TimescaleDB hypertable on `date`
  - news_items    — Tiingo news articles with a GIN-indexed tickers ARRAY

The eod_prices hypertable uses 1-month chunks on the `date` column.  Dropping
the table in downgrade() automatically removes the hypertable metadata too.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # instruments
    # ------------------------------------------------------------------
    op.create_table(
        "instruments",
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("exchange_code", sa.String(), nullable=True),
        sa.Column("asset_type", sa.String(), nullable=True),
        sa.Column("tiingo_start_date", sa.Date(), nullable=True),
        sa.Column("tiingo_end_date", sa.Date(), nullable=True),
        sa.Column("eod_last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("ticker", name="pk_instruments"),
    )

    # ------------------------------------------------------------------
    # eod_prices  (will become a hypertable below)
    # ------------------------------------------------------------------
    op.create_table(
        "eod_prices",
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Double(), nullable=False),
        sa.Column("high", sa.Double(), nullable=False),
        sa.Column("low", sa.Double(), nullable=False),
        sa.Column("close", sa.Double(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("adj_open", sa.Double(), nullable=False),
        sa.Column("adj_high", sa.Double(), nullable=False),
        sa.Column("adj_low", sa.Double(), nullable=False),
        sa.Column("adj_close", sa.Double(), nullable=False),
        sa.Column("adj_volume", sa.BigInteger(), nullable=False),
        sa.Column("div_cash", sa.Double(), server_default="0", nullable=False),
        sa.Column("split_factor", sa.Double(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["ticker"],
            ["instruments.ticker"],
            name="fk_eod_prices_ticker_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ticker", "date", name="pk_eod_prices"),
    )
    op.create_index("ix_eod_prices_date", "eod_prices", ["date"], unique=False)

    # Convert eod_prices to a TimescaleDB hypertable partitioned on `date`.
    # chunk_time_interval => INTERVAL '1 month' gives ~monthly chunks.
    # migrate_data => TRUE copies any pre-existing rows into the hypertable
    # chunk structure; it does NOT make this call idempotent.  True idempotency
    # would require if_not_exists => TRUE.  Re-runs are prevented by Alembic's
    # alembic_version tracking, not by this flag.
    op.execute(
        "SELECT create_hypertable("
        "  'eod_prices',"
        "  'date',"
        "  chunk_time_interval => INTERVAL '1 month',"
        "  migrate_data => TRUE"
        ")"
    )

    # ------------------------------------------------------------------
    # news_items
    # ------------------------------------------------------------------
    op.create_table(
        "news_items",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "tickers",
            sa.ARRAY(sa.String()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_news_items"),
    )
    op.create_index(
        "ix_news_items_published_at", "news_items", ["published_at"], unique=False
    )
    op.create_index(
        "ix_news_items_tickers",
        "news_items",
        ["tickers"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    # Drop in reverse dependency order.
    # Dropping eod_prices automatically removes the hypertable registration.
    op.drop_index("ix_news_items_tickers", table_name="news_items")
    op.drop_index("ix_news_items_published_at", table_name="news_items")
    op.drop_table("news_items")

    op.drop_index("ix_eod_prices_date", table_name="eod_prices")
    op.drop_table("eod_prices")

    op.drop_table("instruments")
