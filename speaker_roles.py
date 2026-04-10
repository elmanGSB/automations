from __future__ import annotations
from typing import Sequence
from fireflies import Sentence


def classify_speakers(
    sentences: Sequence[Sentence],
    internal_names: Sequence[str],
) -> dict[str, str]:
    """
    Return {speaker_name: "internal" | "external"} for every speaker in sentences.

    A speaker is internal if their name contains any of the internal_names substrings
    (case-insensitive). All others are external.
    """
    internal_lower = [n.lower() for n in internal_names]
    roles: dict[str, str] = {}
    for sentence in sentences:
        name = sentence.speaker_name
        if name in roles:
            continue
        is_internal = any(fragment in name.lower() for fragment in internal_lower)
        roles[name] = "internal" if is_internal else "external"
    return roles
