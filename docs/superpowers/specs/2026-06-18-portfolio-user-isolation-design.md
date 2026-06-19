# Isolamento de dados por usuário (portfolios + screens) — Design

> Status: **aprovado em brainstorming**, aguardando revisão do spec antes do plano de implementação.

**Goal:** hoje os dados de usuário (`portfolios`/`positions`, `screens`/`screen_filters`,
`rebalance_policies`) são **single-tenant** — não há coluna de dono. Mesmo com o auth
InsForge protegendo as rotas de escrita, todo usuário autenticado enxerga e edita o
**mesmo** conjunto global. Este design adiciona isolamento por usuário: cada conta passa a
ver/editar apenas os próprios recursos.

**Abordagem (escolhida):** filtragem na camada de aplicação — coluna `owner_sub` nas
tabelas-raiz, carimbada na escrita e filtrada em toda leitura. (RLS do Postgres foi
descartado: a API conecta como `tsdbadmin`, que tem `BYPASSRLS`, então políticas não teriam
efeito sem uma role dedicada e replumbing do pool. Fica anotado como hardening futuro.)

**Identidade:** escopo por `sub` (id do usuário do JWT). `org_id` também é gravado na linha
(nullable), **mas não é filtrado ainda** — prepara compartilhamento por organização no
futuro sem nova migração de dados.

**Tech stack (inalterado):** FastAPI, SQLAlchemy 2 async, asyncpg, TimescaleDB (Tiger
`t83f4np6x4`, schema `public`), Alembic (migrations rodadas manualmente fora do container),
InsForge JWT (HS256, `app/core/auth.py`), pytest + httpx ASGITransport.

**Boundary de execução (este esforço):** escrever todo o código/SQL/testes e a migration
Alembic; **a aplicação da migration no Tiger é manual** (convenção do projeto). A migration
**apaga os dados de teste existentes** (ver §6).

---

## 1. Escopo

Dentro do escopo:

| Recurso | Tratamento |
|---|---|
| `portfolios` + `positions` | `owner_sub` em `portfolios`; `positions` herda via `portfolio_id` |
| `screens` + `screen_filters` | `owner_sub` em `screens`; `screen_filters` herda via `screen_id` |
| `rebalance_policies` | sem coluna — possuída transitivamente via `portfolio_id` (PK/FK) |
| Rota `screener.py` | proteger os endpoints `/screener/screens/**` (hoje públicos) |

Fora do escopo (YAGNI): filtragem por `org_id`; RLS; isolamento de qualquer tabela de
catálogo/mercado (`funds_v`, `eod_prices`, `screener_metrics`, `news_items`, etc. — são
dados globais, não de usuário); UI do frontend (consome a API inalterada em contrato).

## 2. Modelo de dados

Tabelas-raiz ganham dono; filhas herdam pela FK existente (`ON DELETE CASCADE` já presente).

**`portfolios`** (`app/models/portfolio.py`):
- `+ owner_sub: Mapped[str]` — `String, nullable=False`. JWT `sub`.
- `+ org_id: Mapped[str | None]` — `String, nullable=True`. JWT `org_id`.
- Remover `unique=True` de `name`; adicionar `UniqueConstraint("owner_sub", "name")`.
- Index em `owner_sub` (toda listagem filtra por ele).

**`screens`** (`app/models/screen.py`): exatamente o mesmo padrão de `portfolios`.

**`positions`, `screen_filters`, `rebalance_policies`:** sem alteração de schema. O dono é
resolvido pelo pai.

`owner_sub` é `TEXT` (o `sub` da InsForge é um UUID/string opaca; tratamos como string
opaca, sem FK — não há tabela de usuários local).

## 3. Identidade nunca vem do cliente

`owner_sub`/`org_id` são **derivados do JWT no servidor** e **nunca** aparecem em request
body ou response:

- Schemas Pydantic de request (`PortfolioCreate`, `PositionBody`, `ScreenCreate`,
  `FilterBody`, `SaveRequest`, `PortfolioPatch`, `ScreenPatch`) **não mudam** → o cliente não
  consegue forjar/alterar dono.
- Schemas de response (`PortfolioOut`, `ScreenOut`, …) **não expõem** `owner_sub`/`org_id`.
- Cada rota captura `user: Annotated[CurrentUser, Depends(get_current_user)]` e repassa
  `user.sub` (e `user.org_id` nas escritas) para o service.

## 4. Camada de service (onde o isolamento mora)

Todo SQL já está concentrado em `app/services/portfolio_crud.py`, `app/services/screener.py`
(saved screens) e `app/services/builder_save.py`. As funções ganham parâmetro `owner_sub`
(e `org_id` nas que inserem):

- **Escrita** (`create_portfolio`, `insert_position` via portfolio, `create_screen`,
  `builder_save.run_save`): carimba `owner_sub`/`org_id` no INSERT da raiz.
- **Leitura/listagem** (`list_portfolios`, `list_screens`): `WHERE owner_sub = :sub`.
- **Operações por id na raiz** (`get_portfolio`, `portfolio_exists`, `update_portfolio`,
  `delete_portfolio`, `get_screen`, `rename_screen`, `delete_screen`): filtram por
  `owner_sub` → registro de outro usuário fica **indistinguível de inexistente**.
- **Operações nas filhas** (positions, filters, rebalance policy): a rota resolve o **pai
  com escopo de dono primeiro** (`get_portfolio` / `_screen_or_404` / `portfolio_exists`
  owner-scoped → 404 se não for do usuário); as ops na filha seguem por
  `portfolio_id`/`screen_id` já validado. Nenhuma query de filha precisa de `owner_sub`
  próprio, mas **toda** rota que toca uma filha deve passar pela verificação do pai.

Princípio de robustez: concentrar o filtro no service e cobrir cada rota com um teste de
isolamento (§7) — uma query nova que esqueça o filtro é pega pelo teste.

## 5. Recorte de proteção das rotas

- **`app/api/routes/portfolios.py`** — router já tem `dependencies=[Depends(get_current_user)]`.
  Cada endpoint passa a capturar `user` e a repassar `user.sub` ao `portfolio_crud`.
  Endpoints afetados: `create`, `list`, `get`, `patch`, `delete`, `put_position`,
  `delete_position`, `overview`, `news`, `lookthrough` (todos resolvem o portfolio via
  `get_portfolio`/`portfolio_exists`, que viram owner-scoped).
- **`app/api/routes/rebalance.py`** — já protegido. Antes de ler/gravar a policy, validar
  `portfolio_crud.portfolio_exists(session, portfolio_id, owner_sub)` → 404. Sem coluna em
  `rebalance_policies`.
- **`app/api/routes/builder.py`** — `/optimize` continua **público** (cálculo puro, sem
  persistência). `/save` (já protegido) captura `user` e repassa `user.sub`/`user.org_id`
  ao `builder_save.run_save`.
- **`app/api/routes/screener.py`** — hoje **sem auth**. Recorte:
  - **Público:** `GET /screener/metrics` (catálogo estático de métricas).
  - **Protegido + owner-scoped:** todos os `/screener/screens/**` (CRUD, filters upsert/
    delete/reorder, build, build/{metric}, results, results.csv). Implementação: dividir o
    `screener.py` em **dois routers** — um público (`/screener/metrics`) e um protegido
    (`dependencies=[Depends(get_current_user)]`) para `/screener/screens/**`. (O split é
    preferível à dependência por-endpoint: garante por construção que nenhum endpoint de
    screen escape da proteção.) `_screen_or_404` vira owner-scoped e gateia build/results/
    filters/CSV (todos resolvem a screen por ele antes de qualquer cálculo).

## 6. Migração de schema + dados (Alembic `0013`)

Arquivo: `backend/alembic/versions/0013_portfolio_screen_owner_isolation.py`
(`down_revision = "0012"`). Rodada **manualmente contra o Tiger** (`alembic upgrade head`).

`upgrade()`:
1. **Apagar dados de teste existentes** antes de aplicar `NOT NULL`:
   - `DELETE FROM positions; DELETE FROM portfolios;` (você confirmou: 6 portfolios / 119
     positions eram testes).
   - `DELETE FROM screen_filters; DELETE FROM screens;` — **mesma natureza de teste e
     necessário** porque `screens.owner_sub` passa a ser `NOT NULL`. (Confirmado no review.)
   - `rebalance_policies` cai por cascade ao apagar `portfolios`.
2. `ALTER TABLE portfolios ADD COLUMN owner_sub TEXT NOT NULL`, `ADD COLUMN org_id TEXT`.
3. `ALTER TABLE screens ADD COLUMN owner_sub TEXT NOT NULL`, `ADD COLUMN org_id TEXT`.
4. Trocar unicidade de `name`: drop do unique global; criar `UNIQUE (owner_sub, name)` em
   `portfolios` e `screens` (nomes de constraint na convenção do `Base`).
5. Index em `portfolios(owner_sub)` e `screens(owner_sub)`.

`downgrade()`: dropar índices/constraints compostas, recriar unique global de `name`, dropar
as colunas. (Não restaura dados apagados — o wipe é irreversível; aceitável por serem dados
de teste.)

## 7. Testes

- **Ajuste dos overrides existentes:** os testes de rota sobrescrevem
  `app.dependency_overrides[get_current_user]` com um `CurrentUser` fixo — garantir que ele
  forneça um `sub` estável e, onde o teste cobre listagem/isolamento, dois subs distintos.
- **Testes de isolamento por rota (núcleo):** usuário A cria o recurso; usuário B recebe
  **404** em GET/PATCH/DELETE/positions/overview/news/lookthrough (portfolios),
  GET/PATCH/DELETE/filters/build/results (screens) e rebalance; a **lista** de A não inclui
  itens de B; o **mesmo `name`** é aceito para A e B (não dispara 409 cross-user).
- **Testes de service:** `list_*`/`get_*` filtram por `owner_sub`; INSERT carimba
  `owner_sub`/`org_id`; `portfolio_exists(.., owner_sub)` retorna False para dono errado.
- **Regressão:** suíte existente (`uv run pytest`) verde; `uv run ruff check`;
  `uv run mypy app`.

## 8. Decisões resolvidas (do brainstorming)

1. Escopo por `sub`, gravando `org_id` na linha desde já (sem filtrar por ele agora).
2. Dados existentes: **apagados** na migration (eram testes).
3. Escopo da entrega: portfolios + positions + rebalance (transitivo) + screens/screen_filters
   + proteger a rota screener.
4. Multi-tenancy via filtragem na aplicação (abordagem A); RLS anotado como hardening futuro.
5. Acesso cross-user → **404** (não 403), para não vazar existência.
6. Unicidade de `name` passa a ser por dono: `UNIQUE (owner_sub, name)`.

## 9. Arquivos tocados (resumo)

| Arquivo | Ação |
|---|---|
| `backend/alembic/versions/0013_portfolio_screen_owner_isolation.py` | Criar |
| `backend/app/models/portfolio.py` | `Portfolio`: +`owner_sub`/`org_id`, unique composta, index |
| `backend/app/models/screen.py` | `Screen`: +`owner_sub`/`org_id`, unique composta, index |
| `backend/app/services/portfolio_crud.py` | Threading de `owner_sub` em todas as funções |
| `backend/app/services/screener.py` | Threading de `owner_sub` nas funções de saved screen |
| `backend/app/services/builder_save.py` | Carimbar `owner_sub`/`org_id` no save |
| `backend/app/api/routes/portfolios.py` | Capturar `user`, repassar `user.sub` |
| `backend/app/api/routes/rebalance.py` | Verificar dono do portfolio-pai |
| `backend/app/api/routes/builder.py` | `/save` repassa `user.sub`/`org_id` |
| `backend/app/api/routes/screener.py` | Split público/protegido; `_screen_or_404` owner-scoped |
| `backend/tests/...` | Overrides + testes de isolamento + service |
