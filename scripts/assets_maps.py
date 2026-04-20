from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import requests
import zipfile
import io


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_naturalearth_admin0_cache(*, cache_dir: Path) -> Path:
    """
    Download and cache Natural Earth Admin 0 countries (110m) shapefile.
    Returns path to the .shp file.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    shp = cache_dir / "ne_110m_admin_0_countries.shp"
    if shp.exists():
        return shp

    # Natural Earth direct zip (110m Admin 0 Countries)
    url = "https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_admin_0_countries.zip"
    r = requests.get(url, timeout=120)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(cache_dir)

    if not shp.exists():
        raise RuntimeError(f"Natural Earth shapefile missing after download: {shp}")
    return shp


def render_maps(*, countries_json: Path, out_pdf_dir: Path) -> None:
    """
    Render monochrome Admin-0 country silhouettes to PDF.

    Data source: Natural Earth via GeoPandas built-in dataset access.
    Style: single fill color (black), no borders/labels.
    """
    out_pdf_dir.mkdir(parents=True, exist_ok=True)

    countries = _read_json(countries_json)
    iso2s = {str(c["country_code"]).upper() for c in countries if str(c.get("country_code", "")).strip()}

    cache_dir = Path("assets") / "cache" / "naturalearth_admin0_110m"
    shp = _ensure_naturalearth_admin0_cache(cache_dir=cache_dir)
    world = gpd.read_file(shp)
    # Natural Earth Admin 0 uses ISO_A2
    if "ISO_A2" not in world.columns:
        raise RuntimeError("Natural Earth dataset missing ISO_A2 column; cannot render maps deterministically.")

    for iso2 in sorted(iso2s):
        g = world[world["ISO_A2"] == iso2]
        if g.empty:
            # Not fatal; keep going.
            continue

        fig = plt.figure(figsize=(2.4, 2.4))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()

        g.plot(ax=ax, color="black", linewidth=0)
        ax.set_aspect("equal")

        out = out_pdf_dir / f"{iso2}.pdf"
        fig.savefig(out, dpi=300, transparent=True)
        plt.close(fig)
        print(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--countries-json", default="data/countries.json")
    p.add_argument("--out-pdf-dir", default="assets/generated/maps/pdf")
    args = p.parse_args()

    render_maps(countries_json=Path(args.countries_json), out_pdf_dir=Path(args.out_pdf_dir))


if __name__ == "__main__":
    main()

