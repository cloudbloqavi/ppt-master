"""
Runner-enforced chart provenance validation + structural-mimic review.

The agent is supposed to (1) match each visualization slide to a company/stock
template (company catalog first), (2) record the reconciled choice in
``chart_provenance.json``, and (3) reproduce the matched template's structure.
None of that was verifiable before — so company templates were silently never
selected (0/28 decks) and matched templates were silently redrawn as new shapes.

This module makes both checkable after the turn, mirroring ``visual_enforcement``:

  1. Locate the project folder(s) the agent just produced.
  2. VALIDATE ``chart_provenance.json`` — present when the deck has viz pages,
     well-formed, references exist on disk for company/stock, every ``custom``
     page carries a non-empty reason. Honest failure states, never dressed up.
  3. REVIEW structure — run ``chart_structural_review.py`` (tier-aware: compares
     company/stock slides against their reference SVG topology, skips custom) and
     fold its weak/abandoned counts into the result.

v1 is advisory/report-only: it never fails the run and never rewrites slides — it
surfaces an honest signal the runner logs. (Auto-regeneration on low affinity is
a deliberate later step, gated on field-tuning the affinity thresholds.)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from agent_runner.config import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILL_SCRIPTS = _REPO_ROOT / "core-ppt-master-engine" / "skills" / "ppt-master" / "scripts"
_SKILL_DIR = _SKILL_SCRIPTS.parent
_REVIEW = _SKILL_SCRIPTS / "chart_structural_review.py"

_PROJECT_ROOTS = [
    _REPO_ROOT / "core-ppt-master-engine" / "projects",
    _REPO_ROOT / "projects",
]

_VALID_TIERS = {"company", "stock", "custom"}


def _find_active_project_dirs(start_time: float | None) -> list[Path]:
    """Project folders with svg_output/*.svg touched during this run (mirrors visual_enforcement)."""
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


def _has_page_charts(spec_lock: Path) -> bool:
    """True when spec_lock.md declares at least one ## page_charts entry (deck has viz pages)."""
    if not spec_lock.is_file():
        return False
    try:
        lines = spec_lock.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    in_block = False
    for line in lines:
        s = line.strip()
        if s.startswith("## page_charts"):
            in_block = True
            continue
        if in_block:
            if s.startswith("##"):
                break
            if s.startswith("-") and ":" in s:
                return True
    return False


def _validate_provenance(project_dir: Path) -> dict:
    """Structural validation of chart_provenance.json. Returns issues + page count."""
    prov_path = project_dir / "chart_provenance.json"
    spec_lock = project_dir / "spec_lock.md"
    deck_has_charts = _has_page_charts(spec_lock)

    if not prov_path.is_file():
        # Missing is only a violation when the deck actually has chart pages.
        return {"present": False, "deck_has_charts": deck_has_charts,
                "issues": (["provenance_missing_but_deck_has_charts"] if deck_has_charts else []),
                "entries": 0, "by_tier": {}}

    try:
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"present": True, "deck_has_charts": deck_has_charts,
                "issues": [f"unparseable: {exc}"], "entries": 0, "by_tier": {}}

    issues: list[str] = []
    pages = prov.get("pages") or {}
    by_tier: dict[str, int] = {}
    for page_id, entry in pages.items():
        entry = entry or {}
        tier = entry.get("tier")
        by_tier[tier] = by_tier.get(tier, 0) + 1
        if tier not in _VALID_TIERS:
            issues.append(f"{page_id}: invalid tier {tier!r}")
            continue
        if tier == "custom":
            if not (entry.get("decision") or "").strip():
                issues.append(f"{page_id}: custom page missing required decision reason")
            continue
        # company / stock must carry a key + an on-disk reference.
        key, ref = entry.get("key"), entry.get("reference")
        if not key:
            issues.append(f"{page_id}: {tier} page missing key")
        if not ref:
            issues.append(f"{page_id}: {tier} page missing reference path")
        elif not (_SKILL_DIR / ref).is_file():
            issues.append(f"{page_id}: reference not found on disk ({ref})")
        # company keys must resolve under powerslides_infographics/
        if tier == "company" and ref and "powerslides_infographics/" not in ref.replace("\\", "/"):
            issues.append(f"{page_id}: company tier but reference is not under powerslides_infographics/")

    if deck_has_charts and not pages:
        issues.append("deck has page_charts but provenance lists no pages")

    return {"present": True, "deck_has_charts": deck_has_charts, "issues": issues,
            "entries": len(pages), "by_tier": by_tier}


def _run_structural_review(project_dir: Path) -> dict:
    if not _REVIEW.is_file():
        return {"status": "review_unavailable", "checked": 0, "weak": 0, "abandoned": 0}
    try:
        proc = subprocess.run(
            [sys.executable, str(_REVIEW), str(project_dir)],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        out = proc.stdout or ""
        data = json.loads(out)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        return {"status": "review_error", "error": str(exc),
                "checked": 0, "weak": 0, "abandoned": 0}
    return {"status": data.get("status", "unknown"),
            "checked": int(data.get("checked", 0)),
            "weak": int(data.get("weak", 0)),
            "abandoned": int(data.get("abandoned", 0))}


def _audit_project(project_dir: Path) -> dict:
    validation = _validate_provenance(project_dir)
    result = {"project": project_dir.name,
              "provenance_present": validation["present"],
              "deck_has_charts": validation["deck_has_charts"],
              "issues": validation["issues"],
              "entries": validation["entries"],
              "by_tier": validation["by_tier"]}
    # Only run the structural review when provenance is present and well-formed.
    if validation["present"] and not any(
        i.startswith("unparseable") for i in validation["issues"]
    ):
        result["review"] = _run_structural_review(project_dir)
    else:
        result["review"] = {"status": "skipped", "checked": 0, "weak": 0, "abandoned": 0}
    return result


def enforce_chart_provenance(start_time: float | None) -> dict:
    """Validate provenance + run structural-mimic review. Honest, advisory result dict.

    Status: ``no_project`` / ``no_charts`` / ``invalid`` (provenance violations) /
    ``abandoned`` / ``weak`` / ``clean`` / ``error``. Never raises to the caller;
    never fails the run.
    """
    project_dirs = _find_active_project_dirs(start_time)
    if not project_dirs:
        return {"ran": False, "status": "no_project", "projects": []}

    logger.info("")
    logger.info("═" * 60)
    logger.info("CHART PROVENANCE + STRUCTURAL-MIMIC REVIEW")
    logger.info("  Projects: %s", ", ".join(p.name for p in project_dirs))
    logger.info("═" * 60)

    per_project = [_audit_project(d) for d in project_dirs]

    total_issues = sum(len(p["issues"]) for p in per_project)
    total_company = sum(p["by_tier"].get("company", 0) for p in per_project)
    total_weak = sum(p["review"].get("weak", 0) for p in per_project)
    total_abandoned = sum(p["review"].get("abandoned", 0) for p in per_project)
    total_checked = sum(p["review"].get("checked", 0) for p in per_project)
    any_charts = any(p["deck_has_charts"] or p["entries"] for p in per_project)

    if not any_charts:
        status = "no_charts"
    elif total_issues > 0:
        status = "invalid"
    elif total_abandoned > 0:
        status = "abandoned"
    elif total_weak > 0:
        status = "weak"
    else:
        status = "clean"

    for p in per_project:
        if p["issues"]:
            logger.warning("  [%s] %d provenance issue(s): %s",
                           p["project"], len(p["issues"]), "; ".join(p["issues"][:6]))

    logger.info("  Provenance result: %s | company_pages=%d structural_checked=%d "
                "weak=%d abandoned=%d issues=%d",
                status, total_company, total_checked, total_weak, total_abandoned, total_issues)
    logger.info("═" * 60)
    logger.info("")

    return {"ran": True, "status": status, "projects": per_project,
            "company_pages": total_company, "checked": total_checked,
            "weak": total_weak, "abandoned": total_abandoned, "issues": total_issues}


def status_line(result: dict) -> str:
    """One honest, user-facing sentence derived from the result dict."""
    status = result.get("status")
    if status == "no_project":
        return "Chart structural review did not run: no slides were found to check."
    if status == "no_charts":
        return "Chart structural review: this deck has no chart/infographic slides to check."
    if status == "invalid":
        return (f"Chart provenance has {result.get('issues', 0)} issue(s) "
                "(missing/mismatched template records) — see the run log.")
    if status == "abandoned":
        return (f"Structural review: {result.get('abandoned', 0)} slide(s) appear to have "
                "dropped their matched template structure — worth a closer look.")
    if status == "weak":
        return (f"Structural review: {result.get('weak', 0)} slide(s) only weakly match their "
                "reference template structure.")
    if status == "clean":
        n = result.get("checked", 0)
        return (f"Chart structural review passed: {n} templated slide(s) match their reference "
                "structure." if n else "Chart structural review passed.")
    return "Chart structural review completed."
