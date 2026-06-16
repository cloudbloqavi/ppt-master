"""Unit tests for the user-facing status line built by visual_enforcement.

Regression context: the status_progress feed used to show a bare count
("Visual review found 16 layout issue(s)...") with no indication of what kind
of issue, and soft (D4) findings never appeared in it at all. These tests pin
that the plain-language category breakdown (e.g. "overlapping text") is built
correctly from the auditor's raw per-page JSON and surfaces in status_line(),
and that soft findings are never silently dropped from any status.
"""
from collections import Counter

from agent_runner import visual_enforcement as ve


def test_breakdown_from_pages_counts_fixes_and_remaining_hard():
    pages = [
        {
            "fixes_applied": ["D2_text_overlap x6", "D3_out_of_bounds x1"],
            "findings": [
                {"rule": "D2_text_overlap", "severity": "hard", "autofix": "applied"},
                {"rule": "D3_out_of_bounds", "severity": "hard", "autofix": "applied"},
                {"rule": "D4_text_overflow", "severity": "soft", "autofix": "none"},
            ],
        },
        {
            "fixes_applied": [],
            "findings": [
                {"rule": "D2_text_overlap", "severity": "hard", "autofix": "none"},
            ],
        },
    ]
    fixed, remaining = ve._breakdown_from_pages(pages)
    assert fixed == Counter({"D2_text_overlap": 6, "D3_out_of_bounds": 1})
    assert remaining == Counter({"D2_text_overlap": 1})


def test_format_categories_is_plain_language_no_rule_codes():
    text = ve._format_categories(Counter({"D2_text_overlap": 6, "D3_out_of_bounds": 1}))
    assert "D2_text_overlap" not in text
    assert "D3_out_of_bounds" not in text
    assert "overlapping text" in text
    assert "text running off the slide edge" in text
    assert " and " in text


def test_format_categories_empty_is_empty_string():
    assert ve._format_categories(Counter()) == ""


def test_status_line_fixed_names_the_category():
    result = {
        "status": "fixed", "fixes": 15, "hard_remaining": 0, "soft_remaining": 0,
        "fixed_breakdown": Counter({"D2_text_overlap": 12, "D3_out_of_bounds": 4}),
        "remaining_breakdown": Counter(),
    }
    line = ve.status_line(result)
    assert "fixed 15" in line
    assert "overlapping text" in line
    assert "text running off the slide edge" in line
    assert "D2_text_overlap" not in line


def test_status_line_never_drops_soft_findings():
    result = {
        "status": "fixed", "fixes": 1, "hard_remaining": 0, "soft_remaining": 9,
        "fixed_breakdown": Counter({"D1_orphan_baseline": 1}), "remaining_breakdown": Counter(),
    }
    line = ve.status_line(result)
    assert "9 minor formatting note(s)" in line


def test_status_line_unresolved_names_the_category():
    result = {
        "status": "unresolved", "hard_remaining": 9, "soft_remaining": 0,
        "fixed_breakdown": Counter(), "remaining_breakdown": Counter({"D2_text_overlap": 9}),
    }
    line = ve.status_line(result)
    assert "9 layout issue(s)" in line
    assert "overlapping text" in line


def test_status_line_clean_with_soft_still_reports_soft():
    result = {"status": "clean", "hard_remaining": 0, "soft_remaining": 2,
              "fixed_breakdown": Counter(), "remaining_breakdown": Counter()}
    line = ve.status_line(result)
    assert "passed" in line
    assert "2 minor formatting note(s)" in line
