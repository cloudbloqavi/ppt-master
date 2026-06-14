"""
Runner-enforced visual review (deterministic layout audit + auto-fix).

The agent's own "Step 6 visual review" is narrated but not reliably executed —
a model optimizing for completion emits the milestone header and skips the work,
so text-overlap / out-of-bounds defects ship unfixed. This module makes the
review a CONCRETE, runner-controlled stage that cannot be skipped or faked:

  1. Locate the project folder(s) the agent just produced.
  2. Run ``svg_layout_auditor.py`` (deterministic geometry checks + auto-fix of
     the unambiguous cases) over ``svg_output/``.
  3. If any SVG was changed, re-run ``finalize_svg.py`` + ``svg_to_pptx.py`` so
     the exported PPTX reflects the fixes (the agent had already exported from
     the un-fixed SVGs).
  4. Return a structured, honest result the runner logs verbatim — including the
     "did not run / skipped / N unresolved" states. No fabricated reasons.

Respects ``--no-visual-review``: when opted out, the stage is skipped and that
fact is logged truthfully (never dressed up as "passed").
"""

from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

from agent_runner.config import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILL_SCRIPTS = _REPO_ROOT / "core-ppt-master-engine" / "skills" / "ppt-master" / "scripts"
_AUDITOR = _SKILL_SCRIPTS / "svg_layout_auditor.py"
_FINALIZE = _SKILL_SCRIPTS / "finalize_svg.py"
_EXPORT = _SKILL_SCRIPTS / "svg_to_pptx.py"

_PROJECT_ROOTS = [
    _REPO_ROOT / "core-ppt-master-engine" / "projects",
    _REPO_ROOT / "projects",
]


def _find_active_project_dirs(start_time: float | None) -> list[Path]:
    """Return project folders containing svg_output/*.svg touched during this run.

    Falls back to all projects with SVGs when no start_time is available.
    """
    found: list[Path] = []
    for root in _PROJECT_ROOTS:
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            svg_dir = d / "svg_output"
            if not (d.is_dir() and svg_dir.is_dir()):
                continue
            svgs = list(svg_dir.glob("*.svg"))
            if not svgs:
                continue
            if start_time is None:
                found.append(d)
                continue
            try:
                if any(s.stat().st_mtime >= start_time - 2 for s in svgs):
                    found.append(d)
            except OSError:
                found.append(d)
    return found


def _run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _reexport(project_dir: Path) -> bool:
    """Re-finalize SVGs and re-export the PPTX after auto-fixes changed svg_output.

    Mirrors SKILL.md Step 7.2-7.3. The agent already produced a deck from the
    un-fixed SVGs; this regenerates it from the corrected sources and removes the
    stale deck(s) — but only once a fresh PPTX is confirmed on disk, so a failed
    re-export never destroys the agent's output.
    """
    exports_dir = project_dir / "exports"
    stale = set(exports_dir.glob("*.pptx")) if exports_dir.is_dir() else set()
    try:
        rc, out, err = _run([sys.executable, str(_FINALIZE), str(project_dir)], timeout=600)
        if rc != 0:
            logger.error("  Visual-review re-export: finalize_svg failed (rc=%d): %s",
                         rc, (err or out)[:500])
            return False
        rc, out, err = _run([sys.executable, str(_EXPORT), str(project_dir)], timeout=600)
        if rc != 0:
            logger.error("  Visual-review re-export: svg_to_pptx failed (rc=%d): %s",
                         rc, (err or out)[:500])
            return False
    except subprocess.TimeoutExpired as exc:
        logger.error("  Visual-review re-export timed out: %s", exc)
        return False

    fresh = set(exports_dir.glob("*.pptx")) if exports_dir.is_dir() else set()
    new_decks = fresh - stale
    if not new_decks:
        logger.error("  Visual-review re-export produced no new PPTX — keeping the existing deck.")
        return False

    # Remove the decks built from un-fixed SVGs now that a corrected one exists.
    for old in stale:
        try:
            old.unlink()
            logger.info("  Removed stale pre-fix deck: %s", old.name)
        except OSError as exc:
            logger.warning("  Could not remove stale deck %s: %s", old.name, exc)
    logger.info("  Re-exported corrected deck: %s", ", ".join(p.name for p in new_decks))
    return True


def _audit_project(project_dir: Path) -> dict:
    """Run the deterministic auditor (auto-fix on) over one project."""
    rc, out, err = _run([sys.executable, str(_AUDITOR), str(project_dir)], timeout=600)
    try:
        summary = json.loads(out)
    except json.JSONDecodeError:
        logger.error("  Auditor produced no parseable summary for %s (rc=%d): %s",
                     project_dir.name, rc, (err or out)[:500])
        return {"project": project_dir.name, "error": "auditor_unparseable",
                "pages": 0, "fixes": 0, "hard_remaining": 0, "reexported": False}

    fixes = int(summary.get("total_fixes_applied", 0))
    result = {
        "project": project_dir.name,
        "pages": int(summary.get("pages_audited", 0)),
        "fixes": fixes,
        "hard_remaining": int(summary.get("total_hard_findings", 0)),
        "reexported": False,
    }
    if fixes > 0:
        result["reexported"] = _reexport(project_dir)
    return result


def enforce_visual_review(no_visual_review: bool, start_time: float | None) -> dict:
    """Run the enforced visual-review stage and return an honest result dict.

    Result keys: ``ran`` (bool), ``status`` (one of ``opted_out`` /
    ``no_project`` / ``clean`` / ``fixed`` / ``unresolved`` / ``error``),
    ``projects`` (per-project details), and aggregate counters. The runner logs
    this verbatim — it must never overstate what happened.
    """
    if no_visual_review:
        logger.info("Visual review: SKIPPED (user opted out via --no-visual-review).")
        return {"ran": False, "status": "opted_out", "projects": [],
                "fixes": 0, "hard_remaining": 0}

    if not _AUDITOR.is_file():
        logger.error("Visual review: auditor script not found at %s — cannot enforce.", _AUDITOR)
        return {"ran": False, "status": "error", "projects": [],
                "fixes": 0, "hard_remaining": 0}

    project_dirs = _find_active_project_dirs(start_time)
    if not project_dirs:
        logger.info("Visual review: no project with svg_output/ found to audit.")
        return {"ran": False, "status": "no_project", "projects": [],
                "fixes": 0, "hard_remaining": 0}

    logger.info("")
    logger.info("═" * 60)
    logger.info("ENFORCED VISUAL REVIEW (deterministic layout audit)")
    logger.info("  Projects: %s", ", ".join(p.name for p in project_dirs))
    logger.info("═" * 60)

    per_project = [_audit_project(d) for d in project_dirs]
    total_fixes = sum(p["fixes"] for p in per_project)
    total_hard = sum(p["hard_remaining"] for p in per_project)
    total_pages = sum(p["pages"] for p in per_project)
    any_error = any(p.get("error") for p in per_project)
    # A project that was auto-fixed but whose deck could not be rebuilt: the
    # exported PPTX still shows the defect. This must NOT be reported as "fixed
    # and rebuilt" — it would be a misleading log.
    reexport_failed = any(p["fixes"] > 0 and not p["reexported"] for p in per_project)

    if any_error:
        status = "error"
    elif total_fixes > 0 and reexport_failed:
        status = "fixed_no_export"
    elif total_hard > 0:
        status = "unresolved"
    elif total_fixes > 0:
        status = "fixed"
    else:
        status = "clean"

    logger.info("  Visual review result: %s | pages=%d auto_fixed=%d "
                "unresolved_hard=%d deck_rebuilt=%s",
                status, total_pages, total_fixes, total_hard, not reexport_failed)
    logger.info("═" * 60)
    logger.info("")

    return {
        "ran": True, "status": status, "projects": per_project,
        "pages": total_pages, "fixes": total_fixes, "hard_remaining": total_hard,
        "reexport_failed": reexport_failed,
    }


def status_line(result: dict) -> str:
    """One honest, user-facing status sentence derived from the result dict."""
    status = result.get("status")
    if status == "opted_out":
        return "Visual review skipped (opted out)."
    if status == "no_project":
        return "Visual review did not run: no slides were found to check."
    if status == "error":
        return "Visual review could not complete; slides were left as generated."
    if status == "clean":
        return "Visual review passed: no layout issues found on any slide."
    if status == "fixed_no_export":
        n = result.get("fixes", 0)
        return (f"Visual review corrected {n} slide layout issue(s), but rebuilding the "
                "deck failed - the exported file may still show them.")
    if status == "fixed":
        n = result.get("fixes", 0)
        extra = "" if not result.get("hard_remaining") else \
            f" {result['hard_remaining']} issue(s) still need attention."
        return f"Visual review fixed {n} slide layout issue(s) and rebuilt the deck.{extra}"
    if status == "unresolved":
        return (f"Visual review found {result.get('hard_remaining', 0)} layout issue(s) "
                "that need a closer look.")
    return "Visual review completed."
