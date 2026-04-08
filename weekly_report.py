"""Weekly job: run aggregate patterns analysis on all notebooks and email results."""
import asyncio
import logging
from state import get_all_notebooks
from analyzer import analyze_patterns
from emailer import send_patterns_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def run_weekly_report() -> None:
    notebooks = get_all_notebooks()
    if not notebooks:
        logger.info("No notebooks found, skipping weekly report")
        return

    for category, notebook_id in notebooks.items():
        logger.info("Running patterns analysis for category '%s' (notebook %s)", category, notebook_id)
        try:
            patterns = analyze_patterns(notebook_id)
            await send_patterns_report(category, patterns)
            logger.info("Sent weekly report for '%s'", category)
        except Exception:
            logger.exception("Failed weekly report for category '%s'", category)


if __name__ == "__main__":
    asyncio.run(run_weekly_report())
