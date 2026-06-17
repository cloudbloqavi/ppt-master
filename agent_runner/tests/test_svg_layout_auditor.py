"""Unit tests for svg_layout_auditor's D2/D3/D4 auto-fixers.

Regression context: D1_orphan_baseline was the only rule with an auto-fix;
D2_text_overlap and D3_out_of_bounds were detection-only, so every run that hit
them reported "N layout issue(s) that need a closer look" and stopped — no
fix was ever attempted. These tests pin the new fix_text_overlap /
fix_out_of_bounds behavior: real defects get corrected without the all-or-
nothing rollback discarding partial progress, and a synthetic unfixable case
is left as an honest, reported finding rather than forced into a worse state.

D4_text_overflow regression context: its container-match (_enclosing_container)
originally only considered <rect>/<image> shapes, so grid/card cells exported
as filled <path> rects (e.g. a calendar's day cells) were invisible to it —
real text overflowing a path-drawn cell was silently never even detected. Its
shrink-to-fit auto-fixer must also be idempotent: a naive re-shrink-by-current-
size compounds without bound across repeated audits, and a shrinking box's
center can drift onto a *different* neighboring cell, manufacturing new
findings each run instead of converging.
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

# Same overlapping pair, but tagged as a verbatim raw-template page: the auditor
# must NOT relocate elements here (D1/D2/D3 off), only allow gentle D4.
_VERBATIM_OVERLAP_SVG = (
    '<svg data-verbatim-template="1" xmlns="http://www.w3.org/2000/svg" '
    'viewBox="0 0 1280 720">\n'
    '<text x="100" y="200" font-size="16" fill="#000">Volatile Competition</text>\n'
    '<text x="220" y="200" font-size="16" fill="#000">Contraction</text>\n'
    '</svg>'
)

_OUT_OF_BOUNDS_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
<text x="110" y="320" font-size="15" font-weight="bold" fill="#000" text-anchor="end">Products Revenue Pillar Label</text>
</svg>"""

# A path-drawn "cell" (the calendar/grid pattern that originally evaded D4
# entirely) wide enough to satisfy _enclosing_container's size-plausibility
# check but too narrow for the text — verified to need the 0.6 floor scale
# and still leave ~8px of residual spill (an honest unresolved finding).
_PATH_CELL_OVERFLOW_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
<path d="M100 100 244 100 244 140 100 140Z" fill="#eee"/>
<text x="105" y="125" font-size="16" fill="#000">Host monthly interactive webinars</text>
</svg>"""

# Same cell pattern but with text that fits comfortably once shrunk.
_PATH_CELL_FIXABLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
<path d="M100 100 165 100 165 140 100 140Z" fill="#eee"/>
<text x="105" y="125" font-size="16" fill="#000">Webinars Drip</text>
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


def test_verbatim_marker_disables_relocation_fixers(tmp_path):
    """A verbatim-marked page must not be relocated by D1/D2/D3 (they scramble
    professionally-authored flattened templates); only gentle D4 may run, and the
    relocation findings are dropped as false positives."""
    a = _auditor()
    svg_path = _write(tmp_path, "P01.svg", _VERBATIM_OVERLAP_SVG)
    result = a.process_page(svg_path, tmp_path / ".review", CANVAS, autofix=True)
    # no relocation fix was applied …
    assert not any(lbl.startswith(("D1", "D2", "D3")) for lbl in result["fixes_applied"])
    # … the overlapping text was NOT moved (original x preserved) …
    assert 'x="220"' in svg_path.read_text(encoding="utf-8")
    # … and no relocation finding survives in the report.
    assert all(f["rule"].startswith("D4") for f in result["findings"])


def test_unmarked_overlap_still_relocates(tmp_path):
    """Control: the same overlapping pair WITHOUT the marker is still D2-fixed,
    proving the marker (not some other change) is what disables relocation."""
    a = _auditor()
    svg_path = _write(tmp_path, "P01.svg", _OVERLAP_SVG)
    result = a.process_page(svg_path, tmp_path / ".review", CANVAS, autofix=True)
    assert any(lbl.startswith("D2") for lbl in result["fixes_applied"])


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


def test_path_drawn_cell_is_seen_as_a_d4_container(tmp_path):
    """The original bug: a filled <path> cell was invisible to D4's container
    match, so text overflowing it was never even detected."""
    a = _auditor()
    svg_path = _write(tmp_path, "cell.svg", _PATH_CELL_OVERFLOW_SVG)
    findings, _tree = a.audit_page(svg_path, CANVAS)
    assert "D4_text_overflow" in _rules(findings)


def test_fix_text_overflow_shrinks_text_to_fit_its_path_cell(tmp_path):
    a = _auditor()
    svg_path = _write(tmp_path, "cell.svg", _PATH_CELL_FIXABLE_SVG)
    tree = a.ET.parse(svg_path, parser=a._svg_parser())
    fixed = a.fix_text_overflow(tree, CANVAS)
    assert fixed == 1
    with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
        tree.write(fh, encoding="unicode", xml_declaration=False)

    post_findings, _ = a.audit_page(svg_path, CANVAS)
    assert "D4_text_overflow" not in _rules(post_findings)


def test_fix_text_overflow_leaves_honest_finding_at_the_shrink_floor(tmp_path):
    """Text too long for its cell even at the 60% floor must stay reported,
    not be shrunk past legibility to force a false 'clean' result."""
    a = _auditor()
    svg_path = _write(tmp_path, "cell.svg", _PATH_CELL_OVERFLOW_SVG)
    tree = a.ET.parse(svg_path, parser=a._svg_parser())
    fixed = a.fix_text_overflow(tree, CANVAS)
    assert fixed == 1
    with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
        tree.write(fh, encoding="unicode", xml_declaration=False)

    post_findings, _ = a.audit_page(svg_path, CANVAS)
    assert "D4_text_overflow" in _rules(post_findings)
    assert all(f.severity == "soft" for f in post_findings)


def test_fix_text_overflow_is_idempotent_across_repeated_runs(tmp_path):
    """Regression: a naive re-shrink-by-current-size compounded without bound
    on every re-run, and the shrinking box's center could drift onto a
    different neighboring cell, manufacturing new findings each pass instead
    of converging. Re-running after the first fix must change nothing."""
    a = _auditor()
    svg_path = _write(tmp_path, "cell.svg", _PATH_CELL_OVERFLOW_SVG)
    tree = a.ET.parse(svg_path, parser=a._svg_parser())
    a.fix_text_overflow(tree, CANVAS)
    with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
        tree.write(fh, encoding="unicode", xml_declaration=False)
    once_fixed = svg_path.read_text(encoding="utf-8")

    for _ in range(3):
        tree = a.ET.parse(svg_path, parser=a._svg_parser())
        fixed_again = a.fix_text_overflow(tree, CANVAS)
        assert fixed_again == 0
        with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
            tree.write(fh, encoding="unicode", xml_declaration=False)

    assert svg_path.read_text(encoding="utf-8") == once_fixed
