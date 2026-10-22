from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.schema import validate_local_snapshots

EDITION_DIR = ROOT / "editions/eurovision-asia-2026"
MANIFEST = json.loads((EDITION_DIR / "edition.json").read_text(encoding="utf-8"))
SPREADSHEET_ID = MANIFEST["source_spreadsheet"].split("/d/")[1].split("/")[0]
GIDS = MANIFEST["source_tabs"]
DATA = EDITION_DIR / "data"
QIDS = {"BD":"Q902", "BT":"Q917", "KH":"Q424", "KR":"Q884", "LA":"Q819", "MN":"Q711", "MY":"Q833", "NP":"Q837", "PH":"Q928", "TH":"Q869", "VN":"Q881"}


def rows(tab: str) -> list[dict[str, str]]:
    url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={GIDS[tab]}"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    raw = response.content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    (DATA / "source_csv" / f"{tab}.csv").write_text(raw, encoding="utf-8")
    return list(csv.DictReader(io.StringIO(raw))) if raw.strip() else []


def val(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def dump(name: str, value: object) -> None:
    (DATA / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    config_rows = rows("Config")
    config_source = {val(r, "key"): r for r in config_rows if val(r, "key")}
    config: dict = {"year": 2026}
    localized = ("event_name", "booklet_title", "about_text", "subtitle_pre", "subtitle_sf1", "subtitle_sf2", "subtitle_final", "subtitle_post", "intro_text_pre", "intro_text_sf1", "intro_text_sf2", "intro_text_final", "intro_text_post")
    for key in localized:
        source_key = key
        if key == "intro_text_final" and key not in config_source:
            source_key = "intro_text_pre"
        row = config_source.get(source_key, {})
        config[key] = {"en": val(row, "value_en"), "ru": val(row, "value_ru")}
    dump("config", config)

    old_countries = {c["country_code"]: c for c in json.loads((DATA / "countries.json").read_text(encoding="utf-8"))}
    countries = []
    for row in rows("Countries"):
        code = val(row, "country_code").upper()
        c = old_countries.get(code, {"country_code": code, "flag": {"wikidata_qid": QIDS[code]}, "map": {"iso_a2": code}, "sources_urls": []})
        c.update({"country_name": {"en": val(row,"country_name_en"), "ru": val(row,"country_name_ru")},
                  "basic_stats": {"en": val(row,"country_facts_en"), "ru": val(row,"country_facts_ru")},
                  "auto_qualify": "HOST" if val(row,"auto_qualify").upper() == "HOST" else "",
                  "qualify_streak": int(val(row,"qualify_streak") or 0), "non_qualify_streak": int(val(row,"non_qualify_streak") or 0),
                  "last_participation": int(val(row,"last_participation") or 0), "won_times": int(val(row,"won_times") or 0),
                  "national_qualify_type": val(row,"national_qualify_type") if val(row,"national_qualify_type") in ("PUBLIC_CONTEST","INTERNAL_SELECTION","MIXED_SELECTION") else ""})
        countries.append(c)
    dump("countries", countries)

    old_artists = {a["country_code"]: a for a in json.loads((DATA / "artists.json").read_text(encoding="utf-8"))}
    artists = []
    for row in rows("Artists"):
        code = val(row, "country_code").upper()
        previous = old_artists[code]
        artists.append({"country_code": code, "artist_name": val(row,"artist_name_en"), "artist_name_ru": val(row,"artist_name_ru"),
            "bio": {"en": val(row,"bio_en"), "ru": val(row,"bio_ru")},
            "facts": {"en": "", "ru": ""}, "photo_file": previous.get("photo_file", ""),
            "artist_real_name": {"en": val(row,"artist_real_name_en"), "ru": val(row,"artist_real_name_ru")},
            "year_born": val(row,"year born"), "place_born": {"en": val(row,"place_born_en"), "ru": val(row,"place_born_ru")},
            "place_growup": {"en": val(row,"place_growup_en"), "ru": val(row,"place_growup_ru")}, "lgbt": val(row,"lgbt")})
    dump("artists", artists)

    songs = []
    for row in rows("Songs"):
        songs.append({"country_code": val(row,"country_code").upper(), "song_title": val(row,"song_title"),
            "song_title_en": val(row,"song_title"), "song_title_translation_en": val(row,"song_title_translation_en"),
            "song_title_ru": val(row,"song_title_translation_ru"), "lyrics_original": val(row,"lyrics_original"),
            "translation_en": val(row,"lyrics_en"), "translation_ru": val(row,"lyrics_ru"),
            "facts": {"en": val(row,"facts_en"), "ru": val(row,"facts_ru")}, "round_sf": "F", "qualified_to_final": "yes",
            "langs": {"en": val(row,"langs_en"), "ru": val(row,"langs_ru")},
            "langs_minor": {"en": val(row,"langs_en_minor"), "ru": val(row,"langs_ru_minor")},
            "genre": {"en": val(row,"genre_en"), "ru": val(row,"genre_ru")}, "number_sf": 0,
            "number_f": int(val(row,"number_final") or 0), "national_final_url": val(row,"national_final_url"),
            "music_video_url": val(row,"music_video_url"), "semi_final_video_url": "", "unofficial_live_url": val(row,"unofficial_live_url"),
            "lyrics_size_modifier": float(val(row,"lyrics_size_modifier") or 0)})
    dump("songs", songs)
    rows("Odds")
    rows("Results")
    dump("odds", [])
    dump("results", {"summary": {"winner_country_code": ""}, "rounds": []})
    dump("rounds", {"rounds": [], "running_order": []})
    validate_local_snapshots(data_dir=str(DATA))
    print(f"Updated Asia 2026 snapshots: {len(countries)} countries, {len(artists)} artists, {len(songs)} songs; schema valid.")


if __name__ == "__main__":
    main()
