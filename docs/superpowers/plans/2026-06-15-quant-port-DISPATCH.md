# Quant Port — DISPATCH para nova sessão (retomar com Opus 4.8)

> **Motivo deste dispatch:** durante a execução, houve um **incidente da API do Opus 4.8** (status.claude.com: "Elevated errors on Claude Opus 4.8 — Investigating", 06:20 UTC 2026-06-15). Para destravar, os agentes dos workflows foram trocados para **Sonnet 4.6**, que avançou bastante. O dono determinou: **"esta implementação é importante demais para despachar para agentes Sonnet"** — então o trabalho feito por Sonnet deve ser **re-revisado em nível Opus (ou refeito)** antes do merge, e o restante deve ser executado por **agentes Opus 4.8** numa sessão nova.

## 0. Antes de começar (pré-condição)
- **Confirmar que o incidente do Opus 4.8 foi resolvido** — checar `https://status.claude.com`. Se ainda estiver "Investigating/Identified", os agentes Opus voltarão a dar **529 Overloaded**. Não relançar até resolver.
- Skill governante: `superpowers:subagent-driven-development` (por task: implementer → revisão de spec → revisão de qualidade, em worktrees isolados).
- **Modelo dos agentes: Opus 4.8** (default; NÃO passar `model: 'sonnet'`).

## 1. Onde está tudo
- Planos: `docs/superpowers/plans/2026-06-14-quant-port-{overview,tier1,tier2,tier3}.md`. O `overview` é a fonte de verdade de dependências cruzadas.
- Worktrees (light, repo `E:/investintell-light`):
  - `feat/quant-port-tier1` → `.claude/worktrees/quant-port-tier1`
  - `feat/quant-port-tier2` → `.claude/worktrees/quant-port-tier2`
  - `feat/quant-port-tier3` → `.claude/worktrees/quant-port-tier3` (ainda em `d382c0f`, vazio)
- Worktree workers (repo `E:/investintell-datalake-workers`):
  - `feat/quant-port-tier1` → `E:/investintell-datalake-workers-port-tier1`
- Scripts de workflow já prontos (editar `model` p/ Opus e reusar via `scriptPath`): em `…/workflows/scripts/quant-port-*.js`.
- Ambiente: Python 3.13.12 / pandas 3.0.1 / numpy 2.2.6 / pytest 9.0.2. Comando: `cd backend && python -m pytest …`. Worker harness: `python -m pytest tests/test_risk_metrics.py` da raiz do repo de workers (sem pyproject/conftest; testes DB se auto-skipam).

## 2. Estado atual (git = fonte de verdade) — TUDO VERDE
- **Tier 1 worktree:** `python -m pytest -q` → **753 passed**. Falta só **T1B-9** (regen OpenAPI/TS types do FundRiskOut).
- **Tier 2 worktree:** `python -m pytest -q` → **787 passed**. Faltam **T2D-2..5, T2E-1/2, T2F-1/2/3, T2G-1..5**.
- **Workers worktree:** T1B-1..6 commitados (Opus).

### Linha Opus vs Sonnet (CRÍTICO para a revisão)
**Feito por Opus (ou correção manual minha — confiável):**
- Tier 1: T1C-1/2/3, T1A-1, T1A-2, **T1A-3 (fix manual, commit `0e42d9c`)**, T1A-4, T1A-5.
- Tier 2: T2A-1..5, T2C-1, T2C-2, T2C-3 (commit `e118af3` — ficou sem revisão por 529; **verifiquei manualmente**: diff limpo, em escopo, gate G5 OK), **T2B-1 (fix manual, commit `3e18e1d`)**.
- Workers: T1B-1..6.

**Feito por Sonnet 4.6 (RE-REVISAR em nível Opus, ou refazer):**
- Tier 1: faixa `ca71be4..aadf629` → **T1A-6 (active_share), T1A-7, T1A-8, T1D-1, T1D-2, T1D-3, T1D-4, T1B-7, T1B-8**.
- Tier 2: faixa `5f4ad38..987151e` → **T2B-2, T2B-3, T2B-4 (+exports do T2B-5 presentes), T2C-4, T2C-5 (CVaR-as-constraint, CLARABEL→SCS), T2C-6 (max_return_cvar), T2C-7, T2C-8, T2D-1 (walk-forward)**.
  - Inspecionar: `git -C <tier1-wt> log --oneline ca71be4..aadf629` e `git -C <tier2-wt> log --oneline 5f4ad38..987151e`.
  - **Atenção especial** aos itens institucionais de mais julgamento: **T2C-5** (solver ladder + verificador de CVaR realizado), **T2C-6** (objetivo max-return com mu BL / gate G5), **T2C-7/8** (CVaR por regime), **T2D-1** (backtest walk-forward).
  - **T2B-5:** não há commit com esse nome, mas os exports públicos (`variance_risk_budget`, `etl_risk_budget`, `portfolio_starr`) existem e a suíte passa. Conferir contra o spec literal do T2B-5 (export surface + guarda estrutural do gate G5).

### Opções para o trabalho Sonnet (decisão do dono na nova sessão)
- **(A) Revisar em nível Opus e manter o que passar** (recomendado — está tudo verde; despachar um revisor Opus por commit Sonnet, com mandato de refazer qualquer um que não atinja o padrão). Mais barato; preserva o verde.
- **(B) Reset e refazer com Opus:** `git -C <tier1-wt> reset --hard 518a99f` (volta ao último Opus do Tier 1) e `git -C <tier2-wt> reset --hard 3e18e1d` (último Opus do Tier 2), depois reexecutar as tasks Sonnet com agentes Opus. Mais caro; descarta trabalho verde.

## 3. Defeitos de plano já encontrados (PADRÃO A VIGIAR)
Dois testes literais do plano usavam **tolerância exata sobre dados aleatórios**, impossível sob numpy 2.x — corrigidos por mim:
- **T1A-3:** `test_information_ratio_nan_input_raises` — `information_ratio` agora é fail-loud em NaN (reject_nan) como `sharpe`/`sortino`. Plano canônico corrigido (commit `85432ec` no worktree de planos).
- **T2B-1:** `test_diagonal_sigma_closed_form` — `rtol 1e-6 → 5e-2` (amostra finita não é exatamente diagonal). Lógica estava correta.
**Vigiar o mesmo padrão no Tier 3** (ex.: RMT/Marchenko-Pastur, tail-VaR, correlation-regime — testes com tolerância apertada sobre dados sintéticos). Implementers devem reportar **BLOCKED** com o desvio numérico exato em vez de mascarar.

## 4. Trabalho restante
1. **Tier 1:** `T1B-9` (regen OpenAPI/TS para os 4 campos novos de FundRiskOut).
2. **Tier 2:** `T2D-2, T2D-3, T2D-4, T2D-5` (backtest walk-forward: schemas/serviço/rota/gate), `T2E-1` (absorption_ratio), `T2E-2` (atribuição de fatores sobre `factor_model_fits` — NÃO refitar), `T2F-1/2/3`, `T2G-1..5`.
3. **Tier 3 (31 tasks) — STAGED.** Pré-requisitos de código cruzados: **antes de lançar, mesclar `feat/quant-port-tier1` + `feat/quant-port-tier2` em `feat/quant-port-tier3`**. Deps: T3F-3/T3G-1/T3G-2 ← T2C-5; T3F-1 ← T2E-1; T3C ← T1B. Tasks de worker (T3B-2/3, T3C-2/3 e possivelmente T3E-2/T3G) → worktree de workers. **T3F-6 ANTES de T3F-5.**
   - **PULAR (decisões de produto do dono, não port mecânico):** **T3G-4** (governança de breach CVaR — exige modelo de dados novo), **T3G-6** (TAA regime bands — spike "NO code"), **T3G-7** (track de fatores fundamental — spike "NO code").

## 5. Receita de orquestração (replicar a que funcionou)
- Pipelines paralelos por worktree; dentro de um worktree, tasks **sequenciais** (compartilham `__init__.py`, `engine.py`, etc.).
- Por task: implementer (lê SÓ a seção `### Task X:` do plano, executa os passos TDD literais, roda o comando de teste exato, commita com a msg do plano + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`) → revisor de spec → revisor de qualidade → loops de correção.
- **Números de linha do plano são âncoras do arquivo pristino e JÁ deslocaram** — localizar por símbolo, nunca por linha absoluta.
- Ordem interna T2C (já feita): #10→#11→#9→#13 = T2C-1/2 (bounds) → 3/4 (turnover) → 5/6 (CVaR-constraint) → 7/8 (regime).
- Os scripts `.js` em `…/workflows/scripts/quant-port-*.js` servem de molde: para Opus, **remover o `model: 'sonnet'`** (deixar herdar Opus) e ajustar a lista de tasks restantes.

## 6. Antes do merge para `main`
- **Revisão final em nível Opus** de todos os commits (especialmente os faixa-Sonnet acima) por branch, antes de mesclar `feat/quant-port-tier{1,2,3}` → `main`.
- Rodar a suíte completa de cada worktree (alvos: Tier 1 753+, Tier 2 787+, mais o que o restante adicionar) e o gate de rota/contrato.
- Memória de projeto relacionada: [[quant-port-tier-orchestration]], [[quant-legacy-vs-light-review]].
