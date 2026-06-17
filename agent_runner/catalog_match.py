"""
Runner-side catalog match stage (Directive prompts).

The Strategist is *supposed* to consult the company catalog (30 entries) before
the stock catalog (71 entries) and pick a tier per slide. In practice the read
is dropped under token pressure — the same prompt picked company templates in one
run and silently fell to stock/custom in the next (see
``provenance_enforcement`` module docstring). Mandating an in-turn subagent does
not fix this: the model declines to spawn it (observed 0 spawns), so any
in-model mechanism inherits the same discretion.

This module removes the decision from model discretion for the case where it is
possible: a **Directive** prompt enumerates slides up front ("Slide 1: …"), so the
per-slide intents exist *before* the agent runs. The runner extracts them, makes
ONE normal LLM completion (not a subagent) that ranks company-first then stock
candidates per slide, and injects the result into the agent prompt. The catalog
is therefore consulted by construction; the model still makes the final tier call
(company / stock / custom / none) with the candidates + theme/layout in view.

Everything here is fail-open: catalogs missing, prompt not Directive, the LLM call
errors, or its output is unparseable → return ``None`` and the run proceeds
exactly as before. It never raises to the caller and never blocks a run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent_runner.config import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHARTS_DIR = (
    _REPO_ROOT / "core-ppt-master-engine" / "skills" / "ppt-master"
    / "templates" / "charts"
)
_COMPANY_INDEX = _CHARTS_DIR / "powerslides_infographics" / "company_index.json"
_STOCK_INDEX = _CHARTS_DIR / "charts_index.json"

# Per-slide "Slide N: <intent>" / "Page N: <intent>" splitter. Captures the index
# and everything up to the next slide/page marker (or end of string).
_SLIDE_SPLIT_RE = re.compile(
    r"(?i)(?:slide|page)\s*(\d+)\s*[:.\-)]\s*(.+?)"
    r"(?=(?:slide|page)\s*\d+\s*[:.\-)]|$)",
    re.DOTALL,
)


def load_catalogs() -> dict[str, dict[str, str]]:
    """Return {key: {"summary": str, "tier": "company"|"stock"}}. Company first.

    Pure I/O; no LLM. Missing/unparseable files contribute nothing (fail-open).
    """
    catalogs: dict[str, dict[str, str]] = {}
    for path, tier in ((_COMPANY_INDEX, "company"), (_STOCK_INDEX, "stock")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("catalog_match: could not read %s (%s)", path.name, exc)
            continue
        for key, entry in (data.get("charts") or {}).items():
            summary = (entry or {}).get("summary")
            if key and summary:
                # company entries are loaded first; never let a stock key with the
                # same name overwrite a company one.
                catalogs.setdefault(key, {"summary": summary, "tier": tier})
    return catalogs


def extract_slide_intents(prompt: str) -> dict[str, str]:
    """Split a Directive prompt into {P01: intent, ...}. Empty dict if not Directive.

    Mirrors the Directive/Brief distinction in strategist.md §0: a prompt that
    enumerates slides is Directive (intents known up front); a topic-only Brief
    returns {} so the caller skips the match stage and leaves it model-driven.
    """
    intents: dict[str, str] = {}
    for m in _SLIDE_SPLIT_RE.finditer(prompt or ""):
        idx = int(m.group(1))
        intent = " ".join(m.group(2).split()).strip(" .")
        if intent:
            intents[f"P{idx:02d}"] = intent
    return intents


def _build_match_prompt(intents: dict[str, str], catalogs: dict[str, dict[str, str]]) -> str:
    """Assemble the single-shot matcher prompt (intents + all summaries + schema)."""
    company_lines, stock_lines = [], []
    for key, meta in catalogs.items():
        line = f"- {key}: {meta['summary']}"
        (company_lines if meta["tier"] == "company" else stock_lines).append(line)

    slides_block = "\n".join(f"- {pid}: {intent}" for pid, intent in intents.items())
    company_block = "\n".join(company_lines)
    stock_block = "\n".join(stock_lines)

    return f"""You are a presentation chart-template matcher. For each slide below, find the \
best-fitting visualization templates from two catalogs.

Each catalog entry's text is a SELECTION RULE in the form "Pick for <content shape>. \
Skip for/if <reason>". A template matches a slide only when the slide's content shape \
satisfies its Pick clause AND does not trip its Skip clause. Match by content SHAPE \
(calendar grid, matrix, cycle, flow, funnel, …), not by surface keywords.

COMPANY CATALOG (in-house; PREFER these — they win on ties):
{company_block}

STOCK CATALOG (generic fallback):
{stock_block}

SLIDES TO MATCH:
{slides_block}

For every slide return:
- up to 3 company candidates whose Pick clause genuinely fits (fewer or none if no \
company entry fits — do not force a match)
- up to 2 stock candidates whose Pick clause fits
- recommended_tier: "company" if a company candidate truly fits; else "stock" if a \
stock candidate fits; else "custom" if neither catalog fits the content shape; else \
"none" if the slide is narrative/text and needs no chart at all
- none_plausible: true only if the slide could reasonably carry no chart

Each candidate is {{"key": "<exact catalog key>", "reason": "<one short clause>"}}. \
Use only keys that appear verbatim above.

Respond with ONLY this JSON (no prose, no markdown fence):
{{"pages": {{"P01": {{"intent": "...", "company": [...], "stock": [...], \
"recommended_tier": "...", "none_plausible": false}}}}}}"""


def _validate_keys(data: dict, catalogs: dict[str, dict[str, str]]) -> dict:
    """Drop any candidate whose key is not a real catalog key (anti-hallucination)."""
    pages = data.get("pages") or {}
    for entry in pages.values():
        if not isinstance(entry, dict):
            continue
        for tier in ("company", "stock"):
            cands = entry.get(tier) or []
            kept = [
                c for c in cands
                if isinstance(c, dict) and c.get("key") in catalogs
                and catalogs[c["key"]]["tier"] == tier
            ]
            entry[tier] = kept
    return data


def match_candidates(
    intents: dict[str, str],
    catalogs: dict[str, dict[str, str]],
    model: str,
    api_key: str,
) -> dict | None:
    """ONE normal LLM completion that ranks candidates per slide. None on any failure.

    Not a subagent: the runner calls this directly so it cannot be skipped. Strict
    JSON out; hallucinated keys are filtered against the real catalog.
    """
    if not (intents and catalogs and api_key):
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        logger.warning("catalog_match: google-genai not importable (%s); skipping.", exc)
        return None

    prompt = _build_match_prompt(intents, catalogs)
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        raw = (resp.text or "").strip()
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("catalog_match: matcher call/parse failed (%s); skipping.", exc)
        return None

    if not isinstance(data, dict) or "pages" not in data:
        logger.warning("catalog_match: matcher returned unexpected shape; skipping.")
        return None

    data = _validate_keys(data, catalogs)
    data.setdefault("schema", "chart_candidates/v1")
    return data


def format_injection_block(data: dict) -> str:
    """Render the candidates as an instruction block appended to the agent prompt."""
    lines = [
        "",
        "## Pre-computed catalog candidates (catalog already consulted for you)",
        "",
        "The company catalog (preferred) and stock catalog have ALREADY been matched "
        "against each slide below. Treat this as the result of the §VII catalog read — "
        "you do not need to re-read the indexes to discover these:",
        "",
    ]
    for pid, entry in (data.get("pages") or {}).items():
        if not isinstance(entry, dict):
            continue
        intent = entry.get("intent", "")
        lines.append(f"- **{pid}** ({intent}):")
        for tier in ("company", "stock"):
            for c in entry.get(tier) or []:
                lines.append(f"    - [{tier}] `{c.get('key')}` — {c.get('reason', '')}")
        rec = entry.get("recommended_tier", "")
        none_ok = entry.get("none_plausible", False)
        lines.append(f"    - recommended_tier: **{rec}**"
                     + (" (a no-chart/narrative treatment is also reasonable)" if none_ok else ""))
    lines += [
        "",
        "Decision rules:",
        "- For each slide pick exactly one tier: `company` / `stock` / `custom` / `none`.",
        "- Prefer the company candidate when one genuinely fits (it wins on ties).",
        "- You MAY choose `custom` or `none` even when a company candidate exists — but "
        "if you do, you MUST record the reason in `chart_provenance.json`'s `decision` "
        "field (the runner cross-checks these candidates against your choices).",
        "",
    ]
    return "\n".join(lines)


def persist_candidates(project_dirs, data: dict) -> int:
    """Write chart_candidates.json into each active project dir. Returns count written.

    The runner writes this itself (rather than trusting the model to) so the
    candidate-aware provenance check always has a ground-truth record of what was
    offered, independent of the model's discretion. Fail-open per directory.
    """
    if not data:
        return 0
    written = 0
    for d in project_dirs:
        try:
            (Path(d) / "chart_candidates.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            written += 1
        except OSError as exc:
            logger.warning("catalog_match: could not write chart_candidates.json to %s (%s)",
                           d, exc)
    return written


def run_catalog_match(prompt: str, model: str, api_key: str) -> tuple[dict | None, str]:
    """Orchestrate the stage. Returns (candidates_or_None, injection_block_or_empty).

    Fail-open end to end: a non-Directive prompt, empty catalogs, or a failed
    match all yield (None, "") and the caller injects nothing.
    """
    intents = extract_slide_intents(prompt)
    if not intents:
        logger.info("catalog_match: prompt is not Directive (no per-slide intents); "
                    "leaving template selection model-driven.")
        return None, ""
    catalogs = load_catalogs()
    if not catalogs:
        logger.warning("catalog_match: no catalog entries loaded; skipping match stage.")
        return None, ""
    logger.info("catalog_match: matching %d slide intent(s) against %d catalog entries...",
                len(intents), len(catalogs))
    data = match_candidates(intents, catalogs, model, api_key)
    if not data:
        return None, ""
    n_company = sum(len(e.get("company") or []) for e in (data.get("pages") or {}).values()
                    if isinstance(e, dict))
    logger.info("catalog_match: produced candidates for %d slide(s) (%d company match(es)).",
                len(data.get("pages") or {}), n_company)
    return data, format_injection_block(data)
