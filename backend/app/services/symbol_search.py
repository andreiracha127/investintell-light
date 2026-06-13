"""Symbol search unificado (Compare autocomplete): universe + funds.

Sem Tiingo, sem cache — ILIKE em duas tabelas locais pequenas a cada tecla.
``rank_hits`` é puro (unit-tested); os readers SQL são finos.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fund import Fund
from app.models.universe import UniverseConstituent

FETCH_CAP = 50  # por tabela, antes do ranking


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards in user search input (backslash escape char)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class SymbolHit:
    symbol: str
    name: str | None
    kind: str  # "stock" | fund_type ("etf" | "mutual_fund" | "mmf")
    instrument_id: uuid.UUID | None


async def fetch_stock_hits(session: AsyncSession, q: str) -> list[SymbolHit]:
    q_upper = q.upper()
    q_esc = _escape_like(q_upper)
    prefix = f"{q_esc}%"
    sub = f"%{_escape_like(q)}%"
    exact_match = (UniverseConstituent.ticker == q_upper).desc()
    prefix_match = UniverseConstituent.ticker.like(prefix, escape="\\").desc()
    result = await session.execute(
        select(UniverseConstituent.ticker, UniverseConstituent.name)
        .where(
            UniverseConstituent.status == "active",
            (UniverseConstituent.ticker.like(prefix, escape="\\"))
            | (UniverseConstituent.name.ilike(sub, escape="\\")),
        )
        .order_by(exact_match, prefix_match, UniverseConstituent.ticker.asc())
        .limit(FETCH_CAP)
    )
    return [SymbolHit(symbol=t, name=n, kind="stock", instrument_id=None) for t, n in result.all()]


async def fetch_fund_hits(session: AsyncSession, q: str) -> list[SymbolHit]:
    q_upper = q.upper()
    q_esc = _escape_like(q_upper)
    prefix = f"{q_esc}%"
    sub = f"%{_escape_like(q)}%"
    ticker_upper = func.upper(Fund.ticker)
    exact_match = (ticker_upper == q_upper).desc()
    prefix_match = ticker_upper.like(prefix, escape="\\").desc()
    result = await session.execute(
        select(Fund.ticker, Fund.name, Fund.fund_type, Fund.instrument_id)
        .where(
            Fund.ticker.is_not(None),
            (ticker_upper.like(prefix, escape="\\")) | (Fund.name.ilike(sub, escape="\\")),
        )
        .order_by(exact_match, prefix_match, ticker_upper.asc())
        .limit(FETCH_CAP)
    )
    return [
        SymbolHit(symbol=t.upper(), name=n, kind=ft, instrument_id=iid)
        for t, n, ft, iid in result.all()
    ]


def rank_hits(hits: list[SymbolHit], q: str, limit: int) -> list[SymbolHit]:
    """Dedup por symbol (último vence — passar stocks ANTES de funds) e
    ordena: ticker exato, prefixo de ticker, resto; tiebreak alfabético."""
    q_upper = q.upper()
    by_symbol: dict[str, SymbolHit] = {}
    for h in hits:
        by_symbol[h.symbol] = h

    def key(h: SymbolHit) -> tuple[int, str]:
        if h.symbol == q_upper:
            rank = 0
        elif h.symbol.startswith(q_upper):
            rank = 1
        else:
            rank = 2
        return (rank, h.symbol)

    return sorted(by_symbol.values(), key=key)[:limit]
