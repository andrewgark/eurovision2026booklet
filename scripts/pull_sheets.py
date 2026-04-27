from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import requests

# Allow running via: `python scripts/pull_sheets.py`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.schema import validate_local_snapshots

# Config tab keys that map to `{"en": ..., "ru": ...}` in config.json
_CONFIG_LOCALIZED_KEYS: frozenset[str] = frozenset(
    {
        "event_name",
        "booklet_title",
        "about_text",
        "subtitle_pre",
        "subtitle_sf1",
        "subtitle_sf2",
        "subtitle_final",
        "subtitle_post",
        "intro_text_pre",
        "intro_text_sf1",
        "intro_text_sf2",
        "intro_text_final",
        "intro_text_post",
    }
)


def _config_shell(*, year: int) -> dict[str, Any]:
    """Default config object: all localized keys start as empty en/ru strings."""
    d: dict[str, Any] = {"year": year}
    for k in _CONFIG_LOCALIZED_KEYS:
        d[k] = {"en": "", "ru": ""}
    return d


# Public "Eurovision Booklet Content" sheet (CSV export; sheet must be viewable without login).
BOOKLET_SPREADSHEET_ID = "1INXyh8glLCOrtI_M-cV_gZ7LXcr5mBm0ffeVhYXQIVc"
BOOKLET_GIDS: dict[str, str] = {
    "Config": "0",
    "Countries": "342702758",
    "Artists": "725670095",
    "Songs": "1442682824",
    "Odds": "1797563105",
    "Results": "1574072165",
}

# ISO 3166-1 alpha-2 → Wikidata country QID (flags). Fallback when the sheet has no QID column.
WIKIDATA_QID_BY_ISO2: dict[str, str] = {
    "AL": "Q222",
    "AM": "Q399",
    "AT": "Q40",
    "AU": "Q408",
    "AZ": "Q227",
    "BE": "Q31",
    "BG": "Q219",
    "CH": "Q39",
    "CY": "Q229",
    "CZ": "Q213",
    "DE": "Q183",
    "DK": "Q35",
    "EE": "Q191",
    "FI": "Q33",
    "FR": "Q142",
    "GB": "Q145",
    "GE": "Q230",
    "GR": "Q41",
    "HR": "Q224",
    "IL": "Q801",
    "IT": "Q38",
    "LT": "Q37",
    "LU": "Q32",
    "LV": "Q211",
    "MD": "Q217",
    "ME": "Q236",
    "MT": "Q233",
    "NO": "Q20",
    "PL": "Q36",
    "PT": "Q45",
    "RO": "Q218",
    "RS": "Q403",
    "SE": "Q34",
    "SM": "Q238",
    "UA": "Q212",
    "IE": "Q27",
    "IS": "Q189",
    "NL": "Q55",
    "ES": "Q29",
}

_RE_ODDS_COL = re.compile(
    r"^odds_(?P<dd>\d{2})_(?P<mm>\d{2})_(?P<yyyy>\d{4})_(?P<bookmaker>[^_]+)_(?P<kind>winner|qualify)$",
    re.IGNORECASE,
)


def _download_csv_raw(spreadsheet_id: str, gid: str) -> str:
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export"
    params = {"format": "csv", "gid": gid}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


def _download_csv(spreadsheet_id: str, gid: str) -> list[dict[str, str]]:
    text = _download_csv_raw(spreadsheet_id, gid)
    if not text.strip():
        return []
    # StringIO: newlines inside quoted CSV cells must not split rows (splitlines() corrupts those fields).
    return list(csv.DictReader(io.StringIO(text)))


def _save_raw_csv(*, out_dir: Path, name: str, raw: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.csv").write_text(raw, encoding="utf-8")


def _require_cols(row: dict[str, str], cols: list[str], *, tab: str) -> None:
    missing = [c for c in cols if c not in row]
    if missing:
        raise ValueError(f"Tab {tab}: missing columns: {missing}")


def _nonempty(s: str) -> str:
    return (s or "").strip()


def _to_iso2(s: str) -> str:
    return _nonempty(s).upper()


def _parse_date(s: str) -> str:
    s = _nonempty(s)
    if not s:
        return str(date.today())
    return s


def _normalize_sf_round(raw: str) -> str:
    """Map sheet values (e.g. SF1_AUTO) to schema Round: SF1 | SF2 | F."""
    u = _nonempty(raw).upper()
    if u == "OVERALL":
        return "F"
    if u.startswith("SF1"):
        return "SF1"
    if u.startswith("SF2"):
        return "SF2"
    if u == "F" or u.startswith("FINAL"):
        return "F"
    raise ValueError(f"Unknown semi/final round label: {raw!r}")


def _to_int(s: str) -> int:
    s = _nonempty(s)
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _to_float(s: str) -> float:
    s = _nonempty(s).replace(",", ".")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _qualified_flag(raw: str) -> str:
    v = _nonempty(raw).lower()
    if v in {"yes", "true", "1", "y", "auto"}:
        return "yes"
    return _nonempty(raw)


def pull_booklet(
    *,
    spreadsheet_id: str,
    gids: dict[str, str],
    year: int,
    out_data_dir: Path,
    save_raw_csv: bool,
) -> None:
    """
    Pull the live booklet spreadsheet layout: one row per country_code (artist + song tabs align on ISO2).
    Running order is taken from the Songs tab (order_sf + round_sf).
    """
    out_data_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_data_dir / "source_csv"

    def tab_raw(name: str) -> str:
        raw = _download_csv_raw(spreadsheet_id, gids[name])
        if save_raw_csv:
            _save_raw_csv(out_dir=raw_dir, name=name, raw=raw)
        return raw

    # --- Config ---
    config_rows = list(csv.DictReader(io.StringIO(tab_raw("Config"))))
    config: dict[str, Any] = _config_shell(year=year)
    for r in config_rows:
        _require_cols(r, ["key", "value_en", "value_ru"], tab="Config")
        key = _nonempty(r["key"])
        if not key:
            continue
        if key == "year":
            config["year"] = int(_nonempty(r["value_en"]) or _nonempty(r["value_ru"]) or str(year))
        elif key in _CONFIG_LOCALIZED_KEYS:
            config[key] = {"en": _nonempty(r["value_en"]), "ru": _nonempty(r["value_ru"])}
        elif key == "intro_text":
            config["about_text"] = {"en": _nonempty(r["value_en"]), "ru": _nonempty(r["value_ru"])}
    (out_data_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- Countries ---
    countries_rows = list(csv.DictReader(io.StringIO(tab_raw("Countries"))))
    countries: list[dict[str, Any]] = []
    for r in countries_rows:
        _require_cols(
            r,
            [
                "country_code",
                "country_name_en",
                "country_name_ru",
                "auto_qualify",
                "qualify_streak",
                "non_qualify_streak",
                "last_participation",
                "won_times",
                "national_qualify_type",
                "country_facts_en",
                "country_facts_ru",
            ],
            tab="Countries",
        )
        code = _to_iso2(r["country_code"])
        if not code:
            continue
        if code not in WIKIDATA_QID_BY_ISO2:
            raise ValueError(f"Missing Wikidata QID mapping for country_code={code!r} (add it to WIKIDATA_QID_BY_ISO2).")
        qid = WIKIDATA_QID_BY_ISO2[code]

        # Normalize structured stats. Keep eurovision_stats around as a one-liner
        # for legacy consumers but stop relying on it for rendering.
        auto_q = _nonempty(r["auto_qualify"]).upper()
        if auto_q not in {"", "HOST", "BIG_FIVE"}:
            auto_q = ""
        nat_q = _nonempty(r["national_qualify_type"]).upper()
        if nat_q not in {"", "PUBLIC_CONTEST", "INTERNAL_SELECTION"}:
            nat_q = ""
        ev_en = (
            f"Auto-qualify: {auto_q}. "
            f"Qualify streak: {_nonempty(r['qualify_streak'])}. "
            f"Non-qualify streak: {_nonempty(r['non_qualify_streak'])}. "
            f"Last participation: {_nonempty(r['last_participation'])}. "
            f"Wins: {_nonempty(r['won_times'])}. "
            f"National selection: {nat_q}."
        ).strip()
        countries.append(
            {
                "country_code": code,
                "country_name": {"en": _nonempty(r["country_name_en"]), "ru": _nonempty(r["country_name_ru"])},
                "basic_stats": {"en": _nonempty(r["country_facts_en"]), "ru": _nonempty(r["country_facts_ru"])},
                "eurovision_stats": {"en": ev_en, "ru": ev_en},
                "flag": {"wikidata_qid": qid},
                "map": {"iso_a2": code},
                "sources_urls": [],
                "auto_qualify": auto_q,
                "qualify_streak": _to_int(r["qualify_streak"]),
                "non_qualify_streak": _to_int(r["non_qualify_streak"]),
                "last_participation": _to_int(r["last_participation"]),
                "won_times": _to_int(r["won_times"]),
                "national_qualify_type": nat_q,
            }
        )
    (out_data_dir / "countries.json").write_text(json.dumps(countries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- Artists (keyed by country_code) ---
    artists_rows = list(csv.DictReader(io.StringIO(tab_raw("Artists"))))
    artists: list[dict[str, Any]] = []
    for r in artists_rows:
        _require_cols(
            r,
            [
                "country_code",
                "artist_name_en",
                "artist_name_ru",
                "type",
                "artist_real_name_en",
                "artist_real_name_ru",
                "year born",
                "lgbt",
                "place_born_en",
                "place_born_ru",
                "place_growup_en",
                "place_growup_ru",
                "bio_en",
                "bio_ru",
                "photo_file",
            ],
            tab="Artists",
        )
        code = _to_iso2(r["country_code"])
        if not code:
            continue
        facts_en = (
            f"Type: {_nonempty(r['type'])}. "
            f"Birth name: {_nonempty(r['artist_real_name_en'])}. "
            f"Born: {_nonempty(r['year born'])}. "
            f"LGBTQ+: {_nonempty(r['lgbt'])}. "
            f"Born in: {_nonempty(r['place_born_en'])}. "
            f"Grew up in: {_nonempty(r['place_growup_en'])}."
        ).strip()
        facts_ru = (
            f"Тип: {_nonempty(r['type'])}. "
            f"Имя при рождении: {_nonempty(r['artist_real_name_ru'])}. "
            f"Год рождения: {_nonempty(r['year born'])}. "
            f"LGBTQ+: {_nonempty(r['lgbt'])}. "
            f"Место рождения: {_nonempty(r['place_born_ru'])}. "
            f"Вырос(ла): {_nonempty(r['place_growup_ru'])}."
        ).strip()
        artists.append(
            {
                "country_code": code,
                "artist_name": _nonempty(r["artist_name_en"]) or _nonempty(r["artist_name_ru"]),
                "artist_name_ru": _nonempty(r["artist_name_ru"]),
                "bio": {"en": _nonempty(r["bio_en"]), "ru": _nonempty(r["bio_ru"])},
                "facts": {"en": facts_en, "ru": facts_ru},
                "photo_file": _nonempty(r["photo_file"]),
                "artist_real_name": {
                    "en": _nonempty(r["artist_real_name_en"]),
                    "ru": _nonempty(r["artist_real_name_ru"]),
                },
                "year_born": _nonempty(r["year born"]),
                "place_born": {
                    "en": _nonempty(r["place_born_en"]),
                    "ru": _nonempty(r["place_born_ru"]),
                },
                "place_growup": {
                    "en": _nonempty(r["place_growup_en"]),
                    "ru": _nonempty(r["place_growup_ru"]),
                },
                "lgbt": _nonempty(r["lgbt"]),
            }
        )
    (out_data_dir / "artists.json").write_text(json.dumps(artists, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- Songs ---
    songs_rows = list(csv.DictReader(io.StringIO(tab_raw("Songs"))))
    songs: list[dict[str, Any]] = []
    running_order: list[dict[str, Any]] = []
    for r in songs_rows:
        _require_cols(
            r,
            [
                "country_code",
                "song_title",
                "song_title_en",
                "song_title_translation_en",
                "song_title_translation_ru",
                "langs_en",
                "langs_en_minor",
                "langs_ru",
                "langs_ru_minor",
                "lyrics_original",
                "lyrics_en",
                "lyrics_ru",
                "genre_en",
                "genre_ru",
                "facts_en",
                "facts_ru",
                "national_final_url",
                "music_video_url",
                "round_sf",
                "order_sf",
                "number_sf",
                "qualified_to_final",
                "lyrics_size_modifier",
            ],
            tab="Songs",
        )
        code = _to_iso2(r["country_code"])
        if not code:
            continue
        title = _nonempty(r["song_title"])
        title_en = _nonempty(r["song_title_en"]) or title
        title_ru = _nonempty(r["song_title_translation_ru"]) or _nonempty(r["song_title_translation_en"]) or title
        rnd = _normalize_sf_round(r["round_sf"])
        songs.append(
            {
                "country_code": code,
                "song_title": title,
                "song_title_en": title_en,
                "song_title_ru": title_ru,
                "lyrics_original": r.get("lyrics_original", "") or "",
                "translation_en": r.get("lyrics_en", "") or "",
                "translation_ru": r.get("lyrics_ru", "") or "",
                "facts": {"en": r.get("facts_en", "") or "", "ru": r.get("facts_ru", "") or ""},
                "round_sf": rnd,
                "qualified_to_final": _qualified_flag(r.get("qualified_to_final", "") or ""),
                "langs": {"en": _nonempty(r["langs_en"]), "ru": _nonempty(r["langs_ru"])},
                "langs_minor": {
                    "en": _nonempty(r["langs_en_minor"]),
                    "ru": _nonempty(r["langs_ru_minor"]),
                },
                "genre": {"en": _nonempty(r["genre_en"]), "ru": _nonempty(r["genre_ru"])},
                "number_sf": _to_int(r["number_sf"]),
                "number_f": _to_int(r.get("number_f", "") or ""),
                "national_final_url": _nonempty(r["national_final_url"]),
                "music_video_url": _nonempty(r["music_video_url"]),
                "lyrics_size_modifier": _to_float(r.get("lyrics_size_modifier", "") or ""),
            }
        )
        order_raw = _nonempty(r.get("order_sf", ""))
        if order_raw.isdigit():
            running_order.append({"round": rnd, "country_code": code, "order": int(order_raw)})
    running_order.sort(key=lambda x: (x["round"], x["order"], x["country_code"]))
    (out_data_dir / "songs.json").write_text(json.dumps(songs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rounds_payload = {"rounds": [], "running_order": running_order}
    (out_data_dir / "rounds.json").write_text(json.dumps(rounds_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- Odds (wide columns → one row per bookmaker × kind) ---
    odds_rows = list(csv.DictReader(io.StringIO(tab_raw("Odds"))))
    odds: list[dict[str, Any]] = []
    if odds_rows:
        odds_cols = [k for k in (odds_rows[0].keys() or []) if k and _RE_ODDS_COL.match(k)]
        for r in odds_rows:
            cid = _to_iso2(r.get("country_id", "") or r.get("country_code", ""))
            if not cid:
                continue
            sf_raw = _nonempty(r.get("SF", ""))
            try:
                q_round = _normalize_sf_round(sf_raw)
            except ValueError:
                q_round = "SF1"
            for col in odds_cols:
                m = _RE_ODDS_COL.match(col)
                if not m:
                    continue
                val = _nonempty(r.get(col, ""))
                if not val:
                    continue
                dd, mm, yyyy, bookmaker, kind = (
                    m.group("dd"),
                    m.group("mm"),
                    m.group("yyyy"),
                    m.group("bookmaker"),
                    m.group("kind").lower(),
                )
                as_of = f"{yyyy}-{mm}-{dd}"
                if kind == "winner":
                    odds.append(
                        {
                            "round": "F",
                            "country_code": cid,
                            "bookmaker": bookmaker,
                            "odds": val,
                            "as_of_date": as_of,
                        }
                    )
                else:
                    odds.append(
                        {
                            "round": q_round,
                            "country_code": cid,
                            "bookmaker": bookmaker,
                            "odds": val,
                            "as_of_date": as_of,
                        }
                    )
    (out_data_dir / "odds.json").write_text(json.dumps(odds, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- Results (optional / empty tab) ---
    raw_results = tab_raw("Results")
    results_rows: list[dict[str, str]] = (
        list(csv.DictReader(io.StringIO(raw_results))) if raw_results.strip() else []
    )
    results = {"summary": {"winner_country_code": ""}, "rounds": results_rows}
    (out_data_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validate_local_snapshots(data_dir=str(out_data_dir))


def pull_template(
    *,
    spreadsheet_id: str,
    gid_config: str,
    gid_countries: str,
    gid_artists: str,
    gid_songs: str,
    gid_running_order: str,
    gid_odds: str,
    gid_results: str,
    out_data_dir: Path,
) -> None:
    """CSV column layout matching templates/sheets/ (separate RunningOrder tab; ids are country_code only)."""
    out_data_dir.mkdir(parents=True, exist_ok=True)

    config_rows = _download_csv(spreadsheet_id, gid_config)
    config: dict[str, Any] = _config_shell(year=2026)
    for r in config_rows:
        _require_cols(r, ["key", "value_en", "value_ru"], tab="Config")
        key = _nonempty(r["key"])
        if not key:
            continue
        if key == "year":
            config["year"] = int(_nonempty(r["value_en"]) or _nonempty(r["value_ru"]) or "2026")
        elif key in _CONFIG_LOCALIZED_KEYS:
            config[key] = {"en": _nonempty(r["value_en"]), "ru": _nonempty(r["value_ru"])}
        elif key == "intro_text":
            config["about_text"] = {"en": _nonempty(r["value_en"]), "ru": _nonempty(r["value_ru"])}
    (out_data_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    countries_rows = _download_csv(spreadsheet_id, gid_countries)
    countries: list[dict[str, Any]] = []
    for r in countries_rows:
        _require_cols(
            r,
            [
                "country_code",
                "country_name_en",
                "country_name_ru",
                "basic_stats_en",
                "basic_stats_ru",
                "eurovision_stats_en",
                "eurovision_stats_ru",
                "wikidata_qid",
            ],
            tab="Countries",
        )
        code = _to_iso2(r["country_code"])
        if not code:
            continue
        qid = _nonempty(r["wikidata_qid"])
        if len(qid) < 2:
            if code not in WIKIDATA_QID_BY_ISO2:
                raise ValueError(f"Missing wikidata_qid for {code} and no ISO2 fallback in WIKIDATA_QID_BY_ISO2.")
            qid = WIKIDATA_QID_BY_ISO2[code]
        countries.append(
            {
                "country_code": code,
                "country_name": {"en": _nonempty(r["country_name_en"]), "ru": _nonempty(r["country_name_ru"])},
                "basic_stats": {"en": _nonempty(r["basic_stats_en"]), "ru": _nonempty(r["basic_stats_ru"])},
                "eurovision_stats": {"en": _nonempty(r["eurovision_stats_en"]), "ru": _nonempty(r["eurovision_stats_ru"])},
                "flag": {"wikidata_qid": qid},
                "map": {"iso_a2": code},
                "sources_urls": [],
            }
        )
    (out_data_dir / "countries.json").write_text(json.dumps(countries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    artists_rows = _download_csv(spreadsheet_id, gid_artists)
    artists: list[dict[str, Any]] = []
    for r in artists_rows:
        _require_cols(r, ["country_code", "artist_name", "bio_en", "bio_ru", "facts_en", "facts_ru", "photo_file"], tab="Artists")
        code = _to_iso2(r["country_code"])
        if not code:
            continue
        artists.append(
            {
                "country_code": code,
                "artist_name": _nonempty(r["artist_name"]),
                "bio": {"en": _nonempty(r["bio_en"]), "ru": _nonempty(r["bio_ru"])},
                "facts": {"en": _nonempty(r["facts_en"]), "ru": _nonempty(r["facts_ru"])},
                "photo_file": _nonempty(r["photo_file"]),
            }
        )
    (out_data_dir / "artists.json").write_text(json.dumps(artists, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    songs_rows = _download_csv(spreadsheet_id, gid_songs)
    songs: list[dict[str, Any]] = []
    for r in songs_rows:
        _require_cols(
            r,
            [
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
            ],
            tab="Songs",
        )
        code = _to_iso2(r["country_code"])
        if not code:
            continue
        songs.append(
            {
                "country_code": code,
                "song_title": _nonempty(r["song_title"]),
                "song_title_en": _nonempty(r["song_title_en"]),
                "song_title_ru": _nonempty(r["song_title_ru"]),
                "lyrics_original": r.get("lyrics_original", ""),
                "translation_en": r.get("translation_en", ""),
                "translation_ru": r.get("translation_ru", ""),
                "facts": {"en": r.get("facts_en", ""), "ru": r.get("facts_ru", "")},
                "round_sf": _normalize_sf_round(r["round_sf"]),
                "qualified_to_final": _qualified_flag(r.get("qualified_to_final", "") or ""),
                "lyrics_size_modifier": _to_float(r.get("lyrics_size_modifier", "") or ""),
            }
        )
    (out_data_dir / "songs.json").write_text(json.dumps(songs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ro_rows = _download_csv(spreadsheet_id, gid_running_order)
    running_order = []
    for r in ro_rows:
        _require_cols(r, ["round", "country_code", "order"], tab="RunningOrder")
        if not _to_iso2(r["country_code"]):
            continue
        running_order.append(
            {
                "round": _normalize_sf_round(r["round"]),
                "country_code": _to_iso2(r["country_code"]),
                "order": int(_nonempty(r["order"]) or "1"),
            }
        )
    rounds_payload = {"rounds": [], "running_order": running_order}
    (out_data_dir / "rounds.json").write_text(json.dumps(rounds_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    odds_rows = _download_csv(spreadsheet_id, gid_odds)
    odds = []
    for r in odds_rows:
        _require_cols(r, ["round", "country_code", "bookmaker", "odds", "as_of_date"], tab="Odds")
        if not _to_iso2(r["country_code"]):
            continue
        odds.append(
            {
                "round": _normalize_sf_round(r["round"]),
                "country_code": _to_iso2(r["country_code"]),
                "bookmaker": _nonempty(r["bookmaker"]),
                "odds": _nonempty(r["odds"]),
                "as_of_date": _parse_date(r.get("as_of_date", "")),
            }
        )
    (out_data_dir / "odds.json").write_text(json.dumps(odds, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    raw_res = _download_csv_raw(spreadsheet_id, gid_results)
    results_rows = list(csv.DictReader(io.StringIO(raw_res))) if raw_res.strip() else []
    results = {"summary": {"winner_country_code": ""}, "rounds": results_rows}
    (out_data_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validate_local_snapshots(data_dir=str(out_data_dir))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull Google Sheets CSV exports into data/*.json (one row per country_code)."
    )
    parser.add_argument(
        "--format",
        choices=("booklet", "template"),
        default="booklet",
        help="booklet: live Eurovision sheet tabs; template: templates/sheets column layout + RunningOrder tab.",
    )
    parser.add_argument("--spreadsheet-id", default=BOOKLET_SPREADSHEET_ID)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--out-data-dir", default=str(REPO_ROOT / "data"))
    parser.add_argument("--no-save-csv", action="store_true", help="Do not write data/source_csv/*.csv snapshots.")

    # Template-only gids
    parser.add_argument("--gid-config", default="")
    parser.add_argument("--gid-countries", default="")
    parser.add_argument("--gid-artists", default="")
    parser.add_argument("--gid-songs", default="")
    parser.add_argument("--gid-running-order", default="")
    parser.add_argument("--gid-odds", default="")
    parser.add_argument("--gid-results", default="")

    args = parser.parse_args()
    out = Path(args.out_data_dir)
    if not out.is_absolute():
        out = (REPO_ROOT / out).resolve()

    if args.format == "booklet":
        pull_booklet(
            spreadsheet_id=args.spreadsheet_id,
            gids=BOOKLET_GIDS,
            year=args.year,
            out_data_dir=out,
            save_raw_csv=not args.no_save_csv,
        )
        print(f"Wrote JSON (+ optional CSV snapshots) to {out}")
        return

    required = [
        args.gid_config,
        args.gid_countries,
        args.gid_artists,
        args.gid_songs,
        args.gid_running_order,
        args.gid_odds,
        args.gid_results,
    ]
    if not all(required):
        parser.error("--format template requires all --gid-* arguments.")
    pull_template(
        spreadsheet_id=args.spreadsheet_id,
        gid_config=args.gid_config,
        gid_countries=args.gid_countries,
        gid_artists=args.gid_artists,
        gid_songs=args.gid_songs,
        gid_running_order=args.gid_running_order,
        gid_odds=args.gid_odds,
        gid_results=args.gid_results,
        out_data_dir=out,
    )
    print(f"Wrote JSON to {out}")


if __name__ == "__main__":
    main()
