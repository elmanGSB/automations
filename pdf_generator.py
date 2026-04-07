import os
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib import colors
from fireflies import Transcript


def _safe_filename(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug[:60]


def generate_transcript_pdf(transcript: Transcript, output_dir: str) -> str:
    """Generate a PDF from a transcript. Returns the path to the created file."""
    filename = f"{_safe_filename(transcript.title)}-{transcript.id[:8]}.pdf"
    output_path = os.path.join(output_dir, filename)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("MeetingTitle", parent=styles["Title"], fontSize=18, spaceAfter=6)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=10, textColor=colors.grey)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=12, spaceBefore=12)
    speaker_style = ParagraphStyle(
        "Speaker",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#1a56db"),
        fontName="Helvetica-Bold",
    )
    text_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14)
    bullet_style = ParagraphStyle("Bullet", parent=styles["Normal"], fontSize=10, leftIndent=12)

    date_str = transcript.date[:10] if transcript.date else "Unknown date"
    duration_min = transcript.duration // 60 if transcript.duration else 0

    story = [
        Paragraph(transcript.title or "Untitled Meeting", title_style),
        Paragraph(f"Date: {date_str} &nbsp;&nbsp; Duration: {duration_min} min", meta_style),
        Spacer(1, 0.4 * cm),
        HRFlowable(width="100%", thickness=1, color=colors.lightgrey),
        Spacer(1, 0.4 * cm),
    ]

    if transcript.participants:
        story.append(Paragraph(f"Participants: {', '.join(transcript.participants)}", meta_style))
        story.append(Spacer(1, 0.3 * cm))

    if transcript.summary_overview:
        story += [
            Paragraph("Summary", section_style),
            Paragraph(transcript.summary_overview, text_style),
            Spacer(1, 0.3 * cm),
        ]

    if transcript.summary_action_items:
        story.append(Paragraph("Action Items", section_style))
        for item in transcript.summary_action_items:
            story.append(Paragraph(f"• {item}", bullet_style))
        story.append(Spacer(1, 0.3 * cm))

    story += [
        HRFlowable(width="100%", thickness=1, color=colors.lightgrey),
        Paragraph("Full Transcript", section_style),
        Spacer(1, 0.2 * cm),
    ]

    if transcript.sentences:
        current_speaker = None
        for sentence in transcript.sentences:
            if sentence.speaker_name != current_speaker:
                current_speaker = sentence.speaker_name
                story.append(Paragraph(current_speaker, speaker_style))
            story.append(Paragraph(sentence.text, text_style))
    else:
        story.append(Paragraph("(No transcript available)", meta_style))

    doc.build(story)
    return output_path
