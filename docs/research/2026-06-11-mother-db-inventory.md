# F6.1 — Inventário read-only do DB-mãe (investintell-allocation)

**Data:** 2026-06-11 · **Método:** SELECTs read-only via `INVESTINTELL_DB_URL` · **Resultado: AMBIGUIDADE DE JOIN — decisão do dono requerida (D7.3)**

## Resumo executivo

1. **A premissa do dispatch caiu:** `instrument_identity` (a "ponte canônica") contém **apenas fundos** (9.033 linhas, mutual funds/ETFs com `sec_series_id`) — **0/20 equities US do teste** (AAPL, MSFT, …). Fundamentals são chaveados por **CIK**, não por series_id.
2. **Fundamentals são excelentes uma vez conhecido o CIK:** `company_characteristics_monthly` (453,7 mil linhas, 13.921 CIKs, grão = fim de período fiscal, TTM em net_income/capex) + `sec_xbrl_facts` (106 M linhas) — 20/20 tickers do teste verificados com dados até Q4-2025/Q1-2026.
3. **Não existe tabela de constituintes** S&P 500/Nasdaq 100, e o substituto via N-PORT é **truncado** (só top holdings: IVV = 54 nomes/63% NAV; QQQM = 56 nomes/91% NAV; QQQ = UIT, sem N-PORT).

## Caminhos de join ticker→CIK (ambíguos)

| Opção | Evidência a favor | Evidência contra |
|---|---|---|
| **A** `sec_cusip_ticker_map.issuer_cik` | 1 linha/ticker, 20/20 p/ CUSIP | issuer_cik NULL em 12/20 mega-caps; **ERRADO para COST** (CIK 1393231 ≠ real 909832); cobertura 5.123/41.786 |
| **B** derivado de `sec_insider_transactions` (issuer_ticker, issuer_cik) | 19/20 corretos, sem colisões, 3.096 tickers alcançam fundamentals | Exaustão transacional, não dado de referência: ABBV ausente; sem datação de validade; renames históricos podem criar pares stale |
| **C** crosswalk próprio do Light via `company_tickers.json` da SEC (oficial) | Inequívoco, oficial, gratuito, cobre tudo; join no DB-mãe por CIK puro (verificado 20/20) | Dependência externa nova no sync (1 download JSON oficial da SEC, versionável como seed) |

## Join de fundamentals (claro, uma vez resolvido o CIK)

```sql
SELECT cik, period_end, book_equity, total_assets, net_income_ttm,
       revenue, gross_profit, shares_outstanding, quality_roa,
       investment_growth, profitability_gross, source_filing_date
FROM company_characteristics_monthly
WHERE cik = ANY($1)
  AND (cik, period_end) IN (SELECT cik, max(period_end)
                            FROM company_characteristics_monthly GROUP BY cik);
```

## Métricas de fundamentals propostas para o catálogo do screener

- Market Cap = shares_outstanding × preço (preço do EOD Tiingo local)
- P/E = market_cap / net_income_ttm
- ROE = net_income_ttm / book_equity · ROA = quality_roa (precomputado)
- Gross margin = gross_profit / revenue (≈ profitability_gross) · Net margin exige revenue TTM (somar trimestres ou XBRL)
- D/E proxy = (total_assets − book_equity) / book_equity (ccm) ou XBRL Liabilities/Equity
- Extras: investment_growth, book-to-market, EPS diluído (XBRL), capex_ttm/revenue

## Universo — opções

- **Seed externo de índices**: lista S&P 500 + Nasdaq 100 (~560 nomes) versionada no repo com fonte/data documentadas (alinha com §3.5 do dispatch; a fonte deixa de ser o DB-mãe). Backfill EOD ≈ 5–10 min.
- **Universo amplo por cobertura**: todas as equities US com fundamentals atuais no DB-mãe (~3.000 tickers via crosswalk; 4.615 CIKs ativos). Backfill ≈ 25–30 min. Mais rico, sem dependência de lista de índice.
- N-PORT top-holdings (54+56 nomes) — **não recomendado** (truncado).

## Sizing

- XBRL: 106 M linhas, 14.556 CIKs, filings até 2026-03-23.
- ccm: 4.615 CIKs com period_end ≥ 2025-06-30 (conjunto "ativo").
- Tickers alcançáveis hoje: ~3.096 (via B) / 1.202 (via A, com erro conhecido).
