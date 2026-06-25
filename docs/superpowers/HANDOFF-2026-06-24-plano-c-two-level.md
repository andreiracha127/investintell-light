# HANDOFF — Plano C: compilador two-level (matriz M + preflight + complete_macro + pós-verificação)

**Data:** 2026-06-24. **Para:** sessão fresh. **Tarefa:** escrever UM plano de implementação (depois executá-lo via SDD com Opus 4.8) para o **Plano C** da rearquitetura COMBO `regime_aware` — o compilador/solver two-level que falta, conforme o freeze v1 **Parte E (§25–§30)**.

Este doc é auto-suficiente. Leia os specs e o estado citados; não re-descubra o que já está mapeado. **Plano C é SÓ backend** (`E:/investintell-light-combo/backend`); o worker de quadrante (datalake) e o policy core já estão prontos.

---

## 0. O que é este projeto (1 parágrafo)

Rearquitetura do alocador `regime_aware` (codinome COMBO) do Investintell Light. Arquitetura nova v1 **congelada** (Architecture Freeze v1): **quadrante (macro, point-in-time) ⊥ gate (mercado, diário)**, 7 sleeves estruturais, fail-loud, sem `combined_regime`/goldfix. Já entregues e validados (SDD Opus + 4 rodadas de `/codex:adversarial-review`): A2 (workers de quadrante, datalake), Backend Policy Core (12 políticas + GateOverlay + `EffectiveRegimePolicy`), o reader §6 e o hardening fail-loud/PIT do path `regime_aware`. **O que falta é o Plano C**: o pipeline two-level formal (compilar TODAS as constraints da política como matriz de implementação `y=Mx`, preflight de viabilidade, fallback de objetivo, pós-verificação completa, e `complete_macro`/`strict`).

## 1. Specs autoritativos (LEIA PRIMEIRO)

- `docs/superpowers/specs/2026-06-23-combo-regime-aware-architecture-freeze-v1.md` — **Parte E (§25–§30) é o seu escopo**: §25 (pipeline único), §26 (universo completo: `complete_macro`/`strict`), §27 (matriz de implementação `y=Mx` — cap por fundo, min_weight, overlap, beta, exposições agregadas; Level-2 = equal-weight por categoria), §28 (preflight de viabilidade LP), §29 (fallback só-de-objetivo BL→min-CVaR), §30 (pós-verificação completa). Leia também §31 (erros estruturados: `MISSING_REQUIRED_SLEEVES`/`POLICY_INFEASIBLE`/`SOLVER_FAILED`/`CONSTRAINT_VIOLATION`), §13 (7 sleeves), §38 (os ~20 testes de aceitação — vários são two-level: cap/overlap/beta/CVaR binding, fallback, pós-verif, `complete_macro` fills, `strict` sem sleeves), §I (legados aposentados — não reintroduzir).
- `docs/superpowers/specs/2026-06-23-combo-scope-decision-macro-v1.md` — contexto (o quadrante é consumido como contrato já materializado).

Os números de seção (§N) abaixo referem-se ao freeze v1.

## 2. Repo / branch / ambiente

| Item | Valor |
|---|---|
| Repo | `E:/investintell-light-combo` (código em `backend/`) |
| Branch | `feat/combo-regime-allocator` |
| HEAD | `ac6b1f0` (fim do regime_aware hardening) |
| venv / testes | `backend/.venv/Scripts/python.exe -m pytest` rodado de `backend/` |
| Lint | `backend/.venv/Scripts/python -m ruff check` (ruff está no venv) |
| Suite baseline | **1587 passed / 0 skipped** |
| Plano (.md) salvo em | `E:/investintell-light-combo/docs/superpowers/plans/` |
| Ledger SDD | `E:/investintell-light-combo/.superpowers/sdd/progress.md` (toda a linha A2/Policy-Core/fixes está aqui) |

- **Sem remote** (merges locais). **NÃO mergear para `main` nem popular prod** — ativação atômica é A5 (freeze §36).
- O quadrante real (`regime_quadrant_snapshot`) NÃO está deployado no DB do backend até A5; o reader (`quadrant_reader.fetch_quadrant_snapshot`) degrada a `None` (→ `QUADRANT_UNAVAILABLE`). Testes do two-level mockam o reader/gate (ver os testes existentes em `backend/tests/test_builder_regime_two_level.py`).

## 3. O que JÁ está feito (NÃO refazer) — e o que o Plano C consome/estende

**Policy Core (consome como contrato).** `app/services/effective_policy.py::build_effective_policy(quadrant_snapshot, gate_snapshot, profile, *, base_cvar_limit) -> EffectiveRegimePolicy`. O `EffectiveRegimePolicy` (frozen) carrega os NÚMEROS FINAIS que o Plano C compila: `sleeve_budgets: dict[str, Budget(lo,hi)]` (7 sleeves), `risk_assets_cap`, `defensive_floor`, `beta_cap` (AGREGADO de carteira), `cvar_limit`, `bl_view_confidence_multiplier`, `fixed_income_sub_budgets` ({} na v1), lineage ids. As 12 políticas + invariantes §15 estão em `app/services/quadrant_policy.py`; o overlay em `app/optimizer/gate_overlay.py`. Startup validation em `app/core/policy_startup.py`.

**Two-level PARCIAL já existente no builder** (`app/services/portfolio_builder.py`) — o Plano C FORMALIZA/COMPLETA isto, não começa do zero:
- `_solve_regime_two_level` (~710): o solve `regime_aware` (proxy→fund). Chamado pelo dispatch `regime_aware` (que já wira o reader §6 + gate fresh + `eff_policy`).
- `_solve_regime_level1` (~584): solve Level-1 sobre as sleeves (proxies), com BL+CVaR e fallback min-CVaR. **Já aplica** (N1) as aggregate constraints `equity+thematic ≤ eff_policy.risk_assets_cap` e `cash+fi+gold+long_short ≥ eff_policy.defensive_floor` via `LinearConstraint` (ver `_regime_aggregate_cons` ~546). Infeasível → `PolicyInfeasibleError`→422.
- Level-2 (~808): fund **equal-weight** por categoria (uma sleeve proxy-only mantém o proxy). Isto é a "implementação determinística" do §27 (Level-2 = equal-weight por categoria) — confirme e formalize como a matriz `M`.
- Fills autorizados para `gold`/`long_short` (~658) quando a sleeve não tem fundo (gold via GLD, long_short via FTLS).
- `_resolve_overlap_constraints` (~891): overlap look-through (pruned per-equity `H·w ≤ overlap_cap`) — JÁ existe e é usado pelos outros objetivos; **verifique se está wired no regime two-level** (provavelmente NÃO está — é um dos gaps).
- `beta_graduated_caps` (per-asset throttle, `taa_bands.py`) preservado e DORMANT (Plano C decide se/como usar); o `eff_policy.beta_cap` AGREGADO está EXPOSTO mas NÃO enforçado (RELEASE GATE) — é o Plano C que o compila.
- `engine.LinearConstraint(coef, lo, hi)` (`app/optimizer/engine.py`): contrato genérico de constraint linear (`coef·w ≤ hi` / `≥ lo`), já threaded em `solve_bl_utility_cvar` E no fallback `solve_min_cvar`. É o mecanismo para compilar as constraints da matriz M.

**Hardening fail-loud/PIT do regime_aware (já fechado — não regredir):** reader §6 wired (sem `gate_snap.quadrant`), gate-state strict {risk_on,risk_off}, gate stale max-lag (`GATE_MAX_LAG_BUSINESS_DAYS=5`), gate future-date rejeitado, caps agregados enforçados no Level-1. Detalhes no ledger SDD + memória `combo-regime-aware-rearch.md`.

## 4. Dossiês de pesquisa (consultar para detalhes finos)

- `E:/light-patches/combo-research/2026-06-23-gap-analysis-freeze-v1.json` → **`result.'g4-two-level-compiler'`** é o seu mapa principal (matriz M, preflight, pós-verificação: REUSÁVEL/MUDA/NOVO/ESFORÇO). Também `g5-postverif-errors-legacy`. Parsear: `(Get-Content $f -Raw | ConvertFrom-Json).result.'g4-two-level-compiler'`.
- `E:/light-patches/combo-research/2026-06-23-terrain-map.json` → `result.'r3-engine-solvers'` e `r4-overlap-lookthrough`.

---

## 5. Escopo do Plano C — os blocos (provável decomposição do plano)

O freeze §25 define o pipeline único. Os blocos abaixo são o delta do que falta sobre o two-level parcial existente. **Tudo no `regime_aware` path; fail-loud sempre (nunca pesos com warnings).**

1. **`complete_macro` / `strict` (§26)** — resolve o achado R4 (deferido pelo dono): hoje sleeves com `lo>0` sem proxy (ex. `alternatives`, `thematic`) ficam em 0 → weights fora do envelope. `universe_policy="complete_macro"` (default): preencher TODOS os sleeves ausentes com **proxies autorizados** (estender os fills de gold/long_short para alternatives/thematic/etc.; identificar os fills na resposta). `universe_policy="strict"`: sleeve obrigatória ausente → `MISSING_REQUIRED_SLEEVES` (422). **Sem renormalização automática.** (Definir os proxies ETF autorizados por sleeve é uma ambiguidade — ver §8.)
2. **Matriz de implementação `M` (§27)** — formalizar `y = M x` (x = pesos Level-1 das sleeves/categorias, y = book final fund-level, M = expansão determinística, hoje equal-weight por categoria). Compilar no Level-1 como constraints sobre `x` (via `M`): **cap por fundo** `(Mx)_i ≤ cap_i`; **min_weight**; **overlap** `H M x ≤ overlap_cap` (wire o `_resolve_overlap_constraints` existente ao regime path); **beta agregado** `(Mᵀβ)ᵀ x ≤ eff_policy.beta_cap` (o beta_cap fund-level que hoje é só exposto); **exposições agregadas** (risk_assets_cap/defensive_floor — já feitas no N1, integrar à compilação M). Level-2 = equal-weight por categoria (política aprovada — formalizar).
3. **Preflight de viabilidade (§28)** — LP com TODAS as constraints ANTES do solver financeiro. Checks: `Σlo ≤ 1 ≤ Σhi`; `Σ cap_eff ≥ 1`; `lo_i ≤ hi_i`; `lo_i ≤ cap_eff_i`. Diferenciar os erros: `structurally_infeasible` (POLICY_INFEASIBLE) / `data_unavailable` (QUADRANT/GATE_UNAVAILABLE) / `policy_invalid` / `solver_failed` (SOLVER_FAILED). Hoje a infeasibilidade é detectada só pelo solver lançar `OptimizerError` (rotulado POLICY_INFEASIBLE de forma um pouco grosseira — ver Minor no ledger); o preflight a torna explícita ANTES e com a causa certa.
4. **Solver primário + fallback só-de-objetivo (§29)** — primário = BL utility + CVaR; fallback = min-CVaR com universo/quadrante/gate/bandas/caps/min_weights/overlap/beta/CVaR-hard-limit/proxies **IDÊNTICOS** (só o objetivo muda). Sem fallback para S4a/goldfix/outra política (já aposentados). O `_solve_regime_level1` já tem BL→min-CVaR; garantir que o fallback preserva TODAS as constraints da matriz M.
5. **Pós-verificação completa (§30)** — após `y = Mx`, verificar: `sum=1`; long-only; cap por instrumento; min_weight; **bandas por sleeve (TODOS os 7, não só os agregados)**; risk_assets cap; defensive floor; sub-budgets FI; beta cap; CVaR; overlap look-through; só proxies autorizados. Qualquer violação → `CONSTRAINT_VIOLATION` (erro estruturado, nenhum peso publicado). Isto também fecha estruturalmente o R4 (um sleeve com `lo>0` em 0 é pego pela pós-verificação se o `complete_macro` não o preencheu).
6. **Erros estruturados + testes de aceitação (§31/§38)** — mapear cada falha ao erro do §31; cobrir os cenários two-level do §38 (cap binding, overlap binding, beta cap binding, CVaR binding, fallback com constraints idênticas, pós-verificação do book, `complete_macro` com fills, `strict` sem sleeves, "nenhum caminho retorna pesos com warnings").

## 6. Decisões travadas (não re-litigar)

- 7 sleeves estruturais; SH/hedge só research. Fail-loud absoluto (§1.7): nunca pesos com warnings/violação; nunca relaxa constraint; `QUADRANT_UNAVAILABLE`/`GATE_UNAVAILABLE`/`POLICY_INFEASIBLE`/`MISSING_REQUIRED_SLEEVES`/`SOLVER_FAILED`/`CONSTRAINT_VIOLATION` + no-trade quando inválido.
- `beta_cap` é AGREGADO de carteira (`eff_policy.beta_cap`), compilado via `(Mᵀβ)ᵀx ≤ beta_cap`; o `beta_graduated_caps` per-asset é um conceito DIFERENTE (preservado, dormant — não conflatar).
- Level-2 = equal-weight por categoria (política aprovada §27). `fixed_income_sub_budgets` = contrato vazio na v1 (não impor tilts FI).
- A calibração dos seeds (caps/half_widths/PROFILE_PORTFOLIO_BETA_CAPS/overlap_cap/o seed infeasível aggressive/recovery/risk_off) é A4 (dono) — o Plano C implementa a ESTRUTURA; valores ficam como estão.
- Ativação atômica A5: NÃO mergear para main nem popular prod.

## 7. Como executar (padrão estabelecido nesta linha de trabalho — replicar)

1. **Planejar**: skill `superpowers:writing-plans` → UM plano em `docs/superpowers/plans/2026-06-24-plano-c-two-level.md` (header + Global Constraints + tasks TDD bite-sized com código real, sem placeholders; ver os planos A2/Policy-Core como modelo de granularidade). Decompor pelos blocos §5 (provavelmente: complete_macro/strict → matriz M + cap/min/overlap/beta compile → preflight LP → fallback → pós-verificação completa → erros/aceitação). Antes de escrever, leia o g4 e o estado real do `_solve_regime_two_level`/`_solve_regime_level1`/`_resolve_overlap_constraints` (não re-derive).
2. **Executar**: skill `superpowers:subagent-driven-development` com **Opus 4.8** (implementers + reviewers Opus; reviewers mecânicos podem ser Sonnet). Um subagente fresco por task; review spec+qualidade por task; fix-loop em Critical/Important; ledger em `.superpowers/sdd/progress.md` (continuar o existente); review final whole-branch; depois **`/codex:adversarial-review`** (`node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" adversarial-review "--wait --base <BASE> ..."`, `CLAUDE_PLUGIN_ROOT=.../openai-codex/codex/1.0.4`) como 2ª validação — esta linha de trabalho pegou bugs REAIS de fail-loud/PIT que os reviews per-task subestimaram; rodar até convergir. Scripts SDD: `task-brief PLAN N` / `review-package BASE HEAD` (de `.../skills/subagent-driven-development/scripts/`, rodados da raiz do repo). DDL não se aplica (Plano C é puro Python/solver).
3. Suite baseline 1587 deve permanecer verde; rodar a full suite antes de cada commit (toda TestClient boota pelo startup hook).

## 8. AMBIGUIDADES a resolver com o dono (antes ou durante o plano — propor default e seguir)

- **Proxies autorizados por sleeve para `complete_macro`** (§26): hoje só gold→GLD, long_short→FTLS. Faltam alternatives/thematic (e cash/equity/fixed_income já costumam ter fundos). Propor um mapa seed sleeve→ETF proxy autorizado (ex. alternatives→? thematic→?) e marcar como calibração A4; o dono confirma os tickers.
- **`universe_policy` default na v1**: `complete_macro` (preenche, mais utilizável) vs `strict` (fail-loud). O freeze sugere `complete_macro` como padrão; confirmar.
- **Beta fund-level**: os betas dos fundos vêm de onde no request path (há `taa_bands.asset_betas`/SPY signal)? Confirmar a fonte de β para compilar `(Mᵀβ)ᵀx ≤ beta_cap` sem reintroduzir o `_load_spy_signal` dead-ish (ou usar os betas já carregados).
- **Granularidade de `M`**: Level-1 sobre sleeves (7) vs sobre categorias (sub-sleeve). O §27 fala em "categoria"; confirmar se a categoria = sleeve na v1 (equal-weight por sleeve) ou há um nível intermediário.

## 9. Estado de memória

Memória de projeto: `combo-regime-aware-rearch.md` (resume A2 + Policy Core + reader + os 5 fixes fail-loud + o R4 deferido a Plano C) — linka [[combo-regime-allocator-build]] [[combo-bl-utility-calibration]]. Atualizar ao fim do Plano C. Ledgers SDD vivem no repo (`.superpowers/sdd/progress.md`).
