from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


Lang = Literal["en", "ru"]
Round = Literal["SF1", "SF2", "F"]


class LocalizedText(BaseModel):
    en: str = ""
    ru: str = ""


class ConfigModel(BaseModel):
    year: int
    event_name: LocalizedText
    booklet_title: LocalizedText
    about_text: LocalizedText
    # Per-booklet-variant cover tagline and intro (see scripts/build.py mapping).
    subtitle_pre: LocalizedText = LocalizedText()
    subtitle_sf1: LocalizedText = LocalizedText()
    subtitle_sf2: LocalizedText = LocalizedText()
    subtitle_final: LocalizedText = LocalizedText()
    subtitle_post: LocalizedText = LocalizedText()
    intro_text_pre: LocalizedText = LocalizedText()
    intro_text_sf1: LocalizedText = LocalizedText()
    intro_text_sf2: LocalizedText = LocalizedText()
    intro_text_final: LocalizedText = LocalizedText()
    intro_text_post: LocalizedText = LocalizedText()


class CountryFlagRef(BaseModel):
    # QID for the country on Wikidata (used to retrieve P41 flag image)
    wikidata_qid: str = Field(min_length=2)


class CountryMapRef(BaseModel):
    # ISO 3166-1 alpha-2, used to select Natural Earth Admin-0 geometry
    iso_a2: str = Field(min_length=2, max_length=2)


AutoQualify = Literal["", "HOST", "BIG_FIVE"]
NationalQualifyType = Literal["", "PUBLIC_CONTEST", "INTERNAL_SELECTION"]


class CountryModel(BaseModel):
    country_code: str = Field(min_length=2, max_length=2)
    country_name: LocalizedText
    basic_stats: LocalizedText
    eurovision_stats: LocalizedText
    flag: CountryFlagRef
    map: CountryMapRef
    sources_urls: list[HttpUrl] = []
    # Structured stats from the Countries sheet (used by Block 2):
    auto_qualify: AutoQualify = ""
    qualify_streak: int = 0
    non_qualify_streak: int = 0
    last_participation: int = 0
    won_times: int = 0
    national_qualify_type: NationalQualifyType = ""


class ArtistModel(BaseModel):
    country_code: str = Field(min_length=2, max_length=2)
    artist_name: str = Field(min_length=1)
    artist_name_ru: str = ""
    bio: LocalizedText
    facts: LocalizedText
    photo_file: str = ""
    # Structured artist metadata (used by Block 3):
    artist_real_name: LocalizedText = LocalizedText()
    year_born: str = ""
    place_born: LocalizedText = LocalizedText()
    place_growup: LocalizedText = LocalizedText()
    lgbt: str = ""


class SongFacts(LocalizedText):
    pass


class SongModel(BaseModel):
    country_code: str = Field(min_length=2, max_length=2)

    song_title: str = Field(min_length=1)
    song_title_en: str = ""
    song_title_translation_en: str = ""
    song_title_ru: str = ""

    lyrics_original: str = ""
    translation_en: str = ""
    translation_ru: str = ""

    facts: SongFacts = SongFacts(en="", ru="")

    round_sf: Round
    qualified_to_final: str = ""

    # Structured song metadata (used by Block 4):
    langs: LocalizedText = LocalizedText()
    langs_minor: LocalizedText = LocalizedText()
    genre: LocalizedText = LocalizedText()
    number_sf: int = 0
    number_f: int = 0
    national_final_url: str = ""
    music_video_url: str = ""
    # Added to the base font from `_lyrics_font_pt` (pt); use when the auto heuristic is too small.
    lyrics_size_modifier: float = 0.0


class RunningOrderRow(BaseModel):
    round: Round
    country_code: str = Field(min_length=2, max_length=2)
    order: int = Field(ge=1)


class RoundsModel(BaseModel):
    rounds: list[dict] = []
    running_order: list[RunningOrderRow] = []


class OddsRow(BaseModel):
    round: Round
    country_code: str = Field(min_length=2, max_length=2)
    bookmaker: str
    odds: str
    as_of_date: date


class ResultsSummary(BaseModel):
    winner_country_code: str = Field(default="", max_length=2)


class ResultsModel(BaseModel):
    summary: ResultsSummary = ResultsSummary()
    rounds: list[dict] = []


def validate_local_snapshots(*, data_dir: str) -> None:
    """Validate the local `data/*.json` snapshots against the expected schema."""
    import json
    from pathlib import Path

    d = Path(data_dir)
    ConfigModel.model_validate_json((d / "config.json").read_text(encoding="utf-8"))

    countries = json.loads((d / "countries.json").read_text(encoding="utf-8"))
    for c in countries:
        CountryModel.model_validate(c)

    artists = json.loads((d / "artists.json").read_text(encoding="utf-8"))
    for a in artists:
        ArtistModel.model_validate(a)

    songs = json.loads((d / "songs.json").read_text(encoding="utf-8"))
    for s in songs:
        SongModel.model_validate(s)

    RoundsModel.model_validate_json((d / "rounds.json").read_text(encoding="utf-8"))

    odds = json.loads((d / "odds.json").read_text(encoding="utf-8"))
    for o in odds:
        OddsRow.model_validate(o)

    ResultsModel.model_validate_json((d / "results.json").read_text(encoding="utf-8"))

