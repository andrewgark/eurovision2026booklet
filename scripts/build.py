from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape


Lang = Literal["en", "ru"]
Variant = Literal["overall_pre", "sf1", "sf2", "final", "overall_post"]


VARIANT_TITLES = {
    "overall_pre": {"en": "Overall (pre-contest)", "ru": "Общий (до конкурса)"},
    "sf1": {"en": "Semi-final 1", "ru": "Полуфинал 1"},
    "sf2": {"en": "Semi-final 2", "ru": "Полуфинал 2"},
    "final": {"en": "Final", "ru": "Финал"},
    "overall_post": {"en": "Overall (results)", "ru": "Общий (результаты)"},
}


@dataclass(frozen=True)
class EntryView:
    entry_id: str
    country_name: str
    artist_name: str
    song_title: str
    bio: str
    facts: str
    lyrics_original: str
    translation: str
    flag_path: str | None
    map_path: str | None
    photo_path: str | None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_tex(s: str) -> str:
    # Minimal escaping; we can harden once real content arrives.
    return (
        s.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("$", "\\$")
        .replace("#", "\\#")
        .replace("_", "\\_")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("~", "\\textasciitilde{}")
        .replace("^", "\\textasciicircum{}")
    )


def _safe_tex_multiline(s: str) -> str:
    s = _safe_tex(s)
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\\\\n")


def _filter_entry_ids(variant: Variant, songs: list[dict[str, Any]]) -> set[str]:
    if variant == "overall_pre" or variant == "overall_post":
        return {s["entry_id"] for s in songs}
    if variant == "sf1":
        return {s["entry_id"] for s in songs if s.get("round_sf") == "SF1"}
    if variant == "sf2":
        return {s["entry_id"] for s in songs if s.get("round_sf") == "SF2"}
    if variant == "final":
        # Before results, finalists may be unknown. We include those marked as qualified, else none.
        return {s["entry_id"] for s in songs if str(s.get("qualified_to_final") or "").strip().lower() in {"yes", "true", "1"}}
    raise ValueError(f"Unknown variant: {variant}")


def build_one(variant: Variant, lang: Lang, *, run_latex: bool) -> Path:
    repo = Path(__file__).resolve().parents[1]
    data_dir = repo / "data"
    build_dir = repo / "build"
    dist_dir = repo / "dist"
    tex_styles_dir = repo / "tex" / "styles"
    templates_dir = repo / "tex" / "templates"

    build_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)

    config = _read_json(data_dir / "config.json")
    countries = {c["country_code"]: c for c in _read_json(data_dir / "countries.json")}
    artists = {a["artist_id"]: a for a in _read_json(data_dir / "artists.json")}
    songs: list[dict[str, Any]] = _read_json(data_dir / "songs.json")
    odds_rows: list[dict[str, Any]] = _read_json(data_dir / "odds.json")

    include_ids = _filter_entry_ids(variant, songs)
    songs_included = [s for s in songs if s["entry_id"] in include_ids]

    entries: list[EntryView] = []
    for s in songs_included:
        c = countries.get(s["country_code"], {})
        a = artists.get(s["artist_id"], {})

        country_name = (c.get("country_name", {}) or {}).get(lang, s["country_code"])
        bio = (a.get("bio", {}) or {}).get(lang, "")
        facts = (s.get("facts", {}) or {}).get(lang, "") or (a.get("facts", {}) or {}).get(lang, "")

        translation = s.get("translation_ru") if lang == "ru" else s.get("translation_en")
        translation = translation or ""

        flag_path = None
        map_path = None
        photo_path = None

        # If assets exist, point to them (relative paths in TeX are OK if we set TEXINPUTS).
        flag_pdf = repo / "assets" / "flags" / "pdf" / f"{s['country_code'].upper()}.pdf"
        if flag_pdf.exists():
            flag_path = os.path.relpath(flag_pdf, build_dir)

        map_pdf = repo / "assets" / "generated" / "maps" / "pdf" / f"{s['country_code'].upper()}.pdf"
        if map_pdf.exists():
            map_path = os.path.relpath(map_pdf, build_dir)

        photo_file = str(a.get("photo_file") or "").strip()
        if photo_file:
            p = repo / "assets" / "artists" / photo_file
            if p.exists():
                photo_path = os.path.relpath(p, build_dir)

        entries.append(
            EntryView(
                entry_id=s["entry_id"],
                country_name=_safe_tex(country_name),
                artist_name=_safe_tex(a.get("artist_name", "")),
                song_title=_safe_tex(s.get("song_title_ru") if lang == "ru" else s.get("song_title_en") or s.get("song_title", "")),
                bio=_safe_tex(bio),
                facts=_safe_tex(facts),
                lyrics_original=_safe_tex_multiline(str(s.get("lyrics_original") or "")),
                translation=_safe_tex_multiline(str(translation)),
                flag_path=flag_path,
                map_path=map_path,
                photo_path=photo_path,
            )
        )

    odds_view = []
    odds_by_entry = {(o["round"], o["entry_id"]): o for o in odds_rows}
    for e in entries:
        o = odds_by_entry.get(("SF1" if variant == "sf1" else "SF2" if variant == "sf2" else "F" if variant == "final" else "SF1", e.entry_id))
        if not o and odds_rows:
            o = odds_rows[0]
        if o:
            odds_view.append(
                {
                    "entry_label": f"{e.country_name} — {e.artist_name}",
                    "bookmaker": _safe_tex(str(o.get("bookmaker", ""))),
                    "odds": _safe_tex(str(o.get("odds", ""))),
                    "as_of_date": _safe_tex(str(o.get("as_of_date", ""))),
                }
            )

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("main.tex.j2")

    mode = "post" if variant == "overall_post" else "pre"
    tex = tpl.render(
        lang=lang,
        variant=variant,
        mode=mode,
        variant_title=VARIANT_TITLES[variant][lang],
        event_name=_safe_tex(config["event_name"][lang]),
        booklet_title=_safe_tex(config["booklet_title"][lang]),
        about_text=_safe_tex(config["about_text"][lang]),
        entries=entries,
        odds_rows=odds_view,
    )

    out_tex = build_dir / f"booklet_{variant}_{lang}.tex"
    out_tex.write_text(tex, encoding="utf-8")

    if run_latex:
        if not shutil.which("latexmk"):
            raise RuntimeError(
                "latexmk not found. Install TeX Live + latexmk, or run without --run-latex to only generate .tex."
            )
        env_texinputs = f"{tex_styles_dir}{os.pathsep}" + os.environ.get("TEXINPUTS", "")
        subprocess.run(
            ["latexmk", "-lualatex", "-interaction=nonstopmode", out_tex.name],
            cwd=str(build_dir),
            check=True,
            env={**os.environ, "TEXINPUTS": env_texinputs},
        )
        pdf = build_dir / f"booklet_{variant}_{lang}.pdf"
        if pdf.exists():
            target = dist_dir / pdf.name
            target.write_bytes(pdf.read_bytes())
            return target

    return out_tex


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=list(VARIANT_TITLES.keys()))
    parser.add_argument("--lang", required=True, choices=["en", "ru"])
    parser.add_argument("--run-latex", action="store_true")
    args = parser.parse_args()

    path = build_one(args.variant, args.lang, run_latex=args.run_latex)
    print(path)


if __name__ == "__main__":
    main()

