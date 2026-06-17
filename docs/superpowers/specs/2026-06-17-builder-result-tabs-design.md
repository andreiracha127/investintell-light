# Builder result tabs — onda 1 (Risco + Backtest + Projeção)

- Data: 2026-06-17
- Status: design aprovado nas decisões-chave, aguardando revisão do spec
- Escopo: transformar o resultado do Builder em um workspace com abas e expor três capacidades quant já implementadas — decomposição de risco, walk-forward out-of-sample e projeção Monte Carlo da carteira.
- Depende da onda 0 ([builder-objective-redesign](2026-06-17-builder-objective-redesign-design.md)): o objetivo primário passa a ser `max_return_cvar` (equilibrium), o que torna o backtest coerente sem precisar rebaixar para `min_cvar`.

## Contexto e problema

O Builder roda o Optimizer (`POST /builder/optimize`) e o [ResultsPanel](../../../frontend/src/components/builder/ResultsPanel.tsx) mostra um resultado estático: KPI tiles (vol, CVaR 95, retorno BL, n_obs, status), tabela de pesos, donuts atual vs proposto e diagnósticos colapsáveis (μ do BL, seleção broad). Depois disso o sistema emudece.

A migração quant trouxe um conjunto de serviços testados e com endpoint que o Builder nunca chama: backtest walk-forward, Monte Carlo, look-through/overlap, factor attribution, decomposição de risco. O frontend ainda tem ~13 chart builders Highcharts em `frontend/src/lib/charts/hc/` dos quais o Builder usa só `allocation`. O gap é de wiring, não de capacidade.

Esta onda entrega o padrão de abas e três capacidades cujo core já existe e é reutilizável.

## Objetivo da onda 1

1. Esqueleto de abas no `ResultsPanel`: `Alocação` (conteúdo atual) · `Risco` · `Backtest` · `Projeção`.
2. Aba Risco sobre a carteira recém-otimizada via `POST /portfolio/analysis`.
3. Aba Backtest sobre a carteira recém-otimizada via `POST /backtest/walk-forward`, incluindo a curva de equity out-of-sample (exige extensão pequena de backend).
4. Aba Projeção forward (Monte Carlo) sobre o NAV sintético da carteira, via novo endpoint `POST /monte-carlo/portfolio` que reusa `block_bootstrap_monte_carlo` (puro) e `load_aligned_returns` (o loader do backtest/optimizer).

## Não-objetivos (ondas futuras)

Overlap/look-through sobre pesos ad-hoc, Exposição a fatores agregada e Fronteira eficiente ficam para ondas posteriores. Não mexer no fluxo de inputs do Builder nem na lógica do solver. Não alterar o endpoint single-instrument `POST /monte-carlo/projection` existente.

## Arquitetura

### Esqueleto de abas

Replicar o padrão já existente em [FundProfileView.tsx:80](../../../frontend/src/components/funds/FundProfileView.tsx#L80): um `type ResultTabId = "allocation" | "risk" | "backtest" | "projection"`, um array `TABS`, `useState`, botões com `role="tab"`/`aria-selected` e render condicional. Reusar as mesmas classes de botão de tab desse arquivo para consistência visual. Não introduzir um componente Tabs genérico (não existe um hoje; seguir a convenção do repo).

Cada aba é um componente isolado com uma responsabilidade:

- `AllocationTab` — recebe o conteúdo que hoje vive no `ResultsPanel` (KPIs, pesos, donuts, diagnósticos). Refactor de extração, sem mudança de comportamento.
- `RiskTab` — recebe o `OptimizeResponse` e dispara `POST /portfolio/analysis`.
- `BacktestTab` — recebe o `OptimizeResponse` (+ objetivo/constraints usados) e dispara `POST /backtest/walk-forward`.
- `ProjectionTab` — recebe o `OptimizeResponse` (+ objetivo/constraints) e dispara `POST /monte-carlo/portfolio`.

### Fetch on-demand + cache

As abas Risco, Backtest e Projeção disparam chamadas caras (o backtest re-otimiza N folds; o MC roda 10k paths). Política:

- A aba só dispara o fetch quando aberta pela primeira vez (lazy).
- O resultado fica em cache enquanto o `OptimizeResponse` corrente não muda; ao rodar uma nova otimização, o cache das abas é invalidado (reset de estado).
- Implementação via `useMutation` do TanStack Query (mesmo padrão de `postBuilderOptimize`), uma mutation por aba, disparada no primeiro mount/abertura. Estado de loading/erro por aba.

## Aba Risco

### Request

`POST /portfolio/analysis` aceita posições ad-hoc com pesos (sem persistência). Montar:

- `mode = "weights"`
- `positions = [{ ticker, weight }]` a partir de cada `WeightOut` do resultado.
- `benchmark = "SPY"` (default; futuramente configurável).
- `range = "1Y"` (default).

Ressalva de identificadores: `/portfolio/analysis` indexa por `ticker`, não por UUID de fundo. Usar `WeightOut.ticker` (resolvido para fundos de universo) e `asset.ticker` para equities. Se algum peso não tiver ticker resolvível, **falar alto** na aba ("não foi possível resolver o ticker de N posições; abra como portfólio salvo") em vez de silenciar ou enviar request inválido.

### Resposta → UI

A resposta já traz tudo computado. Render:

- KPI tiles a partir de `stats`: vol anual, Sharpe, Sortino, CVaR 95, max drawdown (depth), diversification ratio, information ratio, beta vs benchmark. Reusar o componente `KpiTile`.
- Contribuição de risco por ativo (barras) via `buildHcRiskContributionsOption(risk_contributions)` — input `[{ ticker, contribution }]`.
- Matriz de correlação (heatmap) via `buildHcHeatmapOption(correlation_matrix)` — input `{ tickers, matrix }`.
- Curva acumulada carteira vs benchmark via `buildHcCumulativeOption(...)` usando `benchmark_comparison.portfolio` e `benchmark_comparison.benchmark`. Ganho de brinde (o response já entrega as séries).

Todos via o wrapper [HighchartsChart](../../../frontend/src/components/charts/HighchartsChart.tsx) (`options`, `className="h-[...]"`, `isEmpty`, `emptyMessage`).

## Aba Backtest

### Request

`POST /backtest/walk-forward` aceita a lista de ativos (mesmo tipo `AssetRefIn` da otimização) e re-otimiza por fold. Montar:

- `assets = result.weights.map(w => w.asset)`.
- `objective` = o objetivo usado na otimização **se** for mu-free e aceito pelo backtest; caso contrário (views presentes, `bl_utility`, ou objetivo não aceito) cair para `min_cvar` e exibir aviso visível na aba ("backtest roda sem views — Gate G5; objetivo ajustado para min_cvar").
- `constraints` = as constraints usadas na otimização.
- Demais knobs nos defaults do endpoint (`n_splits=5`, `gap=2`, `test_size=63`, `cost_bps=10`).

Nunca enviar views (proibido por design no OOS).

### Resposta → UI

Render:

- KPI tiles: Sharpe médio, folds positivos `positive_folds / n_splits_computed`, turnover médio, desvio do Sharpe.
- Tabela por fold (`folds[]`): fold, train_size, sharpe, cvar_95, max_drawdown, turnover, net_return. Reusar o padrão de tabela do `ResultsPanel`.
- Gráfico de colunas por fold (Sharpe ou retorno líquido por fold) — novo builder `buildHcFoldMetricsOption` (colunas verticais; não há reuso direto).
- Curva de equity OOS (ver extensão de backend) via builder de linha simples (`nav.ts`), com `plotLines` marcando os limites entre folds (pontos de re-otimização).

Rótulo honesto fixo na aba: validação do *processo* de otimização fora da amostra (re-otimiza por fold), não replay da carteira exata.

## Aba Projeção forward (Monte Carlo)

### Request

Novo endpoint `POST /monte-carlo/portfolio`. Montar a partir do resultado:

- `positions = [{ asset, weight }]` a partir de cada `WeightOut` (asset = `AssetRefIn`, o tipo que `load_aligned_returns` consome — não depende de ticker, então cobre também fundos sem ticker).
- `statistic` ∈ {`return`, `max_drawdown`, `sharpe`} — controlado por um seletor na aba; default `return`.
- `n_simulations`, `horizons`, `risk_free_rate`, `seed`, `window_days` nos defaults (10k simulações; horizontes 1/3/5/7/10Y).

### Resposta → UI

Reusa a estrutura do `MonteCarloResponse` (percentis, `confidence_bars`, `historical_percentile_rank`, `degraded`/`degraded_reason`). Render:

- Seletor de estatística (return / max drawdown / sharpe) — segmentado; troca dispara novo fetch (mesma carteira).
- Cone de confiança via novo builder `buildHcConeOption(confidence_bars, statistic, colors)`: bandas `arearange` (5–95, 10–90, 25–75) + linha mediana (50) ao longo dos horizontes. Novo arquivo `lib/charts/hc/cone.ts`.
- Resumo: no horizonte mais longo, a mediana e a faixa 5–95; mais o `historical_percentile_rank` (onde o histórico da carteira cai na distribuição simulada).
- Estado `degraded`: exibir `degraded_reason` quando presente.

Nota honesta fixa: projeção block-bootstrap (blocos de 21 dias, preserva autocorrelação) a partir do histórico comum da carteira proposta, com os pesos-alvo mantidos; é uma distribuição de cenários, não uma garantia.

## Extensão de backend: curva de equity OOS (Backtest)

O NAV out-of-sample por fold **já é computado** em [backtest.py:167](../../../backend/app/analytics/backtest.py#L167) (`nav = (1.0 + net_series).cumprod()`), hoje só usado para o max drawdown. Plano:

1. `app/analytics/backtest.py`: acumular o `net_series` (datas + retorno líquido diário) de cada fold; após o loop, concatenar na ordem temporal e calcular o NAV encadeado global `(1 + concat).cumprod()`. Adicionar ao `WalkForwardResult` um campo `oos_curve: list[tuple[date, float]]` e `fold_boundaries: list[date]` (primeira data de cada fold, para os plotLines). O encadeamento já reflete os custos de rebalanceamento (cobrados em `net_daily[0]`).
2. `app/schemas/backtest.py`: adicionar `oos_curve: list[SeriesPoint]` e `fold_boundaries: list[date]` ao `WalkForwardResponse`. Manter o contrato de fração decimal.
3. `app/services/backtest.py`: mapear os novos campos do result para o response.
4. Testes: estender `tests/test_backtest_analytics.py` (a curva tem comprimento = soma dos n_obs dos folds; datas estritamente crescentes no tempo; fator de crescimento final do NAV encadeado = produto de `(1 + net_return)` por fold; primeira data = início do primeiro test fold) e `test_backtest_route.py`/`test_backtest_schema.py` (campos presentes e bem-formados).

Sem mudança de comportamento nas métricas existentes — apenas exposição de uma série já calculada.

## Novo endpoint de backend: Monte Carlo de carteira

Reaproveita o core puro e o loader compartilhado; quase todo o trabalho é orquestração (espelha o que `app/services/backtest.py` já faz).

1. `app/services/monte_carlo.py`: nova `run_portfolio_monte_carlo(session, payload)` que (a) converte `positions` em `AssetRef` (reusar `_to_data_ref`), (b) chama `load_aligned_returns(session, assets, window_days)` → `frame`, (c) monta o vetor de pesos **alinhado às colunas** do `frame` (chave `fund:{id}`/`equity:{ticker}`), (d) calcula `portfolio_returns = frame @ w` → série, (e) chama uma nova `assemble_portfolio_monte_carlo(portfolio_returns.to_numpy(), ...)`. A `assemble_portfolio_monte_carlo` é análoga à `assemble_monte_carlo` existente, sem o param `ticker`.
2. `app/schemas/monte_carlo.py`: novo `PortfolioMonteCarloRequest` (`positions: list[{asset, weight}]`, `statistic`, `n_simulations`, `horizons`, `risk_free_rate`, `seed`, `window_days`) e `PortfolioMonteCarloResponse` reusando `ConfidenceBar` e os campos de distribuição; `params` próprio (sem ticker; inclui `n_assets`).
3. `app/api/routes/monte_carlo.py`: novo `POST /monte-carlo/portfolio` (thin route, mapeia `ValueError` → 422 verbatim). O endpoint single-instrument `/projection` fica intacto.
4. Premissa explícita (documentada no docstring e na UI): pesos-alvo mantidos (rebalanceamento implícito), consistente com a decomposição de risco da aba Risco. Herda os gates de dados do loader (`MIN_COMMON_OBS = 400`) e do MC (`_MIN_HISTORY = 42`); falha alto quando insuficiente.
5. Testes: `tests/test_monte_carlo_service.py` (série sintética = `frame @ w`; pesos desalinhados/erro; gate de obs; passa por `block_bootstrap_monte_carlo`), `test_monte_carlo_route.py` (endpoint portfolio: shape do response, 422 em histórico insuficiente), `test_monte_carlo_schema.py`.

`block_bootstrap_monte_carlo` e `load_aligned_returns` ficam **inalterados** — reuso puro.

## Frontend: client e tipos

- `frontend/src/lib/api/client.ts`: `PortfolioAnalysisRequest`/`PortfolioAnalysis` já tipados. Confirmar/adicionar `postPortfolioAnalysis`. Adicionar exportação de tipos `WalkForwardRequest`/`WalkForwardResponse` (já em `api.d.ts`) e a função `postBacktestWalkForward`; adicionar tipos e função `postPortfolioMonteCarlo` após a extensão de backend. Tudo no estilo de `postBuilderOptimize` (helper `request<T>`).
- Após as extensões de backend (curva OOS + endpoint de portfolio MC), regenerar `api.d.ts` a partir do OpenAPI.

## Fluxo de dados

1. Usuário roda a otimização (inalterado). `BuilderView` mantém `OptimizeResponse`.
2. `ResultsPanel` renderiza as abas; `Alocação` ativa por default.
3. Ao abrir `Risco`: monta o request a partir dos pesos → `postPortfolioAnalysis` → skeleton → render.
4. Ao abrir `Backtest`: monta o request a partir dos ativos/objetivo → `postBacktestWalkForward` → skeleton → render.
5. Ao abrir `Projeção`: monta o request a partir das posições → `postPortfolioMonteCarlo` → skeleton → render; trocar a estatística refaz o fetch.
6. Nova otimização reseta os caches das abas.

## Erro e loading

Reusar `ResultsSkeleton` e `ErrorPanel` já existentes, por aba. Erros de domínio (422) do backend são exibidos com a mensagem verbatim (fail-loud): ticker não resolvido (Risco), histórico insuficiente para os folds (Backtest), histórico comum insuficiente (Projeção).

## Testes

- Backend: cobertura da curva OOS (backtest) e do endpoint de portfolio MC (analytics/service/schema/route), conforme as seções acima.
- Frontend: testes de componente para `RiskTab`, `BacktestTab` e `ProjectionTab` (estados loading/erro/sucesso com fixtures; troca de estatística na Projeção), e teste do esqueleto de abas (troca de aba, lazy fetch dispara uma vez, reset ao mudar o resultado). Seguir o setup de teste já usado nos componentes do Builder.

## Arquivos afetados

Backend: `app/analytics/backtest.py`, `app/schemas/backtest.py`, `app/services/backtest.py`, `app/services/monte_carlo.py`, `app/schemas/monte_carlo.py`, `app/api/routes/monte_carlo.py`, testes correspondentes. (`app/analytics/monte_carlo.py` e `app/optimizer/data.py` permanecem inalterados.)

Frontend: `components/builder/ResultsPanel.tsx` (esqueleto + extração), novos `components/builder/AllocationTab.tsx`, `RiskTab.tsx`, `BacktestTab.tsx`, `ProjectionTab.tsx`, `lib/api/client.ts` (funções/tipos), novos `lib/charts/hc/foldMetrics.ts` e `lib/charts/hc/cone.ts`, `lib/api/api.d.ts` (regenerado), testes.

## Ondas futuras (contexto, fora de escopo)

Overlap/look-through (precisa aceitar pesos ad-hoc no endpoint), Exposição a fatores (agregação ponderada da atribuição por fundo) e Fronteira eficiente (novo endpoint de varredura de CVaR). Cada uma entra como uma aba isolada adicional, reusando o esqueleto desta onda.
