# Investintell-Light Design System

A **foundations-only** design system: tokens, typography, color, and spacing — nothing
else. No components, no UI kit, no slide/deck generation. It exists to be the **base layer
for refactoring another system** onto a single, disciplined token contract.

The visual language is institutional and data-first — built for **investment / financial**
interfaces: light ground, graphite ink, a single deep accent, flat square forms, and
**tabular numerals everywhere**. Numbers, not adjectives.

---

## What's in scope

| Layer | File(s) | Notes |
|---|---|---|
| **Entry point** | `styles.css` | Link this one file; it `@import`s everything below. `@import` lines only. |
| **Fonts** | `tokens/fonts.css` | `@font-face` (system `local()` + Google fallbacks). |
| **Colors** | `tokens/colors.css` | Literal palette + **semantic aliases** (the contract). |
| **Typography** | `tokens/typography.css` | Families, weights, type scale, tracking, tabular numerals. |
| **Spacing** | `tokens/spacing.css` | 4px scale, layout, borders, radii (0), elevation (none), ticks. |
| **Specimens** | `guidelines/*.card.html` | Visual reference cards for Colors / Type / Spacing. |

> **Out of scope (removed):** React components, the accounting UI kit, slide templates,
> and all deck-generation scripts. This package is deliberately just the foundation.

---

## How to consume it

Link the entry point and build against the **semantic tokens**:

```html
<link rel="stylesheet" href="styles.css">
```

```css
.panel  { background: var(--surface-card); border: 1px solid var(--border-hairline); }
.metric { font: 700 var(--text-kpi)/1 var(--font-sans); font-variant-numeric: tabular-nums; color: var(--ink); }
.accent { color: var(--accent); }
```

When refactoring another system onto this base, **map that system's primitives to the
semantic layer** (`--accent`, `--surface-*`, `--text-*`, `--border-hairline`, `--space-*`,
and the `--text-*` scale) rather than to literal palette names. The semantic aliases are the
stable contract; the literal palette underneath can be re-skinned without touching consumers.

---

## Principles

1. **Light ground always.** Emphasis comes from ink weight and the accent — never a
   background color. No gradients, no textures.
2. **Accent is accent, not fill.** The single deep accent is reserved for hero numbers,
   ticks, rules, and one highlighted data series.
3. **Serif on the title, sans on the data.** Cambria for headings (gravity); Arial,
   **bold + tabular**, for every number.
4. **Flat forms.** Radius 0, no shadow. Depth is drawn with hairlines and graphite blocks —
   the system ships `--radius-*: 0` and `--shadow-*: none` to enforce this.
5. **Numbers, not adjectives.** Exact figures over "solid / strong"; no `~` or `≈`.

---

## Token reference

### Colors (`tokens/colors.css`)
- **Literal palette:** `--oxblood` (accent), `--oxblood-dark`, `--oxblood-wash`,
  `--oxblood-hover`, `--ink`, `--graphite`, `--body`, `--mute`, `--faint`, `--hairline`,
  `--panel`, `--white`, `--grey-bar`.
- **Semantic (build against these):** `--surface-page` · `--surface-card` · `--surface-panel`
  · `--surface-block` · `--surface-selected` · `--text-title` · `--text-body` · `--text-label`
  · `--text-faint` · `--text-on-dark` · `--text-accent` · `--accent` · `--accent-strong` ·
  `--rule-accent` · `--border-hairline` · `--chart-bar` · `--chart-bar-mute` ·
  `--chart-highlight` · `--status-positive` · `--status-negative` · `--status-neutral`.
- *The literal accent is named `--oxblood` for continuity with the source palette; if the
  refactor wants a neutral name, point `--accent` at a new literal and rename freely — only
  the semantic layer is referenced by consumers.*

### Typography (`tokens/typography.css`)
- **Families:** `--font-serif` (Cambria → PT Serif), `--font-sans` (Arial → Arimo),
  `--font-display`, `--font-body`, `--font-mono`.
- **Weights:** `--weight-regular/medium/semibold/bold`.
- **Scale:** `--text-hero` 42 · `--text-title` 29 · `--text-kpi` 28 · `--text-h2` 22 ·
  `--text-h3` 18 · `--text-body` 16 · `--text-small` 14 · `--text-label` 12 · `--text-footer` 13.
- **Leading:** `--leading-tight/snug/normal`. **Tracking:** `--tracking-label/tight/normal`.
- **Helpers:** `.ix-title` · `.ix-kpi` · `.ix-body` · `.ix-label` · `.ix-num` (optional;
  tokens are the contract).

### Spacing & form (`tokens/spacing.css`)
- **Scale (4px base):** `--space-0` … `--space-8` (0 → 64px).
- **Layout:** `--margin-page` · `--spine-width` · `--rule-accent-w/h` · `--content-max`.
- **Borders:** `--border-width` · `--border-hairline-w` · `--border-strong-w` · `--border-style`.
- **Radii:** `--radius-none/sm/md/pill` — all `0`.
- **Elevation:** `--shadow-none` · `--shadow-card` — both `none`.
- **Marks:** `--tick-width` · `--tick-height`.

---

## Fonts

Cambria and Arial are declared via `@font-face` with `local()` sources, so they resolve to
the genuine system faces when installed; **PT Serif** and **Arimo** (metric-compatible with
Arial) load from Google Fonts as the web fallback. To pin exact files, add `url(...)` sources
to the `@font-face` blocks in `tokens/fonts.css`.

---

## Files

```
styles.css                 — entry point (@import only)
tokens/fonts.css           — @font-face + webfont import
tokens/colors.css          — palette + semantic aliases
tokens/typography.css      — families, scale, tracking, numerals
tokens/spacing.css         — spacing, borders, radii, elevation, marks
guidelines/*.card.html     — Colors / Type / Spacing specimen cards
readme.md · SKILL.md       — this file + portable skill manifest
```
