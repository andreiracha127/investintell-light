# Implementação + backtest — histerese assimétrica e modo low-drawdown no detector de crédito

**Data:** 2026-06-13 · **Métodos:** implementação nos workers (`credit_regime`) e no
Light (`macro_regime`), com validação por backtests cloud na QuantConnect via API v2
(creds do lean CLI, org `2e1c086e6a6966746002f1c32c2cbbfd`), janela 2007-01-01 →
2026-06-01, $1M, diário, SPY/IEF, mesmas convenções de execução dos baselines
(flip no fechamento de T → ordem no evento seguinte, fill na abertura; vendas antes de
compras) · **Resultado: a histerese assimétrica entrega o que o legado prometia — flips
46→26 (−43%) e Max DD 25,7%→25,0% no detector de crédito, ao custo modesto de −0,48 p.p.
de CAGR e −0,02 de Sharpe. O score graduado credit-only NÃO replica o perfil
Sharpe 0,555 / DD 20,9% (que é do composite de 12 sinais SEM amplificação, não de um
sinal isolado): como detector credit-only ele é DOMINADO pela histerese (mesmo DD, mais
flips, pior Sharpe/CAGR). Recomendação: ligar a histerese (`CREDIT_REGIME_EXIT_PCTL=0.25`)
como refinamento de produção; a máquina graduada fica disponível para alimentar o score
do composite NoAmp se o produto exigir o perfil de drawdown mínimo.**

> Implementa as recomendações §6.3 (histerese como utilitário de flip-control) e §6.4
> (variante sem amplificação como modo "low-drawdown") de
> `2026-06-12-legacy-quant-engine-backtest.md`, e a §5.2 (detector de crédito binário
> COM histerese) de `2026-06-11-macro-regime-backtest.md`.

---

## 1. O que foi implementado

### 1.1 Worker `credit_regime` (repo investintell-datalake-workers)

`src/workers/credit_regime.py` — engine pura, parametrizada e configurável por env
(sem deploy de código):

- **Histerese assimétrica (`next_state`)**: entra em `risk_off` quando `ratio < p_entry`
  (`CREDIT_REGIME_ENTRY_PCTL`, default p20); só volta a `risk_on` quando recupera
  `≥ p_exit` (`CREDIT_REGIME_EXIT_PCTL`, default == entry → detector binário validado
  inalterado; defina 0,25 para ligar o anti-whipsaw). Exigir o cruzamento da banda mais
  alta evita o whipsaw em torno de um único limiar.
- **`stress_score` 0–100 graduado (`stress_score`)**: ramp linear do rank do ratio na
  janela (`rank ≥ calm → 0`, `rank ≤ panic → 100`; `CREDIT_REGIME_STRESS_CALM_PCTL`/
  `PANIC_PCTL`, default 0,50/0,05). Espelha o sub-score de crédito do legado sem
  amplificação. Materializado por linha; **não altera o estado binário**.
- `percentile_20` generalizado para `percentile(window, q)`; `compute_regime` aceita
  `entry_pctl`/`exit_pctl`/`calm`/`panic`.

`schemas/credit_regime.sql` — colunas aditivas idempotentes `p_exit_5y numeric(14,8)` e
`stress_score numeric(6,3)` (ALTER ADD COLUMN IF NOT EXISTS; aplicadas no cloud via o
`ensure_schema` do próprio worker). CHECK de `state` segue binário.

Testes (`tests/test_credit_regime.py`): histerese simétrica == memoryless; assimétrica
segura `risk_off` até recuperação material; redução de flips no whipsaw (40→2 no fixture);
`stress_score` ramp/monotonicidade/warmup; backward-compat (default = 2 flips no episódio).
**19/19 puros verdes**; integração Tiingo+cloud reconfirma Lehman/COVID em `risk_off`,
2022 sem disparo, 44 flips (≈ os 46 validados), com a migração aplicada.

### 1.2 Light (repo investintell-light)

- `app/services/macro_regime.py`: lê `stress_score`/`p_exit_5y`; `graded_state(score)`
  mapeia o score em `risk_on|caution|risk_off` por bandas (`MACRO_REGIME_CAUTION_SCORE`
  /`RISK_OFF_SCORE`, default 25/50); flag `MACRO_REGIME_LOW_DRAWDOWN_MODE`.
- `app/api/routes/macro.py`: `GET /macro/regime?low_drawdown_mode=true|false` (override
  por requisição; default = env). A resposta expõe `mode`, `state` (binário OU graduado),
  `binary_state`, `graded_state`, `stress_score`, `bands` e `signal.p_exit_5y`.
- Default = `binary` (detector validado, retrocompatível). **6/6 testes verdes.**

### 1.3 Parametrização (sem deploy)

| Variável | Onde | Default | Efeito |
|---|---|---|---|
| `CREDIT_REGIME_ENTRY_PCTL` | worker | 0.20 | banda de entrada (risk_off) |
| `CREDIT_REGIME_EXIT_PCTL` | worker | == entry | banda de saída (risk_on); >entry liga histerese |
| `CREDIT_REGIME_STRESS_CALM_PCTL` / `PANIC_PCTL` | worker | 0.50 / 0.05 | endpoints do ramp do score |
| `MACRO_REGIME_LOW_DRAWDOWN_MODE` | Light | false | default binário vs graduado |
| `MACRO_REGIME_CAUTION_SCORE` / `RISK_OFF_SCORE` | Light | 25 / 50 | bandas do estado graduado |

## 2. Backtests — janela completa 2007→2026 (HYG/IEF proxy)

Projeto `MacroRegimeHYOnly` (32791988), engine portada 1:1 do worker, modo via constante
`MODE`. Composite (32791986) re-rodado como referência.

| Modelo | CAGR | Sharpe | Sortino | Max DD | Flips |
|---|---|---|---|---|---|
| SPY buy-and-hold (ref) | 11,03% | 0,418 | — | 55,0% | 0 |
| MacroRegimeComposite (4 sinais — REFUTADO) | 7,96% | 0,353 | — | 29,4% | 126 |
| `hy_only` baseline (detector atual) | 10,97% | 0,474 | 0,50 | 25,7% | 46 |
| **`hy_only_hysteresis` (entry p20 / exit p25)** | 10,49% | 0,451 | 0,474 | **25,0%** | **26** |
| `hy_only_graded` (low-drawdown credit-only) | 9,82% | 0,45 | 0,478 | 25,0% | 92 |
| LegacyQuantEngineNoAmp (ref do alvo 0,555/20,9%) | 10,12% | 0,555 | 0,570 | 20,9% | 72 |

**Leitura.**

1. **Histerese (recomendação §6.3 — único componente do legado com valor):** confirmada.
   Flips 46→26 (−43%), Max DD 25,7→25,0%, ao custo de −0,48 p.p. de CAGR e −0,02 de
   Sharpe. É o trade-off anti-whipsaw esperado, na direção certa em todas as métricas de
   estabilidade — e ataca exatamente a patologia dos 289 flips do `NoHyst` legado.
2. **Score graduado credit-only NÃO atinge 0,555/20,9%.** Esse perfil é do composite de
   12 sinais SEM amplificação (`NoAmp`, backtest `c52ead7ccbbc3b86db15324a230959c4`), não
   de um sinal isolado. Como detector credit-only, o graded é DOMINADO pela histerese:
   mesmo DD (25,0%), porém **mais** flips (92, pois a banda `caution` dobra as transições
   por episódio) e pior Sharpe/CAGR. A máquina graduada está correta e plugada; o caminho
   para o alvo é alimentá-la com o score do composite NoAmp, não com o crédito sozinho.
3. **Composite (4 sinais) revalidado** em 0,353 / 29,4% / 126 flips — idêntico ao
   relatório anterior, confirmando a fidelidade do harness (e que segue refutado).

## 3. Recomendação

- **Ligar a histerese em produção** como refinamento: `CREDIT_REGIME_EXIT_PCTL=0.25`
  (entry segue 0.20). Default do código permanece conservador (exit==entry = detector
  validado) para não mudar silenciosamente o sinal de produção — a melhoria é opt-in.
- **Modo low-drawdown**: expor via `GET /macro/regime?low_drawdown_mode=true` como badge
  graduado (informativo/UX). Para usá-lo como GATILHO de alocação com o perfil de DD
  mínimo, alimentar o `stress_score` a partir do composite NoAmp (frente futura), não do
  crédito isolado — onde a histerese binária domina.
- Nota: o sucessor de produção do detector segue sendo o `vote2of3`
  (`2026-06-12-regime-detector-alternatives-backtest.md`, Sharpe 0,549 / DD 25,3%); a
  histerese aqui é um utilitário ortogonal, aplicável também aos votos.

## 4. Auditoria — IDs QC

| Variante | Project | Backtest ID |
|---|---|---|
| `hy_only` (baseline) | 32791988 | `cc66ff93894770c2338505796e735dbe` |
| `hy_only_hysteresis` | 32791988 | `14c739f369a8e022d1eaf19e48db19b8` |
| `hy_only_graded` | 32791988 | `89bb12fee454645857ba5e8a08f9daa1` |
| `composite` (revalidação) | 32791986 | `182cc9008b65a6d531f924390e66167b` |

Driver de extração: `lean-research/storage/run_hyonly_variants.py`
(resultados em `lean-research/storage/regimealt-logs/hyonly-variants-results.json`).
Projeto cloud restaurado para `MODE=hy_only` ao fim do run.

## 5. Protótipo: NoAmp graduado vs vote2of3 (o alvo 0,555/20,9% vem de ONDE?)

Para testar se a máquina graduada do Light, alimentada pelo composite NoAmp, reproduz o
perfil low-drawdown — e como ela bate o `vote2of3` — rodei 3 backtests com convenções
idênticas. `no_amp_graded` = NoAmp SEM o override de INFLATION (CPI YoY≥4 → 50/50), ou
seja, o mapa graduado puro `≥50 risk_off / ≥25 caution / else risk_on` **idêntico às
bandas do Light**.

| Modelo | CAGR | Sharpe | Sortino | Max DD | Flips |
|---|---|---|---|---|---|
| `no_amp` (NoAmp completo, COM override INFLATION) | 10,12% | 0,555 | 0,570 | **20,9%** | 72 |
| `no_amp_graded` (SEM INFLATION = bandas do Light) | 10,58% | **0,576** | 0,596 | 25,3% | 79 |
| `vote2of3` | **12,30%** | 0,549 | 0,580 | 25,3% | **16** |

Por crise (retorno% / max DD% na janela):

| Janela | `no_amp` | `no_amp_graded` | `vote2of3` |
|---|---|---|---|
| GFC out/07–jun/09 | +4,0 / −9,7 | +4,0 / −9,7 | +3,1 / −9,8 |
| COVID 2020 | +10,9 / −10,7 | +10,9 / −10,7 | +6,0 / **−19,0** |
| 2022 | **−17,6 / −20,8** | −22,1 / −25,1 | −19,7 / −24,6 |

**Achado central — o 20,9% NÃO vem da máquina graduada; vem do override de INFLATION
pegando 2022.** `no_amp` e `no_amp_graded` protegem GFC e COVID de forma IDÊNTICA
(+4,0/−9,7 e +10,9/−10,7); a única diferença está em 2022, quando os sinais de stress
de crédito ficaram cegos (2022 não foi crise de crédito) e SÓ o gatilho de CPI (YoY≥4 →
50/50) cortou o drawdown (−20,8% vs −25,1%). Removendo o override (= bandas do Light), o
DD sobe para 25,3% — o MESMO do vote2of3. O estado atual confirma: `no_amp` está em
INFLATION agora (2026), `no_amp_graded` e `vote2of3` em risk_on.

**Leitura comparativa.**

1. **vote2of3 segue dominando o caso geral**: +1,7 a +2,2 p.p. de CAGR sobre as duas
   variantes NoAmp, **1/5 dos flips** (16 vs 72–79), DD igual ao `no_amp_graded` (25,3%)
   e Sharpe equivalente (0,549). Fraqueza única: crashes rápidos (COVID −19,0% vs −10,7%
   das variantes graduadas com sleeve 50/50).
2. **`no_amp_graded` tem o melhor Sharpe (0,576)** — dropar o override deixa ele 100% SPY
   nos regimes de CPI alto sem crise (captura mais upside) — mas é **dominado pelo
   vote2of3** em CAGR e flips, sem ganho de DD. Como detector standalone, não se promove.
3. **O perfil de drawdown mínimo (20,9%) é real, mas a alavanca é um overlay de
   inflação/CPI, não o score graduado de crédito.** É barato de adicionar (regra CPI
   YoY≥4 → de-risk 50/50) SOBRE qualquer detector.

**Recomendação atualizada.**

- Caso geral: **vote2of3** (já era o veredito; confirmado e reforçado).
- Min-DD como requisito de produto: NÃO empilhar sinais nem trocar para o composite
  graduado — adicionar um **overlay de inflação (CPI YoY≥4 → 50/50)** sobre o vote2of3. O
  experimento natural é `vote2of3 + inflation_overlay`: tende a manter o CAGR do vote2of3
  e fechar o gap de DD em 2022/COVID. (Não rodado aqui — próxima frente, se desejado.)
- A máquina graduada que implementei está correta e reproduz a proteção GFC/COVID; ela
  vira útil de verdade quando combinada com o overlay de inflação, não isolada.

IDs de auditoria QC (protótipo): `no_amp` `3ba9ac5fc9f63c89aaa207917625e725` ·
`no_amp_graded` `5009441be00ca1dc9118c0404f3372d3` ·
`vote2of3` `ce47e3556323273ecf859a05c15fffa2` (projetos 32829196 e 32827549). Driver:
`lean-research/storage/run_noamp_vs_vote.py`
(`regimealt-logs/noamp-vs-vote-results.json`). Modo `no_amp_graded` adicionado ao port
(gate `use_inflation`, default True preserva o NoAmp; cloud restaurado para `MODE=no_amp`).

## 6. Experimento decisivo: vote2of3 + overlay de inflação (CPI)

Hipótese do §5: se a alavanca low-drawdown é o gatilho de CPI pegando 2022, ele deve
transplantar para o vote2of3 sem matar seu CAGR. Implementei `vote2of3_inflation` =
vote2of3 + overlay (CPI YoY ≥ 4,0% → caution 50/50; sai < 3,5%, histerese; risk_off por
votos mantém 0/100). **Controle:** o `vote2of3` puro reproduziu 0,549 / 25,3% / 12,30% /
16 flips EXATOS — prova de que o overlay não tocou na lógica de votos.

| Modelo | CAGR | Sharpe | Max DD | Flips |
|---|---|---|---|---|
| `vote2of3` (controle) | **12,30%** | 0,549 | 25,3% | **16** |
| `vote2of3_inflation` | 11,81% | **0,551** | 25,3% | 20 |
| (ref) `no_amp` composite completo | 10,12% | 0,555 | **20,9%** | 72 |

Por crise (retorno / max DD):

| Janela | `vote2of3` | `vote2of3_inflation` |
|---|---|---|
| GFC out/07–jun/09 | +3,1 / −9,8 | **+7,1** / −9,7 |
| COVID 2020 | +6,0 / −19,0 | +6,0 / −19,0 |
| 2022 | −19,7 / −24,6 | **−17,6 / −20,8** |

**Leitura.** O overlay faz EXATAMENTE o que foi desenhado para fazer: em 2022 o DD da
janela cai de −24,6% para **−20,8%** (idêntico ao do `no_amp` — mesmo de-risk 50/50 por
CPI), e a GFC melhora (+3,1→+7,1, o CPI alto de 2008 de-riscou antes dos votos virarem).
Sharpe sobe de leve (0,549→0,551), ao custo de −0,49 p.p. de CAGR (12,30→11,81) e +4
flips. **Mas o max DD da janela completa fica em 25,3% — NÃO chega aos 20,9% do `no_amp`.**

Por quê: o 20,9% do `no_amp` não vem só do gatilho de 2022 — vem da defensividade AMPLA
do composite (12 sinais o deixam de-riscado boa parte do tempo, curva mais suave, porém
CAGR 10,12%). O overlay só adiciona o remendo de 2022 ao vote2of3; mantém o caráter dele
(quase sempre 100% investido, CAGR alto). O drawdown global do vote2of3 é dominado pelo
pico-a-vale 2021→2022 que o overlay suaviza só parcialmente.

## 7. Veredito final — três pontos numa fronteira eficiente

1. **CAGR + estabilidade (caso geral): `vote2of3` puro.** 12,30% / 0,549 / 25,3% / 16
   flips. Domina em retorno e tem 1/4–1/5 dos flips dos composites.
2. **Drawdown mínimo (mandato conservador): `no_amp` composite completo.** 20,9% (o menor
   testado), Sharpe 0,555, mas paga −2,2 p.p. de CAGR e 72 flips. A alavanca é a
   defensividade ampla, não o score graduado isolado.
3. **Meio-termo: `vote2of3_inflation`.** Mantém quase todo o CAGR do vote2of3 (11,81%),
   melhora 2022/GFC e o Sharpe (0,551, o melhor do trio vote), por +4 flips — mas NÃO
   entrega os 20,9%. Vale só se proteção a estagflação tipo-2022 for explicitamente
   desejada; caso contrário o vote2of3 puro domina.

Recomendação: **manter `vote2of3` como detector de produção**; oferecer `no_amp` como
"perfil conservador" opcional se houver demanda de DD mínimo; o overlay de inflação é um
add-on barato e defensável, mas de ganho marginal — não um substituto.

IDs QC (overlay): `vote2of3` controle `a47f09f651ba3a8c53a859733fece44f` ·
`vote2of3_inflation` `773562131621b1c7865d9b76ab4d373e` (projeto 32827549). Driver:
`lean-research/storage/run_vote_inflation.py`
(`regimealt-logs/vote-inflation-results.json`). Modo `vote2of3_inflation` adicionado ao
RegimeAltVote (gated; cloud restaurado para `MODE=vote2of3`).
