import os
import re
import json
import subprocess
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SPEAKER_INSTRUCTION = (
    "IMPORTANT: The transcripts use two speaker labels — "
    "[BROCCOLI TEAM] for internal team facilitation questions "
    "(do NOT extract these as insights — they are prompts, not data) "
    "and [INTERVIEWEE] for external participants "
    "(extract ALL insights exclusively from [INTERVIEWEE] lines). "
    "Internal team questions provide context only.\n\n"
)

PROMPT_PATTERNS = _SPEAKER_INSTRUCTION + """Analyze these interview transcripts and extract insights in the following categories. Always include direct quotes and note patterns across multiple interviews.

1. Pain Points & Frustrations
Extract recurring problems, broken processes, time-consuming tasks, and gaps between expectations vs. reality. Provide direct quotes and frequency.

2. Extreme User Behaviors
Identify unusual usage patterns, disproportionate responses to problems, obsessive behaviors, and actions indicating high desperation or motivation. Describe the behavior and explain the underlying need.

3. Hacky Solutions & Workarounds
Find creative makeshift solutions, tool combinations, manual workarounds, and personal systems developed out of necessity. Describe the hack and what problem it solves.

4. Deep Emotions & Psychological Drivers
Extract strong emotional reactions, identity statements ("I'm the type of person who..."), fears, aspirations, shame, and breakthrough moments. Quote emotional language directly and identify triggers.

5. Compelling Quotes
Select vivid, emotionally charged, surprisingly honest, or insightful quotes that capture complex ideas simply or reveal unexpected user behaviors.

6. Common Themes & Patterns
Identify concepts mentioned by multiple people, shared language/metaphors, recurring obstacles, and universal needs. Show frequency and supporting evidence.

For each category, provide:
- Top 3-5 insights with supporting quotes
- Frequency analysis of most common themes
- Notable outliers that don't fit patterns

Always use direct quotes rather than paraphrasing. Show frequency — note how many people mentioned similar things. Provide context for when/why quotes were made. Connect categories — show relationships between pain points and solutions. Flag contradictions when interviewees disagree. Prioritize insights revealing genuine user needs, strong emotions, and innovation opportunities."""

PROMPT_NOVEL_TEMPLATE = _SPEAKER_INSTRUCTION + """Analyze ONLY the interview titled '{title}' from {date} between {participants} against all OTHER transcripts in this notebook to identify completely novel insights, pain points, behaviors, emotions, and quotes that have never appeared in those OTHER transcripts. Focus on genuinely new information from the named transcript, not variations of existing themes.

DO NOT extract insights from any other transcript — those are the comparison baseline only. Every quote and insight you return MUST come from the transcript titled '{title}'.

If you cannot find a transcript matching '{title}' from {date} in this notebook, return only the literal text SOURCE_NOT_FOUND on a single line and nothing else.

Analysis Categories:

Novel Insights: New problem areas not mentioned previously, unique solution approaches or workarounds, unexpected use cases or market segments.

New Pain Points: Entirely new pain points not expressed before, familiar pain points with significantly different intensity/context, uncommon combinations of multiple pain points.

Distinctive Behaviors: Completely unprecedented user behaviors, extreme variations of familiar behaviors, unique adaptations or workflows, outlier usage patterns deviating from established norms.

Unique Emotions: New emotional categories not expressed previously, unusual emotional intensity or triggers, novel emotional combinations or journeys.

Original Quotes: New terminology or unique metaphors, novel framings of familiar concepts, fresh perspectives articulated compellingly.

For each category, provide:
- Brief description
- Why Novel: How it differs from all previous interviews
- Quote/Evidence: Specific supporting evidence
- Significance: Strategic importance

Quality Criteria — Include only insights that are completely absent from previous interviews, significantly different in nature/context/intensity, or potentially valuable for strategy. Exclude minor variations of existing themes, confirmations of known patterns, or demographic differences without behavioral implications.

Be rigorous — only flag truly novel information. Always cite specific evidence. Clearly explain why each insight is genuinely new. Consider strategic implications. Flag whether insights represent outliers or new segments."""


@dataclass
class AnalysisResult:
    patterns: str
    novel: str


@dataclass
class NovelResult:
    novel: str


def query_notebook(notebook_id: str, prompt: str, timeout: float = 180) -> str:
    """Run a prompt against a NotebookLM notebook via nlm CLI. Returns clean answer text."""
    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    result = subprocess.run(
        ["nlm", "notebook", "query", notebook_id, prompt, "--timeout", str(timeout)],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"nlm query failed: {result.stderr.strip()}")

    raw = result.stdout.strip()

    # nlm returns JSON — extract just the answer field
    try:
        data = json.loads(raw)
        answer = data.get("value", {}).get("answer") or data.get("answer") or raw
    except (json.JSONDecodeError, AttributeError):
        answer = raw

    # Strip inline citation numbers like [1], [1-3], [1, 2, 3]
    answer = re.sub(r'\s*\[[\d,\s\-]+\]', '', answer)

    return answer.strip()


def analyze_novel(
    notebook_id: str,
    title: str,
    date: str | None = None,
    participants: list[str] | None = None,
) -> NovelResult:
    """Per-meeting novel insights, scoped to ONE named transcript.

    Names the target transcript explicitly in the prompt so NLM doesn't
    pick its own "newest" by upload timestamp — which leaks insights
    from other recently-uploaded transcripts during recovery / backlog
    windows (the David/Jessy email mash-up of Apr 24).

    If NLM returns the SOURCE_NOT_FOUND sentinel, we fall back to passing
    the response through with a heads-up prefix rather than dropping the
    email — that way a brittle prompt match doesn't silently kill recap
    delivery. We log a warning so we can spot if it happens often.
    """
    prompt = PROMPT_NOVEL_TEMPLATE.format(
        title=title or "(untitled)",
        date=date or "unknown date",
        participants=", ".join(participants) if participants else "unknown",
    )
    logger.info(
        "Running novel insights analysis on notebook %s for '%s' (%s)",
        notebook_id, title, date,
    )
    raw = query_notebook(notebook_id, prompt)
    if raw.strip() == "SOURCE_NOT_FOUND":
        logger.warning(
            "NLM returned SOURCE_NOT_FOUND for '%s' (%s) in notebook %s — "
            "falling through with empty novel; check prompt scoping",
            title, date, notebook_id,
        )
        return NovelResult(
            novel=f"⚠️ Note: NotebookLM could not confidently scope this analysis to '{title}'. "
                  f"Treat the insights below with caution.\n\n{raw}"
        )
    return NovelResult(novel=raw)


def analyze_patterns(notebook_id: str) -> str:
    """Run only Prompt 1 (aggregate patterns) — used for weekly report."""
    logger.info("Running patterns analysis on notebook %s", notebook_id)
    return query_notebook(notebook_id, PROMPT_PATTERNS)


def analyze_notebook(notebook_id: str) -> AnalysisResult:
    """Run both prompts — kept for backwards compatibility."""
    return AnalysisResult(
        patterns=analyze_patterns(notebook_id),
        novel=analyze_novel(notebook_id).novel,
    )
