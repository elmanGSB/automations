import os
import tempfile
from fireflies import Transcript, Sentence
from pdf_generator import generate_transcript_pdf

def test_generate_pdf_handles_special_characters():
    """Transcripts with & < > in text should not crash reportlab."""
    transcript = Transcript(
        id="special01",
        title="Call with AT&T about Revenue > Goals",
        date="2026-04-07",
        duration=900,
        participants=["ceo@att.com"],
        sentences=[
            Sentence(index=0, speaker_name="CEO", text="Our revenue > $1M & growing.", start_time=0.0, end_time=5.0),
        ],
        summary_overview="AT&T CEO discussed revenue < projections.",
        summary_action_items=["Send deck to AT&T"],
        summary_keywords=[],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_transcript_pdf(transcript, tmpdir)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 500

def make_transcript() -> Transcript:
    return Transcript(
        id="abc123",
        title="Customer call with Acme Corp",
        date="2026-04-07T14:00:00Z",
        duration=3600,
        participants=["alice@acme.com", "me@company.com"],
        sentences=[
            Sentence(index=0, speaker_name="Alice", text="Tell me about pricing.", start_time=5.0, end_time=8.2),
            Sentence(index=1, speaker_name="Me", text="Sure, let me walk you through it.", start_time=8.5, end_time=11.0),
            Sentence(index=2, speaker_name="Alice", text="What about enterprise plans?", start_time=11.5, end_time=14.0),
        ],
        summary_overview="Discussion about pricing.",
        summary_action_items=["Send pricing deck", "Schedule follow-up"],
        summary_keywords=["pricing", "enterprise"],
    )

def test_generate_pdf_creates_file():
    transcript = make_transcript()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = generate_transcript_pdf(transcript, tmpdir)
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 1000  # non-empty PDF

def test_generate_pdf_filename_is_slugified():
    transcript = make_transcript()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_transcript_pdf(transcript, tmpdir)
        filename = os.path.basename(path)
        # Should contain slugified title and partial transcript ID
        assert filename.endswith(".pdf")
        assert " " not in filename  # no spaces in filename
        assert "abc123"[:8] in filename  # transcript ID prefix

def test_generate_pdf_no_summary():
    """Should not crash when summary fields are empty."""
    transcript = Transcript(
        id="xyz789",
        title="Quick call",
        date="2026-04-07",
        duration=300,
        participants=[],
        sentences=[],
        summary_overview="",
        summary_action_items=[],
        summary_keywords=[],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_transcript_pdf(transcript, tmpdir)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 500
