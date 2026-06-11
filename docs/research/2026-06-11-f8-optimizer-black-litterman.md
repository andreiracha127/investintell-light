# F8 — Validação do otimizador + camada forward-looking Black-Litterman

**Data:** 2026-06-11 · **Métodos:** docs/código do QuantConnect LEAN (público) + validação
numérica local (CVXPY) com dados reais do DB do Light · **Resultado: VIÁVEL — todos os checks
passaram; BL entra como camada de views sobre o otimizador já planejado, sem trocar o motor.**

> ⚠️ O MCP do QuantConnect está sem credenciais (`UserID not valid (None)`) — backtest na
> plataforma fica pendente de o dono configurar `QUANTCONNECT_USER_ID`/`API_TOKEN` no MCP.
> A pesquisa usou a documentação e o código-fonte públicos do LEAN; a validação do otimizador
> foi feita localmente com os mesmos dados que o F8 usará.

## 1. O que o QuantConnect/LEAN faz (referência de arquitetura)

`BlackLittermanOptimizationPortfolioConstructionModel` (Algorithm Framework):
- **Equilíbrio por reverse optimization:** `π = δ·Σ·w` com δ=2.5, τ=0.05, Σ = cov anualizada
  (252d) de 63 dias de história. ⚠️ **Limitação do LEAN: usa pesos IGUAIS no equilíbrio**, não
  market-cap — nós podemos fazer melhor (temos AUM real por fundo no DB-mãe).
- **Views vindas dos Alpha models:** cada modelo de alpha vira uma view (P = exposições
  normalizadas por direção/magnitude dos insights, Q = convicção, Ω = diag(P·τΣ·Pᵀ)).
- **Posterior pela master formula** fechada; degrada para `None` se Ω singular (views
  linearmente dependentes — precisamos validar posto de P).
- **Separação de camadas:** o BL é um PortfolioConstructionModel que delega a um
  `IPortfolioOptimizer` plugável (default `MaximumSharpeRatioPortfolioOptimizer`; há também
  MinimumVariance, RiskParity, UnconstrainedMeanVariance). **Mesma separação que o F8 já
  planejava** (camada de estimativa → motor CVXPY) — o design está validado por precedente.

## 2. Validação numérica local (dados reais: SPY/AGG/GLD/TLT/AAPL/MSFT, 3y, 751 dias)

Pipeline implementado e executado (script: validação one-off, ~80 linhas CVXPY):
`Σ anualizada → π = δΣw_mkt → views (P,Q) + Ω Idzorek-style → posterior (μ_BL, Σ_BL) →`
(a) max-utility long-only cap 35% e (b) **min-CVaR 95 Rockafellar–Uryasev com cenários
históricos re-centrados em μ_BL** + piso de retorno.

Views de teste: "GLD retorna 12% a.a." (absoluta) e "AAPL supera MSFT em 5% a.a." (relativa).

| Check | Resultado |
|---|---|
| Solver `optimal` nos 4 problemas; pesos somam 1; caps respeitados | ✅ |
| View absoluta eleva μ posterior do ativo (GLD 1.70% → 6.84%) | ✅ |
| View eleva peso no max-utility (GLD 8.3% → 35% cap) | ✅ |
| View relativa tilta o spread AAPL−MSFT na direção esperada | ✅ |
| Min-CVaR com views tilta suavemente (GLD 14.1→14.3, AAPL 0→3.2) | ✅ |
| Sem views, BL reproduz ~pesos de mercado (sanidade da reverse optimization) | ✅ |

**Observação importante de produto:** o max-utility com views fortes produz soluções de canto
(GLD no cap, AGG/MSFT a zero) — comportamento clássico de mean-variance. O **min-CVaR com
cenários re-centrados tilta de forma muito mais conservadora**, que é o comportamento desejável
para o cliente. Recomendação: min-CVaR/BL-recentered como default, max-utility como opção.

## 3. Desenho proposto para o F8 (builder fund-aware + forward-looking)

1. **Equilíbrio melhor que o do LEAN:** w_mkt por **AUM real** dos fundos
   (`sec_registered_funds.monthly_avg_net_assets` / `nav_timeseries.aum_usd`), não equal-weight.
2. **Views do usuário** em 2 formas na UI: absoluta ("estratégia/fundo X retorna Y%") e
   relativa ("X supera Y em Z%"), com confiança (Idzorek: confiança → Ω; default
   Ω = diag(P·τΣ·Pᵀ)). Validar posto de P; rejeitar views dependentes com erro claro.
3. **Σ:** Ledoit-Wolf shrinkage (já no plano F8) sobre NAV returns dos fundos; opcionalmente
   ancorar vol/cauda nas métricas precomputadas do DB-mãe (`volatility_garch`, `cvar_99_evt`)
   como verificação de sanidade, não como input do solver.
4. **Motor:** CVXPY (plano original §3.7 mantido) — objetivos equal-weight, min-vol, ERC,
   max-diversification, **min-CVaR (default) com re-centering BL quando houver views**.
   μ entra APENAS via BL posterior — preserva o espírito "μ-free" do plano: sem views, o
   builder é μ-free puro; com views, μ é disciplinado pelo equilíbrio (não estimado de série).
5. **Gate F8 adicional (BL):** (i) zero views ⇒ pesos ≈ mercado (tolerância numérica);
   (ii) view absoluta em X move μ_X e o peso na direção da view; (iii) Ω singular ⇒ 422 com
   mensagem; (iv) caps/long-only respeitados; (v) CVaR proposto ≤ atual in-sample pelo MESMO
   engine F3 (gate original mantido).

## 4. Alternativas consideradas (e por que BL)

- **Entropy Pooling (Meucci):** mais geral (views em vol/correlação/quantis, sem Gaussiana) e
  casaria com as caudas EVT do DB-mãe — porém muito mais complexo de explicar/parametrizar na
  UI. Candidato a F8.5+ para views de risco; BL cobre o prometido (views de retorno).
- **μ from peer percentiles/manager_score do DB-mãe:** útil como *sugestão de view* (pre-fill),
  não como substituto — manter o usuário como fonte da view.
- **Resampled frontier / robust MVO:** mitigam erro de estimativa mas não incorporam views —
  não atendem a promessa "forward-looking" feita ao cliente.

## 5. Pendências

- Credenciais do QuantConnect no MCP (dono) → opcional: backtest de confirmação na plataforma
  (BL PCM do LEAN vs nosso pipeline, mesmos ativos/período) como evidência extra para o cliente.
- Decidir defaults de produto: δ (2.5), τ (0.05), cap (25% no plano original vs 35% usado no
  teste), piso de retorno no min-CVaR.
