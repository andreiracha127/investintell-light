# Quant Port -- Execution Plan Overview (Tiers 1-3)

> **For agentic workers:** este e o indice mestre. Os planos executaveis task-a-task estao nos tres arquivos de tier. REQUIRED SUB-SKILL para executar: `superpowers:subagent-driven-development` (recomendado) ou `superpowers:executing-plans`.

**Origem:** review comparativo entre o engine quant legado (`E:/investintell-allocation/backend/quant_engine`, 47 servicos / ~17k LOC) e o `investintell-light`. Conclusao do review: o **nucleo do light e igual ou superior** (Ledoit-Wolf, min-CVaR Rockafellar-Uryasev, ERC, max-diversification, Black-Litterman Idzorek, IPCA em producao no worker, detector vote2of3). O que falta -- e o que estes planos portam -- e majoritariamente **fiacao de ultima milha ou ports de ~30 linhas em numpy sobre dados que o light ja calcula**.

**Total:** 46 capacidades, 18 clusters, 88 tasks TDD.

---

## Arquivos deste plano

- **`2026-06-14-quant-port-tier1.md`** -- Tier 1 (vitorias baratas; 24 tasks).

- **`2026-06-14-quant-port-tier2.md`** -- Tier 2 (nucleo institucional; 33 tasks).

- **`2026-06-14-quant-port-tier3.md`** -- Tier 3 (fact-sheet / sistemico / avancado; 31 tasks).

---

## Mapa de cobertura (rank -> capacidade -> cluster -> arquivo)

| # | Capacidade | Cluster | Tier / arquivo |
|---|---|---|---|
| 1 | Sharpe/Sortino/IR online | T1A | T1 (`2026-06-14-quant-port-tier1.md`) |
| 2 | Effective Number of Bets (entropia) | T1A | T1 (`2026-06-14-quant-port-tier1.md`) |
| 3 | Active Share | T1A | T1 (`2026-06-14-quant-port-tier1.md`) |
| 4 | Metricas de regressao RF/alternativos (duracao empirica, credit/inflation beta, crisis alpha) | T1B | T1 (`2026-06-14-quant-port-tier1.md`) |
| 5 | CVaR in-sample -> estimador RU exato | T1C | T1 (`2026-06-14-quant-port-tier1.md`) |
| 6 | Serving macro regional + indicadores globais + fiscal Tesouro | T1D | T1 (`2026-06-14-quant-port-tier1.md`) |
| 7 | Robust Cornish-Fisher Sharpe | T2A | T2 (`2026-06-14-quant-port-tier2.md`) |
| 8 | Risk budgeting por ETL (MCETL/PCETL/STARR) | T2B | T2 (`2026-06-14-quant-port-tier2.md`) |
| 9 | CVaR-como-restricao max-retorno (+SCS, verificador realizado) | T2C | T2 (`2026-06-14-quant-port-tier2.md`) |
| 10 | Restricoes de bloco/setor + bounds por ativo | T2C | T2 (`2026-06-14-quant-port-tier2.md`) |
| 11 | Penalidade de turnover/custo L1 | T2C | T2 (`2026-06-14-quant-port-tier2.md`) |
| 12 | Backtest walk-forward (OOS) | T2D | T2 (`2026-06-14-quant-port-tier2.md`) |
| 13 | CVaR condicional a regime | T2C | T2 (`2026-06-14-quant-port-tier2.md`) |
| 14 | Atribuicao de risco por fatores (sobre IPCA) | T2E | T2 (`2026-06-14-quant-port-tier2.md`) |
| 15 | Absorption ratio Kritzman-Li | T2E | T2 (`2026-06-14-quant-port-tier2.md`) |
| 16 | Expor outputs orfaos do worker (EVT/GARCH) em FundRiskOut | T2F | T2 (`2026-06-14-quant-port-tier2.md`) |
| 17 | Mandato->delta ladder com clamp | T2F | T2 (`2026-06-14-quant-port-tier2.md`) |
| 18 | Alerta 3-sigma He-Litterman (views vs prior) | T2F | T2 (`2026-06-14-quant-port-tier2.md`) |
| 19 | Risk budgeting (variancia): MCTR + retornos implicitos | T2B | T2 (`2026-06-14-quant-port-tier2.md`) |
| 20 | Decomposicao de episodios de drawdown | T2G | T2 (`2026-06-14-quant-port-tier2.md`) |
| 21 | Monte Carlo block-bootstrap | T2G | T2 (`2026-06-14-quant-port-tier2.md`) |
| 22 | Rolling annualized returns | T3A | T3 (`2026-06-14-quant-port-tier3.md`) |
| 23 | Benchmark composto multi-bloco | T3A | T3 (`2026-06-14-quant-port-tier3.md`) |
| 24 | Style-box 9-box | T3B | T3 (`2026-06-14-quant-port-tier3.md`) |
| 25 | IPCA K-selection (worker) | T3B | T3 (`2026-06-14-quant-port-tier3.md`) |
| 26 | manager_score equity-only | T3C | T3 (`2026-06-14-quant-port-tier3.md`) |
| 27 | Enriquecimento do peer ranking | T3C | T3 (`2026-06-14-quant-port-tier3.md`) |
| 28 | Drift 2-tier + downside/semi-deviation | T3D | T3 (`2026-06-14-quant-port-tier3.md`) |
| 29 | Normalizacao de expense ratio | T3D | T3 (`2026-06-14-quant-port-tier3.md`) |
| 30 | Tail-VaR panel (CF mVaR/ETR/Rachev/JB) | T3E | T3 (`2026-06-14-quant-port-tier3.md`) |
| 31 | CVaR parametrico + EVT POT-GPD live | T3E | T3 (`2026-06-14-quant-port-tier3.md`) |
| 32 | Ratios eVestment (Sterling/Omega/Treynor/Jensen) | T3A | T3 (`2026-06-14-quant-port-tier3.md`) |
| 33 | LW constant-correlation + Marchenko-Pastur denoise | T3F | T3 (`2026-06-14-quant-port-tier3.md`) |
| 34 | Correlation-regime/contagio | T3F | T3 (`2026-06-14-quant-port-tier3.md`) |
| 35 | Robusto/vol-target SOCP | T3F | T3 (`2026-06-14-quant-port-tier3.md`) |
| 36 | SCS fallback + verificacao pos-solve (standalone) | T3F | T3 (`2026-06-14-quant-port-tier3.md`) |
| 37 | CVaR limit ajustado a regime | T3G | T3 (`2026-06-14-quant-port-tier3.md`) |
| 38 | Gamma drift monitor (worker) | T3B | T3 (`2026-06-14-quant-port-tier3.md`) |
| 39 | CVaR annualization + verificador realizado | T3G | T3 (`2026-06-14-quant-port-tier3.md`) |
| 40 | PSD eigenvalue repair | T3G | T3 (`2026-06-14-quant-port-tier3.md`) |
| 41 | Governanca de breach CVaR | T3G | T3 (`2026-06-14-quant-port-tier3.md`) |
| 42 | Up/down proficiency + R2 | T3A | T3 (`2026-06-14-quant-port-tier3.md`) |
| 43 | BL Woodbury/full-Omega | T3G | T3 (`2026-06-14-quant-port-tier3.md`) |
| 44 | Marchenko-Pastur + absorption (RMT pack) | T3F | T3 (`2026-06-14-quant-port-tier3.md`) |
| 45 | TAA regime bands (LARGE - spike) | T3G | T3 (`2026-06-14-quant-port-tier3.md`) |
| 46 | Track de fatores fundamental (LARGE - spike) | T3G | T3 (`2026-06-14-quant-port-tier3.md`) |

---

## Ordem de execucao sugerida

A sequencia abaixo segue o review (valor x esforco x dependencias). Dentro de um cluster, execute as tasks na ordem numerada.

### Sprint 1 -- Tier 1 (numpy puro + fiacao sobre dados existentes)
1. **T1C** (#5 CVaR RU) -- trivial e remove a auto-inconsistencia de 3 convencoes; faca primeiro.
2. **T1A** (#1-3 Sharpe/Sortino/IR, ENB, Active Share) -- maior valor/esforco. _Active Share depende de uma fonte de pesos de benchmark (ver perguntas em aberto)._
3. **T1B** (#4 metricas RF/alternativos) -- `[repo: workers]`; popula colunas mortas da migration 0012 e expoe em FundRiskOut.
4. **T1D** (#6 serving macro regional/global/fiscal) -- rotas DB-first sobre tabelas ja materializadas.

### Sprint 2 -- Tier 2 nucleo
1. **T2A** (#7 robust Sharpe) e **T2B** (#8/#19 risk budgeting ETL + MCTR) -- puros e isolados, podem ir em paralelo.
2. **T2C** (eixo do otimizador) na ordem **#10 bounds de bloco/ativo -> #11 turnover L1 -> #9 CVaR-como-restricao (+SCS) -> #13 CVaR por regime**. #10 e pre-requisito dos demais; #9 habilita #13.
3. Em paralelo: **T2E** (#14 atribuicao de fatores sobre `factor_model_fits`, #15 absorption ratio) -- isolados e de alto valor.

### Sprint 3 -- Tier 2 produto/diferenciacao + housekeeping
1. **T2D** (#12 backtest walk-forward) -- reaproveita a contabilidade de custo de `backend/_gate_vs_full_backtest.py` (hoje script solto).
2. **T2G** (#20 episodios de drawdown, #21 Monte Carlo) e **T2F** (#16 outputs orfaos, #17 mandato->delta, #18 alerta 3-sigma).
3. **Housekeeping:** remover o `_sigma_bl` calculado e descartado em `backend/app/services/portfolio_builder.py`; versionar/parametrizar `_gate_vs_full_backtest.py` dentro do servico de backtest.

### Backlog -- Tier 3 (conforme demanda)
Itens T3A-T3F conforme prioridade de produto. **Reavaliar T3G #45 (TAA por regime) e #46 (track de fatores fundamental)** -- sao os unicos itens de esforco *large*; ambos exigem novo substrato de dados/decisao de produto e estao escritos como tasks de **spike/decisao**, nao codigo pronto.

---

## Dependencias cruzadas (nao violar)

- **T2C interno:** #10 (bounds vetoriais/bloco) e pre-requisito de #9/#13 e de qualquer cap por ativo/regime. Ordem fixa 10 -> 11 -> 9 -> 13.
- **T3G #37** (CVaR limit por regime) e **#39** (annualization + verificador realizado) dependem do caminho CVaR-limite de **T2C #9**. Nao iniciar antes.
- **T3F #35** (robusto/vol-target SOCP) so e significativo com um objetivo de retorno (mu BL); fazer apos **T2C #9**. **T3F #36** (hardening SCS) e em grande parte subsumido por #9 se este ja implementar o ladder CLARABEL->SCS.
- **T3F #33/#44** (RMT: LW constant-correlation, Marchenko-Pastur, absorption) sobrepoem **T2E #15** (absorption ratio). Referenciar a funcao de #15, nao duplicar.
- **T2E #14** (atribuicao) e **T3B #25** (K-selection) dependem dos fits IPCA ja persistidos em `factor_model_fits` (existem; nao refitar).
- **T2B #19** e **T3C #26** consomem mu do posterior BL + rf (gate G5) e/ou colunas que **T1B #4** popula -- preferir T1B antes de T3C.
- **T1A #3** (Active Share) fica como funcao de biblioteca ate decidir a fonte de pesos do benchmark (ver perguntas em aberto do Tier 1).

---

## Repos afetados

- **`investintell-light`** (app FastAPI): a maioria das tasks.
- **`investintell-datalake-workers`** (calculo offline): tasks marcadas `[repo: investintell-datalake-workers]` -- presentes em **T1B** (primario), **T2E**, **T2F**, **T3B**, **T3C**, **T3E**, **T3G**. Rodam no harness de teste do repo de workers, nao no pytest do backend do light.
- **`investintell-allocation/backend/quant_engine`**: somente leitura (fonte dos algoritmos).

## Dependencias externas a adicionar

- **`scipy>=1.13`** em `backend/pyproject.toml` -- usado por **T2A** (Cornish-Fisher/Opdyke), **T3E** (genpareto/EVT, Jarque-Bera), **T3F** (chi2 para o raio robusto), **T3G**. Hoje so vem transitivamente via scikit-learn; declarar explicitamente.
- **SCS** -- backend de solver ja embarcado no `cvxpy`; nenhuma instalacao nova, apenas selecao no ladder de solver (T2C #9 / T3F #36).
- **`scikit-learn`** (TimeSeriesSplit, T2D) e **`cvxpy`** (todo o eixo otimizador) ja sao dependencias diretas.

---

## Perguntas em aberto / decisoes de produto (agregado)

Cada tier tem a sua secao detalhada de perguntas em aberto no fim do respectivo arquivo. As decisoes de maior impacto:

- **Active Share (T1A #3):** definir a fonte de pesos de constituintes do benchmark (tabela estatica de holdings de indice? leitura do data-lake? look-through N-PORT de um ETF de indice via `app.services.lookthrough`?). Ate la, fica como funcao pura nao auto-conectada.
- **Risk-free (T1A #1/#2):** usar o default estatico 0.04 (= legado/worker) ou puxar DFF ao vivo do data-lake / aceitar override por request?
- **ENB (T1A #2):** confirmar que a ENB asset-space (entropia sobre `risk_contributions`) e a metrica de Tier 1 pretendida (vs. a ENB factor-space/minimum-torsion, que exigiria um modelo de fatores no caminho online -- tier posterior).
- **Governanca de CVaR (T3G #41):** exige modelo de dados novo (config de limite por perfil + persistencia de `consecutive_breach_days` em snapshot) -- decisao de produto, nao port puro.
- **TAA por regime (T3G #45) e track de fatores fundamental (T3G #46):** itens *large*; precisam de taxonomia de asset-class/IPS, bounds por bloco, regime de 4 estados (#45) e painel macro 8-fatores + EWMA-WLS (#46). Escritos como spikes -- decidir antes de codar.

---

_Gerado a partir do review comparativo (workflow `wzez5qn43`) em 2026-06-14._
