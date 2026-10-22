# Eurovision Booklets (LuaLaTeX)

This project generates PDF and static HTML booklets for multiple contests from per-edition snapshots.

**Source spreadsheet:** [Eurovision Booklet Content](https://docs.google.com/spreadsheets/d/1INXyh8glLCOrtI_M-cV_gZ7LXcr5mBm0ffeVhYXQIVc/edit) (view/export access required for pulls).

Each edition lives under `editions/<edition-id>/data/` and treats each row as **one country ↔ one artist ↔ one song**; **`country_code` (ISO2) is the stable id** in JSON.

## Outputs

The Eurovision 2026 edition builds **10 PDFs** (5 booklet types × 2 languages):

- `overall_pre`: pre-contest overall booklet (all entries + odds page)
- `sf1`: Semi-final 1 booklet (entries in SF1 + odds page)
- `sf2`: Semi-final 2 booklet (entries in SF2 + odds page)
- `final`: Final booklet (finalists + odds page)
- `overall_post`: post-contest overall booklet (all entries + results page)

Languages configured for the current editions:

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
- (optional) `inkscape` only if you use the legacy SVG→PDF flag conversion script

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

3. Build the variants and languages configured for an edition:

```bash
python scripts/build_all.py
```

Outputs land in `dist/<edition-id>/`.

## Adding an edition

Create `editions/<edition-id>/edition.json` and put its JSON snapshots in `editions/<edition-id>/data/`.
The manifest declares the edition's available variants, country sort order, and output filename stems.
The build scripts load these settings through `BookletEdition`; adding a new contest does not require edits to the build code.

```json
{
  "edition_id": "eurovision-asia-2026",
  "variants": ["final"],
  "country_sort": "english",
  "output_stems": {"final": "eurovision_asia_2026_final"}
}
```

`country_sort` can be `english` or `localized`. `variants` controls which booklets can be built; for example, a one-final contest only needs `final`.

## Collaboration workflow (Google Sheets → JSON snapshot)

We use a **two-step flow**:

1. `scripts/pull_sheets.py` pulls CSV exports from the configured booklet spreadsheet into an edition's `data/*.json` and saves raw tab CSV under `data/source_csv/` (use `--no-save-csv` to skip snapshots).
2. LaTeX build reads only the local JSON snapshots (deterministic builds).

```bash
.venv/bin/python scripts/pull_sheets.py --out-data-dir editions/eurovision-2026/data
.venv/bin/python scripts/build_all.py --edition eurovision-2026
```

Use `--format template` plus `--gid-*` flags if you point at a sheet that follows the older column layout in `templates/sheets/`.

This keeps the build reproducible and avoids requiring Google credentials at LaTeX build time.

## Assets pipeline

Download + render assets (cached under `assets/`):

```bash
python scripts/assets_flags.py
python scripts/assets_maps.py
```

Flags are cached as **PNG/JPEG** under `assets/flags/png/` (SVG flags are rasterized on Wikimedia Commons up to `--svg-width` pixels wide, default 4096). LaTeX uses those files directly.

Legacy: convert **SVG**s under `assets/flags/src_svg/` to PDF (requires Inkscape) if you still maintain that folder:

```bash
python scripts/assets_convert_flags.py
```

## Assets policy (no hallucinations)

- **Text fields** (bios, facts, lyrics, translations) are **manually written/pasted** into the Sheet. We do not auto-generate them.
- **Flags** and **maps** are fetched/generated automatically from approved sources, and cached under `assets/`.
- **Artist photos** are manual files placed in `assets/artists/` and referenced from the Sheet.

See `assets/sources.md` for the approved sources.

## Folder layout

- `editions/<edition-id>/edition.json`: contest-specific build settings and source metadata
- `editions/<edition-id>/data/`: JSON snapshots (config, countries, artists, songs, rounds, odds, results) and optional `source_csv/` exports
- `editions/<edition-id>/assets/`: files that belong to one edition, such as artist photos
- `assets/`: booklet assets — flags (`flags/png/` raster, optional legacy `flags/pdf/`), maps, artist photos
- `scripts/`: sync/build pipelines
- `tex/`: LaTeX styles + templates
- `build/<edition-id>/`: generated TeX intermediates
- `dist/<edition-id>/`: final PDFs and HTML

To build only a final booklet (for a contest without semi-finals):

```bash
.venv/bin/python scripts/build_all.py --edition eurovision-asia-2026 --variants final --langs en ru
```

## Notes on TeX availability

If `latexmk` is not installed, `scripts/build_all.py` will fail. You can still generate TeX sources without running LaTeX:

```bash
python scripts/build.py --variant overall_pre --lang en
```

