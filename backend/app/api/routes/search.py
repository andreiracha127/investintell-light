"""Symbol search (Compare autocomplete): GET /search/symbols.

DB-only: universe_constituents + funds locais; nunca Tiingo. Sem cache de
catálogo — a query muda a cada tecla e viraria churn.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.market import SymbolSearchResult
from app.services.symbol_search import fetch_fund_hits, fetch_stock_hits, rank_hits

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/symbols", response_model=list[SymbolSearchResult])
async def search_symbols(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=1, max_length=40)],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> list[SymbolSearchResult]:
    """Sugestões para o Compare: ações (universe) e fundos com ticker."""
    query = q.strip()
    if not query:
        return []
    # stocks ANTES de funds: no dedup por symbol o fund (mais específico) vence.
    hits = (await fetch_stock_hits(session, query)) + (await fetch_fund_hits(session, query))
    return [
        SymbolSearchResult(
            symbol=h.symbol, name=h.name, kind=h.kind, instrument_id=h.instrument_id
        )
        for h in rank_hits(hits, query, limit)
    ]
