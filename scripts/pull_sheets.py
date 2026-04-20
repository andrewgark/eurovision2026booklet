from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests

# Allow running via: `python scripts/pull_sheets.py`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.schema import validate_local_snapshots


@dataclass(frozen=True)
class SheetExport:
    spreadsheet_id: str
    gid_by_tab: dict[str, str]


DEFAULT_TABS = [
    "Config",
    "Countries",
    "Artists",
    "Songs",
    "RunningOrder",
    "Odds",
    "Results",
]


def _download_csv(spreadsheet_id: str, gid: str) -> list[dict[str, str]]:
    # Public export URL (no auth). Sheet must be published or shared appropriately.
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export"
    params = {"format": "csv", "gid": gid}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    return rows


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
    # Keep as ISO string; schema will parse it.
    return s


def pull(
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
    out_data_dir.mkdir(parents=True, exist_ok=True)

    # Config
    config_rows = _download_csv(spreadsheet_id, gid_config)
    config = {
        "year": 2026,
        "event_name": {"en": "", "ru": ""},
        "booklet_title": {"en": "", "ru": ""},
        "about_text": {"en": "", "ru": ""},
    }
    for r in config_rows:
        _require_cols(r, ["key", "value_en", "value_ru"], tab="Config")
        key = _nonempty(r["key"])
        if not key:
            continue
        if key == "year":
            config["year"] = int(_nonempty(r["value_en"]) or _nonempty(r["value_ru"]) or "2026")
        elif key in {"event_name", "booklet_title", "about_text"}:
            config[key] = {"en": _nonempty(r["value_en"]), "ru": _nonempty(r["value_ru"])}

    (out_data_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Countries
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
        countries.append(
            {
                "country_code": code,
                "country_name": {"en": _nonempty(r["country_name_en"]), "ru": _nonempty(r["country_name_ru"])},
                "basic_stats": {"en": _nonempty(r["basic_stats_en"]), "ru": _nonempty(r["basic_stats_ru"])},
                "eurovision_stats": {"en": _nonempty(r["eurovision_stats_en"]), "ru": _nonempty(r["eurovision_stats_ru"])},
                "flag": {"wikidata_qid": _nonempty(r["wikidata_qid"])},
                "map": {"iso_a2": code},
                "sources_urls": [],
            }
        )

    (out_data_dir / "countries.json").write_text(json.dumps(countries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Artists
    artists_rows = _download_csv(spreadsheet_id, gid_artists)
    artists: list[dict[str, Any]] = []
    for r in artists_rows:
        _require_cols(r, ["artist_id", "artist_name", "bio_en", "bio_ru", "facts_en", "facts_ru", "photo_file"], tab="Artists")
        artist_id = _nonempty(r["artist_id"])
        if not artist_id:
            continue
        artists.append(
            {
                "artist_id": artist_id,
                "artist_name": _nonempty(r["artist_name"]),
                "bio": {"en": _nonempty(r["bio_en"]), "ru": _nonempty(r["bio_ru"])},
                "facts": {"en": _nonempty(r["facts_en"]), "ru": _nonempty(r["facts_ru"])},
                "photo_file": _nonempty(r["photo_file"]),
            }
        )
    (out_data_dir / "artists.json").write_text(json.dumps(artists, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Songs
    songs_rows = _download_csv(spreadsheet_id, gid_songs)
    songs: list[dict[str, Any]] = []
    for r in songs_rows:
        _require_cols(
            r,
            [
                "entry_id",
                "country_code",
                "artist_id",
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
            ],
            tab="Songs",
        )
        entry_id = _nonempty(r["entry_id"])
        if not entry_id:
            continue
        songs.append(
            {
                "entry_id": entry_id,
                "country_code": _to_iso2(r["country_code"]),
                "artist_id": _nonempty(r["artist_id"]),
                "song_title": _nonempty(r["song_title"]),
                "song_title_en": _nonempty(r["song_title_en"]),
                "song_title_ru": _nonempty(r["song_title_ru"]),
                "lyrics_original": r.get("lyrics_original", ""),
                "translation_en": r.get("translation_en", ""),
                "translation_ru": r.get("translation_ru", ""),
                "facts": {"en": r.get("facts_en", ""), "ru": r.get("facts_ru", "")},
                "round_sf": _nonempty(r["round_sf"]).upper(),
                "qualified_to_final": _nonempty(r["qualified_to_final"]),
            }
        )
    (out_data_dir / "songs.json").write_text(json.dumps(songs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # RunningOrder
    ro_rows = _download_csv(spreadsheet_id, gid_running_order)
    running_order = []
    for r in ro_rows:
        _require_cols(r, ["round", "entry_id", "order"], tab="RunningOrder")
        if not _nonempty(r["entry_id"]):
            continue
        running_order.append({"round": _nonempty(r["round"]).upper(), "entry_id": _nonempty(r["entry_id"]), "order": int(_nonempty(r["order"]) or "1")})
    rounds_payload = {"rounds": [], "running_order": running_order}
    (out_data_dir / "rounds.json").write_text(json.dumps(rounds_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Odds
    odds_rows = _download_csv(spreadsheet_id, gid_odds)
    odds = []
    for r in odds_rows:
        _require_cols(r, ["round", "entry_id", "bookmaker", "odds", "as_of_date"], tab="Odds")
        if not _nonempty(r["entry_id"]):
            continue
        odds.append(
            {
                "round": _nonempty(r["round"]).upper(),
                "entry_id": _nonempty(r["entry_id"]),
                "bookmaker": _nonempty(r["bookmaker"]),
                "odds": _nonempty(r["odds"]),
                "as_of_date": _parse_date(r.get("as_of_date", "")),
            }
        )
    (out_data_dir / "odds.json").write_text(json.dumps(odds, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Results
    results_rows = _download_csv(spreadsheet_id, gid_results)
    # Keep flexible: store raw rows for now; we validate structure later when we finalize schema.
    results = {"summary": {"winner_entry_id": ""}, "rounds": results_rows}
    (out_data_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validate_local_snapshots(data_dir=str(out_data_dir))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet-id", required=True)

    parser.add_argument("--gid-config", required=True)
    parser.add_argument("--gid-countries", required=True)
    parser.add_argument("--gid-artists", required=True)
    parser.add_argument("--gid-songs", required=True)
    parser.add_argument("--gid-running-order", required=True)
    parser.add_argument("--gid-odds", required=True)
    parser.add_argument("--gid-results", required=True)

    parser.add_argument("--out-data-dir", default="data")
    args = parser.parse_args()

    pull(
        spreadsheet_id=args.spreadsheet_id,
        gid_config=args.gid_config,
        gid_countries=args.gid_countries,
        gid_artists=args.gid_artists,
        gid_songs=args.gid_songs,
        gid_running_order=args.gid_running_order,
        gid_odds=args.gid_odds,
        gid_results=args.gid_results,
        out_data_dir=Path(args.out_data_dir),
    )


if __name__ == "__main__":
    main()

