from fireflies import Sentence
from transcript_formatter import format_with_roles, format_external_with_context


def _s(speaker: str, text: str, idx: int = 0) -> Sentence:
    return Sentence(index=idx, speaker_name=speaker, text=text, start_time=0.0, end_time=1.0)


ROLE_MAP = {"Elman": "internal", "Jacob": "external"}


def test_format_with_roles_labels_speakers():
    sentences = [_s("Elman", "Can you tell me about your process?"), _s("Jacob", "Sure, we use spreadsheets.")]
    result = format_with_roles(sentences, ROLE_MAP)
    assert "[BROCCOLI TEAM] Elman:" in result
    assert "[INTERVIEWEE] Jacob:" in result
    assert "Can you tell me about your process?" in result
    assert "Sure, we use spreadsheets." in result


def test_format_with_roles_no_duplicate_speaker_header():
    sentences = [_s("Jacob", "First sentence.", 0), _s("Jacob", "Second sentence.", 1)]
    result = format_with_roles(sentences, ROLE_MAP)
    assert result.count("[INTERVIEWEE] Jacob:") == 1


def test_format_external_with_context_includes_question_as_context():
    sentences = [
        _s("Elman", "What's your biggest pain point?"),
        _s("Jacob", "Delivery tracking is broken."),
    ]
    result = format_external_with_context(sentences, ROLE_MAP)
    assert "[CONTEXT/QUESTION]" in result
    assert "What's your biggest pain point?" in result
    assert "[INTERVIEWEE] Jacob:" in result
    assert "Delivery tracking is broken." in result


def test_format_external_with_context_skips_trailing_internal():
    """Internal statements at end of transcript with no following external are omitted."""
    sentences = [_s("Elman", "Great, thanks!")]
    result = format_external_with_context(sentences, ROLE_MAP)
    assert "Great, thanks!" not in result


def test_unknown_speaker_treated_as_external():
    sentences = [_s("Stranger", "Hello")]
    result = format_with_roles(sentences, {})
    assert "[INTERVIEWEE] Stranger:" in result
