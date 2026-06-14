# Spec — Screener unificado (base do Plano 6): do wizard ao workspace Build | Results

**Data:** 2026-06-13 · **Status:** aprovado (brainstorming com companion visual)
**Continua:** Plano 1 (`highcharts-grid-foundation-screener` — Grid Pro já no `ResultsTab`)
**Base para:** Plano 6 (implementação, `docs/superpowers/plans/`)
**Referência de UX:** Barchart Stocks Screener (`viewName=filter_view`) — HTML real analisado.

## Objetivo

Substituir o **wizard sequencial de 3 abas** (`Select metrics` → `Build` → `Results`) por um
**workspace unificado de 2 modos** (`Build | Results`) sob um **header persistente**, resolvendo
os quatro problemas levantados em `frontend/src/components/screener/`:

1. **Empty state ambíguo** → primeiro uso passa a ser *inline coaching*: o próprio Build já
   aberto e vazio, com dicas que comunicam o fluxo ("Name → Add metrics → See results").
2. **Seleção de métricas pouco densa** (lista vertical de blocos, 1 por linha) → **typeahead
   "Find a metric…" + popover "Browse by category"** (catálogo inteiro: 33 métricas / 6
   categorias), no padrão "Add a Filter" do Barchart, adaptado à nossa escala.
3. **Contexto fragmentado** (Select Metrics e Build em abas distintas) → **fundidos** num único
   painel `Build`: nomear, adicionar indicadores e ajustar parâmetros sem trocar de aba. A aba
   `Results` (Grid Pro) permanece dedicada à visualização.
4. **Navegação que perde contexto** → nome do screen, contagem ao vivo e ações globais ficam
   **sempre visíveis** num header sticky acima das abas.

## Decisões aprovadas

| # | Decisão | Escolha |
|---|---|---|
| 1 | **Persistência** | **Auto-save ao vivo** — toggle/commit de bound (Enter/blur/preset) persiste na hora; contagem de matches ao vivo; Results sempre refletem o estado salvo. Mantém o `resultsQuery` sem reescrita de contrato. |
| 2 | **Escopo "100% Highcharts Grid Pro"** | **Results + a lista de filtros como Grid Pro editável** (Min/Max inline, reorder de linhas, seleção→delete em massa, sparkline de distribuição por linha). O seletor de métricas (typeahead + popover) permanece UI custom. Grid Pro é a **única** lib de grid do app. |
| 3 | **Build × Results** | **Abas sob header persistente.** Results ganha largura total para o grid (colunas dinâmicas). |
| 4 | **Layout do Build** | **Grid full-width + painel de distribuição inferior fixo** (a linha selecionada mostra histograma + presets + bounds embaixo; o grid não "pula"). **Largura controlada/centralizada**: histograma em bloco `max-width ~560px`, container do workspace centralizado no limite atual (`max-w-[1360px]`). |
| 5 | **Empty state** | **Inline coaching** — sem tela intermediária; o Build já aberto, vazio, com dicas + os 3 micro-passos. |
| 6 | **Add-a-metric** | **Typeahead "Find a metric…" + popover "Browse by category"** (categorias/sub-categorias do catálogo; checkbox = adiciona, auto-save; já-adicionadas marcadas). |

### Padrões do Barchart incorporados (e o que fica de fora)

- **Incorporado:** header/abas persistentes (`Set Filters | Results` → `Build | Results`); barra
  "Add a Filter" → "Add a metric"; filtros como linhas com controles e **delete em massa** por
  checkbox; **reorder = ordem das colunas** no resultado; ações globais `Reset`, `Export`.
- **Fora de escopo (fase 2):** *Views* predefinidas (Main/Technical/Performance); *Filter
  display* (escolher colunas básicas) — nossas colunas já são `ticker + name + métricas`;
  templates/"Barchart Screeners"; share link; watchlist.

## Mockup estrutural

**Build (preenchido) — conteúdo centralizado (`max-w-[1360px] mx-auto`):**

```
┌─ HEADER (sticky) ───────────────────────────────────────────────────────────┐
│ ⌂ Tech Growth ▾      [ 142 matches ]   Saved ✓        [ Reset ]  [ ⬇ CSV ]   │
│ ┌────────┬─────────┐                                                          │
│ │ Build  │ Results │   (abas; Build ativo)                                    │
│ └────────┴─────────┘                                                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ Add metric  [ 🔍 Find a metric…  (P/E, ROE, Beta…) ]   [ Browse by category ▾]│
├──────────────────────────────────────────────────────────────────────────────┤
│  ☐  ☰  Metric          Min        Max        Dist          ×    ← Grid Pro     │
│  ☐  ☰  P/E ratio ●     —          [25.0]     ▁▃▅▂          ×    (editável)     │
│  ☑  ☰  Market cap      [1.0B]     —          ▂▅▇▃          ×                   │
│  ☑  ☰  ROE             [15%]      —          ▃▅▇▂          ×                   │
│  [ Delete 2 selected ]    · ☰ arraste p/ reordenar = ordem das colunas        │
├──────────────────────────────────────────────────────────────────────────────┤
│ Distribution — P/E ratio                              [ 142 matches ]          │
│ ┌─ max-w ~560px ───────────────────┐                                          │
│ │ [████ histograma ████]           │  presets:[10-15•][15-25][>25][Custom]    │
│ │                                  │  Min[ — ]  Max[ 25.0 ]   ← respiro →     │
│ └──────────────────────────────────┘                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Empty state (inline coaching):**

```
│ ⌂ Untitled screen ✎  ← Name your screen            Saved —                    │
│ [ Build ] [ Results ]                                                          │
│ Add metric  [ 🔍 Find a metric… ]  [ Browse ▾ ]   ← Add your first metric      │
│ ─────────────────────────────────────────────────────────────────────────────│
│            No metrics yet — add one above to start building your screen.       │
│            ① Name   →   ② Add metrics & set ranges   →   ③ See results          │
```

**Browse by category (popover — catálogo real):**

```
┌─ Browse metrics ──────────────────────────┐
│ [ 🔍 filter… ]                  33 metrics │
│ ▾ Price                               3/9  │
│   ☑ 1-Year Return        Ret 1Y            │
│   ☐ Last Close Price     Price             │
│   ☑ Avg Daily Volume     Avg Vol           │
│ ▾ Technicals: Statistics              0/13 │
│   ☐ 1-Year Beta vs SPY   Beta 1Y           │
│ ▸ Fundamentals: Valuation             2/3  │
│ ▸ Efficiency                          1/4  │
│ ▸ Indicator                           0/3  │
│ ▸ Growth                              0/1  │
└────────────────────────────────────────────┘
```

## Mapeamento de refatoração (atual → destino)

| Arquivo atual | Destino |
|---|---|
| `ScreenerView.tsx` (orquestrador + `WizardTabs` de 3 passos + `EmptyState`) | **Refatorado** em orquestrador do workspace: `ScreenerHeader` (sticky) + 2 abas (`Build`\|`Results`) via `?tab=build\|results`. Remove `WizardTabs`/`ScreenWizardBody`. Mantém `screensQuery`, seleção, `screenQuery`, `catalogQuery`. |
| `SelectMetricsTab.tsx` **+** `BuildTab.tsx` | **Fundidos** em `BuildPanel.tsx`. A seleção (toggle PUT null/null) vira a `AddMetricBar` + `MetricBrowserPopover`. O ajuste de bounds (os `FilterCard`) vira **edição inline no `FiltersGrid`** + o `DistributionPanel` inferior para a linha ativa. |
| `ScreenStrip.tsx` (chips + `CreateScreenForm`) | Vira o **menu do nome no header** (`ScreenSwitcher`: trocar/renomear/duplicar/novo/excluir). A criação migra para o empty state inline (nomear) e para "New screen" no menu. |
| `ResultsTab.tsx` | **Mantido** (já Grid Pro server-side). O cabeçalho local (nome/contagem/export) sobe para `ScreenerHeader`; busca e paginação permanecem na aba. |
| `gridOptions.ts` (`screenResultsToGridOptions`) | **Reutilizado** p/ Results; ganha um irmão `filtersGridOptions.ts` (`screenFiltersToGridOptions`) para o grid editável. |
| `DataGrid.tsx` | **Reutilizado** nos dois grids (Results e Filtros). |
| `shared.tsx` | Mantido (classes Carbon/Graphite, `retryPolicy`, `ErrorPanel`, `applyFilterResponse`, `isSnapshotMissing`). |

## Árvore de componentes (novos)

```
ScreenerView
├─ ScreenerHeader (sticky)
│   ├─ ScreenSwitcher  ⌂ nome ▾  (switch/rename/duplicate/new/delete) ← funde ScreenStrip
│   ├─ MatchCount      [N matches]  (aria-live, do headline_count)
│   ├─ SaveStatus      Saved ✓ / Saving… / Retry   (indicador de auto-save)
│   └─ GlobalActions   Reset · ⬇ Export CSV
├─ Tabs (Build | Results)
├─ BuildPanel            ← funde SelectMetricsTab + BuildTab
│   ├─ AddMetricBar      (typeahead + botão Browse)
│   │   └─ MetricBrowserPopover  (catálogo agrupado, checkbox = add)
│   ├─ FiltersGrid       (DataGrid + filtersGridOptions; editável)
│   └─ DistributionPanel (EChart histograma + presets + bounds da linha ativa)
└─ ResultsTab            ← praticamente intacto
```

## Grid de filtros editável (Grid Pro)

Novo adapter **puro** `src/lib/grid/filtersGridOptions.ts` (espelha `gridOptions.ts`, unit-tested),
consumido por `BuildPanel` via o `DataGrid` existente. Colunas:

| Coluna | Conteúdo | Interação |
|---|---|---|
| select | checkbox | seleção → "Delete N selected" (delete em massa) |
| `☰` handle | drag | **reorder** → grava `position` (ver Backend) |
| Metric | nome (+ abreviação) | clicar a linha = seleciona p/ o `DistributionPanel` |
| Min | valor editável | cell-edit Pro → `putScreenFilter` |
| Max | valor editável | cell-edit Pro → `putScreenFilter` |
| Dist | **sparkline** SVG (mini-histograma) | renderer custom, dados de `screen-build` |
| `×` | remover | `deleteScreenFilter` |

- **Edição de bounds:** o commit de célula chama `putScreenFilter(screenId, code, {min_value, max_value})`.
  A **regra percent** do `BuildTab` é preservada e centralizada num helper
  (`toDisplayText`/`parseBound`): métricas `data_type === "percent"` exibem/entram 0–100 e enviam
  fração; demais passam raw. `""` = unbounded (null); inválido = sem commit (`aria-invalid`).
- **Sparkline:** renderer gera barras a partir da `Distribution` do filtro, com a banda
  selecionada em `--color-accent`. Reusa o cache `["screen-build", screenId, code]` (ver fluxo).
- **Reorder / Seleção:** recursos Pro (`rows.selection`, row drag). O reorder grava a nova ordem
  de `position`, que é exatamente a ordem das colunas em `Results` (`result_columns` =
  `ticker + name + métricas em position order`).

## Header persistente e semântica de auto-save

Como a persistência é **auto-save**, **não há botão "Salvar mudanças"**. O rótulo "Save" do
protótipo é substituído por um **indicador de status** (`Saved ✓` / `Saving…` / `Retry` em erro,
derivado de `isPending`/`error` das mutations). Ações reais:

- **Nome ▾ (`ScreenSwitcher`):** trocar de screen, **Rename** (`patchScreen`), **Duplicate**,
  **New screen** (`createScreen`), **Delete** (`deleteScreen`, com confirmação — destrutivo).
- **Reset:** limpa todos os filtros do screen (sequência de `deleteScreenFilter`; confirmação).
- **⬇ Export CSV:** `fetchScreenResultsCsv` com o sort/search correntes (lógica migrada do `ResultsTab`).

## Empty state (lazy creation)

Sem screens, renderiza o `BuildPanel` inline com header em modo "Untitled" e a `AddMetricBar`.
O screen é criado no **primeiro gesto** (lazy), evitando órfãos: nomear → `createScreen(name)`;
ou adicionar a 1ª métrica → `createScreen("Untitled screen")` + `putScreenFilter`. Antes disso,
o `Export`/`Reset` ficam desabilitados e a dica "Name your screen" tem destaque.

## Transição do `resultsQuery` (TanStack Query)

**Contrato preservado — nenhuma query muda de chave/assinatura.** O que muda é apenas *de onde*
partem as invalidações.

- `["screen-results", screenId, sort, dir, search, page]` — **inalterado**. `ResultsTab` segue
  com `keepPreviousData`, busca debounced e paginação. Export usa as mesmas opções.
- `applyFilterResponse(qc, screenId, resp)` — **inalterado**: toda edição no `FiltersGrid`
  (`putScreenFilter`/`deleteScreenFilter`) já injeta `resp.screen` em `["screen", id]`, invalida
  `["screens"]` e `["screen-results", screenId]`. Ao voltar à aba `Results`, refetch automático
  (`staleTime 30s`). A origem das mutations migra dos `FilterCard` para as células do grid — a
  fiação de cache é a mesma.
- **Contagem ao vivo** (`MatchCount`): vem do `headline_count` das respostas PUT/DELETE (e do
  build no open). Sai do corpo do `BuildTab` para o `ScreenerHeader`.
- **Distribuições:** `["screen-build", screenId, code]` por filtro — **mantido**. Hoje cada
  `FilterCard` já dispara essa query; no novo, ela alimenta tanto o **sparkline** da linha quanto
  o `DistributionPanel` da linha ativa (mesmo dado, cache compartilhado). *Recomendado* um
  endpoint em lote (ver Backend) para evitar N requisições quando há muitos filtros.
- **Adição de métrica** (popover/typeahead): mesma semântica do toggle atual —
  `putScreenFilter(code, {min:null,max:null})` ("selecionada, sem corte") e prime do
  `["screen-build", …]` no `onSuccess` (como hoje em `SelectMetricsTab`).

## Comportamentos de UI (Tailwind 4 + tokens Graphite)

- **Header sticky:** `sticky top-0 z-10 bg-surface-1 border-b border-border`; container
  `mx-auto max-w-[1360px]`. Reage a `data-density`/`data-theme`/`data-accent` (tokens já globais).
- **Abas:** 2 botões `role="tab"`, ativo em `bg-surface-2 text-accent` borda `border-accent`;
  estado em `?tab=`.
- **AddMetricBar:** `INPUT_CLASS` (typeahead) + botão `BUTTON_CLASS` "Browse". Typeahead filtra
  por `name`/`abbreviation`/`code` (lógica de busca reaproveitada do `SelectMetricsTab`).
- **MetricBrowserPopover:** `bg-surface-2 border border-border-strong`; cabeçalhos de categoria
  `ix-label`; sub-categoria como sub-rótulo; linha = checkbox + nome + abreviação; contador
  `selecionadas/total`. Flat (radius 0), sem sombra pesada (hairline forte).
- **FiltersGrid:** tema `hcg-theme-graphite`; `ix-grid-cell-num` (Min/Max/Dist, tabular, à
  direita); inputs de célula herdam `--hcg-input-*`. Nova classe `ix-grid-spark` (barras
  `--color-chart-bar`/`--color-accent`). Linha ativa em `--color-accent-wash`.
- **DistributionPanel:** `border-t border-border bg-surface-2 ix-pad`; histograma `EChart` em
  contêiner `max-w-[560px]` à esquerda; presets como chips (`accent-wash`/`accent` quando ativos);
  Min/Max em `INPUT_CLASS`; resto da largura é respiro (gráfico não estica).
- **Empty state:** dicas em `text-accent border border-dashed border-accent bg-accent-wash`;
  micro-passos em `text-text-muted`.
- **Acessibilidade:** `role="tablist"`/`tab`, `aria-live="polite"` na contagem e no SaveStatus,
  `aria-pressed` nos chips, foco visível (accent), `aria-invalid` nos bounds.

## Backend (investintell-light, FastAPI)

Núcleo já suporta o redesign (auto-save, contagem, distribuição, CSV). Duas adições:

1. **Reorder de filtros** *(necessário para o `☰`)* — hoje `upsert_filter` define `position` no
   append e não há rota de reordenação. Adicionar `PATCH /screens/{id}/filters/reorder` recebendo
   a lista de `metric_code` na nova ordem (revalida contra o screen; reescreve `position`).
   Retorna `ScreenOut`. *Alternativa:* adiar o reorder para fase 2 (entregar o grid editável sem
   drag).
2. **Build em lote** *(recomendado p/ os sparklines)* — `GET /screens/{id}/build` devolvendo
   `{metric_code: BuildResponse}` de todos os filtros numa requisição. *Alternativa:* reusar
   `GET /screens/{id}/build/{code}` por filtro (como hoje), aceitando N requisições.

Nenhuma mudança no contrato de `results`/`results.csv`. Regenerar tipos
(`openapi-typescript`) após as adições.

## Estados e erros

- **Catálogo vazio** → `AddMetricBar` desabilitada + nota. **Snapshot ausente (422)** →
  `isSnapshotMissing` + `NO_DATA_NOTE` (sparkline/painel mostram "sem dados"; o grid ainda lista).
- **Build sem filtros** → empty state inline (mesmo componente do primeiro uso).
- **Results sem matches** → mensagem atual ("0 rows").
- **Erro de auto-save** (PUT/DELETE/reorder) → `SaveStatus` vira `Retry` + alerta inline na linha;
  política `retryPolicy` (não repete 4xx).
- Skeletons no padrão atual para header, grid e painel.

## Testes

- **Unit (vitest):** `filtersGridOptions` (colunas, ordem por `position`, sparkline, formatter
  percent); helper `parseBound/toDisplayText`. Manter os testes de `gridOptions`/`ResultsTab`.
- **Component:** `BuildPanel` (add via popover/typeahead, edição de bound, remove, delete em
  massa, troca de linha ativa), `ScreenerHeader` (rename/new/delete/reset, indicador de save).
- **Backend (pytest):** `reorder` (ordem ⇒ `position` ⇒ ordem de colunas em `results`); build em
  lote (se adotado). Padrão dos testes de rota existentes.
- `typecheck` + `lint`; smoke Playwright nas abas Build e Results.

## Fora de escopo (fase 2)

Views predefinidas (Main/Technical/Performance); *Filter display* de colunas básicas; templates
("Barchart Screeners"); share/watchlist; dual-thumb range slider (já era polish de F7);
re-sort/refetch ao vivo do grid de Results enquanto edita filtros (hoje: invalida + refetch ao
abrir a aba).
