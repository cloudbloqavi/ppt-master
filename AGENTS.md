# AGENTS.md — Developer Instructions

This file contains project guidelines for AI development tools (Claude Code, Codex, GitHub Copilot, etc.)
used during local development of this repository.

> **Runtime agent instructions** are in [`agent_runner/AGENTS.RUNTIME.md`](agent_runner/AGENTS.RUNTIME.md).
> At execution startup, `run_agent.py` copies that file to `AGENTS.md` in the working directory
> (only when no `AGENTS.md` is present, i.e., inside Docker) so the Antigravity SDK discovers it.
> This root file is excluded from the Docker image.

**You MUST read [`core-ppt-master-engine/skills/ppt-master/SKILL.md`](core-ppt-master-engine/skills/ppt-master/SKILL.md) before any PPT generation task or repo modification.** This repository exists to generate presentations; SKILL.md is the authoritative workflow that owns project creation, role switching, serial execution, quality gates, post-processing, export, and every per-step command.

## Project Overview

Presentation Builder is an AI-driven presentation generation system. Multi-role collaboration (Strategist → Image_Generator → Executor) converts source documents (PDF/DOCX/URL/Markdown) into natively editable PPTX with real PowerPoint shapes (DrawingML).

**Core Pipeline**: `Source Document → Create Project → [Template] → Strategist Eight Confirmations → [Image_Generator] → Executor Live Preview → Quality Check → Post-processing → Export PPTX`

## Required Conventions

- **Repo-wide style rules** — when editing prompt files under [`core-ppt-master-engine/skills/ppt-master/references/`](core-ppt-master-engine/skills/ppt-master/references/), Python under [`core-ppt-master-engine/skills/ppt-master/scripts/`](core-ppt-master-engine/skills/ppt-master/scripts/), or any other code/prose in the repo, follow the matching style rule in [`core-ppt-master-engine/docs/rules/`](core-ppt-master-engine/docs/rules/).
- **Markdown language consistency** — Markdown files under `core-ppt-master-engine/skills/ppt-master/workflows/`, `core-ppt-master-engine/skills/ppt-master/references/`, and `core-ppt-master-engine/docs/` are currently single-language per directory. New files mirror the language of their siblings; do not mix English scaffolding with Chinese paragraphs (or vice versa) inside one file. Chat replies are unaffected.
- **Strictly Relative Paths** — Any file link or path reference inside codebase markdown files (.md) MUST be strictly relative. Never use absolute paths (such as `file:///...` or machine-specific prefixes) in repository files.

## Compatibility Boundary

- This repository is a workflow/skill package, not an app or service scaffold.
- Do NOT assume generic-project conventions like `.worktrees/`, `tests/`, or mandatory branch setup unless the user explicitly requests them.
- On conflict with a generic coding skill, prioritize [`core-ppt-master-engine/skills/ppt-master/SKILL.md`](core-ppt-master-engine/skills/ppt-master/SKILL.md) inside this repository.

## Architecture Live Doc

[ARCHITECTURE.md](ARCHITECTURE.md) is the single source of truth for the **engine/runner**
architecture (`agent_runner/`) and the runner-enforced quality stages around the agent
turn. It is a **live document**: it must always reflect the current code.

*   **Scope**: ARCHITECTURE.md documents the runner engine and its enforcement stages, NOT
    the presentation workflow (which `SKILL.md` owns). Keep that boundary — do not
    duplicate SKILL.md content into ARCHITECTURE.md or vice versa.
*   **Maintenance Rule (MANDATORY)**: any agent that adds, changes, or **reverts** an
    architectural behavior — a runner stage, an enforcement gate, a module's
    responsibility, the run lifecycle, or a cross-module contract — MUST update
    ARCHITECTURE.md *in the same change*: revise the affected section, the module map,
    and/or the lifecycle diagram, and bump the `_Last updated:_` line. A change that only
    touches internals with no architectural effect does not require an update. When in
    doubt, update it — a stale architecture doc is worse than a verbose one.

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
* **AGENTS.md Split**: The local repository uses a split convention — `AGENTS.md` (this file) is the dev-tool instructions file; `agent_runner/AGENTS.RUNTIME.md` is the runtime system instructions copied to `AGENTS.md` inside the Docker container at execution startup. If the remote `CLAUDE.md` or `AGENTS.md` contains workflow updates, merge relevant runtime content into `agent_runner/AGENTS.RUNTIME.md` and relevant dev/maintenance content into this file. Never collapse the two back into one file.
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
