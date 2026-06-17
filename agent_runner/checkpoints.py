"""
Artifact-Driven Checkpoint & Resume Module for the Presentation Builder Agent Runner.

The pipeline (see ``core-ppt-master-engine/skills/ppt-master/SKILL.md``) writes a
durable artifact at every stage:

    research brief (projects/<slug>.md)
      → project folder + sources/
        → design_spec.md
          → spec_lock.md           (machine-readable contract; defines page count N)
            → svg_output/P01..PN    (Executor SVG pages)
              → notes/total.md      (speaker notes)
                → svg_final/P01..PN (finalize_svg.py post-processing)
                  → exports/*.pptx  (svg_to_pptx.py — terminal)

Rather than persist a separate checkpoint counter (which can desync from reality
because the agent works pages non-linearly), we DERIVE the furthest-completed
stage from those artifacts on disk. A retry then resumes from that stage with a
precise, path-named directive instead of cold-restarting and redoing work.

This module is pure disk inspection — no agent state, no side effects. Any
failure here falls back to ``None`` so the caller keeps today's cold-restart
behavior (never worse than before).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent_runner.config import logger

# ── Pipeline stages, ordered from earliest to terminal ───────────────────────
STAGE_NONE = "none"               # nothing on disk
STAGE_RESEARCH = "research"       # research brief saved, no project folder yet
STAGE_INIT = "init"               # project folder (+ sources) exists, no design_spec
STAGE_SPEC = "spec"               # design_spec.md exists, spec_lock.md missing/invalid
STAGE_SPEC_LOCKED = "spec_locked"  # spec_lock.md valid, no SVG pages yet
STAGE_SVG_PARTIAL = "svg_partial"  # 0 < valid SVG pages < N
STAGE_SVG_DONE = "svg_done"       # all N SVG pages valid, no speaker notes yet
STAGE_NOTES = "notes"             # notes/total.md present, svg_final incomplete
STAGE_FINALIZED = "finalized"     # svg_final/ has N pages, no exported pptx yet
STAGE_DONE = "done"               # exports/*.pptx present — pipeline complete

# A project folder must carry at least one of these to be a *real* project (vs a
# stray folder the agent created by writing to an invented path). Mirrors the
# structural markers used in artifacts.py._looks_like_project.
_PROJECT_MARKERS = ("design_spec.md", "spec_lock.md", "svg_output", "exports", "svg_final")

# Minimum byte size for an SVG to be considered non-truncated. A crash mid-write
# leaves a short stub; the floor + root-tag check rejects those so resume
# regenerates the page instead of skipping it.
_MIN_SVG_BYTES = 512
_SVG_NAME_RE = re.compile(r"^P\d+\.svg$", re.IGNORECASE)


@dataclass
class ResumeState:
    """Detected pipeline position for one project, plus resume metadata."""
    stage: str
    project_dir: Path | None = None
    project_name: str = ""
    total_pages: int | None = None       # N, from spec_lock page_rhythm
    valid_pages: int = 0                  # count of valid svg_output SVGs
    next_pages: list[int] = field(default_factory=list)  # slide numbers still to author
    research_docs: list[str] = field(default_factory=list)


# ── spec_lock page-count parser ──────────────────────────────────────────────
# Self-contained on purpose: this is core resume infra and must not depend on the
# status-logging module. The canonical parser lives in
# status_logger._get_page_rhythm_from_spec_lock — keep the two in sync if the
# spec_lock `## page_rhythm` format ever changes (see templates/spec_lock_reference.md).
def count_pages(spec_lock_path: Path) -> int | None:
    """Return the slide count N from a spec_lock.md ``## page_rhythm`` block.

    Returns None when the file is absent or has no parseable page entries — which
    the caller treats as "spec_lock not yet valid".
    """
    if not spec_lock_path.exists():
        return None
    try:
        lines = spec_lock_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        logger.warning("checkpoints: failed to read %s: %s", spec_lock_path, exc)
        return None

    count = 0
    in_rhythm = False
    for line in lines:
        s = line.strip()
        if s.startswith("## page_rhythm"):
            in_rhythm = True
            continue
        if in_rhythm:
            if s.startswith("##"):  # next section ends the block
                break
            if s.startswith("-"):
                page_id = s[1:].split(":")[0].lstrip("-").strip()
                if page_id:
                    count += 1
    return count or None


def _valid_svgs(svg_dir: Path) -> list[int]:
    """Return sorted slide numbers of valid (non-truncated) SVGs in *svg_dir*.

    A page counts as valid only if it is named ``P<NN>.svg``, exceeds the minimum
    byte floor, and contains an ``<svg`` root tag — so a half-written file from a
    crash is excluded and will be regenerated on resume.
    """
    if not svg_dir.is_dir():
        return []
    nums: list[int] = []
    for f in svg_dir.iterdir():
        if not f.is_file() or not _SVG_NAME_RE.match(f.name):
            continue
        try:
            if f.stat().st_size < _MIN_SVG_BYTES:
                continue
            head = f.read_text(encoding="utf-8", errors="ignore")[:1024]
        except Exception:
            continue
        if "<svg" not in head:
            continue
        m = re.search(r"\d+", f.name)
        if m:
            nums.append(int(m.group(0)))
    return sorted(nums)


def _looks_like_project(d: Path) -> bool:
    """True when *d* is a real generated project folder, not a stray directory."""
    if not d.is_dir():
        return False
    return any((d / m).exists() for m in _PROJECT_MARKERS)


def find_active_project(roots: list[Path], since_mtime: float) -> Path | None:
    """Return the newest in-progress project folder modified during this run.

    Scans each ``projects/`` root for real project folders touched at/after
    ``since_mtime`` (so a leftover project from an unrelated earlier invocation is
    never picked) and returns the most recently modified one.
    """
    candidates: list[tuple[float, Path]] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for d in root.iterdir():
                if not _looks_like_project(d):
                    continue
                try:
                    mtime = d.stat().st_mtime
                except Exception:
                    continue
                if mtime + 1.0 < since_mtime:  # 1s slack for fs mtime coarseness
                    continue
                candidates.append((mtime, d))
        except Exception as exc:
            logger.warning("checkpoints: failed to scan %s: %s", root, exc)
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def find_research_docs(roots: list[Path], since_mtime: float) -> list[str]:
    """Return top-level ``projects/<slug>.md`` research briefs written this run.

    These exist when an attempt stopped right after topic research (before project
    init) — the common silent-stop trigger. Surfacing them lets the retry reuse
    the research instead of re-running web search.
    """
    docs: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for md in root.glob("*.md"):
                if not md.is_file():
                    continue
                try:
                    if md.stat().st_mtime + 1.0 < since_mtime:
                        continue
                except Exception:
                    continue
                docs.append(str(md.resolve()))
        except Exception as exc:
            logger.warning("checkpoints: failed to scan %s for briefs: %s", root, exc)
    return sorted(set(docs))


def detect_stage(project_dir: Path) -> ResumeState:
    """Classify the furthest-completed pipeline stage for *project_dir* from disk.

    Validation is intentionally stricter than bare existence (valid SVG count,
    parseable spec_lock, non-empty notes) so a partially-written artifact never
    reads as complete.
    """
    state = ResumeState(stage=STAGE_INIT, project_dir=project_dir,
                        project_name=project_dir.name)

    # Terminal: an exported deck already exists.
    exports = project_dir / "exports"
    if exports.is_dir() and any(exports.glob("*.pptx")):
        state.stage = STAGE_DONE
        return state

    spec_lock = project_dir / "spec_lock.md"
    design_spec = project_dir / "design_spec.md"
    total = count_pages(spec_lock)

    # Before the spec is locked we can't reason about page counts.
    if total is None:
        state.stage = STAGE_SPEC if design_spec.exists() else STAGE_INIT
        return state

    state.total_pages = total

    # svg_final/ complete → only export remains.
    final_pages = _valid_svgs(project_dir / "svg_final")
    if len(final_pages) >= total:
        state.stage = STAGE_FINALIZED
        return state

    # Speaker notes generated → finalize + export remain.
    notes_total = project_dir / "notes" / "total.md"
    notes_ready = notes_total.exists() and notes_total.stat().st_size > 0

    out_pages = _valid_svgs(project_dir / "svg_output")
    state.valid_pages = len(out_pages)

    if len(out_pages) >= total:
        state.stage = STAGE_NOTES if notes_ready else STAGE_SVG_DONE
        return state

    if len(out_pages) > 0:
        # Phase 2: per-slide granularity — resume at the first missing page and
        # author the remainder, rather than regenerating the whole deck.
        present = set(out_pages)
        state.next_pages = [n for n in range(1, total + 1) if n not in present]
        state.stage = STAGE_SVG_PARTIAL
        return state

    state.stage = STAGE_SPEC_LOCKED
    return state


# ── Directive composition ────────────────────────────────────────────────────
def _slide_label(n: int) -> str:
    return f"P{n:02d}"


def _resume_action(state: ResumeState) -> str:
    """Return the human-readable 'what to do next' line for a detected stage."""
    sl = state.stage
    if sl == STAGE_SPEC:
        return ("Resume at the Strategist phase: finish writing spec_lock.md from the "
                "existing design_spec.md, then proceed to Executor SVG generation.")
    if sl == STAGE_SPEC_LOCKED:
        return ("Resume at the Executor phase: generate all SVG pages into svg_output/, "
                "then run the quality check, notes, finalize, and export steps.")
    if sl == STAGE_SVG_PARTIAL:
        done = ", ".join(_slide_label(n) for n in sorted(set(range(1, (state.total_pages or 0) + 1)) - set(state.next_pages)))
        todo = ", ".join(_slide_label(n) for n in state.next_pages)
        return (f"Resume mid-deck: pages {done} are already authored and valid in svg_output/. "
                f"Author ONLY the remaining pages ({todo}), in order, then run the quality "
                f"check, notes, finalize, and export steps. Do NOT regenerate the existing pages.")
    if sl == STAGE_SVG_DONE:
        return ("Resume at the end of the Executor phase: all SVG pages exist in svg_output/. "
                "Generate speaker notes (notes/total.md), then run Step 7 — total_md_split.py, "
                "finalize_svg.py, svg_to_pptx.py — to export the PPTX.")
    if sl == STAGE_NOTES:
        return ("Resume at Step 7 post-processing: SVGs and speaker notes are done. Run "
                "total_md_split.py, then finalize_svg.py, then svg_to_pptx.py to export the PPTX.")
    if sl == STAGE_FINALIZED:
        return ("Resume at the final export: svg_final/ is fully post-processed. Run "
                "svg_to_pptx.py to export the PPTX.")
    # STAGE_INIT
    return ("Resume at the Strategist phase: the project is initialized and sources are "
            "imported. Read references/strategist.md and write design_spec.md + spec_lock.md, "
            "then continue through SVG generation and export.")


def build_resume_directive(roots: list[Path], since_mtime: float) -> str | None:
    """Compose the resume directive appended to a retry prompt, or None.

    Returns None when no reusable on-disk state from this run is found (caller then
    falls back to a plain cold-restart directive).
    """
    try:
        project_dir = find_active_project(roots, since_mtime)
    except Exception as exc:
        logger.warning("checkpoints: project discovery failed: %s", exc)
        project_dir = None

    # Case A — a project folder exists: resume precisely from its furthest stage.
    if project_dir is not None:
        try:
            state = detect_stage(project_dir)
        except Exception as exc:
            logger.warning("checkpoints: stage detection failed for %s: %s", project_dir, exc)
            return None
        if state.stage == STAGE_DONE:
            return None  # already complete; nothing to resume

        pages = f" ({state.total_pages} pages)" if state.total_pages else ""
        logger.info("checkpoints: resuming project '%s' from stage '%s'%s.",
                    state.project_name, state.stage, pages)
        return (
            f"An in-progress project ALREADY EXISTS at:\n  {project_dir}\n"
            f"Detected pipeline stage: {state.stage}{pages}.\n"
            "🚫 Do NOT run `project_manager.py init` again and do NOT create a new project "
            "folder — that produces a duplicate phantom project. Write every file under the "
            "exact path above.\n"
            "Do NOT repeat web research and do NOT re-emit the [[RESEARCH_SOURCES]] manifest; "
            "the research and any completed stages are already on disk.\n"
            f"{_resume_action(state)}"
        )

    # Case B — no project folder, but a research brief was saved: reuse research,
    # resume from project initialization.
    docs = find_research_docs(roots, since_mtime)
    if docs:
        doc_list = "\n".join(f"  - {p}" for p in docs)
        logger.info("checkpoints: no project folder; reusing %d saved research brief(s).", len(docs))
        return (
            "Research from the previous attempt is ALREADY SAVED on disk:\n"
            f"{doc_list}\n"
            "Do NOT repeat web research and do NOT re-emit the [[RESEARCH_SOURCES]] manifest. "
            "Import the saved brief via `project_manager.py import-sources` and resume from "
            "project initialization through PPTX export."
        )

    return None


def default_project_roots() -> list[Path]:
    """The two canonical ``projects/`` roots the agent writes into."""
    project_root = Path(__file__).parent.parent.resolve()
    return [
        project_root / "core-ppt-master-engine" / "projects",
        project_root / "projects",
    ]
