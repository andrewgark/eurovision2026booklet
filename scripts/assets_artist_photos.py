from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse, unquote

import requests


# Many CDNs / WordPress installs return 403 unless the request looks like a browser
# navigation from the same site (custom bot UAs get blocked).
_BROWSER_HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _request_headers_for_photo_url(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    return {**_BROWSER_HEADERS_BASE, "Referer": referer}

_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/heic": ".heic",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _curl_get(url: str, headers: dict[str, str]) -> tuple[bytes, str]:
    """Some CDNs return 403 to Python's HTTP clients but allow curl (TLS / fingerprinting)."""
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        body_path = tdir / "body"
        hdr_path = tdir / "hdr"
        cmd = [
            "curl",
            "-fsSL",
            "-D",
            str(hdr_path),
            "-o",
            str(body_path),
        ]
        if ua := headers.get("User-Agent"):
            cmd.extend(["-A", ua])
        if ref := headers.get("Referer"):
            cmd.extend(["-e", ref])
        for hk, hv in headers.items():
            if hk in ("User-Agent", "Referer"):
                continue
            cmd.extend(["-H", f"{hk}: {hv}"])
        cmd.append(url)
        subprocess.run(cmd, check=True, capture_output=True)
        ctype_raw = ""
        for line in hdr_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("content-type:"):
                ctype_raw = line.split(":", 1)[1].strip()
                break
        ctype = ctype_raw.split(";")[0].strip().lower() if ctype_raw else ""
        return body_path.read_bytes(), ctype


def _fetch_photo(url: str, headers: dict[str, str]) -> tuple[bytes, Any]:
    try:
        r = _request_with_retry("GET", url, headers=headers, timeout=120)
        return r.content, r
    except RuntimeError as exc:
        if "403" not in str(exc) or shutil.which("curl") is None:
            raise
        print(f"  python HTTP stack blocked (403); fetching with curl: {url}")
        body, ctype = _curl_get(url, headers)
        return body, SimpleNamespace(headers={"Content-Type": ctype or "application/octet-stream"})


def _ext_from_response(url: str, resp: Any) -> str:
    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype in _CONTENT_TYPE_EXT:
        return _CONTENT_TYPE_EXT[ctype]
    path = unquote(urlparse(url).path)
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def download_artist_photos(
    *,
    artists_json: Path,
    out_dir: Path,
    force: bool = False,
    request_delay: float = 0.5,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    artists = _read_json(artists_json)
    total = len(artists)
    for idx, a in enumerate(artists, 1):
        code = str(a.get("country_code", "")).upper()
        url = a.get("photo_file")
        if not code:
            print(f"[{idx}/{total}] skipping entry without country_code")
            continue
        if not url:
            print(f"[{idx}/{total}] {code}: no photo_file, skipping")
            continue
        if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
            print(f"[{idx}/{total}] {code}: photo_file is not an http(s) URL, skipping ({url!r})")
            continue

        existing = sorted(out_dir.glob(f"artist_{code}.*"))
        if existing and not force:
            print(f"[{idx}/{total}] {code}: cached ({existing[0]})")
            continue

        photo_headers = _request_headers_for_photo_url(url)
        content, resp = _fetch_photo(url, photo_headers)

        ext = _ext_from_response(url, resp)
        for old in existing:
            old.unlink()
        out = out_dir / f"artist_{code}{ext}"
        out.write_bytes(content)
        print(f"[{idx}/{total}] {code}: {out} ({len(content)} bytes)")
        time.sleep(request_delay)


def main() -> None:
    p = argparse.ArgumentParser(description="Download artist photos listed in data/artists.json")
    p.add_argument("--artists-json", default="data/artists.json")
    p.add_argument("--out-dir", default="assets/artists")
    p.add_argument("--force", action="store_true", help="Re-download even if cached locally")
    p.add_argument("--delay", type=float, default=0.5, help="Seconds to sleep between requests")
    args = p.parse_args()

    download_artist_photos(
        artists_json=Path(args.artists_json),
        out_dir=Path(args.out_dir),
        force=args.force,
        request_delay=args.delay,
    )


if __name__ == "__main__":
    main()
