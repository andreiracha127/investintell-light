# Research/triagem — rebalanceamento, detector macro e look-through de holdings

**Data:** 2026-06-11 · **Métodos:** introspecção do engine LEAN real (lean CLI →
`lean research`, container `quantconnect/research`, reflexão sobre as assemblies
`QuantConnect.*`) + queries read-only no DB Light (porta 5436) e no DB-mãe
(`investintell-allocation-db-1`) · **Resultado: 3 frentes de implementação definidas;
1 descoberta estrutural (dois gates de truncamento de holdings empilhados) com decisão
do dono de reingerir 100%.**

> Complementa `2026-06-11-f8-optimizer-black-litterman.md` (sessão paralela): aquele doc
> valida o **motor** de otimização (BL + min-CVaR/CVXPY); este define a **política de
> rebalanceamento** em torno do motor, o **detector de sinais macro** e o **look-through**.
> O builder e o esquema funds estão sendo construídos na sessão paralela — itens marcados
> 🔀 têm interface com ela e precisam de coordenação.

---

## 1. Inventário verificado no engine LEAN (referência de arquitetura)

Introspecção direta nas assemblies (não documentação) — workspace
`lean-research/ModelTriage/triage.py`, reproduzível com:
`docker exec <container> bash -c 'cd /LeanCLI && PYTHONNET_RUNTIME=coreclr
PYTHONNET_CORECLR_RUNTIME_CONFIG=/Lean/Launcher/bin/Debug/QuantConnect.Lean.Launcher.runtimeconfig.json
python triage.py'`.

### 1.1 Portfolio Construction Models (10 nativos)

| Modelo | Alocação | Relevância p/ Light |
|---|---|---|
| EqualWeighting | peso igual entre insights | ✅ baseline v1 |
| InsightWeighting | campo `weight` do insight | ✅ v1 (nossos scores viram weights) |
| ConfidenceWeighted | `confidence` do insight | opcional |
| AccumulativeInsight | acumula em passos | não |
| MeanVarianceOptimization | Markowitz janela histórica | ⚠️ instável, não adotar puro |
| BlackLittermanOptimization | equilíbrio + views | ✅ já validado na sessão paralela |
| RiskParity | paridade de contribuição de risco | ✅ v2 |
| MeanReversion | OLMAR | não (não é o produto) |
| SectorWeighting | cap setorial | inspiração p/ caps de setor |
| AlphaStreams / Null | utilitários | não |

**Otimizadores plugáveis** (`IPortfolioOptimizer`): MaximumSharpeRatio, MinimumVariance,
RiskParity, UnconstrainedMeanVariance. A separação PCM → optimizer do LEAN é o mesmo
desenho estimativa → motor CVXPY já adotado no F8 (precedente confirmado de novo).

**Mecânica de rebalanceamento do LEAN** (o que vale copiar): o PCM base recebe
`Func<DateTime, DateTime?>` — na prática calendário (`Expiry.END_OF_MONTH`), `timedelta`
ou função custom — **e** duas flags independentes:
`RebalancePortfolioOnInsightChanges` / `RebalancePortfolioOnSecurityChanges`.
Ou seja: *gatilho temporal* e *gatilho por evento* são ortogonais e combináveis.

### 1.2 O que NÃO existe no LEAN

- Nenhum alpha model macro (os 10 nativos são técnicos: EmaCross, Macd, Rsi,
  HistoricalReturns, pairs trading).
- Nenhum suporte a carteira de mutual fund. ETF tem `ETFConstituentUniverse`
  (Weight/SharesHeld/MarketValue, carteira completa point-in-time) — mas é dado da QC
  Data Library; ficou **irrelevante** para nós após a decisão de reingerir N-PORT 100%
  (§3), que cobre ETFs americanos pela mesma fonte.

### 1.3 Ambiente research (libs verificadas, úteis p/ prototipagem)

hmmlearn 0.3.3 · statsmodels 0.14.6 (MarkovRegression) · ruptures 1.1.10 · arch 8.0.0 ·
pykalman · pomegranate · cvxpy 1.7.5 · PyPortfolioOpt 1.5.6 · Riskfolio-Lib 7.0.1.

---

## 2. Frente A — Política de rebalanceamento (implementar no Light)

O motor (BL + min-CVaR) está coberto pela sessão paralela. O que falta — e este doc
define — é a **política**: quando e como o portfólio construído pelo builder é
re-otimizado e re-executado.

**Desenho (espelha a mecânica LEAN, validada em produção há anos):**

1. **Gatilho calendário** configurável por portfólio: `monthly` (default) | `quarterly`
   | `weekly`. Avaliado por job agendado, não em request path.
2. **Gatilho por banda de tolerância** (drift): re-otimiza se algum peso desviar mais
   que `band_abs` (default 5 p.p.) ou `band_rel` (default 25% do peso-alvo) — o padrão
   da literatura de rebalancing (Vanguard/Daruwala) e equivalente funcional das flags de
   evento do LEAN.
3. **Gatilho por evento de sinal** (frente B): mudança de regime macro força
   re-avaliação fora do calendário. Desacoplado via flag — v1 lança sem ele.
4. **Saída**: nova proposta de pesos + diff contra a carteira atual + custo estimado de
   turnover. **Nunca** auto-executa — apresenta ao usuário (produto é advisory).

**Itens de implementação:**

- [ ] A1 — Tabela `rebalance_policy` (portfolio_id, frequency, band_abs, band_rel,
      macro_trigger_enabled, last_evaluated_at). 🔀 coordenar com o esquema do builder.
- [ ] A2 — Serviço `rebalance/evaluator.py`: dado portfólio + política → decide
      `no_action | drift_alert | proposal`, computa drift por posição.
- [ ] A3 — Endpoint `GET /portfolios/{id}/rebalance/preview` (proposta + diff +
      turnover) e job agendado de avaliação.
- [ ] A4 — Pesos-alvo vêm do motor F8 (min-CVaR default, max-utility opção) — 🔀 é a
      interface com o builder: a política chama o mesmo serviço de otimização que o
      builder usa na construção inicial.

---

## 3. Frente B — Detector de sinais macro (fase posterior ao F8)

Não há modelo pronto; o caminho validado é detector próprio com dados FRED.

**MVP (regras, sem ML) — composite de 4 sinais com histórico longo e zero custo:**

| Sinal | Série | Regra risk-off |
|---|---|---|
| Curva de juros | T10Y2Y (FRED) | spread < 0 por ≥ 20 pregões |
| Recessão OECD | `Fred.OECDRecessionIndicators` (categoria nativa no LEAN; série USARECM na API FRED) | == 1 |
| Stress de crédito | ICE BofA HY OAS (BAMLH0A0HYM2) | OAS > p80 móvel 5y |
| Vol implícita | VIX (CBOE/FRED VIXCLS) | > 25 por ≥ 5 pregões |

Estado = `risk_on | caution | risk_off` (0–1 sinais / 2 / ≥3). O estado vira (a) badge
no cockpit, (b) gatilho opcional de rebalanceamento (A1.macro_trigger_enabled),
(c) futura view BL (ex.: risk_off → view negativa em equity de beta alto — encaixa no
motor da sessão paralela sem mudança de arquitetura).

**v2 (ML, validar no research antes de promover):** HMM gaussiano 2–3 estados
(hmmlearn) ou `MarkovRegression` (statsmodels) sobre retornos+vol do benchmark;
`ruptures` para change-points como verificação cruzada. Protótipo no ambiente
`lean research` que já está montado.

**Itens de implementação:**

- [ ] B1 — Ingestão FRED (API pública, key gratuita): 4 séries, tabela
      `macro_series(series_id, date, value)` + sync diário. Sem dependência do DB-mãe.
- [ ] B2 — Serviço `macro/regime.py`: avalia regras → `macro_regime_history`
      (date, state, sinais individuais para explicabilidade).
- [ ] B3 — Endpoint `GET /macro/regime` (estado atual + componentes + histórico).
- [ ] B4 — Integração com A2 (gatilho) e badge no cockpit. 🔀 UI na sessão de frontend.
- [ ] B5 — (v2) Notebook de validação HMM/Markov-switching no workspace lean-research;
      critério de promoção: estabilidade dos estados out-of-sample > regras do MVP.

---

## 4. Frente C — Look-through de holdings (fundos e ETFs)

### 4.1 Descoberta estrutural: dois gates empilhados

Verificado por query nos dois bancos (2026-06-11):

1. **DB-mãe** (`sec_nport_holdings`, 2,23M linhas, particionada): a ingestão trunca —
   mediana 56 posições por (série, report), teto duro 200, penhasco após ~125.
   N-PORT real tem centenas/milhares de posições por fundo. Cobertura média: 81,7% do
   NAV. **Dono confirmou: gate arbitrário de exibição, será removido com reingestão
   de 100% dos holdings (trabalho no projeto investintell-allocation).**
2. **Light** (`app/sync/funds.py:66`): `MAX_HOLDINGS_PER_SERIES = 50` corta de novo no
   sync → cobertura mediana no Light cai para 72,6% (p10 15%, p90 109% — derivativos).

### 4.2 Perfil quantificado do problema (DB Light, 4.558 fundos / 175.310 linhas)

- Fund-of-funds: 756 linhas de holdings são fundos do nosso universo (match
  CUSIP→ISIN), em 311 séries; 33 séries com >50% do NAV em outros fundos.
- Profundidade: só 10 arestas de nível 2; zero ciclos diretos → recursão profundidade 2
  com guarda de ciclo é suficiente e barata.
- 158 posições com `pct_of_nav` negativo (shorts) → preservar sinal, reportar net/gross.
- Σpct > 100% existe (derivativos/alavancagem) → **nunca renormalizar silenciosamente**.

### 4.3 Modelo definido

Look-through recursivo (BFS, profundidade máx. 2, set de séries visitadas), aresta por
match `fund_holdings.cusip/isin ↔ funds.cusip/isin`, peso composto
`w = (pct_parent/100) × pct_child`. Agregação por emissor (dedupe CUSIP-6),
`asset_class`, `sector` (e `currency` após C2), separando exposição direta × indireta.
Residual explícito em 2 buckets (pós-reingestão o bucket "não reportado" desaparece):
*fundo não-decomponível* (fora do universo / sem holdings) e *derivativos* (Σ>100,
reportar gross e net). Staleness em cadeia: resultado carrega o `report_date` mais
antigo da cadeia (N-PORT é trimestral, ~60d de defasagem) — mesmo padrão de
`source_calc_date` em `funds`.

**Itens de implementação:**

- [ ] C0 — **(DB-mãe, pré-requisito)** reingestão N-PORT sem gate. Volume estimado:
      13–26M linhas no histórico (média 300–600 posições/par vs 51,6 atual) — ok, tabela
      particionada. *Fora deste repo.*
- [ ] C1 — Sync Light: remover `MAX_HOLDINGS_PER_SERIES` (ou parametrizar alto);
      volume Light estimado (último report × ~4,5k séries): ~1,8–2,7M linhas.
- [ ] C2 — Schema: adicionar `currency` (e avaliar `quantity`, `fair_value_level`) ao
      `fund_holdings`; **aposentar `is_top50_truncated`** → substituir por
      `coverage_pct` por série calculado no sync. 🔀 migração coordenada com o esquema
      funds da sessão paralela.
- [ ] C3 — Serviço `lookthrough/engine.py`: expansão recursiva + agregações + residual
      + staleness em cadeia. Puro Python sobre o DB local, sem dependência externa.
- [ ] C4 — Endpoint `GET /funds/{id}/lookthrough?dim=issuer|asset_class|sector|currency`
      e `GET /portfolios/{id}/lookthrough` (agregado da carteira do usuário — o caso de
      uso que justifica tudo: exposição consolidada atravessando os fundos).
- [ ] C5 — Frontend: tela de exposição consolidada (direta × indireta × residual).
      🔀 sessão de frontend.

### 4.4 O que a reingestão elimina

- Bucket residual "não reportado" (cobertura → ~100% por construção).
- Necessidade de QC Data Library / fonte licenciada para constituintes de ETF (ETFs
  americanos arquivam N-PORT; eram 577 das 756 posições FoF).
- O v2 "substituir top-50 dos ETFs" do plano anterior — morto antes de nascer.

---

## 5. Ordem sugerida e dependências

```
C0 (DB-mãe, paralelo) ──► C1 ──► C2 ──► C3 ──► C4 ──► C5
A1 ──► A2 ──► A3 (A4 depende do motor F8 da sessão paralela)
B1 ──► B2 ──► B3 ──► B4 (B5 depois; gatilho macro em A2 só após B2)
```

A frente C é a de maior valor imediato para o produto (exposição consolidada é feature
visível) e só depende do C0. A frente A é pequena e destrava o builder como produto
vivo. A frente B é a mais independente — pode rodar 100% em paralelo.

## 6. ADENDO (mesma data, pós-verificação) — re-escopo pelo data-lake tri-partite

A arquitetura evoluiu após a redação dos §1–5: data-lake **TimescaleDB Cloud** (Tiger
`Investintell-Prod`, `t83f4np6x4`) + InsForge (org-scoped) + workers standalone em
`E:\investintell-datalake-workers` deployados no Railway (projeto `investintell-workers`,
`1cc3be4b-c600-43ee-9525-69e05818e5fa`). Estado **verificado** via tiger CLI e Railway CLI
em 2026-06-11:

| Verificação | Resultado |
|---|---|
| `sec_nport_holdings` no cloud | **96,4M linhas, 18.139 séries, média 300 pos/par, mediana 85, máx 18.705 — sem gate** |
| Cobertura | 279.399 pares série-report com ≥95%; CAGGs típicos ~100% |
| CAGGs | `cagg_nport_series_profile` (**coverage_pct + n_synthetic** por série-report — o item C2 já materializado) e `cagg_nav_monthly` |
| Hypertables | 22 (nav_timeseries, macro_data, treasury_data, sec_13f_*, sec_xbrl_facts, **macro_regime_history**…) |
| Catálogo global | populado (sec_managers 977k, instruments_universe 14,8k, esma_* etc.) |
| **Detector de regime macro JÁ EXISTE** | `macro_regime_snapshot` (1.122 dias, único por `as_of_date`): `raw_regime` (ex.: RISK_ON) + `stress_score` 0–100 + `signal_details`/`signal_breakdown` com ~10 sinais (sahm, cfnai, hy_oas, dxy, vix, icsa, permits, ff_roc) e pesos dinâmicos — mais rico que o MVP da §3 |
| Railway | workers de métricas deployados (`risk-metrics` online, `factor-model` completed, `characteristics` offline); **ingestão em implementação** cf. `E:\investintell-datalake-workers\docs\INGESTION_DESIGN.md` |

### Impacto nas frentes

**Frente C (look-through):**
- **C0 ✅ CONCLUÍDO** — reingestão 100% feita direto no cloud (bulk DERA, chave sintética
  `IS:`/`LE:`/`H:`/`CIK:` para os 44,7% sem CUSIP real). O DB-mãe local deixa de ser a
  fonte de holdings.
- **C1 re-escopado**: o sync do Light passa a ler do **TimescaleDB Cloud** (não do DB-mãe);
  alternativa de arquitetura a decidir — (a) Light sincroniza último report por série como
  hoje, ou (b) **look-through vira worker de cálculo** no repo datalake (padrão
  `risk_metrics`: lê holdings do cloud, materializa exposições agregadas no cloud, Light
  só consome). Com 96M linhas e séries de 18k posições, **(b) é o recomendado** — o
  engine recursivo (§4.3) permanece válido, muda o lugar onde roda.
- **C2 simplificado**: `coverage_pct` **não recalcular** — já vem do
  `cagg_nport_series_profile`. Resta aposentar `is_top50_truncated` no Light e propagar
  `currency`.
- **C3 atenção nova**: chaves sintéticas não casam com `funds.cusip` — o match FoF deve
  tratar prefixos (`IS:<isin>` casa via `funds.isin`; `LE:`/`H:`/`CIK:` não casam → bucket
  não-decomponível).

**Frente B (macro) — re-escopada, GATE de validação EXECUTADO (2026-06-12):** ⚠️ o dono
reportou que no legado os macro-regimes capturavam pouco ou nenhum sinal. Backtest na
plataforma QC (2007→2026, lean CLI; doc completo:
`2026-06-11-macro-regime-backtest.md`) **confirmou para o composite e refutou para o
sinal de crédito isolado**:

| | SPY B&H | Composite legado (4 sinais) | Crédito só |
|---|---|---|---|
| CAGR / Sharpe / MaxDD | 11,0% / 0,42 / 55% | 8,0% / 0,35 / 29% | **11,1% / 0,48 / 26%** |
| Flips | 0 | 126 (whipsaw; 2022 PIOR que B&H) | 46 |

**Decisões resultantes:** (i) o Light NÃO consome `macro_regime_snapshot` como gatilho;
(ii) B2 vira detector binário de **stress de crédito com histerese** — e via proxy de
preço HYG/IEF < p20 móvel 5y, não via FRED: as séries ICE BofA (BAML*) viraram janela
rolling ~3 anos na API FRED (mudança de licença ICE) e não são mais reproduzíveis no
histórico; (iii) o worker `macro_ingestion` deve **preservar histórico BAML* acumulado**
(FRED não reabastece >3y); (iv) HMM (B5) segue válido com baseline a bater de
Sharpe 0,48 / DD 26%.
- B1 (ingestão FRED) → é o worker `macro_ingestion` **Tier 1 do INGESTION_DESIGN** (lock
  900_320), no repo de workers — não no Light.
- B2–B3 → o Light **consome** `macro_regime_snapshot`/`macro_regime_history` do cloud
  (endpoint fino `GET /macro/regime` lendo o snapshot mais recente + breakdown para
  explicabilidade). Não reimplementar regras.
- B4 (gatilho de rebalance + badge) inalterado, plugando no `raw_regime`/`stress_score`.
- B5 (HMM v2) continua válido como evolução — candidato a worker de cálculo no repo
  datalake; o INGESTION_DESIGN §3 já aponta CBOE/VIX-contango via Lean como série nova
  para regime.

**Frente A (rebalanceamento):** inalterada — segue no Light (A1–A4), com o gatilho macro
lendo o regime do cloud.

## 7. Artefatos da sessão

- Workspace Lean CLI: `lean-research/` (lean.json + data sample) — projeto `ModelTriage`
  com `triage.py` (introspecção reutilizável). Receita headless na memória
  (`lean-cli-research-env`): exige `PYTHONNET_RUNTIME=coreclr` +
  `PYTHONNET_CORECLR_RUNTIME_CONFIG` apontando para o runtimeconfig do Launcher.
- Fix de ambiente: `lean.exe` (Python 3.13 do sistema) exigiu `setuptools<81`
  (pkg_resources).
- Queries de perfil (cobertura, FoF, profundidade) reproduzíveis nos §3–4 — todas
  read-only.
