"""Unit tests for the runner-side catalog match stage (agent_runner.catalog_match).

The single LLM completion is mocked (we patch google.genai.Client), so these run
offline. The real catalog JSONs are used for load/validate so key-filtering is
exercised against actual template keys.
"""
import json
import types as _pytypes

import pytest

from agent_runner import catalog_match as cm


# ── extract_slide_intents ────────────────────────────────────────────────────
def test_directive_prompt_extracts_intents():
    prompt = (
        "Create a 4-slide annual marketing plan. "
        "Slide 1: a monthly marketing calendar grid. "
        "Slide 2: a 3x3 marketing milestones matrix. "
        "Slide 3: a circular customer lifecycle. "
        "Slide 4: a Sankey diagram of budget flow."
    )
    intents = cm.extract_slide_intents(prompt)
    assert set(intents) == {"P01", "P02", "P03", "P04"}
    assert "calendar grid" in intents["P01"]
    assert "Sankey" in intents["P04"]


def test_page_synonym_and_punctuation_variants():
    prompt = "Page 1 - a funnel. Page 2. a heat map."
    intents = cm.extract_slide_intents(prompt)
    assert set(intents) == {"P01", "P02"}


def test_brief_prompt_yields_no_intents():
    prompt = "Create a deck about our Q3 financial results and growth outlook."
    assert cm.extract_slide_intents(prompt) == {}


# ── load_catalogs ────────────────────────────────────────────────────────────
def test_load_catalogs_has_company_and_stock():
    catalogs = cm.load_catalogs()
    if not catalogs:
        pytest.skip("catalog index files not available")
    tiers = {meta["tier"] for meta in catalogs.values()}
    assert "company" in tiers and "stock" in tiers
    # every entry carries a non-empty selection-rule summary
    assert all(meta["summary"] for meta in catalogs.values())


# ── match_candidates (mocked LLM) ────────────────────────────────────────────
class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, payload):
        self._payload = payload

    def generate_content(self, **kwargs):
        return _FakeResp(self._payload)


class _FakeClient:
    _payload = "{}"

    def __init__(self, *a, **k):
        self.models = _FakeModels(type(self)._payload)


def _patch_client(monkeypatch, payload):
    _FakeClient._payload = payload
    import google.genai as real_genai
    monkeypatch.setattr(real_genai, "Client", _FakeClient)


def test_match_filters_hallucinated_keys(monkeypatch):
    catalogs = {
        "28_monthly_marketing_calendar": {"summary": "Pick for calendars", "tier": "company"},
        "sankey_chart": {"summary": "Pick for flows", "tier": "stock"},
    }
    payload = json.dumps({"pages": {"P01": {
        "intent": "calendar",
        "company": [
            {"key": "28_monthly_marketing_calendar", "reason": "fits"},
            {"key": "99_made_up_key", "reason": "hallucinated"},
        ],
        "stock": [{"key": "sankey_chart", "reason": "wrong tier but real key"}],
        "recommended_tier": "company", "none_plausible": False,
    }}})
    _patch_client(monkeypatch, payload)
    out = cm.match_candidates({"P01": "calendar"}, catalogs, "gemini-3.5-flash", "k")
    assert out is not None
    comp_keys = [c["key"] for c in out["pages"]["P01"]["company"]]
    assert comp_keys == ["28_monthly_marketing_calendar"]  # hallucinated key dropped
    assert out["schema"] == "chart_candidates/v1"


def test_match_returns_none_on_bad_json(monkeypatch):
    _patch_client(monkeypatch, "not json at all")
    catalogs = {"x": {"summary": "s", "tier": "company"}}
    assert cm.match_candidates({"P01": "x"}, catalogs, "m", "k") is None


def test_match_returns_none_without_api_key():
    catalogs = {"x": {"summary": "s", "tier": "company"}}
    assert cm.match_candidates({"P01": "x"}, catalogs, "m", "") is None


def test_match_returns_none_without_intents():
    assert cm.match_candidates({}, {"x": {"summary": "s", "tier": "company"}}, "m", "k") is None


# ── format_injection_block ───────────────────────────────────────────────────
def test_injection_block_lists_candidates_and_rules():
    data = {"pages": {"P01": {
        "intent": "calendar grid",
        "company": [{"key": "28_monthly_marketing_calendar", "reason": "fits"}],
        "stock": [],
        "recommended_tier": "company", "none_plausible": False,
    }}}
    block = cm.format_injection_block(data)
    assert "Pre-computed catalog candidates" in block
    assert "28_monthly_marketing_calendar" in block
    assert "recommended_tier: **company**" in block
    assert "decision" in block


# ── run_catalog_match orchestration ──────────────────────────────────────────
def test_persist_candidates_writes_file(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    data = {"schema": "chart_candidates/v1", "pages": {"P01": {"company": []}}}
    n = cm.persist_candidates([d], data)
    assert n == 1
    written = json.loads((d / "chart_candidates.json").read_text(encoding="utf-8"))
    assert written["schema"] == "chart_candidates/v1"


def test_persist_candidates_noop_on_empty(tmp_path):
    assert cm.persist_candidates([tmp_path], None) == 0
    assert not (tmp_path / "chart_candidates.json").exists()


def test_run_match_brief_prompt_injects_nothing():
    data, inject = cm.run_catalog_match("A deck about Q3 results", "m", "k")
    assert data is None and inject == ""


def test_run_match_directive_success(monkeypatch):
    # Force a known catalog + mocked LLM so the orchestration path is deterministic.
    monkeypatch.setattr(cm, "load_catalogs", lambda: {
        "28_monthly_marketing_calendar": {"summary": "Pick for calendars", "tier": "company"},
    })
    payload = json.dumps({"pages": {"P01": {
        "intent": "a monthly calendar",
        "company": [{"key": "28_monthly_marketing_calendar", "reason": "fits"}],
        "stock": [], "recommended_tier": "company", "none_plausible": False,
    }}})
    _patch_client(monkeypatch, payload)
    data, inject = cm.run_catalog_match("Slide 1: a monthly calendar grid.", "m", "k")
    assert data is not None
    assert "28_monthly_marketing_calendar" in inject
