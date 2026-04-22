"""Rebuild state.json category mappings from NotebookLM ground truth.

Walks NotebookLM, reverse-maps titles to category slugs via KNOWN_CATEGORIES,
and rewrites the category->id mappings in state.json. Preserves _processed and
_nlm_uploaded arrays.

Refuses to write if the same title appears on multiple notebooks (which only
happens after a state.json wipe spawned duplicates) unless --pick-most-sources
is given. The most-sources notebook is the one with the most history worth
preserving.

Usage:
    python rebuild_state.py --dry-run
    python rebuild_state.py
    python rebuild_state.py --pick-most-sources
"""
import argparse
import json
import sys

import state
from config import KNOWN_CATEGORIES
from notebooklm import list_notebooks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print proposed mappings, do not write.")
    parser.add_argument(
        "--pick-most-sources",
        action="store_true",
        help="When duplicates per title exist, keep the one with most sources.",
    )
    args = parser.parse_args()

    title_to_slug = {title: slug for slug, title in KNOWN_CATEGORIES.items()}

    notebooks = list_notebooks()
    per_slug: dict[str, list[dict]] = {}
    skipped: list[str] = []
    for nb in notebooks:
        slug = title_to_slug.get(nb.get("title", ""))
        if slug:
            per_slug.setdefault(slug, []).append(nb)
        else:
            skipped.append(nb.get("title", "(no title)"))

    new_mappings: dict[str, str] = {}
    for slug, candidates in per_slug.items():
        if len(candidates) == 1:
            new_mappings[slug] = candidates[0]["id"]
            continue
        if not args.pick_most_sources:
            print(f"REFUSING: duplicate notebooks for category '{slug}':", file=sys.stderr)
            for c in candidates:
                print(
                    f"  - {c['id']}  sources={c.get('source_count')}  updated={c.get('updated_at')}",
                    file=sys.stderr,
                )
            print(
                "\nResolve in NotebookLM (delete or rename), or re-run with --pick-most-sources.",
                file=sys.stderr,
            )
            return 2
        best = max(candidates, key=lambda nb: nb.get("source_count", 0))
        print(
            f"DUPLICATE for {slug}: {len(candidates)} notebooks; "
            f"keeping {best['id']} ({best.get('source_count')} sources)"
        )
        new_mappings[slug] = best["id"]

    print("\nProposed mappings:")
    print(json.dumps(new_mappings, indent=2))
    if skipped:
        print(f"\nIgnoring {len(skipped)} notebook(s) not in KNOWN_CATEGORIES:")
        for t in skipped:
            print(f"  - {t}")

    if args.dry_run:
        print("\n--dry-run: no changes written.")
        return 0

    def _mutate(data: dict) -> None:
        for k, v in new_mappings.items():
            data[k] = v

    state._transact(_mutate)
    print("\nstate.json updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
