# Chart SVG Style Guide

> This document defines the visual specifications for all SVG chart templates under `templates/charts/`.
> Any new or modified charts **must** follow these standards to ensure visual consistency across the library.

## 0. Upstream Specification Reference

This document is the aesthetics and implementation guide specifically for **chart templates**. All charts must simultaneously comply with the project-level general technical constraints:

> **[`references/shared-standards.md`](../../references/shared-standards.md)** — SVG banned features blacklist, PPT compatibility alternatives, Canvas format, tspan inline rules, grouping specifications, shadow/overlay techniques, and the post-processing pipeline.

The following sections extract entries from `shared-standards.md` most closely related to chart templates. Please consult the upstream document for full details (such as marker constraints, clipPath constraints, arc path calculation formulas, etc.).

---

## 1. Color System (Tailwind CSS Palette)

### 1.1 Text Colors

| Purpose | Hex Value | Tailwind Token | Example |
| :--- | :--- | :--- | :--- |
| **Main Title** | `#0F172A` | Slate 900 | Main chart title |
| **Value Labels** | `#0F172A` | Slate 900 | Numbers on top of bars, key metrics |
| **Subtitle** | `#64748B` | Slate 500 | Date, unit descriptions |
| **Axis Labels** | `#64748B` | Slate 500 | X/Y axis scale values |
| **Axis Title / Legend** | `#475569` | Slate 600 | "Annual Salary (USD)", legend text |
| **Data Source** | `#94A3B8` | Slate 400 | Source attribution at page bottom |
| **Footnote / Muted Tips** | `#CBD5E1` | Slate 300 | "Stages can be flexibly adjusted" |

### 1.2 Theme Colors (Data Series)

| Color Name | Main Color | Dark Color (Gradient End) | Purpose |
| :--- | :--- | :--- | :--- |
| **Blue** | `#3B82F6` | `#2563EB` | Series 1 (Default preferred) |
| **Emerald** | `#10B981` | `#059669` | Series 2 |
| **Amber** | `#F59E0B` | `#D97706` | Series 3 |
| **Violet** | `#8B5CF6` | `#7C3AED` | Series 4 |
| **Rose** | `#FB7185` | `#E11D48` | Series 5 / Warnings |
| **Pink** | `#EC4899` | `#BE185D` | Comparison group (e.g. Female in butterfly chart) |

> Radial gradients (e.g. bubble charts) use bright variants: `#60A5FA`, `#34D399`, `#FBBF24`, `#A78BFA`, `#FB7185`

### 1.3 Semantic Colors

| Purpose | Hex Value | Description |
| :--- | :--- | :--- |
| Target Met / Positive | `#10B981` | Emerald 500 |
| Warning / Neutral | `#F59E0B` | Amber 500 |
| Missed Target / Negative | `#EF4444` | Red 500 |
| Outlier Annotation | `#F43F5E` | Rose 500 |

### 1.4 UI Auxiliary Colors

| Purpose | Hex Value | Description |
| :--- | :--- | :--- |
| **Axis Lines** | `#94A3B8` | Slate 400, stroke-width="2" |
| **Grid Lines** | `#E2E8F0` or `#E0E0E0` | stroke-dasharray="4,4" |
| **Center Dividers** | `#CBD5E1` | E.g. Quadrant crosshair lines |
| **Card Background** | `#F8FAFC` / `#F8F9FA` | Slate 50 |
| **Card Stroke** | `#E2E8F0` | Slate 200 |
| **Row Divider** | `#F1F5F9` | Slate 100 (Very faint) |
| **Tint Background** (Blue) | `#EFF6FF` | Blue 50 |
| **Tint Background** (Green) | `#ECFDF5` | Emerald 50 |
| **Tint Background** (Red) | `#FFF1F2` | Rose 50 |
| **Tint Background** (Yellow) | `#FFFBEB` | Amber 50 |

---

## 2. Typography Specification

### 2.1 Font Stack

```
font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
```

- For pure English scenarios, `'PingFang SC', 'Microsoft YaHei'` can be omitted.
- **Banned**: Do NOT use `@font-face`, external fonts, or `<style>` tags.

### 2.2 Font Hierarchy

| Level | Size | font-weight | Purpose |
| :--- | :--- | :--- | :--- |
| H1 | `34px` | `bold` (700) | Main chart title |
| H2 | `22px` | `600` | Section title (e.g. "Detailed Data") |
| Body L | `18-20px` | `600` | Key metrics, percentages |
| Body M | `15-16px` | `600` | Data labels, category names |
| Body S | `14px` | normal | Subtitles, legends, sources |
| Caption | `12-13px` | normal | Axis scales, footnotes |

> **Minimum font size limit: 12px**. All text elements must not be smaller than 12px.

### 2.3 tspan rules

All text contents inside `<text>` elements **must** be wrapped in `<tspan>`:

```xml
<!-- Correct -->
<text x="60" y="80" font-size="34" fill="#0F172A">
    <tspan>Chart Title</tspan>
</text>

<!-- Incorrect -->
<text x="60" y="80" font-size="34" fill="#0F172A">Chart Title</text>
```

### 2.4 Inline Formatting Rules (shared-standards SS4)

**Single logical line = Single `<text>`**. When different colors or weights are needed within the same line, use inline `<tspan>` tags. **Do NOT** use separate, side-by-side `<text>` elements:

```xml
<!-- Correct: One text frame, three runs -->
<text x="100" y="200" font-size="24" fill="#333333">
  Achieve a <tspan fill="#3B82F6" font-weight="bold">10x</tspan> efficiency boost
</text>

<!-- Incorrect: Three independent text frames, cannot be edited as one line in PPT -->
<text x="100" y="200">Achieve a</text>
<text x="160" y="200" fill="#3B82F6">10x</text>
<text x="240" y="200">efficiency boost</text>
```

> Inline tspan elements **must NOT** carry `x`, `y`, or `dy` attributes; otherwise, the post-processor will split them into separate text frames. `dx` can be used to fine-tune spacing.

### 2.5 Data Highlighting Default Behavior

Key numbers and metrics in charts should be highlighted by default:
- **Result Metrics**: Percentages, multipliers, amounts → `<tspan fill="ThemeColor" font-weight="bold">`
- **Comparison Indicators**: Increase/decrease, met/unmet target → Semantic color (Green/Red)
- **Non-highlighted Text**: Conjunctions, common verbs, structural text (axis labels, legends, page numbers)

---

## 3. Shadow Filters

`<filter>` elements are permitted and are the recommended path for generating PowerPoint shadows/glows (see the "Banned List" explanation below). All shadow definitions must use the `feFlood` scheme — **do NOT** use `<feComponentTransfer>` inside a `<filter>`:

```xml
<filter id="chartShadow" x="-15%" y="-15%" width="130%" height="130%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="2-4"/>
    <feOffset dx="0" dy="1-3" result="offsetBlur"/>
    <feFlood flood-color="#0F172A" flood-opacity="0.08-0.15" result="shadowColor"/>
    <feComposite in="shadowColor" in2="offsetBlur" operator="in" result="shadow"/>
    <feMerge>
        <feMergeNode in="shadow"/>
        <feMergeNode in="SourceGraphic"/>
    </feMerge>
</filter>
```

### Parameter Reference

| Scenario | stdDeviation | dy | flood-opacity |
| :--- | :--- | :--- | :--- |
| Heavy elements (arrows, cards) | 4-6 | 2-4 | 0.12-0.15 |
| Medium elements (bars, boxes) | 2-3 | 1-2 | 0.10-0.15 |
| Light elements (bottom cards) | 4-6 | 2-4 | 0.06-0.08 |

### Banned List

- `flood-color="#000000"` → Must use `#0F172A`
- `<feComponentTransfer>` + `<feFuncA slope=...>` → Use `<feFlood flood-color flood-opacity>` instead
- `flood-opacity > 0.20` → Shadow is too heavy, keep it under 0.15-0.20

> **The sub-elements are banned, not the `<filter>` tag itself.** `<filter>` is the officially recommended shadow path in PPT Master (see `shared-standards.md` §1 which does not blacklist filters, and §6 which lists filter shadows as the canonical implementation for drop-shadows). The converter (`svg_to_pptx/drawingml_styles.py`) actively maps `feGaussianBlur` + `feOffset` + `feFlood` + `feComposite` + `feMerge` (and the `feDropShadow` shorthand) to DrawingML `<a:outerShdw>`.
>
> The reason `feComponentTransfer/feFuncA(slope)` is banned: **it only adjusts opacity and cannot carry color values**. When the converter reads `feFuncA slope`, it treats it only as alpha and leaves the color as default `'000000'`. While the shadow color looks correct in the SVG (since SourceAlpha is black by default), it defaults to pitch black `#000000` when exported to PPTX, causing a noticeable color temperature clash with other cards that use `feFlood flood-color="#0F172A"`.
>
> In short: **using filters is fine, but the primitives must explicitly define color; primitives that only express opacity are banned.**

### Shadow Usage Principles (shared-standards SS6)

> **Shadows are aesthetic additions, not default decorators.** Restraint produces a "designed" look. "Shadows should be felt, not seen" is the premium aesthetic standard.

- **Apply shadow to**: Cards floating on top of photos/colored panels, the main call-to-action (CTA), overlay layers (tooltips, callouts).
- **Do NOT apply shadow to**: Background panels/splitters, equal peer cards in a grid, containers that already have stroke/gradient fills, main body text containers, decorative lines/icons, or on dark backgrounds (where black shadows are invisible).
- **Page Budget**: Maximum of 2-3 shadow-cast elements per page. If a 4th shadow is needed, remove one from an existing element first.
- **Consistent Light Source**: All `feOffset` `dx`/`dy` directions on a page must be uniform (default to `dx=0, dy=positive`, simulating light from above).
- **Two-tier Height Limits**:

| Tier | Scenario | dy | stdDeviation | flood-opacity |
| :--- | :--- | :--- | :--- | :--- |
| Ground (No shadow) | Backgrounds, peer grid cards, splitters, body text | — | — | — |
| Resting | Cards on photos/panels, secondary callouts | 2-4 | 4-8 | 0.06-0.10 |
| Elevated | Main CTA, focus/recommended cards, overlays | 6-10 | 10-16 | 0.12-0.20 |

- **Do NOT Stack**: Combining shadow + stroke + round corner + gradient fill on the same container looks amateurish. A container's "attention budget" is small; pick only one of these styling elements.

---

## 4. Gradient Specifications

### 4.1 Linear Gradients (Bar/Column Charts)

```xml
<linearGradient id="barGrad1" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" style="stop-color:#3B82F6;stop-opacity:1" />
    <stop offset="100%" style="stop-color:#2563EB;stop-opacity:1" />
</linearGradient>
```

- Direction: Light-to-dark (top-to-bottom or left-to-right).
- Semantic IDs: Give gradient IDs meaningful names, e.g. `barGrad1`, `leftGrad`, `actualBarBlue`.

### 4.2 Radial Gradients (Bubble Charts)

```xml
<radialGradient id="bubbleGrad1" cx="30%" cy="30%">
    <stop offset="0%" style="stop-color:#60A5FA;stop-opacity:0.9" />
    <stop offset="100%" style="stop-color:#2563EB;stop-opacity:0.7" />
</radialGradient>
```

- Position highlights to the top-left (`cx="30%" cy="30%"`).
- Keep edge opacity down to 0.7 to create transparency and depth.

---

## 5. Structural Rules

### 5.1 Hierarchical Grouping (shared-standards SS4 Grouping)

Use `<g id="...">` for semantic grouping to facilitate individual animations or positioning in PPT:

```xml
<g id="chartArea">        <!-- Main chart area -->
    <g id="bar-1">...</g>  <!-- Group each data element independently -->
    <g id="bar-2">...</g>
</g>
<g id="legend">            <!-- Legend area -->
    <g id="legend-high">...</g>
</g>
<g id="detailList">        <!-- Details panel -->
    <g id="list-items">
        <g id="item-1">...</g>
    </g>
</g>
```

**Grouping Unit Reference** (from shared-standards):

| Grouping Unit | Contained Elements |
| :--- | :--- |
| Card/Panel | Background rect + shadow (if applicable) + icon + title + body text |
| Process Step | Number circle + icon + label + description |
| List Item | Bullet/number + icon + title + description |
| Icon-Text Combo | Icon elements + adjacent label |
| Page Header | Title + subtitle + decoration |
| Decor Cluster | Related decorative shapes (rings, spheres, dots) |

**Naming Convention**: Use descriptive `id` attributes (e.g. `card-1`, `step-discover`, `header`, `footer`).

> Only `<g opacity="...">` is banned (see §6.2). Plain structural `<g>` elements are required.

### 5.2 viewBox

Must be fixed to `0 0 1280 720` (PPT 16:9 aspect ratio); do not change.

### 5.3 Background

The first element in the SVG must always be a full-screen white background rect:
```xml
<rect width="1280" height="720" fill="#FFFFFF"/>
```

### 5.4 Data Source

Located at the bottom of the page in a fixed format:
```xml
<text x="60" y="695" font-family="..." font-size="14" fill="#94A3B8">
    <tspan>Source: XXX</tspan>
</text>
```

---

## 6. SVG Banned Features & Compatibility (shared-standards SS1-2)

### 6.1 Absolute Bans

| Banned Feature | Alternative Solution |
| :--- | :--- |
| HTML Named Entities (`&nbsp;`, `&mdash;`, `&copy;`, `&ndash;`, `&reg;`, `&hellip;`, `&bull;`, etc.) | Write the raw Unicode character directly (`—`, `–`, `©`, `®`, `→`, NBSP, etc.) |
| Raw `& < > " '` in text or attributes | Must escape as XML entities: `&amp;`, `&lt;`, `&gt;`, `&quot;`, `&apos;` |
| `<style>` / `class` | Use inline attributes (`id` is legal inside `<defs>`) |
| `<foreignObject>` | `<text>` + `<tspan>` |
| `mask` | Use overlay masking rectangles / gradient overlays |
| `<symbol>` + `<use>` | Write the full duplicated elements directly |
| `textPath` | Position text elements manually |
| `@font-face` | Use the system font stack |
| `<animate*>` / `<set>` | None (handled on the PPT side) |
| `<script>` / event attributes | None |
| `<iframe>` | None |

### 6.2 PPT Compatibility Alternatives

| Banned Syntax | Correct Alternative |
| :--- | :--- |
| `fill="rgba(255,255,255,0.1)"` | `fill="#FFFFFF" fill-opacity="0.1"` |
| `<g opacity="0.2">...</g>` | Set `fill-opacity` / `stroke-opacity` individually on each child element |
| `<image opacity="0.3"/>` | Overlay a `<rect fill="BackgroundColor" opacity="0.7"/>` on top of the image |

### 6.3 Conditionally Allowed

| Feature | Condition | Conversion Result |
| :--- | :--- | :--- |
| `marker-start` / `marker-end` | `<marker>` is in `<defs>`, `orient="auto"`, shape is triangle/diamond/circle | DrawingML `<a:headEnd>` / `<a:tailEnd>` |
| `clipPath` on `<image>` | `<clipPath>` is in `<defs>`, single child element, **only applied to `<image>`** | DrawingML `<a:prstGeom>` / `<a:custGeom>` |
| `stroke-dasharray` | Use preset values: `4,4` / `2,2` / `8,4` / `8,4,2,4` | PPTX `<a:prstDash>` |
| `text-decoration` | `underline` / `line-through` | Native PPTX text formatting |
| `transform="rotate(...)"` | Supported across all element types | PPTX `<a:xfrm rot="...">` |

> See `shared-standards.md` §1.1 (marker constraints) and §1.2 (clipPath constraints) for full conditions.

### 6.4 Dashed Preset Contrast

| SVG Value | PPTX Preset | Purpose / Scenario |
| :--- | :--- | :--- |
| `4,4` | Dash | Generic dashed lines, splitters |
| `2,2` | Dot (sysDot) | Placeholders, thin borders |
| `8,4` | Long dash | Timeline connectors, process arrows |
| `8,4,2,4` | Long dash-dot | Technical layouts, dimension lines |

---

## 7. Legacy Color Mapping Reference Table

When updating old templates, use this table to quickly map old colors:

| Old Color (Material/Flat) | → | New Color (Tailwind) | Role |
| :--- | :--- | :--- | :--- |
| `#2C3E50` | → | `#0F172A` | Primary text |
| `#7F8C8D` | → | `#64748B` | Secondary text |
| `#5D6D7E` | → | `#475569` | Legend text |
| `#95A5A6` | → | `#94A3B8` | Data source text |
| `#BDC3C7` | → | `#CBD5E1` | Muted elements |
| `#2196F3` / `#1976D2` | → | `#3B82F6` / `#2563EB` | Blue series |
| `#4CAF50` / `#388E3C` | → | `#10B981` / `#059669` | Green series |
| `#FF9800` / `#F57C00` | → | `#F59E0B` / `#D97706` | Orange series |
| `#E91E63` | → | `#F43F5E` | Outliers |
| `#000000` (shadow) | → | `#0F172A` | Shadow base |

---

## 8. Placeholder Content Strategy

Since these SVG files are "templates" designed to be dynamically adapted by AI, their core value lies in demonstrating **graphic structure, typography limits, and visual spacing** rather than conveying actual business data. The placeholder texts should adhere to these principles:

### 8.0 English-Only Rule
**Mandatory Requirement**: All placeholder texts in the chart templates (including titles, subtitles, axis values, legends, data nodes, description details, and source footnotes) **must be written in English**.
- **Reason**: Ensures that downstream LLMs in the automation pipeline can parse structural content layout accurately, and because English words provide natural spatial boundaries to verify layout wrap logic.

### 8.1 Structure Boundary Demonstration
- **Show Maximum Width/Wrap Logic**: Intentionally use typical-length strings (two to three-word phrases, multi-line `tspan` nodes) to clearly show text boundaries. This ensures the AI has a reference to avoid overflow when populating the final template.
- **Show Data Formats**: Use formatted placeholder numbers (e.g. `$1,234.5M`, `98.5%`) rather than simple integers like `10` to verify symbol spacing and text width.

### 8.2 Generality & Neutrality
- Use generic and professional business placeholders; avoid hyper-specific or narrow business data unless the template has a strong industry theme.
- **Recommended**: `Category A`, `Q1 Revenue`, `Strategic Objective`, `Phase 01`.
- **Avoid**: Extremely specific, localized texts (e.g. "Vendor Sales Analysis for X Region in 2023").

### 8.3 Visual Balance
- Placeholder text should maintain the visual balance of the chart (e.g. equal left/right widths in a butterfly chart, staggered lengths in a list) to clearly illustrate the layout design intent.

---

## 9. Registering to `charts_index.json`

After adding a new SVG template, it **must** be registered in [charts_index.json](./charts_index.json); otherwise, the Strategist cannot select it.

### 9.1 Field Specifications

```json
"<key>": {
  "summary": "Pick for <content shape + scale>. Skip if <counter-example → alternative template>."
}
```

- **`key`**: The SVG filename minus the `.svg` suffix, in snake_case (e.g. `bullet_chart`).
- **`summary`**: A selection sentence, not a description. Use the syntax in `meta.summaryGrammar`: define when to select it, then use `Skip if ... (use <other_key>)` to redirect to confusing alternatives.
- **`meta.total`**: Increment by 1.

> **Do NOT include** `label`, `categories`, `quickLookup`, or `keywords` fields. The Strategist performs semantic matching directly on the summaries.

### 9.2 Examples

❌ Description only: `"summary": "Bidirectional comparison chart for two datasets"`
✅ Selection rule: `"summary": "Pick for two mirrored datasets sharing a common axis (age pyramid, A/B). Skip for >2 sides (use grouped_bar_chart)."`

❌ Overly long summary (>400 characters) — makes it harder to isolate selection rules. Aim for 150-300 characters.

---

## 10. Checklist

Check each of the following points after adding or modifying a chart:

### Basic Validation
- [ ] `xmllint --noout` passes without errors
- [ ] viewBox is set to `0 0 1280 720`
- [ ] The first element is a white background `<rect width="1280" height="720" fill="#FFFFFF"/>`

### Colors
- [ ] No legacy colors remain (verify via `grep`)
- [ ] Shadow `flood-color` is set to `#0F172A` with opacity ≤ 0.20
- [ ] Data sources use `#94A3B8`

### Typography
- [ ] No text element has `font-size < 12`
- [ ] All `<text>` content is wrapped in `<tspan>`
- [ ] Lines with mixed formats use inline `<tspan>` rather than separate `<text>` tags
- [ ] Inline `<tspan>` elements do not carry `x`, `y`, or `dy` attributes
- [ ] Titles are 34px, subtitles 18px, sources 14px

### Structure
- [ ] Major elements are grouped semantically via `<g id="...">`
- [ ] No `<style>`, `class`, `<foreignObject>`, `mask`, or `rgba()` declarations
- [ ] No `<g>` tag has an `opacity` attribute
- [ ] Text characters are raw Unicode (`—`, `©`, `→`, NBSP, etc.) without HTML named entities; raw `&`, `<`, and `>` are escaped as XML entities (`&amp;`, `&lt;`, `&gt;`)

### Shadows
- [ ] Uses the `feFlood` filter structure (not `feComponentTransfer`)
- [ ] Shadow directions (`dx`/`dy`) are uniform across the page
- [ ] No more than 3 shadow-cast elements per page

### Registration (New Templates Only)
- [ ] Entry added to `charts_index.json` under `charts.<key>` with a `summary` field
- [ ] `summary` is written as a selection rule (`Pick for ... Skip if ... (use <other>)`)
- [ ] `summary` length is kept between 150-300 characters (max 350 characters to cover key anchors)
- [ ] `meta.total` incremented by 1

### Coordinates Calibration (For calculator-supported charts)
- [ ] Rectangular coordinate charts (bar, line, scatter, waterfall, butterfly, etc.) contain `<!-- chart-plot-area: x_min,y_min,x_max,y_max -->`
- [ ] Polar coordinate charts (pie, donut, radar) contain `<!-- chart-plot-area: <type> | center: cx,cy | radius: r -->`
- [ ] Calibration marks are placed inside `<g id="chartArea">` after axes but before data elements
- [ ] Coordinates exactly match actual SVG coordinates

### Validation Commands
```bash
# Quick validation
f="your_chart.svg"
xmllint --noout "skills/ppt-master/templates/charts/$f" && echo "XML OK" || echo "XML FAIL"
echo "Old colors:" && grep -c '#2C3E50\|#7F8C8D\|#95A5A6\|#5D6D7E\|#000000' "skills/ppt-master/templates/charts/$f"
echo "Small fonts:" && grep -c 'font-size="[0-9]"' "skills/ppt-master/templates/charts/$f"
```

---

## 11. Card Container Patterns

Card containers are the most frequently reused visual units (KPI cards, section cards, info blocks). The following three patterns are verified, round-trip compatible implementations. New templates should follow these conventions:

### 11.1 Half-Rounded Section Tab

**Purpose**: Adds a colored "section tab" on top of a card to classify areas (S/W/O/T, Political/Economic, categories, etc.), offering a compact title label.

**Two Configurations** — select based on the tab's anchor position:

| Configuration | Shape | Visual Semantics | Typical Scenario |
| :--- | :--- | :--- | :--- |
| **Top Round, Bottom Square** | Top two corners rounded, bottom straight | Tab grows out of the card | Section headers, quadrant titles |
| **Top Square, Bottom Round** | Top corners straight, bottom rounded | Tab hangs down from the top divider | Chapter bookmarks, index markers |

> Both configurations require drawing the tab as **a single path with one set of rounded corners**. Do not use a fully rounded rect covered by a straight rect; they split during PPTX round-tripping.

**Implementation 1: Top Round, Bottom Square (Default)**

```xml
<!-- Formula: Width W, Height H, Radius R, Top-Left Origin (x, y) -->
<path d="M {x+R} {y} h {W-2R} a {R} {R} 0 0 1 {R} {R} v {H-R} h -{W} v -{H-R} a {R} {R} 0 0 1 {R} -{R} Z"
      fill="#2563EB"/>

<!-- Example: 240x50, r=25, Origin (245, 140) -->
<path d="M 245 140 h 190 a 25 25 0 0 1 25 25 v 25 h -240 v -25 a 25 25 0 0 1 25 -25 Z" fill="#2563EB"/>
```

**Implementation 2: Top Square, Bottom Round (Hanging Tag)**

```xml
<!-- Formula: Width W, Height H, Radius R, Top-Left Origin (x, y) -->
<path d="M {x} {y} h {W} v {H-R} a {R} {R} 0 0 1 -{R} {R} h -{W-2R} a {R} {R} 0 0 1 -{R} -{R} Z"
      fill="#2563EB"/>

<!-- Example: 240x50, r=25, Origin (245, 140) -->
<path d="M 245 140 h 240 v 25 a 25 25 0 0 1 -25 25 h -190 a 25 25 0 0 1 -25 -25 Z" fill="#2563EB"/>
```

**Banned Hack**:

```xml
<!-- ❌ Banned: Fully rounded rect covered by a straight rect -->
<rect width="260" height="120" rx="12" fill="#EFF6FF"/>
<rect y="100" width="260" height="20" fill="#EFF6FF"/>
```

### 11.2 Nested Card Border

**Purpose**: Gives the card a layered border effect while avoiding high-contrast stroke styles.

**Approach**: Overlay a smaller white card inside a slightly larger light-gray card, leaving an 8-20px margin to act as the border.

```xml
<!-- Outer border layer -->
<rect x="60" y="140" width="560" height="255" rx="20" fill="#F1F5F9"/>
<!-- Inner white card (inset by 20px, smaller radius) -->
<rect x="80" y="210" width="520" height="165" rx="12" fill="#FFFFFF"/>
```

### 11.3 Card Grid as Page Skeleton

**Purpose**: For pages with parallel sections, lay them out in a grid.

**Grid Dimension Guidelines** (1280x720 Canvas):

| Grid | Single Card (W × H) | Gap | Starting Coordinates (x, y) |
| :--- | :--- | :--- | :--- |
| 2×2 | 560 × 255 | 40 | (60, 140), (660, 140), (60, 420), (660, 420) |
| 2×3 (landscape) | 370 × 260 | 25 | (50, 130), row gap 290 |
| 1×3 (portrait card) | 400 × 540 | 30 | (60, 130), column gap 430 |
| 1×4 (metrics header) | 280 × 250 | 20 | (60, 150), column gap 300 |

### 11.5 Diagonal Dashed Connector

**Purpose**: Connects diagonal relationships across quadrants or layers (migrations, influences, reporting). Horizontal/vertical arrows show progress; diagonal dashed connectors guide relations.

**Approach**: A single `<line>` + `stroke-dasharray="6 5"` + `marker-end`. Define a specific marker (e.g. Slate 600 `#475569`) to distinguish from primary progress arrows.

```xml
<defs>
  <marker id="migrationArrow" markerWidth="12" markerHeight="12"
          refX="10" refY="6" orient="auto" markerUnits="strokeWidth">
    <path d="M 0,0 L 10,6 L 0,12 Z" fill="#475569"/>
  </marker>
</defs>

<!-- Diagonal dashed connector from bottom-right (Q4) to top-left (Q2) -->
<line x1="850" y1="605" x2="385" y2="200"
      stroke="#475569" stroke-width="2"
      stroke-dasharray="6 5" stroke-linecap="round"
      marker-end="url(#migrationArrow)"/>

<!-- Mid-line label block -->
<rect x="525" y="385" width="190" height="28" rx="14"
      fill="#FFFFFF" stroke="#CBD5E1" stroke-width="1"/>
<text x="620" y="403" text-anchor="middle" font-size="12"
      font-weight="700" fill="#475569" letter-spacing="1">PRIORITY MIGRATION</text>
```

> **Requirement**: Diagonal connectors must have a center label (e.g. mid-line block) to define the relationship.

### 11.6 Ground Anchor Ellipse — Non-Filter Depth

**Purpose**: Gives floating elements (avatars, icons, badges) a grounded shadow depth without using expensive `<filter>` components.

**Benefits**: Matches native PPTX shapes, edits easily, and conforms to shadow budget constraints.

**Approach**: Draw a very flat ellipse (`ry << rx`) under the element using Slate 900 or the primary color with low opacity:

```xml
<!-- Shadow anchor (drawn first, cy is 10-15px below element bottom) -->
<ellipse cx="80" cy="172" rx="70" ry="5" fill="#0F172A" opacity="0.10"/>
<!-- Floating element body -->
<circle cx="80" cy="80" r="80" fill="#E2E8F0"/>
```

**Parameters Reference**:

| Element Radius | Ellipse rx | Ellipse ry | Opacity |
| :--- | :--- | :--- | :--- |
| 30-50 px | r × 0.85 | 3-4 | 0.10-0.15 |
| 50-100 px | r × 0.85 | 5-6 | 0.10-0.12 |
| 100+ px | r × 0.85 | 7-9 | 0.08-0.10 |

### 11.7 Bidirectional Interaction Arrows

**Purpose**: Illustrates paired request/response, pull/push, up/down relationships.

**Approach**: Two parallel `<line>` elements with opposite directions, using distinct colors and containing text labels:

```xml
<defs>
  <marker id="reqArrow" markerWidth="10" markerHeight="10" refX="9" refY="5"
          orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L10,5 L0,10 Z" fill="#3B82F6"/>
  </marker>
</defs>

<!-- Request: Left-to-right (Blue) -->
<line x1="380" y1="250" x2="926" y2="250" stroke="#3B82F6" stroke-width="2.5"
      marker-end="url(#reqArrow)"/>
<rect x="500" y="216" width="280" height="26" rx="11" fill="#FFFFFF"
      stroke="#3B82F6" stroke-width="1"/>
<text x="640" y="234" text-anchor="middle" font-size="14" font-weight="700"
      fill="#3B82F6">① Login Request · POST /auth/login</text>
```

---

### 11.8 Reference Implementations

| Pattern | Reference Template |
| :--- | :--- |
| §11.1 Section Tab | `quadrant_text_bullets.svg`, `labeled_card.svg`, `vertical_pillars.svg`, `comparison_columns.svg` |
| §11.2 Nested Card | `labeled_card.svg` |
| §11.3 2×2 Card Grid | `kpi_cards.svg`, `quadrant_text_bullets.svg`, `labeled_card.svg` |
| §11.3 2×3 Card Grid | `icon_grid.svg` |
| §11.3 1×3 / 1×4 Card Grid | `comparison_columns.svg`, `vertical_pillars.svg` |
| §11.5 Diagonal Connector | `matrix_2x2.svg` |
| §11.6 Anchor Ellipse | `team_roster.svg` |
| §11.7 Bidirectional Arrows | `client_server_flow.svg` |
