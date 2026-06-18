# AGENTS.md — Runtime Instructions

This file contains the runtime system instructions for the Presentation Builder agent.
It is copied to `AGENTS.md` in the working directory at execution startup so the
Antigravity SDK discovers it automatically.

**You MUST read [`core-ppt-master-engine/skills/ppt-master/SKILL.md`](core-ppt-master-engine/skills/ppt-master/SKILL.md) before any PPT generation task.** SKILL.md is the authoritative workflow that owns project creation, role switching, serial execution, quality gates, post-processing, export, and every per-step command. This file only points to where related material lives — it never substitutes for SKILL.md.

## Project Overview

Presentation Builder is an AI-driven presentation generation system. Multi-role collaboration (Strategist → Image_Generator → Executor) converts source documents (PDF/DOCX/URL/Markdown) into natively editable PPTX with real PowerPoint shapes (DrawingML).

**Core Pipeline**: `Source Document → Create Project → [Template] → Strategist Eight Confirmations → [Image_Generator] → Executor Live Preview → Quality Check → Post-processing → Export PPTX`

> Topic-only requests with no source material: run the standalone [`topic-research`](core-ppt-master-engine/skills/ppt-master/workflows/topic-research.md) workflow before SKILL.md Step 1 to gather web materials.
>
> Phase B resumption (split-mode execution): when the user opens a fresh chat and says "resume generating projects/<x>" or similar, run the standalone [`resume-execute`](core-ppt-master-engine/skills/ppt-master/workflows/resume-execute.md) workflow to enter Phase B (SVG generation + export) without re-running Phase A. This can also be triggered automatically for the latest failed runs using `python3 run_agent.py --resume` or `python3 auto_resume.py`.
>
> Decks containing data charts: run the standalone [`verify-charts`](core-ppt-master-engine/skills/ppt-master/workflows/verify-charts.md) workflow between the executor and post-processing steps to calibrate chart coordinates.
>
> Recorded narration / video export: run the standalone [`generate-audio`](core-ppt-master-engine/skills/ppt-master/workflows/generate-audio.md) workflow after post-processing.
>
> Object-level animation tuning: when the user asks to change animation order, effect, timing, or a specific object's reveal behavior, run the standalone [`customize-animations`](core-ppt-master-engine/skills/ppt-master/workflows/customize-animations.md) workflow. Default export already has global animations; do not create `animations.json` unless customization was requested.
>
> Live preview: any time the user mentions "live preview", "preview", "see the effect", or wants to click/select a slide element, run [`live-preview`](core-ppt-master-engine/skills/ppt-master/workflows/live-preview.md). Step 6 does not start it by default (it is disabled by default unless explicitly enabled); the workflow covers post-export re-entry and applying submitted annotations.
>
> Brand identity setup: when the user asks to "set up brand" / "establish brand" / "create brand guidelines", provides a brand asset (logo / brand site URL / branded PPTX / brand PDF), or wants to extract a brand from existing materials, run the standalone [`create-brand`](core-ppt-master-engine/skills/ppt-master/workflows/create-brand.md) workflow. Output goes to `core-ppt-master-engine/skills/ppt-master/templates/brands/<id>/`. Brands apply at SKILL.md Step 3 via the same explicit-path rule as layout templates — the user supplies the brand directory path to apply it; bare brand names never trigger.
>
> Visual self-check: This step is enabled by default (opt-out). The pipeline automatically runs the standalone [`visual-review`](core-ppt-master-engine/skills/ppt-master/workflows/visual-review.md) workflow between the executor and post-processing steps. If the user opts out (e.g., via the `--no-visual-review` CLI argument or explicitly requesting it in their prompt), this step is skipped.

## Subagent and Parallel Execution Policy

Deciding whether to leverage the parallel subagentic approach for background or parallel activities (such as source document processing or batch visual reviews) must be based on a dynamic assessment of system resources:
- **Execution Mode**:
  - **Parallel Mode**: If the host system has sufficient resources, the agent should leverage `invoke_subagent` to execute parallel tasks concurrently.
  - **Sequential Mode**: If resources are constrained or if running in a resource-limited environment, the agent must fall back to sequential execution inside the main parent agent.

## Execution Requirements

- For standalone template creation (no source deck), read [`core-ppt-master-engine/skills/ppt-master/workflows/create-template.md`](core-ppt-master-engine/skills/ppt-master/workflows/create-template.md).
- Technical SVG/PPT constraints live in [`core-ppt-master-engine/skills/ppt-master/references/shared-standards.md`](core-ppt-master-engine/skills/ppt-master/references/shared-standards.md).
- Canvas choices live in [`core-ppt-master-engine/skills/ppt-master/references/canvas-formats.md`](core-ppt-master-engine/skills/ppt-master/references/canvas-formats.md).
- Icon library details live in [`core-ppt-master-engine/skills/ppt-master/templates/icons/README.md`](core-ppt-master-engine/skills/ppt-master/templates/icons/README.md).

## Command Quick Reference

Convenience summary only — full workflow in [`core-ppt-master-engine/skills/ppt-master/SKILL.md`](core-ppt-master-engine/skills/ppt-master/SKILL.md).

```bash
# Source content conversion
python3 core-ppt-master-engine/skills/ppt-master/scripts/source_to_md/pdf_to_md.py <PDF_file>
python3 core-ppt-master-engine/skills/ppt-master/scripts/source_to_md/doc_to_md.py <DOCX_or_other_file>
python3 core-ppt-master-engine/skills/ppt-master/scripts/source_to_md/excel_to_md.py <XLSX_or_XLSM_file>
python3 core-ppt-master-engine/skills/ppt-master/scripts/source_to_md/ppt_to_md.py <PPTX_file>
python3 core-ppt-master-engine/skills/ppt-master/scripts/source_to_md/web_to_md.py <URL>

# Project management
python3 core-ppt-master-engine/skills/ppt-master/scripts/project_manager.py init <project_name> --format ppt169
python3 core-ppt-master-engine/skills/ppt-master/scripts/project_manager.py import-sources <project_path> <source_files_or_URLs...> --move
python3 core-ppt-master-engine/skills/ppt-master/scripts/project_manager.py validate <project_path>

# Resumption & Watchdog (scans output directory for incomplete runs, restores to workspace, and resumes)
python3 run_agent.py --resume
python3 run_agent.py --resume --depth 5
python3 auto_resume.py
python3 auto_resume.py --depth 5

# Running with Visual Review Opt-out (enabled by default)
python3 run_agent.py --no-visual-review --prompt "Your prompt here"

# Status feed → GCP Pub/Sub (auto-enabled on Cloud Run; ordered, keyed by RUN_ID).
# Full local (gcloud auth/ADC + emulator) and hosted (Cloud Run Job) setup with
# separate sections: QUICKSTART.md → "Status Feed → GCP Pub/Sub (Local & Hosted)".

# Image tools and SVG quality check
python3 core-ppt-master-engine/skills/ppt-master/scripts/analyze_images.py <project_path>/images
# Formula rendering — manifest written by Strategist after typography confirmation:
python3 core-ppt-master-engine/skills/ppt-master/scripts/latex_render.py <project_path>
python3 core-ppt-master-engine/skills/ppt-master/scripts/latex_render.py <project_path> --dry-run
python3 core-ppt-master-engine/skills/ppt-master/scripts/latex_render.py <project_path> --providers codecogs,quicklatex,mathpad,wikimedia
# In-pipeline AI image generation — manifest mode (required, even for 1 image):
python3 core-ppt-master-engine/skills/ppt-master/scripts/image_gen.py --manifest <project_path>/images/image_prompts.json
python3 core-ppt-master-engine/skills/ppt-master/scripts/image_gen.py --render-md <project_path>/images/image_prompts.json
# Out-of-pipeline one-off / debug / single-image fixup only (no manifest, no sidecar):
python3 core-ppt-master-engine/skills/ppt-master/scripts/image_gen.py "prompt" --aspect_ratio 16:9 --image_size 1K -o <project_path>/images
python3 core-ppt-master-engine/scripts/svg_editor/server.py <project_path> --live
python3 core-ppt-master-engine/scripts/svg_quality_checker.py <project_path>
python3 core-ppt-master-engine/skills/ppt-master/scripts/animation_config.py scaffold <project_path>  # optional, only for custom object-level animation
python3 core-ppt-master-engine/skills/ppt-master/scripts/animation_config.py validate <project_path>  # optional, before re-export

# Post-processing pipeline: run sequentially, one command at a time
python3 core-ppt-master-engine/skills/ppt-master/scripts/total_md_split.py <project_path>
python3 core-ppt-master-engine/skills/ppt-master/scripts/finalize_svg.py <project_path>
python3 core-ppt-master-engine/skills/ppt-master/scripts/svg_to_pptx.py <project_path>
# Add --merge-paragraphs when the user wants paragraph-level editable text frames instead of one-per-line (default off, see SKILL.md Step 7.3).
```

## Core Directories

- `core-ppt-master-engine/skills/ppt-master/SKILL.md` — main workflow authority.
- `core-ppt-master-engine/skills/ppt-master/references/` — role definitions and technical specifications.
- `core-ppt-master-engine/skills/ppt-master/scripts/` — runnable tool scripts.
- `core-ppt-master-engine/skills/ppt-master/templates/` — layout templates, chart templates, icon library, brand presets.
- `core-ppt-master-engine/skills/ppt-master/workflows/` — standalone workflow files.
- `core-ppt-master-engine/projects/` — user project workspace.

## Path and Output Convention

- **Strictly Relative Paths** — Any file link or path reference inside generated markdown or spec files MUST be strictly relative. Never use absolute paths (such as `file:///...` or machine-specific prefixes).
- **Compatibility Boundary** — This repository is a workflow/skill package, not an app or service scaffold. Do NOT assume generic-project conventions like `.worktrees/`, `tests/`, or mandatory branch setup. On conflict with a generic coding skill, prioritize `SKILL.md` inside this repository.
