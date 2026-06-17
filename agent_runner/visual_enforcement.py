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
import re
import sys
import subprocess
from collections import Counter
from pathlib import Path

from agent_runner.config import logger

# Plain-language names for the auditor's internal rule codes. The status feed
# is the non-technical end-user log — rule codes like "D2_text_overlap" must
# never leak into it, but a category like "overlapping text" tells the user
# what was actually wrong without exposing internals.
_FRIENDLY_RULE_NAMES = {
    "D1_orphan_baseline": "text floating into the header",
    "D2_text_overlap": "overlapping text",
    "D3_out_of_bounds": "text running off the slide edge",
    "D4_text_overflow": "text crowding its card edge",
}
_FIX_LABEL_RE = re.compile(r"^(\w+)\s+x(\d+)$")


def _friendly(rule: str) -> str:
    return _FRIENDLY_RULE_NAMES.get(rule, rule)


def _breakdown_from_pages(pages: list[dict]) -> tuple[Counter, Counter]:
    """Tally (fixed_rule_counts, remaining_hard_rule_counts) from one auditor
    summary's per-page results, for a plain-language breakdown."""
    fixed: Counter = Counter()
    remaining: Counter = Counter()
    for page in pages:
        for label in page.get("fixes_applied", []):
            m = _FIX_LABEL_RE.match(label)
            if m:
                fixed[m.group(1)] += int(m.group(2))
        for finding in page.get("findings", []):
            if finding.get("severity") == "hard" and finding.get("autofix") not in ("applied",):
                remaining[finding.get("rule", "?")] += 1
    return fixed, remaining


def _soft_breakdown_from_pages(pages: list[dict]) -> Counter:
    """Tally remaining soft (D4) findings by rule, regardless of whether a
    shrink-to-fit was attempted — D4 is now partially auto-fixable, so a
    leftover soft finding may be "still too tight even after shrinking",
    not merely "untouched"."""
    soft: Counter = Counter()
    for page in pages:
        for finding in page.get("findings", []):
            if finding.get("severity") == "soft":
                soft[finding.get("rule", "?")] += 1
    return soft


def _format_categories(counter: Counter) -> str:
    """e.g. 'overlapping text and text running off the slide edge' — no counts,
    no rule codes, just the distinct categories involved, for a readable line."""
    names = [_friendly(rule) for rule in counter]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]

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
                "pages": 0, "fixes": 0, "hard_remaining": 0, "soft_remaining": 0,
                "fixed_breakdown": Counter(), "remaining_breakdown": Counter(),
                "soft_breakdown": Counter(), "reexported": False}

    fixed_breakdown, remaining_breakdown = _breakdown_from_pages(summary.get("pages", []))
    soft_breakdown = _soft_breakdown_from_pages(summary.get("pages", []))
    fixes = int(summary.get("total_fixes_applied", 0))
    result = {
        "project": project_dir.name,
        "pages": int(summary.get("pages_audited", 0)),
        "fixes": fixes,
        "hard_remaining": int(summary.get("total_hard_findings", 0)),
        "soft_remaining": int(summary.get("total_soft_findings", 0)),
        "fixed_breakdown": fixed_breakdown,
        "remaining_breakdown": remaining_breakdown,
        "soft_breakdown": soft_breakdown,
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
                "fixes": 0, "hard_remaining": 0, "soft_remaining": 0,
                "fixed_breakdown": Counter(), "remaining_breakdown": Counter(), "soft_breakdown": Counter()}

    if not _AUDITOR.is_file():
        logger.error("Visual review: auditor script not found at %s — cannot enforce.", _AUDITOR)
        return {"ran": False, "status": "error", "projects": [],
                "fixes": 0, "hard_remaining": 0, "soft_remaining": 0,
                "fixed_breakdown": Counter(), "remaining_breakdown": Counter(), "soft_breakdown": Counter()}

    project_dirs = _find_active_project_dirs(start_time)
    if not project_dirs:
        logger.info("Visual review: no project with svg_output/ found to audit.")
        return {"ran": False, "status": "no_project", "projects": [],
                "fixes": 0, "hard_remaining": 0, "soft_remaining": 0,
                "fixed_breakdown": Counter(), "remaining_breakdown": Counter(), "soft_breakdown": Counter()}

    logger.info("")
    logger.info("═" * 60)
    logger.info("ENFORCED VISUAL REVIEW (deterministic layout audit)")
    logger.info("  Projects: %s", ", ".join(p.name for p in project_dirs))
    logger.info("═" * 60)

    per_project = [_audit_project(d) for d in project_dirs]
    total_fixes = sum(p["fixes"] for p in per_project)
    total_hard = sum(p["hard_remaining"] for p in per_project)
    total_soft = sum(p.get("soft_remaining", 0) for p in per_project)
    total_pages = sum(p["pages"] for p in per_project)
    any_error = any(p.get("error") for p in per_project)
    total_fixed_breakdown: Counter = Counter()
    total_remaining_breakdown: Counter = Counter()
    total_soft_breakdown: Counter = Counter()
    for p in per_project:
        total_fixed_breakdown.update(p.get("fixed_breakdown", Counter()))
        total_remaining_breakdown.update(p.get("remaining_breakdown", Counter()))
        total_soft_breakdown.update(p.get("soft_breakdown", Counter()))
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
                "unresolved_hard=%d unresolved_soft=%d deck_rebuilt=%s",
                status, total_pages, total_fixes, total_hard, total_soft, not reexport_failed)
    if total_fixed_breakdown:
        logger.info("  Fixed by category: %s", dict(total_fixed_breakdown))
    if total_remaining_breakdown:
        logger.info("  Still unresolved by category: %s", dict(total_remaining_breakdown))
    logger.info("═" * 60)
    logger.info("")

    return {
        "ran": True, "status": status, "projects": per_project,
        "pages": total_pages, "fixes": total_fixes, "hard_remaining": total_hard,
        "soft_remaining": total_soft, "reexport_failed": reexport_failed,
        "fixed_breakdown": total_fixed_breakdown,
        "remaining_breakdown": total_remaining_breakdown,
        "soft_breakdown": total_soft_breakdown,
    }


def _soft_suffix(result: dict) -> str:
    """Never drop soft findings from the user-facing line — they used to vanish
    silently since only hard_remaining was ever reported. D4 is now partially
    auto-fixable (shrink-to-fit), so name the category and say a fix was
    attempted rather than implying nothing was done."""
    n = result.get("soft_remaining", 0)
    if not n:
        return ""
    cats = _format_categories(result.get("soft_breakdown", Counter()))
    what = f" ({cats})" if cats else ""
    return (f" {n} minor formatting note(s){what} could not be fully resolved "
            f"even after auto-fix and were left as-is.")


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
        return f"Visual review passed: no hard layout issues found on any slide.{_soft_suffix(result)}"
    fixed_cats = _format_categories(result.get("fixed_breakdown", Counter()))
    remaining_cats = _format_categories(result.get("remaining_breakdown", Counter()))
    if status == "fixed_no_export":
        n = result.get("fixes", 0)
        what = f" ({fixed_cats})" if fixed_cats else ""
        return (f"Visual review corrected {n} slide layout issue(s){what}, but rebuilding the "
                f"deck failed - the exported file may still show them.{_soft_suffix(result)}")
    if status == "fixed":
        n = result.get("fixes", 0)
        what = f" ({fixed_cats})" if fixed_cats else ""
        extra = "" if not result.get("hard_remaining") else \
            f" {result['hard_remaining']} issue(s) ({remaining_cats}) still need attention."
        return (f"Visual review fixed {n} slide layout issue(s){what} and rebuilt the "
                f"deck.{extra}{_soft_suffix(result)}")
    if status == "unresolved":
        what = f" ({remaining_cats})" if remaining_cats else ""
        return (f"Visual review found {result.get('hard_remaining', 0)} layout issue(s){what} "
                f"that need a closer look.{_soft_suffix(result)}")
    return "Visual review completed."
