from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
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
    m = re.search(r"/Special:FilePath/(.+)$", url)
    if not m:
        raise RuntimeError(f"Unexpected flag URL for {qid}: {url}")
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


def _commons_imageinfo(file_title: str, *, svg_raster_width: int) -> dict[str, Any]:
    """file_title must be like 'File:Flag of Sweden.svg'."""
    params: dict[str, Any] = {
        "action": "query",
        "format": "json",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
    }
    if svg_raster_width > 0:
        params["iiurlwidth"] = svg_raster_width

    r = _request_with_retry(
        "GET",
        COMMONS_API,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=120,
    )
    payload = r.json()
    pages = payload.get("query", {}).get("pages", {})
    if not pages:
        raise RuntimeError(f"Commons API: empty pages for {file_title!r}")
    page = next(iter(pages.values()))
    if page.get("missing"):
        raise RuntimeError(f"Commons file missing: {file_title!r}")
    infos = page.get("imageinfo") or []
    if not infos:
        raise RuntimeError(f"Commons API: no imageinfo for {file_title!r}")
    return infos[0]


def _commons_download_url(ii: dict[str, Any]) -> str:
    """
    Wikimedia rasterizes SVGs to PNG when iiurlwidth is set → use thumburl.
    For raster originals, use the full-resolution url.
    """
    mime = (ii.get("mime") or "").lower()
    if mime == "image/svg+xml":
        u = ii.get("thumburl")
        if not u:
            raise RuntimeError(f"No PNG thumbnail for SVG (Commons / iiurlwidth): {ii!r}")
        return u
    u = ii.get("url")
    if not u:
        raise RuntimeError(f"No file URL in imageinfo: {ii!r}")
    return u


def _guess_ext(*, content_type: str, url: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if "jpeg" in ct or ct == "image/jpg":
        return ".jpg"
    if "png" in ct:
        return ".png"
    lu = url.split("?", 1)[0].lower()
    for suf, ext in (
        (".png", ".png"),
        (".jpg", ".jpg"),
        (".jpeg", ".jpg"),
    ):
        if lu.endswith(suf):
            return ext
    return ".png"


def download_flags(
    *,
    countries_json: Path,
    out_dir: Path,
    force: bool = False,
    request_delay: float = 0.1,
    svg_raster_width: int = 1024,
) -> None:
    """
    Fetch each country's flag from Wikimedia Commons (via Wikidata P41) as a
    high-resolution raster (PNG for SVG flags; original file for raster flags).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    countries = _read_json(countries_json)
    total = len(countries)
    raster_exts = {".png", ".jpg", ".jpeg"}

    for idx, c in enumerate(countries, 1):
        code = str(c["country_code"]).upper()
        qid = c.get("flag", {}).get("wikidata_qid")
        if not qid:
            print(f"[{idx}/{total}] {code}: no wikidata_qid, skipping", flush=True)
            continue

        existing_raster = [
            p for p in out_dir.glob(f"{code}.*") if p.suffix.lower() in raster_exts
        ]
        if existing_raster and not force:
            print(f"[{idx}/{total}] {code}: cached ({existing_raster[0].name})", flush=True)
            continue

        # Wikidata + Commons only when we actually need a fresh file (avoids N remote calls on cached runs).
        t_fetch = time.monotonic()
        print(
            f"[{idx}/{total}] {code}: fetching P41 from Wikidata ({qid})…",
            flush=True,
        )
        t0 = time.monotonic()
        filename = _qid_to_flag_filename(qid)
        print(
            f"[{idx}/{total}] {code}: Wikidata → {filename!r} ({time.monotonic() - t0:.1f}s)",
            flush=True,
        )
        file_title = "File:" + filename if not filename.startswith("File:") else filename

        if request_delay > 0:
            time.sleep(request_delay)

        print(f"[{idx}/{total}] {code}: Commons imageinfo (svg width={svg_raster_width})…", flush=True)
        t1 = time.monotonic()
        ii = _commons_imageinfo(file_title, svg_raster_width=svg_raster_width)
        mime = (ii.get("mime") or "").lower()
        print(
            f"[{idx}/{total}] {code}: imageinfo OK ({mime or 'unknown mime'}, {time.monotonic() - t1:.1f}s)",
            flush=True,
        )
        dl_url = _commons_download_url(ii)

        print(f"[{idx}/{total}] {code}: downloading raster…", flush=True)
        t2 = time.monotonic()
        r = _request_with_retry(
            "GET",
            dl_url,
            headers={"User-Agent": USER_AGENT},
            timeout=120,
        )
        nbytes = len(r.content)
        print(
            f"[{idx}/{total}] {code}: downloaded {nbytes // 1024} KiB ({time.monotonic() - t2:.1f}s)",
            flush=True,
        )
        ext = _guess_ext(content_type=r.headers.get("Content-Type", ""), url=dl_url)
        out = (out_dir / code).with_suffix(ext)
        for old in existing_raster:
            old.unlink()
        out.write_bytes(r.content)
        print(
            f"[{idx}/{total}] {code}: wrote {out.name} — total {time.monotonic() - t_fetch:.1f}s",
            flush=True,
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Download country flags from Wikimedia Commons as high-quality raster images (PNG/JPEG)."
    )
    p.add_argument("--countries-json", default="data/countries.json")
    p.add_argument(
        "--out-dir",
        default="assets/flags/png",
        help="Directory for <CC>.png (or .jpg if Commons serves JPEG).",
    )
    p.add_argument("--force", action="store_true", help="Re-download even if cached locally")
    p.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="Seconds to sleep before Commons after Wikidata (0 = none). Use higher values if you hit 429.",
    )
    p.add_argument(
        "--svg-width",
        type=int,
        default=1024,
        help="Max width (px) for SVG→PNG rasterization on Commons (iiurlwidth). Higher = slower; 1024 is usually enough for print.",
    )
    args = p.parse_args()

    download_flags(
        countries_json=Path(args.countries_json),
        out_dir=Path(args.out_dir),
        force=args.force,
        request_delay=args.delay,
        svg_raster_width=max(0, int(args.svg_width)),
    )


if __name__ == "__main__":
    main()
