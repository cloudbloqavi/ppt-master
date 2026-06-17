"""Unit tests for svg_doctor (single-SVG lint + auto-fix).

Loads the script by path (it lives under the skill scripts dir, not an importable
package) and exercises both classes of finding: AUTO-FIX (mechanical, rewritten by
--fix) and REVIEW (judgment, never auto-edited).
"""
import importlib.util
from pathlib import Path

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[2] / "core-ppt-master-engine" / "skills" / "ppt-master"


def _doctor():
    path = _SKILL_DIR / "scripts" / "svg_doctor.py"
    spec = importlib.util.spec_from_file_location("svg_doctor", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _codes(findings):
    return {f.code for f in findings}


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "x.svg"
    p.write_text(body, encoding="utf-8")
    return p


# ── AUTO-FIX class ───────────────────────────────────────────────────────────
def test_html_entities_detected_and_fixed(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<text>A&nbsp;B&mdash;C</text></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert "html_entities" in _codes(findings)
    assert "&nbsp;" not in fixed and "&mdash;" not in fixed
    assert "—" in fixed


def test_rgba_converted_to_hex_preserving_alpha(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<rect fill="rgba(255,0,0,0.5)"/></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert "rgba_color" in _codes(findings)
    # visual-preserving: hex + the alpha kept as fill-opacity
    assert "rgba(" not in fixed and "#FF0000" in fixed
    assert 'fill-opacity="0.5"' in fixed


def test_rgb_no_alpha_no_opacity_attr(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<rect stroke="rgb(0,128,255)"/></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert "#0080FF" in fixed and "opacity" not in fixed


def test_script_stripped_but_style_flagged_not_removed(tmp_path):
    # <script> is non-rendering -> stripped. <style> paints -> REVIEW, left intact.
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<style>.a{fill:red}</style><script>x</script><rect class="a"/></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert "banned_script" in _codes(findings)   # autofix
    assert "banned_style" in _codes(findings)    # review (flag only)
    assert "<script" not in fixed                # stripped
    assert "<style" in fixed                     # NOT removed (would change visuals)
    assert "class=" in fixed                     # class preserved (style targets it)
    # banned_style must be REVIEW class, not autofix
    assert [f.cls for f in findings if f.code == "banned_style"] == ["review"]


def test_missing_xmlns_and_viewbox_added(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg width="1280" height="720"><rect/></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert {"missing_xmlns", "missing_viewbox"} <= _codes(findings)
    assert 'xmlns="http://www.w3.org/2000/svg"' in fixed
    assert 'viewBox="0 0 1280 720"' in fixed


def test_stray_ampersand_escaped_but_legal_preserved(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<text>Tom &amp; legal, raw &  stray</text></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert "stray_ampersand" in _codes(findings)
    # legal entity untouched, stray one escaped
    assert fixed.count("&amp;") == 2


def test_clean_svg_has_no_findings_and_exit_zero(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                         '<rect x="0" y="0" width="50" height="50" fill="#112233"/></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert findings == []
    assert fixed is None  # nothing changed
    assert d.main([str(p)]) == 0


# ── REVIEW class (never auto-fixed) ──────────────────────────────────────────
def test_mirrored_transform_flagged_not_fixed(tmp_path):
    d = _doctor()
    body = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path d="M0 10 5 0 9 0 10 10Z" transform="matrix(1 0 0 -1 40 50)"/></svg>')
    p = _write(tmp_path, body)
    findings, fixed = d.review(p, do_fix=True)
    assert "mirrored_transform" in _codes(findings)
    # review-class item must NOT be rewritten
    assert fixed is None or "matrix(1 0 0 -1 40 50)" in (fixed or p.read_text(encoding="utf-8"))
    # exit code 1 because a review finding remains
    assert d.main([str(p)]) == 1


def test_out_of_bounds_flagged(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                         '<rect x="0" y="0" width="500" height="50"/></svg>')
    findings, _ = d.review(p, do_fix=False)
    assert "out_of_bounds" in _codes(findings)


def test_parse_error_flagged(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg"><rect></svg>')  # unclosed rect
    findings, _ = d.review(p, do_fix=False)
    assert "parse_error" in _codes(findings)
