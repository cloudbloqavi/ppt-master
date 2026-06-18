"""Regression tests for research-source citation timing in status_logger.

Two ordering bugs are covered:

1. **Manifest scan window** — a populated `[[RESEARCH_SOURCES]]` manifest is often
   larger than the streaming scan window (_SCAN_OVERLAP). The old gate only parsed
   while the marker was still inside that window, so by the time the closing ``` fence
   streamed in the marker had scrolled out and the block was skipped; citations
   surfaced only when a *later* marker re-entered the window (end of run) or never.

2. **Late manifest vs. brief** — the model defers emitting its manifest to end-of-turn,
   so citations landed *after* the slide-design events. The brief's `## Sources` section
   is written right after research, so the runner now emits from there at write time
   (reading the content from the write call's args, since writes carry no ToolResult
   chunk). Idempotent by domain, so the later manifest adds no duplicate.
"""
import pytest

from agent_runner import status_logger as sl


@pytest.fixture(autouse=True)
def _reset():
    sl.reset_run_state()
    yield
    sl.reset_run_state()


def _capture(monkeypatch):
    events = []
    monkeypatch.setattr(
        sl, "log_status",
        lambda msg, event_type="progress", payload=None: events.append((event_type, msg, payload)),
    )
    return events


def _stream(text, chunk=24):
    """Feed text to the text-stream scanner in small deltas, like the SDK does."""
    for i in range(0, len(text), chunk):
        sl._check_text_for_status(text[i:i + chunk])


def _domains(events):
    return [p.get("domain") for (et, _m, p) in events if et == "citation" and p]


# A populated block whose marker→closing-fence span exceeds the scan window.
_BIG_MANIFEST = (
    "## Topic Research Complete\n\nSummary text here.\n\n"
    "[[RESEARCH_SOURCES]]\n```json\n"
    '{\n  "sources": [\n'
    + ",\n".join(
        f'    {{"name": "Source number {i} with a deliberately long descriptive '
        f'title to pad the block well past the streaming window", '
        f'"url": "https://example-domain-{i}.com/path/to/article"}}'
        for i in range(12)
    )
    + "\n  ]\n}\n```\n\nMoving on to the next phase.\n"
)


def test_big_manifest_emits_when_block_closes(monkeypatch):
    events = _capture(monkeypatch)
    # Sanity: the block really is larger than the window this guards against.
    span = _BIG_MANIFEST.index("```\n\nMoving") - _BIG_MANIFEST.index("[[RESEARCH_SOURCES]]")
    assert span > sl._SCAN_OVERLAP, "test manifest must exceed the scan window"

    _stream(_BIG_MANIFEST)
    domains = _domains(events)
    assert len(domains) == 12, f"expected all 12 sources, got {domains}"
    assert "example-domain-0.com" in domains
    assert sl._sources_parsed is True


def test_no_late_dependency_on_second_marker(monkeypatch):
    """The populated block must surface on its own — not wait for a later marker."""
    events = _capture(monkeypatch)
    _stream(_BIG_MANIFEST)
    # Citations present BEFORE any subsequent (empty) manifest is ever emitted.
    assert len(_domains(events)) == 12


def test_empty_then_populated_marker(monkeypatch):
    """An early empty manifest must not lock out a later populated one."""
    events = _capture(monkeypatch)
    _stream("[[RESEARCH_SOURCES]]\n```json\n{\"sources\": []}\n```\n")
    assert _domains(events) == []
    _stream(_BIG_MANIFEST)
    assert len(_domains(events)) == 12


def test_citations_are_deduped_by_domain(monkeypatch):
    events = _capture(monkeypatch)
    _stream(_BIG_MANIFEST)
    _stream(_BIG_MANIFEST)  # replay: idempotent, no duplicate citations
    assert len(_domains(events)) == 12


# ── Early emission at brief-write time ──────────────────────────────────────
# The model defers its [[RESEARCH_SOURCES]] manifest to end-of-turn, so citations
# used to surface AFTER the slide-design events. The brief's `## Sources` section,
# however, is written right after research — so the runner emits from there at
# write time. Writes carry no ToolResult chunk; content is read from the call args.

class _Chunk:
    """Minimal stand-in for an SDK ToolCall chunk."""
    def __init__(self, name, args, id="t1"):
        self.name = name
        self.args = args
        self.id = id


def _names(events):
    return [p.get("name") for (et, _m, p) in events if et == "citation" and p]


def test_parse_md_text_captures_label_as_name():
    md = ("# Brief\n\n## Sources\n"
          "* Foo Bar Report: https://foo.com/x\n"
          "- https://bare.com/y\n"
          "* [Linked Title](https://linked.com/z)\n")
    srcs = sl._parse_sources_from_md_text(md)
    assert {"name": "Foo Bar Report", "url": "https://foo.com/x"} in srcs
    assert {"name": "", "url": "https://bare.com/y"} in srcs
    assert {"name": "Linked Title", "url": "https://linked.com/z"} in srcs


def test_extract_write_content_handles_content_key_and_diffblock():
    assert "## Sources" in sl._extract_write_content({"content": "## Sources\nx"})
    db = {"filePath": "x.md", "diffBlock": [{"lines": [
        {"text": "## Sources", "action": "LINE_ACTION_INSERT"},
        {"text": "* A: https://a.com/1", "action": "LINE_ACTION_INSERT"},
        {"text": "stale", "action": "LINE_ACTION_DELETE"},
    ]}]}
    out = sl._extract_write_content(db)
    assert "## Sources" in out and "https://a.com/1" in out
    assert "stale" not in out  # deleted lines are not part of the new content


def test_brief_write_emits_sources_early(monkeypatch):
    events = _capture(monkeypatch)
    brief = ("# Topic\n\n## Sources\n"
             "* Illumina SBS Technology Workflow: https://www.illumina.com/x\n"
             "* Genetic Education: https://geneticeducation.co.in/y\n")
    sl._check_tool_call_for_status(
        _Chunk("edit_file", {"filePath": "/proj/projects/topic.md", "content": brief}))
    domains = _domains(events)
    assert "illumina.com" in domains
    assert "geneticeducation.co.in" in domains
    # Name preserved (richer than a bare-domain citation).
    assert "Illumina SBS Technology Workflow" in _names(events)


def test_brief_emit_dedups_against_later_manifest(monkeypatch):
    """The whole point: emit early from the brief, and the model's later manifest
    for the same domain adds nothing (no duplicate, correct ordering)."""
    events = _capture(monkeypatch)
    sl._check_tool_call_for_status(_Chunk("edit_file", {
        "filePath": "/p/projects/t.md",
        "content": "## Sources\n* Illumina: https://www.illumina.com/x\n"}))
    early = len(_domains(events))
    assert early == 1
    _stream('[[RESEARCH_SOURCES]]\n```json\n'
            '{"sources": [{"name": "Illumina SBS", "url": "https://www.illumina.com/x"}]}\n```\n')
    assert len(_domains(events)) == early  # deduped by domain — no late duplicate
