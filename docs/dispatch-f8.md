# Dispatch F8 — Portfolio Builder fund-aware com forward-looking Black-Litterman

**Data:** 2026-06-11 · **Status:** aprovado pelo dono (re-escopo sobre o §3.7 original) ·
**Pré-requisitos:** F0–F7 concluídas (último commit relevante `5cc7297`).

Base de evidência (ler antes de implementar):
- `docs/research/2026-06-11-mother-db-funds-inventory.md` — o que existe de fundos no DB-mãe.
- `docs/research/2026-06-11-f8-optimizer-black-litterman.md` — validação do otimizador + BL
  (forma fechada local 7/7 checks + backtest QC plataforma, projeto 32779505).

## §1 Motivação do re-escopo

O plano original (equities-only, CVaR computado de 2y de preços Tiingo) ignorava o ativo mais
rico do DB-mãe: ~9 mil fundos com identidade completa, 1,02M linhas de métricas de risco
precomputadas (até 2026-06-09), 27,4M de NAVs diários (1970→2026-06-05) e 2,23M holdings
N-PORT. As tabelas de APLICAÇÃO do builder no DB-mãe estão vazias (o "builder quebrado") —
o Light reconstrói essa camada do zero. O cliente teve prometido um builder com visão
forward-looking: entra como camada Black-Litterman sobre o motor CVXPY (validada).

## §2 Escopo / não-escopo

**Entra:** sync read-only de fundos → universo de fundos navegável → motor de otimização
CVXPY → camada BL de views → UI do builder no cockpit (design F7) → overlap N-PORT.
**Não entra:** escrita no DB-mãe (NUNCA); look-through completo de holdings (N-PORT é top-50);
Entropy Pooling (registrado como evolução, F9+); ratings de terceiros (lipper vazia);
streaming (F9). UCITS/ESMA: identidade sincronizada, mas universo v1 = fundos SEC com NAV.

## §3 Tarefas por sub-fase

### F8.1 — Sync de fundos (`app/sync/funds.py`, padrão F6)
1. Migration: tabelas locais `funds` (identidade+classificação+fees), `fund_risk_latest`
   (snapshot do último calc_date por fundo), `fund_nav` (janela rolante de NAV diário),
   `fund_holdings` (N-PORT último report por série, com `pct_of_nav` e flag top-50).
2. Critério de inclusão v1: instrumento em `instrument_identity` com sec_series_id, NAV ≥ 2
   anos em `nav_timeseries`, presença no último calc de `fund_risk_metrics`. Estimativa:
   ~5–7 mil fundos. Classificação: `strategy_label` com fallback em cascata
   (sec_registered_funds → sec_etfs → reclassification stage → 'Unclassified').
3. Script CLI resumível `scripts/sync_funds.py` (mesma ergonomia do backfill F6: fresh-skip,
   métricas de progresso, uma conexão read-only por run, DSN nunca logado).
4. Campos de staleness (`synced_at`, `source_calc_date`, `source_nav_max_date`) expostos na API.

### F8.2 — Universo de fundos no Light
1. Endpoints: `GET /funds` (filtros: strategy_label, asset_class é derivado, fund_type
   ETF/MF/MMF, expense_ratio ≤, AUM ≥, métricas de risco com operadores — reuso do padrão do
   screener F6), `GET /funds/{id}` (perfil: identidade, fees, métricas, NAV sparkline,
   top holdings), paginação + CSV como no screener.
2. UI: tela **Funds** no cockpit (sidebar ganha 5º item) — tabela densa Carbon (design F7),
   colunas configuráveis de métricas precomputadas, peer percentile como barra inline,
   badge elite_flag. SEM recomputar métricas no Light: exibir as do DB-mãe com data-fonte.

### F8.3 — Motor de otimização (`app/optimizer/`)
1. `uv add cvxpy scikit-learn`.
2. Inputs: lista de ativos (fundos via `fund_nav` e/ou equities via `eod_prices`), janela
   (default 2y), constraints (long-only, cap default 25%, min opcional, soma=1).
3. Σ: Ledoit-Wolf (sklearn) sobre retornos diários alinhados (interseção de datas; mínimo
   400 obs comuns ou 422).
4. Objetivos: `equal_weight`, `min_vol`, `erc`, `max_diversification`,
   `min_cvar` (default; Rockafellar–Uryasev α=0.95 sobre cenários históricos).
5. μ NUNCA estimado de série histórica (anti-pattern guard do plano original mantido):
   sem views ⇒ problemas μ-free; com views ⇒ μ só via posterior BL (F8.4).

### F8.4 — Camada Black-Litterman (`app/optimizer/black_litterman.py`)
1. Equilíbrio: `π = δ·Σ·w_mkt`, com **w_mkt por AUM real** (fundos: AUM do sync; equities:
   market cap do fundamentals F6; mistura: normalizar no universo do problema). δ=2.5, τ=0.05.
2. Views: absolutas (`asset retorna q% a.a.`) e relativas (`X − Y = q%`), cada uma com
   confiança ∈ (0,1] (Idzorek → Ω; default Ω = diag(P·τΣ·Pᵀ)).
3. Validações fail-loud: posto de P (views dependentes ⇒ 422 com mensagem), Ω singular ⇒ 422,
   ativos da view fora do universo ⇒ 422.
4. Aplicação: max-utility (μ_BL, Σ_BL) como objetivo opcional `bl_utility`; e re-centering de
   cenários (`scen + (μ_BL − μ_hist)/252`) para o `min_cvar` com views — default do produto.

### F8.5 — UI Builder no cockpit
1. Fluxo: selecionar base (portfólio salvo OU resultado do screener de fundos OU tickers
   ad-hoc) → constraints → objetivo → views BL (builder de views com 2 formas + slider de
   confiança) → **Suggest weights**.
2. Resultado: comparação atual-vs-proposta — pesos lado a lado (tabela densa + donuts),
   métricas in-sample pelo MESMO engine F3 (CVaR 95, vol, retorno, max DD), delta destacado;
   overlap de holdings N-PORT entre fundos propostos (com disclaimer top-50).
3. Ações: salvar proposta como novo portfólio; exportar CSV. Estados vazio/erro/loading no
   padrão F7 (fail-loud com detail verbatim).

## §4 Gates (todos obrigatórios antes do commit de fechamento da fase)

**G1 — Sync (padrão F6):** 5/5 fundos sorteados conferidos contra o DB-mãe NA FONTE (valores
de risk metrics, NAV e holdings batem); contagens e staleness plausíveis; re-run é idempotente.
**G2 — Otimizador analítico:** 2 ativos iid ⇒ 50/50; vol 1:2 não correlacionados ⇒ min-vol
~4/5–1/5 (forma fechada); ERC com Σ diagonal ⇒ pesos ∝ 1/σ; solver `optimal` em todos; pesos
somam 1 (1e-6); caps respeitados.
**G3 — CVaR:** proposta min-CVaR tem CVaR 95 in-sample ≤ carteira atual, avaliado pelo MESMO
engine F3 (replay), nos 3 portfólios de teste.
**G4 — Ledoit-Wolf:** shrinkage do app == sklearn de referência (atol 1e-10) em fixture.
**G5 — Anti-μ guard:** grep/teste estrutural garantindo que nenhum objetivo consome média
histórica de retornos fora do caminho BL.
**G6 — BL:** (i) zero views ⇒ pesos ≈ w_mkt (tolerância documentada); (ii) view absoluta
bullish em X eleva μ_X e peso de X vs baseline; (iii) view relativa tilta o spread; (iv) P
deficiente em posto ⇒ 422; (v) confiança→Ω monotônica (mais confiança ⇒ mais tilt).
**G7 — Live gate:** fluxo completo vivo no browser (Playwright): screener de fundos → builder
→ views → proposta → salvar como portfólio → abrir no /portfolio.

## §5 Decisões de produto (defaults propostos — dono pode vetar no PR)

δ=2.5 · τ=0.05 · cap=25% · α CVaR=0.95 · janela=2y · piso de retorno no min-CVaR com views =
retorno de equilíbrio do universo (π·w_mkt) · universo v1 = fundos SEC (critério F8.1-2).

## §6 Convenções de execução (herdadas)

Subagent-driven (implementador → spec review → quality review → fix), live gates por sub-fase,
commits atômicos `F8: ...` + Co-Authored-By, DB-mãe SÓ leitura SÓ via app/sync, limiter Tiingo
single-process (sync de fundos NÃO toca Tiingo — só DB-mãe), make check verde por commit.

## §7 Riscos conhecidos

- `strategy_label` nulo em ~62% dos registered funds → cascata de classificação + bucket
  'Unclassified' visível (não esconder).
- N-PORT top-50 → overlap é aproximação; disclaimer fixo na UI.
- Volume do sync NAV (27M linhas na fonte) → janela rolante (2y default) e batch por
  instrument_id; NUNCA `SELECT *` sem janela.
- MMFs têm NAV estável → excluir de min-vol/ERC por default? Decisão: incluir, mas o builder
  avisa quando >50% do universo tem vol < 1% a.a. (proposta degenerada).
