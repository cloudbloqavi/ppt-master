---
kind: reference
artifact: chart_provenance.json
---

# Chart Provenance Reference (`chart_provenance.json`)

> Machine-readable record of **which visualization source each slide actually used**.
> One entry per page that carries a chart / structured infographic. Written by the
> Strategist at selection time and **confirmed/corrected by the Executor at inclusion
> time** (the Executor is the source of truth for what actually shipped in the SVG).
> The runner validates it after the turn, and the structural-mimic review consumes it.

This file exists because the three older artifacts disagreed in practice: `design_spec.md`
§VII (Strategist intent), `spec_lock.md` `page_charts` (lock), and the SVG the Executor
actually drew could all name different templates for the same page. `chart_provenance.json`
is the **single reconciled truth** — and the only artifact the structural-mimic review reads.

## Location

`<project_path>/chart_provenance.json`

## Schema (v1)

```json
{
  "schema": "chart_provenance/v1",
  "pages": {
    "P01": {
      "tier": "company",
      "key": "11_org_tree",
      "reference": "templates/charts/powerslides_infographics/11_org_tree.svg",
      "viz_type": "org_tree",
      "decision": "Pick: org charts / OKR cascades; no Skip clause applies.",
      "confirmed_by": "executor"
    },
    "P02": {
      "tier": "stock",
      "key": "isometric_stairs",
      "reference": "templates/charts/isometric_stairs.svg",
      "viz_type": "maturity_progression",
      "decision": "No company entry fit (31_maturity_transformation_roadmap is a raw export; Skip per executor 'never silently abandon'); closest stock match.",
      "confirmed_by": "executor"
    },
    "P04": {
      "tier": "custom",
      "key": null,
      "reference": null,
      "viz_type": "stacked_year_roadmap",
      "decision": "No company or stock template fit a 5-year stacked-objective roadmap; bespoke free design.",
      "confirmed_by": "executor"
    }
  }
}
```

## Field rules

| Field | Rule |
|---|---|
| `tier` | One of `company` \| `stock` \| `custom`. Drives the review behavior below. |
| `key` | Template basename without `.svg` (e.g. `11_org_tree`, `isometric_stairs`). **`null` only when `tier: custom`.** |
| `reference` | Repo-relative path to the source SVG. **Must exist on disk** for `company`/`stock`. **`null` only when `tier: custom`.** |
| `viz_type` | Short slug for the visualization (matches §IX visualization name). |
| `decision` | One sentence. For `company`/`stock`: why this entry (cite the Pick clause). **For `custom`: MANDATORY logged reason** why neither catalog fit — empty/absent is a validation failure. |
| `confirmed_by` | `strategist` when first written; the Executor rewrites to `executor` once the page SVG is generated against (or diverged from) the reference. |

## Tier → reference path resolution

| `tier` | `reference` resolves to |
|---|---|
| `company` | `templates/charts/powerslides_infographics/<key>.svg` |
| `stock` | `templates/charts/<key>.svg` |
| `custom` | `null` (no reference exists) |

## How the structural-mimic review uses this file

| `tier` | Review behavior |
|---|---|
| `company` | Structural-mimic compare generated SVG topology against `reference` (strict — the slide must visibly carry the reference's structure; runtime theme/colors are expected to differ and are ignored). |
| `stock` | Same structural-mimic compare against the stock `reference`. |
| `custom` | **Skip** structural compare — there is no reference. Only the generic layout/quality audit applies. |

## Selection cascade (Strategist) — the three tiers

1. **Company catalog first** — match the page against `powerslides_infographics/company_index.json` (30 entries). If a `Pick` clause fits and no `Skip` applies and the SVG is cleanly reproducible → `tier: company`.
2. **Stock catalog** — only if no company entry fit, match `charts_index.json` (71 entries). A fit → `tier: stock`.
3. **Custom (LLM free design)** — only if neither catalog fits the content / style / theme coherence → `tier: custom`, with a **mandatory** `decision` reason. Never silently default to custom.
