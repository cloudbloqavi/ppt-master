"""Unit tests for agent_runner.checkpoints — artifact-driven stage detection.

Builds synthetic project folders at each pipeline rung in a tmp dir and asserts
the detector classifies the stage (and per-slide resume set) correctly, including
the "partial/truncated artifact" cases that naive existence checks get wrong.
"""
from pathlib import Path

import pytest

from agent_runner import checkpoints as cp


# ── builders ─────────────────────────────────────────────────────────────────
def _valid_svg(path: Path, pad: int = 600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1280 720'>"
    body += "<rect/>" * pad  # pad past the _MIN_SVG_BYTES floor
    path.write_text(body + "</svg>", encoding="utf-8")


def _spec_lock(project: Path, n: int) -> None:
    rows = "\n".join(f"- P{i:02d}: dense" for i in range(1, n + 1))
    (project / "spec_lock.md").write_text(
        f"## colors\n- bg: #fff\n\n## page_rhythm\n{rows}\n\n## forbidden\n- x\n",
        encoding="utf-8",
    )


def _make_project(root: Path, name: str = "demo_ppt169_20260615_1002") -> Path:
    p = root / name
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── count_pages ──────────────────────────────────────────────────────────────
def test_count_pages_parses_rhythm(tmp_path):
    proj = _make_project(tmp_path)
    _spec_lock(proj, 4)
    assert cp.count_pages(proj / "spec_lock.md") == 4


def test_count_pages_missing_returns_none(tmp_path):
    assert cp.count_pages(tmp_path / "nope.md") is None


# ── detect_stage rungs ───────────────────────────────────────────────────────
def test_stage_done(tmp_path):
    proj = _make_project(tmp_path)
    _spec_lock(proj, 2)
    (proj / "exports").mkdir()
    (proj / "exports" / "demo_20260615.pptx").write_bytes(b"PK\x03\x04stub")
    assert cp.detect_stage(proj).stage == cp.STAGE_DONE


def test_stage_finalized(tmp_path):
    proj = _make_project(tmp_path)
    _spec_lock(proj, 2)
    _valid_svg(proj / "svg_final" / "P01.svg")
    _valid_svg(proj / "svg_final" / "P02.svg")
    assert cp.detect_stage(proj).stage == cp.STAGE_FINALIZED


def test_stage_notes(tmp_path):
    proj = _make_project(tmp_path)
    _spec_lock(proj, 2)
    _valid_svg(proj / "svg_output" / "P01.svg")
    _valid_svg(proj / "svg_output" / "P02.svg")
    (proj / "notes").mkdir()
    (proj / "notes" / "total.md").write_text("notes here", encoding="utf-8")
    assert cp.detect_stage(proj).stage == cp.STAGE_NOTES


def test_stage_svg_done_without_notes(tmp_path):
    proj = _make_project(tmp_path)
    _spec_lock(proj, 2)
    _valid_svg(proj / "svg_output" / "P01.svg")
    _valid_svg(proj / "svg_output" / "P02.svg")
    assert cp.detect_stage(proj).stage == cp.STAGE_SVG_DONE


def test_stage_svg_partial_reports_missing_pages(tmp_path):
    proj = _make_project(tmp_path)
    _spec_lock(proj, 4)
    _valid_svg(proj / "svg_output" / "P01.svg")
    _valid_svg(proj / "svg_output" / "P03.svg")
    state = cp.detect_stage(proj)
    assert state.stage == cp.STAGE_SVG_PARTIAL
    assert state.valid_pages == 2
    assert state.next_pages == [2, 4]


def test_stage_svg_partial_excludes_truncated(tmp_path):
    """A half-written SVG (crash mid-write) must NOT count as a finished page."""
    proj = _make_project(tmp_path)
    _spec_lock(proj, 2)
    _valid_svg(proj / "svg_output" / "P01.svg")
    (proj / "svg_output" / "P02.svg").write_text("<svg", encoding="utf-8")  # truncated stub
    state = cp.detect_stage(proj)
    assert state.stage == cp.STAGE_SVG_PARTIAL
    assert state.next_pages == [2]


def test_stage_spec_locked(tmp_path):
    proj = _make_project(tmp_path)
    _spec_lock(proj, 3)
    (proj / "svg_output").mkdir()
    assert cp.detect_stage(proj).stage == cp.STAGE_SPEC_LOCKED


def test_stage_spec_only(tmp_path):
    proj = _make_project(tmp_path)
    (proj / "design_spec.md").write_text("# spec", encoding="utf-8")
    assert cp.detect_stage(proj).stage == cp.STAGE_SPEC


def test_stage_init(tmp_path):
    proj = _make_project(tmp_path)
    (proj / "svg_output").mkdir()  # structural marker, but no spec yet
    assert cp.detect_stage(proj).stage == cp.STAGE_INIT


# ── find_active_project ──────────────────────────────────────────────────────
def test_find_active_project_picks_newest(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    old = _make_project(root, "old_ppt169_1")
    _spec_lock(old, 1)
    new = _make_project(root, "new_ppt169_2")
    _spec_lock(new, 1)
    import os
    os.utime(old, (1000, 1000))
    os.utime(new, (5000, 5000))
    assert cp.find_active_project([root], since_mtime=0.0) == new


def test_find_active_project_skips_stale_before_run_start(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    stale = _make_project(root, "stale_ppt169_1")
    _spec_lock(stale, 1)
    import os
    os.utime(stale, (1000, 1000))
    assert cp.find_active_project([root], since_mtime=9000.0) is None


def test_find_active_project_ignores_non_project_dirs(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    (root / "just_a_folder").mkdir()  # no structural markers
    assert cp.find_active_project([root], since_mtime=0.0) is None


# ── build_resume_directive ───────────────────────────────────────────────────
def test_resume_directive_case_a_forbids_reinit(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    proj = _make_project(root, "demo_ppt169_2")
    _spec_lock(proj, 2)
    _valid_svg(proj / "svg_output" / "P01.svg")  # partial
    directive = cp.build_resume_directive([root], since_mtime=0.0)
    assert directive is not None
    assert "ALREADY EXISTS" in directive
    assert "Do NOT run `project_manager.py init`" in directive
    assert "P02" in directive  # names the page still to author


def test_resume_directive_case_a_done_returns_none(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    proj = _make_project(root, "demo_ppt169_3")
    _spec_lock(proj, 1)
    (proj / "exports").mkdir()
    (proj / "exports" / "x.pptx").write_bytes(b"PK")
    assert cp.build_resume_directive([root], since_mtime=0.0) is None


def test_resume_directive_case_b_research_reuse(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    (root / "fintech_sea.md").write_text("# research brief", encoding="utf-8")
    directive = cp.build_resume_directive([root], since_mtime=0.0)
    assert directive is not None
    assert "ALREADY SAVED" in directive
    assert "Do NOT repeat web research" in directive


def test_resume_directive_none_when_empty(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    assert cp.build_resume_directive([root], since_mtime=0.0) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
