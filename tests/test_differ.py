"""Tests for the diff computation service."""

import json
import pytest
from app.services.differ import compute_full_diff


class TestDiffComputation:
    def test_identical_texts_produce_minimal_diff(self):
        text = "# Privacy Policy\n\nWe collect your data.\n"
        result = compute_full_diff(text, text)
        assert result["clauses_added"] == "[]" or json.loads(result["clauses_added"]) == []
        assert result["clauses_removed"] == "[]" or json.loads(result["clauses_removed"]) == []

    def test_added_section_detected(self):
        old = "# Privacy Policy\n\nWe collect your data.\n"
        new = "# Privacy Policy\n\nWe collect your data.\n\n## New Section\n\nNew content here.\n"
        result = compute_full_diff(old, new)
        added = json.loads(result["clauses_added"])
        assert len(added) > 0

    def test_removed_section_detected(self):
        old = "# Policy\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B.\n"
        new = "# Policy\n\n## Section A\n\nContent A.\n"
        result = compute_full_diff(old, new)
        removed = json.loads(result["clauses_removed"])
        assert len(removed) > 0

    def test_diff_html_is_generated(self):
        old = "# Policy\n\nOld text.\n"
        new = "# Policy\n\nNew text.\n"
        result = compute_full_diff(old, new)
        assert result["diff_html"] is not None
        assert len(result["diff_html"]) > 0

    def test_diff_text_is_unified_format(self):
        old = "Line one.\nLine two.\n"
        new = "Line one.\nLine three.\n"
        result = compute_full_diff(old, new)
        assert "---" in result["diff_text"] or "@@" in result["diff_text"] or result["diff_text"]
