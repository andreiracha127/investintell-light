# Design — Optimizer sobre universo amplo (seleção por estrutura de risco → alocação enxuta)

**Data:** 2026-06-16
**Status:** Design aprovado (brainstorming) — pronto para virar plano de implementação TDD.
**Repo:** `investintell-light` (backend). Construído **por cima de `feat/quant-port-tier3`** (consome RMT/MP denoise, LW constant-correlation e PSD-repair portados no Tier 3).
**Memórias relacionadas:** [[builder-optimize-redesign]], [[quant-port-tier-orchestration]], [[datalake-architecture]].

---

## 1. Problema

O optimizer em `main` resolve sobre uma camada fina de **≤50 fundos**. O cap vem de duas camadas **acima** do otimizador (o Tier 3 não as tocou):

- `MAX_UNIVERSE_ASSETS = 50` (constante de produto, `backend/app/schemas/builder.py`).
- `.limit(max_assets)` no SQL ranqueado por uma métrica única (`backend/app/optimizer/data.py::select_universe_funds`, Gate 4 da cascata).

A cascata atual (Gates): (1) filtros de catálogo (exclui Unclassified, liquidez/AUM, tipo, classe, estratégia, expense, métricas) → (2) histórico mínimo (≥400 NAVs por fundo) → (3) AUM>0 (se BL) → (4) **ranking por métrica única + LIMIT ≤50** → (5) include_ids manual.

**Objetivo:** o otimizador deve **enxergar todo o universo filtrado** (Gates 1–3 preservados) e ainda produzir um **portfólio final enxuto** (~20–40 posições).

### Dois gargalos reais para escalar N (independentes do cap)

1. **Interseção de datas comuns.** `load_aligned_returns` alinha por `dropna()` e exige ≥400 datas comuns entre **todos** os fundos (`MIN_COMMON_OBS`). Cada fundo adicionado corta o histórico comum de todos (limitado pelo fundo mais jovem) → adicionar centenas derruba a interseção abaixo de 400 → 422. **Não é resolvido por nada do Tier 3.**
2. **Custo do solver.** min-CVaR é um LP de ~T+N variáveis; o SOCP escala com N. N de centenas é tratável mas precisa de orçamento de tempo.

### O que o Tier 3 já entregou (e onde está)

- **Engine já usa Ledoit-Wolf shrinkage** (`sigma_ledoit_wolf`) + **PSD eigenvalue-repair** (`_validate_sigma`, T3G-3) — não usa covariância amostral crua.
- **RMT/MP denoise + LW constant-correlation** (T3F-1): portado, mas **só plugado no `correlation_regime` service** (diagnóstico), **não** no engine de alocação.
- **BL Woodbury full-Ω** (T3G-5), **SCS fallback ladder** (T3F-2): no engine/BL.

---

## 2. Decisões (do dono, no brainstorming)

1. **Escopo:** otimizar sobre **todo o universo filtrado** (remover o cap/LIMIT do Gate 4; preservar Gates 1–3).
2. **Histórico desigual:** **covariância pairwise** (cada par na interseção daquele par), em vez de interseção global via `dropna`.
3. **RMT no engine:** **sim** — plugar MP denoise + LW constant-correlation na estimação de covariância do engine para universos grandes (q=N/T alto), com Ledoit-Wolf como fallback para N pequeno.
4. **Cardinalidade:** **portfólio final enxuto** (~20–40 posições) — cap de cardinalidade efetivo.
5. **Arquitetura:** **dois estágios** (seleção por estrutura de risco → alocação convexa) — Abordagem A.
6. **Critério de seleção (Estágio 1):** **diversificação + qualidade** — clustering por correlação denoised para cobertura de risco; desempate dentro do cluster por score de qualidade (Sharpe/expense/AUM). **Sem** consumir retorno esperado (respeita o gate G5 mu-free).

---

## 3. Arquitetura — pipeline de dois estágios

```
Gates 1–3 (filtros de qualidade, SEM cap de ranking)        ← preserva o de main
        │  N candidatos (centenas)
        ▼
[Estágio 1 — SELEÇÃO]
  retornos T×N (com NaN, sem dropna global)
   → covariância PAIRWISE vetorizada (máscara de disponibilidade)
   → RMT/MP denoise + LW constant-correlation  (Tier 3)
   → PSD eigenvalue-repair                      (Tier 3 / engine)
   → clustering por correlação denoised → 1 representante por cluster
     (desempate por score de qualidade: Sharpe/expense/AUM)
        │  K ids selecionados (~30–40)
        ▼
[Estágio 2 — ALOCAÇÃO]  (engine atual, quase sem mudança estrutural)
  retornos T×K alinhados (dropna, MIN_COMMON_OBS)
   → σ robusta (RMT quando q=N/T alto, senão Ledoit-Wolf) + PSD-repair
   → min-CVaR / BL / ERC  →  pesos sobre K
```

**Princípio:** o Estágio 1 vê o universo inteiro e usa **risco** (estrutura de correlação) + **qualidade** (filtros) para escolher um conjunto enxuto, diverso e representativo. O Estágio 2 é a alocação convexa existente, agora sobre um conjunto pequeno e bem-comportado.

---

## 4. Componentes (unidades isoladas e testáveis)

### 4.1 `pairwise_covariance(R)` — novo, `app/analytics/pairwise_cov.py`
- **Faz:** covariância pairwise de uma matriz de retornos T×N **com NaN** (sem dropna global), vetorizada via máscara de disponibilidade: com `R₀ = R` (NaN→0) e `M` (máscara binária 1=presente), `n_ij = MᵀM` (overlap por par), médias pairwise `μ = (R₀ᵀM)/n_ij`, e `cov_ij = (R₀ᵀR₀)/n_ij − μ_ij·μ_jiᵀ`. Sem loop explícito por par.
- **Guarda:** pares com overlap `< MIN_PAIR_OVERLAP` (default **252 pregões**) são marcados; fundos cujo overlap mediano cai abaixo do limiar são **excluídos** do universo com aviso estruturado (fail-loud, não silencioso). Se o resultado não tiver ≥2 fundos viáveis → `ValueError` (→422).
- **Saída:** matriz N×N (cov pairwise crua) + lista de fundos excluídos/razões. A correlação/denoise/PSD-repair são aplicados a seguir (reuso do `rmt.py` e do `_validate_sigma`).
- **Interface:** pura (numpy/pandas), sem I/O. Testada em frames sintéticos com padrões de NaN conhecidos.

### 4.2 Seletor diversificação+qualidade (Estágio 1) — novo, `app/optimizer/selection.py`
- **Faz:** dado (correlação denoised N×N, scores de qualidade por fundo, K), agrupa por correlação via **clustering hierárquico aglomerativo** sobre distância `d_ij = 1 − ρ_ij` (linkage average), corta em ~K clusters, e escolhe **1 representante por cluster** maximizando o score de qualidade.
- **Score de qualidade:** combinação normalizada dos sinais que os Gates já priorizam (ex.: Sharpe_1y maior, expense_ratio menor, AUM maior) — composição explícita, **sem retorno esperado** (G5). Pesos do score: defaults documentados, ajustáveis.
- **Saída:** lista de ~K `instrument_id` selecionados + diagnóstico (cluster de cada um, score).
- **Interface:** pura. Testada em universo sintético com clusters plantados (verifica 1/cluster + melhor qualidade).

### 4.3 Seam de dados pairwise — modifica `app/optimizer/data.py`
- **Novo loader** que retorna a matriz T×N **sem** dropna global (mantém NaN) para o Estágio 1. O `load_aligned_returns` atual (dropna + MIN_COMMON_OBS) **permanece** para o Estágio 2 sobre os K.
- **`select_universe_funds`:** remover o `LIMIT max_assets` (ou torná-lo opcional); retornar **todos** os fundos que passam nos Gates 1–3, sujeito a um **teto de segurança duro** (`MAX_UNIVERSE_CANDIDATES`, default **2000**) que **falha-loud** se excedido (sinaliza usar o caminho de worker — fase 2).

### 4.4 `sigma_robust(...)` — modifica `app/optimizer/engine.py`
- **Faz:** estimador de covariância que escolhe o método pela razão `q = N/T`: quando q é alto (universo grande relativo ao histórico), usa **MP denoise + LW constant-correlation** (`rmt.py`); senão, mantém **Ledoit-Wolf** (`sigma_ledoit_wolf`). Sempre seguido de PSD eigenvalue-repair (`_validate_sigma`). **Default do limiar: `q > 0.5`** (N > T/2) ativa o caminho RMT; ajustável e validado por teste. Comportamento determinístico; fallback explícito se o denoise falhar.
- **Não muda** a interface dos `solve_*` (compatibilidade com o builder atual).

### 4.5 Orquestração do builder — modifica o service/route do builder/optimize
- **Encadeia:** Gates 1–3 (sem cap) → loader pairwise → Estágio 1 (pairwise cov → denoise → PSD-repair → seleção) → loader alinhado dos K → Estágio 2 (engine) → resultado, **mantendo** o contrato de resposta atual + adicionando diagnóstico da seleção (clusters, fundos excluídos).
- **Execução assíncrona/job** (o pipeline pode levar segundos sobre N grande). Detalhe de wiring (rota async vs job) resolvido no plano.

---

## 5. Fluxo de dados (resumo)

`universo filtrado (N)` → `retornos T×N (com NaN)` → `pairwise cov` → `denoise+PSD-repair` → `clustering+qualidade` → `K ids` → `retornos T×K (dropna)` → `engine (σ robusta + min-CVaR/BL/ERC)` → `pesos sobre K`.

---

## 6. Erros (fail-loud, contrato do projeto)

- Overlap pairwise insuficiente para um fundo → **excluído** com aviso estruturado (logging `extra=`), nunca silenciosamente.
- < 2 candidatos viáveis após Gates/exclusão → `ValueError` → 422.
- Universo filtrado excede `MAX_UNIVERSE_CANDIDATES` → `ValueError` → 422 (com mensagem orientando estreitar filtros; worker é fase 2).
- Estágio 2 reusa as guardas existentes (MIN_COMMON_OBS sobre os K).
- RMT denoise que não produz matriz reparável → fail-closed (não retorna matriz silenciosamente inválida).

---

## 7. Testes (TDD)

- **`pairwise_covariance`:** (a) bate com `np.cov` no caso sem-NaN; (b) padrões de NaN conhecidos → overlaps e médias pairwise corretos; (c) PSD após repair; (d) exclusão de fundo com overlap < limiar; (e) fail-loud com <2 viáveis.
- **Seletor:** universo sintético com K clusters plantados → escolhe 1 por cluster e o de melhor qualidade dentro de cada; estabilidade sob perturbação pequena.
- **`sigma_robust`:** q alto → caminho RMT; q baixo → Ledoit-Wolf; ambos PSD; fallback determinístico quando denoise falha.
- **Integração builder:** end-to-end sobre universo médio sintético → portfólio de ~K posições, pesos somam 1, respeita constraints; diagnóstico de seleção presente.

---

## 8. Decisões fixadas (defaults, ajustáveis)

| Parâmetro | Default | Nota |
|---|---|---|
| `K` (clusters ≈ posições finais) | **30–40** | alinhado ao `DEFAULT_UNIVERSE_ASSETS` atual |
| `MIN_PAIR_OVERLAP` | **252 pregões (~1 ano)** | overlap mínimo por par para o pairwise |
| `MAX_UNIVERSE_CANDIDATES` | **2000** | teto de segurança on-demand; acima → worker (fase 2) |
| Clustering | **hierárquico aglomerativo, distância 1−ρ, linkage average** | detalhes no plano |
| Limiar de q para RMT no engine | **q > 0.5** (N > T/2) | ativa o caminho RMT; ajustável, validado por teste |
| Execução | **assíncrona/job** | pipeline pode levar segundos sobre N grande |

---

## 9. Escopo / não-objetivos (YAGNI)

- **Fase 1 (este spec):** pipeline on-demand de dois estágios até `MAX_UNIVERSE_CANDIDATES`. Fail-loud acima do teto.
- **Fase 2 (NÃO agora):** pré-cálculo no worker (DB-first) para universo > teto; só se a demanda exigir.
- **Fora de escopo:** MIQP/cardinalidade inteira exata (Abordagem B, rejeitada por custo/escalabilidade); mudanças no contrato de resposta além do diagnóstico de seleção; UI (tarefa de frontend separada).
- **Depende de:** `feat/quant-port-tier3` mesclado/baixado (RMT, PSD-repair, LW const-corr).

---

## 10. Pré-requisito de integração

Mesclar/baixar `feat/quant-port-tier3` antes de iniciar (este trabalho importa `app/analytics/rmt.py` e o `_validate_sigma`/`sigma_ledoit_wolf` do engine do Tier 3).
