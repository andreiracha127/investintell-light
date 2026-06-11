# F8 (pré) — Inventário read-only de FUNDOS no DB-mãe (investintell-allocation)

**Data:** 2026-06-11 · **Método:** SELECTs read-only via `INVESTINTELL_DB_URL` (localhost:5434) ·
**Conclusão: o DB-mãe é fund-first — o lado de fundos é o ativo mais rico do banco e justifica
re-escopar o F8 (Portfolio Builder) de equity-only para fundos como cidadãos de primeira classe.**

## O que existe (verificado por contagem + amostra)

### Identidade e universo
| Tabela | Linhas | Conteúdo |
|---|---:|---|
| `instrument_identity` | 9.033 | Ponte canônica de fundos: instrument_id ↔ CIK, sec_series_id, sec_class_id, CUSIP, ISIN, SEDOL, FIGI, ticker, LEI |
| `instruments_universe` | 14.786 | Universo com instrument_type, asset_class, geography, currency, attributes JSON |
| `sec_registered_funds` | 3.112 | Mutual funds N-CEN: strategy_label, fees (management/expense), primary_benchmark, flags (index, fund-of-fund, target-date, master-feeder), AUM, NAV/share |
| `sec_etfs` | 985 | ETFs N-CEN: index_tracked, in-kind creation/redemption, tracking difference gross/net, fees, AUM |
| `sec_money_market_funds` | 373 | MMFs N-MFP: categoria, WAM/WAL, 7-day yield, % liquidez diária/semanal, stable NAV |
| `esma_funds` | 11.268 | UCITS europeus: domicile, host member states, strategy_label, manager |
| `sec_fund_classes` | 36.516 | Share classes: expense_ratio, advisory fees, returns, net_assets, turnover |
| `sec_fund_prospectus_stats` | 72.157 | Por classe/filing: management fee, net expense ratio, 12b-1, fee waivers, expense examples 1/3/5/10y, best/worst quarter, avg returns 1/5/10y |
| `sec_fund_prospectus_returns` | 17.502 | Retornos anuais por série/ano (bar chart do prospecto) |

### Séries temporais e risco (o núcleo)
| Tabela | Linhas | Conteúdo |
|---|---:|---|
| `nav_timeseries` | 27.419.383 | NAV diário + return_1d + AUM, **9.046 instrumentos, 1970 → 2026-06-05** |
| `nav_monthly_returns_agg` | 583.850 | Agregados mensais (open/close, vol diária média) |
| `fund_risk_metrics` | 1.022.541 | **7.818 instrumentos, 2006-01 → 2026-06-09**, ~75 métricas por (instrument, calc_date): CVaR 95 (1m/3m/6m/12m, conditional, **EVT 99/99.9 + xi shape**), VaR, returns 1m→10y ann., vol 1y + GARCH, max DD 1y/3y, Sharpe/Sortino/Calmar, **Cornish-Fisher Sharpe com CI**, alpha/beta, IR/TE, downside/upside capture, crisis_alpha_score, inflation/credit beta, empirical duration, **peer percentiles por estratégia** (sharpe/sortino/return/drawdown pctl), manager_score + score_components, elite_flag/rank, momentum (NAV/flow/blended, RSI, BB), métricas MMF (7-day yield, WAM, liquidez) |
| `sec_nport_holdings` | 2.234.955 | **Composição dos portfolios** por série: 8.554 séries até 2026-05-31; cusip/isin/issuer, asset_class, sector, market_value, pct_of_nav, fair_value_level. ⚠️ top-50 holdings por fundo no último report (53–80% do NAV somado nas amostras) |
| `strategy_reclassification_stage` | 994.497 | Pipeline de classificação de estratégia (labels em várias tabelas via classification_source) |

### Vazias no DB-mãe (o "builder quebrado" — camada de aplicação)
`funds_universe` (0), `fund_memberships` (0), `instrument_screening_metrics` (0),
`lipper_ratings` (0), `sec_fund_style_snapshots` (0); `portfolio_construction_runs` (4),
`model_portfolios` (10). Os DADOS são ricos; a camada de construção/uso em cima deles é que
nunca funcionou — exatamente o que o Light pode reconstruir do zero.

## Status F8.1 (commit 4f14780)

Sync implementado e executado: 4.558 fundos elegíveis (series_id + risk calc 2026 + NAV 2y
fresco), 2,35M NAVs, 175k holdings; gate G1 5/5 contra a fonte. Cascata de classificação
precisou ser estendida na prática: só 730/4.558 séries elegíveis aparecem nas tabelas
N-CEN/N-MFP — a cobertura real veio do `strategy_reclassification_stage` keyed por
instrument_id (`source_table='instruments_universe'`, 4.502/4.558) + peer label específico;
restam 52 'Unclassified' (1,1%). `asset_class` 100% via instruments_universe.

⚠️ **Ressalva de qualidade DA FONTE:** o classificador por descrição do DB-mãe erra em casos
visíveis (ex.: "WesMark Government Bond Fund" rotulado 'High Yield Bond' por
`matched_pattern desc:high_yield`, confidence high, e o current_strategy_label da fonte diz o
mesmo). O sync espelha a fonte fielmente; a F8.2 deve exibir a origem da classificação e o
F8/builder não deve usar strategy_label como constraint rígida sem revisão humana.

## Lacunas conhecidas
- `strategy_label` NULL em 1.947/3.112 registered funds; `peer_*`/`elite_*` NULL para parte dos
  instrumentos no último calc_date (3.215 "None" de label no último snapshot do risk metrics).
- N-PORT holdings truncado em top-50 por fundo (suficiente para overlap/concentração aproximados,
  não para look-through completo).
- `lipper_ratings` vazia (sem ratings de terceiros).
- ESMA/UCITS: identidade e classificação presentes; cobertura de NAV via `esma_nav_history` a verificar.

## Implicação para o F8
O plano original (§3.7: CVXPY sobre 2Y de preços EOD Tiingo, equities do portfólio) ignora que o
DB-mãe já entrega, pronto e atualizado, o que o F8 ia computar — e muito mais (EVT CVaR, peer
ranking, 20 anos de histórico mensal). Re-escopo proposto (decisão do dono):
1. **Sync read-only de fundos** (novo módulo em `app/sync`, mesmo padrão do F6): identidade +
   risk metrics (último calc_date) + NAV (janela necessária) + classificação → tabelas locais.
2. **Universo de fundos navegável** no Light (screener de fundos por estratégia/risco/fees usando
   métricas precomputadas — sem recomputar nada).
3. **Builder fund-aware**: otimização (CVXPY) sobre NAV returns de fundos e/ou equities, com
   constraints por estratégia/asset_class e CVaR do DB-mãe como input/validação.
4. Holdings N-PORT para **overlap/concentração** entre fundos do portfólio (com a ressalva top-50).

Regra mantida: DB-mãe é **SÓ leitura, SÓ via app/sync** — nada de request path.
