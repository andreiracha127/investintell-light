# COMBO Regime-Aware — Architecture / Design Freeze v1

**Status:** APROVADO (architecture freeze). **Parameter freeze:** pendente de calibração.
**Fonte:** especificação entregue pelo dono em 2026-06-23. Este documento é a referência
autoritativa e substitui specs anteriores que misturavam quadrante, gate, goldfix e hedge.

> **Decisão congelada:** O quadrante define a política estratégica entre sete sleeves. O gate,
> independente e igualmente validado, apenas restringe CVaR, beta e o teto conjunto de equity+thematic.
> Confidence autoriza ou impede consumo; nunca representa retorno esperado. Snapshots ambíguos,
> ausentes, inválidos ou vencidos não geram recomendação. Todos os quadrantes usam o mesmo pipeline
> two-level, com constraints compiladas e verificadas no book final.

---

## 1. Princípios invariantes

1. **Quadrante e gate são dimensões independentes.** Quadrante = política macroestratégica; gate = restrição de risco. **Não existe mais `combined_regime`.**
2. **Somente dados válidos geram alocação `regime_aware`.** Ausência/ambiguidade/baixa-confiança/vencido não produz carteira. Não existe `None → expansion` nem `None → risk_on`.
3. **Os quatro quadrantes existem operacionalmente:** `recovery`, `expansion`, `slowdown`, `contraction`.
4. **Sete sleeves estruturais:** `cash`, `equity`, `fixed_income`, `thematic`, `alternatives`, `gold`, `long_short`.
5. **SH não é sleeve estrutural.** Só research overlay / shadow-live. Fora de centros, bandas, prior, fills.
6. **Sem branches especiais que escapam das constraints.** `SLOWDOWN` não aciona goldfix. Todos os quadrantes passam pelo mesmo compilador, solver e pós-verificação.
7. **Fail-loud.** Não retorna pesos com warnings de violação; não relaxa constraint silenciosamente; não troca mandato para preservar disponibilidade.

---

# Parte A — Regime Gate v2

## 2. Domínio macro

| Quadrante | Crescimento | Inflação |
|---|---:|---:|
| `recovery` | positivo | negativo |
| `expansion` | positivo | positivo |
| `slowdown` | negativo | positivo |
| `contraction` | negativo | negativo |

O worker é a única autoridade para: calcular scores, aplicar hysteresis, definir confidence,
publicar o quadrante, avaliar cobertura/integridade das fontes. O backend não recalcula nem corrige.

## 3. Modelo do snapshot

```python
Quadrant = Literal["recovery", "expansion", "slowdown", "contraction"]
ComputeStatus = Literal["valid", "low_confidence", "unavailable", "invalid"]
EffectiveStatus = Literal["valid", "low_confidence", "stale", "unavailable", "invalid"]

@dataclass(frozen=True)
class AxisDiagnostics:
    score: float | None
    sign: Literal[-1, 1] | None          # sinal efetivo pós-hysteresis; NULL se não consumível
    candidate_confidence: float | None
    margin: float | None
    uncertainty_raw: float | None
    uncertainty_adjusted: float | None

@dataclass(frozen=True)
class QuadrantSnapshot:
    snapshot_id: str
    quadrant: Quadrant | None            # consumível; só preenchido quando status_at_compute=="valid"
    candidate_quadrant: Quadrant | None  # classificação instantânea (auditoria/UI)
    candidate_confidence: float | None
    growth: AxisDiagnostics
    inflation: AxisDiagnostics
    coverage_quality: float
    freshness_quality: float
    source_health_quality: float
    transition_pending: bool
    transition_reason: str | None
    as_of: date                          # data econômica representada
    available_at: datetime               # primeiro instante com todos os inputs disponíveis
    computed_at: datetime
    data_stale_after: datetime
    pipeline_stale_after: datetime
    stale_after: datetime
    status_at_compute: ComputeStatus     # persistido e imutável
    model_version: str
    confidence_model_version: str
    confidence_method: str
    source_vintage_hash: str
```

`effective_status` é derivado **na leitura** (o worker nunca reescreve snapshots antigos):

```python
def effective_status(snapshot, now):
    if snapshot.status_at_compute == "valid" and now >= snapshot.stale_after:
        return "stale"
    return snapshot.status_at_compute
```

## 4. Semântica de confidence

`candidate_confidence` mede a confiança na **classificação do eixo**, não a previsão de retorno.

Para cada eixo a: score `s_a = Σ_k w_k · z_k` ; incerteza `u_a = sqrt(wᵀ Ω_a w)`.

Qualidade agregada de dados: `q_data = min(coverage_quality, freshness_quality, source_health_quality)`.

Incerteza ajustada: `u*_a = u_a / max(q_data, 0.25)`.

Com sinal candidato `h_a` (segue o lado do score): `confidence_a = Φ( h_a · s_a / u*_a )`, logo `0.50 ≤ confidence_a ≤ 1`.

Confiança do quadrante (conservadora): `candidate_confidence = min(confidence_growth, confidence_inflation)`.

| Confidence | Significado |
|---:|---|
| 0.50 | completamente ambíguo |
| 0.70 | mínimo operacional |
| 0.85+ | classificação forte |
| NULL | indisponível ou inválido |

`0` nunca representa indisponibilidade. Constantes iniciais (parameter freeze, a calibrar contra
estabilidade de vintage / frequência de abstenção / qualidade operacional — nunca contra retorno):

```python
MIN_CANDIDATE_CONFIDENCE = 0.70
MIN_INPUT_COVERAGE = 0.80
```

## 5. Hysteresis dos eixos

```python
AXIS_ENTER = 0.25
AXIS_EXIT = 0.10
```

**5.1 Inicialização** (sem estado anterior): inicializa o eixo só se `abs(score) >= AXIS_ENTER` E
`candidate_confidence >= MIN_CANDIDATE_CONFIDENCE`; senão `status_at_compute ∈ {low_confidence, unavailable}`, `quadrant = NULL`.

**5.2 Estado confirmado** (sinal anterior `h_{t-1}`): `signed_margin = h_{t-1} · s_t`. **Precedência obrigatória — troca oposta ANTES de estabilidade:**

```python
if signed_margin <= -AXIS_ENTER:   # evidência suficiente no sentido oposto
    switch_sign()                  # troca se confiança mínima também atendida
elif signed_margin >= AXIS_EXIT:   # sinal anterior permanece confirmado
    keep_sign()
else:                              # deadband / transição não confirmada
    keep_internal_state_only()
    publish_no_quadrant()
```

Qualquer eixo em transição → `transition_pending = true`, `status_at_compute = low_confidence`, `quadrant = NULL`.
A hysteresis pode preservar o último sinal internamente, mas isso NÃO autoriza consumo pelo backend.

## 6. Status e consumibilidade

| Effective status | Consumo pelo builder |
|---|---|
| `valid` | permitido |
| `low_confidence` | proibido; diagnóstico/UI |
| `stale` | proibido |
| `unavailable` | proibido |
| `invalid` | proibido e gera alerta |

`valid` ⟺ quadrant não-nulo ∧ candidate_quadrant não-nulo ∧ candidate_confidence ≥ 0.70 ∧ growth+inflation
confirmados ∧ input coverage ≥ 0.80 ∧ fontes críticas saudáveis ∧ não vencido ∧ sem transição pendente.

Backend (conceitual) — **proibido buscar o "último quadrante não nulo":**

```sql
SELECT * FROM regime_quadrant_snapshot
WHERE status_at_compute='valid' AND quadrant IS NOT NULL
  AND candidate_confidence >= 0.70 AND stale_after > now()
ORDER BY available_at DESC LIMIT 1;
```

## 7. Constraints de integridade

```sql
CHECK ( (status_at_compute='valid' AND quadrant IS NOT NULL AND candidate_quadrant IS NOT NULL
         AND candidate_confidence IS NOT NULL AND candidate_confidence >= 0.70 AND transition_pending=FALSE)
     OR (status_at_compute<>'valid' AND quadrant IS NULL) );
CHECK ( status_at_compute NOT IN ('unavailable','invalid') OR candidate_confidence IS NULL );
```
Também: quality fields ∈ [0,1]; `stale_after <= data_stale_after`; `stale_after <= pipeline_stale_after`;
`computed_at >= available_at`; `as_of <= available_at`; `model_version`/`source_vintage_hash` não-vazios.

## 8. `available_at` e point-in-time

`available_at_snapshot = max(computed_at, max_j available_at_j)` sobre inputs necessários j.
Backtest filtra `snapshot.available_at <= decision_time` (NUNCA só `as_of <= decision_date`).
Revisions/restatements só alteram o modelo a partir da própria data de disponibilidade.

## 9. `stale_after`

Cada fonte declara: `expected_cadence`, `grace_period`, `hard_max_age`, `critical`, `available_at`, `next_expected_release`.
Por fonte crítica j: `expiry_j = min(next_expected_release_j + grace_j, available_at_j + hard_max_age_j)`.
`data_stale_after = min_{j∈critical} expiry_j`. `pipeline_stale_after = computed_at + 2 dias úteis`.
`stale_after = min(data_stale_after, pipeline_stale_after)`. (Os dois componentes persistidos separadamente.)

Hard max ages iniciais: diária 3 dias úteis; semanal 14 corridos; mensal 45 corridos; trimestral 120 corridos.
Fonte mensal com calendário confiável: `next_expected_release + 5 dias úteis`.

## 10. Auditoria da qualidade

Snapshot principal guarda só agregados (coverage/freshness/source_health quality, uncertainty raw/adjusted).
Contribuições por indicador vão em tabela de auditoria ligada por `snapshot_id`. Permite distinguir: macro
ambíguo / falta de cobertura / fonte atrasada / falha de ingestão / revisão anormal / incerteza estatística alta.

---

# Parte B — Gate de risco

## 11. Contrato do gate

```python
GateState = Literal["risk_on", "risk_off"]

@dataclass(frozen=True)
class GateSnapshot:
    state: GateState | None
    as_of: date
    available_at: datetime
    computed_at: datetime
    stale_after: datetime
    status_at_compute: ComputeStatus
    model_version: str
    source_vintage_hash: str
```
Backend consome gate só com state válido ∧ effective_status==valid ∧ available_at ≤ decision_time ∧ stale_after > now.
Gate ausente NÃO vira `risk_on`. Para `regime_aware`, quadrant e gate devem ser **simultaneamente** consumíveis.

---

# Parte C — Policy Core

## 12. Separação de responsabilidades

`QuadrantPolicy` (centro, bandas, envelope) → `GateOverlay` (aperta risco) → Black-Litterman (direção dentro
do envelope) → Two-level compiler (categorias→book) → Solver (resolve sem alterar identidade). **Sem `gate+quadrant→estado híbrido`.**

## 13. Sete sleeves estruturais

```python
STRUCTURAL_SLEEVES = ("cash","equity","fixed_income","thematic","alternatives","gold","long_short")
```
Removidos da base: `hedge`, `SH`, `STAG_GOLD`, `GOLDFIX_TARGET`.

## 14. Contrato de `QuadrantPolicy`

```python
@dataclass(frozen=True)
class Budget:
    lo: float
    hi: float

@dataclass(frozen=True)
class QuadrantPolicy:
    center: dict[str, float]
    half_width: dict[str, float]         # larguras FINAIS efetivas; sem HW_SCALE/multiplicador em runtime
    risk_assets_cap: float
    defensive_floor: float
    fixed_income_sub_budgets: dict[str, Budget]
    policy_version: str
```
Indexadas por `QUADRANT_POLICIES[profile][quadrant]` — **3 perfis × 4 quadrantes = 12 políticas**.
A aplicação não inicia se qualquer combinação faltar.

## 15. Invariantes das políticas

`Σ_g center_g = 1`; `0 ≤ center_g ≤ 1`; `lo_g = center_g − half_width_g`; `hi_g = center_g + half_width_g`;
`0 ≤ lo_g ≤ center_g ≤ hi_g ≤ 1`; `Σ lo_g ≤ 1 ≤ Σ hi_g`; `equity+thematic ≤ risk_assets_cap`;
`cash+fixed_income+gold+long_short ≥ defensive_floor`. Centros que não somam 100% falham no startup. **Sem normalização em runtime.**

## 16. Política completa dos 4 quadrantes

Os 4 no mesmo artefato versionado. Nenhum pode ser alias/sentinel/branch-que-pula-solver/carteira-fixa-igual-entre-perfis.
- **RECOVERY:** crescimento ↑, inflação ↓; mais equity/thematic; FI equilibrada; menos cash estrutural.
- **EXPANSION:** crescimento ↑, inflação ↑; equity ainda relevante; atenção a inflação/commodities/duração.
- **SLOWDOWN:** crescimento ↓, inflação pressionada; menos equity/thematic; menos duração longa; mais inflação-linked/cash/gold/diversificadores.
- **CONTRACTION:** crescimento ↓, inflação ↓; mais cash/soberano; duration de qualidade; equity/thematic reduzidos; crédito especulativo limitado.

## 17. Priors de calibração — SLOWDOWN (sementes de pesquisa, não aprovados)

| Perfil | Cash | Equity | FI | Thematic | Alt | Gold | L/S |
|---|---:|---:|---:|---:|---:|---:|---:|
| Aggressive | 10% | 26% | 21% | 4% | 14% | 14% | 11% |
| Moderate | 15% | 17% | 27% | 3% | 13% | 14% | 11% |
| Conservative | 20% | 7% | 34% | 1% | 10% | 15% | 13% |

## 18. Priors de calibração — CONTRACTION (sementes)

| Perfil | Cash | Equity | FI | Thematic | Alt | Gold | L/S |
|---|---:|---:|---:|---:|---:|---:|---:|
| Aggressive | 16% | 18% | 35% | 2% | 6% | 11% | 12% |
| Moderate | 22% | 10% | 41% | 1% | 5% | 11% | 10% |
| Conservative | 27% | 4% | 45% | 0% | 4% | 10% | 10% |

## 19. Half-widths

Cada política armazena a largura FINAL por sleeve/perfil. **Sem `HW_SCALE`/`WIDTH_MULTIPLIER` em runtime**
(ferramenta offline pode usar multiplicadores p/ gerar candidatos; o arquivo aprovado guarda só os finais).
Seed de pesquisa (± pp): Cash 4/4; Equity 6/4; FI 6/6; Thematic 2/1; Alt 4/3; Gold 4/3; L/S 3/3 (SLOWDOWN/CONTRACTION).

## 20. Renda fixa interna

`fixed_income` agregada no mandato, mas sub-budgets **quantitativos e versionados**:

```python
FIXED_INCOME_BUCKETS = ("sovereign_short_intermediate","sovereign_long_duration","inflation_linked",
                        "investment_grade_credit","high_yield_preferred","structured_private_credit")
```
Enquanto não definidos, o produto NÃO deve declarar que implementa tilts internos de FI.

---

# Parte D — Gate Overlay

## 21. Princípio
Gate não altera quadrante/centro/taxonomia/mapeamento de sleeves/prior de mercado. Só aperta o envelope de risco.

## 22. Parametrização v1 (forma comum + intensidade por perfil)

```python
@dataclass(frozen=True)
class GateOverlayShape:
    cvar_tightening: float
    beta_tightening: float
    risk_assets_reduction: float

@dataclass(frozen=True)
class ProfileGatePolicy:
    intensity: float
    bl_view_confidence_multiplier: float
```
`risk_on` = identidade (cvar×1, beta×1, reduction 0, BL×1). Para `risk_off`:
`effective_cvar_mult = 1 − intensity·cvar_tightening`; `effective_beta_mult = 1 − intensity·beta_tightening`;
`effective_risk_assets_cap = base_risk_assets_cap − intensity·risk_assets_reduction` (risk_assets = equity+thematic).
Sem shifts independentes por sleeve na v1. `defensive_floor` permanece definido pelo quadrante na v1.

## 23. Invariantes do gate
cvar_mult ∈ (0,1]; beta_mult ∈ (0,1]; reduction ≥ 0; intensity ∈ [0,1]; gate nunca aumenta risco / injeta SH /
altera centro / cria quadrante. A intensidade preserva o ladder entre perfis (não colapsa para a mesma carteira).

## 24. Black-Litterman views

`bl_view_confidence_multiplier`: 0.0 → omite views (μ=π); 0.5 → meia-confiança; 1.0 → normal.

```python
if overlay.bl_view_confidence_multiplier == 0.0:
    mu = pi; views = None
else:
    effective_confidence = base_confidence * overlay.bl_view_confidence_multiplier
```
**Nunca passar `confidence=0` para `omega_idzorek()`.** v1: `risk_off.bl_view_confidence_multiplier = 0.0` (política fixa, não hiperparâmetro).

---

# Parte E — Integração Two-Level

## 25. Pipeline único (todos os quadrantes)

```
validar quadrant snapshot → validar gate snapshot → carregar QuadrantPolicy → aplicar GateOverlay
→ resolver universo de 7 sleeves → construir matriz M → compilar constraints no Level-1
→ preflight de viabilidade → solver primário → fallback apenas de objetivo → expandir y=Mx → pós-verificação
```

## 26. Universo completo
Padrão `universe_policy="complete_macro"`: sleeves ausentes preenchidas com proxies autorizados e identificados na
resposta. `universe_policy="strict"`: sleeve obrigatória ausente → `MISSING_REQUIRED_SLEEVES`. **Sem renormalização automática.**

## 27. Matriz de implementação
`y = M x` (x = pesos Level-1, y = book final, M = implementação determinística). Compila no Level-1: cap por fundo
`(Mx)_i ≤ cap_i`; min_weight; overlap `H M x ≤ overlap_cap`; beta; exposições agregadas. Level-2 = equal-weight por categoria (política aprovada).

## 28. Preflight de viabilidade
LP de viabilidade com TODAS as constraints antes do solver financeiro. Checks: `Σlo ≤ 1 ≤ Σhi`; `Σ cap_eff ≥ 1`;
`lo_i ≤ hi_i`; `lo_i ≤ cap_eff_i`. Diferencia: `structurally_infeasible` / `data_unavailable` / `policy_invalid` / `solver_failed`.

## 29. Fallback
Só muda o objetivo: `BL utility → min-CVaR`. Idênticos: universo, quadrante, gate, bandas, caps, min_weights, overlap,
beta, CVaR hard limit, proxies preenchidos. **Sem fallback para S4a/goldfix/outra política.**

## 30. Pós-verificação (após y=Mx)
sum(weights)=1; long-only; cap por instrumento; min_weight; bandas por sleeve; risk_assets cap; defensive floor;
sub-budgets FI; beta cap; CVaR; overlap look-through; só proxies autorizados. Qualquer violação → erro, nenhum peso publicado.

---

# Parte F — Erros e comportamento operacional

## 31. Erros estruturados (nenhum retorna pesos)

`QUADRANT_UNAVAILABLE` (ausente/ambíguo/vencido) · `GATE_UNAVAILABLE` · `POLICY_NOT_FOUND` (profile×quadrant) ·
`MISSING_REQUIRED_SLEEVES` (strict) · `POLICY_INFEASIBLE` · `SOLVER_FAILED` (nenhum solver `optimal`) ·
`CONSTRAINT_VIOLATION` (pós-verificação) · `POLICY_VERSION_MISMATCH` (worker/backend incompatíveis).

## 32. No-trade
Quando `regime_aware` não pode ser produzida: não inventa carteira; pode manter operacionalmente a carteira aprovada;
nenhum rebalanceamento. É no-trade, não nova recomendação. `strategic_neutral` existe só como objetivo explícito, nunca fallback silencioso.

---

# Parte G — Calibração (parameter freeze pendente)

## 33. Escopo
A calibrar: centros dos 4 quadrantes; half-widths finais; risk_assets caps; defensive floors; sub-budgets FI; forma
comum do gate; intensidades por perfil; thresholds de confidence; SLA de staleness. Arquitetura congelada, valores não.

## 34. Redução de graus de liberdade
`center_{p,q} = ProjectSimplex(base_p + s_p · Δ_q)` (base_p = centro estratégico do perfil; Δ_q = tilt comum do
quadrante; s_p = intensidade do perfil). Materializado offline como centro explícito normalizado. ProjectSimplex NÃO roda em produção.

## 35. Sequência de calibração
1. Congelar temporariamente: RECOVERY, EXPANSION, gamma, beta caps, views, taxonomia, seleção de fundos.
2. Calibrar SLOWDOWN e CONTRACTION com gate em identidade.
3. Validar: beta, MaxDD, CVaR, Ulcer, recuperação, turnover, effN, concentração, inviabilidade.
4. Congelar os 4 quadrantes.
5. Calibrar o gate por ablação (cvar tightening, beta tightening, risk_assets cap, combinação).
6. Manter `bl_view_confidence_multiplier=0` fixo em risk-off na v1.
7. Walk-forward sobre o livro B. 8. Confirmar ladder dos 3 perfis. 9. Parameter freeze versionado.

---

# Parte H — Deploy e governança

## 36. Ativação atômica
Worker v2 e backend v2 entram em produção JUNTOS. Proibido `worker v1 + backend v2` ou `worker v2 + backend v1`.
Backend valida `snapshot.model_version`, `confidence_model_version`, `policy_version`, API contract version → mismatch = erro estruturado.

## 37. Startup validation
Valida: 12 políticas profile×quadrant presentes; todos os centros somam 1; todos os sleeves presentes; half-widths
finais válidos; risk_assets caps válidos; defensive floors válidos; sub-budgets FI válidos; gate shape válido;
intensidades válidas; nenhum campo legado ativo. Falha impede o serviço de iniciar.

## 38. Testes de aceitação (cobertura mínima)
1. 4 quadrantes × 2 gates × 3 perfis. 2. Quadrant ausente. 3. low-confidence. 4. stale. 5. invalid. 6. Gate ausente/stale.
7. Transição não confirmada. 8. Troca oposta (precedência). 9. Broad diversificado. 10. Explicit monoclasse.
11. `complete_macro` com fills. 12. `strict` sem sleeves. 13. Cap binding. 14. Overlap binding. 15. Beta cap binding.
16. CVaR binding. 17. BL views omitidas em risk-off. 18. Fallback com constraints idênticas. 19. Pós-verificação do book. 20. Nenhum caminho retorna pesos com warnings.

---

# Parte I — Legados aposentados (remover do caminho de produção)

`DEFAULT_QUADRANT` · `None → expansion` · `None → risk_on` · `combined_regime` · `RISK_ON/INFLATION/RISK_OFF` como
substitutos de quadrante · `STAG_GOLD` · `GOLDFIX_TARGET` automático · goldfix que pula o solver · hedge como sleeve
estrutural · SH no prior/centros · `HW_SCALE` oculto · normalização de centros em runtime · fallback S4a ·
forward-fill do último quadrante válido · aceitação de `optimal_inaccurate`.
