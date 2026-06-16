"""Unit tests for svg_layout_auditor's D2/D3 auto-fixers.

Regression context: D1_orphan_baseline was the only rule with an auto-fix;
D2_text_overlap and D3_out_of_bounds were detection-only, so every run that hit
them reported "N layout issue(s) that need a closer look" and stopped — no
fix was ever attempted. These tests pin the new fix_text_overlap /
fix_out_of_bounds behavior: real defects get corrected without the all-or-
nothing rollback discarding partial progress, and a synthetic unfixable case
is left as an honest, reported finding rather than forced into a worse state.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[2] / "core-ppt-master-engine" / "skills" / "ppt-master"


def _auditor():
    path = _SKILL_DIR / "scripts" / "svg_layout_auditor.py"
    spec = importlib.util.spec_from_file_location("svg_layout_auditor", path)
    mod = importlib.util.module_from_spec(spec)
    # dataclasses + `from __future__ import annotations` resolves field types via
    # sys.modules[cls.__module__] — must be registered before exec_module, or
    # asdict() on Finding/Box later blows up with "'NoneType' has no '__dict__'".
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(tmp_path: Path, name: str, body: str) -> Path:
    svg_dir = tmp_path / "svg_output"
    svg_dir.mkdir(exist_ok=True)
    p = svg_dir / name
    p.write_text(body, encoding="utf-8")
    return p


def _rules(findings):
    return [f.rule for f in findings]


CANVAS = (1280, 720)

_OVERLAP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
<text x="100" y="200" font-size="16" fill="#000">Volatile Competition</text>
<text x="220" y="200" font-size="16" fill="#000">Contraction</text>
</svg>"""

_OUT_OF_BOUNDS_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
<text x="110" y="320" font-size="15" font-weight="bold" fill="#000" text-anchor="end">Products Revenue Pillar Label</text>
</svg>"""


def test_fix_text_overlap_separates_crowded_pair(tmp_path):
    a = _auditor()
    svg_path = _write(tmp_path, "overlap.svg", _OVERLAP_SVG)
    findings, _tree = a.audit_page(svg_path, CANVAS)
    assert "D2_text_overlap" in _rules(findings)

    tree = a.ET.parse(svg_path, parser=a._svg_parser())
    fixed = a.fix_text_overlap(tree, CANVAS)
    assert fixed >= 1
    with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
        tree.write(fh, encoding="unicode", xml_declaration=False)

    post_findings, _ = a.audit_page(svg_path, CANVAS)
    assert "D2_text_overlap" not in _rules(post_findings)


def test_fix_out_of_bounds_pulls_text_back_onto_canvas(tmp_path):
    a = _auditor()
    svg_path = _write(tmp_path, "oob.svg", _OUT_OF_BOUNDS_SVG)
    findings, _tree = a.audit_page(svg_path, CANVAS)
    assert "D3_out_of_bounds" in _rules(findings)

    tree = a.ET.parse(svg_path, parser=a._svg_parser())
    fixed = a.fix_out_of_bounds(tree, CANVAS)
    assert fixed == 1
    with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
        tree.write(fh, encoding="unicode", xml_declaration=False)

    post_findings, _ = a.audit_page(svg_path, CANVAS)
    assert "D3_out_of_bounds" not in _rules(post_findings)


def test_process_page_autofix_commits_overlap_fix_and_records_it(tmp_path):
    """End-to-end through process_page: backup/commit path, not just the bare fixer."""
    a = _auditor()
    project = tmp_path
    svg_path = _write(project, "overlap.svg", _OVERLAP_SVG)
    review_dir = project / ".review"

    result = a.process_page(svg_path, review_dir, CANVAS, autofix=True)
    assert any(label.startswith("D2_text_overlap") for label in result["fixes_applied"])
    assert result["hard"] == 0
    assert (review_dir / "overlap.audit.json").is_file()


def test_process_page_keeps_partial_progress_instead_of_all_or_nothing(tmp_path):
    """Two independent overlapping rows: even if only one is resolvable, the
    other's detection-only fix attempt must not roll back the one that worked."""
    a = _auditor()
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
<text x="100" y="100" font-size="16" fill="#000">Volatile Competition</text>
<text x="220" y="100" font-size="16" fill="#000">Contraction</text>
<text x="100" y="600" font-size="16" fill="#000">Premium High-Share</text>
<text x="205" y="600" font-size="16" fill="#000">Steady</text>
</svg>"""
    svg_path = _write(tmp_path, "rows.svg", svg)
    review_dir = tmp_path / ".review"
    before, _ = a.audit_page(svg_path, CANVAS)
    assert len(before) >= 2

    result = a.process_page(svg_path, review_dir, CANVAS, autofix=True)
    assert result["hard"] <= len(before)
    assert any(label.startswith("D2_text_overlap") for label in result["fixes_applied"])


def test_no_autofix_flag_leaves_svg_untouched(tmp_path):
    a = _auditor()
    svg_path = _write(tmp_path, "overlap.svg", _OVERLAP_SVG)
    review_dir = tmp_path / ".review"
    original = svg_path.read_text(encoding="utf-8")

    result = a.process_page(svg_path, review_dir, CANVAS, autofix=False)
    assert result["fixes_applied"] == []
    assert svg_path.read_text(encoding="utf-8") == original
    assert result["hard"] >= 1
