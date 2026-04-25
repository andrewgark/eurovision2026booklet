from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import requests


WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIMEDIA_FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/"
USER_AGENT = "eurovision2026booklet/1.0 (local build; contact: local)"


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
    r = _request_with_retry(
        "GET",
        WIKIDATA_SPARQL,
        params={"format": "json", "query": query},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=60,
    )
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


def _request_with_retry(
    method: str,
    url: str,
    *,
    max_retries: int = 5,
    base_delay: float = 2.0,
    **kwargs: Any,
) -> requests.Response:
    """HTTP request with exponential backoff, honoring Retry-After on 429/503."""
    delay = base_delay
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.request(method, url, **kwargs)
            if r.status_code in (429, 503):
                retry_after = r.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                print(f"  rate-limited ({r.status_code}) on {url}; sleeping {wait:.1f}s (attempt {attempt}/{max_retries})")
                time.sleep(wait)
                delay *= 2
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            print(f"  request error: {exc}; retrying in {delay:.1f}s (attempt {attempt}/{max_retries})")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"Failed to {method} {url} after {max_retries} attempts: {last_exc}")


def download_flags(
    *,
    countries_json: Path,
    out_svg_dir: Path,
    force: bool = False,
    request_delay: float = 1.0,
) -> None:
    out_svg_dir.mkdir(parents=True, exist_ok=True)

    countries = _read_json(countries_json)
    total = len(countries)
    for idx, c in enumerate(countries, 1):
        code = str(c["country_code"]).upper()
        qid = c.get("flag", {}).get("wikidata_qid")
        if not qid:
            print(f"[{idx}/{total}] {code}: no wikidata_qid, skipping")
            continue

        out = out_svg_dir / f"{code}.svg"
        if out.exists() and not force:
            print(f"[{idx}/{total}] {code}: cached ({out})")
            continue

        filename = _qid_to_flag_filename(qid)
        time.sleep(request_delay)

        url = WIKIMEDIA_FILEPATH + filename
        r = _request_with_retry(
            "GET",
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=120,
        )

        out.write_bytes(r.content)
        print(f"[{idx}/{total}] {code}: {out} ({filename})")
        time.sleep(request_delay)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--countries-json", default="data/countries.json")
    p.add_argument("--out-svg-dir", default="assets/flags/src_svg")
    p.add_argument("--force", action="store_true", help="Re-download even if cached locally")
    p.add_argument("--delay", type=float, default=1.0, help="Seconds to sleep between requests")
    args = p.parse_args()

    download_flags(
        countries_json=Path(args.countries_json),
        out_svg_dir=Path(args.out_svg_dir),
        force=args.force,
        request_delay=args.delay,
    )


if __name__ == "__main__":
    main()

