# Backtest QC — detector de macro-regime: composite legado vs sinal único de crédito

**Data:** 2026-06-11/12 · **Métodos:** backtests cloud na plataforma QuantConnect via
lean CLI (workspace `lean-research/`, conta admin@investintell.com, org
`2e1c086e6a6966746002f1c32c2cbbfd`); 3 projetos (benchmark SPY buy-and-hold,
composite de 4 sinais réplica do legado, ablação sinal-único de crédito); janela
2007-01-01 → 2026-06-01, $1M, resolução diária; logs e equity curves extraídos via
API v2 (`backtests/read/log`, `backtests/chart/read`) com as credenciais do CLI ·
**Resultado: o composite NÃO captura sinal (categoria c — confirma a experiência do
legado: Sharpe 0,353 vs 0,418 do buy-and-hold, CAGR −3,1 p.p., e em 2022 teve drawdown
PIOR que buy-and-hold); mas o sinal ÚNICO de stress de crédito captura (categoria a:
Sharpe 0,481, max DD 25,7% vs 55,0%, CAGR igual/superior). O problema do legado não são
os sinais — é o composite. Bônus estrutural: o hy_oas do legado nem é mais reproduzível
via FRED (séries ICE BofA agora limitadas a ~3 anos rolling).**

> Gate definido no §6 ("Frente B — re-escopada") de
> `2026-06-11-lean-research-rebalance-macro-lookthrough.md`. Este doc decide se o Light
> consome `macro_regime_snapshot` do legado, re-pesa, ou parte para o HMM (B5).

---

## 1. Estratégias testadas

Alocação por estado: `risk_on` = 100% SPY · `caution` = 50% SPY + 50% IEF ·
`risk_off` = 100% IEF. Flip detectado no fechamento de T → ordens no evento seguinte
(fill na abertura seguinte; conservador, sem lookahead). Vendas antes de compras;
leverage 4 nos ativos só como folga de margem (targets nunca passam de 100%).

**Composite (réplica honesta do legado, 4 sinais; risk_off se ≥2 ativos, caution se 1):**

| Sinal | Fonte QC | Regra risk-off |
|---|---|---|
| VIX | FRED `VIXCLS` (auth code) | > 25 por ≥ 5 observações |
| Stress de crédito | **proxy de preço HYG/IEF** (ver §3) | ratio ajustado < p20 móvel 5y (mín. 252 obs) |
| Curva de juros | `USTreasuryYieldCurveRate` (10y−2y) | invertida por ≥ 20 observações |
| Initial claims | FRED `ICSA` (auth code) | MA 4 semanas > 1,15× mínimo móvel 12 meses |

**Ablação (sinal único):** mesma mecânica, guiada APENAS pelo sinal de crédito
(risk_off/risk_on binário, sem caution).

Degradações vs legado (documentadas): sahm, cfnai, dxy, permits e ff_roc não têm fonte
implementável no QC → composite reduzido aos 4 sinais acima; hy_oas substituído por
proxy de preço (§3); pesos iguais em vez de dinâmicos.

## 2. Resultados (janela completa 2007→2026)

| Métrica | SPY buy-and-hold | Composite (4 sinais) | Crédito só |
|---|---|---|---|
| CAGR | **11,03%** | 7,96% | **11,14%** |
| Sharpe | 0,418 | 0,353 | **0,481** |
| Sortino | 0,424 | 0,372 | **0,509** |
| Max drawdown | 55,0% | 29,4% | **25,7%** |
| Recuperação do max DD (dias) | 1.772 | 1.296 | **709** |
| Beta | 1,00 | 0,45 | 0,61 |
| Flips de estado | 0 | **126** | 46 |
| Equity final ($1M) | $7,64M | $4,43M | **$7,79M** |

Tempo em estado (composite): risk_on 68% · caution ~20% · risk_off ~12%.
Crédito só: risk_off apenas 6,7% do tempo — protege pouco tempo, no momento certo.

### 2.1 Por crise (equity curves via `backtests/chart/read`; DD da janela)

| Janela | SPY B&H | Composite | Crédito só |
|---|---|---|---|
| GFC out/2007–jun/2009 — max DD | −54,8% | **−21,3%** | −24,0% |
| GFC — retorno da janela | −37,9% | −14,1% | **−7,1%** |
| COVID 2020 — max DD | −31,2% | **−14,0%** | −22,4% |
| COVID 2020 — retorno do ano | **+17,6%** | −6,9% | +0,6% |
| 2022 — max DD | −24,4% | **−28,5% (pior!)** | −24,2% |
| 2022 — retorno do ano | −18,2% | −26,3% | −18,1% |

Leitura: o composite protege 2008/2020 mas **devolve tudo (e mais) no ruído**: perde a
recuperação de 2020 (−6,9% num ano em que o SPY fez +17,6%), e em 2022 fica PIOR que
buy-and-hold — whipsaw de VIX (13 flips só em 2022) somado à curva invertida que o
prendeu em caution (50% IEF) de ago/2022 a ago/2024, justo com IEF caindo. O sinal de
crédito sozinho ficou risk-off contínuo 31/07/2008→16/04/2009 (pegou Lehman inteiro) e
09/03→01/06/2020 (pegou COVID), e em 2022 simplesmente não disparou (≈ B&H, sem custo).

### 2.2 Diagnóstico do composite

- **VIX é a fonte do ruído**: ~80% dos flips são streaks de VIX>25 que entram/saem de
  caution em dias. Cada ida a caution custa metade da recuperação subsequente.
- **Curva invertida ≥20d é sinal de horizonte errado** para alocação tática: inversão
  2022–2024 durou 2 anos (um único "sinal ativo" de 500 pregões) — penaliza o carrego
  sem timing de saída.
- **Percentil móvel dessensibiliza após crise**: a janela 5y contendo o crash de 2020
  elevou o teto do p20/p80 e o sinal de crédito não disparou em 2022 (limitação
  conhecida do desenho do legado também).

## 3. Descoberta estrutural: hy_oas não é mais reproduzível via FRED

Cadeia verificada empiricamente (impacta o worker `macro_ingestion` do INGESTION_DESIGN):

1. FRED cacheado do QC: `BAMLH0A0HYM2` só entrega dados a partir de ~2024 (backtest v1
   `25e4e0798ec598383b71fe3a3f587620`: sinal hy nunca ativo em 2008/2020; 1º flip
   04/04/2025).
2. API FRED direta (key do worker): `fred/series` reporta `observation_start=2023-06-12`
   — **as séries ICE BofA no FRED viraram janela rolling de ~3 anos** (mudança de
   licença ICE). `fredgraph.csv` idem (ignora `cosd`).
3. Datalake (`macro_data` no Tiger `t83f4np6x4`): `BAMLH0A0HYM2` só de 2016-09 em diante
   (2.551 obs) — não cobre 2008.

→ Degradação adotada: **proxy de preço HYG/IEF** (closes ajustados, ratio < p20 móvel
5y, mín. 252 obs; HYG existe desde 2007-04 → sinal vivo a partir de ~abr/2008). É
metodologicamente até preferível para produção: 100% derivável de preços que já temos
(Tiingo), sem dependência da licença ICE/FRED. VIXCLS e ICSA seguem disponíveis com
histórico completo via FRED com auth code (`Fred.set_auth_code`; key gratuita do worker).

## 4. Auditoria — IDs QC

| Projeto | Project ID | Backtest (final) | Backtest ID |
|---|---|---|---|
| MacroRegimeBuyHold | 32791990 | `bh-spy-2007-2026` | `099e0d46736defeee37833dd661051fe` |
| MacroRegimeComposite | 32791986 | `composite-v4-hygproxy` | `1f73146d45e394edff9183c6cb108a5c` |
| MacroRegimeHYOnly | 32791988 | `credit-only-v4-hygproxy` | `856a7e9f643a8c44501456e6a328cd86` |

Iterações intermediárias (mantidas para auditoria da descoberta do §3):
composite v1 FRED-cacheado `25e4e0798ec598383b71fe3a3f587620` (78 flips, hy morto);
composite v2 FRED-auth+ICSA `30c00a0b1656a7e6ec4846db5c4069ef`; hy-only v1/v2/v3
`a9e257277f88cefc97d79d65d5bd988a` / `14a2a96d270699b6ed9a9507fc76a587` /
`30e0b388e94b6a9e2abfd74879906da1` (v3 = tentativa fredgraph.csv, 0 dados).
Código local: `lean-research/MacroRegime{Composite,HYOnly,BuyHold}/main.py`
(+ `FredCsvDebug` local). Equity curves do §2.1 amostradas em ~2.450 pontos pelo chart
da QC (DDs por janela levemente subestimados vs diário; os max DD da tabela §2 são os
exatos do relatório QC).

## 5. Veredito e recomendação para a Frente B

**Veredito: (c) para o composite, (a) para o sinal de crédito isolado.**

1. **Não consumir o composite do legado** (`macro_regime_snapshot.raw_regime`) como
   gatilho de alocação/rebalance — o backtest confirma a experiência do dono: o
   composite de pesos ~iguais com VIX/curva destrói valor (Sharpe e CAGR piores que não
   fazer nada, e falha exatamente numa das crises-alvo, 2022). Como **badge informativo**
   no cockpit o `stress_score` pode continuar, mas sem acionar nada.
2. **Re-pesar = reduzir ao sinal de crédito.** O caminho com evidência é um detector
   mínimo: stress de crédito por proxy de preço (HYG/IEF ou equivalente em OAS quando
   disponível) como **único** gatilho de modulação, binário, com histerese. Ele melhorou
   Sharpe E drawdown E recuperação sem custo de CAGR. VIX e curva entram no máximo como
   contexto/explicabilidade, não como votos.
3. **B5 (HMM) continua válido**, mas o baseline a bater passa a ser o sinal de crédito
   (Sharpe 0,481 / DD 25,7%), não o composite nem buy-and-hold. Se o HMM não superar
   isso out-of-sample, não se promove.
4. **Ação no datalake** (fora deste repo): o `macro_ingestion` deve assumir que
   `BAMLH0A0HYM2` (e demais BAML*) só terá ~3 anos rolling no FRED — preservar o
   histórico já acumulado desde 2016 (não sobrescrever por janela) e adicionar o ratio
   HYG/IEF como série derivada de regime.
