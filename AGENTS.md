# AGENTS.md

This file is the project entry point for general AI agents.

**You MUST read [`core-ppt-master-engine/skills/ppt-master/SKILL.md`](core-ppt-master-engine/skills/ppt-master/SKILL.md) before any PPT generation task or repo modification.** This repository exists to generate presentations; SKILL.md is the authoritative workflow that owns project creation, role switching, serial execution, quality gates, post-processing, export, and every per-step command. The rest of this file only points to where related material lives — it never substitutes for SKILL.md.

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

## Required Conventions

- **Repo-wide style rules** — when editing prompt files under [`core-ppt-master-engine/skills/ppt-master/references/`](core-ppt-master-engine/skills/ppt-master/references/), Python under [`core-ppt-master-engine/skills/ppt-master/scripts/`](core-ppt-master-engine/skills/ppt-master/scripts/), or any other code/prose in the repo, follow the matching style rule in [`core-ppt-master-engine/docs/rules/`](core-ppt-master-engine/docs/rules/).
- **Markdown language consistency** — Markdown files under `core-ppt-master-engine/skills/ppt-master/workflows/`, `core-ppt-master-engine/skills/ppt-master/references/`, and `core-ppt-master-engine/docs/` are currently single-language per directory. New files mirror the language of their siblings; do not mix English scaffolding with Chinese paragraphs (or vice versa) inside one file. Chat replies are unaffected.
- **Strictly Relative Paths** — Any file link or path reference inside codebase markdown files (.md) MUST be strictly relative. Never use absolute paths (such as `file:///...` or machine-specific prefixes) in repository files.

## Compatibility Boundary

- This repository is a workflow/skill package, not an app or service scaffold.
- Do NOT assume generic-project conventions like `.worktrees/`, `tests/`, or mandatory branch setup unless the user explicitly requests them.
- On conflict with a generic coding skill, prioritize [`core-ppt-master-engine/skills/ppt-master/SKILL.md`](core-ppt-master-engine/skills/ppt-master/SKILL.md) inside this repository.

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
- `core-ppt-master-engine/skills/ppt-master/scripts/docs/` — topic-focused script docs.
- `core-ppt-master-engine/skills/ppt-master/templates/` — layout templates, chart templates, icon library, brand presets.
- `core-ppt-master-engine/skills/ppt-master/workflows/` — standalone workflow files.
- `core-ppt-master-engine/docs/` — user-facing documentation (FAQ, installation, technical design, templates guide, audio narration).
- `core-ppt-master-engine/docs/rules/` — repo-wide style rules.
- `core-ppt-master-engine/examples/` — example projects.
- `core-ppt-master-engine/projects/` — user project workspace.

## Testing

The `agent_runner` engine and the `ppt-master` skill scripts have fast, deterministic,
offline regression tests under [`agent_runner/tests/`](agent_runner/tests/).

*   **Test guide**: [TEST.md](TEST.md) is the single source of truth — it documents the
    test strategy, the per-file inventory, the run commands, and the conventions for
    adding tests.
*   **Run command**: from the repo root,
    ```bash
    python3 -m pytest agent_runner/tests/
    ```
*   **Authoring rule**: whenever you write or change a test to validate or verify a
    specific execution behavior, follow the conventions in `TEST.md` (where the file
    goes, how it is structured, deterministic/offline requirements) **and** update the
    `TEST.md` inventory table. Do not place ad-hoc test scripts elsewhere in the repo.

## Dependency Auditing & EOL Maintenance

To maintain secure, stable, and up-to-date Python dependencies, this project includes an automated dependency audit log.

*   **Dependency Tracking File**: [DEPENDENCIES.md](DEPENDENCIES.md) in the project root lists package versions, latest stable PyPI releases, EOL status, and action recommendations.
*   **Audit Command**: Run the following script to automatically parse requirements, fetch the latest PyPI versions, and refresh `DEPENDENCIES.md` (while preserving manual EOL and custom notes):
    ```bash
    python3 check_dependencies.py
    ```
*   **Auditing Rule**: Any agent running in this workspace MUST review `DEPENDENCIES.md` regularly, execute the check script, and verify package deprecation timelines and compatibility (e.g. NumPy 2.0 API changes).

## Repo Sync & Pre-Merge Guidelines

When merging updates from the upstream remote repository (`https://github.com/cloudbloqavi/ppt-master`), the agent MUST follow these strict rules to preserve this repository's custom directory structure, cleanups, and logic adjustments:

### 1. Directory & Path Mapping
* **Upstream root** corresponds to the local `core-ppt-master-engine/` subdirectory. All upstream files in subfolders (e.g. `skills/`, `docs/`, `projects/`, and root pages `index.html`, `viewer.html`) must be copied to `core-ppt-master-engine/`.
* **Root documentation files** (`AGENTS.md`, `CLAUDE.md`, `README.md`, `SECURITY.md`) reside at the local root. When updated, their internal links and path strings MUST be prefixed with `core-ppt-master-engine/` to match the local structure.

### 2. Cleaned Up Directories (Always Skip)
* Do **NOT** copy or sync the `examples/` directory from the remote.
* Do **NOT** copy or sync the `docs/zh/` directory and the root `README_CN.md` (Chinese documentation and readme files are cleaned up/removed).

### 3. Preserved Local Configurations (Never Overwrite)
* **Root `requirements.txt`**: Do not overwrite this file; it contains local path mappings (`-r core-ppt-master-engine/...`).
* **`core-ppt-master-engine/skills/ppt-master/SKILL.md`**:
  * **Eight Confirmations**: MUST remain **Non-blocking by default** (the agent makes all planning/design decisions autonomously and runs continuously without stopping to wait for user confirmation).
  * **Live Preview**: MUST remain **Disabled by default** (do not start the preview server server.py by default).
* **`.env.example` Files**: Do **NOT** blindly overwrite `.env.example` (both at the root and inside the skill directory). Preserve local custom configurations (e.g. root mandatory runtime variables and optional agent prompt config) and merge them with incoming remote parameters. Translate all Chinese comments, headers, or explanations to English during the merge.
* **CLAUDE.md and AGENTS.md Sync**: If any changes are detected in the remote `CLAUDE.md` during a sync, they must be merged into the local `AGENTS.md` as custom rules or quick references. `CLAUDE.md` itself must always be kept clean and contain only a reference link to `AGENTS.md` to keep documentation fully in sync and avoid duplication.
* **Generic Branding Preservation**: Do not allow the upstream "PPT Master" name to overwrite the local "Presentation Builder" generic branding. Keep human-readable names generic.

### 4. Gitignore Filtering
* **Check against `.gitignore`**: Prior to merging or copying any incoming files from the remote, check their destination path against the local `.gitignore` rules (using a command like `git check-ignore`). Any file matching an ignore pattern must NOT be merged or copied.

### 5. Safe Sync Workflow
1. Add the remote if missing and checkout/export files to a temporary workspace.
2. Selectively copy files to their mapped target paths. Prior to copying any file, check its destination path against local `.gitignore` rules (using `git check-ignore <path>`). If it is flagged as ignored, skip copying it.
3. Re-apply path prefixing (`core-ppt-master-engine/`) to any root documentation changes.
4. Run the branding normalization utility to automatically translate all incoming "PPT Master" occurrences to "Presentation Builder":
   ```bash
   python3 normalize_branding.py
   ```
5. Run `git reset` to unstage everything, ensuring all synced changes remain in the working tree for manual review and commit.

### 6. CJK (Chinese) Character Filtering & Translation
* **Zero Chinese Characters Rule**: The project repository must remain entirely in English. If a merge or conflict resolution from the remote repository introduces files, text, comments, or documentation containing Chinese characters:
  * **Conflict Resolution**: During a merge, if conflicts arise in files containing Chinese characters, prioritize resolving them to preserve the logical structure, then translate the resolved Chinese text into natural English.
  * **Automatic Scanning**: Run the scanner to audit the codebase for CJK characters:
    ```bash
    python3 core-ppt-master-engine/skills/ppt-master/scripts/check_cjk.py --scan
    ```
  * **Automatic Translation**: Run the translation tool using the Gemini API (ensuring `GEMINI_API_KEY` is present in your environment or `.env` file) to automatically translate comments, docstrings, config values, and Markdown contents:
    ```bash
    python3 core-ppt-master-engine/skills/ppt-master/scripts/check_cjk.py --translate
    ```
  * **Single File Target**: To scan or translate specific files (e.g., modified files or conflicts):
    ```bash
    python3 core-ppt-master-engine/skills/ppt-master/scripts/check_cjk.py --scan --files path/to/file1.py path/to/file2.md
    python3 core-ppt-master-engine/skills/ppt-master/scripts/check_cjk.py --translate --files path/to/file1.py
    ```
  * **Deck Directory Renaming**: Rename any template decks or directories containing Chinese characters to their standard lowercase-with-underscore English IDs (e.g. `china_telecom`, `cmb`, `powerchina_standard`) and update all corresponding index maps (`decks_index.json`) and spec references.
  * **Punctuation Standards**: Replace full-width CJK punctuation marks (e.g. colons `：`, parentheses `（）`, quotes `「」`, enumeration commas `、`) with standard ASCII equivalents.
  * **WSL Sync**: Always verify and sync the translation changes to your WSL workspace after the merge.