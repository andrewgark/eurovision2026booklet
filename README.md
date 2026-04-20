# Eurovision 2026 Booklet (LuaLaTeX)

This project generates Eurovision 2026 PDF booklets from a shared knowledge base (Google Sheets).

## Outputs

We build **10 PDF variants** (5 booklet types × 2 languages):

- `overall_pre`: pre-contest overall booklet (all entries + odds page)
- `sf1`: Semi-final 1 booklet (entries in SF1 + odds page)
- `sf2`: Semi-final 2 booklet (entries in SF2 + odds page)
- `final`: Final booklet (finalists + odds page)
- `overall_post`: post-contest overall booklet (all entries + results page)

Languages:

- `en`
- `ru`

## Quick start (local JSON data)

1. Create a Python venv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Ensure you have TeX tooling installed:

- `latexmk`
- `lualatex`
- (optional) `inkscape` for converting SVG flags to PDF

On Ubuntu/WSL you can install them with:

```bash
sudo apt update
sudo apt install -y latexmk texlive-luatex texlive-latex-extra texlive-fonts-recommended texlive-lang-cyrillic
```

Verify:

```bash
latexmk -v
lualatex --version
```

Optional (for SVG → PDF conversion of flags):

```bash
sudo apt install -y inkscape
```

3. Build all PDFs (uses `data/*.json`):

```bash
python scripts/build_all.py
```

Outputs land in `dist/`.

## Collaboration workflow (Google Sheets → JSON snapshot)

We use a **two-step flow**:

1) `scripts/pull_sheets.py` pulls data from Google Sheets into local `data/*.json` snapshots.\n
2) LaTeX build reads only the local JSON snapshots (deterministic builds).

This keeps the build reproducible and avoids requiring Google credentials at LaTeX build time.

## Assets pipeline

Download + render assets (cached under `assets/`):

```bash
python scripts/assets_flags.py
python scripts/assets_maps.py
```

Convert flags to PDF (optional; requires Inkscape):

```bash
python scripts/assets_convert_flags.py
```

## Assets policy (no hallucinations)

- **Text fields** (bios, facts, lyrics, translations) are **manually written/pasted** into the Sheet. We do not auto-generate them.
- **Flags** and **maps** are fetched/generated automatically from approved sources, and cached under `assets/`.
- **Artist photos** are manual files placed in `assets/artists/` and referenced from the Sheet.

See `assets/sources.md` for the approved sources.

## Folder layout

- `data/`: JSON snapshots (config, countries, artists, songs, rounds, odds, results)\n
- `assets/`: flags, maps, artist photos\n
- `scripts/`: sync/build pipelines\n
- `tex/`: LaTeX styles + templates\n
- `build/`: generated TeX intermediates\n
- `dist/`: final PDFs\n

## Notes on TeX availability

If `latexmk` is not installed, `scripts/build_all.py` will fail. You can still generate TeX sources without running LaTeX:\n

```bash
python scripts/build.py --variant overall_pre --lang en
```

