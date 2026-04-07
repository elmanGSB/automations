import json
import subprocess
from config import KNOWN_CATEGORIES


def create_notebook(title: str) -> str:
    """Create a NotebookLM notebook. Returns the notebook ID."""
    result = subprocess.run(
        ["nlm", "notebook", "create", title, "--output", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create notebook '{title}': {result.stderr.strip()}")
    data = json.loads(result.stdout.strip())
    return data["id"]


def add_pdf_source(notebook_id: str, pdf_path: str, title: str) -> None:
    """Upload a PDF file as a source to a NotebookLM notebook."""
    result = subprocess.run(
        [
            "nlm", "source", "add", notebook_id,
            "--file", pdf_path,
            "--title", title,
            "--wait",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to add source to notebook '{notebook_id}': {result.stderr.strip()}"
        )


def notebook_title_for_category(category: str) -> str:
    """Return a human-readable notebook title for a category slug."""
    if category in KNOWN_CATEGORIES:
        return KNOWN_CATEGORIES[category]
    # Unknown: title-case the slug
    return category.replace("-", " ").title()
