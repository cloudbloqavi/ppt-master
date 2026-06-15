#!/usr/bin/env python3
"""
Structural-mimic review: does each generated slide carry the structure of the
reference template it was matched to?

This is the deterministic backstop for the "structural mimicking" contract. The
Strategist matches viz pages to a company/stock template; the Executor is told to
reproduce that template's structure with the runtime theme. Whether it actually
*did* was previously unverifiable — some slides mimic, some come out brand new.

This script reads ``chart_provenance.json`` (the reconciled per-page record of
which template each slide used; see ``templates/chart_provenance_reference.md``)
and, for every ``company``/``stock`` page, compares the GENERATED SVG against its
REFERENCE SVG on **structure/topology only** — element-type histogram, group
topology, and the dominant repeated-unit count. Runtime theme differences (colors,
fonts, exact text) are deliberately ignored: the two are *supposed* to differ
visually; only the structure must match.

``custom`` pages are skipped — they have no reference, so there is nothing to
compare (this is exactly why the tier field exists).

v1 is **report-only**: it writes findings to ``<project>/.review/structural/`` and
prints a JSON summary; it does not regenerate slides. The runner consumes the
summary and logs it honestly. Auto-regeneration on low affinity is a later step.

Usage:
    python3 chart_structural_review.py <project_path>

Exit code is always 0 (advisory); read the JSON summary on stdout.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

# Skill dir = .../skills/ppt-master ; references in provenance are relative to it
# (e.g. "templates/charts/powerslides_infographics/18_swot.svg").
_SKILL_DIR = Path(__file__).resolve().parent.parent

# Semantic (structure-bearing) SVG tags. We count these and ignore everything
# else (defs, gradients, filters, metadata) so a theme/decoration difference
# never registers as a structural difference.
_SEMANTIC_TAGS = {
    "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "path", "text", "image", "use", "g",
}
# Tags whose presence/volume marks a reference as a "raw" PowerPoint export
# (filter-laden, thousands of primitives). For those, element COUNT is not a fair
# yardstick — a clean redraw legitimately has far fewer elements — so we drop the
# count signal and lean on type-shape + repeat-unit instead.
_RAW_MARKERS = {"filter", "feGaussianBlur", "feColorMatrix", "feOffset", "feFlood"}
_RAW_SEMANTIC_THRESHOLD = 300  # > this many semantic elements ⇒ treat ref as raw

# Affinity thresholds (heuristic, advisory).
_FLAG_BELOW = 0.50          # affinity under this ⇒ "weak" structural match
_ABANDON_RATIO = 0.15       # clean-ref count ratio under this ⇒ "abandoned" suspect


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _iter_elems(root: ET.Element):
    for el in root.iter():
        yield _strip_ns(el.tag), el


def _signature(svg_path: Path) -> dict | None:
    """Structure-only signature of an SVG: type histogram + topology + repeat unit."""
    try:
        root = ET.fromstring(svg_path.read_text(encoding="utf-8", errors="replace"))
    except (ET.ParseError, OSError):
        return None

    hist: Counter[str] = Counter()
    raw_markers = 0
    # Direct-child group count per parent → the modal value approximates the
    # "repeat unit" (e.g. 4 SWOT quadrants, 5 roadmap phases) the design repeats.
    sibling_group_counts: list[int] = []

    for tag, el in _iter_elems(root):
        if tag in _RAW_MARKERS:
            raw_markers += 1
        if tag in _SEMANTIC_TAGS:
            hist[tag] += 1
        # count semantic children of this element (one level)
        child_groups = sum(
            1 for c in list(el) if _strip_ns(c.tag) in ("g", "rect", "circle", "path")
        )
        if child_groups >= 2:
            sibling_group_counts.append(child_groups)

    n_semantic = sum(hist.values())
    repeat_unit = Counter(sibling_group_counts).most_common(1)[0][0] if sibling_group_counts else 0
    is_raw = raw_markers > 0 and n_semantic > _RAW_SEMANTIC_THRESHOLD

    return {
        "hist": dict(hist),
        "n_semantic": n_semantic,
        "n_text": hist.get("text", 0),
        "n_groups": hist.get("g", 0),
        "repeat_unit": repeat_unit,
        "raw_markers": raw_markers,
        "is_raw": is_raw,
    }


def _cosine(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _affinity(gen: dict, ref: dict) -> tuple[float, dict]:
    """Combine three theme-invariant structure signals into an affinity in [0,1].

    Inputs are two ``_signature()`` dicts: ``gen`` (the generated slide) and ``ref``
    (the reference template). Only structure is compared — colors, fonts, and exact
    text are deliberately ignored, because the generated slide is *supposed* to
    differ from the reference visually (it carries the runtime theme); only the
    layout/topology must match.

    Signals
    -------
    1. ``type_cosine`` ∈ [0,1] — cosine similarity of the two element-type
       histograms (counts of ``rect``/``circle``/``path``/``text``/``g``/…). Answers
       "is this built from the same kinds of shapes in the same proportions?"
           type_cosine = (Σ gen[t]·ref[t]) / (‖gen‖·‖ref‖)        # over all tags t

    2. ``repeat_match`` ∈ {0.0, 0.5, 1.0} — does the slide reproduce the
       reference's dominant *repeated-unit* count (e.g. 4 SWOT quadrants, 5 roadmap
       phases, 3 columns)?  ``repeat_unit`` is the modal sibling-group count.
           1.0 if gen.repeat_unit == ref.repeat_unit
           0.5 if |gen.repeat_unit − ref.repeat_unit| == 1   (off by one)
           0.0 otherwise

    3. ``count_credit`` ∈ [0,1] — how much of the reference's structural mass the
       slide carries; operationalizes the §5 "<30% element count ⇒ downgrade"
       heuristic. ``count_ratio`` is generated/reference semantic-element counts,
       and full credit is reached once the slide has ≥50 % of the reference's:
           count_ratio  = gen.n_semantic / max(ref.n_semantic, 1)
           count_credit = min(1.0, count_ratio / 0.5)

    Formula (two branches)
    ----------------------
    The reference's nature decides the weighting:

    * Clean reference (hand-authored / small):
          affinity = 0.5·type_cosine + 0.2·repeat_match + 0.3·count_credit

    * Raw reference (filter-laden raw PPTX export: ``is_raw`` is True when it has
      filter markers AND > 300 semantic elements) — the count signal is dropped,
      because a clean redraw legitimately has far fewer elements than the bloated
      export, so penalizing on count would be a false negative:
          affinity = 0.7·type_cosine + 0.3·repeat_match

    The returned ``affinity`` feeds the verdict in ``review_project()``:
    ``count_ratio < _ABANDON_RATIO`` (0.15) ⇒ ``abandoned_suspect``;
    ``affinity < _FLAG_BELOW`` (0.50) ⇒ ``weak``; otherwise ``ok``.

    NOTE: every weight and threshold here is a heuristic first guess. Calibrate
    them against real runs before promoting the review from report-only to an
    auto-regenerate gate.

    Worked example
    --------------
    Reference ``18_swot.svg`` (clean): hist {rect:20, text:32, g:12, path:4},
    n_semantic = 68, repeat_unit = 16.
    Generated slide reuses the SWOT skeleton but with 3 of the 4 quadrants drawn
    densely: hist {rect:18, text:30, g:11, path:3}, n_semantic = 62,
    repeat_unit = 16.

        type_cosine  ≈ 0.999                  # near-identical shape mix
        repeat_match = 1.0                     # 16 == 16
        count_ratio  = 62 / 68 = 0.912
        count_credit = min(1.0, 0.912 / 0.5) = 1.0
        affinity     = 0.5·0.999 + 0.2·1.0 + 0.3·1.0 = 0.9995 → verdict "ok"

    Contrast — the executor collapsed a 5-phase roadmap into a plain timeline:
    ref n_semantic = 90, repeat_unit = 5; gen n_semantic = 11, repeat_unit = 0.

        type_cosine  ≈ 0.55
        repeat_match = 0.0                     # lost the 5-phase structure
        count_ratio  = 11 / 90 = 0.122         # < 0.15 ⇒ abandoned_suspect
        count_credit = min(1.0, 0.122 / 0.5) = 0.244
        affinity     = 0.5·0.55 + 0.2·0.0 + 0.3·0.244 = 0.348 → verdict "abandoned_suspect"

    Returns ``(affinity, components)`` where ``components`` exposes the raw signal
    values (``type_cosine`` / ``repeat_match`` / ``count_ratio`` / ``ref_is_raw``)
    for the per-page finding.
    """
    type_cosine = _cosine(gen["hist"], ref["hist"])

    # Repeat-unit agreement: did the generated slide reproduce the reference's
    # dominant repeated count (the quadrants / phases / columns)?
    ru_g, ru_r = gen["repeat_unit"], ref["repeat_unit"]
    repeat_match = 1.0 if (ru_r and ru_g == ru_r) else (
        0.5 if (ru_r and abs(ru_g - ru_r) <= 1) else 0.0
    )

    ref_raw = ref["is_raw"]
    if ref_raw:
        # Raw export: ignore count ratio (unfair); structure-shape + repeat only.
        count_ratio = None
        affinity = 0.7 * type_cosine + 0.3 * repeat_match
    else:
        denom = max(ref["n_semantic"], 1)
        count_ratio = gen["n_semantic"] / denom
        count_credit = min(1.0, count_ratio / 0.5)  # ≥50% of ref elements ⇒ full credit
        affinity = 0.5 * type_cosine + 0.2 * repeat_match + 0.3 * count_credit

    return affinity, {
        "type_cosine": round(type_cosine, 3),
        "repeat_match": repeat_match,
        "count_ratio": None if count_ratio is None else round(count_ratio, 3),
        "ref_is_raw": ref_raw,
    }


def _resolve_generated_svg(svg_dir: Path, page_id: str) -> Path | None:
    """Map a provenance page id (P01) to its file in svg_output/ (P01.svg or 01_*.svg)."""
    if not svg_dir.is_dir():
        return None
    m = re.search(r"(\d+)", page_id)
    if not m:
        return None
    n = int(m.group(1))
    exact = svg_dir / f"P{n:02d}.svg"
    if exact.is_file():
        return exact
    for f in sorted(svg_dir.glob("*.svg")):
        fm = re.match(r"0*(\d+)", f.stem)
        if fm and int(fm.group(1)) == n:
            return f
    return None


def review_project(project_dir: Path) -> dict:
    prov_path = project_dir / "chart_provenance.json"
    if not prov_path.is_file():
        return {"project": project_dir.name, "status": "no_provenance",
                "pages": [], "weak": 0, "abandoned": 0, "checked": 0}

    try:
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"project": project_dir.name, "status": "provenance_unparseable",
                "error": str(exc), "pages": [], "weak": 0, "abandoned": 0, "checked": 0}

    svg_dir = project_dir / "svg_output"
    pages_out: list[dict] = []
    weak = abandoned = checked = 0

    for page_id, entry in sorted((prov.get("pages") or {}).items()):
        tier = (entry or {}).get("tier")
        if tier == "custom":
            pages_out.append({"page": page_id, "tier": "custom", "verdict": "skipped_custom"})
            continue
        if tier not in ("company", "stock"):
            pages_out.append({"page": page_id, "tier": tier, "verdict": "skipped_unknown_tier"})
            continue

        ref_rel = (entry or {}).get("reference") or ""
        ref_path = (_SKILL_DIR / ref_rel) if ref_rel else None
        gen_path = _resolve_generated_svg(svg_dir, page_id)

        if not ref_path or not ref_path.is_file():
            pages_out.append({"page": page_id, "tier": tier, "key": entry.get("key"),
                              "verdict": "reference_missing", "reference": ref_rel})
            continue
        if not gen_path:
            pages_out.append({"page": page_id, "tier": tier, "key": entry.get("key"),
                              "verdict": "generated_missing"})
            continue

        ref_sig = _signature(ref_path)
        gen_sig = _signature(gen_path)
        if not ref_sig or not gen_sig:
            pages_out.append({"page": page_id, "tier": tier, "key": entry.get("key"),
                              "verdict": "parse_error"})
            continue

        affinity, components = _affinity(gen_sig, ref_sig)
        checked += 1

        severe = (components["count_ratio"] is not None
                  and components["count_ratio"] < _ABANDON_RATIO)
        if severe:
            verdict = "abandoned_suspect"
            abandoned += 1
        elif affinity < _FLAG_BELOW:
            verdict = "weak"
            weak += 1
        else:
            verdict = "ok"

        pages_out.append({
            "page": page_id, "tier": tier, "key": entry.get("key"),
            "affinity": round(affinity, 3), "verdict": verdict,
            "components": components,
            "gen_elements": gen_sig["n_semantic"], "ref_elements": ref_sig["n_semantic"],
            "gen_repeat_unit": gen_sig["repeat_unit"], "ref_repeat_unit": ref_sig["repeat_unit"],
        })

    # Persist per-project findings for inspection.
    out_dir = project_dir / ".review" / "structural"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(
            json.dumps({"pages": pages_out}, indent=2), encoding="utf-8")
    except OSError:
        pass

    status = "clean"
    if abandoned:
        status = "abandoned"
    elif weak:
        status = "weak"
    return {"project": project_dir.name, "status": status, "checked": checked,
            "weak": weak, "abandoned": abandoned, "pages": pages_out}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(json.dumps({"error": "usage: chart_structural_review.py <project_path>"}))
        return 0
    project_dir = Path(argv[1]).resolve()
    if not project_dir.is_dir():
        print(json.dumps({"error": f"not a directory: {project_dir}"}))
        return 0
    print(json.dumps(review_project(project_dir), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
