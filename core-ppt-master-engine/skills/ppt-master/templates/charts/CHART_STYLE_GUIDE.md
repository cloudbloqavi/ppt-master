# Chart SVG Style Guide

> This document defines the visual specifications for the **stock** SVG chart templates under `templates/charts/`.
> When adding or modifying these charts, the following standards **must** be adhered to to ensure visual consistency across the stock library.
>
> **Exemption:** the company catalog in [`powerslides_infographics/`](./powerslides_infographics/) carries its own visual specifications and does **not** follow this guide — see [`powerslides_infographics/STYLE_GUIDE.md`](./powerslides_infographics/STYLE_GUIDE.md). When recreating a matched company infographic, preserve its source styling.

## 0. Upstream Specification Reference

This document is an aesthetic and implementation specification **dedicated to chart templates**. All charts must also comply with project-level general technical constraints:

> **[`references/shared-standards.md`](../../references/shared-standards.md)** — SVG disabled features blacklist, PPT compatibility alternatives, Canvas format, tspan inline rules, grouping specifications, shadow/overlay techniques, post-processing pipeline

The following sections excerpt the most relevant items from shared-standards for chart templates. For complete details (e.g., marker conditional constraints, clipPath conditional constraints, arc path calculation formulas, etc.), please refer to the upstream document.

---

## 1. Color System (Tailwind CSS Palette)

### 1.1 Text Colors

| Purpose | Color Value | Tailwind Token | Example |
|------|------|----------------|------|
| **Main Title** | `#0F172A` | Slate 900 | Chart Main Title |
| **Value Label** | `#0F172A` | Slate 900 | Bar Top Value, Key Metrics |
| **Subtitle** | `#64748B` | Slate 500 | Date, Unit Description |
| **Axis Label** | `#64748B` | Slate 500 | X/Y Axis Tick Values |
| **Axis Title / Legend** | `#475569` | Slate 600 | "Annual Salary (10k RMB)", Legend Text |
| **Data Source** | `#94A3B8` | Slate 400 | Source Description at Page Bottom |
| **Footnote / Faded Hint** | `#CBD5E1` | Slate 300 | "Adjustable at each stage" |

### 1.2 Theme Colors (Data Series)

| Color Name | Main Color | Dark Color (Gradient End) | Purpose |
|------|------|------------------|------|
| **Blue** | `#3B82F6` | `#2563EB` | 1st Series (Default Preferred) |
| **Emerald** | `#10B981` | `#059669` | 2nd Series |
| **Amber** | `#F59E0B` | `#D97706` | 3rd Series |
| **Violet** | `#8B5CF6` | `#7C3AED` | 4th Series |
| **Rose** | `#FB7185` | `#E11D48` | 5th Series / Warning |
| **Pink** | `#EC4899` | `#BE185D` | Comparison Group (e.g., Butterfly Chart Female) |

> Radial gradients (e.g., bubble charts) use lighter variants: `#60A5FA`, `#34D399`, `#FBBF24`, `#A78BFA`, `#FB7185`

### 1.3 Semantic Colors

| Purpose | Color Value | Description |
|------|------|------|
| Achieved / Positive | `#10B981` | Emerald 500 |
| Warning / Neutral | `#F59E0B` | Amber 500 |
| Not Achieved / Negative | `#EF4444` | Red 500 |
| Outlier Annotation | `#F43F5E` | Rose 500 |

### 1.4 UI Auxiliary Colors

| Purpose | Color Value | Description |
|------|------|------|
| **Axis Line** | `#94A3B8` | Slate 400, stroke-width="2" |
| **Grid Line** | `#E2E8F0` or `#E0E0E0` | stroke-dasharray="4,4" |
| **Center Divider Line** | `#CBD5E1` | e.g., Quadrant Crosshairs |
| **Card Background** | `#F8FAFC` / `#F8F9FA` | Slate 50 |
| **Card Stroke** | `#E2E8F0` | Slate 200 |
| **Row Divider Line** | `#F1F5F9` | Slate 100 (Very Light) |
| **Tint Background** (Blue) | `#EFF6FF` | Blue 50 |
| **Tint Background** (Green) | `#ECFDF5` | Emerald 50 |
| **Tint Background** (Red) | `#FFF1F2` | Rose 50 |
| **Tint Background** (Yellow) | `#FFFBEB` | Amber 50 |

---

## 2. Typography Guidelines

### 2.1 Font Stack

```
font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
```

- For purely English scenarios, `'PingFang SC', 'Microsoft YaHei'` can be omitted.
- **Forbidden** to use `@font-face`, external fonts, or `<style>` tags.

### 2.2 Font Size Hierarchy

| Level | Font Size | font-weight | Purpose |
|------|------|-------------|------|
| H1 | `34px` | `bold` (700) | Chart Main Title |
| H2 | `22px` | `600` | Section Title (e.g., "Detailed Data") |
| Body L | `18-20px` | `600` | Key Values, Percentages |
| Body M | `15-16px` | `600` | Data Labels, Category Names |
| Body S | `14px` | Normal | Subtitle, Legend, Source |
| Caption | `12-13px` | Normal | Axis Ticks, Annotations |

> **Minimum Font Size: 12px**. All text must not be smaller than 12px.

### 2.3 tspan Specification

The text content of all `<text>` elements **must** be wrapped in `<tspan>`:

```xml
<!-- Correct -->
<text x="60" y="80" font-size="34" fill="#0F172A">
    <tspan>Chart Title</tspan>
</text>

<!-- Incorrect -->
<text x="60" y="80" font-size="34" fill="#0F172A">Chart Title</text>
```

### 2.4 Inline Formatting Rules (shared-standards SS4)

**Single logical line = single `<text>`**. When multiple colors/weights are needed within the same line, use inline `<tspan>`, **do not** use multiple side-by-side `<text>`:

```xml
<!-- Correct: One text frame, three runs -->
<text x="100" y="200" font-size="24" fill="#333333">
  Achieve<tspan fill="#3B82F6" font-weight="bold">10x</tspan>efficiency improvement
</text>

<!-- Incorrect: Three independent text frames, cannot be edited as one line in PPT -->
<text x="100" y="200">Achieve</text>
<text x="160" y="200" fill="#3B82F6">10x</text>
<text x="240" y="200">efficiency improvement</text>
```

> Inline tspan **must not** carry `x` / `y` / `dy`, otherwise post-processing will split it into independent text frames. `dx` can be used for fine-tuning letter spacing.

### 2.5 Data Highlight Default Behavior

Key data text in charts should be highlighted by default:
- **Numerical Results** — Percentages, multiples, amounts → `<tspan fill="theme color" font-weight="bold">`
- **Comparison Items** — Increase/decrease, achieved/not achieved → Semantic color (green/red)
- **Not Highlighted** — Conjunctions, common verbs, structural text (axis labels, legends, page numbers)

---

## 3. Shadow Filter

`<filter>` itself is allowed and is the officially recommended path for PPT shadows/glows (see "Forbidden List" at the end of this section for details). This section unifies the shadow primitive syntax—use the `feFlood` scheme, **forbid** the use of `<feComponentTransfer>` inside `<filter>`:

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
|------|-------------|-----|---------------|
| Heavy Elements (arrows, cards) | 4-6 | 2-4 | 0.12-0.15 |
| Medium Elements (bars, boxes) | 2-3 | 1-2 | 0.10-0.15 |
| Light Elements (bottom cards) | 4-6 | 2-4 | 0.06-0.08 |

### Forbidden List

- `flood-color="#000000"` → Must use `#0F172A`
- `<feComponentTransfer>` + `<feFuncA slope=...>` → Use `<feFlood flood-color flood-opacity>` instead
- `flood-opacity > 0.20` → Shadow too heavy, max 0.15-0.20

> **What is forbidden is the sub-element, not `<filter>` itself.** `<filter>` is allowed by Presentation Builder and is the officially recommended path for shadows/glows (see [`shared-standards.md`](../../references/shared-standards.md) §1 blacklist does not include filter, §6 lists filter shadow as the official implementation of drop-shadow). The converter [`svg_to_pptx/drawingml_styles.py`](../../scripts/svg_to_pptx/drawingml_styles.py) also actively maps `feGaussianBlur` + `feOffset` + `feFlood` + `feComposite` + `feMerge` (and `feDropShadow` shorthand) to DrawingML `<a:outerShdw>`.
>
> The reason for specifically forbidding `feComponentTransfer/feFuncA(slope)`: **it can physically only adjust transparency, not carry color**. When the converter reads `feFuncA slope`, it treats it only as alpha, and the color field remains the default `'000000'`—the shadow color appears normal on the SVG side (because SourceAlpha itself is black), but after exporting to PPTX, the shadow color will be fixed to pure black `#000000`, creating a visually noticeable warm/cool color difference compared to other cards on the same page using `feFlood flood-color="#0F172A"`.
>
> In short: **Using filters is fine, but the primitive must be able to explicitly express "color"; primitives that can only express "transparency" are forbidden.**

### Shadow Usage Principles (shared-standards SS6)

> **Shadows are an aesthetic component, not a default treatment.** Restraint rather than abundance creates a "designed" feel. "Shadows are perceived, not seen" is a high-end aesthetic standard.

**Should add shadows**: Cards floating above photos/colored panels, the sole main CTA, overlays (tooltip, callout)

**Should not add shadows**: Background panels/dividers, peer cards in a grid, containers with existing strokes/gradients, body text paragraph containers, decorative lines/icons, on dark backgrounds (black shadows are invisible)

**Per-page budget**: A maximum of 2-3 elements with shadows. If a 4th shadow is needed, first remove an existing one.

**Unified light source**: The `dx`/`dy` direction of all `feOffset` on the same page must be consistent (default `dx=0, dy=positive value`, light comes from above).

**Two-level height limit**:

| Level | Scenario | dy | stdDeviation | flood-opacity |
|------|------|----|--------------|---------------|
| Ground (no shadow) | Background, peer grid cards, dividers, body text containers | — | — | — |
| Static | Cards on photos/panels, secondary callouts | 2-4 | 4-8 | 0.06-0.10 |
| Elevated | Main CTA, focus/recommended cards, overlays | 6-10 | 10-16 | 0.12-0.20 |

**Do not stack**: Shadow + stroke + rounded corners + gradient fill all at once = template feel. A container's "look at me" budget is small, choose one.

---

## 4. Gradient Specification

### 4.1 Linear Gradient (Bar/Column Charts)

```xml
<linearGradient id="barGrad1" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" style="stop-color:#3B82F6;stop-opacity:1" />
    <stop offset="100%" style="stop-color:#2563EB;stop-opacity:1" />
</linearGradient>
```

- Direction: From light to dark (top to bottom or left to right)
- Each gradient ID should be semantic: `barGrad1`, `leftGrad`, `actualBarBlue`

### 4.2 Radial Gradient (Bubble Charts)

```xml
<radialGradient id="bubbleGrad1" cx="30%" cy="30%">
    <stop offset="0%" style="stop-color:#60A5FA;stop-opacity:0.9" />
    <stop offset="100%" style="stop-color:#2563EB;stop-opacity:0.7" />
</radialGradient>
```

- Highlight biased towards top-left (`cx="30%" cy="30%"`)
- Edge opacity reduced to 0.7 to create a sense of transparency

---

## 5. Structure Specification

### 5.1 Hierarchical Grouping (shared-standards SS4 Grouping)

Use `<g id="...">` for semantic grouping, facilitating individual operations/animations in PPT:

```xml
<g id="chartArea">        <!-- Chart Body -->
    <g id="bar-1">...</g>  <!-- Each data element grouped independently -->
    <g id="bar-2">...</g>
</g>
<g id="legend">            <!-- Legend Area -->
    <g id="legend-high">...</g>
</g>
<g id="detailList">        <!-- Detail Panel -->
    <g id="list-items">
        <g id="item-1">...</g>
    </g>
</g>
```

**Grouping Unit Reference** (from shared-standards):

| Grouping Unit | Contents |
|---------|---------|
| Card/Panel | Background rect + shadow (if applicable) + icon + title + body text |
| Process Step | Numbered circle + icon + label + description |
| List Item | Bullet/Number + icon + title + description |
| Icon-Text Combination | Icon element + adjacent label |
| Page Header | Title + subtitle + decoration |
| Decorative Cluster | Related decorative shapes (rings, spheres, dots) |

**Naming Convention**: Use descriptive `id`s (e.g., `card-1`, `step-discover`, `header`, `footer`).

> Only `<g opacity="...">` is forbidden (see SS2). Pure structural `<g>` is required.

### 5.2 viewBox

Fixed at `0 0 1280 720` (PPT 16:9), cannot be modified.

### 5.3 Background

The first line is always a white full-screen background:
```xml
<rect width="1280" height="720" fill="#FFFFFF"/>
```

### 5.4 Data Source

Located at the bottom of the page, fixed format:
```xml
<text x="60" y="695" font-family="..." font-size="14" fill="#94A3B8">
    <tspan>Data Source: XXX</tspan>
</text>
```

---

## 6. SVG Forbidden Features and Compatibility (shared-standards SS1-2)

### 6.1 Absolutely Forbidden

| Forbidden Feature | Alternative |
|---------|---------|
| HTML Named Entities (`&nbsp;` `&mdash;` `&copy;` `&ndash;` `&reg;` `&hellip;` `&bull;` …) | Directly write native Unicode characters (`—` `–` `©` `®` `→` NBSP …) |
| Bare `& < > " '` in text/attribute values | Must be written as XML entities `&amp;` `&lt;` `&gt;` `&quot;` `&apos;` |
| `<style>` / `class` | Inline attributes (`id` is valid within `<defs>`) |
| `<foreignObject>` | `<text>` + `<tspan>` |
| `mask` | Overlay mask rectangle / gradient overlay |
| `<symbol>` + `<use>` | Write out the full element directly |
| `textPath` | Manually arrange `<text>` |
| `@font-face` | System font stack |
| `<animate*>` / `<set>` | None (PPT handles animation) |
| `<script>` / event attributes | None |
| `<iframe>` | None |

### 6.2 PPT Compatibility Alternatives

| Forbidden Syntax | Correct Alternative |
|---------|----------|
| `fill="rgba(255,255,255,0.1)"` | `fill="#FFFFFF" fill-opacity="0.1"` |
| `<g opacity="0.2">...</g>` | Set `fill-opacity` / `stroke-opacity` individually on each child element |
| `<image opacity="0.3"/>` | Overlay `<rect fill="background color" opacity="0.7"/>` after the image |

### 6.3 Conditionally Allowed

| Feature | Condition | Conversion Result |
|------|------|----------|
| `marker-start` / `marker-end` | `<marker>` in `<defs>`, `orient="auto"`, shape is triangle/diamond/circle | DrawingML `<a:headEnd>` / `<a:tailEnd>` |
| `clipPath` on `<image>` | `<clipPath>` in `<defs>`, single child element, **only for images** | DrawingML `<a:prstGeom>` / `<a:custGeom>` |
| `stroke-dasharray` | Use preset values `4,4` / `2,2` / `8,4` / `8,4,2,4` | PPTX `<a:prstDash>` |
| `text-decoration` | `underline` / `line-through` | PPTX native text formatting |
| `transform="rotate(...)"` | Supported by all element types | PPTX `<a:xfrm rot="...">` |

> For complete conditional constraints, see [`shared-standards.md`](../../references/shared-standards.md) SS1.1 (marker constraints) and SS1.2 (clipPath constraints).

### 6.4 Dashed Line Preset Comparison

| SVG Value | PPTX Preset | Applicable Scenario |
|--------|-----------|---------|
| `4,4` | Dash | General dashed line, divider line |
| `2,2` | Dot (sysDot) | Placeholder outline, thin border |
| `8,4` | Long dash | Timeline connection, process arrow |
| `8,4,2,4` | Long dash-dot | Technical drawings, dimension lines |

---

## 7. Old Color Mapping Quick Reference

When maintaining old templates, use the following mapping for quick replacement:

| Old Color (Material/Flat) | → | New Color (Tailwind) | Role |
|----------------------|---|-----------------|------|
| `#2C3E50` | → | `#0F172A` | Main Text |
| `#7F8C8D` | → | `#64748B` | Secondary Text |
| `#5D6D7E` | → | `#475569` | Legend Text |
| `#95A5A6` | → | `#94A3B8` | Data Source |
| `#BDC3C7` | → | `#CBD5E1` | Faded Elements |
| `#2196F3` / `#1976D2` | → | `#3B82F6` / `#2563EB` | Blue Series |
| `#4CAF50` / `#388E3C` | → | `#10B981` / `#059669` | Green Series |
| `#FF9800` / `#F57C00` | → | `#F59E0B` / `#D97706` | Orange Series |
| `#E91E63` | → | `#F43F5E` | Outlier |
| `#000000` (shadow) | → | `#0F172A` | Shadow Base Color |

---

## 8. Placeholder Content Strategy

Since these SVG files are "templates" for subsequent AI calls, their core value lies in demonstrating **graphic structure, layout constraints, and visual space**, rather than conveying real business data. Therefore, the text content written into the templates should follow the following "placeholder principles":

### 8.0 English-Only Rule

**Mandatory Requirement**: All placeholder text in chart templates (including titles, subtitles, axes, legends, data nodes, detailed descriptions, and bottom source descriptions) **must be written entirely in English**.
- **Purpose**: To ensure that the LLM in the subsequent automated pipeline can perform semantic understanding and structured content mapping more accurately, and at the same time, the natural length characteristics of English words make it easier to demonstrate line-breaking logic and spatial boundaries in the template during layout.

### 8.1 Structural Boundary Demonstration

- **Show maximum width/line-breaking logic**: Deliberately use strings of typical length (e.g., two or three-word phrases, multi-line `tspan`) to clearly demonstrate the boundaries of text boxes. This ensures that AI has an intuitive reference when filling in real text, preventing overflow.
- **Show data format**: Use placeholder numerical values that reflect complete format characteristics (e.g., `$1,234.5M`, `98.5%`) rather than just simple `10`, to verify whether symbols and character widths are adapted.

### 8.2 Generality and Neutrality

- Use generic, professional business placeholders, avoiding overly vertical or concrete specific business data (unless the template itself has strong industry attributes).
- **Recommended practice**: Use `Category A`, `Q1 Revenue`, `Strategic Objective`, `Phase 01`.
- **Avoid practice**: Using specific, lengthy real-world data (e.g., "Analysis of a certain brand's special equipment sales in 2023").

### 8.3 Visual Balance

- Placeholder text should visually maintain the balance of the chart (e.g., the left and right text lengths of a butterfly chart should be roughly equal, and list text should vary in length), so that the layout design intent of the chart can be seen at a glance.

---

## 9. Register to charts_index.json

After adding a new SVG template, it **must** be registered in [`charts_index.json`](./charts_index.json), otherwise Strategist will not discover it during selection.

### 9.1 Field Specification

```json
"<key>": {
  "summary": "Pick for <content form + scale>. Skip if <counter-example → alternative template>."
}
```

- **`key`** = SVG filename without `.svg`, lowercase with underscores (e.g., `bullet_chart`)
- **`summary`** is a **selection sentence**, not a descriptive sentence. See `meta.summaryGrammar` for syntax: first state when to pick it, then use `Skip if ... (use <other_key>)` to point to the most easily confused sibling template.
- **`meta.total`** increments by +1 synchronously.

> **No need for** `label` / `categories` / `quickLookup` / `keywords` — these have been removed. Strategist reads the entire summary list and performs semantic matching, without relying on any pre-calculated index. **Note**: The summary is in English, but source documents often contain Chinese/industry terms ("Middle Platform", "Architecture Diagram", "Pipeline"). Strategist is responsible for semantic translation and matching. If a template's hit strongly depends on a certain Chinese phrase, write its English equivalent into the summary's Pick clause.

### 9.2 Counter-examples

❌ Only write "what it is": `"summary": "Bidirectional comparison chart for two datasets"`
✅ Write "when to pick": `"summary": "Pick for two mirrored datasets sharing a common axis (age pyramid, A/B). Skip for >2 sides (use grouped_bar_chart)."`

❌ Summary too long (>400 characters) — makes it harder to grasp the main point during selection, target is 150-300 characters.

> **Why not stricter**: A single structural template often needs to cover multiple business frameworks/scenarios (e.g., `quadrant_text_bullets` covers SWOT + Ansoff, `top_down_tree` covers org + OKR). The summary needs to list keyword anchors (like "principles, key takeaways, action items") to allow Strategist to semantically hit "non-numeric structural pages", so the old baseline of 100-180 characters is already too tight after structural-based naming.

---

## 10. Checklist

After adding or modifying a chart, check each item:

### Basic Validation
- [ ] `xmllint --noout` passes
- [ ] viewBox is `0 0 1280 720`
- [ ] First line is white background `<rect width="1280" height="720" fill="#FFFFFF"/>`

### Colors
- [ ] No old color residue (`grep` verification, see command below)
- [ ] Shadow `flood-color` is `#0F172A`, opacity less than or equal to 0.20
- [ ] Data source uses `#94A3B8`

### Typography
- [ ] No text with `font-size < 12`
- [ ] All `<text>` content wrapped in `<tspan>`
- [ ] Multiple formats on the same line use inline `<tspan>`, **not** multiple side-by-side `<text>`
- [ ] Inline `<tspan>` does not carry `x` / `y` / `dy`
- [ ] Title 34px, subtitle 18px, source 14px

### Structure
- [ ] Main elements have semantic `<g id="...">`
- [ ] No `<style>`, `class`, `<foreignObject>`, `mask`, `rgba()`
- [ ] `<g>` tags have no `opacity` attribute
- [ ] Text characters are native Unicode (`—` `©` `→` NBSP, etc.), no HTML named entities (`&nbsp;` `&mdash;` `&copy;`, etc.); bare `& < >` are escaped as `&amp; &lt; &gt;`

### Shadows
- [ ] Uses `feFlood` scheme (not `feComponentTransfer`)
- [ ] `dx`/`dy` direction of shadows on the same page is consistent
- [ ] No more than 3 shadowed elements per page

### Registration (for new templates only)
- [ ] `charts.<key>` in `charts_index.json` has `summary` field registered
- [ ] `summary` is written as a selection sentence (`Pick for ... Skip if ... (use <other>)`), not a descriptive sentence
- [ ] `summary` length controlled to 150-300 characters (rewrite if >400 characters); if the template covers multiple business frameworks/scenarios, it can be relaxed to 350 characters to fit keyword anchors
- [ ] `meta.total` increments by +1 synchronously

### Coordinate Calibration Markers (mandatory for calculator-supported charts)
- [ ] Rectangular coordinate charts (bar / horizontal_bar / grouped_bar / stacked_bar / line / area / stacked_area / scatter / waterfall / pareto / butterfly) include `<!-- chart-plot-area: x_min,y_min,x_max,y_max -->` marker
- [ ] Pie / donut / radar charts include `<!-- chart-plot-area: <type> | center: cx,cy | radius: r -->` marker
- [ ] Marker is located within `<g id="chartArea">`, after the axes, before data elements
- [ ] Coordinate values are consistent with the actual SVG coordinates of the axes

### Verification Commands
```bash
# One-click verification
f="your_chart.svg"
xmllint --noout "skills/ppt-master/templates/charts/$f" && echo "XML OK" || echo "XML FAIL"
echo "Old colors:" && grep -c '#2C3E50\|#7F8C8D\|#95A5A6\|#5D6D7E\|#000000' "skills/ppt-master/templates/charts/$f"
echo "Small fonts:" && grep -c 'font-size="[0-9]"' "skills/ppt-master/templates/charts/$f"
```

---

## 11. Card Container Patterns

Container cards are the most frequently reused visual units in Presentation Builder (KPI cards, section cards, info cards). The following three patterns are verified "reference implementations" compatible with PPTX round-tripping. New templates should prioritize adopting them, rather than inventing equivalent but poorly implemented alternatives.

### 11.1 Half-Rounded Section Tab

**Purpose**: To add a colored "tab header" to a card or block, identifying its category (S/W/O/T, Political/Economic, self-introduction/awards, etc.). It's easier to recognize than a plain text title and more compact than a separate label bar.

**Two Forms** — choose based on whether the tab's "visual anchor" is at the top or bottom:

| Form | Shape | Visual Semantics | Typical Scenarios |
|------|------|---------|---------|
| **Rounded Top, Straight Bottom** (Rounded Top Corners) | Top two corners rounded, bottom two corners straight | Label "growing out" of the card | Section card header, quadrant title, info card category |
| **Straight Top, Rounded Bottom** (Rounded Bottom Corners) | Top two corners straight, bottom two corners rounded | Hanging tag "suspended" from page header/section bar | Section anchor, page header divider extension, table of contents jump marker |

> Common requirement for both forms: **Only round one pair of corners**, draw the entire path directly. Do not use the hack of "fully rounded rectangle + same-color rectangle covering the bottom/top" (this will become two independent objects when round-tripped to PPTX, and colors can easily decouple during editing).

**Implementation One: Rounded Top, Straight Bottom (Default)**

```xml
<!-- Template: Width W, Height H, Corner Radius R, Top-left origin (x, y) -->
<path d="M {x+R} {y} h {W-2R} a {R} {R} 0 0 1 {R} {R} v {H-R} h -{W} v -{H-R} a {R} {R} 0 0 1 {R} -{R} Z"
      fill="#2563EB"/>

<!-- Example: 240×50, r=25, Origin (245, 140) -->
<path d="M 245 140 h 190 a 25 25 0 0 1 25 25 v 25 h -240 v -25 a 25 25 0 0 1 25 -25 Z" fill="#2563EB"/>
```

**Implementation Two: Straight Top, Rounded Bottom (Hanging Tag)**

```xml
<!-- Template: Width W, Height H, Corner Radius R, Top-left origin (x, y) -->
<path d="M {x} {y} h {W} v {H-R} a {R} {R} 0 0 1 -{R} {R} h -{W-2R} a {R} {R} 0 0 1 -{R} -{R} Z"
      fill="#2563EB"/>

<!-- Example: 240×50, r=25, Origin (245, 140) -->
<path d="M 245 140 h 240 v 25 a 25 25 0 0 1 -25 25 h -190 a 25 25 0 0 1 -25 -25 Z" fill="#2563EB"/>
```

**Forbidden Counter-example** (common in old PEST/SWOT/comparison_columns implementations):

```xml
<!-- ❌ Do not write like this: Use a fully rounded rectangle + a white rectangle to cover one rounded corner -->
<rect width="260" height="120" rx="12" fill="#EFF6FF"/>
<rect y="100" width="260" height="20" fill="#EFF6FF"/>
```

The bottom covering rectangle will become an independent rectangle object tied to the header color during SVG→PPTX round-tripping. When editing the header color in PPT, it's easy to miss changing it, leading to a visual "giveaway".

### 11.2 Nested Card Border

**Purpose**: To give cards a layered "bordered" feel, but avoid `stroke`. `stroke` is often rendered as thin layered lines in PPTX and can create a templated look when combined with shadows.

**Method**: An outer light gray rounded rect + an inner white slightly smaller rounded rect. Leaving an 8–20px gap between the two layers creates a "border" effect.

```xml
<!-- Outer "border" layer -->
<rect x="60" y="140" width="560" height="255" rx="20" fill="#F1F5F9"/>
<!-- Inner white content card (inset 20px, smaller radius) -->
<rect x="80" y="210" width="520" height="165" rx="12" fill="#FFFFFF"/>
```

**Applicable Conditions**:
- When the card also has a section header from §11.1 above it, the outer frame acts as the "backplate" for the header.
- Only **one type** of border expression should be used on the same page: outer frame OR stroke OR shadow, do not use them simultaneously (see §3 Shadow Usage Principles).

### 11.3 Card Grid as Page Skeleton

**Purpose**: When a page needs to display 4 equal aspects (pillar / aspect / quadrant) side-by-side, prioritize a 2×2 grid over vertical stacking.

**Recommended Grid Sizes** (1280×720 canvas):

| Grid | Single Card W × H | Spacing | Origin (x, y) |
|------|-------------|------|-------------|
| 2×2 | 560 × 255 | 40 | (60, 140) (660, 140) (60, 420) (660, 420) |
| 2×3 (Horizontal) | 370 × 260 | 25 | (50, 130) Row spacing 290 |
| 1×3 (Long Horizontal) | 400 × 540 | 30 | (60, 130) Column spacing 430 |
| 1×4 (Top) | 280 × 250 | 20 | (60, 150) Column spacing 300 |

**Determination**: "4 parallel aspects" → 2×2; "3 parallel aspects" → 1×3; "6 capability points" → 2×3; "4 key metrics" → 1×4. Pages marked `page_rhythm` as `breathing` **should not** use card grids (see executor-base.md §2.1).

### 11.5 Diagonal Dashed Connector

**Purpose**: To express "cross-quadrant/cross-level" relationships — priority migration, influence transmission, dotted line reporting, diagonal trends. Horizontal/vertical arrows express "process progress", while diagonal dashed arrows express "relationship or directional guidance"; their semantics are different.

**Method**: A single `<line>` + `stroke-dasharray="6 5"` + `marker-end`. A separate marker needs to be defined for this line (do not reuse the arrow color of the main flowchart, Slate 600 `#475569` is recommended to express a "suggestive, non-mandatory" tone).

```xml
<defs>
  <marker id="migrationArrow" markerWidth="12" markerHeight="12"
          refX="10" refY="6" orient="auto" markerUnits="strokeWidth">
    <path d="M 0,0 L 10,6 L 0,12 Z" fill="#475569"/>
  </marker>
</defs>

<!-- Priority migration arrow from Q4 (bottom right) to Q2 (top left) -->
<line x1="850" y1="605" x2="385" y2="200"
      stroke="#475569" stroke-width="2"
      stroke-dasharray="6 5" stroke-linecap="round"
      marker-end="url(#migrationArrow)"/>

<!-- Mid-segment label: White capsule over the arrow to avoid visual clutter -->
<rect x="525" y="385" width="190" height="28" rx="14"
      fill="#FFFFFF" stroke="#CBD5E1" stroke-width="1"/>
<text x="620" y="403" text-anchor="middle" font-size="12"
      font-weight="700" fill="#475569" letter-spacing="1">PRIORITY MIGRATION</text>
```

> **Pairing Requirement**: Each diagonal dashed arrow must be accompanied by a mid-segment label (small capsule or a line of text), otherwise readers will be confused about "what this line is saying". Unlabeled arrows are only allowed in horizontal/vertical flows (e.g., `process_flow`).

### 11.6 Ground Anchor Ellipse — Non-Filter Depth Expression

**Purpose**: To give "circles/icons/avatars/trophies/role badges floating on cards" a visual anchor that "touches the ground", **without using `<filter>` shadows**.

**Why it's useful**:
1. Native PPTX circle/ellipse objects, consistent across renderers, will not be parsed as `<a:outerShdw>` (avoiding shadow color loss or rearrangement issues).
2. Echoes §3 "Restrained Shadows" — a page's shadow budget is capped at 2-3, other elements needing "depth" can use this method.
3. **Easier to re-edit in PPT** than filter shadows (users can directly drag, change color, delete).

**Method**: Draw a **horizontally flattened ellipse** (`ry << rx`) directly **below** the floating element, with low opacity, and a color using the main theme color or Slate 900:

```xml
<!-- Ground anchor shadow plate below avatar/badge, cy 10-15px lower than avatar bottom edge -->
<ellipse cx="80" cy="172" rx="70" ry="5" fill="#0F172A" opacity="0.10"/>
<!-- Then draw the avatar body (order is important, ellipse must be drawn first) -->
<circle cx="80" cy="80" r="80" fill="#E2E8F0"/>
```

**Parameter Reference**:

| Floating Element Radius | Ellipse rx | Ellipse ry | opacity |
|-------------|---------|---------|---------|
| 30-50 px | r × 0.85 | 3-4 | 0.10-0.15 |
| 50-100 px | r × 0.85 | 5-6 | 0.10-0.12 |
| 100+ px | r × 0.85 | 7-9 | 0.08-0.10 |

Color: Default `#0F172A` (neutral dark gray), can be changed to a darker variant of the main theme color (e.g., `#1E3A8A` under an avatar) to express a "brand color shadow".

**Forbidden**: Do not draw the ellipse as a perfect circle or near-perfect circle (`ry/rx > 0.25` will appear distorted). Also, do not stack it on top of `<filter>` shadows — choose one is enough.

### 11.7 Bidirectional Interaction Arrows

**Purpose**: To express paired relationships such as "request/response", "push/pull", "upstream/downstream", "supply/demand". This differs from unidirectional process arrows.

**Method**: Two parallel `<line>`s + `marker-end`s of different colors, in opposite directions. **Each line must have an action label**:

```xml
<defs>
  <marker id="reqArrow" markerWidth="10" markerHeight="10" refX="9" refY="5"
          orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L10,5 L0,10 Z" fill="#3B82F6"/>
  </marker>
  <marker id="respArrow" markerWidth="10" markerHeight="10" refX="9" refY="5"
          orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L10,5 L0,10 Z" fill="#10B981"/>
  </marker>
</defs>

<!-- Request: Left to right, blue -->
<line x1="380" y1="250" x2="926" y2="250" stroke="#3B82F6" stroke-width="2.5"
      marker-end="url(#reqArrow)"/>
<rect x="500" y="216" width="280" height="26" rx="11" fill="#FFFFFF"
      stroke="#3B82F6" stroke-width="1"/>
<text x="640" y="234" text-anchor="middle" font-size="14" font-weight="700"
      fill="#3B82F6">① Login Request · POST /auth/login</text>

<!-- Response: Right to left, green -->
<line x1="926" y1="290" x2="384" y2="290" stroke="#10B981" stroke-width="2.5"
      marker-end="url(#reqArrow)"/>
<!-- ...same label pairing... -->
```

**Color Convention**: Request side (initiator) uses blue `#3B82F6`, response side (responder) uses green `#10B981`. For peer-to-peer relationships (e.g., A↔B collaboration), use Slate 600 `#475569` uniformly without distinguishing colors.

**Forbidden**: "Bare lines" are not allowed — **each** bidirectional arrow must have a label explaining the action; otherwise, readers cannot discern the directional semantics.

### 11.8 Reference Implementations

| Pattern | Reference Template |
|------|---------|
| §11.1 Half-Rounded Section Tab (Rounded Top, Straight Bottom) | `quadrant_text_bullets.svg`, `labeled_card.svg`, `vertical_pillars.svg`, `comparison_columns.svg` |
| §11.2 Nested Card Border | `labeled_card.svg` |
| §11.3 2×2 Card Grid | `kpi_cards.svg`, `quadrant_text_bullets.svg`, `labeled_card.svg` |
| §11.3 2×3 Card Grid | `icon_grid.svg` |
| §11.3 1×3/1×4 Card Grid | `comparison_columns.svg`, `vertical_pillars.svg` |
| §11.5 Diagonal Dashed Connector | `matrix_2x2.svg` |
| §11.6 Ground Anchor Ellipse | `team_roster.svg` |
| §11.7 Bidirectional Interaction Arrows | `client_server_flow.svg` |