# Backtest QC — quant_engine LEGADO fiel (12 sinais, pesos dinâmicos) vs modelos do Light

**Data:** 2026-06-12 · **Métodos:** introspecção do código legado em
`E:\investintell-allocation\backend\quant_engine\regime_service.py` (verificado
byte-idêntico ao worktree corrigido `E:\inv-g1-block-fidelity\backend\quant_engine\` —
`regime_service.py`, `taa_band_service.py` e `risk_calc.py` sem diff em 2026-06-12);
port fiel para QuantConnect (lean CLI, org `2e1c086e6a6966746002f1c32c2cbbfd`);
4 backtests cloud (composite fiel ×2 mapeamentos + 2 ablações), janela
2007-01-01 → 2026-06-01, $1M, diário, SPY/IEF, mesmas convenções de execução dos
baselines; logs e equity curves via API v2 (`backtests/read/log`,
`backtests/chart/read`) · **Resultado: o modelo REAL do legado (10–12 sinais, pesos
dinâmicos, histerese) CONFIRMA o veredito do teste degradado — perde para credit-only
e vote2of3 (Sharpe 0,381 e CAGR 6,97% vs 0,549/12,30% do vote2of3). A ablação isola o
culpado: a AMPLIFICAÇÃO DINÂMICA DE PESOS destrói valor (removê-la sobe CAGR
6,97%→10,12% e Sharpe 0,381→0,555). A histerese tem valor modesto comprovado. Nada do
composite merece substituir o vote2of3; o único candidato condicional é o score
graduado SEM amplificação, se minimizar drawdown virar requisito (max DD 20,9%, o
menor de tudo que já testamos).**

> Continuação de `2026-06-11-macro-regime-backtest.md` (que usou réplica DEGRADADA de
> 4 sinais com pesos iguais). Este doc testa o modelo COMPLETO e fecha a questão
> "o que do legado vai para os workers do Light?".

---

## 1. O modelo legado, extraído do código

Fonte: `quant_engine/regime_service.py` (paths abaixo relativos a
`E:\investintell-allocation\backend\`). O worker `app/jobs/workers/risk_calc.py`
(linha ~1460) chama `classify_regime_multi_signal(**build_regime_inputs(...))`, grava
`MacroRegimeSnapshot(raw_regime, stress_score, signal_details, signal_breakdown)` e a
TAA aplica `apply_regime_hysteresis` (linha 1706) encadeando o regime EFETIVO anterior.

### 1.1 Sinais e fórmulas (`classify_regime_multi_signal`, linhas 453-747)

Cada sinal vira sub-score 0–100 via `_ramp(v, calm, panic)` (linear, clampado —
linhas 750-760). Sinais ausentes são descartados e os pesos base renormalizados
(linha 655-658).

| # | Sinal | Peso base | Série FRED | Fórmula (linhas) |
|---|---|---|---|---|
| 1 | vix | 0,10 | VIXCLS | ramp(VIX, 18→35) (543-545) |
| 2 | hy_oas | 0,12 | BAMLH0A0HYM2 | ramp(OAS, 2,5→6,0) (547-550) |
| 3 | dxy | 0,08 | DTWEXBGS | z-score vs 252 obs (std populacional, mín. 60 obs; 967-998) → ramp(z, 0→2) (552-555) |
| 4 | energy_shock | 0,12 | DCOILWTICO | max( max(ramp(z,0,5→3), ramp(−z,0,5→3)), ramp(\|RoC 3m\|, 0→50) ) (1294-1311) → identidade (565-567) |
| 5 | cfnai | 0,18 | CFNAI | ramp(−CFNAI, 0,20→0,70) (569-576) |
| 6 | yield_curve | 0,05 | DGS10−DGS2 | ramp(−spread, −1,0→0,5) (579-582) |
| 7 | baa_spread | 0,05 | BAA10Y | ramp(spread, 1,2→2,5) (584-587) |
| 8 | ff_roc | 0,05 | DFF | Δ 6m (obs ≤ data_última−180d; 917-964) → ramp(Δ, −0,5→1,5) (591-593) |
| 9 | sahm | 0,08 | SAHMREALTIME | ramp(Sahm, 0→0,50) (595-598) |
| 10 | icsa | 0,08 | ICSA | z da MA-4sem vs 52 MAs móveis (janela 400d, mín. 26 MAs, std≥1; 1063-1114) → ramp(z, 0,5→2,5) (600-603) |
| 11 | credit_impulse | 0,05 | TOTBKCR | RoC 6m (1117-1176) → ramp(−RoC, −0,5→2,0) (605-609) |
| 12 | permits | 0,04 | PERMIT | RoC 6m → ramp(−RoC, −5→20) (611-615) |

CPI (CPIAUCSL YoY, ancorado na obs do numerador; 1256-1286) é APENAS override de
INFLATION — não pontua stress.

### 1.2 Pesos dinâmicos (`_amplify_weights`, linhas 202-308)

`w_eff = w_base · (1 + α·(s/100)^γ)` com α=2, γ=2 → renormaliza para soma 1 → cap
w_max=0,35 com redistribuição proporcional sobre os não-capados (até 5 iterações).
Config de produção: `alpha=2.0, gamma=2.0, w_max=0.35` (defaults, linhas 661-666).
Sinal no máximo (s=100) triplica o peso base antes da renormalização.

### 1.3 Agregação e estados (linhas 679-728)

`stress_score = Σ sᵢ·w_eff_i` (0–100). Mapeamento: **≥50 → CRISIS** · senão
**CPI YoY ≥4% → INFLATION** · **≥25 → RISK_OFF** · senão **RISK_ON**. Hierarquia
CRISIS > INFLATION > RISK_OFF > RISK_ON. Default sem sinais: RISK_OFF (BUG-R5).

### 1.4 Histerese (`apply_regime_hysteresis`, linhas 355-450)

Escalação de severidade (RISK_ON 0 < INFLATION 1 < RISK_OFF 2 < CRISIS 3): imediata.
De-escalação: só se `stress < entry_threshold(prev) − 5` com
`DEFAULT_REGIME_SCORE_THRESHOLDS = {risk_off_entry: 25, crisis_entry: 50,
inflation_entry: 25}` (342-352). Transição para INFLATION vinda de não-CRISIS: passa
direto. Chamada de produção: risk_calc.py:1706, encadeando o efetivo anterior.

### 1.5 Mapeamento regime → alocação (`taa_band_service.py`, linhas 27-53)

Centros de equity do `DEFAULT_TAA_BANDS`: RISK_ON 0,52 · INFLATION 0,42 ·
RISK_OFF 0,38 · CRISIS 0,25 (resto em renda fixa/alternativos/caixa).

## 2. Port para QC e degradações documentadas

Projetos em `E:\investintell-light\lean-research\LegacyQuantEngine*/main.py`. Lógica
portada 1:1 (incl. ordem dos sinais, std populacional, arredondamentos, âncoras de
RoC na data da última observação, staleness gates de nível: VIXCLS/BAA10Y 5d,
SAHMREALTIME/CPIAUCSL 45d, CFNAI 75d). 4 variantes via `MODE`:

| Variante | Detector | Alocação (SPY/IEF) |
|---|---|---|
| `Faithful` | fiel completo (amplificação + histerese) | RISK_ON 100/0 · RISK_OFF e INFLATION 50/50 · CRISIS 0/100 (comparável aos baselines) |
| `Taa` | idem | centros TAA do legado: 52/48 · 38/62 · 42/58 · 25/75 |
| `NoAmp` | sem `_amplify_weights` (pesos base renormalizados) | padrão |
| `NoHyst` | sem histerese (regime cru) | padrão |

Degradações (dados, não lógica):

1. **hy_oas**: BAMLH0A0HYM2 irreproduzível (licença ICE → janela ~3y). Proxy:
   percentil móvel 5y do ratio HYG/IEF ajustado (mín. 252 obs), sub-score
   `ramp(1−percentil, 0,50→0,95)` — OAS 2,5 ≈ regime mediano → stress 0; OAS 6,0 ≈
   cauda dos 5% piores → stress 100. Vivo a partir de ~abr/2008 (93% dos dias).
2. **Vintage**: séries mensais FRED com revisões atuais; QC entrega a observação em
   obs_date+1 — ANTES da publicação real (CFNAI sai ~3 sem. depois do mês). Viés
   levemente A FAVOR do legado; mesmo assim ele perde.
3. **Warmup**: lookbacks semeados via `history()` no início (logs `SEED` confirmam
   todas as 11 séries preenchidas até 2006-12).

Sanidade dos sinais (logs `SIGNAL`, run Faithful): nenhum sinal morto — 12/12 com
≥93% de disponibilidade e max_score=100. Médias de sub-score reveladoras:
baa_spread **76,9** (!), energy_shock 39,0, dxy 33,4, ff_roc 27,6, permits 26,3,
curva 24,7 — vs vix 18,4, hy_oas 12,9, icsa 11,7, credit_impulse 7,9.

## 3. Resultados — janela completa 2007→2026

| Modelo | CAGR | Sharpe | Sortino | Max DD | Flips | Equity final |
|---|---|---|---|---|---|---|
| SPY buy-and-hold | 11,03% | 0,418 | — | 55,0% | 0 | $7,64M |
| Réplica degradada (4 sinais, pesos iguais) | 7,96% | 0,353 | 0,372 | 29,4% | 126 | $4,43M |
| Credit-only (produção Light) | **11,14%** | 0,481 | 0,509 | 25,7% | 46 | $7,79M |
| vote2of3 (candidato Light) | **12,30%** | 0,549 | — | 25,3% | ~17 | — |
| **Legado FIEL (mapa padrão)** | 6,97% | 0,381 | 0,407 | 24,1% | 131 | $3,70M |
| **Legado FIEL (bandas TAA)** | 6,55% | 0,449 | 0,500 | 21,4% | 134 | $3,43M |
| **Ablação: sem amplificação** | 10,12% | **0,555** | 0,570 | **20,9%** | 72 | $6,51M |
| **Ablação: sem histerese** | 7,00% | 0,369 | 0,390 | 25,6% | 289 | $3,72M |

Tempo por regime (dias de pregão, total 4.883):

| Variante | RISK_ON | RISK_OFF | INFLATION | CRISIS | stress médio |
|---|---|---|---|---|---|
| Fiel | 1.116 (23%) | 2.272 (47%) | 400 (8%) | 1.095 (22%) | 36,1 |
| Sem amplificação | 2.278 (47%) | 1.562 (32%) | 628 (13%) | 415 (8%) | 25,3 |
| Sem histerese | 1.394 (29%) | 2.156 (44%) | 469 (10%) | 864 (18%) | 36,1 |

**Diagnóstico.** O modelo fiel passa 77% do tempo defensivo (incl. 22% em CRISIS =
100% IEF). Duas causas se compõem:

1. **Calibração quebrada do baa_spread**: ramp(1,2→2,5) com BAA10Y médio pós-2007
   ≈2,3–2,5 → sub-score médio 76,9, stress quase permanente. dxy e energy_shock
   (z-scores simétricos) também rodam cronicamente elevados (33–39).
2. **A amplificação dinâmica** multiplica quadraticamente exatamente esses sinais
   cronicamente altos (s=77 → peso ×2,2 pré-renormalização), empurrando o composite
   (média 36,1) acima do gatilho de 25 na maior parte da história. É o "single-factor
   tyranny" que o cap w_max=0,35 deveria evitar — mas o problema não é um fator
   dominar, é o score médio inflar. Removendo SÓ a amplificação: CAGR +3,15 p.p.,
   Sharpe +0,17, flips 131→72, dias de CRISIS 1.095→415.

A histerese, ao contrário, ajuda: sem ela os flips explodem (289), o DD piora
(+1,5 p.p.) e o Sharpe cai (−0,012). Valor modesto, mas real, de anti-whipsaw.

## 4. Análise por crise (retorno da janela / max DD na janela)

Equity curves via `backtests/chart/read` (2.500 pontos; DD intra-janela levemente
suavizado pela amostragem — o DD da janela completa vem das estatísticas full-res).

| Janela | B&H | credit-only | vote2of3 | Legado fiel | Legado TAA | Sem amplif. | Sem hister. |
|---|---|---|---|---|---|---|---|
| GFC out/07–jun/09 | −37,9% / −54,8% | −7,1% / −24,0% | +3,1% / −9,8% | **+13,7% / −9,7%** | +1,2% / −9,3% | +4,0% / −9,7% | +10,6% / −9,6% |
| COVID 2020 (ano) | +17,6% / −31,2% | +0,6% / −22,4% | +6,0% / −19,0% | −1,0% / −10,6% | +8,6% / −7,6% | **+10,9% / −10,7%** | +2,1% / −10,8% |
| 2022 (ano) | −18,2% / −24,4% | −18,1% / −24,2% | −18,4% / −24,6% | −21,2% / −23,9% | −18,4% / −20,8% | **−17,6% / −20,8%** | −23,2% / −25,4% |

Leitura honesta: **na GFC o legado fiel foi o MELHOR modelo já testado**
(+13,7%/−9,7% — a amplificação escala rápido numa crise de crédito real e o CRISIS
de 100% IEF capturou o rally de Treasuries). O problema é o custo dessa agressividade
fora das crises: 2010–2019 o modelo "grita lobo" continuamente (CRISIS em 2010-12 e
2015-16) e perde a década de alta. Em 2022 NENHUM modelo protege (stress de crédito
nunca disparou; o legado ainda fica 50/50 via INFLATION, mas IEF caiu junto).

## 5. IDs de auditoria QC

| Projeto | Project ID | Backtest ID |
|---|---|---|
| LegacyQuantEngineFaithful | 32829189 | `1e4777dcc871bf76a27a684dfaac2279` |
| LegacyQuantEngineTaa | 32829193 | `f48e24a5d47b7455ff41ce47da1a536b` |
| LegacyQuantEngineNoAmp | 32829196 | `c52ead7ccbbc3b86db15324a230959c4` |
| LegacyQuantEngineNoHyst | 32829198 | `6f4aba787128f74bd3d84a1fdc2fc25e` |

Logs CLI e do algoritmo (FLIP/SUMMARY/SIGNAL):
`lean-research/storage/regimealt-logs/LegacyQuantEngine*.log` e
`LegacyQuantEngine{Faithful,TaaBands,NoAmp,NoHyst}-algolog.txt`. Script de extração:
`lean-research/storage/fetch_legacy_results.py`.

## 6. Veredito — o que do legado vai para os workers do Light?

1. **O composite legado fiel NÃO supera os modelos do Light — descartar.** Com o
   modelo COMPLETO (12 sinais, pesos dinâmicos, histerese, dados melhores do que o
   legado teria em produção por causa do vintage), o resultado é PIOR que a réplica
   degradada em CAGR (6,97% vs 7,96%) e muito pior que credit-only (11,14%) e
   vote2of3 (12,30%). A dúvida do dono está respondida: não era a réplica pobre que
   penalizava o legado — é o modelo.
2. **A amplificação dinâmica de pesos (o diferencial do legado) destrói valor — NÃO
   portar.** É o componente que explica a diferença: removê-la vale +3,15 p.p. de
   CAGR e +0,17 de Sharpe. Ela amplifica sinais mal calibrados (baa_spread com panic
   no nível MÉDIO da série) e mantém o sistema defensivo 77% do tempo.
3. **Histerese assimétrica: único componente com valor comprovado** (sem ela: flips
   131→289, Sharpe −0,012, DD +1,5 p.p.). Mas é remédio para um problema que o
   vote2of3 não tem (~17 flips). Vale portar apenas como utilitário de flip-control
   genérico nos workers, não como motivo para adotar o composite.
4. **Candidato condicional: o score graduado SEM amplificação** — Sharpe 0,555 (o
   maior de tudo que já testamos), max DD 20,9% (o menor), ao custo de −2,2 p.p. de
   CAGR vs vote2of3 e 72 flips. Se o produto exigir perfil de drawdown mínimo
   (mandatos conservadores), esta variante merece um worker; para o caso geral, o
   vote2of3 domina.
5. **Sinais individuais**: nenhum sinal do legado isoladamente justifica adoção —
   os de melhor comportamento (hy_oas/crédito, icsa) já estão no vote2of3/credit-only
   do Light. baa_spread, dxy e energy_shock estão miscalibrados (sub-score médio
   33–77) e qualquer reaproveitamento exigiria recalibração por percentil, não ramps
   fixos.

**Recomendação final: manter vote2of3 como modelo dos workers do Light; não portar o
composite nem a amplificação do legado; opcionalmente extrair (a) a histerese como
utilitário e (b) a variante sem amplificação como modo "low-drawdown" se houver
demanda de produto.**
