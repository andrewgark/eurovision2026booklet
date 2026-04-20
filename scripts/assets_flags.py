from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import requests


WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIMEDIA_FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _qid_to_flag_filename(qid: str) -> str:
    """
    Resolve a Wikidata QID (country) -> Commons filename of its flag (P41).
    Returns a filename like: 'Flag of Sweden.svg'
    """
    query = f"""
    SELECT ?flag WHERE {{
      wd:{qid} wdt:P41 ?flag .
    }}
    LIMIT 1
    """
    r = requests.get(
        WIKIDATA_SPARQL,
        params={"format": "json", "query": query},
        headers={"User-Agent": "eurovision2026booklet/1.0 (local build)"},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        raise RuntimeError(f"No P41 flag found for {qid}")
    url = bindings[0]["flag"]["value"]
    # Example: http://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Sweden.svg
    m = re.search(r"/Special:FilePath/(.+)$", url)
    if not m:
        raise RuntimeError(f"Unexpected flag URL for {qid}: {url}")
    from urllib.parse import unquote

    return unquote(m.group(1))


def download_flags(*, countries_json: Path, out_svg_dir: Path) -> None:
    out_svg_dir.mkdir(parents=True, exist_ok=True)

    countries = _read_json(countries_json)
    for c in countries:
        code = str(c["country_code"]).upper()
        qid = c.get("flag", {}).get("wikidata_qid")
        if not qid:
            continue
        filename = _qid_to_flag_filename(qid)

        # Download from Wikimedia Commons via Special:FilePath
        url = WIKIMEDIA_FILEPATH + filename
        r = requests.get(url, headers={"User-Agent": "eurovision2026booklet/1.0 (local build)"}, timeout=120)
        r.raise_for_status()

        out = out_svg_dir / f"{code}.svg"
        out.write_bytes(r.content)
        print(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--countries-json", default="data/countries.json")
    p.add_argument("--out-svg-dir", default="assets/flags/src_svg")
    args = p.parse_args()

    download_flags(countries_json=Path(args.countries_json), out_svg_dir=Path(args.out_svg_dir))


if __name__ == "__main__":
    main()

