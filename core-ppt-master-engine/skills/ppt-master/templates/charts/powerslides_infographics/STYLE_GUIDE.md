# PowerSlides Infographics — Company Style Guide

> This document defines the visual specifications for the **company-preferred** infographic templates in this folder (`templates/charts/powerslides_infographics/`).
> These templates carry their own brand identity and do **not** follow the stock [`../CHART_STYLE_GUIDE.md`](../CHART_STYLE_GUIDE.md) (Tailwind palette). This guide mirrors that document's structure; where a section is identical it says so rather than duplicating, to avoid drift.

> **Cardinal rule — preserve on recreation.** When the Strategist selects one of these templates (Design Spec §VII, path `templates/charts/powerslides_infographics/<key>.svg`) and the Executor recreates the page, **preserve the source SVG's own colors and typography**. Do not normalize to the stock Tailwind palette. New infographics added here must follow the palette and type below to stay consistent.

> **Override vs inherit.** Sections **1** (Color System) and **2.1** (Font Stack) **override** the stock guide with company values. Section **9** (Register) targets `company_index.json`. Every other section is **inherited** — identical to the stock guide and/or [`shared-standards.md`](../../../references/shared-standards.md); only the *aesthetic* layer diverges.

## 0. Upstream Specification Reference

Same as the stock guide §0. These templates must also comply with project-level general technical constraints:

> **[`shared-standards.md`](../../../references/shared-standards.md)** — SVG disabled-features blacklist, PPT compatibility alternatives, Canvas format, tspan inline rules, grouping specifications, shadow/overlay techniques, post-processing pipeline.

Only the **aesthetic** layer (Color System §1, Font Stack §2.1) diverges from the stock guide; all structural/technical constraints are inherited unchanged.

---

## 1. Color System (Company Brand Palette)

**Overrides** the stock Tailwind palette. Observed across the 30 templates in this folder.

### 1.1 Text Colors

| Purpose | Color Value | Notes |
|------|------|------|
| **Main Title** | `#1E2761` | Brand navy |
| **Value Label** | `#0F1530` | Near-black navy, key metrics |
| **Subtitle** | `#6B7BAE` | Muted blue-violet |
| **Axis / Secondary Label** | `#595959` | Neutral grey |
| **Body Text** | `#3F3F3F` | Neutral dark grey |
| **Data Source / Faded Hint** | `#CADCFC` | Light blue tint |
| **On-dark Text** | `#FFFFFF` | White, over navy panels |

### 1.2 Theme Colors (Data Series)

| Color Name | Main Color | Dark Variant (Gradient End) | Purpose |
|------|------|------------------|------|
| **Coral Red** | `#E63946` | `#C92A37` | Primary accent / highlight / key markers (dominant) |
| **Steel Blue** | `#457B9D` | `#356381` | 1st series / main structural fill |
| **Medium Blue** | `#649ABB` | `#4E7E9C` | 2nd series / supporting fill |
| **Muted Blue-Violet** | `#6B7BAE` | `#55648F` | 3rd series / connectors |
| **Light Blue** | `#CADCFC` | `#A9C2EE` | Tints, soft backgrounds, faded labels |
| **Navy** | `#1E2761` | `#0F1530` | Headers, dark backgrounds, cover panels |

### 1.3 Semantic Colors

The brand leans on its blues + coral rather than a green/red split. Map semantics as:

| Purpose | Color Value | Description |
|------|------|------|
| Positive / Neutral | `#457B9D` | Steel blue |
| Emphasis / Alert | `#E63946` | Coral red |
| Caution / Standout | `#FFC000` | Gold (use sparingly — e.g. a warning cell) |

### 1.4 UI Auxiliary Colors

| Purpose | Color Value | Description |
|------|------|------|
| **Card / Panel Background** | `#F2F2F2` | Light surface grey |
| **Card Stroke / Divider** | `#CADCFC` | Light blue, or `#E4ECFB` |
| **Center Divider Line** | `#6B7BAE` | Muted blue |
| **Tint Background** | `#E4ECFB` | Very light brand blue |
| **White** | `#FFFFFF` | Card fills, on-dark text |

---

## 2. Typography Guidelines

### 2.1 Font Stack (Override)

PPT-safe stacks (every stack ends in a pre-installed family):

| Use | Stack |
|-----|-------|
| **Body / Titles** | `Calibri, Calibri_MSFontService, sans-serif` |
| **Mono / Code / Labels** | `Consolas, Consolas_MSFontService, sans-serif` |
| **Display (optional)** | `Lato Black, Lato Black_MSFontService, sans-serif` (falls back to `Arial`) |
| **Fallback** | `Arial, Arial_MSFontService, sans-serif` |

- **Forbidden** to use `@font-face`, external fonts, or `<style>` tags (same as stock guide).

### 2.2 Font Size Hierarchy

Inherits the stock guide §2.2 (H1 34 / H2 22 / Body 14–20 / Caption 12–13; **minimum 12px**). Cover/hero pages may use larger display sizes.

### 2.3 tspan Specification

Inherits the stock guide §2.3 — all `<text>` content wrapped in `<tspan>`.

### 2.4 Inline Formatting Rules (shared-standards SS4)

Inherits the stock guide §2.4 — single logical line = single `<text>`; multi-color/weight via inline `<tspan>` (no `x`/`y`/`dy` on inline tspan).

### 2.5 Data Highlight Default Behavior

Inherits the stock guide §2.5, with the **brand accent** substituting the Tailwind theme color: highlight numerical results with `<tspan fill="#E63946" font-weight="bold">` (coral) instead of `#3B82F6`.

---

## 3. Shadow Filter

Inherits the stock guide §3 (feFlood scheme; no `<feComponentTransfer>`; opacity ≤ 0.20), with one override: shadow `flood-color` uses the brand navy **`#0F1530`** instead of `#0F172A`.

---

## 4. Gradient Specification

Inherits the stock guide §4. Gradient end-colors use the **dark variants** from §1.2 above (e.g. `#457B9D` → `#356381`) rather than the Tailwind dark stops.

---

## 5. Structure Specification

Inherits the stock guide §5 entirely — hierarchical grouping (SS4), `viewBox="0 0 1280 720"` (§5.2), background (§5.3), and data-source placement (§5.4).

---

## 6. SVG Forbidden Features and Compatibility (shared-standards SS1–2)

Inherits the stock guide §6 and `shared-standards.md` SS1–2 **unchanged** — no company override. Same absolutely-forbidden list, PPT compatibility alternatives, conditionally-allowed features, and dashed-line presets.

---

## 7. Old Color Mapping Quick Reference

When adapting a generic/stock-colored source into this catalog, remap to the brand palette:

| Generic role | → Brand color |
|------|------|
| Primary blue / 1st series | `#457B9D` |
| Accent / highlight | `#E63946` |
| Title / dark text | `#1E2761` |
| Faded / hint | `#CADCFC` |
| Card background | `#F2F2F2` |

---

## 8. Placeholder Content Strategy

Inherits the stock guide §8 entirely — English-only rule (§8.0), structural-boundary demonstration (§8.1), generality/neutrality (§8.2), visual balance (§8.3).

---

## 9. Register to `company_index.json` (Override)

Unlike stock charts (which register to `charts_index.json`), templates here register to [`company_index.json`](./company_index.json) — the **company-preferred** catalog matched *before* the stock library (see [`strategist.md`](../../../references/strategist.md) §VII "Company catalog first").

### 9.1 Field Specification

Each entry: `"<key>": { "summary": "Pick for <content shape + scale>. Skip for <reason → alternative>." }`. `key` matches the filename stem (e.g. `23_quarterly_product_roadmap`). Per-template descriptions and match criteria live in [`design_spec.md`](./design_spec.md).

### 9.2 Counter-examples

Same anti-patterns as the stock guide §9.2 — a `summary` that describes the picture instead of stating a `Pick for … / Skip for …` selection rule is wrong.

---

## 10. Checklist

Inherits the stock guide §10, with two company deltas:
- **Colors** — verify against the brand palette in §1 above (not the Tailwind palette).
- **Registration** — verify the entry exists in `company_index.json` (not `charts_index.json`).

All other checks (basic validation, typography, structure, shadows, coordinate-calibration markers, verification commands) are unchanged.

---

## 11. Card Container Patterns

Inherits the stock guide §11 (§11.1–11.8). The card-construction patterns are geometry, palette-agnostic — reuse them, filled with the brand colors from §1.
