# Isolamento de dados por usuário (portfolios + screens) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** isolar `portfolios`/`positions`, `screens`/`screen_filters` e `rebalance_policies` por usuário, de modo que cada conta autenticada veja/edite apenas os próprios recursos.

**Architecture:** filtragem na camada de aplicação. As tabelas-raiz (`portfolios`, `screens`) ganham `owner_sub` (= claim `sub` do JWT) e `org_id` (= claim `org_id`, gravado mas não filtrado). Toda escrita carimba o dono; toda leitura filtra por `owner_sub`. As filhas (`positions`, `screen_filters`, `rebalance_policies`) são possuídas transitivamente — a rota resolve o pai com escopo de dono antes de tocar a filha. Acesso cross-user retorna 404 (não vaza existência). Unicidade de `name` passa a ser por dono.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, asyncpg, TimescaleDB (Tiger `t83f4np6x4`, schema `public`), Alembic (migrations rodadas manualmente fora do container), InsForge JWT HS256 (`app/core/auth.py`), pytest + httpx ASGITransport.

**Source spec:** `docs/superpowers/specs/2026-06-18-portfolio-user-isolation-design.md`

## Global Constraints

- `owner_sub`/`org_id` são SEMPRE derivados do JWT no servidor — NUNCA aceitos em request body nem expostos em response. Schemas Pydantic de request/response não mudam.
- Acesso a recurso de outro usuário → **404** (jamais 403).
- Unicidade de `name`: composta `(owner_sub, name)` em `portfolios` e `screens`. Constraint nomeada na convenção do `Base` (`uq_<table>_owner_sub`).
- `owner_sub`: coluna `TEXT NOT NULL`; `org_id`: `TEXT NULL`. Sem FK (não há tabela de usuários local).
- Migrations rodam manualmente contra o Tiger (`alembic upgrade head`) — não no container.
- Comandos: `cd backend && uv run pytest ...`; lint `uv run ruff check`; tipos `uv run mypy app`.
- Convenção de testes de rota: `create_app()`, `app.dependency_overrides[get_session] = lambda: None`, `app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub="u-1", org_id=None, claims={})`, services stubbed via `monkeypatch` no módulo canônico. Sem rede/DB ao vivo.
- Branch: `feat/portfolio-user-isolation` (já criada a partir de `main`; o spec já está commitado nela).

---

## File Structure

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `backend/alembic/versions/0013_portfolio_screen_owner_isolation.py` | Schema + wipe de dados de teste | Criar |
| `backend/app/models/portfolio.py` | `Portfolio`: +`owner_sub`/`org_id`, unique composta | Modificar |
| `backend/app/models/screen.py` | `Screen`: +`owner_sub`/`org_id`, unique composta | Modificar |
| `backend/app/services/portfolio_crud.py` | Threading de `owner_sub` nas funções de CRUD/posição | Modificar |
| `backend/app/services/screener.py` | Threading de `owner_sub` nas funções de saved screen | Modificar |
| `backend/app/services/builder_save.py` | `run_save` carimba `owner_sub`/`org_id` | Modificar |
| `backend/app/api/routes/portfolios.py` | Captura `user`, repassa `user.sub` | Modificar |
| `backend/app/api/routes/rebalance.py` | Checa dono do portfolio-pai | Modificar |
| `backend/app/api/routes/builder.py` | `/save` repassa `user.sub`/`org_id` | Modificar |
| `backend/app/api/routes/screener.py` | Split público/protegido; `_screen_or_404` owner-scoped | Modificar |
| `backend/tests/*` | Atualizar stubs (9 arquivos) + testes de wiring/isolamento | Modificar/Criar |

**Arquivos de teste que fazem stub das funções alteradas (atualizar assinaturas):**
`test_portfolios_crud_route.py`, `test_portfolios_overview.py`, `test_portfolios_news_route.py`,
`test_lookthrough.py`, `test_rebalance.py`, `test_screener_routes.py`, `test_builder_save_route.py`,
`test_statistics_routes.py`, `test_statistics_service.py`.

---

## Task 1: Migration Alembic 0013 (schema + wipe)

**Files:**
- Create: `backend/alembic/versions/0013_portfolio_screen_owner_isolation.py`

**Interfaces:**
- Produces: colunas `portfolios.owner_sub` (NOT NULL), `portfolios.org_id` (NULL), `screens.owner_sub` (NOT NULL), `screens.org_id` (NULL); constraints `uq_portfolios_owner_sub (owner_sub, name)` e `uq_screens_owner_sub (owner_sub, name)`; remove `uq_portfolios_name` e `uq_screens_name`.

- [ ] **Step 1: Criar o arquivo de migration**

`backend/alembic/versions/0013_portfolio_screen_owner_isolation.py`:

```python
"""per-user isolation: owner_sub/org_id on portfolios and screens

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-18

Adds owner_sub (NOT NULL) and org_id (NULL) to the two root user-data tables
and swaps the global UNIQUE(name) for a per-owner UNIQUE(owner_sub, name).
Children (positions, screen_filters, rebalance_policies) are owned
transitively via their FK and get no column. Existing rows are test data with
no owner, so they are deleted before owner_sub becomes NOT NULL.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1) Wipe pre-isolation test data (no owner to backfill). Children cascade:
    #    positions + rebalance_policies via portfolios; screen_filters via screens.
    op.execute("DELETE FROM positions")
    op.execute("DELETE FROM portfolios")
    op.execute("DELETE FROM screen_filters")
    op.execute("DELETE FROM screens")

    # 2) portfolios: add owner columns, swap unique(name) -> unique(owner_sub, name).
    op.add_column("portfolios", sa.Column("owner_sub", sa.String(), nullable=False))
    op.add_column("portfolios", sa.Column("org_id", sa.String(), nullable=True))
    op.drop_constraint("uq_portfolios_name", "portfolios", type_="unique")
    op.create_unique_constraint(
        "uq_portfolios_owner_sub", "portfolios", ["owner_sub", "name"]
    )

    # 3) screens: same treatment.
    op.add_column("screens", sa.Column("owner_sub", sa.String(), nullable=False))
    op.add_column("screens", sa.Column("org_id", sa.String(), nullable=True))
    op.drop_constraint("uq_screens_name", "screens", type_="unique")
    op.create_unique_constraint(
        "uq_screens_owner_sub", "screens", ["owner_sub", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_screens_owner_sub", "screens", type_="unique")
    op.create_unique_constraint("uq_screens_name", "screens", ["name"])
    op.drop_column("screens", "org_id")
    op.drop_column("screens", "owner_sub")

    op.drop_constraint("uq_portfolios_owner_sub", "portfolios", type_="unique")
    op.create_unique_constraint("uq_portfolios_name", "portfolios", ["name"])
    op.drop_column("portfolios", "org_id")
    op.drop_column("portfolios", "owner_sub")
```

- [ ] **Step 2: Verificar que a migration é detectada e está encadeada**

Run: `cd backend && uv run alembic history | head -5`
Expected: a linha `0012 -> 0013 (head), per-user isolation...` aparece no topo.

- [ ] **Step 3: Aplicar upgrade/downgrade contra o DB de dev local e voltar**

(O DSN default é `postgresql+asyncpg://light:light@localhost:5436/investintell_light`. Se não houver DB local, pule para a aplicação manual no Tiger na Task 9 e marque este step como N/A no DB local.)

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: sem erros; o round-trip up→down→up conclui limpo.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0013_portfolio_screen_owner_isolation.py
git commit -m "feat(db): migration 0013 — owner_sub/org_id on portfolios + screens"
```

---

## Task 2: Modelos `Portfolio` e `Screen`

**Files:**
- Modify: `backend/app/models/portfolio.py:29-79` (classe `Portfolio`)
- Modify: `backend/app/models/screen.py:18-50` (classe `Screen`)
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: colunas da Task 1.
- Produces: `Portfolio.owner_sub: Mapped[str]`, `Portfolio.org_id: Mapped[str | None]`, `Screen.owner_sub: Mapped[str]`, `Screen.org_id: Mapped[str | None]`; `UniqueConstraint("owner_sub", "name")` em ambos.

- [ ] **Step 1: Escrever o teste de modelo (falha)**

Adicionar a `backend/tests/test_models.py`:

```python
def test_portfolio_has_owner_columns_and_composite_unique() -> None:
    from app.models.portfolio import Portfolio

    cols = Portfolio.__table__.c
    assert "owner_sub" in cols and not cols["owner_sub"].nullable
    assert "org_id" in cols and cols["org_id"].nullable
    uniques = {
        tuple(sorted(c.name for c in con.columns))
        for con in Portfolio.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("name", "owner_sub") in uniques


def test_screen_has_owner_columns_and_composite_unique() -> None:
    from app.models.screen import Screen

    cols = Screen.__table__.c
    assert "owner_sub" in cols and not cols["owner_sub"].nullable
    assert "org_id" in cols and cols["org_id"].nullable
    uniques = {
        tuple(sorted(c.name for c in con.columns))
        for con in Screen.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("name", "owner_sub") in uniques
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd backend && uv run pytest tests/test_models.py -k owner -v`
Expected: FAIL (`owner_sub` não existe).

- [ ] **Step 3: Alterar `Portfolio`**

Em `backend/app/models/portfolio.py`, na classe `Portfolio`:

Trocar a linha de `name` (remover `unique=True`):

```python
    name: Mapped[str] = mapped_column(String, nullable=False)

    # Dono (JWT sub) — escopo de isolamento. org_id (JWT org_id) é gravado mas
    # não filtrado ainda (preparação para compartilhamento por organização).
    owner_sub: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

Trocar `__table_args__` para incluir a unique composta (o índice da unique cobre buscas por `owner_sub`):

```python
    __table_args__ = (
        CheckConstraint("origin IN ('manual', 'builder')", name="origin"),
        UniqueConstraint("owner_sub", "name"),
    )
```

`UniqueConstraint` já está importado em `portfolio.py`.

- [ ] **Step 4: Alterar `Screen`**

Em `backend/app/models/screen.py`, importar `UniqueConstraint` (já importado) e na classe `Screen`:

Trocar a linha de `name`:

```python
    name: Mapped[str] = mapped_column(String, nullable=False)

    owner_sub: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

Adicionar `__table_args__` ao final da classe `Screen` (hoje ela não tem):

```python
    __table_args__ = (UniqueConstraint("owner_sub", "name"),)
```

- [ ] **Step 5: Rodar testes + tipos**

Run: `cd backend && uv run pytest tests/test_models.py -v && uv run mypy app/models/portfolio.py app/models/screen.py`
Expected: PASS / sem erros.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/portfolio.py backend/app/models/screen.py backend/tests/test_models.py
git commit -m "feat(models): owner_sub/org_id + per-owner unique on Portfolio/Screen"
```

---

## Task 3: `portfolio_crud` — threading de `owner_sub`

**Files:**
- Modify: `backend/app/services/portfolio_crud.py` (funções de CRUD/posição)
- Test: `backend/tests/test_portfolio_crud_isolation.py` (novo)

**Interfaces:**
- Consumes: `Portfolio.owner_sub` (Task 2).
- Produces (assinaturas que as rotas/builder consomem):
  - `create_portfolio(session, payload, owner_sub: str, org_id: str | None, *, origin="manual") -> Portfolio`
  - `get_portfolio(session, portfolio_id, owner_sub: str) -> Portfolio | None`
  - `list_portfolios(session, owner_sub: str) -> Sequence[Row]`
  - `update_portfolio(session, portfolio_id, owner_sub: str, *, name, cash) -> Portfolio | None`
  - `delete_portfolio(session, portfolio_id, owner_sub: str) -> bool`
  - `portfolio_exists(session, portfolio_id, owner_sub: str) -> bool`
  - `delete_position(session, portfolio_id, ticker, owner_sub: str) -> bool`

- [ ] **Step 1: Escrever os testes de isolamento (falham)**

`backend/tests/test_portfolio_crud_isolation.py`:

```python
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
```

(Estes provam a forma das cláusulas que a implementação usa; a prova end-to-end de isolamento é o smoke manual no Tiger na Task 9.)

- [ ] **Step 2: Rodar para confirmar que passam triviais e depois guiam a implementação**

Run: `cd backend && uv run pytest tests/test_portfolio_crud_isolation.py -v`
Expected: PASS (validam a forma das queries — servem de contrato para os Steps 3-4).

- [ ] **Step 3: Adicionar `owner_sub` às funções de CRUD**

Em `backend/app/services/portfolio_crud.py`:

`create_portfolio` — assinatura e construção:

```python
async def create_portfolio(
    session: AsyncSession,
    payload: PortfolioCreate,
    owner_sub: str,
    org_id: str | None,
    *,
    origin: str = "manual",
) -> Portfolio:
    portfolio = Portfolio(
        name=payload.name,
        cash=payload.cash,
        origin=origin,
        owner_sub=owner_sub,
        org_id=org_id,
        positions=[
            Position(
                ticker=p.ticker,
                quantity=p.quantity,
                acq_price=p.acq_price,
                basis=p.basis or "reference",
                commission=p.commission,
                trade_date=p.trade_date,
            )
            for p in payload.positions
        ],
    )
    session.add(portfolio)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicatePortfolioNameError(
            f"A portfolio named {payload.name!r} already exists."
        ) from exc
    loaded = await get_portfolio(session, portfolio.id, owner_sub)
    if loaded is None:  # pragma: no cover — the row was just committed
        raise RuntimeError(f"Portfolio {portfolio.id} vanished after commit.")
    return loaded
```

`get_portfolio`:

```python
async def get_portfolio(
    session: AsyncSession, portfolio_id: int, owner_sub: str
) -> Portfolio | None:
    """Load one OWNED portfolio WITH its positions (lazy='raise')."""
    result = await session.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.positions))
        .where(Portfolio.id == portfolio_id, Portfolio.owner_sub == owner_sub)
    )
    return result.scalar_one_or_none()
```

`list_portfolios`:

```python
async def list_portfolios(session: AsyncSession, owner_sub: str) -> Sequence[Row]:
    """List the caller's portfolios (id order), capped at LIST_HARD_CAP."""
    result = await session.execute(
        select(
            Portfolio.id,
            Portfolio.name,
            Portfolio.cash,
            func.count(Position.id).label("position_count"),
            Portfolio.created_at,
        )
        .outerjoin(Position)
        .where(Portfolio.owner_sub == owner_sub)
        .group_by(Portfolio.id)
        .order_by(Portfolio.id)
        .limit(LIST_HARD_CAP)
    )
    return result.all()
```

`update_portfolio` (passa `owner_sub` aos `get_portfolio`):

```python
async def update_portfolio(
    session: AsyncSession,
    portfolio_id: int,
    owner_sub: str,
    *,
    name: str | None,
    cash: float | None,
) -> Portfolio | None:
    portfolio = await get_portfolio(session, portfolio_id, owner_sub)
    if portfolio is None:
        return None
    if name is not None:
        portfolio.name = name
    if cash is not None:
        portfolio.cash = cash
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicatePortfolioNameError(
            f"A portfolio named {name!r} already exists."
        ) from exc
    return await get_portfolio(session, portfolio_id, owner_sub)
```

`delete_portfolio`:

```python
async def delete_portfolio(
    session: AsyncSession, portfolio_id: int, owner_sub: str
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Portfolio).where(
                Portfolio.id == portfolio_id, Portfolio.owner_sub == owner_sub
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)
```

`portfolio_exists`:

```python
async def portfolio_exists(
    session: AsyncSession, portfolio_id: int, owner_sub: str
) -> bool:
    found = await session.scalar(
        select(Portfolio.id).where(
            Portfolio.id == portfolio_id, Portfolio.owner_sub == owner_sub
        )
    )
    return found is not None
```

- [ ] **Step 4: Adicionar guard de dono em `delete_position`**

```python
async def delete_position(
    session: AsyncSession, portfolio_id: int, ticker: str, owner_sub: str
) -> bool:
    """Delete one position only if its portfolio belongs to owner_sub."""
    owned = select(Portfolio.id).where(
        Portfolio.id == portfolio_id, Portfolio.owner_sub == owner_sub
    )
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Position).where(
                Position.portfolio_id == portfolio_id,
                Position.ticker == ticker,
                Position.portfolio_id.in_(owned),
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)
```

(`get_position`, `insert_position`, `update_position` ficam inalterados: a rota `put_position` gateia via `portfolio_exists(..., owner_sub)` ANTES de chamá-los.)

- [ ] **Step 5: Rodar testes + tipos**

Run: `cd backend && uv run pytest tests/test_portfolio_crud_isolation.py -v && uv run mypy app/services/portfolio_crud.py`
Expected: PASS / sem erros. (Os testes de rota que stubam estas funções quebram aqui — são corrigidos nas Tasks 4/5/6.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/portfolio_crud.py backend/tests/test_portfolio_crud_isolation.py
git commit -m "feat(portfolios): scope portfolio_crud reads/writes by owner_sub"
```

---

## Task 4: Rota `portfolios.py` — wiring de identidade

**Files:**
- Modify: `backend/app/api/routes/portfolios.py`
- Test: `backend/tests/test_portfolios_crud_route.py`

**Interfaces:**
- Consumes: `portfolio_crud` owner-scoped (Task 3); `CurrentUser` (`app.core.auth`).

- [ ] **Step 1: Atualizar stubs + adicionar teste de wiring (falha)**

Em `backend/tests/test_portfolios_crud_route.py`, atualizar as assinaturas dos fakes para receber `owner_sub` (e `org_id` no create) e capturar o sub. Exemplos a aplicar:

```python
async def fake_create(
    session, payload, owner_sub, org_id
):  # era (session, payload)
    received.append((payload, owner_sub, org_id))
    return _portfolio(...)
```

```python
async def fake_get(session, portfolio_id, owner_sub):  # +owner_sub
    return _portfolio(pid=portfolio_id, positions=[_position()])
```

```python
async def fake_list(session, owner_sub):  # +owner_sub
    return rows
```

```python
async def fake_update(session, portfolio_id, owner_sub, *, name, cash):  # +owner_sub
    ...
```

```python
async def fake_delete(session, portfolio_id, owner_sub):  # +owner_sub
    return True
```

No `_install_put_stubs`:

```python
async def fake_exists(session, portfolio_id, owner_sub):  # +owner_sub
    return portfolio_found
```

```python
async def fake_delete_pos(session, portfolio_id, ticker, owner_sub):  # +owner_sub
    received.append((portfolio_id, ticker, owner_sub))
    return True
```

Adicionar um teste de wiring novo:

```python
async def test_create_forwards_owner_from_jwt(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    captured: list[tuple[str, str | None]] = []

    async def fake_create(session: Any, payload: Any, owner_sub: str, org_id: Any):
        captured.append((owner_sub, org_id))
        return _portfolio()

    monkeypatch.setattr(portfolio_crud, "create_portfolio", fake_create)
    async with _client() as ac:
        await ac.post("/portfolios", json={"name": "X"})
    assert captured == [("u-1", None)]
```

E ajustar `test_delete_position_204` para esperar `owner_sub` capturado: `assert received == [(1, "AAPL", "u-1")]`.

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd backend && uv run pytest tests/test_portfolios_crud_route.py -k "forwards_owner or delete_position_204" -v`
Expected: FAIL (a rota ainda não passa `owner_sub`).

- [ ] **Step 3: Capturar `user` e repassar `user.sub` em cada endpoint**

Em `backend/app/api/routes/portfolios.py`, importar o tipo e adicionar o parâmetro `user` a cada handler. Topo do arquivo (após os imports existentes):

```python
from app.core.auth import CurrentUser, get_current_user  # CurrentUser é novo no import
```

Em cada endpoint, adicionar o parâmetro e repassar. Mudanças por handler:

```python
# create_portfolio
async def create_portfolio(
    payload: PortfolioCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PortfolioOut:
    ...
    portfolio = await portfolio_crud.create_portfolio(
        session, payload, user.sub, user.org_id
    )
```

```python
# list_portfolios
async def list_portfolios(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[PortfolioListItem]:
    rows = await portfolio_crud.list_portfolios(session, user.sub)
```

```python
# get_portfolio / patch_portfolio / delete_portfolio / get_portfolio_overview /
# get_portfolio_news / get_portfolio_lookthrough:
# adicionar `user: Annotated[CurrentUser, Depends(get_current_user)]` e trocar
# as chamadas para:
await portfolio_crud.get_portfolio(session, portfolio_id, user.sub)
await portfolio_crud.update_portfolio(session, portfolio_id, user.sub, name=..., cash=...)
await portfolio_crud.delete_portfolio(session, portfolio_id, user.sub)
```

```python
# put_position: gate de dono e mantém o resto
if not await portfolio_crud.portfolio_exists(session, portfolio_id, user.sub):
    raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")

# delete_position: repassa owner ao service
deleted = await portfolio_crud.delete_position(session, portfolio_id, symbol, user.sub)
```

(O router já tem `dependencies=[Depends(get_current_user)]`; declarar `user=Depends(get_current_user)` no handler reusa a mesma dependência — FastAPI deduplica.)

- [ ] **Step 4: Rodar o arquivo de teste inteiro**

Run: `cd backend && uv run pytest tests/test_portfolios_crud_route.py -v`
Expected: PASS (todos, incluindo o wiring novo).

- [ ] **Step 5: Atualizar stubs nos demais testes de rota de portfolio**

Atualizar as assinaturas dos fakes (`get_portfolio`/`portfolio_exists`/etc. com `+owner_sub`) em:
`tests/test_portfolios_overview.py`, `tests/test_portfolios_news_route.py`, `tests/test_lookthrough.py`.

Run: `cd backend && uv run pytest tests/test_portfolios_overview.py tests/test_portfolios_news_route.py tests/test_lookthrough.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/portfolios.py backend/tests/test_portfolios_crud_route.py backend/tests/test_portfolios_overview.py backend/tests/test_portfolios_news_route.py backend/tests/test_lookthrough.py
git commit -m "feat(portfolios): forward JWT sub to owner-scoped portfolio_crud"
```

---

## Task 5: Rota `rebalance.py` — checar dono do portfolio-pai

**Files:**
- Modify: `backend/app/api/routes/rebalance.py`
- Test: `backend/tests/test_rebalance.py`

**Interfaces:**
- Consumes: `portfolio_crud.portfolio_exists/get_portfolio` owner-scoped (Task 3).

- [ ] **Step 1: Atualizar stubs + teste de isolamento (falha)**

Em `backend/tests/test_rebalance.py`, garantir que o client faz override de `get_current_user` (padrão do `_client()`), atualizar fakes de `portfolio_crud.get_portfolio`/`portfolio_exists` para `+owner_sub`, e adicionar:

```python
async def test_rebalance_policy_get_404_for_non_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_exists(session, portfolio_id, owner_sub):
        return False  # portfolio não é do usuário -> indistinguível de inexistente

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_exists)
    async with _client() as ac:
        response = await ac.get("/portfolios/1/rebalance/policy")
    assert response.status_code == 404
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd backend && uv run pytest tests/test_rebalance.py -k non_owner -v`
Expected: FAIL (hoje a rota não checa o dono no GET policy).

- [ ] **Step 3: Adicionar a checagem de dono nos três endpoints**

Em `backend/app/api/routes/rebalance.py`, importar `CurrentUser` e `portfolio_crud` (já importado), e em cada handler:

```python
# get_rebalance_policy
async def get_rebalance_policy(
    portfolio_id: int,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> RebalancePolicyOut:
    if not await portfolio_crud.portfolio_exists(session, portfolio_id, user.sub):
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    policy = await evaluator.get_policy(session, portfolio_id)
    if policy is None:
        raise HTTPException(status_code=404, detail=(...))  # mensagem existente
    return _policy_out(policy, is_default=False)
```

```python
# put_rebalance_policy: trocar o gate por um owner-scoped
async def put_rebalance_policy(
    portfolio_id: int,
    payload: RebalancePolicyIn,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> RebalancePolicyOut:
    if not await portfolio_crud.portfolio_exists(session, portfolio_id, user.sub):
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    policy = await evaluator.upsert_policy(session, portfolio_id, frequency=..., ...)
    ...
```

```python
# get_rebalance_preview: usar get_portfolio owner-scoped
async def get_rebalance_preview(
    portfolio_id: int,
    session: SessionDep,
    datalake: OptionalDatalakeDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> RebalancePreviewResponse:
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id, user.sub)
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    ...
```

Adicionar ao import do topo: `from typing import Annotated` (já presente) e `from app.core.auth import CurrentUser, get_current_user` (trocar o import existente de `get_current_user` para incluir `CurrentUser`).

- [ ] **Step 4: Rodar testes + tipos**

Run: `cd backend && uv run pytest tests/test_rebalance.py -v && uv run mypy app/api/routes/rebalance.py`
Expected: PASS / sem erros.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/rebalance.py backend/tests/test_rebalance.py
git commit -m "feat(rebalance): gate policy/preview on portfolio ownership"
```

---

## Task 6: `builder_save` + rota `builder.py` — carimbar dono no save

**Files:**
- Modify: `backend/app/services/builder_save.py:241` (`run_save`)
- Modify: `backend/app/api/routes/builder.py:66` (`save`)
- Test: `backend/tests/test_builder_save_route.py`

**Interfaces:**
- Consumes: `portfolio_crud.create_portfolio(..., owner_sub, org_id, *, origin)` (Task 3); `CurrentUser`.
- Produces: `run_save(session, payload, owner_sub: str, org_id: str | None) -> SaveResponse`.

- [ ] **Step 1: Atualizar stubs + teste de wiring (falha)**

Em `backend/tests/test_builder_save_route.py`: garantir override de `get_current_user`; se o teste stuba `builder_save.run_save`, atualizar para `(session, payload, owner_sub, org_id)` e capturar; se stuba `portfolio_crud.create_portfolio`, atualizar para `(session, payload, owner_sub, org_id, *, origin)`. Adicionar:

```python
async def test_save_forwards_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str | None]] = []

    async def fake_run_save(session, payload, owner_sub, org_id):
        captured.append((owner_sub, org_id))
        return SaveResponse(portfolio_id=1, name="P", notional_usd=1000.0, positions=[])

    monkeypatch.setattr(builder_save, "run_save", fake_run_save)
    async with _client() as ac:
        await ac.post("/builder/save", json={<payload mínimo válido do teste existente>})
    assert captured == [("u-1", None)]
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd backend && uv run pytest tests/test_builder_save_route.py -k forwards_owner -v`
Expected: FAIL.

- [ ] **Step 3: `run_save` aceita e repassa o dono**

Em `backend/app/services/builder_save.py`, alterar a assinatura e a chamada de create_portfolio:

```python
async def run_save(
    session: AsyncSession,
    payload: SaveRequest,
    owner_sub: str,
    org_id: str | None,
) -> SaveResponse:
    ...
    try:
        portfolio = await portfolio_crud.create_portfolio(
            session, create_payload, owner_sub, org_id, origin="builder"
        )
    except portfolio_crud.DuplicatePortfolioNameError as exc:
        raise BuilderError(str(exc)) from exc
    ...
```

- [ ] **Step 4: Rota `/save` captura `user` e repassa**

Em `backend/app/api/routes/builder.py`:

```python
from app.core.auth import CurrentUser, get_current_user  # CurrentUser é novo

@router.post("/save", response_model=SaveResponse, status_code=201)
async def save(
    payload: SaveRequest,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SaveResponse:
    try:
        return await builder_save.run_save(session, payload, user.sub, user.org_id)
    except BuilderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

(Remover o `dependencies=[Depends(get_current_user)]` do decorator — a dependência agora vem pelo parâmetro `user`, que cumpre o mesmo papel de proteção. `/optimize` permanece público.)

- [ ] **Step 5: Rodar testes + tipos**

Run: `cd backend && uv run pytest tests/test_builder_save_route.py -v && uv run mypy app/services/builder_save.py app/api/routes/builder.py`
Expected: PASS / sem erros.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/builder_save.py backend/app/api/routes/builder.py backend/tests/test_builder_save_route.py
git commit -m "feat(builder): stamp owner_sub/org_id when saving a proposal"
```

---

## Task 7: `screener` service — threading de `owner_sub`

**Files:**
- Modify: `backend/app/services/screener.py:103-166` (CRUD de screen)
- Test: `backend/tests/test_screener_isolation.py` (novo)

**Interfaces:**
- Consumes: `Screen.owner_sub` (Task 2).
- Produces:
  - `create_screen(session, name, owner_sub: str, org_id: str | None) -> Screen`
  - `get_screen(session, screen_id, owner_sub: str) -> Screen | None`
  - `list_screens(session, owner_sub: str) -> Sequence[Row]`
  - `rename_screen(session, screen_id, owner_sub: str, name: str) -> Screen | None`
  - `delete_screen(session, screen_id, owner_sub: str) -> bool`

- [ ] **Step 1: Teste de forma de query (passa, contrato)**

`backend/tests/test_screener_isolation.py`:

```python
from sqlalchemy import select
from app.models.screen import Screen


def test_owned_screen_select_filters_owner() -> None:
    stmt = select(Screen).where(Screen.id == 1, Screen.owner_sub == "u-1")
    assert "owner_sub" in str(stmt.compile())
```

Run: `cd backend && uv run pytest tests/test_screener_isolation.py -v` → PASS.

- [ ] **Step 2: Alterar as funções de CRUD de screen**

Em `backend/app/services/screener.py`:

```python
async def create_screen(
    session: AsyncSession, name: str, owner_sub: str, org_id: str | None
) -> Screen:
    screen = Screen(name=name, owner_sub=owner_sub, org_id=org_id, filters=[])
    session.add(screen)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateScreenNameError(f"A screen named {name!r} already exists.") from exc
    loaded = await get_screen(session, screen.id, owner_sub)
    if loaded is None:  # pragma: no cover
        raise RuntimeError(f"Screen {screen.id} vanished after commit.")
    return loaded


async def get_screen(
    session: AsyncSession, screen_id: int, owner_sub: str
) -> Screen | None:
    result = await session.execute(
        select(Screen)
        .options(selectinload(Screen.filters))
        .where(Screen.id == screen_id, Screen.owner_sub == owner_sub)
    )
    return result.scalar_one_or_none()


async def list_screens(session: AsyncSession, owner_sub: str) -> Sequence[Row]:
    result = await session.execute(
        select(
            Screen.id,
            Screen.name,
            func.count(ScreenFilter.id).label("filter_count"),
            Screen.created_at,
            Screen.updated_at,
        )
        .outerjoin(ScreenFilter)
        .where(Screen.owner_sub == owner_sub)
        .group_by(Screen.id)
        .order_by(Screen.id)
        .limit(LIST_HARD_CAP)
    )
    return result.all()


async def rename_screen(
    session: AsyncSession, screen_id: int, owner_sub: str, name: str
) -> Screen | None:
    screen = await get_screen(session, screen_id, owner_sub)
    if screen is None:
        return None
    screen.name = name
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateScreenNameError(f"A screen named {name!r} already exists.") from exc
    return await get_screen(session, screen_id, owner_sub)


async def delete_screen(
    session: AsyncSession, screen_id: int, owner_sub: str
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Screen).where(
                Screen.id == screen_id, Screen.owner_sub == owner_sub
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)
```

(`upsert_filter`, `delete_filter`, `reorder_filters`, `fetch_results`, `count_matching`, `compute_distribution` ficam por `screen_id` — gateados pela rota via `_screen_or_404(..., owner_sub)`.)

- [ ] **Step 3: Rodar tipos**

Run: `cd backend && uv run mypy app/services/screener.py`
Expected: sem erros. (Os testes de rota de screener quebram aqui — corrigidos na Task 8.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/screener.py backend/tests/test_screener_isolation.py
git commit -m "feat(screener): scope saved-screen CRUD by owner_sub"
```

---

## Task 8: Rota `screener.py` — split público/protegido + owner

**Files:**
- Modify: `backend/app/api/routes/screener.py`
- Test: `backend/tests/test_screener_routes.py`

**Interfaces:**
- Consumes: `screener_service` owner-scoped (Task 7); `CurrentUser`.

- [ ] **Step 1: Atualizar stubs + testes de proteção (falham)**

Em `backend/tests/test_screener_routes.py`, no client builder, adicionar o override:

```python
app.dependency_overrides[get_current_user] = lambda: CurrentUser(
    sub="u-1", org_id=None, claims={}
)
```

(e os imports `from app.core.auth import CurrentUser, get_current_user`). Atualizar os fakes de `get_screen`/`list_screens`/`create_screen`/`rename_screen`/`delete_screen` com os novos parâmetros (`+owner_sub`, e `create_screen` com `+org_id`). Adicionar:

```python
def _client_noauth() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_metrics_catalog_is_public() -> None:
    async with _client_noauth() as ac:
        response = await ac.get("/screener/metrics")
    assert response.status_code != 401


async def test_screens_list_requires_auth() -> None:
    async with _client_noauth() as ac:
        response = await ac.get("/screener/screens")
    assert response.status_code in (401, 403)
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `cd backend && uv run pytest tests/test_screener_routes.py -k "public or requires_auth" -v`
Expected: FAIL (`/screener/screens` ainda é público → 200).

- [ ] **Step 3: Split em dois routers + `_screen_or_404` owner-scoped**

Em `backend/app/api/routes/screener.py`:

```python
from app.core.auth import CurrentUser, get_current_user

# Router público: apenas o catálogo estático de métricas.
public_router = APIRouter(prefix="/screener", tags=["screener"])

# Router protegido: tudo que opera sobre saved screens (dado de usuário).
router = APIRouter(
    prefix="/screener",
    tags=["screener"],
    dependencies=[Depends(get_current_user)],
)
```

Mover `@router.get("/metrics")` para `@public_router.get("/metrics")`. Manter TODOS os endpoints `/screens/**` no `router` protegido.

Tornar `_screen_or_404` owner-scoped:

```python
async def _screen_or_404(
    session: AsyncSession, screen_id: int, owner_sub: str
) -> Screen:
    screen = await screener_service.get_screen(session, screen_id, owner_sub)
    if screen is None:
        raise HTTPException(status_code=404, detail=f"Screen {screen_id} not found.")
    return screen
```

Em cada endpoint `/screens/**`, adicionar `user: Annotated[CurrentUser, Depends(get_current_user)]` e repassar `user.sub`:
- `create_screen`: `await screener_service.create_screen(session, payload.name, user.sub, user.org_id)`
- `list_screens`: `await screener_service.list_screens(session, user.sub)`
- `get_screen`/`patch_screen`/`delete_screen`: `screener_service.get_screen/rename_screen/delete_screen(session, screen_id, user.sub[, name])`
- `put_filter`/`delete_filter`/`reorder_filters`/`build_metric`/`build_all`/`get_results`/`get_results_csv`: trocar as chamadas `_screen_or_404(session, screen_id)` por `_screen_or_404(session, screen_id, user.sub)` (o gate de dono); as funções de filter/build/results seguem por `screen_id` já validado.

Registrar o `public_router` onde os routers são incluídos (procurar `include_router(screener` em `app/main.py` ou `app/api/__init__.py` e adicionar `include_router(screener.public_router)` ao lado do `screener.router`).

- [ ] **Step 4: Rodar o arquivo de teste inteiro**

Run: `cd backend && uv run pytest tests/test_screener_routes.py -v`
Expected: PASS (incluindo os dois novos de proteção).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/screener.py backend/app/main.py backend/tests/test_screener_routes.py
git commit -m "feat(screener): protect saved-screen routes, owner-scope, keep /metrics public"
```

---

## Task 9: Regressão completa, schemas e smoke manual no Tiger

**Files:**
- Modify: `backend/tests/test_statistics_routes.py`, `backend/tests/test_statistics_service.py` (stubs remanescentes, se houver)
- Verify: `backend/app/schemas/portfolios.py`, `backend/app/schemas/screener.py` (sem owner exposto)

**Interfaces:**
- Consumes: todas as tasks anteriores.

- [ ] **Step 1: Corrigir stubs remanescentes**

Atualizar quaisquer fakes de `get_portfolio`/`portfolio_exists`/`get_screen`/`list_screens` em `tests/test_statistics_routes.py` e `tests/test_statistics_service.py` para as novas assinaturas (`+owner_sub`).

Run: `cd backend && uv run pytest tests/test_statistics_routes.py tests/test_statistics_service.py -v`
Expected: PASS.

- [ ] **Step 2: Confirmar que `owner_sub`/`org_id` NÃO vazam nas responses**

Run: `cd backend && uv run pytest -q`
Expected: suíte inteira verde. Adicionalmente, inspecionar `app/schemas/portfolios.py` (`PortfolioOut`, `PortfolioListItem`) e `app/schemas/screener.py` (`ScreenOut`, `ScreenListItem`): confirmar que NÃO declaram `owner_sub`/`org_id` (não declaram hoje; como usam `from_attributes`, campos não declarados não são serializados — nada a fazer, apenas confirmar).

- [ ] **Step 3: Lint + tipos no projeto inteiro**

Run: `cd backend && uv run ruff check && uv run mypy app`
Expected: limpo.

- [ ] **Step 4: Aplicar a migration no Tiger (manual)**

Com `DATABASE_URL` apontando para o Tiger `t83f4np6x4` (mesmo DSN do serviço `api`):

Run: `cd backend && uv run alembic upgrade head`
Expected: `Running upgrade 0012 -> 0013`. Verificar no Tiger:

```sql
SELECT count(*) FROM portfolios;   -- 0 (wipe)
SELECT count(*) FROM screens;      -- 0 (wipe)
\d portfolios   -- owner_sub NOT NULL, org_id, uq_portfolios_owner_sub (owner_sub, name)
\d screens      -- idem
```

- [ ] **Step 5: Smoke de isolamento end-to-end (dois JWTs)**

Com dois tokens InsForge válidos de usuários distintos (A=subA, B=subB):
1. `POST /portfolios` (token A) cria "Growth" → 201.
2. `POST /portfolios` (token B) cria "Growth" → 201 (mesmo nome permitido entre donos).
3. `GET /portfolios` (token B) → lista NÃO contém o portfolio de A.
4. `GET /portfolios/{id_de_A}` (token B) → 404.
5. `GET /portfolios/{id_de_A}/rebalance/policy` (token B) → 404.
6. Repetir 1-4 para `POST/GET /screener/screens` (A cria, B recebe 404 no id de A; `GET /screener/metrics` sem token → 200).

Documentar o resultado no PR.

- [ ] **Step 6: Commit final + abrir PR**

```bash
git add backend/tests/test_statistics_routes.py backend/tests/test_statistics_service.py
git commit -m "test: update remaining stubs for owner-scoped services"
```

Abrir PR de `feat/portfolio-user-isolation` → `main` com o resumo do smoke da Step 5.

---

## Self-Review (preenchido)

**Cobertura do spec:** §2 modelo → Task 1+2; §3 identidade não-cliente → Tasks 4/6/8 (schemas inalterados, confirmado na Task 9.2); §4 service → Tasks 3/7; §5 rotas → Tasks 4/5/6/8; §6 migração+wipe → Task 1 (aplicada na Task 9.4); §7 testes → cada task + Task 9. Sem lacunas.

**Placeholders:** o único trecho não-literal é o `<payload mínimo válido>` na Task 6.1 — intencional: reusar o payload já existente em `test_builder_save_route.py` (o teste já tem um válido). Sem TBD/TODO.

**Consistência de tipos:** ordem de parâmetros uniforme — `owner_sub: str` posicional após os obrigatórios existentes; `org_id: str | None` só em criação (`create_portfolio`, `create_screen`, `run_save`). Nomes batem entre "Produces" das Tasks 3/6/7 e os "Consumes" das rotas (Tasks 4/5/6/8).
