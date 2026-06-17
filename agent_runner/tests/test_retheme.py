"""Tests for the deterministic raw-template re-theme (color + typography).

Two layers are covered:
  * ``retheme_chart_svg`` — the pure mapping/apply logic (palette role-matching,
    font-role classification, quote-safe font emission, structure preservation).
  * ``retheme_enforcement`` — the runner stage that decides *which* pages get
    re-themed (company-tier pages whose referenced template is a raw export) and
    rebuilds the deck.

All offline and deterministic; the only network/subprocess boundary (_reexport)
is monkeypatched.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from agent_runner import retheme_enforcement as rt  # also puts scripts/ on sys.path
import retheme_chart_svg as r  # noqa: E402  (import side-effect of the line above)

_SKILL = Path(__file__).resolve().parents[2] / "core-ppt-master-engine" / "skills" / "ppt-master"
_RAW_TPL = "templates/charts/powerslides_infographics/28_monthly_marketing_calendar.svg"
_CLEAN_TPL = "templates/charts/powerslides_infographics/07_cycle.svg"

# A small representative project theme.
THEME_COLORS = {
    "bg": "#ffffff", "secondary_bg": "#f8fafc", "border": "#e2e8f0",
    "text": "#1e293b", "text_secondary": "#475569", "primary": "#0f2942",
    "accent": "#0d9488", "secondary_accent": "#f59e0b",
}
THEME_TYPO = {
    "font_family": '"Microsoft YaHei", Arial, sans-serif',
    "body_family": '"Microsoft YaHei", Arial, sans-serif',
    "title_family": "Georgia, serif",
    "code_family": "Consolas, monospace",
}


# ───────────────────────── script: classification ─────────────────────────

def test_classify_font_roles():
    assert r.classify_font("Consolas, monospace") == "code"
    assert r.classify_font("Georgia, serif") == "title"
    assert r.classify_font("Arial, sans-serif") == "body"
    # 'sans-serif' must win over the 'serif' substring it contains.
    assert r.classify_font("Calibri,Calibri_MSFontService,sans-serif") == "body"


# ───────────────────────── script: color mapping ─────────────────────────

def test_neutrals_map_to_nearest_luminance():
    colors = Counter({"#ffffff": 5, "#f2f2f2": 10, "#262626": 3})
    m = r.build_color_mapping(colors, THEME_COLORS)
    assert m["#f2f2f2"] == "#f8fafc"     # light grey → light surface, not border
    assert m["#262626"] in ("#1e293b", "#0f2942")  # near-black → ink/primary
    # white maps to bg (identity #ffffff→#ffffff is dropped)
    assert "#ffffff" not in m


def test_chromatics_map_by_prominence():
    colors = Counter({"#e63946": 14, "#457b9d": 7})  # red used more than blue
    m = r.build_color_mapping(colors, THEME_COLORS)
    assert m["#e63946"] == "#0d9488"          # most-used → primary accent
    assert m["#457b9d"] == "#f59e0b"          # next → secondary accent


def test_color_mapping_drops_identity():
    # A template already using a theme color must not appear as a self-map.
    colors = Counter({"#0d9488": 3})
    assert r.build_color_mapping(colors, THEME_COLORS) == {}


# ───────────────────────── script: font mapping ─────────────────────────

def test_font_stack_emitted_with_single_quotes():
    fonts = Counter({"Calibri,Calibri_MSFontService,sans-serif": 9})
    typo = {"body_family": '"Microsoft YaHei", "PingFang SC", Arial, sans-serif'}
    m = r.build_font_mapping(fonts, typo)
    stack = next(iter(m.values()))
    assert '"' not in stack            # no double quotes that would break the attribute
    assert "'Microsoft YaHei'" in stack


def test_apply_font_mapping_does_not_break_attribute():
    svg = '<text font-family="Calibri,sans-serif">x</text>'
    typo = {"body_family": '"Inter", Arial, sans-serif'}
    out, _ = r.retheme_svg(svg, {}, typo)
    # exactly one well-formed font-family attribute remains
    assert out.count('font-family="') == 1
    assert "Inter" in out
    # the value must use single quotes internally so the attribute closes correctly
    assert 'font-family="\'Inter\', Arial, sans-serif"' in out


# ───────────────────────── script: end-to-end + structure ─────────────────────────

def test_retheme_preserves_structure_changes_only_style():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#f2f2f2"/>'
           '<text fill="#e63946" font-family="Arial,sans-serif">Hi</text></svg>')
    out, report = r.retheme_svg(svg, THEME_COLORS, THEME_TYPO)
    assert report["colors_remapped"] == 2 and report["fonts_remapped"] == 1
    # same number of elements / tags — nothing added or removed
    assert out.count("<rect") == 1 and out.count("<text") == 1
    assert "#f2f2f2" not in out and "#e63946" not in out
    assert "Hi" in out  # text content untouched


def test_parse_spec_lock_preserves_font_quotes(tmp_path):
    spec = tmp_path / "spec_lock.md"
    spec.write_text(
        "## colors\n- bg: #FFFFFF\n- accent: #0D9488\n\n"
        '## typography\n- font_family: "Microsoft YaHei", Arial, sans-serif\n'
        "- body: 20\n",
        encoding="utf-8",
    )
    colors, typo = r.parse_spec_lock(spec)
    assert colors["accent"] == "#0d9488"
    assert typo["font_family"] == '"Microsoft YaHei", Arial, sans-serif'
    assert "body" not in typo  # non-family typography rows are not remapped


# ───────────────────────── enforcement: raw detection ─────────────────────────

def test_is_raw_template_by_filter(tmp_path):
    p = tmp_path / "a.svg"
    p.write_text('<svg><filter id="f"><feGaussianBlur/></filter></svg>', encoding="utf-8")
    assert rt._is_raw_template(p) is True


def test_is_raw_template_by_size(tmp_path):
    p = tmp_path / "big.svg"
    p.write_text("<svg>" + "<rect/>" * 5000 + "</svg>", encoding="utf-8")
    assert rt._is_raw_template(p) is True


def test_clean_template_is_not_raw():
    # The real clean sibling 07_cycle must NOT be treated as raw.
    assert rt._is_raw_template(_SKILL / _CLEAN_TPL) is False


def test_real_raw_template_is_raw():
    assert rt._is_raw_template(_SKILL / _RAW_TPL) is True


# ───────────────────────── enforcement: per-project ─────────────────────────

def _make_project(tmp_path: Path, reference: str, tier: str = "company",
                  page_name: str = "P01.svg") -> Path:
    """A minimal project: spec_lock + provenance + a verbatim copy of the template.

    ``page_name`` is the generated SVG's filename in ``svg_output/``. Real decks use
    the numbered convention (``01_campaign_calendar.svg``), NOT ``P01.svg``; pass it
    explicitly to exercise the page-id → file resolution.
    """
    proj = tmp_path / "proj"
    (proj / "svg_output").mkdir(parents=True)
    (proj / "spec_lock.md").write_text(
        "## colors\n- bg: #FFFFFF\n- secondary_bg: #F8FAFC\n- border: #E2E8F0\n"
        "- text: #1E293B\n- text_secondary: #475569\n- primary: #0F2942\n"
        "- accent: #0D9488\n- secondary_accent: #F59E0B\n\n"
        '## typography\n- font_family: "Microsoft YaHei", Arial, sans-serif\n'
        '- title_family: Georgia, serif\n- code_family: Consolas, monospace\n',
        encoding="utf-8",
    )
    prov = {"schema": "chart_provenance/v1", "pages": {
        "P01": {"tier": tier, "key": Path(reference).stem, "reference": reference}}}
    (proj / "chart_provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    # verbatim copy of the actual template as the generated page
    (proj / "svg_output" / page_name).write_text(
        (_SKILL / reference).read_text(encoding="utf-8"), encoding="utf-8")
    return proj


def test_page_svg_resolves_numbered_filename(tmp_path):
    """REGRESSION: provenance keys pages 'P01' but real decks name the file
    '01_campaign_calendar.svg'. The resolver must map P01 → that file; the old
    P01.svg-only match silently found nothing and the whole re-theme stage no-opped
    on every real deck (re-theme + verbatim marker never applied → auditor scrambled
    the template)."""
    svg_dir = tmp_path / "svg_output"
    svg_dir.mkdir()
    (svg_dir / "01_campaign_calendar.svg").write_text("<svg/>", encoding="utf-8")
    (svg_dir / "04_budget_sankey.svg").write_text("<svg/>", encoding="utf-8")
    assert rt._page_svg(svg_dir, "P01").name == "01_campaign_calendar.svg"
    assert rt._page_svg(svg_dir, "P04").name == "04_budget_sankey.svg"
    assert rt._page_svg(svg_dir, "P02") is None          # no matching number
    # direct P0N.svg naming still works
    (svg_dir / "P03.svg").write_text("<svg/>", encoding="utf-8")
    assert rt._page_svg(svg_dir, "P03").name == "P03.svg"


def test_retheme_project_with_real_numbered_filenames(tmp_path, monkeypatch):
    """REGRESSION (end-to-end): a raw company page named by the real numbered
    convention must still be re-themed and marked verbatim — not skipped."""
    monkeypatch.setattr(rt, "_reexport", lambda d: True)
    proj = _make_project(tmp_path, _RAW_TPL, page_name="01_campaign_calendar.svg")
    res = rt._retheme_project(proj)
    assert res["rethemed_pages"], "numbered-file raw company page must be re-themed"
    out = (proj / "svg_output" / "01_campaign_calendar.svg").read_text(encoding="utf-8")
    assert "data-verbatim-template" in out[:600]   # marker stamped → auditor D4-only
    assert "#e63946" not in out.lower()            # theme actually applied


def test_retheme_project_rethemes_raw_company_page(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "_reexport", lambda d: True)  # no subprocess in tests
    proj = _make_project(tmp_path, _RAW_TPL)
    page = proj / "svg_output" / "P01.svg"
    assert "#e63946" in page.read_text(encoding="utf-8").lower()  # original chromatic present

    res = rt._retheme_project(proj)

    assert res["rethemed_pages"] and res["reexported"] is True
    out = page.read_text(encoding="utf-8").lower()
    assert "#e63946" not in out                 # template chromatic remapped away
    assert "#0d9488" in out                     # → project accent
    assert "calibri" not in out                 # template font remapped away


def test_retheme_project_skips_clean_company_template(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "_reexport", lambda d: True)
    proj = _make_project(tmp_path, _CLEAN_TPL)  # 07_cycle is clean → adapt path, not verbatim
    res = rt._retheme_project(proj)
    assert res["rethemed_pages"] == []


def test_retheme_project_flags_non_verbatim_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "_reexport", lambda d: True)
    proj = _make_project(tmp_path, _RAW_TPL)
    # Overwrite the verbatim copy with a tiny from-scratch redraw (the Slide-2
    # failure mode): provenance still says company/<raw key>, but the page is a
    # fraction of the template's size.
    (proj / "svg_output" / "P01.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#123456"/>'
        '<text fill="#abcdef" font-family="Arial,sans-serif">Rebuilt</text></svg>',
        encoding="utf-8",
    )
    res = rt._retheme_project(proj)
    assert res["not_verbatim"], "a tiny page for a raw template must be flagged as not-verbatim"
    assert "P01" in res["not_verbatim"][0]


def test_retheme_project_skips_stock_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "_reexport", lambda d: True)
    proj = _make_project(tmp_path, _RAW_TPL, tier="stock")
    res = rt._retheme_project(proj)
    assert res["rethemed_pages"] == []  # only company-tier raw templates are re-themed


# ───────────────────────── enforcement: status line ─────────────────────────

def test_status_line_plain_language():
    line = rt.status_line({"ran": True, "pages": 2, "reexport_failed": False})
    assert "2" in line and "theme" in line.lower()
    # no internal jargon leaks to the end-user feed
    for term in ("retheme", "svg", "verbatim", "provenance"):
        assert term not in line.lower()


def test_status_line_empty_when_noop():
    assert rt.status_line({"ran": True, "pages": 0}) == ""
