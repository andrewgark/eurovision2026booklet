from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass(frozen=True)
class EntryRow:
    iso2: str
    country_name_en: str
    artist_name: str
    song_title: str
    round_sf: str = ""
    running_order: int = 0


def _mw_api_wikitext(*, page: str) -> str:
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "parse",
        "page": page,
        "prop": "wikitext",
        "format": "json",
        "formatversion": 2,
    }
    # Wikipedia requires a descriptive User-Agent for automated requests.
    headers = {"User-Agent": "eurovision2026booklet/1.0 (template generator; https://example.invalid)"}
    r = requests.get(url, params=params, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    wikitext = ((data.get("parse") or {}).get("wikitext") or "")
    if not isinstance(wikitext, str) or not wikitext.strip():
        raise RuntimeError(f"Empty wikitext for Wikipedia page: {page}")
    return wikitext


_RE_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")
_RE_TAGS = re.compile(r"</?[^>]+>")
_RE_REF = re.compile(r"<ref[^>]*>.*?</ref>", re.DOTALL)
_RE_TEMPL = re.compile(r"\{\{[^{}]*\}\}")
_RE_WS = re.compile(r"\s+")

# Markdown links in the uploaded Wikipedia dump often include an optional title:
# [Text](/wiki/Foo "Foo (bar)")
_RE_MD_LINK = re.compile(r'\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def _clean_cell(s: str) -> str:
    s = s.strip()
    s = _RE_REF.sub("", s)
    s = _RE_TAGS.sub("", s)
    s = _RE_TEMPL.sub("", s)
    s = s.replace("''", "")
    s = _RE_LINK.sub(r"\1", s)
    s = s.replace("&nbsp;", " ").replace("–", "-")
    s = _RE_WS.sub(" ", s).strip()
    # remove leading table markup remnants
    s = s.lstrip("|!").strip()
    return s


def _clean_md_cell(s: str) -> str:
    s = s.strip()
    # remove images
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", s)
    # convert markdown links to link text
    s = _RE_MD_LINK.sub(r"\1", s)
    # remove citation footnote markers like [123]
    s = re.sub(r"\[\d+\]", "", s)
    # remove quotes around song titles
    s = s.strip().strip('"').strip()
    s = _RE_WS.sub(" ", s).strip()
    return s


def _parse_markdown_table(lines: list[str], *, start_idx: int) -> tuple[list[str], list[list[str]], int]:
    """
    Parses a GitHub-style markdown table starting at start_idx (header row).
    Returns (headers, rows, next_idx_after_table).
    """
    header = lines[start_idx].strip()
    if "|" not in header:
        raise RuntimeError("Not a markdown table header.")
    headers = [_clean_md_cell(c) for c in header.strip("|").split("|")]

    # separator line
    sep_idx = start_idx + 1
    if sep_idx >= len(lines) or set(lines[sep_idx].strip().replace("|", "").replace("-", "").replace(" ", "")) != {""}:
        # be permissive: allow missing/odd separators
        pass

    rows: list[list[str]] = []
    i = start_idx + 2
    while i < len(lines):
        ln = lines[i].rstrip("\n")
        if not ln.strip():
            break
        if not ln.lstrip().startswith("|"):
            break
        cells = [_clean_md_cell(c) for c in ln.strip().strip("|").split("|")]
        # normalize length
        if len(cells) < len(headers):
            cells += [""] * (len(headers) - len(cells))
        rows.append(cells[: len(headers)])
        i += 1
    return headers, rows, i


def _load_entries_from_wikipedia_markdown(*, md_path: Path, year: int) -> list[EntryRow]:
    """
    Uses a locally saved markdown dump of the Wikipedia page (as provided by the user).
    Extracts:
    - the participants table (country/artist/song)
    - semi-final running order tables for SF assignment + order
    """
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 1) Participants table
    participants_headers: list[str] | None = None
    participants_rows: list[list[str]] = []
    for i, ln in enumerate(lines):
        if ln.strip().startswith("| Country") and "Artist" in ln and "Song" in ln:
            participants_headers, participants_rows, _ = _parse_markdown_table(lines, start_idx=i)
            break
    if not participants_headers or not participants_rows:
        raise RuntimeError("Could not find participants table in the provided Wikipedia markdown dump.")

    def _col_idx(name: str) -> int:
        for j, h in enumerate(participants_headers or []):
            if h.strip().lower() == name:
                return j
        return -1

    i_country = _col_idx("country")
    i_artist = _col_idx("artist")
    i_song = _col_idx("song")
    if i_country < 0:
        raise RuntimeError(f"Participants table missing Country column: {participants_headers}")

    base_entries: list[EntryRow] = []
    for r in participants_rows:
        country = r[i_country].strip()
        if not country:
            continue
        artist = r[i_artist].strip() if i_artist >= 0 else "TBA"
        song = r[i_song].strip() if i_song >= 0 else "TBA"
        iso2 = _EUROVISION_NAME_TO_ISO2.get(country, "")
        base_entries.append(EntryRow(iso2=iso2, country_name_en=country, artist_name=artist or "TBA", song_title=song or "TBA"))

    # 2) Semi-final tables: map country -> (round_sf, order)
    ro_map: dict[str, tuple[str, int]] = {}
    for idx, ln in enumerate(lines):
        if ln.strip().startswith("| R/O | Country") and "Artist" in ln and "Song" in ln:
            headers, rows, _ = _parse_markdown_table(lines, start_idx=idx)
            # detect which semi based on nearest preceding heading
            # scan backwards for "### Semi-final 1/2"
            round_sf = ""
            for k in range(idx, max(-1, idx - 200), -1):
                h = lines[k].strip().lower()
                if h.startswith("### semi-final 1"):
                    round_sf = "SF1"
                    break
                if h.startswith("### semi-final 2"):
                    round_sf = "SF2"
                    break
            if not round_sf:
                continue

            # locate indices
            hdr_low = [h.strip().lower() for h in headers]
            try:
                j_ro = hdr_low.index("r/o")
            except ValueError:
                j_ro = -1
            try:
                j_country = hdr_low.index("country")
            except ValueError:
                j_country = -1
            if j_ro < 0 or j_country < 0:
                continue
            for r in rows:
                country = r[j_country].strip()
                if not country:
                    continue
                try:
                    order = int(re.sub(r"[^\d]", "", r[j_ro]) or "0")
                except Exception:
                    order = 0
                if order:
                    ro_map[country] = (round_sf, order)

    # merge base entries with RO data
    out: list[EntryRow] = []
    for e in base_entries:
        round_sf, order = ro_map.get(e.country_name_en, ("", 0))
        out.append(
            EntryRow(
                iso2=e.iso2,
                country_name_en=e.country_name_en,
                artist_name=e.artist_name,
                song_title=e.song_title,
                round_sf=round_sf,
                running_order=order,
            )
        )

    # stable ordering: by SF then order then country
    def _sf_key(sf: str) -> int:
        return {"SF1": 1, "SF2": 2, "": 9}.get(sf, 9)

    out.sort(key=lambda x: (_sf_key(x.round_sf), x.running_order or 9999, x.country_name_en))
    return out


def _extract_entries_table(wikitext: str) -> str:
    """
    Heuristic: find first wikitable that contains headers including Country + Artist + Song.
    """
    # Split into wikitables
    tables = re.findall(r"\{\|[\s\S]*?\|\}", wikitext)
    for t in tables:
        low = t.lower()
        if "wikitable" not in low:
            continue
        if "country" in low and "artist" in low and "song" in low:
            return t
    raise RuntimeError("Could not find an entries wikitable with Country/Artist/Song headers.")


def _parse_wikitable_entries(table_wikitext: str) -> list[EntryRow]:
    # Find header row (first line starting with !)
    lines = [ln.rstrip("\n") for ln in table_wikitext.splitlines()]
    header_cols: list[str] = []
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("!"):
            # header cells are separated by !!
            raw = ln.lstrip()[1:]
            header_cols = [_clean_cell(c) for c in raw.split("!!")]
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("Entries table has no header row.")

    # Identify indices (case-insensitive)
    def _idx(name: str) -> int | None:
        for j, col in enumerate(header_cols):
            if col.strip().lower() == name:
                return j
        return None

    i_country = _idx("country")
    i_artist = _idx("artist")
    i_song = _idx("song")
    i_iso2 = _idx("iso") or _idx("code") or _idx("country code")
    if i_country is None:
        raise RuntimeError(f"Header columns missing required fields: {header_cols}")
    # Artist/song are sometimes not yet available; we still want a template.
    if i_artist is None:
        i_artist = -1
    if i_song is None:
        i_song = -1

    # Parse rows: each starts with |-
    rows: list[EntryRow] = []
    cur_cells: list[str] = []
    in_row = False
    for ln in lines[header_idx + 1 :]:
        s = ln.strip()
        if s.startswith("|-"):
            if in_row and cur_cells:
                # flush previous
                pass
            cur_cells = []
            in_row = True
            continue
        if not in_row:
            continue
        if s.startswith("|}"):
            break
        if s.startswith("!"):
            # ignore subheaders
            continue
        if s.startswith("|"):
            # cell line; can contain || separators
            raw = s[1:]
            parts = raw.split("||")
            cur_cells.extend([_clean_cell(p) for p in parts])
            # Attempt to flush if we have enough cells
            if len(cur_cells) >= max(i_country, i_artist, i_song) + 1:
                country = cur_cells[i_country] if i_country < len(cur_cells) else ""
                artist = cur_cells[i_artist] if (i_artist >= 0 and i_artist < len(cur_cells)) else ""
                song = cur_cells[i_song] if (i_song >= 0 and i_song < len(cur_cells)) else ""
                iso2 = ""
                if i_iso2 is not None and i_iso2 < len(cur_cells):
                    iso2 = cur_cells[i_iso2].upper()
                if not iso2:
                    # best-effort: derive from country flag templates often used like "Sweden" (not reliable)
                    iso2 = ""

                # Some tables use empty continuation rows; skip if no country
                if country:
                    rows.append(
                        EntryRow(
                            iso2=iso2,
                            country_name_en=country,
                            artist_name=artist or "TBA",
                            song_title=song or "TBA",
                        )
                    )
                cur_cells = []
                in_row = False

    # De-dup by (country, artist, song)
    seen: set[tuple[str, str, str]] = set()
    out: list[EntryRow] = []
    for r in rows:
        key = (r.country_name_en, r.artist_name, r.song_title)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def load_entries_from_wikipedia(*, year: int) -> list[EntryRow]:
    # Wikipedia page naming is not always consistent; try a few common patterns.
    pages = [
        f"Eurovision_Song_Contest_{year}",
        f"Eurovision_Song_Contest_{year}_(entries)",
        f"Template:ESC_{year}_participants",
    ]
    last_err: Exception | None = None
    for page in pages:
        try:
            wikitext = _mw_api_wikitext(page=page)
            try:
                table = _extract_entries_table(wikitext)
                entries = _parse_wikitable_entries(table)
                if entries:
                    # deterministic ordering: as in table order
                    return entries
            except Exception:
                # Fallback: some pages only list participating countries (no entries table yet).
                entries = _parse_participating_countries_fallback(wikitext, year=year)
                if entries:
                    return entries
        except Exception as e:  # noqa: BLE001 - deliberate multi-strategy fetch
            last_err = e
            continue
    raise RuntimeError(f"Failed to load entries from Wikipedia for {year}: {last_err}")


_EUROVISION_NAME_TO_ISO2: dict[str, str] = {
    "Albania": "AL",
    "Armenia": "AM",
    "Australia": "AU",
    "Austria": "AT",
    "Azerbaijan": "AZ",
    "Belgium": "BE",
    "Bulgaria": "BG",
    "Croatia": "HR",
    "Cyprus": "CY",
    "Czech Republic": "CZ",
    "Czechia": "CZ",
    "Denmark": "DK",
    "Estonia": "EE",
    "Finland": "FI",
    "France": "FR",
    "Georgia": "GE",
    "Germany": "DE",
    "Greece": "GR",
    "Israel": "IL",
    "Italy": "IT",
    "Latvia": "LV",
    "Lithuania": "LT",
    "Luxembourg": "LU",
    "Malta": "MT",
    "Moldova": "MD",
    "Montenegro": "ME",
    "Norway": "NO",
    "Poland": "PL",
    "Portugal": "PT",
    "Romania": "RO",
    "San Marino": "SM",
    "Serbia": "RS",
    "Slovenia": "SI",
    "Spain": "ES",
    "Sweden": "SE",
    "Switzerland": "CH",
    "Ukraine": "UA",
    "United Kingdom": "GB",
    "Netherlands": "NL",
    "Ireland": "IE",
    "Iceland": "IS",
}


def _parse_participating_countries_fallback(wikitext: str, *, year: int) -> list[EntryRow]:
    """
    Fallback when Wikipedia doesn't yet have an entries table.
    We try to find the 'Participating countries' section and extract wikilinks.
    Artist/song stay 'TBA' (Wikipedia often doesn't have them yet early).
    """
    # Allow any heading level (== ... ==, === ... ===, etc.)
    m = re.search(r"={2,}\s*Participating countries\s*={2,}([\s\S]*?)(?:\n={2,}|\Z)", wikitext, flags=re.IGNORECASE)
    # Many Wikipedia pages (and templates) do not have a dedicated section header;
    # in that case, scan the full wikitext.
    section = m.group(1) if m else wikitext

    # Wikipedia often uses {{esc|Country}} templates instead of raw links.
    esc_names = re.findall(r"\{\{\s*esc\s*\|\s*([^}|]+)", section, flags=re.IGNORECASE)
    link_names = _RE_LINK.findall(section)
    names = [_clean_cell(x) for x in (esc_names + list(link_names))]
    out: list[EntryRow] = []
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        iso2 = _EUROVISION_NAME_TO_ISO2.get(name, "")
        # If the section includes obvious non-countries, skip those.
        if not iso2 and name not in _EUROVISION_NAME_TO_ISO2:
            continue
        seen.add(name)
        out.append(EntryRow(iso2=iso2, country_name_en=name, artist_name="TBA", song_title="TBA"))
    return out


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    _ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def generate(*, out_dir: Path, year: int = 2026) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate_md_dumps = [
        # If user copies the dump into the repo
        repo_root / "uploads" / f"Eurovision_Song_Contest_{year}-0.md",
        # Cursor upload location (common in this workspace)
        Path("/home/andre/.cursor/projects/home-andre-eurovision2026booklet/uploads") / f"Eurovision_Song_Contest_{year}-0.md",
    ]
    md_dump = next((p for p in candidate_md_dumps if p.exists()), None)
    entries = _load_entries_from_wikipedia_markdown(md_path=md_dump, year=year) if md_dump else load_entries_from_wikipedia(year=year)

    # ---- Config ----
    _write_csv(
        out_dir / "Config.csv",
        ["key", "value_en", "value_ru"],
        [
            {"key": "year", "value_en": str(year), "value_ru": str(year)},
            {"key": "event_name", "value_en": f"Eurovision Song Contest {year}", "value_ru": f"Евровидение {year}"},
            {"key": "booklet_title", "value_en": "Booklet", "value_ru": "Буклет"},
            {
                "key": "about_text",
                "value_en": "Template text. Replace with your curated booklet intro.",
                "value_ru": "Шаблонный текст. Замените на ваш вступительный текст.",
            },
        ],
    )

    # ---- Countries ----
    country_fieldnames = [
        "country_code",
        "country_name_en",
        "country_name_ru",
        "basic_stats_en",
        "basic_stats_ru",
        "eurovision_stats_en",
        "eurovision_stats_ru",
        "wikidata_qid",
    ]
    country_rows: list[dict[str, str]] = []
    # countries are derived from entries; allow duplicates and then dedup by ISO2/country name
    seen_c: set[tuple[str, str]] = set()
    for e in entries:
        key = (e.iso2, e.country_name_en)
        if key in seen_c:
            continue
        seen_c.add(key)
        country_rows.append(
            {
                "country_code": e.iso2,
                "country_name_en": e.country_name_en,
                "country_name_ru": f"TODO: {e.country_name_en}",
                "basic_stats_en": f"Template: basic country stats for {e.country_name_en}.",
                "basic_stats_ru": f"Шаблон: базовая статистика для {e.country_name_en}.",
                "eurovision_stats_en": f"Template: Eurovision stats for {e.country_name_en}.",
                "eurovision_stats_ru": f"Шаблон: статистика Евровидения для {e.country_name_en}.",
                "wikidata_qid": "",
            }
        )
    _write_csv(out_dir / "Countries.csv", country_fieldnames, country_rows)

    # ---- Artists + Songs + RunningOrder + Odds ----
    artists_fieldnames = ["country_code", "artist_name", "bio_en", "bio_ru", "facts_en", "facts_ru", "photo_file"]
    songs_fieldnames = [
        "country_code",
        "song_title",
        "song_title_en",
        "song_title_ru",
        "lyrics_original",
        "translation_en",
        "translation_ru",
        "facts_en",
        "facts_ru",
        "round_sf",
        "qualified_to_final",
        "lyrics_size_modifier",
        "artist_name",
        "country_name_en",
    ]
    running_order_fieldnames = ["round", "country_code", "order"]
    odds_fieldnames = ["round", "country_code", "bookmaker", "odds", "as_of_date"]

    artist_rows: list[dict[str, str]] = []
    song_rows: list[dict[str, str]] = []
    running_order_rows: list[dict[str, str]] = []
    odds_rows: list[dict[str, str]] = []

    for i, e in enumerate(entries, start=1):
        iso2 = e.iso2 or "XX"
        artist_name = e.artist_name
        song_title = e.song_title

        round_sf = e.round_sf or ("SF1" if (i % 2 == 1) else "SF2")

        artist_rows.append(
            {
                "country_code": iso2,
                "artist_name": artist_name,
                "bio_en": f"Template bio for {artist_name}. Replace with curated text.",
                "bio_ru": f"Шаблон биографии для {artist_name}. Замените на подготовленный текст.",
                "facts_en": f"Template facts for {artist_name}.",
                "facts_ru": f"Шаблон фактов для {artist_name}.",
                "photo_file": "",
            }
        )

        song_rows.append(
            {
                "country_code": iso2,
                "song_title": song_title,
                "song_title_en": song_title,
                "song_title_ru": f"TODO: {song_title}",
                "lyrics_original": "Template lyrics (paste original lyrics here).",
                "translation_en": "Template translation to English.",
                "translation_ru": "Шаблон перевода на русский.",
                "facts_en": f"Template song facts for {song_title}.",
                "facts_ru": f"Шаблон фактов о песне {song_title}.",
                "round_sf": round_sf,
                "qualified_to_final": "",
                "lyrics_size_modifier": "",
                "artist_name": artist_name,
                "country_name_en": e.country_name_en,
            }
        )

        running_order_rows.append(
            {
                "round": round_sf,
                "country_code": iso2,
                "order": str(e.running_order or i),
            }
        )

        odds_rows.append(
            {
                "round": "OVERALL",
                "country_code": iso2,
                "bookmaker": "TemplateBookmaker",
                "odds": "100/1",
                "as_of_date": f"{year}-04-20",
            }
        )

    _write_csv(out_dir / "Artists.csv", artists_fieldnames, artist_rows)
    _write_csv(out_dir / "Songs.csv", songs_fieldnames, song_rows)
    _write_csv(out_dir / "RunningOrder.csv", running_order_fieldnames, running_order_rows)
    _write_csv(out_dir / "Odds.csv", odds_fieldnames, odds_rows)

    # ---- Results ----
    # `pull_sheets.py` keeps results rows flexible for now; we still provide a sensible header template.
    _write_csv(
        out_dir / "Results.csv",
        ["round", "country_code", "place", "points_total", "notes"],
        [
            {
                "round": "FINAL",
                "country_code": song_rows[0]["country_code"] if song_rows else "",
                "place": "1",
                "points_total": "0",
                "notes": "Template row. Adjust schema/columns as you finalize results format.",
            }
        ],
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "templates" / "sheets"
    generate(out_dir=out_dir, year=2026)
    print(f"Wrote CSV templates to: {out_dir}")


if __name__ == "__main__":
    main()

