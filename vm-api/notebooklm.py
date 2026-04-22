import re
import subprocess
from config import KNOWN_CATEGORIES


def create_notebook(title: str) -> str:
    """Create a NotebookLM notebook. Returns the notebook ID."""
    try:
        result = subprocess.run(
            ["nlm", "notebook", "create", title],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timed out creating notebook '{title}' after 120s")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create notebook '{title}': {result.stderr.strip()}")
    # Output format: "✓ Created notebook: Title\n  ID: <uuid>"
    match = re.search(r"ID:\s*([a-f0-9-]{36})", result.stdout)
    if not match:
        raise RuntimeError(f"Failed to parse notebook ID from output: {result.stdout!r}")
    return match.group(1)


def add_file_source(notebook_id: str, file_path: str, title: str) -> None:
    """Upload a local file as a source to a NotebookLM notebook.

    nlm source add accepts .pdf, .docx, .txt, .md, .csv, plus audio/video/image
    formats — see notebooklm-mcp-cli's supported_extensions set. The pipeline
    currently emits .docx (see docx_generator.py) but the function does not
    inspect the extension, so callers can pass any nlm-supported file.
    """
    try:
        result = subprocess.run(
            [
                "nlm", "source", "add", notebook_id,
                "--file", file_path,
                "--title", title,
                "--wait",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timed out uploading file to notebook '{notebook_id}' after 600s")
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
