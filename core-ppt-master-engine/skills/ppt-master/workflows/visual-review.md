---
description: Per-page rubric-based visual self-review via parallel subagents. Run after Executor, before post-processing.
---

# Visual Review Workflow

> Standalone post-generation step. Goal: reduce human iteration by letting AI subagents visually self-check each rendered slide against a fixed rubric and apply atomic position/spacing fixes.
>
> Reads `<project>/svg_output/<page>.svg` and a pre-rendered PNG of each slide, then either applies a fix or flags `needs_human`. **Never touches** brand decisions, layout structure, or other files.
>
> This workflow is **independent** — invokable in a fresh chat session with only `<project_path>` as input. No upstream conversation context required.

## Positioning

This is an **opt-out review loop**. The main pipeline (SKILL.md Step 1–7) invokes it by default before Step 7 post-processing, unless the user explicitly opts out (e.g. via `--no-visual-review` CLI argument or prompt instruction).

**Token cost**: each batch subagent re-reads the rubric + `design_spec.md` + `spec_lock.md` and processes K SVG+PNG pairs. For a 20-page deck with K=5, expect on the order of 100–150K additional input tokens on top of the main generation run.

## When to Run

- Executor (SKILL.md Step 6) has finished all pages
- `svg_quality_checker.py` has passed
- Post-processing (`finalize_svg.py`, `svg_to_pptx.py`) has **not** yet run
- By default (unless opted out via the `--no-visual-review` CLI flag or prompt instruction)

For decks containing data charts, run [`verify-charts`](./verify-charts.md) first — visual-review focuses on visual rhythm / collision / alignment, not chart coordinate math.

## When NOT to Run

- The project has no `svg_output/<page>.svg` files yet — finish Executor first
- `svg_quality_checker.py` has not been run or has failed — fix static violations first
- User has already applied annotations via `live-preview` workflow and is in a fixed-edit loop — describe changes directly, do not re-trigger rubric
- The user has explicitly opted out (via `--no-visual-review` CLI flag or prompt instruction)

---

## Prerequisites

```bash
# 1. playwright + chromium installed (the PNG renderer)
pip install playwright
python3 -m playwright install chromium

# 2. live-preview server running for this project (provides inlined SVG fetch)
python3 skills/ppt-master/scripts/svg_editor/server.py <project_path> --no-browser
# (single instance per project — if it's already running, skip)
```

The renderer (`visual_review.py`) does **not** auto-start the live-preview server. It expects the server to be reachable at `http://localhost:5050` (override with `--server-url`).

> **Why playwright, not cairosvg**: cairo's text API has no font-fallback chain, so CJK characters render as tofu boxes for any deck whose font-family list relies on system fallback (Microsoft YaHei / PingFang SC / etc.). Playwright drives a real chromium and produces output identical to what the live-preview browser shows — the only fidelity-preserving option for bilingual decks.

---

## Step 1 — Pre-render all PNGs

```bash
python3 skills/ppt-master/scripts/visual_review.py <project_path>
```

This writes one PNG per page to `<project_path>/.preview/<page>.png` at 1280×720, with `<use data-icon>` inlined and `<image href>` resolved exactly as the live-preview browser sees them. Renders are serialized via a project-local file lock — safe to invoke concurrently.

Exit codes:

- `0` — all pages rendered
- `2` — live-preview server unreachable (start it per Prerequisites)
- `3` — playwright python / chromium not installed (or browser failed to launch)
- `4` — one or more page-level render failures (see stderr; partial output is on disk)

If any page comes back with `"all_background": true` in the JSON summary, that page rendered to a blank surface — investigate before continuing (broken `<use>` reference, missing image asset, etc.).

---

## Step 2 — Spawn the review team (Antigravity SDK Subagent Orchestration)

To parallelize the visual review workflow, the main agent leverages the built-in subagents capability of the Antigravity SDK:

1. **Partition the Slides**: If the number of generated pages $N$ is greater than two ($N > 2$), the main agent SHOULD leverage subagents to execute the reviews in parallel. Partition the pages into batches of $\le K$ pages (default **K = 5**).
2. **Invoke Parallel Subagents**: For each batch, invoke a built-in `self` subagent (or define a custom subagent using `define_subagent` if tool restrictions are desired) in parallel. You can invoke them concurrently using the native `invoke_subagent` tool.
3. **Subagent Configuration**:
   - **Type**: `self` (inherits all tools including file read/write and image viewing) or custom.
   - **System Prompt**: 
     > You are a visual-review subagent. Evaluate the assigned slide SVGs and their pre-rendered PNGs in `.preview/` against the Visual Review Rubric. Back up each slide before editing (`cp` or copy tool to `.review/backup/<page>.iter1.svg`), make precise positioning/alignment fixes directly to the SVG files in-place (do not modify brand colors or copy text), and write a JSON report to `.review/<page>.json` matching §5 of the rubric.
   - **Initial Prompt**: Pass the rubric content, `design_spec.md` context, `spec_lock.md` context, and the list of specific slides (`svg_path` and `png_path`) for the batch.

**Host compatibility**: In the Antigravity SDK environment, the orchestrating agent spawns subagents asynchronously in the background. Each subagent runs independently, performs its file and visual review steps, writes the `.json` report, and signals the parent once it transitions to `Idle`.

---

## Step 3 — Aggregate findings

The orchestrator emits the aggregate Markdown table back to you (the main agent):

```
| page | role | status | hard_hits | soft_hits | fixes_applied | needs_human_reason |
|------|------|--------|-----------|-----------|---------------|---------------------|
```

Statuses:

- `ok` — page passed clean, no fixes applied
- `fixed` — at least one fix applied, all Hard rules now pass
- `needs_human` — fix attempted but rolled back (rule §4.2), or rule violation requires brand/structure decision outside the rubric's scope
- `render_failed` — Iteration 0 PNG sanity failed (rare; usually means renderer / server issue)
- `prereq_failed` — static checker hadn't been run

Plus a brand-token aggregate at `<project>/.review/brand_review.json` if any §1.1 escalations occurred — review this once at the end of the run, not per page.

---

## Step 4 — Decide next move

For each row in the table:

- `ok` / `fixed` — no action; the SVG has been updated in-place (originals are at `<project>/.review/backup/<page>.iter<N>.svg`)
- `needs_human` — read the page's JSON `needs_human_items[].suggested_fix_summary`, decide with the user whether to apply or defer
- `render_failed` — re-run `visual_review.py` for that page only (`--pages <token>`); if it persists, hand off to manual review
- `prereq_failed` — go back and run `svg_quality_checker.py`

If `brand_review.json` is non-empty, that's a single decision applied across the deck (e.g., bump footer text color from `#6E7681` to `#8B949E` — one change, every page benefits). Do this once, then optionally re-run visual-review for the affected pages only.

After the table is clean, continue to post-processing per [`SKILL.md`](../SKILL.md) Step 7:

```bash
python3 skills/ppt-master/scripts/total_md_split.py <project_path>
python3 skills/ppt-master/scripts/finalize_svg.py <project_path>
python3 skills/ppt-master/scripts/svg_to_pptx.py <project_path>
```

---

## Notes & invariants

- **Single source of truth for rules**: [`references/visual-review.md`](../references/visual-review.md). This workflow file is just the orchestration — never restate or paraphrase rules here.
- **Concurrency**: `visual_review.py` serializes renders via `<project>/.preview/.render.lock`. Subagents must never call the renderer directly without the lock.
- **Iteration budget**: default 1 iteration. Bumping to 2 doubles render cost and roughly triples token cost. Only worth it for high-stakes / final-cut decks.
- **Don't-touch (rubric §3)** is hard-enforced by subagents. If you want the subagent to e.g. change a brand color, that is **out of scope** — make the change manually first, then re-render & re-review.
- **Backups**: every modified SVG has a `.review/backup/<page>.iter<N>.svg` rollback anchor. Restore by `cp`.
- **The rubric is not the designer**: it catches collisions, drift, and rhythm errors — it does not improve a fundamentally weak layout. If 80%+ of pages come back `needs_human`, the design spec or the executor's choice of layout patterns is the root cause, not this workflow.
- **Playwright output discipline**: when an agent uses the playwright MCP tool `browser_take_screenshot` directly (outside the `visual_review.py` script), the `filename` parameter is resolved against the CWD (typically the repo root) — passing a bare relative path will create stray directories inside the repository. Always pass an absolute path:
  - One-off probe / ad-hoc inspection → `/tmp/probe-<topic>-<n>.png`
  - Project artifact (replaces what the script would have produced) → `<project_path>/.preview/<page>.png` (absolute)
  - Never write to `<repo>/<anything>.png` or `<repo>/<some_dir>/...` — those are caught by `.gitignore` patterns but the cleanup burden is real

  The `visual_review.py` script handles output paths correctly on its own; this rule only applies to direct playwright MCP usage during interactive exploration or recovery.

---

## Appendix: Iteration loop (opt-in)

Default behavior is single-iteration review: one scan, fix in place, write the report. The full iteration loop in [`references/visual-review.md`](../references/visual-review.md) §4.1 supports:

1. Iteration 1: scan + fix
2. Re-render via `visual_review.py --pages <token>`
3. Iteration 2: re-verify changed elements + scan for new Hard hits
4. Rollback on any new Hard hit introduced by a fix

To enable, set iteration budget = 2 in the orchestrator prompt (this is a prompt-level instruction to subagents; neither `visual_review.py` nor the harness enforces it). Each added iteration roughly doubles render cost and triples token cost on the affected pages — reserve for final-cut runs only.
