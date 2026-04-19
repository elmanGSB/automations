"""Tests for meeting classifier."""
import pytest
from classifier import classify_meeting


@pytest.mark.asyncio
async def test_tools_research_classification():
    """Test that tool evaluation calls are classified as tools-research, not advisors."""
    # John Beeker call data: discussing Windmill, NotebookLM, Raggy, Compose U
    result = await classify_meeting(
        title="Elman amador and Jon",
        participants=["elman@stanford.edu", "jonathanbeekman@gmail.com"],
        summary="Discussed strategic reassessment, food distribution pivot, AI automation tools (Windmill, NotebookLM CLI, Raggy, Compose U)",
        transcript_excerpt="""[BROCCOLI TEAM]: Jon, thanks for jumping on. We're looking at some workflow automation tools to streamline our operations. Have you looked at Windmill?

[INTERVIEWEE]: Yeah, I've actually been evaluating Windmill for some of my projects. It's pretty solid for building internal tools and automating workflows.

[BROCCOLI TEAM]: What's your take on the UI? Is it intuitive for non-technical users?

[INTERVIEWEE]: The UI is clean, and they've got good documentation. I've also been testing NotebookLM's CLI functionality for document extraction and analysis.""",
    )

    assert result.category == "tools-research"
    assert result.confidence in ["high", "medium", "low"]
    assert isinstance(result.reasoning, str)
    assert len(result.reasoning) > 0


@pytest.mark.asyncio
async def test_advisor_vs_tools_research_disambiguation():
    """Test that advisor business mentorship is distinguished from tool evaluation."""
    # Advisor business mentorship call
    advisor_result = await classify_meeting(
        title="Elman and Advisor: Growth Strategy",
        participants=["elman@stanford.edu", "advisor@example.com"],
        summary="Discussed business strategy, market positioning, hiring decisions for food distribution pivot",
        transcript_excerpt="""[BROCCOLI TEAM]: Looking for your input on our growth strategy for the food distribution business.

[INTERVIEWEE]: You should focus on building relationships with larger distributors first. The market consolidation is accelerating.

[BROCCOLI TEAM]: Any thoughts on hiring for this pivot?

[INTERVIEWEE]: Hire someone with 10+ years in food distribution. The relationships are critical.""",
    )

    assert advisor_result.category == "advisors"

    # Tool evaluation call (same meeting, different conversation)
    tools_result = await classify_meeting(
        title="Elman and Advisor: Automation Tools",
        participants=["elman@stanford.edu", "advisor@example.com"],
        summary="Evaluated Windmill, NotebookLM, and other workflow automation platforms for operations",
        transcript_excerpt="""[BROCCOLI TEAM]: We're considering different automation platforms. What do you think of Windmill?

[INTERVIEWEE]: Windmill is solid for internal tools. Have you looked at their API integrations?

[BROCCOLI TEAM]: How does it compare to NotebookLM for document processing?

[INTERVIEWEE]: Different use cases. Windmill is better for workflows, NotebookLM for document analysis.""",
    )

    assert tools_result.category == "tools-research"
