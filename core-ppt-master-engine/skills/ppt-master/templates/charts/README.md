# SVG Visualization Template Library

This directory contains the standardized SVG visualization templates used by Presentation Builder — charts, infographics, process diagrams, relationship diagrams, and strategic frameworks. The directory name `charts/` is kept for backward compatibility; the library scope is broader than charts.

## Source of truth

[`charts_index.json`](./charts_index.json) is the single source of truth for the library: total count + one selection-rule `summary` per template (format: `"Pick for X. Skip if Y (use other_key)."`). Both human readers and AI roles read it in full — there is no category/keyword sub-index. Selection is done by semantic match against the summary list in one pass.

To browse the library, open `charts_index.json` and scan the `charts` block top-to-bottom; each entry's `summary` answers "when do I pick this, when do I skip" directly.

## Style rules

See [`CHART_STYLE_GUIDE.md`](./CHART_STYLE_GUIDE.md) for the color palette, typography, and SVG authoring conventions the **stock** templates must follow.

The company catalog in [`powerslides_infographics/`](./powerslides_infographics/) is the exception: it has its own index (`company_index.json`), its own brand identity ([`STYLE_GUIDE.md`](./powerslides_infographics/STYLE_GUIDE.md)), and is matched **before** the stock library (see [`references/strategist.md`](../../references/strategist.md) §VII "Company catalog first"). It does not follow `CHART_STYLE_GUIDE.md`.

## Usage

Before generating a chart page, open the corresponding `<key>.svg` file to read its structure and layout. Files are named after the `key` field in `charts_index.json` (e.g. `bar_chart.svg`, `quadrant_bubble_scatter.svg`). Templates are named by visual structure, not by business-model name — keywords like SWOT, BCG, PEST, OKR, Porter's Five Forces, Value Chain are matched via each template's `summary` field.
