"""Unit tests for svg_doctor (single-SVG lint + auto-fix + ingestion sanitization).

Loads the script by path (it lives under the skill scripts dir, not an importable
package) and exercises every finding class: AUTO-FIX (mechanical, rewritten by
--fix), REVIEW (judgment, never auto-edited), INFO (advisory, never gates), and the
SECURITY scan for untrusted SVGs (event handlers / javascript: stripped as visual
no-ops; external refs / data: / DTDs held as REVIEW) plus the --ingest gate and the
shareable Markdown report.
"""
import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL_DIR = _REPO_ROOT / "core-ppt-master-engine" / "skills" / "ppt-master"


def _doctor():
    # svg_doctor lives at the repo root (scripts/svg_doctor/), a standalone dev tool
    # outside the skill bundle.
    path = _REPO_ROOT / "scripts" / "svg_doctor" / "svg_doctor.py"
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


# ── SECURITY / INGESTION class (untrusted SVG) ───────────────────────────────
def test_event_handler_stripped_as_visual_noop(tmp_path):
    # onload= is executable script but paints nothing -> AUTO-FIX (stripped).
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
                         'onload="steal()"><rect width="5" height="5" onclick="x()"/></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert "sec_event_handler" in _codes(findings)
    assert "onload" not in fixed and "onclick" not in fixed
    assert "<rect" in fixed  # element kept; only the handler removed


def test_javascript_url_attribute_stripped(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<a href="javascript:alert(1)"><rect width="5" height="5"/></a></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert "sec_js_url" in _codes(findings)
    assert "javascript:" not in fixed
    assert "<rect" in fixed  # visible child preserved


def test_external_reference_is_review_not_autofixed(tmp_path):
    # External <image> loads remote content -> can't be silently stripped -> REVIEW.
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<image href="https://evil.example/x.png" width="5" height="5"/></svg>')
    findings, fixed = d.review(p, do_fix=True)
    assert "sec_external_ref" in _codes(findings)
    # not removed (visual-preserving invariant); still present after --fix
    assert "evil.example" in (fixed or p.read_text(encoding="utf-8"))
    # a review-class security finding fails the gate even without --ingest
    assert d.main([str(p)]) == 1


def test_namespace_url_is_not_flagged_external(tmp_path):
    # xmlns="http://..." is a namespace, not a fetched resource -> must NOT trip.
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" '
                         'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
                         '<rect width="5" height="5"/></svg>')
    findings, _ = d.review(p, do_fix=False)
    assert "sec_external_ref" not in _codes(findings)


def test_doctype_entity_flagged(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<!DOCTYPE svg [<!ENTITY xxe "boom">]>'
                         '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
    findings, _ = d.review(p, do_fix=False)
    assert {"sec_doctype", "sec_entity"} <= _codes(findings)


def test_ingest_gate_fails_even_when_autofixed(tmp_path):
    # An onload is auto-stripped, but --ingest still rejects so a human signs off.
    # Pass --report into tmp_path so the gate's default report never writes into the
    # real svg_doctor/reports/ folder during the test.
    d = _doctor()
    rpt = tmp_path / "r.md"
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
                         'onload="x()"><rect width="5" height="5"/></svg>')
    # without --ingest: handler is autofix-only -> exit 0
    assert d.main([str(p), "--fix"]) == 0
    # with --ingest: any security construct rejects -> exit 1
    p2 = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
                          'onload="x()"><rect width="5" height="5"/></svg>')
    assert d.main([str(p2), "--ingest", "--fix", "--report", str(rpt)]) == 1


def test_raw_export_is_info_and_does_not_gate(tmp_path):
    # A raw export is an accepted verbatim+re-theme class -> INFO, never blocks.
    d = _doctor()
    body = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">']
    body.append('<filter id="f"><feGaussianBlur stdDeviation="2"/></filter>')
    for i in range(320):
        body.append(f'<rect x="{i%10}" y="{i%10}" width="1" height="1"/>')
    body.append("</svg>")
    p = _write(tmp_path, "".join(body))
    findings, _ = d.review(p, do_fix=False)
    info = [f for f in findings if f.code == "raw_export"]
    assert info and info[0].cls == "info"
    # info must not fail the gate (no review/security findings here)
    assert d.main([str(p)]) == 0


def test_report_file_written_with_verdict(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<image href="https://evil.example/x.png" width="5" height="5"/></svg>')
    rpt = tmp_path / "report.md"
    rc = d.main([str(p), "--report", str(rpt)])
    assert rc == 1  # external ref blocks
    text = rpt.read_text(encoding="utf-8")
    assert "REJECT" in text and "sec_external_ref" in text


def test_clean_file_report_says_accept(tmp_path):
    d = _doctor()
    p = _write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                         '<rect x="0" y="0" width="50" height="50" fill="#112233"/></svg>')
    rpt = tmp_path / "ok.md"
    rc = d.main([str(p), "--report", str(rpt)])
    assert rc == 0
    assert "ACCEPT" in rpt.read_text(encoding="utf-8")
