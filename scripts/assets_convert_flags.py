from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def _require_cmd(cmd: str) -> None:
    if not shutil.which(cmd):
        raise RuntimeError(
            f"Required command not found: {cmd}. "
            "Install inkscape (recommended) or provide pre-converted PDFs in assets/flags/pdf/."
        )


def convert_svg_to_pdf(*, in_svg_dir: Path, out_pdf_dir: Path) -> None:
    """
    Convert SVG flags to PDF for LaTeX inclusion.

    Uses Inkscape CLI if available.
    """
    _require_cmd("inkscape")

    out_pdf_dir.mkdir(parents=True, exist_ok=True)
    for svg in sorted(in_svg_dir.glob("*.svg")):
        pdf = out_pdf_dir / (svg.stem.upper() + ".pdf")
        subprocess.run(
            ["inkscape", str(svg), "--export-type=pdf", "--export-filename", str(pdf)],
            check=True,
        )
        print(pdf)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in-svg-dir", default="assets/flags/src_svg")
    p.add_argument("--out-pdf-dir", default="assets/flags/pdf")
    args = p.parse_args()

    convert_svg_to_pdf(in_svg_dir=Path(args.in_svg_dir), out_pdf_dir=Path(args.out_pdf_dir))


if __name__ == "__main__":
    main()

