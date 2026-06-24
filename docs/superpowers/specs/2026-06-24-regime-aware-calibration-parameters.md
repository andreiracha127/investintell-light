# Regime-Aware Calibration Parameters

Data: 2026-06-24

Este documento lista os parâmetros que ainda precisam de calibração depois do Plano C. A estrutura backend está fechada; o que falta é parameter freeze em duas frentes:

1. A3: classificador macro no harness.
2. A4: política/otimizador no harness.

A5 é ativação atomica somente depois do freeze.

## Principio De Modelo

O eixo calibrado do modelo é `profile`, com tres mestres canonicos:

- `conservative`
- `moderate`
- `aggressive`

`mandate` equivale ao IPS do cliente. Ele não é eixo de calibração. Mandate/IPS só deve carregar constraints individuais de construção do portfolio, como caps por posição, pisos, limites por sleeve, restrições de concentração ou overlap.

Para `regime_aware`, CVaR é condição interna do profile, não do mandate. O cliente não passa `cvar_limit`; o backend rejeita `cvar_limit` em `regime_aware`. O motor sempre roda BL max-utility com hard CVaR calibrado pelo profile.

## A3 - Classificador Macro

Estes itens precisam ser calibrados no harness macro-release. O backend atual apenas consome o snapshot materializado e filtrado.

| Bloco | Parametros a calibrar | Config atual |
|---|---|---|
| Transformações por familia | Fórmulas exatas por familia: z-score, YoY/MoM, difusão, surpresa, nivel vs tendencia, winsor/clip, lag/release handling | Ainda não está no backend |
| Pesos das familias | Peso relativo de growth, inflation, labor, credit, liquidity etc. | Ainda não está no backend |
| Escala dos scores | Normalização final de `growth_score` e `inflation_score` | Backend só consome scores prontos |
| `u_floor` | Piso operacional para confiança/validade | Ainda não está no backend |
| Hysteresis | `AXIS_ENTER` e `AXIS_EXIT` por eixo growth/inflation | Ainda não está no backend |
| Confidence minima | Limiar para publicar quadrante consumivel | Backend exige `candidate_confidence >= 0.70` |
| Abstenção | Regras de `invalid`/`abstain` por cobertura, vintage instability ou baixa confiança | Backend só aceita `status_at_compute = 'valid'` |
| Freshness/PIT | Regras de disponibilidade e validade temporal | Backend exige `available_at <= decision_time` e `stale_after > decision_time` |
| Model version | Versão oficial consumida pelo builder | `macro_quadrant_us_v1` |
| Gate freshness | Atraso maximo do gate materializado | `GATE_MAX_LAG_BUSINESS_DAYS = 5` business days |

Critérios de calibração A3:

- estabilidade de vintage;
- cobertura historica;
- taxa de `valid`;
- taxa de abstenção;
- flips por ano;
- duração media dos quadrantes;
- divergencias macro-release vs market-implied.

Proibido calibrar A3 contra CAGR, Sharpe ou retorno. A confidence é proxy operacional, não probabilidade de acerto financeiro.

### Constantes Market-Implied Mantidas Para Paridade

Estas constantes existem em `taa_bands.py`, mas o runtime `regime_aware` consome o quadrante oficial materializado pelo worker.

| Parametro | Valor atual |
|---|---:|
| `G_LOOK` | 126 |
| `I_LOOK` | 126 |
| `GATE_DD` | 0.06 |
| `EMA_HALFLIFE_DAYS` | 5 |
| `MAX_DAILY_SHIFT` | 0.03 |
| `VG_BETA` | 1.5 |
| `BG_COEF` | 1.0 |

## A4 - Politicas E Otimizador

### Utility, CVaR E Beta

| Parametro | Conservative | Moderate | Aggressive |
|---|---:|---:|---:|
| `PROFILE_GAMMA` | 13.50 | 4.75 | 1.90 |
| `PROFILE_CVAR_LIMIT` diario 95% | 0.016 | 0.022 | 0.030 |
| `PROFILE_PORTFOLIO_BETA_CAPS` | 0.30 | 0.55 | 0.85 |

Outros parametros globais:

| Parametro | Valor atual |
|---|---:|
| `DELTA_MARKET` | 2.5 |
| `DEFAULT_CVAR_ALPHA` | 0.95 |

CVaR é medido em perdas diarias cruas, sem anualização.

### Gate Overlay

Shape comum risk-off:

| Parametro | Valor atual |
|---|---:|
| `cvar_tightening` | 0.50 |
| `beta_tightening` | 0.30 |
| `risk_assets_reduction` | 0.10 |

Intensidade por profile:

| Profile | Intensity | CVaR mult risk-off | Beta mult risk-off | Risk-assets cap reduction |
|---|---:|---:|---:|---:|
| conservative | 0.50 | 0.75 | 0.85 | 5pp |
| moderate | 0.70 | 0.65 | 0.79 | 7pp |
| aggressive | 1.00 | 0.50 | 0.70 | 10pp |

Efeito atual em risk-off:

| Profile | CVaR efetivo risk-off | Beta cap efetivo risk-off |
|---|---:|---:|
| conservative | 0.0120 | 0.2550 |
| moderate | 0.0143 | 0.4345 |
| aggressive | 0.0150 | 0.5950 |

`bl_view_confidence_multiplier` em risk-off é `0.0` em todos os perfis. Isto significa views omitidas e `mu = pi`.

### Sleeves Estruturais

O Policy Core tem 7 sleeves:

- `cash`
- `equity`
- `fixed_income`
- `thematic`
- `alternatives`
- `gold`
- `long_short`

`fixed_income` é um sleeve, não uma categoria única. Ele contém cinco strategy labels/categorias economicas:

| Label | Categoria | Benchmark |
|---|---|---|
| 3.1 | Government Bond | GOVT |
| 3.2 | Investment Grade Bond | LQD |
| 3.3 | High Yield Bond | HYG |
| 3.4 | Inflation-Linked Bond | TIP |
| 3.5 | Intermediate-Term Bond | BND |

### Half-Widths Atuais

| Sleeve | Half-width |
|---|---:|
| cash | 4pp |
| equity | 4pp |
| fixed_income | 6pp |
| thematic | 1pp |
| alternatives | 3pp |
| gold | 3pp |
| long_short | 3pp |

Os half-widths são materializados por policy e clampados quando o centro está no limite. Exemplo: `conservative/contraction/thematic` tem centro `0%`, logo half-width efetivo `0pp`.

### Centros Atuais Por Profile E Quadrante

Valores em percentual do portfolio.

| Profile | Quadrant | Cash | Equity | Fixed Income | Thematic | Alternatives | Gold | Long/Short | Risk Assets Cap | Defensive Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| aggressive | recovery | 5.00 | 33.00 | 31.00 | 8.00 | 5.00 | 10.00 | 8.00 | 45.00 | 28.00 |
| aggressive | expansion | 8.25 | 26.80 | 22.68 | 7.22 | 12.37 | 13.40 | 9.28 | 42.00 | 33.00 |
| aggressive | slowdown | 10.00 | 26.00 | 21.00 | 4.00 | 14.00 | 14.00 | 11.00 | 35.00 | 45.00 |
| aggressive | contraction | 16.00 | 18.00 | 35.00 | 2.00 | 6.00 | 11.00 | 12.00 | 25.00 | 54.00 |
| moderate | recovery | 10.00 | 23.00 | 38.00 | 6.00 | 5.00 | 10.00 | 8.00 | 34.00 | 43.00 |
| moderate | expansion | 13.40 | 16.49 | 29.91 | 5.15 | 12.37 | 13.40 | 9.28 | 30.00 | 48.00 |
| moderate | slowdown | 15.00 | 17.00 | 27.00 | 3.00 | 13.00 | 14.00 | 11.00 | 25.00 | 52.00 |
| moderate | contraction | 22.00 | 10.00 | 41.00 | 1.00 | 5.00 | 11.00 | 10.00 | 15.00 | 62.00 |
| conservative | recovery | 14.02 | 4.67 | 42.06 | 2.80 | 4.67 | 16.82 | 14.96 | 20.00 | 62.00 |
| conservative | expansion | 16.22 | 4.50 | 32.43 | 1.80 | 10.81 | 18.92 | 15.32 | 18.00 | 67.00 |
| conservative | slowdown | 20.00 | 7.00 | 34.00 | 1.00 | 10.00 | 15.00 | 13.00 | 15.00 | 62.00 |
| conservative | contraction | 27.00 | 4.00 | 45.00 | 0.00 | 4.00 | 10.00 | 10.00 | 10.00 | 72.00 |

Sequencia de calibração A4:

1. Congelar `recovery` e `expansion`.
2. Calibrar `slowdown` e `contraction` com gate em identidade.
3. Validar beta, MaxDD, CVaR, Ulcer, recuperação, turnover, effective N e inviabilidade.
4. Congelar os quatro quadrantes.
5. Calibrar gate por ablação.
6. Rodar walk-forward no livro B.
7. Confirmar ladder dos tres profiles.
8. Versionar parameter freeze.

## Mandate / IPS - Nao E Calibracao Master

Estes campos podem ser overrides individuais de portfolio. Eles mudam as metricas realizadas daquele portfolio, mas não alteram o profile master.

| Campo | Valor default atual | Observação |
|---|---:|---|
| `constraints.cap` | 0.25 | Cap por instrumento final |
| `constraints.min_weight` | `None` | Piso hard por linha ativa de `y` quando informado |
| `constraints.overlap_cap` | `None` | Cap look-through fund-mediated |
| `constraints.block_budgets` | `None` | Usado em paths especificos; para `regime_aware`, o core usa sleeves/policy |
| `universe_policy` | `complete_macro` | `strict` falha se faltarem sleeves requeridos |

CVaR, gamma, beta cap master, gate intensity e centros por quadrante não pertencem ao mandate/IPS.

## Pontos Que Precisam De Proposta Quant

| Frente | Precisamos receber proposta para |
|---|---|
| A3 | Transformações por familia macro |
| A3 | Pesos das familias |
| A3 | Escala e clipping dos scores |
| A3 | `u_floor` |
| A3 | `AXIS_ENTER` / `AXIS_EXIT` |
| A3 | Confidence minima e abstenção |
| A3 | Validação comparativa macro-release vs market-implied |
| A4 | Centros `slowdown` e `contraction` |
| A4 | Half-widths finais por sleeve, se mudarem |
| A4 | `risk_assets_cap` e `defensive_floor` por profile/quadrant |
| A4 | `PROFILE_GAMMA` |
| A4 | `PROFILE_CVAR_LIMIT` diario 95% |
| A4 | `PROFILE_PORTFOLIO_BETA_CAPS` |
| A4 | Gate shape e intensidades |
| A4 | `overlap_cap` recomendado como IPS/default operacional, se houver |
| A4 | Correção do seed infeasivel `aggressive/recovery/risk_off`, se aparecer no harness |

## Calibration Seed v0.1 - Parecer Quant

Status: proposta aprovada como seed inicial, nao como freeze empirico.

Esta seed deve ser tratada como uma configuracao v0.1 bem condicionada para a primeira execucao ampla do harness. "Otimizada", aqui, significa:

- coerente economicamente;
- poucos graus de liberdade;
- ladder dos profiles preservado;
- sem inviabilidades geometricas conhecidas;
- ainda nao validada por replay PIT.

O freeze so ocorre depois de rodar A3/A4 no harness com os criterios abaixo.

## Diagnostico Dos Parametros Atuais

### Gate `aggressive/recovery/risk_off` Inviavel

Definicao vigente:

```text
risk_assets = equity + thematic
```

Em `aggressive/recovery`, os centros atuais sao `equity=33%` e `thematic=8%`. Com half-widths de `4pp` e `1pp`:

```text
risk_assets_min = (33 - 4) + (8 - 1) = 36%
```

O gate atual reduz o cap de `45%` em `10pp`:

```text
risk_assets_cap_risk_off = 35%
```

Logo:

```text
36% > 35%
```

Isto e uma inviabilidade estrutural, nao numerica.

### CVaR Risk-Off Comprime O Ladder

Limites risk-off atuais:

| Profile | CVaR diario risk-off |
|---|---:|
| conservative | 1.20% |
| moderate | 1.43% |
| aggressive | 1.50% |

A distancia entre `moderate` e `aggressive` cai para apenas `7 bps`, o que pode fazer os dois perfis convergirem para quase o mesmo conjunto factivel.

### `conservative/slowdown` Quebra Progressao De Risk Assets

Centros atuais de `equity + thematic`:

| Quadrante | Conservative |
|---|---:|
| recovery | 7.47% |
| expansion | 6.30% |
| slowdown | 8.00% |
| contraction | 4.00% |

`slowdown` fica mais arriscado que `recovery` e `expansion`. Como `recovery` e `expansion` permanecem congelados, a correcao deve ocorrer em `slowdown` e `contraction`.

## A3 Seed v0.1 - Classificador Macro

### Contrato Dos Eixos

Fixar explicitamente a semantica antes de calibrar thresholds:

| Quadrante | Growth | Inflation |
|---|---:|---:|
| recovery | + | - |
| expansion | + | + |
| slowdown | - | + |
| contraction | - | - |

Os scores representam impulso macro relativo, nao previsao de retorno e nao probabilidade.

O replay deve ser integralmente point-in-time: valor, vintage e timestamp disponiveis na data da decisao. ALFRED/FRED vintage dates e Real-Time Data Set da Philadelphia Fed sao referencias adequadas para snapshots historicos e divulgacoes sucessivas.

### Transformacoes v0.1

Usar classes de transformacao, em vez de formulas diferentes para cada serie.

Para toda variavel, a normalizacao deve ser expanding e PIT:

```text
z_j,t = clip(
  (q_j,t - median_10y,t) / (1.4826 * MAD_10y,t),
  -3,
  +3
)
```

Minimo: `60` observacoes mensais equivalentes. Nao usar media, desvio ou winsorization calculados na amostra completa.

| Classe | Transformacao inicial |
|---|---|
| Quantity/index | `0.50*z(g_3m_ann - g_12m) + 0.30*z(g_6m_ann - g_12m) + 0.20*z(g_12m - median_10y)` |
| Rate/level | `0.70*z(level-neutral) + 0.30*z(delta_3m)` |
| Diffusion index | `0.70*z(index - 50) + 0.30*z(delta_3m)` |
| Price index | `0.55*z(pi_3m_ann - pi_12m) + 0.30*z(pi_6m_ann - pi_12m) + 0.15*z(pi_12m - median_10y)` |
| Inverse indicator | Multiplicar o resultado por `-1`, por exemplo desemprego, claims ou lending standards |
| Consensus surprise | Peso zero em v0.1 |

`surprise` deve permanecer desligado ate existir historico de consenso comprovadamente PIT. Isto evita introduzir uma segunda fonte de cobertura e revisao ja na primeira calibracao.

Dentro de cada familia:

- usar media Huberizada;
- aplicar pesos de confiabilidade por serie;
- clipar o family score em `[-2.5, +2.5]`;
- clipar o score final de cada eixo em `[-2, +2]`.

### Pesos Iniciais Por Familia

Growth axis:

| Familia | Peso |
|---|---:|
| Real activity | 35% |
| Labor | 25% |
| Surveys/diffusion | 20% |
| Credit releases | 10% |
| Liquidity releases | 10% |

Inflation axis:

| Familia | Peso |
|---|---:|
| Consumer inflation | 35% |
| Pipeline/producer prices | 20% |
| Wages/labor costs | 20% |
| Price breadth | 15% |
| Survey expectations | 10% |

Market prices, breakevens, spreads negociados e equity prices ficam fora do score macro-release. Eles pertencem exclusivamente ao comparador market-implied.

Pesos ativos so devem ser renormalizados quando:

- houver pelo menos `80%` da massa original do eixo disponivel;
- growth contiver atividade ou trabalho;
- inflation contiver consumer inflation;
- pelo menos tres familias estiverem validas em cada eixo.

### `u`, Confidence, Hysteresis E Abstencao

Definicoes:

- `C`: cobertura ponderada;
- `F`: freshness relativa ao calendario proprio de cada serie;
- `A`: concordancia entre familias;
- `V`: confiabilidade historica de vintage.

Seed:

```text
u_t = 0.35*C_t + 0.20*F_t + 0.25*A_t + 0.20*V_t

u_floor = 0.65
MIN_CONFIDENCE = 0.70

GROWTH_AXIS_ENTER = 0.35
GROWTH_AXIS_EXIT  = 0.15

INFLATION_AXIS_ENTER = 0.40
INFLATION_AXIS_EXIT  = 0.15
```

Inflation recebe `ENTER` ligeiramente maior por ser tipicamente mais ruidoso e heterogeneo entre consumer, producer e wages.

Para cada eixo:

```text
m_a = clip((abs(score_a) - EXIT_a) / (ENTER_a - EXIT_a), 0, 1)
confidence_t = 0.60*u_t + 0.40*sqrt(m_growth,t * m_inflation,t)
```

Esta confidence e apenas um indice operacional de qualidade e margem, nao uma probabilidade.

Maquina de estados:

1. Estado neutro entra em positivo ao cruzar `+ENTER`.
2. Estado neutro entra em negativo ao cruzar `-ENTER`.
3. Estado positivo volta a neutro abaixo de `+EXIT`.
4. Estado negativo volta a neutro acima de `-EXIT`.
5. Nao ha quadrante consumivel enquanto qualquer eixo estiver neutro.
6. Um estado `abstain` nao sobrescreve o ultimo snapshot oficial valido.

Abster tambem quando:

- `u < u_floor`;
- `confidence < 0.70`;
- cobertura insuficiente;
- familia critica ausente;
- dispersao ponderada entre family scores exceder `1.25` robust-z;
- freshness ou disponibilidade PIT falhar.

### Busca A3

Busca pequena e regularizada:

| Parametro | Faixa |
|---|---|
| Pesos por familia | seed +/- 5pp, soma 100% |
| Growth enter | 0.30 a 0.50, passo 0.05 |
| Inflation enter | 0.35 a 0.55, passo 0.05 |
| Exit | 0.10 a 0.20, passo 0.05 |
| `u_floor` | 0.60 a 0.72 |
| Confidence minima | 0.68 a 0.75 |
| Serie clip | 2.5 ou 3.0 |

Selecao lexicografica, sem CAGR, Sharpe ou retorno:

1. Menor instabilidade entre primeira divulgacao e vintages posteriores.
2. Eliminar ciclos extras e flips espurios.
3. Cobertura e taxa de valid adequadas.
4. Abstencao suficiente para nao publicar estados frageis.
5. Menor complexidade e menor distancia da seed.

Guardrails iniciais:

| Metrica | Faixa de aceitacao inicial |
|---|---:|
| `valid` em datas elegiveis | 75% a 90% |
| Abstencao | 10% a 25% |
| Flips oficiais | 2 a 5 por ano |
| Duracao mediana | >= 45 dias uteis |
| Percentil 10 da duracao | >= 10 dias uteis |
| Quadrante alterado por revisao de vintage | <= 10% |
| Mudanca de timing por revisao | mediana <= 1 release |

### Macro-Release Versus Market-Implied

Manter congelados nesta etapa:

| Parametro | Valor |
|---|---:|
| `G_LOOK` | 126 |
| `I_LOOK` | 126 |
| `GATE_DD` | 6% |
| `EMA_HALFLIFE_DAYS` | 5 |
| `MAX_DAILY_SHIFT` | 3% |
| `VG_BETA` | 1.5 |
| `BG_COEF` | 1.0 |

O relatorio comparativo deve mostrar:

- cobertura comum;
- valid e abstention;
- flips por ano;
- duracao dos regimes;
- concordancia por eixo;
- concordancia exata de quadrante;
- episodios de divergencia;
- duracao das divergencias;
- lead/lag das transicoes.

A divergencia e diagnostico. Ela nao deve ser minimizada durante a calibracao, pois isso transformaria o classificador macro em uma copia indireta do sinal de mercado.

## A4 Seed v0.1 - Politicas

### Centros v0.1

`recovery` e `expansion` permanecem exatamente congelados.

Para `aggressive` e `moderate`, manter os seeds atuais na primeira rodada. Eles ja expressam uma logica economica coerente:

- slowdown/stagflation: menos thematic, mais gold, alternatives e long/short;
- contraction/disinflation: mais cash e fixed income.

Fazer apenas a correcao necessaria no conservative:

| Profile | Quadrant | Cash | Equity | FI | Thematic | Alternatives | Gold | L/S | Risk cap | Defensive floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| aggressive | slowdown | 10 | 26 | 21 | 4 | 14 | 14 | 11 | 35 | 45 |
| aggressive | contraction | 16 | 18 | 35 | 2 | 6 | 11 | 12 | 25 | 54 |
| moderate | slowdown | 15 | 17 | 27 | 3 | 13 | 14 | 11 | 25 | 52 |
| moderate | contraction | 22 | 10 | 41 | 1 | 5 | 11 | 10 | 15 | 62 |
| conservative | slowdown | 21 | 5 | 34 | 1 | 10 | 16 | 13 | 12 | 68 |
| conservative | contraction | 28 | 3 | 45 | 0 | 4 | 10 | 10 | 8 | 74 |

Mudancas no conservative:

- slowdown: `-2pp` equity, `+1pp` cash e `+1pp` gold;
- contraction: `-1pp` equity, `+1pp` cash;
- risk-assets passam a `6%` e `3%`;
- floors e caps ficam coerentes com o profile ladder.

Resultado em risk assets do conservative:

```text
7.47% -> 6.30% -> 6.00% -> 3.00%
```

### Half-Widths

Na primeira rodada, manter integralmente:

```text
cash           4pp
equity         4pp
fixed_income   6pp
thematic       1pp
alternatives   3pp
gold           3pp
long_short     3pp
```

Nao calibrar simultaneamente centros, widths, gamma, hard limits e gate. Isso tornaria impossivel identificar a origem das melhorias ou inviabilidades.

Abrir os half-widths somente se o harness mostrar:

- inviabilidade recorrente sem gate;
- turnover excessivo por bandas estreitas;
- optimizer sempre encostado no mesmo limite;
- effective N muito baixo;
- incapacidade de diferenciar os profiles.

### Gamma, CVaR E Beta

Primeira rodada com gate em identidade: manter os parametros atuais como ancoras.

| Profile | Gamma | CVaR 95% diario | Beta cap |
|---|---:|---:|---:|
| conservative | 13.50 | 0.016 | 0.30 |
| moderate | 4.75 | 0.022 | 0.55 |
| aggressive | 1.90 | 0.030 | 0.85 |

Manter `DELTA_MARKET = 2.5`.

Gamma nao deve ser recalibrado ate a escala final do classificador e o mapeamento das views estarem congelados. Caso contrario, uma mudanca de magnitude em `growth_score` ou `inflation_score` altera a intensidade efetiva das views e torna a comparacao dos gammas invalida.

Depois do freeze dos centros, fazer busca coordenada:

```text
gamma_multiplier  {0.85, 1.00, 1.15}
cvar_multiplier   {0.90, 1.00, 1.10}
beta_cap_delta    {-0.05, 0.00, +0.05}
```

Sempre impor:

```text
gamma_conservative > gamma_moderate > gamma_aggressive
CVaR_conservative < CVaR_moderate < CVaR_aggressive
beta_conservative < beta_moderate < beta_aggressive
```

### Gate v0.1 Corrigido

Proposta:

```text
cvar_tightening       = 0.35
beta_tightening       = 0.25
risk_assets_reduction = 0.07

intensity:
  conservative = 0.50
  moderate     = 0.70
  aggressive   = 1.00

bl_view_confidence_multiplier = 0.0
GATE_MAX_LAG_BUSINESS_DAYS    = 5
```

Efeitos:

| Profile | CVaR risk-off | Beta cap risk-off | Reducao risk-assets |
|---|---:|---:|---:|
| conservative | 0.0132 | 0.2625 | 3.5pp |
| moderate | 0.0166 | 0.4538 | 4.9pp |
| aggressive | 0.0195 | 0.6375 | 7.0pp |

Melhorias esperadas:

1. Preserva distancia material entre os limites de CVaR dos tres perfis.
2. Mantem `aggressive` como profile com maior intensidade de gate.
3. Corrige `aggressive/recovery/risk_off`:

```text
cap_risk_off = 45 - 7 = 38%
risk_assets_min = 36%
folga = 2pp
```

O multiplier de views igual a zero deve ser testado separadamente na ablacao, e nao assumido como automaticamente benefico.

### Ablacao Do Gate

Rodar nesta ordem:

| Experimento | Views | CVaR | Beta | Risk cap |
|---|---:|---:|---:|---:|
| Identity | 1 | off | off | off |
| Views only | 0 | off | off | off |
| CVaR only | 1 | on | off | off |
| Beta only | 1 | off | on | off |
| Risk cap only | 1 | off | off | on |
| Constraints without view suppression | 1 | on | on | on |
| Full gate | 0 | on | on | on |

O full gate so deve ser congelado se, em todos os profiles:

- reduzir beta, CVaR e risk assets realizados;
- nao inverter o profile ladder;
- nao gerar inviabilidade;
- nao aumentar turnover desproporcionalmente;
- produzir beneficio adicional em relacao as ablações mais simples.

### Criterio De Escolha A4

Selecao lexicografica:

1. Zero violacao pos-solve.
2. Zero inviabilidade no universo canonico `complete_macro`.
3. Inviabilidade <= `0.5%` na matriz de universos e mandates de stress.
4. Profile ladder preservado em pelo menos `90%` dos rebalances.
5. Pareto entre MaxDD, CVaR, Ulcer e recuperacao.
6. Menor turnover.
7. Maior effective N.
8. Menor distancia da seed.

Cada linha de centros pode variar inicialmente em `2pp`, com:

- soma exata de `100%`;
- distancia L1 maxima de `8pp` por profile/quadrant;
- risk assets de slowdown nao superiores a expansion;
- risk assets de contraction nao superiores a slowdown;
- ao menos `2pp` de folga geometrica sob identity e risk-off.

### Fixed Income Por Categoria

Embora a politica opere no sleeve `fixed_income`, o harness nao pode reporta-lo como bloco homogeneo.

Para cada rebalanceamento, registrar:

```text
GOVT / fixed_income
LQD  / fixed_income
HYG  / fixed_income
TIP  / fixed_income
BND  / fixed_income
```

O `defensive_floor` nao garante sozinho qualidade defensiva, porque `HYG` pertence ao sleeve FI. Beta e CVaR continuam sendo os controles hard para esse risco.

Guardrail inicial de freeze:

- `p95(HYG / fixed_income) <= 50%` em slowdown;
- `p95(HYG / fixed_income) <= 35%` em contraction.

Isto e criterio de rejeicao do parametro no harness, nao uma nova constraint de backend nesta etapa.

### Overlap E Mandate

`overlap_cap` nao deve virar parametro master de profile.

Recomendacao:

- master/default: `None`;
- template IPS operacional: `0.15`;
- aplicar o template somente quando a cobertura look-through for pelo menos `85%`;
- abaixo disso, nao fingir protecao usando a semantica atual de exposicao zero para fundos sem N-PORT.

Matriz de robustez:

```text
cap              {0.20, 0.25}
min_weight       {None, 0.01, 0.02}
overlap_cap      {None, 0.15}
universe_policy  {complete_macro, strict}
```

Uma inviabilidade causada por `min_weight=0.02` em um universo muito fragmentado e propriedade legitima daquele IPS, nao motivo para relaxar o profile master. O Plano C ja estabelece hard floors no book final, hard CVaR e fail-loud sem renormalizacao.

## Sequencia Executavel Recomendada

1. Materializar replay PIT e metricas de vintage.
2. Rodar a seed A3 acima.
3. Fazer busca limitada de thresholds, weights, `u_floor` e confidence.
4. Congelar A3 e publicar o relatorio macro-release vs market-implied.
5. Congelar `recovery`/`expansion` e os parametros base atuais.
6. Rodar os centros A4 v0.1 com gate em identidade.
7. Buscar centros/caps/floors em torno da seed.
8. Congelar os quatro quadrantes.
9. Rodar ablacao e calibrar o gate v0.1.
10. Executar Book B uma unica vez, sem retuning.
11. Confirmar o ladder dos profiles.
12. Versionar o manifest completo e somente entao executar A5.

## Recomendacao

Adotar esta configuracao como `calibration_seed_v0.1`.

Ela corrige as duas incoerencias numericas visiveis antes do harness:

- a inviabilidade de `1pp` em `aggressive/recovery/risk_off`;
- a progressao incorreta de `conservative/slowdown`.

Ela nao altera prematuramente parametros cuja calibracao depende dos resultados do harness.

## Referencias

- FRED/ALFRED vintage dates: https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html
- OECD System of Composite Leading Indicators: https://www.oecd.org/content/dam/oecd/en/data/methods/OECD-System-of-Composite-Leading-Indicators.pdf
