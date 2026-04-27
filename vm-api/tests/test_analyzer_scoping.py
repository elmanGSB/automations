"""Tests for the prompt-scoping fix that names the target transcript explicitly.

Background: Apr 24 incident — an email titled "Jessy Frozen AM" had a body
discussing both Jessy and David Abadin because NLM picked "newest" by upload
timestamp and treated multiple recently-uploaded transcripts as candidates.
"""
import os

from unittest.mock import patch

os.environ.setdefault("FIREFLIES_API_KEY", "test")


def test_analyze_novel_includes_target_metadata_in_prompt():
    """The prompt must explicitly name the target transcript so NLM doesn't
    fall back to its own freshness heuristic."""
    from analyzer import analyze_novel

    captured = {}

    def fake_query(notebook_id, prompt, timeout=180):
        captured["prompt"] = prompt
        return "## Novel Insights\n- something"

    with patch("analyzer.query_notebook", side_effect=fake_query):
        analyze_novel(
            "nb-id",
            title="Jessy Frozen AM",
            date="2026-04-22",
            participants=["Elman", "Jessy"],
        )

    p = captured["prompt"]
    assert "Jessy Frozen AM" in p
    assert "2026-04-22" in p
    assert "Elman" in p
    assert "Jessy" in p
    assert "SOURCE_NOT_FOUND" in p
    assert "DO NOT extract insights from any other transcript" in p


def test_analyze_novel_returns_normal_result_on_clean_response():
    from analyzer import analyze_novel

    with patch("analyzer.query_notebook", return_value="## Novel\n- foo"):
        result = analyze_novel("nb", title="Real Meeting", date="2026-04-22")

    assert "foo" in result.novel
    assert "could not confidently scope" not in result.novel


def test_analyze_novel_falls_through_with_warning_on_source_not_found():
    """When NLM can't scope, we still pass the response through with a
    cautionary prefix rather than dropping the email entirely. Logs a
    warning so we can spot recurrence."""
    from analyzer import analyze_novel

    with patch("analyzer.query_notebook", return_value="SOURCE_NOT_FOUND"):
        result = analyze_novel(
            "nb",
            title="Ghost Meeting",
            date="2026-04-22",
            participants=[],
        )

    assert "could not confidently scope" in result.novel
    assert "Ghost Meeting" in result.novel


def test_analyze_novel_handles_missing_optional_args():
    """date and participants are optional — defaults must produce a
    well-formed prompt rather than the literal string 'None'."""
    from analyzer import analyze_novel

    captured = {}

    def fake_query(notebook_id, prompt, timeout=180):
        captured["prompt"] = prompt
        return "ok"

    with patch("analyzer.query_notebook", side_effect=fake_query):
        analyze_novel("nb", title="Real Meeting")

    p = captured["prompt"]
    assert "None" not in p
    assert "unknown" in p  # the default for date/participants
