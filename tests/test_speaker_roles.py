from fireflies import Sentence
from speaker_roles import classify_speakers


def _sentence(speaker: str, text: str = "hello") -> Sentence:
    return Sentence(index=0, speaker_name=speaker, text=text, start_time=0.0, end_time=1.0)


def test_internal_speaker_matched_by_substring():
    sentences = [_sentence("Elman Amador"), _sentence("Jacob Torres")]
    roles = classify_speakers(sentences, internal_names=["elman"])
    assert roles["Elman Amador"] == "internal"
    assert roles["Jacob Torres"] == "external"


def test_case_insensitive_match():
    sentences = [_sentence("KLARA Smith"), _sentence("Bob Jones")]
    roles = classify_speakers(sentences, internal_names=["klara"])
    assert roles["KLARA Smith"] == "internal"


def test_unknown_speaker_is_external():
    sentences = [_sentence("Unknown")]
    roles = classify_speakers(sentences, internal_names=["elman", "klara"])
    assert roles["Unknown"] == "external"


def test_empty_sentences():
    roles = classify_speakers([], internal_names=["elman"])
    assert roles == {}


def test_multiple_internal_names():
    sentences = [_sentence("Elman"), _sentence("Klara"), _sentence("Guest")]
    roles = classify_speakers(sentences, internal_names=["elman", "klara"])
    assert roles["Elman"] == "internal"
    assert roles["Klara"] == "internal"
    assert roles["Guest"] == "external"
