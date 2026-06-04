# PPT Master Design System and Layout Capabilities: Key Component Analysis

This document details the key instructions, specification reference files, and Python scripts within the `ppt-master` repository that collectively ensure robust layout alignments, prevent text/visual overlaps, maintain boundary constraints, align text orientations, and map icons correctly.

---

## 1. Architectural Blueprint: The Intermediate SVG Translation

Unlike tools that output flat screenshots or compile raw OpenXML from scratch (which is highly verbose and error-prone), PPT Master uses **SVG as an intermediate 2D vector coordinate space** (typically $1920 \times 1080$ pixels for 16:9 slides). 

SVG is highly structured and well-represented in LLM training data. A deterministic Python compilation engine ([`svg_to_pptx`](../skills/ppt-master/scripts/svg_to_pptx)) translates these SVG coordinates and primitives one-to-one to native PowerPoint DrawingML shapes at export time ($1\text{ px} = 9525\text{ EMUs}$).

```
[Markdown Sources]
        ↓
[Strategist Phase]  →  Produces design_spec.md & spec_lock.md
        ↓
[Executor Phase]    →  Generates raw vector SVGs (sequential, page-by-page)
        ↓
[Quality Gate]      →  svg_quality_checker.py (zero tolerance for banned elements/drift)
        ↓
[Post-Processing]   →  finalize_svg.py (expands placeholders, flattens coordinates)
        ↓
[PPTX Export]       →  svg_to_pptx (maps SVG to native PowerPoint DrawingML)
```

---

## 2. Key Instructions & Design References (`.md` Files)

The visual quality, grid alignment, safety zones, and lack of overlap are governed by strict natural-language prompts and specifications located in `skills/ppt-master/references/`:

### A. [`shared-standards.md`](../skills/ppt-master/references/shared-standards.md) — Technical SVG/PPT Constraints
This is the core technical "rulebook" read by both the Strategist and Executor roles.
* **Inline Text Runs (`<text>` & `<tspan>` constraints)**: To keep text elements from overlapping or drifting during translation, this file mandates that a single logical text line must be wrapped in a single `<text>` element with inline `<tspan>` runs for formatting variations. This prevents text boxes from breaking into independent overlapping frames on PowerPoint export.
* **SVG Banned Features Blacklist**: Explicitly bans CSS classes, embedded styles (`<style>`), `<foreignObject>`, and `<mask>` features that break PowerPoint's internal layout engines, prescribing clean, inline-styled SVG primitives.
* **Shadows & Overlay Treatments**: Restricts soft shadows to a maximum of 2–3 elements per page (under a single light source offset `dy=4` to `8`) to avoid cluttered visual depth.

### B. [`executor-base.md`](../skills/ppt-master/references/executor-base.md) — Base SVG Generation Guidelines
Governs how slide pages are built sequentially.
* **Per-Page `spec_lock.md` Re-Read (Anti-Drift)**: To combat context-compression drift (where models hallucinate font families, size ramps, or colors mid-way through a long deck), the Executor must re-read the machine-readable contract `spec_lock.md` before generating *each* page.
* **Layout Rhythm (`page_rhythm`)**: Dictates spacing rules based on rhythm attributes (`anchor`, `dense`, `breathing`). For instance, `breathing` slides explicitly forbid multi-card grids, forcing natural whitespace and high contrast.
* **Grid Guidelines**: Enforces specific layout rules for cards, grids, timelines, and margins.

### C. [`image-layout-patterns.md`](../skills/ppt-master/references/image-layout-patterns.md) & [`image-layout-spec.md`](../skills/ppt-master/references/image-layout-spec.md) — Grids and Inset Layouts
* **Layout Vocabulary**: Defines 72 numbered placement combinations (Primary structures and Modifier layers) for mixing text and graphics.
* **Geometry Calculation**: Provides trigonometric formulas and coordinate systems for sizing side-by-side grids, donut/pie slices, overlapping photo spreads, and insets to prevent structural clashes.

### D. [`executor-consultant-top.md`](../skills/ppt-master/references/executor-consultant-top.md) & Style-Specific Sheets
* **Safe Margins & Spacing Budgets**: Prescribes pixel budgets (e.g., margins $x: 60\text{--}80\text{px}$, $y: 100\text{--}120\text{px}$) and strict typography hierarchy scales (ramps) anchored on the body text size.

---

## 3. Key Python Scripts (`.py` Files)

The deterministic layout correctness, icon rendering, and format compliance are enforced by scripts in `skills/ppt-master/scripts/`:

### A. The Quality Gate: [`svg_quality_checker.py`](../skills/ppt-master/scripts/svg_quality_checker.py)
A massive 64KB script running pre-export compliance checks. It halts execution on the following violations:
* **Dimension Mismatch**: Ensures `viewBox` matches canvas specs (e.g., $1920 \times 1080$).
* **Banned Syntax**: Flags inline CSS selectors, CSS classes, group opacities, or `<foreignObject>` elements.
* **Design Spec Drift**: Matches the generated colors, typography stacks, and icons directly against the `spec_lock.md` configuration.

### B. Post-Processing Engine: [`finalize_svg.py`](../skills/ppt-master/scripts/finalize_svg.py) & the `svg_finalize/` Package
This orchestrates final cleanups on disk:
* **[`embed_icons.py`](../skills/ppt-master/scripts/svg_finalize/embed_icons.py)**: Searches for abstract placeholders (like `<use data-icon="lucide/bolt"/>`) and inserts the literal path definitions from the templates library, aligning them to the placeholder's coordinate frame.
* **[`flatten_tspan.py`](../skills/ppt-master/scripts/svg_finalize/flatten_tspan.py)**: Extracts vertical line-height calculations (`dy` stacks) and flattens nested tspans. This ensures that text flows naturally in PPTX text frames without line collisions or vertical collapses.
* **[`svg_rect_to_path.py`](../skills/ppt-master/scripts/svg_finalize/svg_rect_to_path.py)**: Converts rounded SVG rectangles into exact path shapes to prevent PowerPoint from misinterpreting corner geometries.

### C. OpenXML Compiler: [`svg_to_pptx.py`](../skills/ppt-master/scripts/svg_to_pptx.py) & the `svg_to_pptx/` Package
This converts compliant SVGs into OpenXML structures:
* **[`drawingml_elements.py`](../skills/ppt-master/scripts/svg_to_pptx/drawingml_elements.py)**: Handles the element dispatching loop. For instance, translating `<text>` nodes to `<p:sp>` (shapes) containing `<p:txBody>` (text bodies) with exact font sizes, bold weights, alignments, and paragraph structures.
* **[`drawingml_paths.py`](../skills/ppt-master/scripts/svg_to_pptx/drawingml_paths.py)**: Normalizes custom geometries (`<path d="...">` command lists) and outputs native PowerPoint `<a:custGeom>` tags.
* **[`drawingml_styles.py`](../skills/ppt-master/scripts/svg_to_pptx/drawingml_styles.py)**: Compiles fills, borders, gradients, drop shadows, and text alignments into OpenXML style sheets.

---

## 4. Key Takeaways for maintaining design fidelity

| Issue Prevented | Key Component File | Mechanism |
|---|---|---|
| **Text Overflow/Overlap** | [`shared-standards.md`](../skills/ppt-master/references/shared-standards.md) §Inline Text Runs & [`flatten_tspan.py`](../skills/ppt-master/scripts/svg_finalize/flatten_tspan.py) | Wraps styled runs in a single text frame; flattens baseline offsets to prevent rendering lines on top of each other. |
| **Color & Font Inconsistency** | [`spec_lock.md`](../projects/spec_lock.md) & [`executor-base.md`](../skills/ppt-master/references/executor-base.md) §2.1 | Forces the LLM to re-read styling constraints per-page, eliminating memory-based style mutations. |
| **Broke PowerPoint Layouts** | [`svg_quality_checker.py`](../skills/ppt-master/scripts/svg_quality_checker.py) | Operates as a strict build-gate; rejects non-conforming XML attributes, CSS styles, or unsupported groupings. |
| **Broken Icons** | [`embed_icons.py`](../skills/ppt-master/scripts/svg_finalize/embed_icons.py) & `templates/icons/` | Resolves abstract semantic tags to actual vector geometries before building PPTX files. |
| **Coordinate/Shape Distortions** | [`drawingml_paths.py`](../skills/ppt-master/scripts/svg_to_pptx/drawingml_paths.py) & `EMU_PER_PX` | Scales absolute canvas coordinates ($1920\times1080$ px) smoothly to PowerPoint's native English Metric Units. |
