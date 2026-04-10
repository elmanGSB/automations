from __future__ import annotations
from typing import Sequence
from fireflies import Sentence

INTERNAL_LABEL = "[BROCCOLI TEAM]"
EXTERNAL_LABEL = "[INTERVIEWEE]"


def format_with_roles(
    sentences: Sequence[Sentence],
    role_map: dict[str, str],
) -> str:
    """
    Format full transcript with role labels on every speaker change.

    Internal speakers → [BROCCOLI TEAM] (facilitation context only).
    External speakers → [INTERVIEWEE] (primary data source).
    Unknown speakers default to external.
    """
    lines: list[str] = []
    current_speaker: str | None = None

    for sentence in sentences:
        speaker = sentence.speaker_name
        role = role_map.get(speaker, "external")
        label = INTERNAL_LABEL if role == "internal" else EXTERNAL_LABEL

        if speaker != current_speaker:
            current_speaker = speaker
            lines.append(f"\n{label} {speaker}:")
        lines.append(sentence.text)

    return "\n".join(lines).strip()


def format_external_with_context(
    sentences: Sequence[Sentence],
    role_map: dict[str, str],
) -> str:
    """
    Format transcript for extraction — external statements are primary,
    preceded by internal questions as [CONTEXT/QUESTION] blocks.

    Trailing internal-only lines are intentionally omitted.
    """
    lines: list[str] = []
    pending_internal: list[str] = []
    current_speaker: str | None = None

    for sentence in sentences:
        speaker = sentence.speaker_name
        role = role_map.get(speaker, "external")

        if role == "internal":
            pending_internal.append(sentence.text)
        else:
            if pending_internal:
                context = " ".join(pending_internal)
                lines.append(f"\n[CONTEXT/QUESTION] {context}")
                pending_internal = []
                current_speaker = None  # force header after any context block
            if speaker != current_speaker:
                current_speaker = speaker
                lines.append(f"\n{EXTERNAL_LABEL} {speaker}:")
            lines.append(sentence.text)

    return "\n".join(lines).strip()
