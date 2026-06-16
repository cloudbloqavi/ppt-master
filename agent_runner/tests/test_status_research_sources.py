"""Regression tests for research-source citation timing in status_logger.

The bug: a populated `[[RESEARCH_SOURCES]]` manifest is often larger than the
streaming scan window (_SCAN_OVERLAP). The old gate only ran the parse while the
marker was still inside that window, so by the time the block's closing ``` fence
streamed in, the marker had scrolled out — the completed block was skipped and the
citations surfaced only when a *later* marker re-entered the window (at the very
end of the run) or never at all. These assert citations now fire as soon as the
block closes, regardless of block size.
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
