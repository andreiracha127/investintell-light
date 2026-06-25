# COMBO — Decisão de escopo: Quadrante macro v1 (adendo ao Architecture Freeze v1)

**Status:** APROVADO (architecture). **Parameter freeze:** pendente. Complementa
`2026-06-23-combo-regime-aware-architecture-freeze-v1.md` (Parte A).

## 1. Decisão de escopo

O quadrante **oficial de produção** é construído com **dados macro publicados, point-in-time** — não com proxies de mercado.

| Papel | model_family | model_version | Uso |
|---|---|---|---|
| **Production candidate v1** | `macro_release` | `macro_quadrant_us_v1` | quadrante estratégico oficial |
| **Challenger preservado** | `market_implied` | `market_implied_quadrant_v0` | regressão / shadow / diagnóstico de divergência / pesquisa. **NUNCA fallback** |
| **Gate** | `market_risk_gate` | (atual) | restrição de risco, diário, market-based |

Separação institucional: **dados macro publicados → quadrante estratégico**; **dados de mercado diários → gate restritivo**. Os dois modelos de quadrante rodam **separados** na v1 — sem híbrido 70/30 (um eventual `macro_quadrant_hybrid_v2` é modelo NOVO, não alteração silenciosa da v1). Snapshot macro inválido → `QUADRANT_UNAVAILABLE` + no-trade (jamais cai no market-implied).

## 2. Veredito do audit do macro-ingestion (2026-06-23)

`macro_data` (prod Tiger `t83f4np6x4`): `(series_id, obs_date, value, source, is_derived, created_at, updated_at, created_by, updated_by)`, PK `(series_id, obs_date)`, upsert `ON CONFLICT DO UPDATE`. **Não persiste vintages** (sem `realtime_start`/`vintage_id`/`revision_number`/`release_at`/`available_at`); fonte FRED (revisão corrente). 99 séries, 1959→2026, mas série revisada (look-ahead).

**Conclusão:** a **reconstrução point-in-time é o bloco adicional necessário** de A1. Caminho: ALFRED (mesma API key FRED, `realtime_start`/`realtime_end`). Reusável: registry de séries por axis/family/frequency, fetch rate-limited, pesos por eixo.

## 3. Não construir plataforma macro universal

Cesta **pequena, auditável, historicamente reconstruível**: 3–5 famílias por eixo (mais séries só quando uma família tem múltiplos componentes; o score NÃO deve ter dezenas de parâmetros independentes). Indicadores compostos identificam mudanças qualitativas / turning points (estilo OECD CLI), não previsão numérica de crescimento. BIS/FMI entram só quando agregam informação específica — disponibilidade no datalake NÃO é critério de inclusão. Estrutura inicial:

- **Growth:** atividade/produção · consumo real · mercado de trabalho · novos pedidos/leading activity.
- **Inflation:** inflação core realizada · pressão de preços upstream · salários/custos · expectativas de inflação.

## 4. Registro de fontes v1 (`MacroSourceSpec`)

```python
@dataclass(frozen=True)
class MacroSourceSpec:
    source_id: str
    axis: Literal["growth", "inflation"]
    family: str
    transform_id: str
    direction: Literal[-1, 1]
    weight: float
    cadence: Literal["daily", "weekly", "monthly", "quarterly"]
    release_calendar_id: str | None
    revision_policy: Literal["none", "vintage"]
    grace_period: timedelta
    hard_max_age: timedelta
    critical: bool
    minimum_history: int
    source_spec_version: str
```
O mesmo registro serve as duas famílias: fonte diária de mercado (`cadence=daily`, `revision_policy=none`, `available_at = close + lag`, `hard_max_age = 3 business days`) e fonte macro publicada (`cadence=monthly/quarterly`, `revision_policy=vintage`, `available_at = release timestamp`, `stale_after = next release + grace`). O design genérico evita uma 2ª migração de schema; o que se evita é o catálogo ilimitado.

## 5. Vintages point-in-time (o bloco A1 adicional)

Cada observação precisa de: `series_id, observation_period, value, release_at, available_at, vintage_id, revision_number, source, ingested_at`. Consulta-chave: **`latest vintage available_at <= decision_time`** (FRED/ALFRED suporta vintages via realtime). Se a infra guardasse só o valor revisado, está pronta para produção corrente mas não para backtest PIT — que é o caso atual → reconstruir vintages.

## 6. Confidence v1 — `rolling_score_mad_distinct_vintages_v1` (macro) / `rolling_score_mad_252bd_v1` (market)

Proxy operacional de confiança (governa abstenção), **não** probabilidade calibrada. Por eixo a:

```
u_raw_a = max( 1.4826 · MAD(s_a sobre VINTAGES DISTINTOS na janela), u_floor_a )   # NÃO 252 linhas forward-filled; NÃO dividir por sqrt(n)
UNCERTAINTY_WINDOW_BD = 252        # janela
MIN_UNCERTAINTY_VINTAGES = 12      # < 12 vintages distintos → status=unavailable, confidence=NULL
# (seed do macro: janela mínima 24 / preferida 36 vintages)

coverage_quality   = Σ_k |w_k|·I(input_k válido) / Σ_k |w_k|     # ponderado pela importância
freshness_quality  = 1 se age ≤ cadence+grace; decai linear até 0 em hard_max_age; 0 depois  # penalização SUAVE
source_health      = finitude ∧ schema ∧ unidade ∧ range plausível ∧ pipeline ok ∧ sem erro crítico de revisão
q_data = min(coverage_quality, freshness_quality, source_health_quality)
u_adj_a = u_raw_a / max(q_data, 0.25)
confidence_a = Φ( |s_a| / u_adj_a )          # sinal CANDIDATO do score, não o sinal antigo da hysteresis
candidate_confidence = min(confidence_growth, confidence_inflation)
```
`u_floor` estimado na calibração, congelado em `confidence_model_version`. Falha de fonte crítica → `invalid`/`unavailable` (NÃO compensada por outras fontes saudáveis).

**Hard gates separados da confidence** (a confidence não substitui disponibilidade):
```
coverage < 0.80          → unavailable
fonte crítica inválida   → invalid
now >= stale_after       → stale         (bloqueio DURO; freshness_quality é só penalização suave antes)
transition_pending       → low_confidence
confidence < 0.70        → low_confidence
```
Consumível ⟺ confidence ≥ 0.70 ∧ ambos eixos confirmados ∧ status valid ∧ fresco.

**Calibrar** AXIS_ENTER/AXIS_EXIT/MIN_CANDIDATE_CONFIDENCE/u_floor SÓ contra: taxa de abstenção, frequência de flips, reversões em 10/20/40 dias, tempo de confirmação de mudança persistente, estabilidade entre vintages, % de tempo em `valid`. **Nunca CAGR/Sharpe/performance dos quadrantes.**

## 7. Sequenciamento da Parte A

- **A1 — infraestrutura e contratos:** `MacroSourceSpec`; auditar/reconstruir vintages e `available_at`; integrar calendários existentes; consulta point-in-time; adapters para fontes diárias e release-driven.
- **A2 — dois workers comparáveis:** `MarketImpliedAxisModel` + `MacroReleaseAxisModel`, **ambos emitem exatamente o mesmo `QuadrantSnapshot`**.
- **A3 — calibração do classificador macro** (sem retorno): transformações, pesos das famílias, escala dos scores, u_floor, hysteresis, confidence mínima, abstenção, estabilidade de vintage.
- **A4 — calibração das políticas:** QUADRANT_POLICIES, gate overlays, impacto no livro B, walk-forward.
- **A5 — ativação:** worker macro v1 + backend v2 atômicos; market-implied em shadow; sem fallback; snapshot macro inválido → QUADRANT_UNAVAILABLE + no-trade.

**Validação comparativa (antes de tocar o livro B):** cobertura histórica, taxa de `valid`, abstenção, flips/ano, duração média dos quadrantes, revisões de classificação entre vintages, tempo de confirmação, distribuição do tempo nos 4 quadrantes, divergências macro×mercado. Impacto no livro B só após validar o classificador.

## 8. Audit de prontidão da infra (antes de declarar pronta)
Confirmar que se pode reconstruir "o que o sistema sabia naquele instante" via `latest vintage available_at <= decision_time`. **Resultado 2026-06-23: NÃO (macro_data só tem valor revisado) → reconstrução de vintages é trabalho de A1.**
