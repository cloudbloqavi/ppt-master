# PPT Master — Forensic Architecture & Codebase Analysis

> **Scope**: Complete reverse-engineering of the `ppt-master` repository — architecture, data flow, code-level mechanics, dependencies, constraints, and operational gotchas.
>
> **Audience**: Engineers onboarding to the codebase or evaluating the system for integration.

---

## Table of Contents

1. [Architecture Philosophy](#1-architecture-philosophy)
2. [Repository Structure Map](#2-repository-structure-map)
   - [2.5 The References Directory — LLM Instruction Manual](#25-the-references-directory--llm-instruction-manual)
   - [2.6 The Workflows Directory — Pipeline Extensions](#26-the-workflows-directory--pipeline-extensions)
3. [Seven-Stage Pipeline Deep Dive](#3-seven-stage-pipeline-deep-dive)
4. [DrawingML Translation Engine](#4-drawingml-translation-engine)
5. [Text & Typography Engine](#5-text--typography-engine)
6. [SVG Quality Checker](#6-svg-quality-checker)
7. [Animation System](#7-animation-system)
8. [Image Generation Subsystem](#8-image-generation-subsystem)
   - [8.6 Image Palettes — Color Behavior Library](#86-image-palettes--color-behavior-library)
   - [8.7 Image Renderings — Visual Style Library](#87-image-renderings--visual-style-library)
   - [8.8 The Rendering × Palette Compatibility Matrix](#88-the-rendering--palette-compatibility-matrix)
   - [8.9 How Palettes & Renderings Flow Through the Pipeline](#89-how-palettes--renderings-flow-through-the-pipeline)
   - [8.10 Standalone Execution (Path A) vs. Host-Native Agent (Path B)](#810-standalone-execution-path-a-vs-host-native-agent-path-b)
9. [Live Preview Server](#9-live-preview-server)
10. [Dependency Graph & Package Registry](#10-dependency-graph--package-registry)
11. [Known Constraints & Gotchas](#11-known-constraints--gotchas)


---

## 1. Architecture Philosophy

### 1.1 The Core Design Decision

PPT Master splits presentation creation into two fundamentally different workloads:

| Workload | Owner | Nature |
|---|---|---|
| **Visual design, structure, layout** | LLM (the "AI designer") | Creative, context-dependent |
| **Compilation to native PowerPoint** | Deterministic Python engine | Mechanical, rule-based |

The LLM never touches DrawingML XML. It generates **SVG** — a format it is fluent in from web-scale training data — and a deterministic pipeline compiles that SVG to native PowerPoint shapes.

### 1.2 Why SVG? — The Canvas vs. Document Impedance Mismatch

The choice of SVG as the intermediate representation was arrived at by eliminating alternatives:

| Format | Verdict | Reason |
|---|---|---|
| **Direct DrawingML XML** | ❌ REJECTED | Too verbose — a rounded rectangle with gradient + shadow requires ~100 lines of nested OpenXML. LLMs exhaust context producing it, and consistency collapses over a 15-slide deck. |
| **HTML/CSS** | ❌ REJECTED | HTML describes a *document flow* (relative positioning, flexbox, grid). PowerPoint is an *absolute-coordinate canvas* where every element is independently positioned. Bridging the two requires browser-scale layout engine complexity. |
| **WMF/EMF** | ❌ REJECTED | Microsoft-only binary vector format. Zero LLM training data. |
| **SVG-as-raster-image** | ❌ REJECTED | Embedding SVG as a flat image produces zero editability in PowerPoint — it's a screenshot. |
| **SVG-as-vector-layer** | ✅ CHOSEN | 1:1 coordinate mapping with PowerPoint's absolute canvas. LLMs generate it reliably. Humans can preview/edit it in any browser. Python scripts can parse and convert it deterministically. |

**The SVG Translation Layer insight**: SVG matches PowerPoint's worldview — both use absolute 2D coordinates. SVG primitives map directly to DrawingML concepts:

```
SVG <rect>           →  <a:prstGeom prst="roundRect">
SVG transform        →  <a:xfrm>
SVG <linearGradient> →  <a:gradFill>
SVG <filter>         →  <a:effectLst> (shadow / glow)
SVG <text>           →  <p:sp> with <p:txBody>
```

SVG is the only format that simultaneously satisfies three requirements: **AI can generate it**, **humans can preview it in browsers**, and **scripts can convert it deterministically to PowerPoint**.

### 1.3 Coordinate Space: Pixels vs. EMUs

| Phase | Unit | Example |
|---|---|---|
| SVG generation & quality checking | CSS pixels (96 DPI) | `viewBox="0 0 1920 1080"` for 16:9 |
| PowerPoint export | EMUs (English Metric Units) | 1 inch = 914,400 EMU |
| Conversion factor | `1 px = 9,525 EMU` | Defined in [`drawingml_utils.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_utils.py) as `EMU_PER_PX = 9525` |

The entire pipeline works in pixel-space. EMU conversion is isolated to the final export step ([`svg_to_pptx.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx.py)), keeping layout arithmetic simple for both the LLM and the quality checker.

### 1.4 Role Switching, Not Sub-Agents

PPT Master uses **role switching within a single LLM context** rather than dispatching to sub-agents. The pipeline has two primary roles:

| Role | Defined in | Responsibility |
|---|---|---|
| **Strategist** | [`references/strategist.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/strategist.md) | Analyze source material, define slide structure, produce `design_spec.md` and `spec_lock.md`, present Eight Confirmations |
| **Executor** | [`references/executor-base.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/executor-base.md) | Generate SVG pages one-by-one, write speaker notes, run quality checks |

This preserves full context continuity — the Executor has access to all Strategist decisions without inter-agent message-passing overhead or context loss.

### 1.5 Drift Resistance: `spec_lock.md`

LLMs suffer **context-compression drift** during long generation runs. Over a 15-slide deck, the model's memory of styling parameters (color palettes, font stacks, icon choices) degrades, resulting in visual inconsistency.

PPT Master counters this with a **two-file design system**:

| File | Purpose | Format |
|---|---|---|
| `design_spec.md` | Human-readable visual narrative — audience, tone, color palettes, layout outlines | Structured Markdown with YAML frontmatter |
| `spec_lock.md` | Machine-readable styling contract — exact HEX colors, font families, font sizes per role, page rhythm markers | JSON-like Markdown tokens |

**The Per-Page Re-Read Gate** (enforced by [`SKILL.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/SKILL.md) Rule 8): Before generating **each** SVG page, the Executor must re-read `spec_lock.md`. It is forbidden to generate slides from conversational memory. This bypasses context-window limits and keeps colors, fonts, and layout templates consistent across long decks.

---

## 2. Repository Structure Map

### 2.1 Top-Level Directory Layout

```
ppt-master/
├── AGENTS.md                    # AI agent entry point — routes to SKILL.md
├── skills/ppt-master/           # Core skill package (THE authoritative workflow)
│   ├── SKILL.md                 # Main pipeline definition (563 lines)
│   ├── references/              # Role definitions & technical specifications
│   ├── scripts/                 # All runnable Python tools (~30 scripts)
│   ├── templates/               # Layout templates, chart templates, icons, brands
│   ├── workflows/               # Standalone sub-workflows (topic-research, etc.)
│   └── requirements.txt         # Python dependency manifest
├── docs/                        # User-facing documentation
│   ├── rules/                   # Repo-wide style rules
│   ├── technical-design.md      # Core architecture rationale
│   └── templates-architecture.md # Template system design
├── projects/                    # User project workspace (gitignored content)
└── examples/                    # Example projects for reference
```

### 2.2 Scripts Package Anatomy

```
skills/ppt-master/scripts/
├── source_to_md/                # Source conversion scripts
│   ├── pdf_to_md.py             # PDF → Markdown (PyMuPDF)
│   ├── doc_to_md.py             # DOCX/HTML/EPUB → Markdown (mammoth, markdownify)
│   ├── excel_to_md.py           # XLSX → Markdown (openpyxl)
│   ├── ppt_to_md.py             # PPTX → Markdown (python-pptx)
│   └── web_to_md.py             # URL → Markdown (requests, curl_cffi)
│
├── svg_to_pptx/                 # DrawingML translation engine (18 modules, ~250KB)
│   ├── drawingml_converter.py   # Core dispatcher — routes SVG elements to converters
│   ├── drawingml_elements.py    # Per-element converters (rect, circle, line, path, text, image)
│   ├── drawingml_paths.py       # SVG path parser + normalizer + EMU generator
│   ├── drawingml_styles.py      # Fill, stroke, gradient, shadow, glow builders
│   ├── drawingml_context.py     # ConvertContext — shared state (transform, defs, media)
│   ├── drawingml_utils.py       # Constants (EMU_PER_PX, SVG_NS), color parsing, transform matrix
│   ├── pptx_builder.py          # Top-level PPTX assembly (889 lines)
│   ├── pptx_cli.py              # CLI entry point for svg_to_pptx
│   ├── pptx_dimensions.py       # Canvas format definitions (EMU/pixel mappings)
│   ├── pptx_discovery.py        # SVG file discovery and ordering
│   ├── pptx_media.py            # PNG rendering (CairoSVG/svglib fallback)
│   ├── pptx_narration.py        # Audio narration injection (shape XML, timing)
│   ├── pptx_notes.py            # Speaker notes XML generation
│   ├── pptx_slide_xml.py        # Slide XML templates (SVG embed mode)
│   ├── tspan_flattener.py       # In-memory tspan → independent <text> flattener
│   ├── use_expander.py          # In-memory <use data-icon> → <g> expansion
│   └── animation_config.py      # animations.json loader + validator
│
├── svg_finalize/                # On-disk SVG finalization (7 modules)
│   ├── embed_icons.py           # <use data-icon="..."> → inline <g> with paths
│   ├── embed_images.py          # External image refs → base64 data URIs
│   ├── align_embed_images.py    # Image alignment and embedding orchestration
│   ├── crop_images.py           # Image crop processing
│   ├── fix_image_aspect.py      # preserveAspectRatio correction
│   ├── flatten_tspan.py         # Positional tspan → independent text elements (on disk)
│   └── svg_rect_to_path.py      # Rounded rect → <path> (for browser fidelity)
│
├── svg_editor/                  # Live preview Flask server
│   ├── server.py                # Flask backend (616 lines) — API + annotation system
│   └── static/                  # Frontend HTML/CSS/JS for slide preview
│
├── image_backends/              # Pluggable image generation providers (15 backends)
│   ├── backend_gemini.py        # Google Gemini
│   ├── backend_openai.py        # OpenAI / OpenAI-compatible
│   ├── backend_qwen.py          # Alibaba Qwen
│   ├── backend_zhipu.py         # Zhipu GLM-Image
│   ├── backend_volcengine.py    # Volcengine Seedream
│   ├── backend_stability.py     # Stability AI
│   ├── backend_bfl.py           # Black Forest Labs FLUX
│   ├── backend_ideogram.py      # Ideogram
│   ├── backend_minimax.py       # MiniMax
│   ├── backend_modelscope.py    # ModelScope
│   ├── backend_siliconflow.py   # SiliconFlow
│   ├── backend_fal.py           # fal.ai
│   ├── backend_replicate.py     # Replicate
│   ├── backend_openrouter.py    # OpenRouter
│   └── backend_common.py        # Shared utilities (rate-limit detection, retry logic)
│
├── project_manager.py           # Project init / validate / import-sources
├── image_gen.py                 # Unified image generation CLI (manifest + single-shot)
├── image_search.py              # Web image search (DuckDuckGo/Bing, CC-licensed)
├── analyze_images.py            # Image metadata analysis (aspect ratio, color)
├── latex_render.py              # LaTeX formula → PNG (online services)
├── svg_quality_checker.py       # SVG compliance checker (1491 lines, 9+ check categories)
├── total_md_split.py            # Speaker notes splitter (total.md → per-slide .md)
├── finalize_svg.py              # On-disk SVG finalization entry point
├── svg_to_pptx.py               # PPTX export entry point (thin wrapper → pptx_cli.py)
├── update_spec.py               # Propagate spec_lock.md changes across SVGs
├── pptx_animations.py           # Transition/entrance animation XML builders
└── config.py                    # .env resolution and env-var loading
```

#### Scripts Purpose & Functional Groupings

The `scripts/` directory is the **deterministic half** of the system — Python code that runs on your machine (not in the LLM). While `references/` tells the AI *what* to generate, `scripts/` processes the output *after* the AI produces it.

| Functional Group | Scripts | Role in Pipeline |
|---|---|---|
| **Source Conversion** (`source_to_md/`) | `pdf_to_md.py`, `doc_to_md.py`, `excel_to_md.py`, `ppt_to_md.py`, `web_to_md.py` | **Step 1**: Convert any input format to Markdown so the LLM can read it. Each script handles format-specific extraction (PDF images, Excel formulas, PPTX shapes). |
| **Project Management** | `project_manager.py` | **Step 2**: Initialize project directories, import sources, validate project structure. The `init` command creates the canonical folder layout (§2.4). |
| **Image Generation** (`image_backends/`) | `image_gen.py` + 15 backend modules | **Step 5**: Unified CLI for AI image generation across 15 providers. Backend dispatch via `IMAGE_BACKEND` env var. In Path B (Antigravity/Claude Code), the host's native `generate_image` tool is used instead. |
| **Image Analysis** | `analyze_images.py`, `image_search.py` | **Step 5**: Analyze project images for quality/format issues; search web for stock images. |
| **SVG Quality Gate** | `svg_quality_checker.py` | **Step 6→7 boundary**: Validates SVGs against DrawingML constraints (see §6). Any error blocks export. |
| **Post-Processing** (`svg_finalize/`) | 7 modules (`embed_icons.py`, `embed_images.py`, `flatten_tspan.py`, etc.) | **Step 7.1**: On-disk SVG finalization — icon expansion, image embedding, tspan flattening, aspect ratio correction. |
| **MD Splitting** | `total_md_split.py` | **Step 7.2**: Split `notes/total.md` into per-slide speaker notes files. |
| **SVG Finalization** | `finalize_svg.py` | **Step 7.2**: Orchestrate all `svg_finalize/` modules on the project's SVGs. |
| **DrawingML Engine** (`svg_to_pptx/`) | 18 modules (~250KB) | **Step 7.3**: The translation engine — parses SVG XML, writes DrawingML shapes. (See §4 for full internals.) |
| **PPTX Assembly** | `svg_to_pptx.py` | **Step 7.3**: CLI entry point that drives the translation engine and writes the final `.pptx` file. |
| **Animation** | `pptx_animations.py`, `animation_config.py` | **Step 7.3+**: Default slide transitions + optional custom animation from `animations.json`. |
| **Live Preview** (`svg_editor/`) | `server.py` + `static/` | **Optional**: Flask-based browser preview with click-to-annotate (not required for export). |
| **Utilities** | `config.py`, `update_spec.py`, `latex_render.py` | Cross-cutting: env-var resolution, spec propagation, LaTeX formula rendering. |

**Self-documentation**: The [`scripts/docs/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/docs/) directory contains topic-focused docs for script usage:

| Doc | Covers |
|---|---|
| [`conversion.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/docs/conversion.md) | All source conversion scripts — options, edge cases, format-specific notes |
| [`image.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/docs/image.md) | Image generation, analysis, and search scripts |
| [`project.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/docs/project.md) | Project manager commands (init, import-sources, validate) |
| [`svg-pipeline.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/docs/svg-pipeline.md) | Post-processing pipeline (split → finalize → export) |
| [`update_spec.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/docs/update_spec.md) | Spec propagation and update workflows |
| [`troubleshooting.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/docs/troubleshooting.md) | Common issues and debugging guides |

### 2.3 Template System

```
skills/ppt-master/templates/
├── layouts/                     # Page layout templates (SVG page rosters)
│   ├── layouts_index.json       # Machine-readable index of all layout sets
│   └── <layout_id>/             # Each layout: design_spec.md + SVG pages
├── brands/                      # Brand identity presets
│   ├── brands_index.json        # Brand index
│   └── <brand_id>/              # Each brand: colors, typography, logos
├── charts/                      # Visualization SVG templates
│   ├── charts_index.json        # Chart template index
│   └── *.svg                    # Bar, line, pie, donut, funnel, process, etc.
├── icons/                       # Icon library (multiple sub-libraries)
│   ├── README.md                # Icon usage guide
│   └── <library>/               # Icon SVG files searchable by keyword
└── decks/                       # Combined brand + layout replicas
```

**Three template kinds** (defined in [`templates-architecture.md`](file:///c:/Users/aviji/repo/ppt-master/docs/templates-architecture.md)):

| Kind | Contains | Example |
|---|---|---|
| `brand` | Color scheme, typography, logos, voice | Corporate identity preset |
| `layout` | Page roster, slide structures (SVG templates) | "Pitch deck 12-page" |
| `deck` | Combined brand + layout replica | Full themed starter deck |

**Multi-Path Fusion**: When the user supplies both a `brand` and a `layout`, the Strategist merges their specs — identity (colors, typography) from the brand, structure (canvas, layouts) from the layout. Same-kind conflicts are surfaced to the user.

#### Templates Purpose & Architecture

The `templates/` directory is the **design asset library** — pre-built, reusable components that accelerate deck creation. Unlike `references/` (which are LLM instructions) or `scripts/` (which are Python tools), templates are **data files** consumed by both the LLM and the scripts.

| Subdirectory | Contents | How It's Used |
|---|---|---|
| [`layouts/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/layouts/) | Page roster SVG templates organized by layout set. Each set has a `design_spec.md` + SVG pages defining slide structures. | **Step 3**: When the user specifies a layout, the Strategist reads the layout's `design_spec.md` to inherit slide structures, then the Executor uses the SVG templates as starting points for each page. |
| [`brands/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/brands/) | Brand identity presets — colors, typography, logos, voice guidelines. Each brand has its own directory under `brands/<brand_id>/`. | **Step 3**: When the user specifies a brand, the Strategist inherits its color scheme and typography into `design_spec.md` / `spec_lock.md`. Created via the [`create-brand`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/create-brand.md) workflow. |
| [`charts/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/charts/) | **72 SVG chart/diagram templates** + index + style guide. Covers bar, line, pie, donut, funnel, Gantt, radar, treemap, Sankey, matrix, timeline, process flow, journey map, and many more. | **Step 6**: The Executor uses these as structural starting points when a slide requires a data visualization. The [`CHART_STYLE_GUIDE.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/charts/CHART_STYLE_GUIDE.md) (31KB) provides detailed styling rules for chart adaptation. |
| [`icons/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/icons/) | SVG icon libraries (multiple sub-libraries, e.g., Lucide). Icons referenced via `<use data-icon="lucide/chart-bar"/>` in SVGs. | **Step 6→7**: Icon placeholders in SVGs are expanded to inline `<g>` groups by `finalize_svg` and `svg_to_pptx`. See §8.5. |
| [`decks/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/decks/) | Combined brand + layout replicas — full themed starter decks. | **Step 3**: Pre-fused brand + layout combinations for one-step template application. |

**Reference files** in the templates root:

| File | Purpose |
|---|---|
| [`design_spec_reference.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/design_spec_reference.md) | Canonical template showing the full `design_spec.md` schema — all fields, their types, allowed values, and examples (22KB). The Strategist references this when writing a project's `design_spec.md`. |
| [`spec_lock_reference.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/spec_lock_reference.md) | Canonical template for `spec_lock.md` — the machine-readable styling contract format (12KB). Defines all token fields the Executor must re-read per page. |
| [`README.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/README.md) | Overview of the template system architecture and usage instructions. |

**Chart template library highlights** (72 templates in [`charts/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/charts/)):

| Category | Templates |
|---|---|
| **Data charts** | `bar_chart`, `line_chart`, `pie_chart`, `donut_chart`, `area_chart`, `scatter_chart`, `bubble_chart`, `radar_chart`, `heatmap_chart`, `treemap_chart`, `waterfall_chart`, `stacked_bar_chart`, `grouped_bar_chart`, `horizontal_bar_chart`, `pareto_chart`, `box_plot_chart`, `bullet_chart`, `butterfly_chart`, `dual_axis_line_chart`, `dumbbell_chart`, `gauge_chart`, `progress_bar_chart`, `stacked_area_chart`, `word_cloud` |
| **Process/flow** | `process_flow`, `chevron_process`, `chevron_chain_with_tail`, `pipeline_with_stages`, `snake_flow`, `fishbone_diagram`, `client_server_flow`, `journey_map`, `gantt_chart`, `roadmap_vertical` |
| **Structural** | `matrix_2x2`, `venn_diagram`, `pyramid_chart`, `pyramid_isometric`, `concentric_circles`, `hub_spoke`, `hub_inward_arrows`, `top_down_tree`, `mind_map`, `segmented_wheel`, `layered_architecture`, `module_composition`, `circular_stages` |
| **Lists/tables** | `basic_table`, `comparison_table`, `consulting_table`, `feature_matrix_table`, `financial_statement_table`, `harvey_balls_table`, `project_schedule_table`, `comparison_columns`, `pros_cons_chart`, `agenda_list`, `vertical_list`, `numbered_steps`, `icon_grid`, `labeled_card`, `kpi_cards`, `team_roster` |
| **Specialized** | `sankey_chart`, `quadrant_bubble_scatter`, `quadrant_text_bullets`, `isometric_stairs`, `arc_anchored_list`, `vertical_pillars` |

### 2.4 Project Directory Structure

Every project initialized by `project_manager.py init` creates:

```
projects/<project_name>/
├── sources/           # Converted source materials (Step 1 output)
│   └── _files/        # Extracted images from source documents
├── templates/         # Copied/fused layout/brand specs
├── images/            # Downloaded / AI-generated image assets
│   ├── image_prompts.json  # Image generation manifest
│   └── image_prompts.md    # Markdown sidecar (fallback for manual gen)
├── svg_output/        # Raw AI-generated SVG pages
├── svg_final/         # Post-processed SVGs (icons inlined, images embedded)
├── notes/             # Speaker notes (total.md + per-slide splits)
├── exports/           # Final PPTX files
├── backup/            # Timestamped SVG backups before each export
├── design_spec.md     # Visual design specification
└── spec_lock.md       # Machine-readable styling contract
```

### 2.5 The References Directory — LLM Instruction Manual

[`references/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/) is not code — it's the **AI's runtime operating system**. While `scripts/` contains Python that runs on your machine, `references/` contains **Markdown "programs" that run inside the LLM's brain**. Each file is a detailed role prompt that the agent reads (`read_file`) to know how to behave at each pipeline stage.

This is why the repo is ~300KB of Markdown and ~250KB of Python — half the system runs as deterministic scripts, the other half runs as natural-language instructions inside the LLM.

#### Role Definition Files

| File | Role | When Read | Size |
|---|---|---|---|
| [`strategist.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/strategist.md) | **Strategist** — analyze sources, define slide structure, run Eight Confirmations, produce `design_spec.md` + `spec_lock.md` | Step 4 | 57KB |
| [`executor-base.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/executor-base.md) | **Executor base** — SVG generation rules, per-page spec_lock re-read, quality standards | Step 6 | 32KB |
| [`executor-general.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/executor-general.md) | Executor variant for general-purpose decks | Step 6 | 6KB |
| [`executor-consultant.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/executor-consultant.md) | Executor variant for consulting-style decks | Step 6 | 8KB |
| [`executor-consultant-top.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/executor-consultant-top.md) | Executor variant for top-tier consulting (MBB-style) | Step 6 | 11KB |
| [`image-generator.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-generator.md) | **Image_Generator** — compose image prompts using rendering + palette + HEX values | Step 5 | 44KB |
| [`image-searcher.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-searcher.md) | Image search — when to search web vs. generate | Step 5 | 12KB |
| [`template-designer.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/template-designer.md) | Template creation — for standalone template workflows | On demand | 25KB |
| [`visual-review.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/visual-review.md) | Visual self-check rubric — per-page quality scoring | On demand | 16KB |

#### Technical Specification Files

| File | Purpose | When Read |
|---|---|---|
| [`shared-standards.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/shared-standards.md) | SVG banned features blacklist + all DrawingML constraints (markers, clipPath, patterns, filters) — the "what PowerPoint can and cannot do" rulebook | Steps 4–6 |
| [`canvas-formats.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/canvas-formats.md) | Canvas dimensions for all output formats (16:9, 4:3, A4, Xiaohongshu, WeChat, etc.) | Step 2 |
| [`animations.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/animations.md) | Animation effect catalog for custom animation workflow | On demand |
| [`svg-image-embedding.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/svg-image-embedding.md) | Rules for `<image>` placement in SVG (sizing, aspect ratio, clipping) | Step 6 |
| [`image-base.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-base.md) | Base image handling rules (format, sizing, naming conventions) | Step 5 |
| [`image-layout-patterns.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-layout-patterns.md) | Image layout composition patterns (hero, split, grid, overlay, etc.) | Steps 5–6 |
| [`image-layout-spec.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-layout-spec.md) | Image layout technical specifications | Steps 5–6 |

#### Prompt-Engineering Libraries (Subdirectories)

| Directory | Contents | Purpose |
|---|---|---|
| [`image-palettes/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-palettes/) | 14 color behavior presets + index | Control HEX color proportions in AI images (see §8.6) |
| [`image-renderings/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-renderings/) | 20 visual style presets + index | Control visual style of AI images (see §8.7) |
| [`image-type-templates/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-type-templates/) | Type-specific prompt templates | Fewshot prompts for hero images, icons, chart backgrounds, etc. |
| [`ai-image-comparison/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/ai-image-comparison/) | Model comparison data | Evaluation data for AI image model selection |

#### How It Works at Runtime

When `SKILL.md` says "switch to Strategist role", the agent executes:

```
read_file references/strategist.md     ← 57KB of structured instructions load into context
```

That 57KB prompt becomes the AI's operating instructions — it contains the Eight Confirmations protocol, the auto-selection tables for rendering/palette, the `design_spec.md` template structure, and hundreds of edge-case rules. When the pipeline moves to Step 6, the agent switches:

```
read_file references/executor-base.md  ← 32KB of SVG generation rules
read_file references/executor-general.md  ← or executor-consultant.md, based on deck type
```

The executor prompt contains SVG banned-feature lists, per-page generation protocols, quality gate thresholds, and the `spec_lock.md` re-read mandate. These files are essentially **software written in natural language that compiles into LLM behavior**.

### 2.6 The Workflows Directory — Pipeline Extensions

[`workflows/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/) contains 9 standalone Markdown workflow files. These are **optional side-quests** — they extend the core 7-step pipeline for specific use cases but are never required for a basic deck generation. Each workflow is triggered by a specific user action or deck characteristic.

**Architectural pattern**: Workflows are to the core pipeline what plugins are to an app. The core pipeline (SKILL.md Steps 1–7) always runs. A workflow injects itself at a specific pipeline junction (before, between, or after steps) to handle a specialized concern.

```
Core Pipeline:  Step 1 → 2 → 3 → 4 → 5 → 6 → 7
                                ↑         ↑    ↑    ↓
                         topic-research  |  verify-charts  generate-audio
                         (before Step 1) |  (between 6→7)  (after Step 7)
                                    customize-animations
                                    (between 6→7)
```

| Workflow | File | Trigger Condition | Injection Point | What It Does |
|---|---|---|---|---|
| **Topic Research** | [`topic-research.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/topic-research.md) | User provides only a topic, no source files | **Before Step 1** | Web search → gather materials → produce source Markdown so the pipeline can continue |
| **Resume Execution** | [`resume-execute.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/resume-execute.md) | User opens new chat and says "继续生成 projects/x" | **Replaces Steps 1–4** | Skip Phase A (already done in prior chat), enter Phase B directly with existing `spec_lock.md` |
| **Create Template** | [`create-template.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/create-template.md) | User wants to create a reusable layout template | **Standalone** | Creates SVG page rosters + `design_spec.md` in `templates/layouts/` |
| **Create Brand** | [`create-brand.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/create-brand.md) | User provides brand assets (logo, branded PPTX, brand PDF) | **Standalone** | Extract brand identity → `templates/brands/<id>/` |
| **Verify Charts** | [`verify-charts.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/verify-charts.md) | Deck contains data charts | **Between Steps 6→7** | Chart coordinate calibration — verifies data labels, axis scales, bar proportions |
| **Customize Animations** | [`customize-animations.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/customize-animations.md) | User explicitly asks for animation tuning | **Between Steps 6→7** | Scaffold `animations.json` → user edits → validate → re-export |
| **Live Preview** | [`live-preview.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/live-preview.md) | User says "preview", "看效果", clicks elements | **During/after Step 6** | Start Flask server, handle annotation round-trips, apply corrections |
| **Visual Review** | [`visual-review.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/visual-review.md) | User explicitly requests per-page visual check | **Between Steps 6→7** | Per-page rubric-based visual scoring — user must explicitly trigger |
| **Generate Audio** | [`generate-audio.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/generate-audio.md) | User wants recorded narration | **After Step 7** | TTS → per-slide MP3/WAV → embed in PPTX |

**Key constraints** (from [`AGENTS.md`](file:///c:/Users/aviji/repo/ppt-master/AGENTS.md)):
- Workflows are **never auto-triggered** by the AI — only by explicit user request or matching trigger conditions
- `visual-review` in particular must NEVER be inferred from deck size, model identity, or any signal other than user request
- `create-brand` output goes to `templates/brands/<id>/` and is applied at Step 3 when the user explicitly provides the brand path

---

## 3. Seven-Stage Pipeline Deep Dive

The PPT Master pipeline is a **strict serial pipeline** — each step's output is the next step's input. Steps marked ⛔ BLOCKING require explicit user approval before proceeding.

```
[Source Doc]  →  Step 1: Conversion  →  MD Source
                      │
                      ▼
              Step 2: Project Init  →  Folder structure
                      │
                      ▼
              Step 3: Template Integration  →  Copy templates & fuse specs
                      │
                      ▼
              Step 4: Strategist ⛔  →  8 Confirmations → design_spec.md + spec_lock.md
                      │
                      ▼
              Step 5: Image Acquisition  →  AI-generated / web-sourced assets
                      │
                      ▼
              Step 6: Executor  →  Sequential SVGs + Quality Gate (0 errors)
                      │
                      ▼
              Step 7: Post-Processing  →  Split notes → Finalize SVG → Export PPTX
```

### Step 1: Source Content Conversion

**Objective**: Normalize incoming documents into clean, structured Markdown.

| Input Format | Script | Key Library | Mechanism |
|---|---|---|---|
| PDF | [`pdf_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/pdf_to_md.py) | `PyMuPDF` (fitz) | Text block extraction + image export to `_files/` |
| DOCX | [`doc_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/doc_to_md.py) | `mammoth` | XML-to-HTML conversion, then `markdownify` for MD |
| HTML | [`doc_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/doc_to_md.py) | `markdownify` | Direct HTML→Markdown |
| EPUB | [`doc_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/doc_to_md.py) | `ebooklib` | Extract XHTML chapters, convert each to MD |
| Legacy (.doc/.rtf/.odt) | [`doc_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/doc_to_md.py) | System `pandoc` | Fallback to pandoc CLI for formats without Python parsers |
| XLSX | [`excel_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/excel_to_md.py) | `openpyxl` | Sheet-by-sheet tabular extraction to Markdown tables |
| PPTX | [`ppt_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/ppt_to_md.py) | `python-pptx` | Slide-by-slide text/shape extraction |
| URL | [`web_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/web_to_md.py) | `requests` + `beautifulsoup4` | Fetch HTML, strip chrome, convert to MD |
| WeChat URLs | [`web_to_md.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/source_to_md/web_to_md.py) | `curl_cffi` | TLS fingerprint impersonation to bypass anti-scraping |

**Output**: `sources/extracted_source.md` + related images under `sources/_files/`.

**No source material?** When the user provides only a topic name, the [`topic-research`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/topic-research.md) workflow fires first — it uses web search to gather materials, then feeds them through Step 1.

### Step 2: Project Initialization

**Objective**: Create the standard directory structure and lock down the output aspect ratio.

**Command**: `python3 project_manager.py init <project_name> --format <format>`

**Key implementation** ([`project_manager.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/project_manager.py)):
- Creates the full directory tree (sources/, svg_output/, exports/, etc.)
- Writes a `project.json` with the canvas format key and creation timestamp
- Supports `import-sources` subcommand to move converted files into the project

**Canvas formats** (defined in [`canvas-formats.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/canvas-formats.md)):

| Format Key | Dimensions (px) | Aspect Ratio | Use Case |
|---|---|---|---|
| `ppt169` | 1920 × 1080 | 16:9 | Standard widescreen (default) |
| `ppt43` | 1024 × 768 | 4:3 | Legacy presentations |
| `a4portrait` | 1587 × 2245 | A4 portrait | Print documents |
| `a4landscape` | 2245 × 1587 | A4 landscape | Print landscape |

### Step 3: Template Integration (Optional)

**Objective**: Apply layout, brand, or deck presets to the project.

**Mechanics**:
1. User provides an explicit path to a template directory (bare template names never trigger)
2. Template files are copied into `projects/<name>/templates/`
3. If multiple template kinds are combined (e.g., brand + layout), the Strategist performs **segment-level fusion**:
   - **Identity segment** (colors, typography) → inherited from the `brand`
   - **Structural segment** (canvas, page roster) → inherited from the `layout`
4. Conflicts within the same segment are surfaced to the user for resolution

**Output**: Fused `design_spec.md` with a provenance trail showing which values came from which template.

### Step 4: Strategist Phase ⛔ BLOCKING

**Objective**: Define the complete slide structure and visual design specification.

**Role definition**: [`references/strategist.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/strategist.md) — the Strategist reads source material, analyzes content structure, and produces the design contract.

#### The Eight Confirmations (Mandatory User Approval)

The Strategist **must** present these 8 items and halt for explicit user confirmation:

| # | Confirmation | Example |
|---|---|---|
| 1 | Canvas format | `ppt169` (16:9 widescreen) |
| 2 | Page count range | 10–12 pages |
| 3 | Target audience | Marketing executives |
| 4 | Style objective | "Professional, data-driven, tech-forward" |
| 5 | Color scheme (HEX) | Primary: `#1976D2`, Secondary: `#42A5F5`, Accent: `#FF6F00` |
| 6 | Icon library selection | `lucide` or `material` |
| 7 | Typography & Formula policy | `mixed` / `render-all` / `text-only` |
| 8 | Image usage guidelines | "AI-generated hero images, no stock photos" |

**LaTeX Formula Rendering**: If the formula policy is `mixed` or `render-all`, equations are collected in `images/formula_manifest.json` and compiled using [`latex_render.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/latex_render.py). This script uses online services (Codecogs, Quicklatex) to output transparent PNG formulas that are added to the image resource pool.

#### Strategist Outputs

| File | Contents |
|---|---|
| `design_spec.md` | Full visual narrative — §I Audience, §II Tone, §III Color, §IV Typography, §V Page Outline, §VI Layout, §VII Charts, §VIII Image Plan |
| `spec_lock.md` | Machine-readable tokens — exact HEX colors, font families, font-size hierarchy (title/subtitle/body/caption/page-number), page rhythm markers (`anchor`/`dense`/`breathing`), page-to-layout-template mapping, page-to-chart-template mapping |

### Step 5: Image Acquisition

**Objective**: Acquire and prepare all external visual assets before SVG generation.

**Trigger**: Active when `design_spec.md §VIII` lists items marked `Acquire Via: ai` or `Acquire Via: web`.

#### Image Generation: Two Paths

| Path | When | Mechanism |
|---|---|---|
| **Path A** (script-based) | User has `IMAGE_BACKEND` configured in `.env` | [`image_gen.py --manifest`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/image_gen.py) runs all Pending items through the configured backend |
| **Path B** (host-native) | AI coding host has built-in image generation (e.g., Antigravity, Claude) | Host generates images from `image_prompts.json` prompts, saves to `images/` |

#### Manifest-Driven Generation (Path A)

The manifest file `images/image_prompts.json` is the single source of truth:

```json
{
  "items": [
    {
      "filename": "hero_cover.png",
      "prompt": "A futuristic cityscape...",
      "aspect_ratio": "16:9",
      "image_size": "1K",
      "status": "Pending",
      "purpose": "Cover page hero image",
      "type": "background"
    }
  ]
}
```

**Status lifecycle**: `Pending` → `Generated` | `Failed` | `Needs-Manual`

**Adaptive concurrency** ([`image_gen.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/image_gen.py) `_run_manifest()`):
- Starts at configurable concurrency (default 3)
- On rate-limit errors: halves concurrency (min 1), requeues the item, waits 10s
- Status is atomically written back after each completion (crash-safe via tmp file + `os.replace`)

**15 pluggable backends** in [`image_backends/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/image_backends/), tiered by support level:

| Tier | Backends |
|---|---|
| **Core** | `gemini`, `openai`, `qwen`, `zhipu`, `volcengine` |
| **Extended** | `stability`, `bfl` (FLUX), `ideogram` |
| **Experimental** | `minimax`, `modelscope`, `siliconflow`, `fal`, `replicate`, `openrouter` |

Each backend implements a `generate(prompt, aspect_ratio, image_size, output_dir, filename, model)` function. Backend selection is via `IMAGE_BACKEND` env var, with provider-specific keys (e.g., `GEMINI_API_KEY`, `OPENAI_API_KEY`).

#### Other Image Tools

| Script | Purpose |
|---|---|
| [`image_search.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/image_search.py) | Search web for CC-licensed images (DuckDuckGo/Bing) |
| [`analyze_images.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/analyze_images.py) | Check aspect ratios and dominant colors without loading pixels into LLM context |

### Step 6: Executor Phase

**Objective**: Generate the raw visual layouts (SVG files) and speaker notes.

**Role definition**: [`references/executor-base.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/executor-base.md)

#### Execution Rules (Strictly Enforced by SKILL.md)

| Rule | Rationale |
|---|---|
| **Sequential page generation** | Pages generated one-by-one in a single continuous pass. Batch generation forbidden. |
| **No sub-agent delegation** | SVG generation is context-dependent; sub-agents lose design context. |
| **No script-generated SVGs** | Cross-page visual consistency depends on per-page authoring with full upstream context. |
| **Per-page `spec_lock.md` re-read** | Prevents context-compression drift (see §1.5). |
| **Hand-written SVGs only** | Each SVG is written directly by the main agent, not templated or looped. |

#### Live Preview

Before SVG generation begins, the system starts a background preview server:

```bash
python3 scripts/svg_editor/server.py <project_path> --live
```

This serves a web UI at `http://localhost:5050` (or 5051 as fallback) that auto-refreshes as SVGs are written to `svg_output/`. Users can click elements and add annotations directly in the browser.

#### Quality Gate

After all SVGs are generated, the quality checker runs:

```bash
python3 scripts/svg_quality_checker.py <project_path>
```

**Any error blocks the export.** The checker enforces 9+ categories of checks (see §6 for full breakdown). The Executor must fix all errors before proceeding.

#### Executor Outputs

| Output | Location |
|---|---|
| SVG pages | `svg_output/slide01.svg`, `slide02.svg`, ... |
| Speaker notes | `notes/total.md` (all notes in a single file, split later) |

### Step 7: Post-Processing & Export

**Objective**: Prepare SVGs and assemble the final PowerPoint deck.

**Three commands run sequentially (order matters)**:

#### 7.1 Split Speaker Notes

```bash
python3 scripts/total_md_split.py <project_path>
```

Splits `notes/total.md` into `notes/slide01.md`, `notes/slide02.md`, etc., matching the SVG filenames. Each per-slide file becomes the speaker notes pane in PowerPoint.

#### 7.2 Finalize SVGs (On-Disk)

```bash
python3 scripts/finalize_svg.py <project_path>
```

Reads `svg_output/` and writes finalized SVGs to `svg_final/`. The finalization pipeline runs these transformations via [`svg_finalize/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/):

| Module | Transformation |
|---|---|
| [`embed_icons.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/embed_icons.py) | `<use data-icon="lib/name"/>` → inline `<g>` with vector paths from icon library |
| [`embed_images.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/embed_images.py) | External `<image href="...">` → base64 `data:image/png;base64,...` data URIs |
| [`flatten_tspan.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/flatten_tspan.py) | Positional `<tspan>` elements → independent `<text>` elements |
| [`svg_rect_to_path.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/svg_rect_to_path.py) | Rounded `<rect>` → `<path>` with Bézier curves (browser rendering fidelity) |
| [`fix_image_aspect.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/fix_image_aspect.py) | `preserveAspectRatio` correction for consistent cross-renderer behavior |
| [`crop_images.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/crop_images.py) | Image crop processing |

The `svg_final/` output is self-contained — renders correctly in IDEs, web browsers, and image viewers without external dependencies.

#### 7.3 Export to PPTX

```bash
python3 scripts/svg_to_pptx.py <project_path>
# Optional: --merge-paragraphs for paragraph-level editable text frames
```

**Dual pipeline architecture** — the export does NOT read `svg_final/`:

```
                  ┌──► finalize_svg.py ──► svg_final/ ──► Browser / IDE previews
                  │
[svg_output/] ────┤
                  │
                  └──► svg_to_pptx.py ──► In-memory transforms ──► exports/*.pptx
```

**Why?** `svg_to_pptx.py` reads `svg_output/` directly and applies the same transformations (icon expansion, tspan flattening) **in memory**. This preserves editable PowerPoint elements (e.g., rounded rectangle corner handles) that would be lost if it read the flattened `svg_final/` output.

**Export process** ([`pptx_builder.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/pptx_builder.py)):

1. Create base PPTX with `python-pptx` (set slide dimensions, add blank layouts)
2. Save to temp file, extract as ZIP
3. For each SVG:
   - Run `convert_svg_to_slide_shapes()` → get slide XML + media files + relationships + animation targets
   - Write slide XML to `ppt/slides/slideN.xml`
   - Write media to `ppt/media/`
   - Write relationships to `ppt/slides/_rels/slideN.xml.rels`
   - Inject speaker notes as `ppt/notesSlides/notesSlideN.xml`
   - Inject narration audio if present
   - Inject transition and animation timing XML
4. Update `[Content_Types].xml` with media types
5. Verify all internal relationship targets resolve (dangling-reference check)
6. Re-pack as ZIP → final `.pptx`

**Three export modes**:

| Mode | Flag | Description |
|---|---|---|
| **Native shapes** | `--native` (default) | Full DrawingML conversion — shapes are editable in PowerPoint |
| **SVG embed** | `--no-native` | SVG embedded as image — viewable but not editable |
| **Compatibility** | `--compat` | PNG + SVG dual format — works in older Office versions |

---

## 4. DrawingML Translation Engine

The core translation engine lives in [`svg_to_pptx/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/) (18 modules, ~250KB total). It parses SVG XML elements and writes equivalent DrawingML shapes into PowerPoint's slide XML.

### 4.1 Element Dispatch Architecture

The entry point is [`drawingml_converter.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_converter.py) function `convert_svg_to_slide_shapes()`:

```
SVG File
   │
   ├─ 1. Expand <use data-icon="..."> placeholders (use_expander.py)
   ├─ 2. Flatten positional <tspan> (tspan_flattener.py)
   ├─ 3. Collect <defs> into {id: element} dictionary
   ├─ 4. Check for unsupported visual elements (bail if found)
   │
   └─ 5. Walk tree → dispatch each element via _CONVERTERS table:
         │
         ├─► <rect>     → convert_rect()      symmetric roundRect or custGeom Bézier
         ├─► <circle>   → convert_circle()     ellipse preset or custGeom ring sector
         ├─► <ellipse>  → convert_ellipse()    ellipse preset
         ├─► <line>     → convert_line()       custGeom or preset line + arrow heads
         ├─► <path>     → convert_path()       custGeom + normalized path commands
         ├─► <polygon>  → convert_polygon()    custGeom closed path
         ├─► <polyline> → convert_polyline()   custGeom open path
         ├─► <text>     → convert_text()       text frame with multi-run paragraphs
         ├─► <image>    → convert_image()      picture shape with MIME matching
         ├─► <g>        → convert_g()          group shape (recursive)
         └─► <svg>      → convert_nested_svg() nested SVG container
```

The dispatch table is defined at line 315 of [`drawingml_converter.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_converter.py#L315-L327):

```python
_CONVERTERS = {
    'rect': convert_rect, 'circle': convert_circle, 'ellipse': convert_ellipse,
    'line': convert_line, 'path': convert_path,
    'polygon': convert_polygon, 'polyline': convert_polyline,
    'text': convert_text, 'image': convert_image,
    'g': convert_g, 'svg': convert_nested_svg,
}
```

Any visual SVG element NOT in this table raises `SvgNativeConversionError`, halting the export. Non-visual tags (`defs`, `title`, `desc`, `metadata`, `style`) are silently skipped.

### 4.2 ConvertContext — Shared State

[`ConvertContext`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_context.py) is a dataclass passed through the entire recursive tree walk. Key fields:

| Field | Type | Purpose |
|---|---|---|
| `defs` | `dict[str, Element]` | All `<defs>` children indexed by id |
| `id_counter` | `int` | Auto-incrementing shape ID allocator (starts at 2; 1 = spTree root) |
| `translate_x/y` | `float` | Accumulated translation from parent `<g>` transforms |
| `scale_x/y` | `float` | Accumulated scale factors |
| `transform_matrix` | `tuple[6 floats]` | Full affine matrix for elements that support it (images) |
| `inherited_styles` | `dict` | Style attributes inherited from parent groups (fill, stroke, opacity) |
| `media_files` | `dict[str, bytes]` | Accumulated media file bytes for the slide |
| `rel_entries` | `list[dict]` | OPC relationship entries to write |
| `anim_targets` | `list` | Top-level `<g id="...">` groups for animation targeting |
| `merge_paragraphs` | `bool` | Opt-in flag for paragraph-level text merging |
| `depth` | `int` | Recursion depth (only depth==0 records anim targets) |

Child contexts are created via `ctx.child(dx, dy, sx, sy)` which accumulates transforms. **Opacity is multiplicative** — parent opacity × child opacity, not a simple override (line 121–131 of `drawingml_context.py`).

### 4.3 Shape Mapping Details

#### Rectangles

| SVG Case | DrawingML Output | Code Path |
|---|---|---|
| `<rect rx="10" ry="10">` (symmetric) | `<a:prstGeom prst="roundRect">` with `adj` value as fraction of shorter side (0–50000) | Preserves interactive corner-radius handle in PowerPoint |
| `<rect rx="10" ry="20">` (asymmetric) | `<a:custGeom>` with cubic Bézier corners using scale factor K ≈ 0.5522847 | PowerPoint has no native asymmetric-corner preset |
| `<rect>` (no rounding) | `<a:prstGeom prst="rect">` | Simplest case |

#### Circles & Donut Charts

| SVG Case | DrawingML Output |
|---|---|
| Normal `<circle>` | `<a:prstGeom prst="ellipse">` |
| Donut arc segment (circle with `stroke-dasharray` where `strokeWidth/radius >= 0.15`) | `<a:custGeom>` containing outer arc → line → inner arc → close. Preserves donut charts at full vector fidelity. |

#### Lines & Arrow Heads

Plain `<line>` → custom geometry path. Lines with `marker-start`/`marker-end` → native `<a:prstGeom prst="line">` so PowerPoint recognizes them for arrow head rendering.

Arrow-head classification ([`drawingml_styles.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_styles.py) `_classify_marker()`):

| SVG Marker Shape | DrawingML `type` |
|---|---|
| 3-vertex closed path/polygon | `triangle` |
| 4-vertex closed path/polygon | `diamond` |
| `<circle>`/`<ellipse>` | `oval` |

Size mapping uses categorical buckets: `markerWidth/Height < 6` → `sm`, `6–12` → `med`, `>12` → `lg`. When `markerUnits="strokeWidth"` (SVG default), ratio-based thresholds apply instead (≤2.0 → sm, 2.0–3.5 → med, ≥3.5 → lg).

#### Paths — Parse → Normalize → EMU

The path pipeline ([`drawingml_paths.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_paths.py)):

1. **Parse**: Tokenize SVG `d` attribute into `PathCommand` objects (M, L, C, Q, A, Z, etc.)
2. **Absolutize**: Convert all relative commands (m, l, c, q, a) to absolute (M, L, C, Q, A)
3. **Normalize**: Reduce to M/L/C/Z only:
   - `S` (smooth cubic) → compute reflected control point → emit `C`
   - `Q` (quadratic Bézier) → convert to cubic using `_quad_to_cubic()` (2/3 rule)
   - `T` (smooth quadratic) → reflect + convert to cubic
   - `A` (arc) → `_arc_to_cubic_beziers()` using SVG spec F.6.5 algorithm (center parameterization, split at 90° segments)
4. **EMU conversion**: Scale all coordinates, compute bounding box, emit DrawingML path commands:
   - `M` → `<a:moveTo><a:pt x="" y=""/></a:moveTo>`
   - `L` → `<a:lnTo><a:pt x="" y=""/></a:lnTo>`
   - `C` → `<a:cubicBezTo><a:pt/>×3</a:cubicBezTo>`
   - `Z` → `<a:close/>`

### 4.4 Fill, Stroke & Effects

[`drawingml_styles.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_styles.py) handles all visual styling:

#### Fill Types

| SVG Input | DrawingML Output | Function |
|---|---|---|
| `fill="#1976D2"` | `<a:solidFill><a:srgbClr val="1976D2"/></a:solidFill>` | `build_solid_fill()` |
| `fill="url(#grad1)"` (linearGradient) | `<a:gradFill><a:gsLst>...</a:gsLst><a:lin ang="..." scaled="1"/></a:gradFill>` | `build_gradient_fill()` |
| `fill="url(#grad2)"` (radialGradient) | `<a:gradFill>...<a:path path="circle">...</a:path></a:gradFill>` | `build_gradient_fill()` |
| `fill="url(#pat1)"` (pattern) | `<a:pattFill prst="lgGrid"><a:fgClr>...<a:bgClr>...</a:pattFill>` | `build_pattern_fill()` |
| `fill="none"` | `<a:noFill/>` | — |

Gradient angle conversion: SVG uses `(x1,y1)→(x2,y2)` vectors; DrawingML uses clockwise angles in 60,000ths of a degree. Conversion: `atan2(y2-y1, x2-x1)` → degrees → × 60,000.

#### Stroke Properties

`build_stroke_xml()` maps SVG stroke attributes to `<a:ln>`:

| SVG Attribute | DrawingML | Notes |
|---|---|---|
| `stroke-width` | `<a:ln w="...">` | EMU conversion |
| `stroke-dasharray` | `<a:prstDash>` or `<a:custDash>` | Preset patterns recognized; custom → proportional to stroke width |
| `stroke-linecap` | `cap="rnd/sq/flat"` | round/square/butt mapping |
| `stroke-linejoin` | `<a:round/>/<a:bevel/>/<a:miter/>` | Direct mapping |
| `marker-start/end` | `<a:headEnd>/<a:tailEnd>` | See §4.3 arrow heads |

#### Shadow & Glow Effects

SVG `<filter>` elements are classified by `classify_filter_effect()`:

| SVG Filter | Classification | DrawingML Output |
|---|---|---|
| `feGaussianBlur` + `feOffset` (non-zero dx/dy) | `shadow` | `<a:outerShdw blurRad="..." dist="..." dir="...">` |
| `feGaussianBlur` without offset | `glow` | `<a:glow rad="...">` |

Shadow mapping nuances:
- **Blur radius**: SVG σ × 2.0 = DrawingML blurRad (matches CSS drop-shadow→box-shadow convention)
- **Alpha scaling**: SVG opacity × 0.75 = DrawingML alpha (PowerPoint renders alpha heavier than SVG)
- **Direction**: `atan2(dy, dx)` → clockwise angle in 60,000ths of degree
- **Alignment**: Inferred from offset direction (opposite corner anchoring)

### 4.5 Group Handling & Transform Composition

[`convert_g()`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_converter.py#L135-L282) converts `<g>` to `<p:grpSp>`:

| Behavior | Implementation |
|---|---|
| **Single-child flattening** | Groups with 1 child and no semantic animation role are flattened (no `<p:grpSp>` wrapper) |
| **Bounding box calculation** | Union of all child bounds in EMU |
| **Identity coordinate mapping** | `chOff/chExt == off/ext` — children keep absolute slide coordinates |
| **Rotation pivot compensation** | SVG `rotate(angle, cx, cy)` rotates around a specific pivot; DrawingML `rot` always rotates around bbox center. The converter computes the offset delta and adjusts `<a:off>`. |
| **Full affine matrix support** | For subtrees containing only images, the full 6-element affine matrix is composed and passed through (handles flips like `translate(cx,cy) scale(-1,-1) translate(-cx,-cy)`) |

---

## 5. Text & Typography Engine

Text is the most complex element in the SVG-to-PPTX translation. PowerPoint text is structured as `<p:txBody>` containing `<a:p>` paragraphs with `<a:r>` runs; SVG text uses `<text>` with inline `<tspan>` elements for styling changes.

### 5.1 The tspan Problem

LLMs commonly generate multi-line text using positionally-placed `<tspan>` elements:

```xml
<text x="100" y="200" font-size="24">
  <tspan x="100" y="200">First Line</tspan>
  <tspan x="100" y="230">Second Line</tspan>
  <tspan x="100" y="260">Third Line</tspan>
</text>
```

**Problem**: DrawingML text frames position text flows relative to the `<p:sp>` bounding box, not by absolute coordinates. Mapping `<tspan y="230">` to a PowerPoint run would collapse all text onto a single line.

### 5.2 tspan Flattener

**Solution**: [`tspan_flattener.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/tspan_flattener.py) (in-memory, used by svg_to_pptx) and [`svg_finalize/flatten_tspan.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/flatten_tspan.py) (on-disk, used by finalize_svg).

The flattener walks every `<text>` element. When it encounters positional `<tspan>` children (those with explicit `x` and `y` or `dy` attributes), it:

1. **Extracts** each positional `<tspan>` with its computed position
2. **Replaces** the parent `<text>` with independent `<text>` elements, one per positional group
3. **Preserves** inline styling `<tspan>` elements (those with only `fill`, `font-weight`, etc.) as children of their new parent `<text>`

**Before**: One `<text>` with 3 positional `<tspan>`s → **After**: Three independent `<text>` elements, each at its own `(x, y)`.

This is critical because the DrawingML converter then maps each independent `<text>` to its own `<p:sp>` text shape with correctly computed position.

### 5.3 Text-to-DrawingML Conversion

[`convert_text()`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/drawingml_elements.py) in `drawingml_elements.py`:

1. **Compute bounding box**: Use font-size × character count to approximate text width (no font metric files), font-size × 1.2 for height (CSS default line-height)
2. **Map font attributes**:
   - `font-family` → `<a:latin typeface="..."/>`
   - `font-size` → `<a:rPr sz="..."/>` (in half-points, so 24pt = sz="2400")
   - `font-weight="bold"` → `<a:rPr b="1"/>`
   - `font-style="italic"` → `<a:rPr i="1"/>`
   - `text-decoration="underline"` → `<a:rPr u="sng"/>`
   - `text-anchor` → `<a:pPr algn="l/ctr/r"/>`
3. **Multi-run paragraphs**: When a `<text>` contains inline `<tspan>` children (non-positional, styling-only), each `<tspan>` becomes a separate `<a:r>` run within a single paragraph, preserving mixed formatting (e.g., bold+normal in one line)
4. **Auto-fit**: The text frame uses `<a:bodyPr wrap="none">` (no word wrap) with shrink-to-fit to avoid text clipping in PowerPoint

### 5.4 Merge Paragraphs Mode

The `--merge-paragraphs` CLI flag (opt-in) activates paragraph-level merging: consecutive `<text>` elements that share the same x-coordinate and have y-spacing consistent with a paragraph flow are merged into a single `<p:sp>` with multiple `<a:p>` paragraphs. This produces text boxes that behave like a word processor in PowerPoint — editable as flowing paragraphs rather than independent shapes.

---

## 6. SVG Quality Checker

[`svg_quality_checker.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_quality_checker.py) (1,491 lines) is the gateway between Step 6 (Executor) and Step 7 (Post-processing). **Any error blocks export.** It validates SVGs against a comprehensive ruleset derived from DrawingML constraints.

### 6.1 Check Categories

| Category | What it checks | Example violation |
|---|---|---|
| **XML Well-formedness** | Valid XML, UTF-8, no BOM issues | `&` used instead of `&amp;` in text |
| **Canvas Dimensions** | viewBox matches project format (e.g., 1920×1080 for ppt169) | viewBox "0 0 960 540" when format is ppt169 |
| **Banned Elements** | No `<mask>`, `<style>`, `<foreignObject>`, `<symbol>+<use>`, `<textPath>`, `<script>`, `<animate*>`, `<iframe>`, `@font-face` | `<foreignObject>` found |
| **Banned Attributes** | No `class` attributes on visual elements (CSS classes have no PPT equivalent) | `class="title-text"` |
| **HTML Entity Check** | No HTML named entities (`&mdash;`, `&copy;`, `&nbsp;`, etc.) — only XML entities allowed | `R&amp;D` is OK; `R&mdash;D` is not |
| **Color Format** | Only `#RRGGBB`, `#RGB`, `rgb(r,g,b)` — no `rgba()`, no CSS named colors | `fill="rgba(25,118,210,0.5)"` |
| **Text Validation** | Font sizes in reasonable range, no empty text, all coordinates present | `<text>` without `x` or `y` attribute |
| **Image Validation** | Images have valid href (file exists or valid data URI), reasonable size | `<image href="../images/missing.png"/>` |
| **Icon Placeholder** | `<use data-icon="...">` references a valid icon in the library | `data-icon="lucide/nonexistent"` |
| **Pattern Fill** | `data-pptx-pattern` must be one of the 45 OOXML preset pattern names | `data-pptx-pattern="invalidName"` |

### 6.2 The OOXML Pattern Preset Enum

Pattern fills use a closed enum — the 45 preset names defined in ECMA-376. The quality checker maintains the full list (`_OOXML_PATTERN_PRESETS`) and rejects any non-matching value:

```python
_OOXML_PATTERN_PRESETS = {
    'pct5', 'pct10', 'pct20', 'pct25', 'pct30', 'pct40', 'pct50',
    'pct60', 'pct70', 'pct75', 'pct80', 'pct90', 'horz', 'vert',
    'ltHorz', 'ltVert', 'dkHorz', 'dkVert', 'narHorz', 'narVert',
    'dashHorz', 'dashVert', 'cross', 'dnDiag', 'upDiag', 'ltDnDiag',
    'ltUpDiag', 'dkDnDiag', 'dkUpDiag', 'wdDnDiag', 'wdUpDiag',
    'dashDnDiag', 'dashUpDiag', 'diagCross', 'smCheck', 'lgCheck',
    'smGrid', 'lgGrid', 'dotGrid', 'smConfetti', 'lgConfetti',
    'horzBrick', 'diagBrick', 'solidDmnd', 'openDmnd', 'dotDmnd',
    'plaid', 'sphere', 'weave', 'divot', 'shingle', 'wave', 'trellis',
    'zigZag',
}
```

### 6.3 Error vs. Warning

| Severity | Behavior | Example |
|---|---|---|
| **Error** | Export blocked. Must be fixed. | Banned element found, missing viewBox |
| **Warning** | Export proceeds, but output may degrade | Icon placeholder unresolved, very large SVG file |

The checker outputs a structured report: per-file error/warning counts, with line numbers and descriptions. Exit code is non-zero if any errors exist.

---

## 7. Animation System

### 7.1 Default Animations (Always Applied)

The PPTX exporter automatically applies slide-level animations without any user configuration:

| Element | Default Animation |
|---|---|
| **Slide transitions** | Fade transition between slides |
| **Entrance effects** | Top-level `<g id="...">` groups receive sequential `appear` entrance effects |

Implementation: [`pptx_animations.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/pptx_animations.py) generates the timing XML (`<p:timing>` / `<p:transition>`) injected into each slide.

**Animation targeting**: During `convert_g()`, top-level groups at `depth==0` whose `id` is non-empty are registered in `ctx.anim_targets`. The animation builder assigns sequential click-to-advance effects to these targets. This means the **SVG group structure directly controls animation order** — the first `<g>` in the SVG source tree animates first.

### 7.2 Custom Animations (Opt-In)

Only activated when the user explicitly requests animation customization. The [`customize-animations`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/customize-animations.md) workflow:

1. **Scaffold**: `python3 animation_config.py scaffold <project_path>` generates `animations.json` with auto-detected targets
2. **Edit**: User modifies per-object effects, timing, and order
3. **Validate**: `python3 animation_config.py validate <project_path>` checks schema
4. **Re-export**: `python3 svg_to_pptx.py <project_path>` reads `animations.json` and applies custom timing

**`animations.json` schema** ([`animation_config.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/animation_config.py)):

```json
{
  "slides": {
    "slide01": {
      "transition": { "type": "fade", "duration": 500 },
      "objects": [
        {
          "target_id": "title-group",
          "effect": "fadeIn",
          "trigger": "onClick",
          "delay": 0,
          "duration": 500
        }
      ]
    }
  }
}
```

### 7.3 Narration Audio

[`pptx_narration.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/pptx_narration.py) handles audio injection:

- Reads `notes/<slideNN>.mp3` or `.wav` files
- Embeds audio as a media relationship in the slide
- Adds an invisible audio shape (`<p:sp>` with `<a:audioFile>`)
- Configures auto-play timing synchronized with slide transitions

The full audio generation workflow is standalone: [`generate-audio`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/generate-audio.md).

---

## 8. Image Generation Subsystem

### 8.1 Architecture Overview

[`image_gen.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/image_gen.py) (769 lines) is the unified CLI for image generation. It uses a **provider-agnostic dispatch pattern**:

```
             ┌─ backend_gemini.py   (google-genai SDK)
             ├─ backend_openai.py   (openai SDK)
IMAGE_BACKEND─┤─ backend_qwen.py    (dashscope)
             ├─ backend_zhipu.py    (bigmodel)
             ├─ backend_volcengine.py (ark SDK)
             ├─ backend_stability.py (REST API)
             ├─ backend_bfl.py      (REST API)
             ├─ backend_ideogram.py (REST API)
             └─ ... (8 more)
```

### 8.2 Provider Configuration

Configuration resolution ([`config.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/config.py)):

1. **Process environment** (wins)
2. **`.env` file** — searched in order: CWD → repo root → `~/.ppt-master/.env`

Required keys per backend:

| Backend | Required Key | Optional Overrides |
|---|---|---|
| gemini | `GEMINI_API_KEY` | `GEMINI_MODEL`, `GEMINI_BASE_URL` |
| openai | `OPENAI_API_KEY` | `OPENAI_MODEL`, `OPENAI_BASE_URL` |
| qwen | `QWEN_API_KEY` or `DASHSCOPE_API_KEY` | `QWEN_MODEL` |
| zhipu | `ZHIPU_API_KEY` or `BIGMODEL_API_KEY` | `ZHIPU_MODEL` |
| volcengine | `VOLCENGINE_API_KEY` or `ARK_API_KEY` | `VOLCENGINE_MODEL` |

### 8.3 Rate Limit Handling

[`backend_common.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/image_backends/backend_common.py) provides `is_rate_limit_error(exc)`:

- Checks HTTP status codes (429, 503)
- Checks exception message patterns ("rate limit", "quota", "too many requests")
- Used by `_run_manifest()` to distinguish rate-limits (requeue) from hard failures (mark Failed)

### 8.4 Manifest Lifecycle

```
Strategist writes image_prompts.json (all items "Pending")
    │
    ▼
image_gen.py --manifest reads manifest
    │
    ├── Batch dispatch (ThreadPoolExecutor)
    │     ├── Success → status="Generated", remove last_error
    │     ├── Rate limit → requeue, halve concurrency, sleep 10s
    │     └── Hard fail → status="Failed", record last_error[:500]
    │
    ├── Atomic manifest write after each completion
    │
    └── Generate image_prompts.md sidecar (render_manifest_md_to_file)
```

### 8.5 Icon System

**Separate from image generation**, the icon system uses pre-existing SVG icon libraries:

| Component | File |
|---|---|
| Icon library directory | [`templates/icons/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/templates/icons/) |
| Icon placeholder in SVG | `<use data-icon="lucide/chart-bar" fill="#1976D2" width="40" height="40" x="100" y="200"/>` |
| On-disk expansion | [`svg_finalize/embed_icons.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_finalize/embed_icons.py) |
| In-memory expansion | [`svg_to_pptx/use_expander.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_to_pptx/use_expander.py) |

The `<use data-icon>` syntax is a project-internal extension — browsers and PowerPoint do not understand it. Both `finalize_svg` and `svg_to_pptx` expand it into inline `<g>` groups containing the icon's native `<path>` elements, with color and scale applied.

### 8.6 Image Palettes — Color Behavior Library

[`references/image-palettes/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-palettes/) (14 preset files + index) is a **prompt-engineering library** that controls how the deck's HEX color values are distributed within AI-generated images. It does NOT supply HEX values — those come from `design_spec.md`. The palette tells the AI image model **how to use** those HEX values.

**Core distinction** (from [`_index.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-palettes/_index.md)):

| Concern | Source | Example |
|---|---|---|
| **What colors** (HEX values) | `design_spec.md` → `spec_lock.md` | Primary: `#1976D2`, Secondary: `#42A5F5` |
| **How to use them** (proportions, roles) | `image-palettes/<chosen>.md` | "Secondary covers ~55% as breathing field; accent appears only in 5-10% as small markers" |

**The 14 presets**:

| Palette | Temperament | Best For |
|---|---|---|
| `cool-corporate` | Stable, professional, restrained | Consulting / B2B / finance |
| `warm-earth` | Friendly, grounded, human | Brand / lifestyle / education |
| `tech-neon` | Energetic, futuristic, high-contrast | AI / SaaS / product launch |
| `editorial-classic` | Refined, magazine, balanced | Journalism / opinion / culture |
| `macaron` | Soft pastel, gentle, approachable | Education / children / onboarding |
| `mono-ink` | High-contrast monochrome with sparse accents | Methodology / manifesto |
| `vivid-launch` | Bold, saturated, attention-grabbing | Product launch / marketing |
| `dark-cinematic` | Premium, atmospheric, low-light | Premium product / entertainment |
| `duotone` | Two-color limited, poster-like | Cultural / cover hero / cinematic |
| `nature-organic` | Earthy, natural, wellness | Environment / outdoor |
| `jewel-tone` | Deep saturated gemstone + gold | Luxury / fashion / heritage |
| `frost-ice` | Near-white field with pale cool accents | Health / medical / premium SaaS |
| `sunset-gradient` | Warm gradient flow (pink→orange→purple) | Lifestyle / creative / travel |
| `earthy-dusty` | Muted desaturated earth tones | Interior / wellness / mindfulness |

**Each palette file contains**:
1. **Compatible renderings table** — which visual styles pair well (✓✓/✓/✗)
2. **Fewshot prompt snippet** — actual example text to splice into image generation prompts, showing exact color proportions and roles

**Example** (from [`editorial-classic.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-palettes/editorial-classic.md)):
> *"Secondary warm cream `#FAF7F2` covers about 55% of the canvas with subtle paper-grain at 8% opacity; primary deep navy `#0F2C4C` carries the dominant data block on the left (about 32%); accent burnt orange `#C2410C` appears as one thin horizontal rule..."*

**Escape hatch**: When no preset fits, the Strategist sets `image_palette: custom` and writes a one-paragraph `image_palette_behavior` describing proportions and roles in prose. At most one candidate per dimension may use `custom`.

### 8.7 Image Renderings — Visual Style Library

[`references/image-renderings/`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-renderings/) (20 preset files + index) is the companion library controlling **visual style** — line quality, texture, depth, material, and mood of AI-generated images.

**Palettes vs. Renderings — the two-axis model**:

```
                    Rendering (HOW it's drawn)
                    │
                    │   vector-illustration
                    │   flat
                    │   glassmorphism
                    │   sketch-notes
                    │   watercolor
                    │   ...20 presets
                    │
 Palette (HOW colors are used) ──── Each AI image prompt gets BOTH:
                    │                 • Rendering style paragraph
                    │                 • Palette proportion rules
                    │                 • Deck's actual HEX values
                    │
                    cool-corporate
                    warm-earth
                    tech-neon
                    ...14 presets
```

**The 20 renderings**, grouped by category:

| Category | Renderings |
|---|---|
| **Modern / commercial** | `vector-illustration`, `flat`, `minimalist-swiss`, `glassmorphism`, `3d-isometric`, `digital-dashboard`, `corporate-photo`, `blueprint`, `editorial` |
| **Hand-drawn / educational** | `sketch-notes`, `ink-notes`, `chalkboard`, `paper-cut` |
| **Narrative / atmospheric** | `watercolor`, `warm-scene`, `screen-print`, `vintage-poster` |
| **Specialty** | `fantasy-animation`, `pixel-art`, `nature` |

**Each rendering file contains**: style paragraph, line/texture/depth notes, deck HEX usage rules, and a fewshot prompt snippet.

### 8.8 The Rendering × Palette Compatibility Matrix

Not all combinations work. The [`image-palettes/_index.md`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/references/image-palettes/_index.md) §4 provides a 20×14 compatibility matrix (✓✓ recommended / ✓ acceptable / ✗ avoid). Examples:

| Combination | Verdict | Reason |
|---|---|---|
| `sketch-notes` + `cool-corporate` | ✓ | Acceptable but sketch-notes has built-in warm tendency |
| `digital-dashboard` + `macaron` | ✗ | Pastel palette clashes with data-dense dashboard aesthetic |
| `glassmorphism` + `frost-ice` | ✓✓ | Perfect — frosted glass panels on near-white field |
| `pixel-art` + `jewel-tone` | ✗ | 8-bit retro aesthetic doesn't pair with deep gemstone tones |

### 8.9 How Palettes & Renderings Flow Through the Pipeline

```
Step 4 (Strategist)
  ├── Auto-selects rendering from design_spec.d Style
  │     └── read_file references/image-renderings/_index.md
  ├── Auto-selects palette from design_spec.e Color Scheme
  │     └── read_file references/image-palettes/_index.md
  ├── Cross-checks compatibility matrix (if ✗, swap to alternate)
  └── Writes choices to spec_lock.md:
        image_rendering: editorial-classic
        image_palette: cool-corporate

Step 5 (Image_Generator role)
  ├── read_file references/image-renderings/<chosen>.md
  ├── read_file references/image-palettes/<chosen>.md
  └── For each image prompt:
        Splice rendering style paragraph + palette proportion rules
        + deck's actual HEX values from spec_lock.md
        → Complete prompt for AI image generation

Note: In Path B (host-native, e.g., Antigravity/Claude Code),
the palette/rendering rules are applied implicitly by the LLM
when composing prompts, rather than by explicit file reads.
```

**Key rule**: Both rendering and palette are **locked for the entire deck** — switching mid-deck creates visual inconsistency across slides.

### 8.10 Standalone Execution (Path A) vs. Host-Native Agent (Path B)

Depending on how PPT Master is executed, API keys and image generation are handled differently:

- **Path A (Standalone/CLI-driven)**: When running the pipeline directly via terminal scripts (e.g., executing `python3 skills/ppt-master/scripts/image_gen.py`), the system requires API keys (such as `GEMINI_API_KEY`, `OPENAI_API_KEY`, or any other provider key listed in §8.2) to be defined in a `.env` file at the root or standard config directories. The Python scripts call the selected LLM APIs directly.
- **Path B (Host-Native Agent)**: When using an agentic coding assistant (such as **Antigravity** or **Claude Code**) to run the pipeline, the assistant intercepts commands or handles tasks natively. The host assistant uses its own built-in credentials and tools (such as the `generate_image` tool) to produce image assets and write them to the `images/` directory. In this mode, a local `.env` file containing LLM API keys is **not required**, as key resolution and generation are delegated to the host platform's secure context.

---

## 9. Live Preview Server

> [!NOTE]
> **Optional Component**: The live preview server is completely optional and is not a mandatory step for PPTX generation. It is designed solely for user preview, live inspection, and click-to-annotate feedback. The pipeline can proceed from SVG generation directly to post-processing and export without ever starting `server.py`.

### 9.1 Architecture

[`svg_editor/server.py`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/scripts/svg_editor/server.py) (616 lines) is a Flask application that provides a browser-based slide preview and annotation system.

```
[Browser UI]  ◄──►  [Flask Server]  ◄──►  [svg_output/ on disk]
                         │
                         ├── GET /api/slides        → List all SVGs with annotation counts
                         ├── GET /api/slide/<name>   → Serve SVG content + annotations
                         ├── POST /api/slide/<name>/annotate → Add annotation to element
                         ├── DELETE /api/slide/<name>/annotate/<id> → Remove annotation
                         ├── POST /api/save-all      → Write annotations back to SVG files
                         ├── POST /api/shutdown       → Graceful server shutdown
                         ├── GET /images/<path>       → Serve project images
                         └── GET /assets/<path>       → Serve extracted media assets
```

### 9.2 Key Features

| Feature | Implementation |
|---|---|
| **Icon inlining** | `_inline_icons()` expands `<use data-icon>` for browser preview |
| **Per-project locking** | `.live_preview.lock` prevents duplicate servers; stale locks auto-recovered |
| **Idle timeout** | Default 900s (normal) / 7200s (live mode); auto-shutdown if no requests |
| **Annotation system** | Click any SVG element → assign a text annotation → annotations stored as `data-edit-target`/`data-edit-annotation` attributes |
| **Auto-refresh** | `--live` mode: frontend polls for new/changed SVGs during generation |
| **Mtime caching** | Thread-safe LRU cache keyed by `(file_path, mtime)` — avoids re-parsing unchanged SVGs |
| **Path traversal guard** | `_safe_svg_path()` uses `resolve() + startswith()` to prevent directory traversal attacks |

### 9.3 Annotation Workflow

1. User starts preview server (auto-started in Step 6, or manually via [`live-preview`](file:///c:/Users/aviji/repo/ppt-master/skills/ppt-master/workflows/live-preview.md) workflow)
2. Clicks an element in the browser → element gets a temporary `_edit_N` id
3. Types annotation text (e.g., "Make this text larger", "Change color to blue")
4. Clicks "Save All" → annotations written back to SVG files as `data-edit-*` attributes
5. The AI reads annotations and applies requested changes
6. Transient `_edit_N` ids are stripped from non-annotated elements on save (reduces SVG pollution)

---

## 10. Dependency Graph & Package Registry

### 10.1 Core Python Dependencies

| Package | Version Constraint | Used By | Purpose |
|---|---|---|---|
| `python-pptx` | ≥0.6.21 | `svg_to_pptx`, `ppt_to_md.py` | PPTX creation and PPTX-to-MD extraction |
| `lxml` | ≥4.9 | `svg_to_pptx` (implicit via python-pptx) | XML parsing and manipulation |
| `Pillow` (PIL) | ≥9.0 | `embed_images`, `crop_images`, `analyze_images` | Image processing, format detection, base64 encoding |
| `flask` | ≥3.0.0 | `svg_editor/server.py` | Live preview web server |
| `PyMuPDF` (fitz) | ≥1.22 | `pdf_to_md.py` | PDF text/image extraction |
| `mammoth` | ≥1.6 | `doc_to_md.py` | DOCX-to-HTML conversion |
| `markdownify` | ≥0.11 | `doc_to_md.py`, `web_to_md.py` | HTML-to-Markdown conversion |
| `openpyxl` | ≥3.1 | `excel_to_md.py` | Excel workbook reading |
| `beautifulsoup4` | ≥4.12 | `web_to_md.py` | HTML parsing for web scraping |
| `requests` | ≥2.28 | `web_to_md.py`, `image_search.py`, `latex_render.py` | HTTP client |
| `curl_cffi` | ≥0.5 | `web_to_md.py` (WeChat) | TLS fingerprint impersonation |
| `CairoSVG` | ≥2.7 (optional) | `pptx_media.py` | SVG-to-PNG rasterization (preferred) |
| `svglib` | ≥0.9 (optional) | `pptx_media.py` | SVG-to-PNG fallback when CairoSVG unavailable |
| `ebooklib` | ≥0.18 | `doc_to_md.py` (EPUB) | EPUB chapter extraction |

### 10.2 Image Backend SDKs (Install Per Backend)

| Backend | SDK Package | Install |
|---|---|---|
| gemini | `google-genai` | `pip install google-genai` |
| openai | `openai` | `pip install openai` |
| qwen | `dashscope` | `pip install dashscope` |
| zhipu | `zhipuai` | `pip install zhipuai` |
| volcengine | `volcengine` | `pip install volcengine` |
| stability | (REST, no SDK) | `requests` only |
| bfl | (REST, no SDK) | `requests` only |
| replicate | `replicate` | `pip install replicate` |
| fal | `fal-client` | `pip install fal-client` |

### 10.3 System Dependencies

| Dependency | Required By | Notes |
|---|---|---|
| `pandoc` | `doc_to_md.py` (legacy formats) | Only for .doc, .odt, .rtf, .tex, .rst, .org, .typ |
| Cairo libraries | `CairoSVG` | Optional; SVG rasterization for compatibility mode |
| Python 3.10+ | All scripts | f-string, `match/case`, union type hints |

---

## 11. Known Constraints & Gotchas

### 11.1 SVG → DrawingML Fundamental Constraints

| SVG Feature | PowerPoint Reality | Impact |
|---|---|---|
| `opacity` on groups | PowerPoint has no group-level opacity | Opacity pushed down to individual child elements |
| `<mask>` | DrawingML has no per-pixel alpha compositing | Must use alternatives: clipPath, stacked gradients, filter shadow |
| `rgba()` colors | DrawingML uses separate `<a:alpha>` child | SVG quality checker blocks `rgba()` — must use `rgb()` + `opacity` |
| CSS `class` selectors | No CSS engine in DrawingML | All styling must be inline attributes |
| `text-overflow`, `word-wrap` | DrawingML uses fixed-size text frames | Text sizing is approximate — auto-shrink-to-fit compensates |
| Nested `<svg>` viewBox scaling | DrawingML has no nested viewport concept | Nested SVGs flattened with computed transforms |
| Complex `<filter>` chains | Only shadow + glow mapped | Multi-stage filters (e.g., blur+colorMatrix+composite) are dropped |

### 11.2 LLM Execution Gotchas

| Gotcha | What Happens | Mitigation |
|---|---|---|
| **Context-compression drift** | Over 10+ slides, the LLM forgets exact color HEX values from early conversation | `spec_lock.md` re-read per page (SKILL.md Rule 8) |
| **"Card grid" monotony** | Without intervention, every page looks like a 2×2 card grid | `page_rhythm` field in `spec_lock.md` — `anchor`/`dense`/`breathing` forces layout variation |
| **Script-generation temptation** | LLMs may try to write a Python loop that generates all slides at once for efficiency | SKILL.md Rule 9 explicitly forbids this — visual consistency depends on per-page authoring |
| **Sub-agent delegation** | Context loss when slides are dispatched to sub-agents | SKILL.md Rule 6 — all SVG generation must stay in the main agent |
| **HTML entity leakage** | LLMs trained on web data often emit `&nbsp;` or `&mdash;` in SVG text | SVG quality checker catches these as errors |

### 11.3 Export Edge Cases

| Edge Case | Behavior | Root Cause |
|---|---|---|
| Empty `<g>` groups | Silently skipped (no empty `<p:grpSp>`) | PowerPoint crashes on zero-child group shapes |
| `<path d="">` (empty path) | Silently skipped | Zero-length path produces invalid custGeom |
| Very large SVG files (>5MB) | Warning, but export proceeds | PowerPoint may lag when opening |
| Circular gradient stops at same position | Collapsed to solid fill | DrawingML gradients require distinct positions |
| `stroke-width="0"` with visible stroke color | Treated as `<a:noFill/>` line | Zero-width strokes are invisible in both SVG and PPT |

### 11.4 Platform-Specific Notes

| Platform | Issue | Workaround |
|---|---|---|
| **macOS** | CairoSVG requires Cairo C libraries | `brew install cairo` before `pip install CairoSVG` |
| **Windows** | `os.replace()` fails if target is open in another process | Atomic manifest writes may fail if a user has the JSON open in an editor |
| **LibreOffice** | DrawingML `custGeom` rendering differs from Microsoft Office | Compatibility mode (`--compat`) uses PNG+SVG dual format |
| **PowerPoint Online** | Limited `custGeom` support | Complex vector shapes may render incorrectly in the web version |

---

*Generated by forensic code analysis of the `ppt-master` repository. All file paths, line numbers, and code references verified against the current codebase.*





