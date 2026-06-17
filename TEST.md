# TEST.md

Test strategy, inventory, and run instructions for the **agent_runner** engine and
the **ppt-master** skill scripts it drives.

> For any AI agent: when you write or change a test to validate execution behavior,
> follow [Conventions for new tests](#conventions-for-new-tests) below and update
> the [Test inventory](#test-inventory) table in this file. This file is the single
> source of truth for how testing works in this repo.

## Scope

These are fast, deterministic, **offline** unit/regression tests. They never call
the live agent, the Antigravity SDK, a model, or the network, and never run a real
end-to-end PPTX generation. Each test pins one previously-observed behavior or bug
so a regression is caught in seconds instead of in a 15-minute production run.

End-to-end validation (an actual deck build) is still done by running the engine
itself — see [`run_agent.py`](run_agent.py) usage in [AGENTS.md](AGENTS.md). That is
out of scope here.

## Location & layout

- All tests live in **[`agent_runner/tests/`](agent_runner/tests/)**.
- Files are named `test_<area>.py`; test functions are named `test_*`.
- There is **no `pytest.ini` / `[tool.pytest]` config** — default discovery is used,
  so the directory path is passed explicitly on the command line.
- Tests import engine modules as a package (`from agent_runner import <module>`).
  Skill scripts under `core-ppt-master-engine/.../scripts/` are **not** an importable
  package, so they are loaded by path (see patterns below).

## How to run

Run from the repo root (`ai-builder-engine/`). Works the same in WSL, Linux, and
macOS; on native Windows PowerShell, prefix `PYTHONIOENCODING=utf-8` (see note).

```bash
# Everything
python3 -m pytest agent_runner/tests/

# One file
python3 -m pytest agent_runner/tests/test_status_research_sources.py

# One test function
python3 -m pytest agent_runner/tests/test_checkpoints.py::test_stage_finalized

# Quiet summary / verbose / stop at first failure
python3 -m pytest agent_runner/tests/ -q
python3 -m pytest agent_runner/tests/ -v
python3 -m pytest agent_runner/tests/ -x

# List tests without running them
python3 -m pytest agent_runner/tests/ --collect-only -q
```

Requirements: `pytest` (install with `pip install pytest` if missing; the engine
deps are in [`requirements.txt`](requirements.txt)).

**Windows encoding note.** Some tests assert on output containing Unicode (em-dash,
emoji, flags). On native Windows the default console codec is cp1252 and can raise
`UnicodeEncodeError` while printing. Avoid it by setting the env var for the run:

```bash
# Git Bash
PYTHONIOENCODING=utf-8 python3 -m pytest agent_runner/tests/
```
```powershell
# PowerShell
$env:PYTHONIOENCODING = "utf-8"; python -m pytest agent_runner/tests/
```

**Speed note.** A targeted file runs in seconds. The **full** suite is slower
(minutes) because `test_svg_to_pptx_transform.py` and the provenance tests import
heavy graphics/conversion modules and parse real reference SVGs. When iterating on
one area, run just that file; run the full suite before committing.

## Test inventory

| File | Tests | Covers |
|------|------:|--------|
| [`test_checkpoints.py`](agent_runner/tests/test_checkpoints.py) | 18 | Artifact-driven resume-stage detection (`agent_runner.checkpoints`): builds synthetic project folders at each pipeline rung in a tmp dir and asserts the correct stage + per-slide resume set, including partial/truncated-artifact cases. |
| [`test_provenance_enforcement.py`](agent_runner/tests/test_provenance_enforcement.py) | 17 | Chart-provenance validation + structural-mimic review (`agent_runner.provenance_enforcement` and `chart_structural_review.py`). Uses **real** powerslides reference SVGs so on-disk checks and topology signatures exercise actual files. Skips if the catalog is absent. |
| [`test_catalog_match.py`](agent_runner/tests/test_catalog_match.py) | 13 | Runner-side catalog match (`agent_runner.catalog_match`): Directive/Brief intent extraction, company-first candidate ranking with a mocked LLM, hallucinated-key filtering, injection-block rendering, and `chart_candidates.json` persistence. |
| [`test_retheme.py`](agent_runner/tests/test_retheme.py) | 20 | Deterministic raw-template re-theme (`scripts/retheme_chart_svg.py` + `agent_runner.retheme_enforcement`): palette role-mapping (neutrals by luminance, chromatics by prominence), font-role classification + quote-safe emission, structure-preserving apply, raw-template detection, per-project re-theme of verbatim company pages, the not-verbatim compliance flag (page far smaller than its template ⇒ rebuilt-from-scratch), and **page-id→file resolution for the real numbered convention** (`P01` → `01_campaign_calendar.svg`, the regression that silently no-opped the whole stage on real decks). Real templates; `_reexport` monkeypatched. |
| [`test_svg_doctor.py`](agent_runner/tests/test_svg_doctor.py) | 19 | `svg_doctor.py` single-SVG lint + auto-fix + **ingestion sanitization**. Exercises all finding classes: AUTO-FIX (mechanical), REVIEW (judgment, never auto-edited), INFO (advisory, never gates — raw-export intrinsic properties like mirrored transforms/oob/heavy), and the SECURITY scan for untrusted SVGs (event handlers + `javascript:` stripped as visual no-ops; external refs/`data:`/DTD held as REVIEW), plus the `--ingest` gate (rejects on any active/external construct even when auto-stripped) and the shareable Markdown `--report`. |
| [`test_svg_to_pptx_transform.py`](agent_runner/tests/test_svg_to_pptx_transform.py) | 5 | Leaf-`<path>` affine transform baking in `svg_to_pptx` (matrix/scale/flip not collapsed to the origin — the boat-tier pyramid bug). Skips if the `svg_to_pptx` package is unavailable. |
| [`test_status_research_sources.py`](agent_runner/tests/test_status_research_sources.py) | 8 | Research-source citation timing in `status_logger`: (1) a populated `[[RESEARCH_SOURCES]]` manifest larger than the scan window must emit when its block closes, not only when a later marker reappears (streaming-delta replay); (2) sources emit early at brief-write time from the `## Sources` section (content read from the write call's args, since writes have no ToolResult), with label→name capture and domain-dedup against the model's later manifest. |
| [`test_svg_layout_auditor.py`](agent_runner/tests/test_svg_layout_auditor.py) | 11 | `D2_text_overlap` / `D3_out_of_bounds` / `D4_text_overflow` auto-fixers in `svg_layout_auditor.py` — overlapping text pairs get separated, off-canvas text gets pulled back in, text overflowing a filled-`<path>`-drawn cell (not just `<rect>`) gets shrunk to fit or honestly left as a soft finding at the 60% floor, `process_page` commits partial progress instead of an all-or-nothing rollback, the D4 shrink is idempotent across repeated audits, `--no-autofix` leaves the SVG untouched, and a `data-verbatim-template` page is protected from D1/D2/D3 relocation (D4-only, relocation findings dropped) while the unmarked control still relocates. |
| [`test_visual_enforcement.py`](agent_runner/tests/test_visual_enforcement.py) | 9 | User-facing `status_line()` in `visual_enforcement.py` — plain-language category breakdown (e.g. "overlapping text") is built from the auditor's raw JSON and never leaks rule codes, and soft (D4) findings are never silently dropped from any status or left uncategorized. |

_Total: 120 tests._ Keep the counts and the total in sync when you add or remove tests.

## Testing strategy / patterns

Reuse these established patterns instead of inventing new harnesses:

- **Import a skill script by path.** Scripts under
  `core-ppt-master-engine/skills/ppt-master/scripts/` are not an importable package.
  Load them with `importlib.util.spec_from_file_location(...)` (see
  `test_svg_doctor.py::_doctor` and `test_provenance_enforcement.py::_load_review_module`).
- **`sys.path`-insert a script subpackage.** For a script package like `svg_to_pptx`,
  insert its parent scripts dir onto `sys.path` once at module top
  (see `test_svg_to_pptx_transform.py`).
- **Synthetic fixtures in `tmp_path`.** Build project folders, spec_lock files, and
  SVGs inside pytest's `tmp_path`. **Never** write into the repo, a real
  `projects/` dir, or an output-artifacts folder.
- **Skip when optional inputs are missing.** Guard a module with
  `pytestmark = pytest.mark.skipif(...)` when it depends on an optional package or an
  on-disk asset (catalog SVGs, the `svg_to_pptx` package) so the suite stays honest
  in trimmed environments.
- **Stream replay + `monkeypatch` for the status logger.** To test the user-facing
  status feed, monkeypatch `status_logger.log_status` to capture events and feed text
  through `_check_text_for_status` / `_check_thought_for_status` in small deltas to
  mimic the SDK stream. Call `reset_run_state()` in an autouse fixture.
- **Regression-first docstrings.** Every test module opens with a docstring naming
  the behavior/bug it locks in and why, so a future failure is diagnosable from the
  test alone.

## Conventions for new tests

When you add a test to validate or verify a specific execution behavior:

1. **Place it** in `agent_runner/tests/` as `test_<area>.py` (extend an existing
   file when the area already has one). Use `test_*` function names.
2. **Open with a docstring** that states the behavior/bug under test and why it
   matters (regression intent), matching the existing files.
3. **Reuse a pattern** from [Testing strategy](#testing-strategy--patterns) above —
   import-by-path for skill scripts, `tmp_path` for filesystem state, `monkeypatch`
   for I/O, `skipif` for optional deps.
4. **Keep it deterministic and offline.** No network, no real SDK/model calls, no
   real agent runs, no wall-clock or random dependence, no writing outside `tmp_path`.
5. **Use relative paths** in any repo file you touch (per
   [AGENTS.md](AGENTS.md) → Required Conventions).
6. **Update this file**: add/adjust the row in the [Test inventory](#test-inventory)
   table (file, count, one-line coverage) and the running total.
7. **Run it**, then run the full suite before committing:
   `python3 -m pytest agent_runner/tests/`.
