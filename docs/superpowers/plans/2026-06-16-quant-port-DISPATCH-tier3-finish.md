# Quant Port — DISPATCH #2: terminar Tier 3 + merge final (sessão nova, Opus 4.8)

> **Por que este dispatch:** Tier 1 e Tier 2 estão 100% concluídos e verdes. O Tier 3 está ~20/28 e a sessão interativa ficou longa/lenta demais para terminar (o runtime de Workflow caiu silenciosamente 2x durante o Tier 3, ~30–40 min de execução cada). Workflows **não retomam entre sessões** (resume é same-session). Então a sessão nova parte do **estado git (durável)** e roda só o que faltar. **NÃO confie em contagens deste doc — verifique o git primeiro (STEP 0).**

## Skill governante
`superpowers:subagent-driven-development` (por task: implementer → spec review → quality review, em worktrees isolados). Modelo dos agentes: **Opus 4.8** (não passar `model: 'sonnet'`). Ultracode: orquestrar via Workflow.

## Ambiente
Python 3.13 GLOBAL (sem `.venv` por-worktree; deps no site-packages global: numpy 2.2.6 / pandas 3.0.1 / cvxpy / scikit-learn; scipy importável). Light: `cd <wt>/backend && python -m pytest -q`. Workers: da RAIZ do repo de workers `python -m pytest tests/ -q` (sem pyproject/conftest no root; testes de DB auto-skipam).

---

## STEP 0 — Verificar o estado git ANTES de tudo (fonte de verdade)
Os workflows da sessão anterior podem ter committado mais tasks. Rode:
```
for d in f a g x; do echo "== tier3-$d =="; git -C E:/investintell-light/.claude/worktrees/quant-port-tier3-$d log --oneline afb67ca..HEAD; done
echo "== workers =="; git -C E:/investintell-datalake-workers-port-tier1 log --oneline 85648b9..HEAD
```
Mapeie cada commit a uma task (a msg de commit cita a task). Só rode as tasks que NÃO aparecerem committadas.

---

## 1. Onde está tudo (branches/worktrees)
Repo light `E:/investintell-light`:
- `feat/quant-port-tier1` @ `38b3374` (worktree `.claude/worktrees/quant-port-tier1`) — **COMPLETO**, 753 verde.
- `feat/quant-port-tier2` @ `3a1e1f2` (worktree `…/quant-port-tier2`) — **COMPLETO**, 882 verde.
- `feat/quant-port-tier3` @ `afb67ca` (worktree `…/quant-port-tier3`) — **base de integração**: tier1+tier2 já mesclados, 942 verde. É a branch que vai para `main` no fim.
- Worktrees de cluster do Tier 3 (branches de `afb67ca`, **ainda NÃO mesclados** em `feat/quant-port-tier3`):
  - `feat/quant-port-tier3-a` (`…/quant-port-tier3-a`): **T3A-1..5, T3B-1 DONE** (6/6).
  - `feat/quant-port-tier3-f` (`…/quant-port-tier3-f`): **T3F-1,2,3,4,5,6,7 DONE**; **T3F-8** (gate) em curso/talvez feito.
  - `feat/quant-port-tier3-g` (`…/quant-port-tier3-g`): **T3G-3, T3G-2, T3G-1, T3G-5 DONE** (4/4 — cluster COMPLETO).
  - `feat/quant-port-tier3-x` (`…/quant-port-tier3-x`): **T3D-1 DONE**; **T3D-2, T3D-3, T3E-1, T3E-2** restantes (cluster com mais pendência).

Repo workers `E:/investintell-datalake-workers`:
- Worktree quant: `E:/investintell-datalake-workers-port-tier1`, branch `feat/quant-port-tier1`. Contém **T1B-1..6** + **T3C-1** (cherry-pick `1487bfe`) + **T3B-2** (`436f458`), **T3B-3** (`7f3e033`), **T3C-2** (`b022b85`) DONE; **T3C-3** restante.
- ⚠️ O checkout PRINCIPAL `E:/investintell-datalake-workers` está na branch **`feat/sec-tier-c-ingestion`** (trabalho de SEC, não-relacionado). NÃO trabalhar lá.

Planos: `docs/superpowers/plans/2026-06-14-quant-port-{overview,tier1,tier2,tier3}.md` (no worktree `…/quant-port-tiers-plan`). **Os planos JÁ FORAM CORRIGIDOS** para 3 defeitos (ver §3) — use-os como fonte de verdade canônica.

Scripts de Workflow persistidos (molde reutilizável; NÃO retomáveis entre sessões, mas a estrutura serve): em `…/quant-port-tiers-plan/.claude/.../workflows/scripts/quant-port-tier3-recovery-wf_c60b1055-c82.js` (o mais recente, 3 clusters paralelos com cadeia implement→spec→quality+loops+protocolo anti-masking).

---

## 2. Trabalho restante

### 2a. Tasks Tier 3 (verificar via STEP 0; rodar só as não-committadas)
- **Light, worktree `tier3-f`:** `T3F-8` (full-cluster regression gate — pode ser no-op se a suíte já estiver verde; não-commitado talvez signifique gate sem mudança).
- **Light, worktree `tier3-x`:** `T3D-2` (downside/semi-deviation), `T3D-3` (expense-ratio normalization), `T3E-1` (tail-VaR panel CF mVaR/ETR/Rachev/JB), `T3E-2` (paramétrico Gaussian + EVT POT-GPD fail-closed). ← maior bloco restante.
- **WORKERS, worktree `-port-tier1`:** `T3C-3` (enriquecer peer ranking SQL). NÃO cherry-pickar o `0fcaf13` da branch SEC (conflita no schema, foi escrito sobre base diferente) — re-rodar na base do T1B.

> **ROTEAMENTO CRÍTICO (lição aprendida):** TODO o cluster **T3C é de workers** (`manager_score`, peer ranking vivem em `src/workers/`), apesar de não ter a tag `[repo: ...]` no heading. Rodar T3C-2/T3C-3 SÓ no worktree `E:/investintell-datalake-workers-port-tier1`, commitando com `git -C` nesse path. NÃO deixar o agente navegar para o checkout principal (foi o que corrompeu a branch SEC; ver §4).

### 2b. PULADOS (decisão de produto do dono — NÃO portar): `T3G-4`, `T3G-6`, `T3G-7`.

### 2c. Merge-back (após todas as tasks)
Mesclar `feat/quant-port-tier3-{a,f,g,x}` em `feat/quant-port-tier3` (na ordem; `--no-ff`). Conflitos esperados são **ADITIVOS** e resolvíveis por união:
- `backend/app/analytics/__init__.py` (cada cluster adiciona exports → unir imports + `__all__`).
- `backend/app/main.py` (rotas novas: correlation-regime etc. → manter todas).
- `backend/app/analytics/risk.py` (T3D-2, T3E-1 etc. anexam funções).
- possivelmente schemas/serviços compartilhados.
Técnica usada antes (funcionou): resolver `__init__.py` reescrevendo a união ordenada; para arquivos de teste que ambos "anexam" no fim, reconstruir com `git show :3:<file>` + cauda do `:2:`. Depois `git -C tier3 ... pytest -q` deve ficar verde (alvo > 942 + o que as tasks adicionarem). Remover os 4 worktrees de cluster (`git worktree remove --force`).

---

## 3. Defeitos de plano JÁ CORRIGIDOS (não re-corrigir; estão no plano canônico tier3)
Todos pegos pelo protocolo anti-masking (implementer reporta BLOCKED com o desvio numérico exato, sem mascarar):
- **T3G-2** (`test_verify_realized_cvar_breach`): fixture tinha 10/300 crashes (3,33% < cauda 5%), `historical_cvar` não detectava. **Corrigido**: 18 crashes (>5%).
- **T3D-1** (`test_compute_drifts_status_boundaries_are_inclusive`): `0.45-0.40 == 0.0499…` em IEEE754 < 0.05. **Corrigido**: constante `_BAND_TOL = 1e-9` + comparadores `>= band - _BAND_TOL`.
- **T3B-2** (`test_select_k_recovers_true_k`): argmax puro retorna K=4 (fatores extras inflam R² OOS ~2e-4), teste espera K=2. **Corrigido**: tie-break de parcimônia (`_K_PARSIMONY_TOL = 1e-3`, menor K dentro do tol do máximo). ⚠️ **Isto é um desvio deliberado do argmax legado — o dono deve revisar/aprovar na Fase 4.**

Vigiar o MESMO padrão nas tasks restantes (T3E EVT/tail-VaR têm risco de tolerância sobre dados sintéticos). Implementers DEVEM reportar BLOCKED com o desvio exato, nunca mascarar.

---

## 4. Pendência de limpeza (workers / branch SEC)
Os implementers misrouteados committaram T3C-1 e T3C-3 na branch **`feat/sec-tier-c-ingestion`** do checkout principal de workers, intercalados com commits de SEC:
- `b827d27` (T3C-1), `0fcaf13` (T3C-3), `f89066a` (fix T3C-3).
O **T3C-1 já foi cherry-pickado** para `feat/quant-port-tier1` (commit `1487bfe`) — OK. O **T3C-3 será re-rodado** na base correta (não cherry-pickar: conflita em `risk_metrics.sql` porque foi escrito sobre o schema da branch SEC, não o do T1B).
**AÇÃO Fase 4:** remover `b827d27`, `0fcaf13`, `f89066a` da branch `feat/sec-tier-c-ingestion` ANTES de ela mesclar (rebase -i dropando-os, ou cuidado equivalente) — senão duplicam ao mesclar. Esta é a track do dono de SEC; confirmar com ele.

---

## 5. Fase 4 — antes do merge para produção
1. **Regenerar o contrato de forma autoritativa** (resolve qualquer staleness/conflito de openapi entre tiers): em `feat/quant-port-tier3` (já com tudo mesclado), rodar `make types-check` (ou: `cd backend && uv run python scripts/export_openapi.py` + `cd frontend && pnpm run types`) e commitar `openapi.json` + `api.d.ts`. Tier 1 regenerou só p/ FI/alt; Tier 2 NÃO regenerou (rotas backtest/monte-carlo, EVT/GARCH, mandate, DiagnosticsOut estão stale); Tier 3 adiciona /correlation-regime, PositionDriftOut.status etc. Toolchain disponível: uv, pnpm, node, make.
2. **Review final Opus por branch** (especialmente os itens de mais julgamento do Tier 3: T3F RMT/SOCP/correlation-regime, T3E EVT, T3G BL-Woodbury, e a decisão de parcimônia do T3B-2).
3. **Suíte completa verde** em cada branch + gate de rota/contrato.
4. **Merges:**
   - `feat/quant-port-tier3` → `main` (contém tier1+tier2+tier3 do app light).
   - workers `feat/quant-port-tier1` → workers-main (T1B + T3B-2/3 + T3C-1/2/3).
5. **Decisões menores do dono:**
   - Convenção `FundRiskOut`: campos FI/alt (T1B-8) e EVT/GARCH (T2F-1) saíram como `float|None=None` (opcionais/`?:` no TS), divergindo dos irmãos `float|None` (required-nullable). Em `backend/app/schemas/funds.py`. Padronizar ou manter.
   - UI: `FundProfileView.tsx` teve as linhas dessas métricas removidas em `b634ce9` (eram sempre-NULL); restaurar é tarefa de frontend separada para quando o worker popular não-NULL.
   - Aprovar/reverter o tie-break de parcimônia do T3B-2 (§3).

---

## 6. Receita de orquestração (replicar a que funcionou)
- **Paralelizar por worktree** (1 dir/branch por cluster, todos de `afb67ca`); **sequencial dentro do worktree** (compartilham `__init__.py`/`engine.py`/`main.py`). Depois merge-back.
- Por task: implementer (lê SÓ a seção `### Task X` do plano canônico; localizar por símbolo, NUNCA por linha absoluta — números deslocaram; TDD literal; comando de teste exato; suíte completa; commit com a msg do plano + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`) → spec reviewer (read-only) → quality reviewer (read-only) → loops de fix (máx 2 por estágio).
- **Anti-masking:** implementer com defeito numérico de plano → reset worktree limpo + reportar BLOCKED com desvio exato (NÃO afrouxar tolerância nem mudar valor esperado).
- **Crash do runtime:** caiu silenciosamente ~30–40 min em execuções grandes. Mitigar: lotes menores OU watcher de transcript (dispara se ocioso >6 min) e re-rodar fresh o que faltar (via STEP 0). Dentro da sessão, resume por journal funciona (`Workflow({scriptPath, resumeFromRunId})`); entre sessões NÃO.
- Memórias de projeto: [[quant-port-tier-orchestration]], [[quant-legacy-vs-light-review]].

---

## 7. Resumo de 1 linha para o dono
Tier 1+2 prontos e verdes; Tier 3 ~20/28 (faltam T3F-8, T3G-5, T3D-2/3, T3E-1/2, T3C-2/3 — confirmar via git); depois merge-back dos 4 branches em `feat/quant-port-tier3`, regen de contrato, review final e merges para `main` + workers-main; limpar 3 commits quant da branch SEC; aprovar o tie-break do T3B-2.
