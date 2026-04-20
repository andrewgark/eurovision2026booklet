from __future__ import annotations

import sys
from pathlib import Path

# Allow running via: `python scripts/build_all.py`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build import build_one


def main() -> None:
    variants = ["overall_pre", "sf1", "sf2", "final", "overall_post"]
    langs = ["en", "ru"]

    for v in variants:
        for l in langs:
            # Run LaTeX by default for the "build all" command.
            out = build_one(v, l, run_latex=True)
            print(out)


if __name__ == "__main__":
    main()

