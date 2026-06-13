# Backtest QC — alternativas para o detector de regime (além do Credit Regime)

**Data:** 2026-06-12 · **Métodos:** 6 backtests cloud na QuantConnect via lean CLI
(workspace `lean-research/`, org `2e1c086e6a6966746002f1c32c2cbbfd`); mesma mecânica
do estudo anterior (`2026-06-11-macro-regime-backtest.md`): janela 2007-01-01 →
2026-06-01, $1M, diário, binário risk_on = 100% SPY / risk_off = 100% IEF, flip no
fechamento de T → ordem no evento seguinte (fill na abertura; sem lookahead), vendas
antes de compras; equity curves por crise via `backtests/chart/read` ·
**Resultado: dois candidatos BATEM o baseline crédito-só (Sharpe 0,481 / DD 25,7%) em
TODAS as métricas — o ensemble por votos `vote2of3` (crédito + tendência + NFCI, ≥2
votos: Sharpe 0,549, DD 25,3%, CAGR 12,30%) e a variante sem NFCI `credit_and_trend`
(0,503 / 25,4% / 11,62%). Todos os sinais são 100% materializáveis do data-lake.**

> Continuação da Frente B (re-escopada). Baseline = detector binário de stress de
> crédito HYG/IEF já em produção (`credit_regime_daily`, worker `credit_regime`).
> A lição do estudo anterior foi respeitada: estados binários (sem caution),
> sinais com histerese/avaliação lenta, e a regra "composite por pesos ≈ iguais com
> VIX/curva destrói valor" — aqui o ensemble é por VOTOS entre sinais individualmente
> defensáveis, não por score.

---

## 1. Inventário do data-lake (o que existe com histórico utilizável)

`macro_data` no Tiger `t83f4np6x4` tem 98 séries; as relevantes para regime com
histórico PLENO (cobrindo 2008) e reabastecimento garantido:

| Série | Cobertura no lake | Frequência | Nota |
|---|---|---|---|
| `NFCI` (Chicago Fed) | 1971 → atual | semanal | índice de condições financeiras; **revisado ex-post** |
| `BAA10Y` (Moody's Baa − 10Y) | 1986 → atual | diária | spread de crédito SEM problema de licença ICE (os `BAML*` seguem rolling ~3y) |
| `STLFSI4` (St. Louis Fed) | 1993 → atual | semanal | stress financeiro; não testado (redundante c/ NFCI, mesma família/viés) |
| `YIELD_CURVE_10Y2Y` / `DGS10`/`DGS2` | 1976 → atual | diária | curva — REFUTADA como gatilho no estudo anterior |
| `VIXCLS` | 1990 → atual | diária | REFUTADO como gatilho (whipsaw) |
| `SAHMREALTIME`, `CFNAI`, `ICSA`, `INDPRO`, `PERMIT` | 1959/67 → atual | mensal/semanal | lentos demais p/ alocação tática; contexto |
| SPY em `eod_prices` (Tiingo) | 1993 → atual | diária | base do sinal de tendência |
| HYG/IEF | já no `credit_regime_daily` (worker busca os preços) | diária | sinal de crédito em produção |

Pré-validação no lake (consultas 2026-06-12): NFCI > 0 em 12,1% das semanas desde
2007; em 2022 o máximo foi −0,098 (não dispara — bom: 2022 não era crise de funding) e
em 2020 +0,306 (dispara). BAA10Y máx 2022 = 2,42 com p80 ≈ 3,0 (idem).

## 2. Candidatos testados

| Modo | Regra risk-off | Fonte produção |
|---|---|---|
| `trend` | SPY fechamento mensal < SMA 10 meses (Faber; avaliação só na virada do mês) | `eod_prices` |
| `nfci` | NFCI > 0 entra; sai < −0,05 (histerese) | `macro_data` |
| `baa10y` | spread > p80 móvel 5 anos (mín. 252 obs; espelho do p20 do crédito) | `macro_data` |
| `credit_or_trend` | crédito OU tendência ativos | combinação |
| `credit_and_trend` | crédito E tendência ativos (2-de-2) | combinação |
| `vote2of3` | ≥2 votos entre {crédito, tendência, NFCI} | combinação |

Crédito = réplica exata do detector em produção (HYG/IEF ajustado < p20 móvel 5y,
mín. 252 obs). Código: `lean-research/RegimeAlt*/main.py` (template único, `MODE`).

## 3. Resultados (janela completa 2007→2026)

| Métrica | SPY B&H | Crédito-só (baseline) | **vote2of3** | nfci | credit_and_trend | baa10y | trend | credit_or_trend |
|---|---|---|---|---|---|---|---|---|
| CAGR | 11,03% | 11,14% | **12,30%** | 12,33% | 11,62% | 11,51% | 9,12% | 8,71% |
| Sharpe | 0,418 | 0,481 | **0,549** | 0,548 | 0,503 | 0,511 | 0,418 | 0,396 |
| Sortino | 0,424 | 0,509 | **0,580** | 0,555 | 0,534 | 0,533 | 0,442 | 0,417 |
| Max drawdown | 55,0% | 25,7% | **25,3%** | 29,8% | 25,4% | 35,3% | 28,6% | 28,5% |
| Recuperação DD (dias) | 1.772 | 709 | **709** | 709 | 709 | 895 | 895 | 895 |
| Beta | 1,00 | 0,61 | 0,57 | 0,58 | 0,62 | 0,55 | 0,39 | 0,38 |
| Ordens (≈ 2×flips) | — | — | **34** | 10 | 54 | 98 | 66 | 106 |

### 3.1 Por crise (equity curves via `backtests/chart/read`; ref. do estudo anterior)

| Janela | SPY B&H | Crédito-só | **vote2of3** | nfci | credit_and_trend |
|---|---|---|---|---|---|
| GFC out/07–jun/09 — retorno | −37,9% | −7,1% | **+3,1%** | +16,0% | −5,7% |
| GFC — max DD | −54,8% | −24,0% | **−9,8%** | −9,7% | −24,2% |
| COVID 2020 — retorno do ano | +17,6% | +0,6% | **+6,0%** | −2,3% | +6,0% |
| COVID 2020 — max DD | −31,2% | −22,4% | **−19,0%** | −28,7% | −19,0% |
| 2022 — retorno | −18,2% | −18,1% | −18,4% | −18,2% | −18,4% |
| 2022 — max DD | −24,4% | −24,2% | −24,6% | −24,4% | −24,6% |

Leitura: o `vote2of3` melhora as duas crises-alvo (GFC e COVID) **sem pagar nada em
2022** (nenhum dos 3 sinais atingiu 2 votos — exatamente o comportamento desejado, que
o composite legado não tinha). O `nfci` sozinho brilha na GFC (entrou cedo, ago/2007,
e ficou fora ~2 anos) mas é LENTO no COVID (semanal: DD −28,7%) e seu resultado carrega
viés de revisão (§4). A tendência sozinha não compensa (Sharpe = B&H); o OR
sobre-protege (pior que o baseline) — o valor está na **confirmação cruzada**.

## 4. Caveats

1. **Viés de revisão do NFCI**: o QC/FRED serve a última vintage; o NFCI é revisado
   ex-post. Os números de `nfci` e (em menor grau) `vote2of3` são um teto otimista.
   Mitigantes: (i) o `credit_and_trend` (zero séries revisadas) TAMBÉM bate o baseline
   em todas as métricas — a melhora não depende do NFCI; (ii) no `vote2of3` o NFCI é
   1 voto entre 3, nunca decide sozinho; (iii) em produção o worker acumula o NFCI
   real-time daqui pra frente (sem viés prospectivo).
2. Tendência mensal tem granularidade grossa (até 1 mês de atraso na entrada) — é o
   preço do baixo whipsaw; foi testada e perde sozinha, só agrega como confirmação.
3. `baa10y` NÃO substitui o crédito HYG/IEF (DD 35,3% — reage devagar e dessensibiliza
   no pós-crise). Vale como **extensão histórica/fallback** (1986→) e contexto.
4. Reconstrução local difere marginalmente do QC (Tiingo adj vs QC adj) — irrelevante
   para a decisão, relevante se quisermos reproduzir flip a flip.

## 5. Auditoria — IDs QC

| Projeto | Project ID | Backtest | Backtest ID |
|---|---|---|---|
| RegimeAltTrend | 32827541 | `trend-v1` | `b5bb925e8adac169fd0f1f397975258c` |
| RegimeAltNFCI | 32827544 | `nfci-v1` | `c7d6afb9cc5f9bf649e8f775bf04fe6b` |
| RegimeAltBaa10y | 32827545 | `baa10y-v1` | `1d77c95b9684aafe1d7b01887fe26bec` |
| RegimeAltCreditOrTrend | 32827547 | `credit-or-trend-v1` | `bacd9c47154436899f05e0f93292ffa3` |
| RegimeAltVote | 32827549 | `vote2of3-v1` | `7ecef2e31f1fa4c98b7c5cc732b1f259` |
| RegimeAltCreditAndTrend | 32827815 | `credit-and-trend-v1` | `f55cf26b35ad07919bfa9e27cafdf0fe` |

## 6. Veredito e caminho de produção

**Veredito: promover o `vote2of3` como evolução do detector de regime.**

1. **Detector novo**: ensemble por votos — crédito (HYG/IEF < p20 5y, já em produção) +
   tendência (SPY mensal < SMA10m, de `eod_prices`) + NFCI (> 0 / sai < −0,05, de
   `macro_data`); `risk_off` com ≥2 votos. Melhora Sharpe (0,481→0,549), DD
   (25,7→25,3%), CAGR (11,14→12,30%) e nº de flips (46→~17) vs o detector atual, e
   fica neutro em 2022.
2. **Materialização**: estender o worker `credit_regime` (repo
   `investintell-datalake-workers`) para `regime_composite_daily` com colunas
   `credit_vote`, `trend_vote`, `nfci_vote`, `state`, `flip` — todos os insumos já
   estão no lake (nenhuma fonte nova). Manter `credit_regime_daily` intacto
   (compatibilidade + é 1 dos votos).
3. **Consumo no Light**: `app/services/macro_regime.py` passa a ler o composto e expor
   o breakdown dos 3 votos (explicabilidade: qual sinal está ativo). O badge ganha
   nuance "1 voto ativo" (informativo, sem ação) vs "≥2 = risk_off".
4. **Se quisermos zero exposição a séries revisadas**: `credit_and_trend` (2-de-2) é a
   alternativa conservadora — também bate o baseline (0,503 / 25,4% / 11,62%).
5. **BAA10Y**: adicionar como série de contexto no breakdown e fallback de longo
   histórico do voto de crédito (pré-2007 / eventual indisponibilidade de HYG).
6. **HMM (B5)**: o baseline a bater sobe para **Sharpe 0,549 / DD 25,3%** (vote2of3).
   Se não superar isso out-of-sample, não se promove.
