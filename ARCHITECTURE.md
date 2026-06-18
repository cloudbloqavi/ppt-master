# ARCHITECTURE.md

> **Live document.** This file is the single source of truth for the *engine/runner*
> architecture and MUST be kept in sync with the code. Any AI agent that adds,
> changes, or reverts architectural behavior (a runner stage, an enforcement gate,
> a module responsibility, the run lifecycle, a cross-module contract) MUST update
> this file in the same change. See [AGENTS.md](AGENTS.md) §"Architecture Live Doc".
>
> **Scope boundary.** This file documents the Python **runner engine** (`agent_runner/`)
> and the runner-enforced quality stages around the agent turn. It does NOT document
> the presentation *workflow* (project creation, role switching, SVG generation,
> export) — that authority is [`core-ppt-master-engine/skills/ppt-master/SKILL.md`](core-ppt-master-engine/skills/ppt-master/SKILL.md).
> When the two overlap, SKILL.md wins for workflow and this file wins for the runner.

_Last updated: 2026-06-17 — status sink: ordered Pub/Sub (RUN_ID ordering key) + flush-on-exit + Cloud Run Jobs detection._

---

## 1. Two layers

The system has two cooperating layers:

| Layer | What it is | Where |
|---|---|---|
| **The agent** | A single Gemini turn that internally plays the Strategist → (Image_Generator) → Executor roles, driven by the skill markdown. It reads/writes files, runs scripts, and exports the PPTX. | `core-ppt-master-engine/skills/ppt-master/` (prompts + scripts) |
| **The runner** | A Python harness that wraps that turn: it prepares inputs, launches the agent, enforces quality deterministically *around* the turn, persists artifacts, and guards against silent failure with retries. | `agent_runner/` |

The central design principle: **anything left to the model's in-turn discretion is
unreliable** (the catalog read gets dropped under token pressure; mandated subagents
are not spawned). So quality-critical decisions are either *made by the runner* or
*verified by the runner*, never merely *requested of the model*.

## 2. Runner module map (`agent_runner/`)

| Module | Responsibility |
|---|---|
| `config.py` | CLI args, env validation (`GEMINI_API_KEY`, `OUTPUT_ARTIFACTS_DIR`), logger, `--model` default. Imported first (sets protobuf/encoding env). |
| `core.py` | Orchestration. `main_run()` = retry loop + lifecycle; `run_agent()` = builds system instructions, runs the **catalog match** pre-stage, launches the SDK agent, streams chunks, returns `(usage, subagent_stats, catalog_candidates)`. |
| `catalog_match.py` | **Pre-turn stage.** Runner-side, deterministic template tier selection for Directive prompts (see §4.1). |
| `retheme_enforcement.py` | **Post-turn stage.** Re-themes verbatim raw-template pages (colors + typography) via `scripts/retheme_chart_svg.py`, then rebuilds the deck (see §4.2). |
| `visual_enforcement.py` | **Post-turn stage.** Runner-enforced deterministic layout audit + deck rebuild (see §4.3). |
| `provenance_enforcement.py` | **Post-turn stage.** Validates `chart_provenance.json` + candidate-aware selection check + structural-mimic review (see §4.4). |
| `status_logger.py` | Maps internal events to the non-technical end-user status feed (`--status-progress`). Never leaks internal terms. Pluggable sink: local file and/or GCP Pub/Sub. Pub/Sub publishes with **message ordering** keyed by `RUN_ID` (so on-topic order = emission order) and is **flushed on exit** (`close_status_logging`), so a Cloud Run Job does not drop queued events. |
| `checkpoints.py` / `resumption.py` | Disk-checkpoint resume: detect the furthest-completed stage on disk and continue instead of cold-restarting. |
| `artifacts.py` | Snapshots project/PPTX files, copies outputs to `OUTPUT_ARTIFACTS_DIR`, writes `run_manifest.json`, finalizes log placement. |
| `tools.py` | Workspace self-test (`--self-test`, no API key needed). |
| `logging_setup.py` | File logging + orphan-log sweep. |

## 3. Run lifecycle (`main_run` → `run_agent`)

```
main_run()
  sweep orphan logs → setup logging → check deps → resolve prompt → setup status log
  [resume?] find_and_restore_incomplete_project
  retry loop (RUN_AGENT_MAX_RETRIES, default 3):
    snapshot project files + existing PPTX
    run_agent():
      build system_instructions (+ visual-review override)
      ── PRE-TURN: catalog_match.run_catalog_match() → inject candidates into instructions
      Agent(config).chat(prompt) → stream Thought/Text/ToolCall/ToolResult
      return (usage, subagent_stats, catalog_candidates)
    on success:
      mark all slides ready → record token usage
      ── POST-TURN: enforce_retheme()              (verbatim raw-template pages → project theme + rebuild)
      ── POST-TURN: enforce_visual_review()        (deterministic auditor + rebuild)
      ── POST-TURN: persist chart_candidates.json  (runner writes the audit record)
      ── POST-TURN: enforce_chart_provenance()     (validate + candidate-aware + structural)
    finally: copy_output_artifacts (+ run_manifest.json)
    new PPTX produced?  yes → success/break   no → silent_failure → retry
  finalize_log_placement
```

Web research is **native Google Search grounding** (in-model): it never appears as a
tool call, subprocess, or subagent.

## 4. Runner-enforced quality stages

These are the three stages that exist because the model cannot be trusted to do them
reliably on its own. All are **fail-open**: any internal error is logged and the run
proceeds; none of them currently *fail* a run (they enforce/repair and report).

### 4.1 Catalog match (pre-turn) — `catalog_match.py`
- **Problem:** the Strategist drops the company-catalog read under token pressure, so
  identical Directive prompts pick company templates in one run and silently fall to
  stock/custom in the next.
- **Mechanism:** for a **Directive** prompt (enumerated slides), the runner extracts
  per-slide intents, makes **ONE normal LLM completion** (not a subagent) over the 30
  company + 71 stock catalog summaries, ranks company-first candidates per slide, and
  injects them into `system_instructions`. The catalog is therefore consulted *by
  construction*; the model still makes the final tier call (company/stock/custom/none)
  with theme/layout in view. **Brief** prompts skip this and stay model-driven.
- **Artifact:** the runner writes `chart_candidates.json` into the project folder
  itself (does not trust the model to), so the audit record always exists.

### 4.2 Raw-template re-theme (post-turn) — `retheme_enforcement.py`
- **Problem:** a few company templates (`16`, `23`–`32`) are **raw PowerPoint exports**
  (filter-laden, huge, flattened). The model cannot redraw them faithfully — it gives
  up and free-designs, losing the distinctive infographic — yet they must still adopt
  the project theme. Copy-verbatim alone keeps the original (off-theme) palette; adapt-
  from-scratch themes correctly but loses the design. A raw export can satisfy neither
  requirement by model effort alone.
- **Mechanism:** the **Executor copies a raw company template verbatim** and edits only
  `<text>` (per [executor-base.md](core-ppt-master-engine/skills/ppt-master/references/executor-base.md)
  §"Per-page chart reference" raw-export exception); then the runner **re-themes those
  pages deterministically** with `scripts/retheme_chart_svg.py` — a find-and-map over the
  SVG's small color + font vocabulary (neutrals→theme neutral ramp by luminance,
  chromatics→theme accents by prominence, font families→typography roles), touching no
  geometry, text, or sizes. A page is "raw" when its referenced template carries
  `<filter>`/`feGaussianBlur` or exceeds ~20 KB (same fingerprint as `lint_chart_catalog.py`).
- **Why deterministic:** the earlier "let the model re-skin it" attempt was unreliable and
  was reverted. A script over ~6 hex codes + a handful of font stacks is not — same
  "decide/verify in the runner, don't trust in-turn discretion" principle as §4.1.
- **Rebuild:** runs *before* §4.3 so the layout auditor sees the final themed fonts, and
  re-exports the deck (shared `_reexport`) so the themed SVGs reach the PPTX. Fail-open.
- **Verbatim-compliance check:** the Executor must *copy* a raw template (rule 9 carve-out
  in [SKILL.md](core-ppt-master-engine/skills/ppt-master/SKILL.md)); when it instead rebuilds
  the infographic from scratch, the page comes out far smaller than the template. This stage
  flags that (`not_verbatim`) so the loss of the branded design is surfaced, not silent.
- **Auditor protection:** this stage stamps verbatim pages with `data-verbatim-template`.
  The §4.3 layout auditor's relocation fixers (D1/D2/D3) misfire on these dense flattened
  templates (reading tightly-packed-but-correct labels as overlaps, e.g. D2×103 on the
  pristine template), so on marked pages it runs **D4 (text-shrink) only** and drops the
  relocation findings as false positives — the professional layout is preserved.

### 4.3 Visual review (post-turn) — `visual_enforcement.py`
- **Problem:** the agent narrates Step 6 visual review without actually running it.
- **Mechanism:** the runner independently runs the deterministic `svg_layout_auditor.py`,
  which auto-fixes unambiguous defects (text overlap, `y=0` orphan baseline,
  out-of-bounds, D4 text-overflow shrink) in `svg_output/`, and rebuilds the deck if any
  SVG changed (the agent had exported from the un-fixed SVGs). Honors `--no-visual-review`.

### 4.4 Chart provenance + structural review (post-turn) — `provenance_enforcement.py`
- **Problem:** template selection quality and structural fidelity were unverifiable.
- **Checks:**
  - `chart_provenance.json` present when the deck has chart pages; well-formed; tiers
    valid; company/stock references exist on disk under the right path.
  - **Strategist-skipped:** all entries `confirmed_by: executor` → the Strategist never
    wrote provenance (issue).
  - **Candidate-aware:** if `chart_candidates.json` shows a company candidate existed for
    a page but a non-company tier was chosen with no `decision` reason → issue.
  - **Coverage advisory:** chart deck with zero company-tier pages → `catalog_skip_suspected`
    warning (advisory only — legitimate decks may have no company match).
  - **Structural-mimic review:** company/stock slides compared against their reference
    SVG topology; custom slides skipped.

## 5. Design principles

1. **Runner-enforced, not model-trusted** — quality-critical work is made or verified by
   the runner (§4), because in-turn model discretion is unreliable.
2. **Decide vs. validate** — a validator can only enforce a decision's *presence/format*,
   never its *quality*. To make a decision reliable, move *where* it is made (the catalog
   match stage), then keep validation as the safety net.
3. **Fail-open** — enforcement never breaks a run; it repairs/reports and lets the
   pipeline finish.
4. **Deterministic where possible** — prefer a deterministic script (layout auditor) or a
   narrow single LLM call (catalog match) over a full agent turn or a subagent.
5. **Honest reporting** — status lines and logs state what actually happened (e.g. never
   claim visual review passed if it did not run).

## 6. Tests

Fast, deterministic, offline regression tests live under
[`agent_runner/tests/`](agent_runner/tests/); LLM/network calls are mocked. See
[TEST.md](TEST.md) for the inventory and conventions.
