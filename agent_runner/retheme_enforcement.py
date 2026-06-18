"""
Runner-enforced re-theme of verbatim raw-template pages (post-turn).

Some company catalog templates are raw PowerPoint exports (filter-laden, very large)
that the model cannot redraw faithfully — so the contract is: the Executor copies
such a template **verbatim** into the slide and edits only its ``<text>`` content,
and the *runner* re-themes it here (colors + typography) to the project palette.
That keeps the distinctive infographic looking like the original AND adopting the
deck's theme — the two requirements that conflict for raw templates if the model
tries to adapt them by hand (it gives up and free-designs; see
``lint_chart_catalog.py`` and ``provenance_enforcement``).

The re-theme itself is deterministic (``scripts/retheme_chart_svg.py``): a find-and-map
over the SVG's small color + font vocabulary, no geometry or text touched. This module
decides *which* pages get it (company-tier pages whose referenced template is raw) and
re-exports the deck so the themed SVGs reach the PPTX.

Fail-open: any missing file, unreadable provenance, or per-page error is logged and
skipped; the run always proceeds.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from agent_runner.config import logger
# Reuse the canonical project finder + careful re-export (stale-deck safe) so this
# stage rebuilds decks exactly the way visual review does.
from agent_runner.visual_enforcement import _find_active_project_dirs, _reexport

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILL_DIR = _REPO_ROOT / "core-ppt-master-engine" / "skills" / "ppt-master"
_SCRIPTS_DIR = _SKILL_DIR / "scripts"

# A referenced template counts as "raw" (must be consumed verbatim, then re-themed
# here) when it carries PPTX-export fingerprints or is too large for the model to
# redraw — the same criterion lint_chart_catalog.py uses to keep these out of the
# clean-vector contract.
_RAW_BANNED = ("<filter", "feGaussianBlur", "feComponentTransfer")
_RAW_BYTES = 20_000

# Import the deterministic re-theme functions in-process (pure stdlib; testable).
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
try:
    from retheme_chart_svg import parse_spec_lock, retheme_svg  # type: ignore
except Exception as exc:  # noqa: BLE001 — fail-open if the script is missing
    parse_spec_lock = None  # type: ignore
    retheme_svg = None  # type: ignore
    logger.warning("retheme: could not import retheme_chart_svg (%s); stage disabled.", exc)


def _is_raw_template(path: Path) -> bool:
    """True if the catalog template at ``path`` is a raw export (verbatim class)."""
    try:
        if path.stat().st_size > _RAW_BYTES:
            return True
        head = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(tok in head for tok in _RAW_BANNED)


def _resolve_template(entry: dict) -> Path | None:
    """Resolve a provenance entry's template SVG to an absolute path under the skill."""
    ref = (entry.get("reference") or "").strip()
    if ref:
        p = (_SKILL_DIR / ref).resolve()
        if p.is_file():
            return p
    key = (entry.get("key") or "").strip()
    if key:
        p = (_SKILL_DIR / "templates" / "charts" / "powerslides_infographics" / f"{key}.svg")
        if p.is_file():
            return p
    return None


_VERBATIM_MARKER = "data-verbatim-template"


def _stamp_verbatim_marker(svg_text: str) -> str:
    """Tag the root <svg> so the layout auditor knows this is a verbatim raw
    template and must not relocate its elements (D4-only). Idempotent."""
    if _VERBATIM_MARKER in svg_text[:800]:
        return svg_text
    m = re.search(r"<svg\b", svg_text)
    if not m:
        return svg_text
    i = m.end()
    return f'{svg_text[:i]} {_VERBATIM_MARKER}="1"{svg_text[i:]}'


def _page_svg(svg_dir: Path, page_id: str) -> Path | None:
    """Map a provenance page id (``P01``) to its generated file in ``svg_output/``.

    Real decks name pages by the numbered convention ``01_campaign_calendar.svg``,
    NOT ``P01.svg`` — so a plain ``page_id``-stem match silently finds nothing and
    the whole re-theme stage no-ops. This mirrors
    ``chart_structural_review._resolve_generated_svg`` (extract the page number, then
    match a file whose leading digits equal it) so every stage resolves pages the
    same way.
    """
    if not svg_dir.is_dir():
        return None
    direct = svg_dir / f"{page_id}.svg"
    if direct.is_file():
        return direct
    m = re.search(r"(\d+)", page_id)
    if not m:
        return None
    n = int(m.group(1))
    exact = svg_dir / f"P{n:02d}.svg"
    if exact.is_file():
        return exact
    for s in sorted(svg_dir.glob("*.svg")):
        sm = re.match(r"0*(\d+)", s.stem)
        if sm and int(sm.group(1)) == n:
            return s
    return None


def _retheme_project(project_dir: Path) -> dict:
    """Re-theme every verbatim raw-template page in one project. Returns a report."""
    result = {"project": project_dir.name, "rethemed_pages": [], "skipped_raw": [],
              "not_verbatim": [], "reexported": False, "error": None}
    if retheme_svg is None or parse_spec_lock is None:
        result["error"] = "retheme_unavailable"
        return result

    prov_path = project_dir / "chart_provenance.json"
    try:
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
        pages = prov.get("pages") or {}
    except (OSError, json.JSONDecodeError):
        return result  # no provenance ⇒ nothing to do (fail-open)

    colors, typo = parse_spec_lock(project_dir / "spec_lock.md")
    if not colors and not typo:
        logger.info("  retheme: %s has no spec_lock theme; skipping.", project_dir.name)
        return result

    svg_dir = project_dir / "svg_output"
    for page_id, entry in pages.items():
        if not isinstance(entry, dict) or (entry.get("tier") != "company"):
            continue
        tpl = _resolve_template(entry)
        if not tpl or not _is_raw_template(tpl):
            continue
        svg = _page_svg(svg_dir, page_id)
        if not svg:
            result["skipped_raw"].append(f"{page_id}: no generated SVG found")
            continue
        # Compliance check: a verbatim copy is ~the template's size. A page that is
        # dramatically smaller means the Executor rebuilt the infographic from
        # scratch (the failure mode where provenance says company/<key> but the
        # distinctive design is lost) — surface it loudly. A rebuilt page is NOT
        # protected as verbatim: it is a normal generated SVG and must be audited
        # normally, so it gets no verbatim marker.
        is_rebuilt = False
        try:
            is_rebuilt = svg.stat().st_size < tpl.stat().st_size * 0.5
        except OSError:
            pass
        if is_rebuilt:
            result["not_verbatim"].append(
                f"{page_id} ({entry.get('key')}): page is "
                f"{svg.stat().st_size}B vs template {tpl.stat().st_size}B "
                f"— likely rebuilt from scratch, not copied verbatim")
        try:
            text = svg.read_text(encoding="utf-8")
            out, report = retheme_svg(text, colors, typo)
            # Mark genuine verbatim copies so the layout auditor protects them
            # (D4-only); leave rebuilt pages unmarked for normal auditing.
            if not is_rebuilt:
                out = _stamp_verbatim_marker(out)
            if out != text:
                svg.write_text(out, encoding="utf-8")
            if report["colors_remapped"] or report["fonts_remapped"]:
                result["rethemed_pages"].append(
                    f"{page_id} ({entry.get('key')}): "
                    f"{report['colors_remapped']} color(s), {report['fonts_remapped']} font(s)")
        except OSError as exc:
            result["skipped_raw"].append(f"{page_id}: {exc}")

    if result["rethemed_pages"]:
        result["reexported"] = _reexport(project_dir)
    return result


def enforce_retheme(start_time: float | None) -> dict:
    """Re-theme verbatim raw-template pages across all active projects (post-turn).

    Runs BEFORE visual review so the layout auditor sees the final themed fonts
    (font swaps can shift text metrics). Fail-open and honest: reports exactly what
    was re-themed and whether the deck was rebuilt.
    """
    if retheme_svg is None:
        return {"ran": False, "status": "unavailable", "projects": [], "pages": 0}

    project_dirs = _find_active_project_dirs(start_time)
    if not project_dirs:
        return {"ran": False, "status": "no_project", "projects": [], "pages": 0}

    per_project = [_retheme_project(d) for d in project_dirs]
    total_pages = sum(len(p["rethemed_pages"]) for p in per_project)
    not_verbatim = [(p["project"], w) for p in per_project for w in p.get("not_verbatim", [])]
    if not total_pages and not not_verbatim:
        logger.info("Re-theme: no verbatim raw-template pages to re-theme.")
        return {"ran": True, "status": "noop", "projects": per_project, "pages": 0,
                "not_verbatim": 0}

    reexport_failed = any(p["rethemed_pages"] and not p["reexported"] for p in per_project)
    logger.info("")
    logger.info("═" * 60)
    logger.info("RAW-TEMPLATE RE-THEME (verbatim copy → deterministic theme)")
    for p in per_project:
        for line in p["rethemed_pages"]:
            logger.info("  %s: %s", p["project"], line)
    # Loud warning when a raw company page was NOT copied verbatim — the
    # distinctive infographic was lost even though provenance records it.
    for proj, w in not_verbatim:
        logger.warning("  ⚠ %s: %s", proj, w)
    logger.info("  Re-theme result: pages=%d deck_rebuilt=%s not_verbatim=%d",
                total_pages, not reexport_failed, len(not_verbatim))
    logger.info("═" * 60)
    logger.info("")

    return {"ran": True, "status": "rethemed" if not reexport_failed else "rethemed_no_export",
            "projects": per_project, "pages": total_pages, "reexport_failed": reexport_failed,
            "not_verbatim": len(not_verbatim)}


def status_line(result: dict) -> str:
    """One non-technical line for the end-user status feed (no internal terms)."""
    if not result.get("ran"):
        return ""
    nv = result.get("not_verbatim", 0)
    n = result.get("pages", 0)
    if not n and not nv:
        return ""
    if nv and not n:
        return (f"{nv} branded infographic(s) were redrawn instead of using the "
                f"original design — see the run log.")
    base = f"Adapted {n} branded infographic(s) to match your presentation theme."
    if result.get("reexport_failed"):
        base = (f"Adapted {n} branded infographic(s) to your theme, "
                f"but the slides could not be fully rebuilt — see the run log.")
    if nv:
        base += (f" Note: {nv} other(s) were redrawn instead of using the original "
                 f"branded design.")
    return base
