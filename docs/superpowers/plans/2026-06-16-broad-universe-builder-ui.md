# Broad-universe no builder UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor no builder UI o modo broad-universe do optimizer (toggle no Fund Universe card, gating de objetivo, painel de diagnóstico de seleção), sem mudança de contrato (o backend já serve tudo).

**Architecture:** Mudança de frontend (React + design system próprio; estado local em `UniverseDraft` fluindo por `universeDraftToSpec`) mais um fix de mensagem de 1 linha no backend. A lógica testável é isolada em funções puras de `assets.ts`; componentes apresentacionais (`SelectionDiagnostics`) e morphing de controles (`FundUniverseCard`) são testados via @testing-library; o wiring fino em `BuilderView` consome as funções puras já testadas.

**Tech Stack:** TypeScript, React 19, @tanstack/react-query, vitest + @testing-library/react (jsdom, jest-dom global em `frontend/vitest.setup.ts`), Tailwind (design system Investintell Cockpit). Backend: Python 3.13/pydantic.

**Spec:** `docs/superpowers/specs/2026-06-16-broad-universe-builder-ui-design.md`.

---

## Convenções (LER ANTES DE CADA TASK)

- **Working dir:** `E:\investintell-light`. Frontend em `frontend/`, backend em `backend/`.
- **Frontend usa pnpm.** Type-check: `cd frontend && pnpm run typecheck`. Testes: `cd frontend && pnpm vitest run <path>` (ou `pnpm exec vitest run <path>`).
- **Backend:** `cd backend && python -m pytest <path> -v`; lint `python -m ruff check <files>` (line-length=100).
- **Padrão de teste frontend:** primeira linha `// @vitest-environment jsdom`; `vi.mock("@/lib/api/client", ...)` para a rede; mockar componentes-folha pesados; `userEvent.setup()`; asserts em `aria-pressed`/`aria-expanded`/texto; `afterEach(cleanup)`. jest-dom (`toBeInTheDocument`) já está global.
- **TDD:** escreva o teste falhando primeiro, rode p/ confirmar a falha, implemente, rode p/ verde, commit.
- **Trailer de commit:**
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- **Pré-existente (NÃO consertar):** `pnpm run typecheck` já tem 6 erros pré-existentes não relacionados — 2 em `BuilderView.tsx` (`turnover_lambda`) e 4 em `rebalance.test.ts` (`status`). Eles são da `main` antes deste trabalho; ignore-os. O critério é: **nenhum erro NOVO** nos arquivos tocados.

---

## File structure

| Arquivo | Tipo | Responsabilidade |
|---|---|---|
| `frontend/src/components/builder/assets.ts` | Modify | `UniverseDraft` ganha `broadUniverse`/`maxPositions`; `universeDraftToSpec` emite-os dinâmicos e omite `include_instrument_ids` em broad; funções puras `objectivesForBroad`/`resolveObjectiveForBroad`. |
| `frontend/src/components/builder/assets.test.ts` | Create | Unit das funções puras de `assets.ts` (T1 e T3). |
| `frontend/src/components/builder/FundUniverseCard.tsx` | Modify | Toggle Ranked/Broad, morphing dos controles, mensagem de contagem, oculta preview/prune em broad. |
| `frontend/src/components/builder/FundUniverseCard.test.tsx` | Create | Toggle + morphing. |
| `frontend/src/components/builder/BuilderView.tsx` | Modify | Wiring do gating de objetivo (consome as funções puras). |
| `frontend/src/components/builder/SelectionDiagnostics.tsx` | Create | Painel colapsável do `SelectionDiagnosticsOut`. |
| `frontend/src/components/builder/SelectionDiagnostics.test.tsx` | Create | Render condicional/expansão. |
| `frontend/src/components/builder/ResultsPanel.tsx` | Modify | Renderiza `<SelectionDiagnostics>` quando `diagnostics.selection != null`. |
| `backend/app/services/portfolio_builder.py` | Modify (1 linha) | Mensagem de cap infeasível: "lower" → "increase" max_positions. |
| `backend/tests/test_builder_broad_universe.py` | Modify | Assert da nova mensagem. |

---

## Task 1: Data layer — `UniverseDraft` + `universeDraftToSpec`

**Files:**
- Modify: `frontend/src/components/builder/assets.ts` (lines 71–83 interface, 94–104 default, 131–150 spec)
- Create: `frontend/src/components/builder/assets.test.ts`

- [ ] **Step 1: Write the failing test.** Create `frontend/src/components/builder/assets.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { defaultUniverseDraft, universeDraftToSpec } from "./assets";

describe("universeDraftToSpec", () => {
  it("ranked mode: broad_universe false, max_positions mirrors max_assets, keeps include ids", () => {
    const draft = { ...defaultUniverseDraft(), maxAssets: 20 };
    const spec = universeDraftToSpec(draft, ["a", "b"]);
    expect(spec.broad_universe).toBe(false);
    expect(spec.max_assets).toBe(20);
    expect(spec.max_positions).toBe(20);
    expect(spec.min_pair_overlap).toBe(252);
    expect(spec.include_instrument_ids).toEqual(["a", "b"]);
  });

  it("broad mode: broad_universe true, max_positions from maxPositions, omits include ids", () => {
    const draft = {
      ...defaultUniverseDraft(),
      broadUniverse: true,
      maxPositions: 25,
      maxAssets: 40,
    };
    const spec = universeDraftToSpec(draft, ["a", "b"]);
    expect(spec.broad_universe).toBe(true);
    expect(spec.max_positions).toBe(25);
    expect("include_instrument_ids" in spec).toBe(false);
  });

  it("default draft is ranked with maxPositions 30", () => {
    const draft = defaultUniverseDraft();
    expect(draft.broadUniverse).toBe(false);
    expect(draft.maxPositions).toBe(30);
  });
});
```

- [ ] **Step 2: Run, expect FAIL.** Run: `cd frontend && pnpm vitest run src/components/builder/assets.test.ts`
  Expected: FAIL — `draft.broadUniverse` is `undefined` / type errors (fields don't exist yet).

- [ ] **Step 3: Implement.** In `frontend/src/components/builder/assets.ts`:

(a) In the `UniverseDraft` interface, replace:
```ts
  rankBy: UniverseRankBy;
  rankDir: "asc" | "desc";
  /** How many top-ranked candidates the optimizer runs over (2–50). */
  maxAssets: number;
}
```
with:
```ts
  rankBy: UniverseRankBy;
  rankDir: "asc" | "desc";
  /** How many top-ranked candidates the optimizer runs over (2–50). */
  maxAssets: number;
  /** Broad-universe mode: optimize the FULL filtered universe (Gates 1–3) via
   * the two-stage pipeline, returning a lean K-position portfolio. */
  broadUniverse: boolean;
  /** Target portfolio cardinality K in broad mode (5–50). Ignored when ranked. */
  maxPositions: number;
}
```

(b) In `defaultUniverseDraft()`, replace:
```ts
    rankBy: "aum_usd",
    rankDir: "desc",
    maxAssets: 30,
  };
```
with:
```ts
    rankBy: "aum_usd",
    rankDir: "desc",
    maxAssets: 30,
    broadUniverse: false,
    maxPositions: 30,
  };
```

(c) Replace the whole `universeDraftToSpec` body (lines 135–149) with:
```ts
  return {
    ...universeFilters(draft),
    rank_by: draft.rankBy,
    rank_dir: draft.rankDir,
    max_assets: draft.maxAssets,
    broad_universe: draft.broadUniverse,
    // In broad mode K = maxPositions; in ranked mode this field is ignored by
    // the backend, so mirror max_assets to keep a valid (ge=2, le=50) value.
    max_positions: draft.broadUniverse ? draft.maxPositions : draft.maxAssets,
    min_pair_overlap: 252,
    // Manual prune (include_instrument_ids) is a ranked-mode concept; broad mode
    // selects representatives automatically, so never pin a list there.
    ...(!draft.broadUniverse && includeIds && includeIds.length >= 2
      ? { include_instrument_ids: [...includeIds] }
      : {}),
  };
```

- [ ] **Step 4: Run, expect PASS.** Run: `cd frontend && pnpm vitest run src/components/builder/assets.test.ts`
  Expected: 3 passed.

- [ ] **Step 5: Commit.**
```bash
git add frontend/src/components/builder/assets.ts frontend/src/components/builder/assets.test.ts
git commit -m "feat(builder): broad_universe fields in UniverseDraft + spec mapping (T1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `FundUniverseCard` — toggle + control morphing

**Files:**
- Modify: `frontend/src/components/builder/FundUniverseCard.tsx`
- Create: `frontend/src/components/builder/FundUniverseCard.test.tsx`

- [ ] **Step 1: Write the failing test.** Create `frontend/src/components/builder/FundUniverseCard.test.tsx`:

```tsx
// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FundUniverseCard } from "./FundUniverseCard";
import { defaultUniverseDraft, type UniverseDraft } from "./assets";

vi.mock("@/lib/api/client", () => ({
  fetchFunds: vi.fn(async () => ({ total: 100, items: [] })),
}));
vi.mock("@/components/ui/DataGrid", () => ({
  DataGrid: () => <div data-testid="datagrid" />,
}));
vi.mock("@/lib/grid/universeGridOptions", () => ({
  universePreviewToGridOptions: () => ({}),
}));

function Harness() {
  const [draft, setDraft] = useState<UniverseDraft>(defaultUniverseDraft());
  return (
    <QueryClientProvider client={new QueryClient()}>
      <FundUniverseCard
        draft={draft}
        setDraft={setDraft}
        onCount={() => {}}
        onSelectionChange={() => {}}
      />
    </QueryClientProvider>
  );
}

afterEach(cleanup);

describe("FundUniverseCard broad toggle", () => {
  it("ranked mode shows Rank by + preview; broad hides them and shows Target positions", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    // Ranked (default): rank control + preview grid present.
    expect(screen.getByLabelText("Rank funds by")).toBeInTheDocument();
    expect(screen.queryByText(/Target positions/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /broad/i }));

    // Broad: rank control gone, K slider present, preview grid gone.
    expect(screen.queryByLabelText("Rank funds by")).not.toBeInTheDocument();
    expect(screen.getByText(/Target positions/i)).toBeInTheDocument();
    expect(screen.queryByTestId("datagrid")).not.toBeInTheDocument();

    // Back to ranked restores the rank control.
    await user.click(screen.getByRole("button", { name: /ranked/i }));
    expect(screen.getByLabelText("Rank funds by")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL.** Run: `cd frontend && pnpm vitest run src/components/builder/FundUniverseCard.test.tsx`
  Expected: FAIL — no "broad" button exists yet.

- [ ] **Step 3: Implement.** In `frontend/src/components/builder/FundUniverseCard.tsx`:

(a) Disable the preview query in broad mode. Replace:
```ts
    enabled: effectiveN >= 2,
```
with:
```ts
    enabled: !draft.broadUniverse && effectiveN >= 2,
```

(b) Insert the mode toggle between the filters block and the rank block. After the filters `</div>` (the one closing the block that starts `<div className="flex flex-wrap items-end gap-x-4 gap-y-3">`), and BEFORE `<div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-3">`, insert:
```tsx
      <div className="mt-3 flex items-stretch border border-border-strong w-fit">
        {[
          { broad: false, label: "Ranked top-N" },
          { broad: true, label: "Broad → lean" },
        ].map((opt) => (
          <button
            key={String(opt.broad)}
            type="button"
            onClick={() => patch({ broadUniverse: opt.broad })}
            aria-pressed={draft.broadUniverse === opt.broad}
            className={`flex h-[34px] items-center px-3.5 text-[12.5px] transition-colors ${
              draft.broadUniverse === opt.broad
                ? "bg-accent font-bold text-on-accent"
                : "bg-field font-medium text-text-secondary hover:bg-layer-hover"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
```

(c) Replace the entire rank block (the `<div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-3">` that contains "Rank by", "Order", and the "How many funds" slider — lines 164–207) with:
```tsx
      <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-3">
        {!draft.broadUniverse && (
          <>
            <label className="flex min-w-[170px] flex-col gap-1">
              <span className={FIELD_LABEL_CLASS}>Rank by</span>
              <select
                value={draft.rankBy}
                onChange={(e) => patch({ rankBy: e.target.value as UniverseRankBy })}
                aria-label="Rank funds by"
                className={INPUT_CLASS}
              >
                {(Object.keys(RANK_BY_LABELS) as UniverseRankBy[]).map((k) => (
                  <option key={k} value={k}>
                    {RANK_BY_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
            <Select
              label="Order"
              value={draft.rankDir}
              onChange={(v) => patch({ rankDir: v as "asc" | "desc" })}
              options={[
                { value: "desc", label: "Best first (high→low)" },
                { value: "asc", label: "Low→high" },
              ]}
            />
          </>
        )}
        {draft.broadUniverse ? (
          <label className="flex w-[200px] flex-col gap-1">
            <span className={FIELD_LABEL_CLASS}>
              Target positions (K){" "}
              <span className="tabular-nums normal-case text-text-secondary">
                {draft.maxPositions}
              </span>
            </span>
            <input
              type="range"
              min={5}
              max={50}
              step={1}
              value={draft.maxPositions}
              onChange={(e) => patch({ maxPositions: Number(e.target.value) })}
              aria-label="Target number of positions (5 to 50)"
              className="h-[34px] accent-[var(--color-accent)]"
            />
          </label>
        ) : (
          <label className="flex w-[200px] flex-col gap-1">
            <span className={FIELD_LABEL_CLASS}>
              How many funds{" "}
              <span className="tabular-nums normal-case text-text-secondary">
                {draft.maxAssets}
              </span>
            </span>
            <input
              type="range"
              min={2}
              max={50}
              step={1}
              value={draft.maxAssets}
              onChange={(e) => patch({ maxAssets: Number(e.target.value) })}
              aria-label="Number of funds to optimize (2 to 50)"
              className="h-[34px] accent-[var(--color-accent)]"
            />
          </label>
        )}
      </div>
```

(d) Add a broad branch to the count message. In the `<p className="ix-fs mb-0 mt-3 ...">` block, replace:
```tsx
        ) : (
          <>
            ≈ <span className="font-bold tabular-nums">{formatNumber(total, 0)}</span>{" "}
            funds match · optimizing the top{" "}
            <span className="font-bold tabular-nums">{effectiveN}</span> by{" "}
            {RANK_BY_LABELS[draft.rankBy]}. Funds without enough overlapping NAV
            history are skipped automatically.
          </>
        )}
```
with:
```tsx
        ) : draft.broadUniverse ? (
          <>
            ≈ <span className="font-bold tabular-nums">{formatNumber(total, 0)}</span>{" "}
            funds in the universe → selecting ≈{" "}
            <span className="font-bold tabular-nums">{draft.maxPositions}</span>{" "}
            positions across risk clusters. Funds without enough overlapping NAV
            history are excluded automatically.
          </>
        ) : (
          <>
            ≈ <span className="font-bold tabular-nums">{formatNumber(total, 0)}</span>{" "}
            funds match · optimizing the top{" "}
            <span className="font-bold tabular-nums">{effectiveN}</span> by{" "}
            {RANK_BY_LABELS[draft.rankBy]}. Funds without enough overlapping NAV
            history are skipped automatically.
          </>
        )}
```

(e) Hide the preview grid in broad mode. Replace:
```tsx
      {effectiveN >= 2 && (
        <div className="mt-3">
```
with:
```tsx
      {!draft.broadUniverse && effectiveN >= 2 && (
        <div className="mt-3">
```

- [ ] **Step 4: Run, expect PASS.** Run: `cd frontend && pnpm vitest run src/components/builder/FundUniverseCard.test.tsx`
  Expected: 1 passed.

- [ ] **Step 5: Commit.**
```bash
git add frontend/src/components/builder/FundUniverseCard.tsx frontend/src/components/builder/FundUniverseCard.test.tsx
git commit -m "feat(builder): broad/ranked toggle + control morphing in FundUniverseCard (T2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Objective gating (pure helpers + BuilderView wiring)

**Files:**
- Modify: `frontend/src/components/builder/assets.ts` (add two pure helpers after `OBJECTIVES`)
- Modify: `frontend/src/components/builder/assets.test.ts` (append tests)
- Modify: `frontend/src/components/builder/BuilderView.tsx`

- [ ] **Step 1: Write the failing test.** Append to `frontend/src/components/builder/assets.test.ts`:

```ts
import { objectivesForBroad, resolveObjectiveForBroad } from "./assets";

describe("objective gating for broad mode", () => {
  it("ranked mode keeps every objective including bl_utility", () => {
    const values = objectivesForBroad(false).map((o) => o.value);
    expect(values).toContain("bl_utility");
    expect(values).toContain("min_cvar");
  });

  it("broad mode drops the mu-based bl_utility objective", () => {
    const values = objectivesForBroad(true).map((o) => o.value);
    expect(values).not.toContain("bl_utility");
    expect(values).toContain("min_cvar");
  });

  it("resolveObjectiveForBroad falls bl_utility back to min_cvar only in broad mode", () => {
    expect(resolveObjectiveForBroad("bl_utility", true)).toBe("min_cvar");
    expect(resolveObjectiveForBroad("bl_utility", false)).toBe("bl_utility");
    expect(resolveObjectiveForBroad("min_vol", true)).toBe("min_vol");
  });
});
```

- [ ] **Step 2: Run, expect FAIL.** Run: `cd frontend && pnpm vitest run src/components/builder/assets.test.ts`
  Expected: FAIL — `objectivesForBroad` / `resolveObjectiveForBroad` not exported.

- [ ] **Step 3: Implement.** In `frontend/src/components/builder/assets.ts`, append after the `OBJECTIVES` array (after its closing `];`):

```ts
/** Objectives selectable in the current mode. Broad-universe mode is
 * risk-structure-only (gate G5), so the backend rejects mu-based objectives
 * (bl_utility / max_return_cvar) — hide bl_utility here (max_return_cvar is not
 * in OBJECTIVES; it is reached only via the views path). */
export function objectivesForBroad(broad: boolean): typeof OBJECTIVES {
  return broad ? OBJECTIVES.filter((o) => o.value !== "bl_utility") : OBJECTIVES;
}

/** Fall a now-unavailable objective back to the mu-free default. In broad mode
 * bl_utility becomes min_cvar; everything else (and all of ranked mode) is
 * left untouched. */
export function resolveObjectiveForBroad(
  objective: BuilderObjective,
  broad: boolean,
): BuilderObjective {
  return broad && objective === "bl_utility" ? "min_cvar" : objective;
}
```

- [ ] **Step 4: Run, expect PASS.** Run: `cd frontend && pnpm vitest run src/components/builder/assets.test.ts`
  Expected: 6 passed (3 from T1 + 3 new).

- [ ] **Step 5: Wire into BuilderView.** In `frontend/src/components/builder/BuilderView.tsx`:

(a) Add the imports `objectivesForBroad, resolveObjectiveForBroad` to the existing import from `"./assets"`. Find the import block that already imports `OBJECTIVES`, `defaultUniverseDraft`, `universeDraftToSpec`, etc. from `"./assets"` and add the two names to it.

(b) Immediately after `const objectiveDef = OBJECTIVES.find((o) => o.value === objective);` (line 229), add:
```ts
  const broadUniverse = mode === "universe" && universeDraft.broadUniverse;
  const visibleObjectives = objectivesForBroad(broadUniverse);
  // Entering broad mode while a mu-based objective is selected silently resets
  // it to the mu-free default (the dropdown also hides it). Functional update
  // keeps `objective` out of the dependency list.
  useEffect(() => {
    setObjective((o) => resolveObjectiveForBroad(o, broadUniverse));
  }, [broadUniverse]);
```

(c) In the objective `<select>`, replace:
```tsx
                {OBJECTIVES.map((o) => (
```
with:
```tsx
                {visibleObjectives.map((o) => (
```

(d) Add a hint under the objective description. Replace:
```tsx
          {objectiveDef && (
            <p className="ix-fs mb-0 mt-2.5 text-text-muted">
              {objectiveDef.description}
            </p>
          )}
```
with:
```tsx
          {objectiveDef && (
            <p className="ix-fs mb-0 mt-2.5 text-text-muted">
              {objectiveDef.description}
            </p>
          )}
          {broadUniverse && (
            <p className="ix-fs mb-0 mt-2 text-text-muted">
              Broad mode is risk-structure-only (gate G5) — return-based
              objectives (BL max utility) are unavailable.
            </p>
          )}
```

- [ ] **Step 6: Verify type-check (no new errors in touched files).** Run: `cd frontend && pnpm run typecheck 2>&1 | grep -E "assets.ts|FundUniverseCard|BuilderView"`
  Expected: the ONLY `BuilderView.tsx` lines are the 2 pre-existing `turnover_lambda` errors (lines ~215/222); no errors mention `assets.ts`, `broadUniverse`, `objectivesForBroad`, or the objective select. If a NEW error appears, fix it.

- [ ] **Step 7: Commit.**
```bash
git add frontend/src/components/builder/assets.ts frontend/src/components/builder/assets.test.ts frontend/src/components/builder/BuilderView.tsx
git commit -m "feat(builder): gate mu-based objectives out of broad mode (T3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `SelectionDiagnostics` panel + ResultsPanel wiring

**Files:**
- Create: `frontend/src/components/builder/SelectionDiagnostics.tsx`
- Create: `frontend/src/components/builder/SelectionDiagnostics.test.tsx`
- Modify: `frontend/src/components/builder/ResultsPanel.tsx`

- [ ] **Step 1: Write the failing test.** Create `frontend/src/components/builder/SelectionDiagnostics.test.tsx`:

```tsx
// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { SelectionDiagnostics } from "./SelectionDiagnostics";

afterEach(cleanup);

const selection = {
  n_candidates: 120,
  n_selected: 3,
  excluded: [{ fund: "fund:AAA", reason: "median pairwise overlap 80 < 252" }],
  clusters: { "fund:REP1": 1, "fund:REP2": 2, "fund:REP3": 3 },
};

describe("SelectionDiagnostics", () => {
  it("summarises candidates→positions and expands to clusters + exclusions", async () => {
    const user = userEvent.setup();
    render(<SelectionDiagnostics selection={selection} />);

    // Summary visible while collapsed; detail tables hidden.
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText(/candidates/)).toBeInTheDocument();
    expect(screen.queryByText("Risk cluster")).not.toBeInTheDocument();
    expect(screen.queryByText(/Excluded/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Selection/i }));

    expect(screen.getByText("Risk cluster")).toBeInTheDocument();
    expect(screen.getByText("fund:REP1")).toBeInTheDocument();
    expect(screen.getByText(/median pairwise overlap/)).toBeInTheDocument();
  });

  it("omits the excluded table when nothing was excluded", async () => {
    const user = userEvent.setup();
    render(<SelectionDiagnostics selection={{ ...selection, excluded: [] }} />);
    await user.click(screen.getByRole("button", { name: /Selection/i }));
    expect(screen.queryByText(/Excluded/)).not.toBeInTheDocument();
    expect(screen.getByText("Risk cluster")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL.** Run: `cd frontend && pnpm vitest run src/components/builder/SelectionDiagnostics.test.tsx`
  Expected: FAIL — module `./SelectionDiagnostics` does not exist.

- [ ] **Step 3: Implement the component.** Create `frontend/src/components/builder/SelectionDiagnostics.tsx`:

```tsx
"use client";

import { useState } from "react";

import { formatNumber } from "@/lib/format";
import type { OptimizeResponse } from "@/lib/api/client";

type Selection = NonNullable<OptimizeResponse["diagnostics"]["selection"]>;

/**
 * Collapsible Stage-1 selection summary for the broad-universe optimizer: how
 * many candidates were considered, how many representatives were picked, which
 * risk cluster each represents, and which funds were excluded (with the
 * fail-loud reason). The caller guards on `diagnostics.selection != null`.
 */
export function SelectionDiagnostics({ selection }: { selection: Selection }) {
  const [open, setOpen] = useState(false);
  const clusterEntries = Object.entries(selection.clusters);
  const nClusters = new Set(Object.values(selection.clusters)).size;
  return (
    <section className="border border-border bg-surface-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="ix-pad flex w-full items-center justify-between gap-2 text-left transition-colors hover:bg-layer-hover"
      >
        <h2 className="ix-label m-0">
          Selection
          <span className="ml-2 font-normal normal-case tracking-normal text-text-secondary">
            <span className="font-bold tabular-nums">
              {formatNumber(selection.n_candidates, 0)}
            </span>{" "}
            candidates →{" "}
            <span className="font-bold tabular-nums">
              {formatNumber(selection.n_selected, 0)}
            </span>{" "}
            positions · {nClusters} risk clusters
          </span>
        </h2>
        <span aria-hidden className="text-[11px] text-text-muted">
          {open ? "▲" : "▼"}
        </span>
      </button>
      {open && (
        <div className="ix-pad flex flex-col gap-4 border-t border-border pt-3">
          <table className="w-full max-w-[480px] border-collapse ix-fs tabular-nums">
            <thead>
              <tr className="bg-field">
                <th className="px-2.5 py-[9px] text-left font-semibold text-text-secondary">
                  Position
                </th>
                <th className="px-2.5 py-[9px] text-right font-semibold text-text-secondary">
                  Risk cluster
                </th>
              </tr>
            </thead>
            <tbody>
              {clusterEntries.map(([fund, cluster]) => (
                <tr key={fund} className="border-b border-border">
                  <td className="ix-cell px-2.5 font-bold text-accent">{fund}</td>
                  <td className="ix-cell px-2.5 text-right text-text-secondary">
                    #{cluster}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {selection.excluded.length > 0 && (
            <div>
              <p className="ix-label mb-1.5">
                Excluded ({selection.excluded.length})
              </p>
              <table className="w-full border-collapse ix-fs">
                <thead>
                  <tr className="bg-field">
                    <th className="px-2.5 py-[9px] text-left font-semibold text-text-secondary">
                      Fund
                    </th>
                    <th className="px-2.5 py-[9px] text-left font-semibold text-text-secondary">
                      Reason
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {selection.excluded.map((ex) => (
                    <tr key={ex.fund} className="border-b border-border">
                      <td className="ix-cell px-2.5 font-bold text-accent">
                        {ex.fund}
                      </td>
                      <td className="ix-cell px-2.5 text-text-secondary">
                        {ex.reason}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
```

> **Confirme:** `OptimizeResponse` é exportado de `@/lib/api/client` (o `ResultsPanel.tsx` já o importa de lá). Se o nome diferir, use o mesmo import que `ResultsPanel` usa para o tipo da resposta.

- [ ] **Step 4: Run the component test, expect PASS.** Run: `cd frontend && pnpm vitest run src/components/builder/SelectionDiagnostics.test.tsx`
  Expected: 2 passed.

- [ ] **Step 5: Wire into ResultsPanel.** In `frontend/src/components/builder/ResultsPanel.tsx`:

(a) Add the import near the other local imports:
```tsx
import { SelectionDiagnostics } from "./SelectionDiagnostics";
```

(b) Replace the μ-diagnostics block:
```tsx
      {/* ── μ diagnostics (only when views drove a posterior) ───────────── */}
      {diagnostics.mu_equilibrium != null && diagnostics.mu_posterior != null && (
        <MuDiagnostics
          rows={rows}
          equilibrium={diagnostics.mu_equilibrium}
          posterior={diagnostics.mu_posterior}
        />
      )}
    </div>
```
with:
```tsx
      {/* ── μ diagnostics (only when views drove a posterior) ───────────── */}
      {diagnostics.mu_equilibrium != null && diagnostics.mu_posterior != null && (
        <MuDiagnostics
          rows={rows}
          equilibrium={diagnostics.mu_equilibrium}
          posterior={diagnostics.mu_posterior}
        />
      )}

      {/* ── Selection diagnostics (broad-universe mode only) ────────────── */}
      {diagnostics.selection != null && (
        <SelectionDiagnostics selection={diagnostics.selection} />
      )}
    </div>
```

- [ ] **Step 6: Verify type-check (no new errors).** Run: `cd frontend && pnpm run typecheck 2>&1 | grep -E "SelectionDiagnostics|ResultsPanel"`
  Expected: no output (no errors in either file).

- [ ] **Step 7: Commit.**
```bash
git add frontend/src/components/builder/SelectionDiagnostics.tsx frontend/src/components/builder/SelectionDiagnostics.test.tsx frontend/src/components/builder/ResultsPanel.tsx
git commit -m "feat(builder): selection diagnostics panel for broad-universe results (T4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Backend — corrigir a mensagem de cap infeasível

**Files:**
- Modify: `backend/app/services/portfolio_builder.py` (line ~431)
- Modify: `backend/tests/test_builder_broad_universe.py` (the explicit-infeasible-cap test)

- [ ] **Step 1: Write the failing assertion.** In `backend/tests/test_builder_broad_universe.py`, find the test `test_broad_universe_explicit_infeasible_cap_fails_loud`. It asserts `response.status_code == 422` and that the body mentions the cap/infeasibility. Add an assertion that the message guides the user correctly:
```python
    assert "increase max_positions" in response.text
```
(Place it right after the existing `assert response.status_code == 422` / body assertions in that test.)

- [ ] **Step 2: Run, expect FAIL.** Run: `cd backend && python -m pytest tests/test_builder_broad_universe.py -k explicit_infeasible_cap -v`
  Expected: FAIL — the current message says "lower max_positions", so "increase max_positions" is absent.

- [ ] **Step 3: Implement.** In `backend/app/services/portfolio_builder.py`, in the broad-mode cap guard, replace:
```python
                "raise the cap or lower max_positions"
```
with:
```python
                "raise the cap or increase max_positions"
```

- [ ] **Step 4: Run, expect PASS.** Run: `cd backend && python -m pytest tests/test_builder_broad_universe.py -q`
  Expected: all green (the infeasible-cap test now finds "increase max_positions"; the others unaffected since the message still contains "infeasible").

- [ ] **Step 5: Commit.**
```bash
git add backend/app/services/portfolio_builder.py backend/tests/test_builder_broad_universe.py
git commit -m "fix(builder): correct broad cap-infeasible hint (increase, not lower, max_positions) (T5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Gate — type-check + targeted tests

**Files:** (nenhum novo — verificação)

- [ ] **Step 1: Frontend type-check — no new errors.** Run: `cd frontend && pnpm run typecheck`
  Expected: exits with ONLY the 6 pre-existing errors — 2 in `BuilderView.tsx` (`turnover_lambda`) and 4 in `rebalance.test.ts` (`status`). NONE in `assets.ts`, `FundUniverseCard.tsx`, `SelectionDiagnostics.tsx`, or `ResultsPanel.tsx`. If a new error appears in a touched file, fix it and re-run.

- [ ] **Step 2: Frontend builder tests — all green.** Run: `cd frontend && pnpm vitest run src/components/builder`
  Expected: the new suites (`assets.test.ts`, `FundUniverseCard.test.tsx`, `SelectionDiagnostics.test.tsx`) all pass; no builder regressions.

- [ ] **Step 3: Backend tests + lint.** Run:
  ```
  cd backend && python -m pytest tests/test_builder_broad_universe.py tests/test_builder_schema.py -q
  cd backend && python -m ruff check app/services/portfolio_builder.py
  ```
  Expected: green; ruff clean.

- [ ] **Step 4: Commit (only if the gate required adjustments).**
```bash
git add -A
git commit -m "test(builder): broad-universe UI regression gate (T6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
  (If nothing changed, skip — the gate is verification only.)

---

## Notas de escopo

- **Não há regen de contrato:** os campos de request (`broad_universe`/`max_positions`/`min_pair_overlap`) e o tipo de resposta (`SelectionDiagnosticsOut`/`ExcludedFundOut`/`DiagnosticsOut.selection`) já estão no `api.d.ts` gerado (T7 do optimizer). Nenhuma task regenera o contrato.
- **Sem teste de render do `BuilderView` inteiro:** o gating de objetivo é exercido pelas funções puras `objectivesForBroad`/`resolveObjectiveForBroad` (Task 3, testadas em `assets.test.ts`); o wiring em `BuilderView` é mecânico e coberto pelo type-check. Um render completo do `BuilderView` exigiria mock pesado (next/navigation, postBuilderOptimize, todos os cards) com baixo retorno de cobertura — deliberadamente fora de escopo.
- **Follow-up conhecido (não neste plano):** a degenerescência do auto-relax do cap (erguer para exatamente `1/K` força peso igual; ocorre p/ K≤4) — evitada na UI pela faixa K≥5; um follow-up de backend poderia erguer o cap para `>1/K` ou sinalizá-lo no diagnóstico.
```
