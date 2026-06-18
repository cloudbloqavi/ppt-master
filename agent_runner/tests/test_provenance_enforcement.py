"""Unit tests for chart provenance validation + structural-mimic review.

Covers the runner-side validator in ``agent_runner.provenance_enforcement`` and the
structural review script (loaded by path, since it lives under the skill scripts
dir and is not an importable package). Real powerslides reference SVGs are used so
the on-disk reference checks and topology signatures exercise actual files.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from agent_runner import provenance_enforcement as pe

_SKILL_DIR = Path(__file__).resolve().parents[2] / "core-ppt-master-engine" / "skills" / "ppt-master"
_PS = _SKILL_DIR / "templates" / "charts" / "powerslides_infographics"
_REF_SWOT = "templates/charts/powerslides_infographics/18_swot.svg"

# Skip the whole module if the catalog isn't present (keeps CI honest elsewhere).
pytestmark = pytest.mark.skipif(
    not (_PS / "18_swot.svg").is_file(),
    reason="powerslides catalog not available",
)


def _load_review_module():
    path = _SKILL_DIR / "scripts" / "chart_structural_review.py"
    spec = importlib.util.spec_from_file_location("chart_structural_review", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _project(tmp_path: Path, prov: dict | None, charts_in_lock: bool = True) -> Path:
    p = tmp_path / "demo_ppt169_20260615_1002"
    (p / "svg_output").mkdir(parents=True)
    if charts_in_lock:
        (p / "spec_lock.md").write_text(
            "## page_rhythm\n- P01: dense\n\n## page_charts\n- P01: 18_swot\n\n## forbidden\n- x\n",
            encoding="utf-8")
    else:
        (p / "spec_lock.md").write_text("## page_rhythm\n- P01: dense\n", encoding="utf-8")
    if prov is not None:
        (p / "chart_provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    return p


# ── _validate_provenance ─────────────────────────────────────────────────────
def test_missing_provenance_with_charts_is_flagged(tmp_path):
    proj = _project(tmp_path, prov=None, charts_in_lock=True)
    v = pe._validate_provenance(proj)
    assert v["present"] is False
    assert "provenance_missing_but_deck_has_charts" in v["issues"]


def test_missing_provenance_without_charts_is_ok(tmp_path):
    proj = _project(tmp_path, prov=None, charts_in_lock=False)
    v = pe._validate_provenance(proj)
    assert v["present"] is False
    assert v["issues"] == []


def test_custom_page_requires_reason(tmp_path):
    prov = {"pages": {"P01": {"tier": "custom", "key": None, "reference": None, "decision": ""}}}
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert any("missing required decision" in i for i in v["issues"])


def test_custom_page_with_reason_is_clean(tmp_path):
    prov = {"pages": {"P01": {"tier": "custom", "key": None, "reference": None,
                              "decision": "no catalog entry fit a stacked roadmap"}}}
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert v["issues"] == []


def test_company_reference_must_exist_on_disk(tmp_path):
    prov = {"pages": {"P01": {"tier": "company", "key": "99_nope",
                              "reference": "templates/charts/powerslides_infographics/99_nope.svg",
                              "decision": "x"}}}
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert any("reference not found on disk" in i for i in v["issues"])


def test_company_reference_must_be_under_powerslides(tmp_path):
    # company tier but stock-style path → two issues (not found + wrong dir)
    prov = {"pages": {"P01": {"tier": "company", "key": "18_swot",
                              "reference": "templates/charts/18_swot.svg", "decision": "x"}}}
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert any("not under powerslides_infographics" in i for i in v["issues"])


def test_valid_company_provenance_is_clean(tmp_path):
    prov = {"pages": {"P01": {"tier": "company", "key": "18_swot",
                              "reference": _REF_SWOT, "viz_type": "swot",
                              "decision": "Pick swot", "confirmed_by": "strategist"}}}
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert v["issues"] == []
    assert v["by_tier"]["company"] == 1


def test_all_executor_confirmed_by_flagged(tmp_path):
    prov = {"pages": {"P01": {"tier": "company", "key": "18_swot",
                              "reference": _REF_SWOT, "viz_type": "swot",
                              "decision": "Pick swot", "confirmed_by": "executor"}}}
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert any("strategist_skipped" in i for i in v["issues"])


def test_catalog_skip_suspected_when_no_company_tier(tmp_path):
    prov = {"pages": {"P01": {"tier": "stock", "key": "sankey_chart",
                              "reference": "templates/charts/sankey_chart.svg",
                              "confirmed_by": "strategist"}}}
    # Make the stock reference exist so we don't get a disk-miss issue
    stock_ref = _SKILL_DIR / "templates" / "charts" / "sankey_chart.svg"
    if not stock_ref.is_file():
        pytest.skip("stock sankey_chart.svg not present")
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert v["catalog_skip_suspected"] is True


def test_catalog_skip_not_suspected_when_company_tier_present(tmp_path):
    prov = {"pages": {"P01": {"tier": "company", "key": "18_swot",
                              "reference": _REF_SWOT, "viz_type": "swot",
                              "confirmed_by": "strategist"}}}
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert v["catalog_skip_suspected"] is False


def _write_candidates(project_dir, pages):
    (project_dir / "chart_candidates.json").write_text(
        json.dumps({"schema": "chart_candidates/v1", "pages": pages}), encoding="utf-8")


def test_company_candidate_skipped_without_reason_is_flagged(tmp_path):
    # Match stage found a company option; agent chose custom with NO reason → issue.
    prov = {"pages": {"P01": {"tier": "custom", "key": None, "reference": None,
                              "decision": "", "confirmed_by": "strategist"}}}
    proj = _project(tmp_path, prov)
    _write_candidates(proj, {"P01": {"company": [{"key": "18_swot", "reason": "fits"}]}})
    v = pe._validate_provenance(proj)
    assert any("company candidate '18_swot' was available" in i for i in v["issues"])


def test_company_candidate_skipped_with_reason_is_clean(tmp_path):
    # Same situation but the agent justified the override → no candidate-aware issue.
    prov = {"pages": {"P01": {"tier": "custom", "key": None, "reference": None,
                              "decision": "swot didn't fit a 3x3 milestones grid",
                              "confirmed_by": "strategist"}}}
    proj = _project(tmp_path, prov)
    _write_candidates(proj, {"P01": {"company": [{"key": "18_swot", "reason": "fits"}]}})
    v = pe._validate_provenance(proj)
    assert not any("was available but tier" in i for i in v["issues"])


def test_stock_choice_over_company_candidate_needs_reason(tmp_path):
    # Stock tier normally needs no decision reason, but if a company candidate
    # existed the choice must be justified.
    prov = {"pages": {"P01": {"tier": "stock", "key": "18_swot", "reference": _REF_SWOT,
                              "decision": "", "confirmed_by": "strategist"}}}
    proj = _project(tmp_path, prov)
    _write_candidates(proj, {"P01": {"company": [{"key": "30_marketing_milestones_matrix",
                                                  "reason": "fits"}]}})
    v = pe._validate_provenance(proj)
    assert any("was available but tier=stock" in i for i in v["issues"])


def test_invalid_tier_flagged(tmp_path):
    prov = {"pages": {"P01": {"tier": "bogus"}}}
    v = pe._validate_provenance(_project(tmp_path, prov))
    assert any("invalid tier" in i for i in v["issues"])


# ── structural review ────────────────────────────────────────────────────────
def test_identical_svg_high_affinity(tmp_path):
    mod = _load_review_module()
    proj = tmp_path / "p"
    (proj / "svg_output").mkdir(parents=True)
    # generated == reference ⇒ affinity 1.0, verdict ok
    (proj / "svg_output" / "P01.svg").write_text(
        (_PS / "18_swot.svg").read_text(encoding="utf-8"), encoding="utf-8")
    (proj / "chart_provenance.json").write_text(json.dumps({"pages": {
        "P01": {"tier": "company", "key": "18_swot", "reference": _REF_SWOT,
                "decision": "x", "confirmed_by": "executor"}}}), encoding="utf-8")
    res = mod.review_project(proj)
    p01 = next(p for p in res["pages"] if p["page"] == "P01")
    assert p01["verdict"] == "ok"
    assert p01["affinity"] >= 0.95


def test_custom_page_skipped(tmp_path):
    mod = _load_review_module()
    proj = tmp_path / "p"
    (proj / "svg_output").mkdir(parents=True)
    (proj / "chart_provenance.json").write_text(json.dumps({"pages": {
        "P01": {"tier": "custom", "key": None, "reference": None, "decision": "bespoke"}}}),
        encoding="utf-8")
    res = mod.review_project(proj)
    assert res["pages"][0]["verdict"] == "skipped_custom"
    assert res["checked"] == 0


def test_no_provenance_status(tmp_path):
    mod = _load_review_module()
    proj = tmp_path / "p"
    (proj / "svg_output").mkdir(parents=True)
    res = mod.review_project(proj)
    assert res["status"] == "no_provenance"
