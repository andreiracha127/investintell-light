# Builder objective redesign — onda 0 (max retorno sob teto de CVaR)

- Data: 2026-06-17
- Status: design aprovado nas decisões-chave, aguardando revisão do spec
- Escopo: mudar a tese do Builder de "minimize risco de cauda" (`min_cvar`) para "maximize retorno sob um teto de CVaR controlado pelo usuário" (`max_return_cvar`), tornando esse objetivo utilizável sem views.
- Precede a onda 1 (abas de resultado), que passa a refletir este objetivo.

## Contexto e problema

`min_cvar` (default atual) não tem termo de retorno: minimiza pura perda de cauda, então o solver foge para o canto mais conservador do espaço (cash/renda fixa curta). Como objetivo único e default, estrutura o produto inteiro em torno de "perca o mínimo" em vez de "ganhe o máximo dentro do risco tolerado".

O objetivo que inverte isso existe (`max_return_cvar`: maximiza `μᵀw` s.t. `CVaR_α(w) ≤ cvar_limit`), mas hoje exige views: o `μ` é o posterior de Black-Litterman, e sem views o builder falha de propósito ([portfolio_builder.py:572](../../../backend/app/services/portfolio_builder.py#L572)) por causa do Gate G5 (nunca maximizar média histórica). Logo, não dá para só trocar o default — todo optimize sem views quebraria.

## Decisões

1. Fonte do `μ` sem views: **retorno de equilíbrio** π = δ·Σ·w_mkt (reverse optimization do BL). Não precisa de views, não é média histórica (respeita G5). Quando o usuário fornece views, segue usando o posterior (refina π), como hoje.
2. Controle de risco: **mandate (preset) + teto de CVaR explícito ajustável**. O mandate (conservative→growth) pré-preenche um `cvar_limit` sugerido; o usuário ajusta o teto quando quiser.

### Nota metodológica: o δ não move a carteira neste objetivo

`max_return_cvar` maximiza `πᵀw`, um objetivo **linear**. Escalar π por uma constante positiva (o δ) não muda o argmax sobre o conjunto convexo de restrições. Como π = δ·Σ·w_mkt, o δ só escala a magnitude — a **direção** (Σ·w_mkt) é o que define a solução. Portanto, neste objetivo, o δ do mandate é irrelevante para a carteira resultante; quem morde é o `cvar_limit`. O mandate continua relevante para outros objetivos (`bl_utility`) e para o equilibrium como floor no `min_cvar`. Consequência de design: no caminho primário, o mandate é essencialmente um **preset de `cvar_limit`** (a alavanca de risco real), não de agressividade via δ.

## Objetivo da onda 0

1. Backend: `max_return_cvar` usa o equilibrium return π quando não há views (e o posterior quando há), respeitando G5.
2. Backend: nova ladder `mandate → cvar_limit` (paralela à `MANDATE_DELTA`), pré-preenchendo o teto sugerido.
3. Backend: suportar ações no equilibrium via market cap (dados já existentes), removendo a rejeição de equities em `_market_weights_for`.
4. Frontend: `max_return_cvar` vira o objetivo primário/default, com seletor de mandate + input de teto de CVaR (pré-preenchido, ajustável), e exibição do teto efetivo após o ajuste de regime.

(A habilitação do `max_return_cvar` no walk-forward foi movida para a onda 1, junto com a aba Backtest — o `solve_fn` do backtest é um closure sem acesso aos AUMs, então o `w_mkt` por fold é resolvido lá.)

## Não-objetivos

Não remover os demais objetivos (`min_cvar`, `min_vol`, `erc`, `max_diversification`, `equal_weight`, `bl_utility`) — continuam disponíveis como alternativas; só deixam de ser o default. Não recalibrar o regime detector. Não alterar a matemática de CVaR/covariância.

## Backend

### `max_return_cvar` sem views (equilibrium)

Em [portfolio_builder.py](../../../backend/app/services/portfolio_builder.py) `run_optimize`, na ramificação `max_return_cvar`:

- Hoje: exige `mu_posterior`; falha se `None`.
- Novo: `mu = mu_posterior if views else mu_equilibrium`. O `mu_equilibrium` (π) já é computado quando o BL está ativo; passa a ser computado sempre que o objetivo for `max_return_cvar`. Ambos são G5-safe.
- `solve_max_return_cvar_capped(scenarios, mu, cvar_limit, ...)` ([engine.py:738](../../../backend/app/optimizer/engine.py#L738)) fica inalterado — só muda quem fornece `mu`.

O equilibrium precisa de `w_mkt`. Hoje `_market_weights_for` deriva de AUM e **rejeita ações**. Decisão: suportar ações via market cap (`shares_outstanding` de `fundamentals_snapshot` × `adj_close` de `eod_prices` — dados já existentes, mesma fórmula do screener), concatenado aos AUMs dos fundos e passado a `bl.market_weights()` (agnóstico a fundo/ação). Fail-loud quando uma ação não tem `shares_outstanding`. Sem nova ingestão. Novo loader `load_equity_market_cap`, espelhando `load_fund_aum`.

### Ladder `mandate → cvar_limit`

Nova tabela em [mandate.py](../../../backend/app/optimizer/mandate.py), espelhando `MANDATE_DELTA`, que resolve um `cvar_limit` sugerido por mandate (override explícito do usuário sempre vence). Valores iniciais (CVaR 95 diário, fração decimal) a **calibrar** com as distribuições históricas de CVaR de carteiras típicas — ponto de partida: conservative/defensive ≈ 0.010, moderate/balanced ≈ 0.020, aggressive ≈ 0.030, growth ≈ 0.035. Resolver via uma função análoga a `resolve_delta` (prioridade: override explícito > ladder do mandate > default).

### Regime tightening (manter, expor)

`apply_regime_cvar_limit` continua apertando o teto sob `risk_off` (×`DEFAULT_RISK_OFF_CVAR_FACTOR` = 0.5). Hoje isso é silencioso. A resposta do optimize deve carregar o **teto efetivo** aplicado (e o estado de regime), para o frontend exibir "teto 2.0% → efetivo 1.0% (regime risk-off)". Adicionar esses campos ao `DiagnosticsOut` (ou a um bloco próprio).

### Suporte a ações no equilibrium (market cap)

`_market_weights_for` ([portfolio_builder.py:173](../../../backend/app/services/portfolio_builder.py#L173)) hoje rejeita ações. Novo: para cada ativo, AUM (fundo) ou market cap (ação) na ordem de `labels`; um novo loader `load_equity_market_cap(session, tickers)` em `optimizer/data.py` computa `shares_outstanding` (mais recente de `fundamentals_snapshot`) × `adj_close` (mais recente de `eod_prices`). Concatenar e passar a `bl.market_weights()`. Fail-loud quando uma ação não tem `shares_outstanding`/preço, com mensagem clara.

### Walk-forward com `max_return_cvar` — movido para a onda 1

A habilitação do walk-forward para `max_return_cvar` (modo equilibrium) vive na onda 1, onde a aba Backtest é construída: o `solve_fn` do backtest é um closure que só recebe a matriz de retornos do fold, sem acesso aos AUMs para computar `w_mkt`. Resolver isso (passar `w_mkt` para o closure + decidir a fonte por fold) é trabalho da aba.

### Broad universe

Hoje `max_return_cvar` bloqueia `broad_universe`. A onda 0 mantém o comportamento do broad inalterado (objetivos de covariância sobre o universo amplo); o caminho primário max-retorno aplica-se aos modos cesta/ranked. Reavaliar broad em onda futura.

## Frontend

No card "Constraints & objective" de [BuilderView.tsx](../../../frontend/src/components/builder/BuilderView.tsx) e no seletor de objetivo ([assets.ts](../../../frontend/src/components/builder/assets.ts)):

- `max_return_cvar` passa a ser o objetivo default, rotulado de forma legível (ex.: "Maximizar retorno sob teto de CVaR"). Os demais objetivos permanecem na lista como alternativas.
- Seletor de **mandate** (conservative→growth) como controle primário de apetite. Selecionar um mandate pré-preenche o `cvar_limit` sugerido (via a nova ladder) e o δ (para os objetivos que o usam).
- Input de **teto de CVaR** (CVaR 95 diário, em %), pré-preenchido pelo mandate e editável a cada run. Validação: obrigatório quando o objetivo é `max_return_cvar`.
- Exibir o **teto efetivo** após o ajuste de regime, lendo os campos novos da resposta (transparência sobre o aperto silencioso).
- Os controles avançados de views (ViewsCard) permanecem opcionais; quando preenchidos, refinam π para o posterior.

## Fluxo

1. Usuário escolhe um mandate (ou aceita o default) → UI pré-preenche teto de CVaR + δ.
2. (Opcional) ajusta o teto explicitamente; (opcional) adiciona views.
3. Roda o optimize com `objective="max_return_cvar"`, `cvar_limit`, `mandate`.
4. Backend resolve `μ` = equilibrium (ou posterior se views), aplica o teto efetivo (regime), maximiza `πᵀw` s.t. CVaR ≤ teto efetivo.
5. Resposta inclui o teto efetivo + estado de regime; o frontend os exibe.

## Erro e edge cases (fail-loud)

- `cvar_limit` ausente com `max_return_cvar` → 422 (já no schema).
- `w_mkt` não computável (sem AUM/market cap) → 422 com mensagem clara.
- Teto efetivo infeasível dado as restrições (cap/min_weight) → status não-`optimal` → 422 verbatim, como hoje.

## Testes

- `solve_max_return_cvar_capped` invariante a escala de `μ` (δ não muda o argmax) — teste explícito da nota metodológica.
- `run_optimize` com `max_return_cvar` sem views usa o equilibrium e produz carteira mais agressiva que `min_cvar` no mesmo universo (teste de comportamento: retorno esperado maior, CVaR no teto).
- Ladder `mandate → cvar_limit` e precedência do override explícito.
- Teto efetivo sob `risk_off` = teto × 0.5, exposto na resposta.
- Walk-forward aceita `max_return_cvar` (equilibrium) e rejeita o caminho de views.
- Frontend: default do objetivo, pré-preenchimento via mandate, override do teto, exibição do teto efetivo.

## Arquivos afetados

Backend: `app/services/portfolio_builder.py`, `app/optimizer/mandate.py`, `app/schemas/builder.py` (campos de teto efetivo/regime na resposta), `app/services/backtest.py` (aceitar max_return_cvar), testes correspondentes. (`app/optimizer/engine.py` `solve_max_return_cvar_capped` permanece inalterado.)

Frontend: `components/builder/BuilderView.tsx`, `components/builder/assets.ts` (lista/labels de objetivo), o card de constraints/objetivo (seletor de mandate + input de teto + teto efetivo), `lib/api/api.d.ts` (regenerado), testes.

## Dependência com a onda 1 (abas)

A onda 1 (Risco/Backtest/Projeção) passa a montar os requests com o objetivo efetivamente usado. O fallback de objetivo do backtest descrito naquele spec muda: com o backtest aceitando `max_return_cvar` (equilibrium), a aba Backtest não precisa mais rebaixar para `min_cvar` quando o usuário usou o objetivo primário — só rebaixa/avisa no caminho de views.
