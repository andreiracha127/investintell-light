"""Scheduled rebalance evaluation job (Frente A — A3).

Run from backend/:
    python scripts/evaluate_rebalance.py
    python scripts/evaluate_rebalance.py --portfolio-id 7

Avalia cada portfólio COM política salva (o preview on-demand cobre os sem
política, com defaults) e carimba ``last_evaluated_at``. Imprime uma linha
JSON por portfólio com a decisão — o produto é advisory: este job NUNCA
executa ordens, só materializa a avaliação para alertas/UI.

Portfólios não-avaliáveis (preço local ausente, <2 posições) são reportados
como erro explícito na saída e seguem para o próximo — uma falha não pode
silenciar as demais avaliações.
"""

import argparse
import asyncio
import datetime as dt
import json
import pathlib
import sys

_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import AsyncSessionLocal, engine  # noqa: E402
from app.models.rebalance import RebalancePolicy  # noqa: E402
from app.rebalance import evaluator  # noqa: E402
from app.services import portfolio_builder, portfolio_crud  # noqa: E402


async def _datalake_session():
    if not get_settings().datalake_db_url:
        return None, None
    from app.core.datalake import _get_sessionmaker

    maker = _get_sessionmaker()
    session = maker()
    return maker, session


async def _run(portfolio_id: int | None) -> int:
    stmt = select(RebalancePolicy)
    if portfolio_id is not None:
        stmt = stmt.where(RebalancePolicy.portfolio_id == portfolio_id)
    failures = 0
    _maker, datalake = await _datalake_session()
    try:
        async with AsyncSessionLocal() as session:
            policies = list((await session.execute(stmt)).scalars())
            if not policies:
                print(json.dumps({"evaluated": 0, "note": "no policies"}))
                return 0
            now = dt.datetime.now(dt.UTC)
            for policy in policies:
                portfolio = await portfolio_crud.get_portfolio(
                    session, policy.portfolio_id
                )
                if portfolio is None:  # FK garante; defensivo
                    continue
                try:
                    evaluation = await evaluator.evaluate_portfolio(
                        session, datalake, portfolio, policy, now=now
                    )
                except (
                    evaluator.RebalanceError,
                    portfolio_builder.BuilderError,
                ) as exc:
                    failures += 1
                    print(json.dumps({
                        "portfolio_id": policy.portfolio_id,
                        "error": str(exc),
                    }))
                    continue
                await evaluator.stamp_evaluated(
                    session, policy.portfolio_id, now
                )
                print(json.dumps({
                    "portfolio_id": policy.portfolio_id,
                    "decision": evaluation.decision,
                    "calendar_due": evaluation.calendar_due,
                    "macro_triggered": evaluation.macro_triggered,
                    "breaches": [
                        d.ticker for d in evaluation.drifts if d.breach
                    ],
                    "turnover_pct": round(
                        evaluation.proposal.turnover_pct, 4
                    ),
                }))
    finally:
        if datalake is not None:
            await datalake.close()
        await engine.dispose()
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portfolio-id", type=int, default=None)
    args = parser.parse_args()
    failures = asyncio.run(_run(args.portfolio_id))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
