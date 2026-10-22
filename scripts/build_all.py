from __future__ import annotations

import sys
import argparse
from pathlib import Path

# Allow running via: `python scripts/build_all.py`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build import build_one
from scripts.build_html import build_html_one
from scripts.edition import BookletEdition


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", default="eurovision-2026")
    parser.add_argument("--variants", nargs="+")
    parser.add_argument("--langs", nargs="+", default=["en", "ru"])
    parser.add_argument("--pdf-only", action="store_true")
    args = parser.parse_args()
    edition = BookletEdition.load(args.edition)
    variants = args.variants or list(edition.variants)
    invalid = [v for v in variants if v not in edition.variants]
    if invalid:
        parser.error(f"variants not configured for {args.edition}: {', '.join(invalid)}")
    langs = args.langs

    for v in variants:
        for l in langs:
            # Run LaTeX by default for the "build all" command.
            pdf = build_one(v, l, run_latex=True, edition=args.edition)
            print("pdf", pdf)
            if not args.pdf_only:
                html_dir = build_html_one(v, l, edition=args.edition)
                print("html", html_dir)


if __name__ == "__main__":
    main()

