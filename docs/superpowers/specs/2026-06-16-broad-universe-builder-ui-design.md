# Broad-universe no builder UI — Design

**Data:** 2026-06-16
**Status:** Aprovado (aguardando review do spec antes do plano)

## Objetivo

Expor no builder UI o modo **broad universe** do optimizer (já implementado e mesclado no backend, `043801d`/`ed03d37`): permitir que o usuário rode o pipeline de dois estágios (seleção por estrutura de risco → alocação convexa enxuta) sobre TODO o universo filtrado (Gates 1–3), em vez do top-N ranqueado (≤50). O backend já serve os campos de request (`broad_universe`/`max_positions`/`min_pair_overlap` em `UniverseSpecIn`) e o diagnóstico de resposta (`DiagnosticsOut.selection: SelectionDiagnosticsOut | null`); o contrato TS (`api.d.ts`) já foi regenerado. Não há mudança de backend exceto um fix de mensagem trivial.

## Decisões de design (do brainstorming)

1. **Entrada do modo:** toggle DENTRO do `FundUniverseCard` ("Ranked top-N | Broad → enxuto"), coexistindo com o ranked sob o modo top-level "Fund universe". Mesmos filtros (Gates 1–3) se aplicam aos dois.
2. **`min_pair_overlap`:** oculto, fixo no default 252 (não exposto na UI).
3. **Diagnóstico de seleção:** painel completo colapsável no `ResultsPanel` (resumo + excluídos + clusters).
4. **Objetivos mu-based em broad:** desabilitados na UI (remover `bl_utility`; `max_return_cvar` já não está na lista), com reset para `min_cvar` se selecionado ao ligar broad.

## Arquitetura

Mudança puramente de frontend (React, design system próprio Investintell Cockpit; sem lib externa), mais um fix de mensagem de 1 linha no backend. Estado local via `useState` (padrão atual do builder); o novo estado mora em `UniverseDraft` e flui por `universeDraftToSpec` → request. Nenhuma mudança de contrato/regen (os campos já existem no schema gerado).

### Arquivos tocados

| Arquivo | Tipo | Responsabilidade |
|---|---|---|
| `frontend/src/components/builder/assets.ts` | Modify | `UniverseDraft` ganha `broadUniverse: boolean` + `maxPositions: number`; `defaultUniverseDraft()` os inicializa; `universeDraftToSpec` emite `broad_universe`/`max_positions` dinâmicos e omite `include_instrument_ids` em broad. |
| `frontend/src/components/builder/FundUniverseCard.tsx` | Modify | Toggle Ranked/Broad; morphing dos controles (oculta rank-by/order, slider vira "Target positions (K)" 5–50); oculta grid de preview/prune em broad; mensagem de contagem sensível ao modo. |
| `frontend/src/components/builder/BuilderView.tsx` | Modify | Gating de objetivo em broad (filtra `OBJECTIVES` p/ mu-free; reseta `bl_utility`→`min_cvar` ao ligar broad); dica explicativa. |
| `frontend/src/components/builder/SelectionDiagnostics.tsx` | Create | Painel colapsável (espelha `MuDiagnostics`) com resumo/clusters/excluídos. |
| `frontend/src/components/builder/ResultsPanel.tsx` | Modify | Renderiza `<SelectionDiagnostics>` quando `diagnostics.selection != null`, após `MuDiagnostics`. |
| `backend/app/services/portfolio_builder.py` | Modify (1 linha) | Corrigir a mensagem de cap infeasível: "lower max_positions" → "increase max_positions". |
| `frontend/src/components/builder/assets.test.ts` | Create | Unit de `universeDraftToSpec` (ambos os modos). |
| `frontend/src/components/builder/FundUniverseCard.test.tsx` | Create | Toggle + morphing dos controles. |
| `frontend/src/components/builder/BuilderView.test.tsx` | Create | Gating de objetivo. |
| `frontend/src/components/builder/SelectionDiagnostics.test.tsx` | Create | Render condicional do diagnóstico. |

## Componentes (unidades, interface, dependências)

### 1. `UniverseDraft` + `universeDraftToSpec` (`assets.ts`)

**O que faz:** modelo de estado do painel de universo + conversão para o request `BuilderUniverseSpec`.

Campos novos em `UniverseDraft`:
```ts
broadUniverse: boolean;   // default false
maxPositions: number;     // default 30; faixa UI 5–50 (cardinalidade K final)
```
`min_pair_overlap` NÃO entra no draft (constante 252).

`universeDraftToSpec(draft, includeIds?)` passa a emitir:
```ts
broad_universe: draft.broadUniverse,
max_positions: draft.broadUniverse ? draft.maxPositions : draft.maxAssets,
min_pair_overlap: 252,
// rank_by/rank_dir/max_assets continuam enviados (backend os ignora em broad).
// include_instrument_ids: SÓ quando !broadUniverse e há ≥2 ids selecionados.
...(!draft.broadUniverse && includeIds && includeIds.length >= 2
  ? { include_instrument_ids: [...includeIds] }
  : {}),
```
**Por que `max_positions: draft.maxAssets` em ranked:** o campo é required no tipo gerado e o backend o ignora fora de broad; reusar `maxAssets` mantém um valor válido (mesma faixa ge=2 le=50) sem semântica nova.

**Cap:** sem tratamento especial no frontend. A faixa K (5–50) garante `cap_default(0.25)·K ≥ 1.25 > 1` (viável e não-degenerado), então o request envia `cap` como hoje. Um cap manual baixo demais para o K resulta em 422 fail-loud (mensagem corrigida — ver backend).

### 2. `FundUniverseCard.tsx`

**O que faz:** UI de configuração do universo (filtros + ranking/seleção).

- **Toggle segmentado** "Ranked top-N | Broad → enxuto": dois `<button>` com `aria-pressed`, estilo idêntico ao mode-toggle do `BuilderView` (`bg-accent`/`bg-field`), ligado a `draft.broadUniverse` via `patch({ broadUniverse })`.
- **Filtros** (type/class/AUM/expense): visíveis em ambos os modos (Gates 1–3).
- **Modo ranked (atual):** "Rank by", "Order", slider "How many funds" (`maxAssets`, 2–50), grid de preview + prune por checkbox.
- **Modo broad:** ocultam-se "Rank by" e "Order"; o slider exibe rótulo **"Target positions (K)"**, faixa **5–50**, ligado a `maxPositions`; o **grid de preview/prune é ocultado** (seleção automática por clustering — prune manual é incompatível). A query de contagem ao vivo (`universeDraftToCountQuery`) continua.
- **Mensagem de contagem:** ranked = "top {N} de {M} fundos"; broad = "{M} fundos no universo → seleciona ~{K} posições entre clusters de risco" (avisa se M < 2).

### 3. `BuilderView.tsx` — gating de objetivo

**O que faz:** orquestra modo/objetivo/constraints e dispara o optimize.

- Computa a lista de objetivos visível: em broad, filtra `OBJECTIVES` removendo `bl_utility` (mu-based). `max_return_cvar` já não está em `OBJECTIVES` (caminho de views, incompatível com universe).
- Ao ligar broad (ou ao já estar em broad), se `objective === "bl_utility"`, reseta para `min_cvar`.
- Dica curta perto do select: "Broad é risk-structure-only (gate G5) — objetivos que usam retorno esperado ficam indisponíveis."

### 4. `SelectionDiagnostics.tsx` (novo)

**O que faz:** exibe o `SelectionDiagnosticsOut` da resposta. Interface:
```ts
function SelectionDiagnostics({ selection }: { selection: SelectionDiagnosticsOut }): JSX.Element
```
Estrutura (colapsável, espelha `MuDiagnostics` — `<section>` + botão `aria-expanded` + corpo):
- **Resumo:** "{n_candidates} candidatos → {n_selected} selecionados" + nº de clusters distintos (de `Object.values(clusters)`).
- **Clusters:** tabela `posição (label) → cluster id` (de `clusters: Record<string, number>`).
- **Excluídos:** tabela `fundo → motivo` (de `excluded: {fund, reason}[]`); se vazio, omite a tabela.

### 5. `ResultsPanel.tsx`

Após o bloco `MuDiagnostics`:
```tsx
{diagnostics.selection != null && (
  <SelectionDiagnostics selection={diagnostics.selection} />
)}
```

### 6. Backend (fix de 1 linha)

`portfolio_builder.py:431`: a mensagem de cap infeasível diz "raise the cap or lower max_positions". Como a infeasibilidade é `cap·K < 1`, a correção é **aumentar** K (mais ativos capados) ou o cap; diminuir K piora. Trocar para: "raise the cap or increase max_positions". (O backend já tem teste de schema cobrindo o caminho; ajustar o assert de mensagem se ele casar o texto antigo.)

## Fluxo de dados

1. Usuário em "Fund universe" liga o toggle Broad → `draft.broadUniverse=true`; controles fazem morph; objetivos mu-based somem.
2. Ajusta filtros + K. Contagem ao vivo mostra M candidatos.
3. Run → `universeDraftToSpec` monta o spec (`broad_universe:true`, `max_positions:K`, sem `include_instrument_ids`) → `postBuilderOptimize`.
4. Resposta: `ResultsPanel` mostra pesos/KPIs e, como `diagnostics.selection != null`, o painel `SelectionDiagnostics` (M→K, clusters, excluídos).

## Tratamento de erros

- Universo broad resolvendo a <2 fundos ou seleção <2 → backend 422 (`BuilderError`); a UI mostra o erro existente do mutation.
- Cap manual infeasível para K → 422 com mensagem corrigida.
- `min_cvar` (mu-free) é o default e sempre permitido em broad; gating impede escolher objetivos rejeitados (evita o 422).

## Testes

- **`assets.test.ts`** (unit puro, sem render): `universeDraftToSpec` em ranked (broad_universe=false, max_positions=maxAssets, include_instrument_ids quando ids) e em broad (broad_universe=true, max_positions=maxPositions, SEM include_instrument_ids).
- **`FundUniverseCard.test.tsx`:** clicar Broad oculta Rank by/Order, slider vira "Target positions (K)", grid de prune some; clicar Ranked restaura.
- **`BuilderView.test.tsx`:** em broad, `bl_utility` não aparece no select; selecionar `bl_utility` e depois ligar broad reseta para `min_cvar`.
- **`SelectionDiagnostics.test.tsx`:** com `selection` populado renderiza "M → K", clusters e excluídos; com `selection=null` não renderiza nada (via ResultsPanel ou guard).

Padrão: vitest + @testing-library/react (`// @vitest-environment jsdom`), `userEvent`, mock de `@/lib/api/client` quando necessário, asserts em `aria-pressed`/`aria-expanded`/texto.

## Fora de escopo (follow-ups, não implementar agora)

- **Degenerescência do auto-relax do cap:** quando o cap default é infeasível, o backend ergue para exatamente `1/K`, o que com K ativos força peso igual (ocorre para K≤4 mesmo sem relax: 4·0.25=1.0 é solução única). A UI evita isso via faixa K≥5. Follow-up: erguer o cap para `>1/K` ou sinalizar no diagnóstico "cap forçou peso igual".
- Expor `min_pair_overlap` como controle avançado (decidido manter oculto).
- Pré-cálculo no worker para universos >2000 (Fase 2 do design do optimizer).

## Pontos a confirmar na implementação

- Nome/forma exatos do objeto `diagnostics` e do tipo `SelectionDiagnosticsOut` no `api.d.ts` gerado (campos `n_candidates`/`n_selected`/`excluded[].{fund,reason}`/`clusters`).
- Como `ResultsPanel` recebe `diagnostics` e o padrão exato de `MuDiagnostics` (classes/estrutura) para espelhar.
- Se há teste de schema no backend casando a string "lower max_positions" (ajustar junto ao fix).
