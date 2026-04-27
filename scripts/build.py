from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import unicodedata
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
    country_code: str
    country_name: str
    artist_name: str
    artist_birth_name: str
    artist_name_lines: list[str]
    artist_birth_name_lines: list[str]
    artist_birth_year: str
    artist_birth_place: str
    artist_grew_up: str
    artist_lgbtq: str
    song_title: str
    song_title_translation: str
    bio: str
    bio_lines: list[str]
    facts: str
    facts_lines: list[str]
    country_stats_lines: list[str]
    country_facts: str
    country_facts_lines: list[str]
    selection_tag: str
    langs_major: list[str]
    langs_minor: list[str]
    genres: list[str]
    national_final_url: str
    music_video_url: str
    lyrics_original: str
    translation: str
    lyrics_rows: list[dict[str, str]]
    lyrics_rows_left: list[dict[str, str]]
    lyrics_rows_right: list[dict[str, str]]
    lyrics_short: bool
    has_translation: bool
    lyrics_font_pt: str
    lyrics_baseline_pt: str
    win_percent: str
    qualify_percent: str
    round_sf: str
    flag_path: str | None
    photo_path: str | None
    context_tag: str
    number_label: str
    vote_label: str


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


def _safe_tex_country_stat_line(s: str) -> str:
    """Like _safe_tex, but pass through lines that embed \\TrophyIcons{...} (Noto Color Emoji)."""
    if s.startswith("\\TrophyIcons{"):
        return s
    return _safe_tex(s)


def _safe_tex_multiline(s: str) -> str:
    s = _safe_tex(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # Use paragraph breaks instead of "\\" to avoid "There's no line here to end"
    # in cases where the final rendered line break lands in vertical mode.
    return s.replace("\n", "\\par\n")


def _safe_tex_lines(s: str) -> list[str]:
    """Split a multiline string into per-line tex-safe fact tokens.

    Empty/whitespace-only lines are dropped. Used to render bio / facts /
    country-facts as a list of mini "fact chip" cards rather than one
    paragraph block.
    """
    if not s:
        return []
    raw = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for line in raw.split("\n"):
        t = line.strip()
        if t:
            out.append(_safe_tex(t))
    return out


def _split_lines(s: str) -> list[str]:
    return s.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _is_section_line(line: str) -> bool:
    ln = line.strip()
    return ln.startswith("[") and ln.endswith("]") and len(ln) >= 2


def _lyrics_rows(*, original: str, translation: str) -> list[dict[str, str]]:
    """
    Produce rows for a paired lyrics table.

    - Section heading lines like "[Verse 1]" are dropped entirely (from both sides).
    - Remaining lines are paired by index. Blank lines are preserved so stanza
      breaks show visually as a small gap. Leading/trailing blank rows are trimmed.
    - Blank rows are marked with kind="gap" so the template can render them as
      a subtle separator rather than an empty table row.
    """
    orig_struct = [ln for ln in _split_lines(original or "") if not _is_section_line(ln)]
    tr_struct = [ln for ln in _split_lines(translation or "") if not _is_section_line(ln)]

    rows: list[dict[str, str]] = []
    for i, ol in enumerate(orig_struct):
        tl = tr_struct[i] if i < len(tr_struct) else ""
        if not ol.strip() and not tl.strip():
            rows.append({"kind": "gap", "orig": "", "trans": ""})
        else:
            rows.append(
                {
                    "kind": "line",
                    "orig": _safe_tex(ol),
                    "trans": _safe_tex(tl),
                }
            )

    while rows and rows[0]["kind"] == "gap":
        rows.pop(0)
    while rows and rows[-1]["kind"] == "gap":
        rows.pop()

    return rows


# Approximate how many narrow-glyph units fit in one lyrics cell before wrapping
# at the largest preset size (~8.4pt DejaVu Sans Condensed). Paired layout uses
# two Y columns inside the 0.685\linewidth lyrics minipage; solo uses full width.
# Scaled with the minipage (was 44 / 90 at 0.71) so wrap heuristics match TeX.
# Slightly below the ~50 Latin chars noted in `tex/styles/booklet.sty` so long
# lines predict extra rows and we shrink the font before the page overflows.
_LYRICS_WRAP_BUDGET_PAIR_COL = 42.0
_LYRICS_WRAP_BUDGET_SOLO_COL = 87.0


def _lyrics_tex_visual_units(s: str) -> float:
    """Rough horizontal width for wrap heuristics (TeX-safe string, not source)."""
    total = 0.0
    for ch in s:
        ew = unicodedata.east_asian_width(ch)
        if ew in ("F", "W"):
            total += 2.0
        else:
            total += 1.0
    return total


def _lyrics_wrapped_lines_in_cell(text: str, char_budget: float) -> int:
    """How many stacked wrap lines this cell needs at the reference font size."""
    u = _lyrics_tex_visual_units(text.strip())
    if u <= 0:
        return 0
    return max(1, math.ceil(u / char_budget))


def _lyrics_layout_units(rows: list[dict[str, str]], *, has_translation: bool) -> float:
    """Effective 'line count' including multi-line wraps inside tabular cells."""
    col_budget = _LYRICS_WRAP_BUDGET_PAIR_COL if has_translation else _LYRICS_WRAP_BUDGET_SOLO_COL
    n_gaps = sum(1 for r in rows if r["kind"] == "gap")
    units = 0.0
    for r in rows:
        if r["kind"] != "line":
            continue
        orig = r.get("orig", "")
        trans = r.get("trans", "")
        if has_translation:
            wo = _lyrics_wrapped_lines_in_cell(orig, col_budget)
            wt = _lyrics_wrapped_lines_in_cell(trans, col_budget)
            row_h = max(wo, wt)
            if row_h == 0:
                row_h = 1
        else:
            row_h = _lyrics_wrapped_lines_in_cell(orig, col_budget)
            if row_h == 0:
                row_h = 1
        units += row_h
    return units + 0.6 * n_gaps


def _lyrics_font_pt(rows: list[dict[str, str]], *, has_translation: bool) -> tuple[str, str]:
    """Pick a font size for the tall lyrics column based on effective line count.

    The right-hand lyrics column is constrained to one page (`\\textheight`),
    so songs with many lyric lines need a smaller font to fit. Rows in the
    `tabularx` can grow vertically when a long original or translation wraps,
    so we estimate wrapped lines using a per-column character budget tuned at
    the largest preset size (conservative: fewer chars per line → more predicted
    wraps → smaller font before overflow).
    """
    # Thresholds are slightly loose: the wrap heuristic over-counts lines, so we
    # nudge bands upward vs raw unit totals; use `lyrics_size_modifier` on a song
    # to add pt when it still prints too small.
    units = _lyrics_layout_units(rows, has_translation=has_translation)
    if units <= 52:
        return ("8.4", "10.0")
    if units <= 62:
        return ("7.5", "9.0")
    if units <= 72:
        return ("6.8", "8.2")
    if units <= 82:
        return ("6.0", "7.3")
    if units <= 92:
        return ("5.4", "6.5")
    return ("4.9", "5.9")


def _apply_lyrics_size_modifier(
    font_pt: str, baseline_pt: str, delta_pt: float
) -> tuple[str, str]:
    """Add a sheet-specified delta (pt) to auto-chosen font and baselineskip."""
    if delta_pt == 0.0:
        return (font_pt, baseline_pt)
    try:
        f = float(font_pt) + delta_pt
        b = float(baseline_pt) + delta_pt
    except ValueError:
        return (font_pt, baseline_pt)
    # Keep within sensible bounds so we do not break the one-page lyrics column.
    f = max(4.5, min(10.0, f))
    b = max(5.4, min(11.0, b))
    return (f"{f:.1f}", f"{b:.1f}")


def _lyrics_size_modifier_from_song(s: dict[str, Any]) -> float:
    raw = s.get("lyrics_size_modifier", 0)
    if raw is None or raw == "":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _split_rows_for_twoup(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Split rows in half at a stanza boundary (gap) near the midpoint, without
    leaving a dangling gap at the top of the right column."""
    n = len(rows)
    if n == 0:
        return [], []
    target = (n + 1) // 2
    best = target
    best_dist = 10**9
    for i, r in enumerate(rows):
        if r["kind"] == "gap":
            d = abs(i - target)
            if d < best_dist:
                best_dist = d
                best = i + 1
    left = rows[:best]
    right = rows[best:]
    # Strip gaps at the edges of both columns. Gaps at the outer edges (start
    # of left, end of right) waste space; gaps at the inner edges (end of left,
    # start of right) are redundant because the stanza break is already visible
    # via the column transition.
    while left and left[0]["kind"] == "gap":
        left.pop(0)
    while left and left[-1]["kind"] == "gap":
        left.pop()
    while right and right[0]["kind"] == "gap":
        right.pop(0)
    while right and right[-1]["kind"] == "gap":
        right.pop()
    return left, right


LYRICS_TWOUP_THRESHOLD = 12
BIO_MAX_CHARS = 440
FACTS_MAX_CHARS = 440
COUNTRY_FACTS_MAX_CHARS = 280


def _split_csv_tokens(s: str) -> list[str]:
    """Split a comma-separated string into trimmed, non-empty tokens."""
    if not s:
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


def _split_stage_name_lines(raw: str) -> list[str]:
    """One line per person for the stage / group name (duo: \"A and B\", \"A & B\",
    \"A и B\"; newlines; comma-separated if several segments)."""
    s = (raw or "").replace("\r\n", "\n").strip()
    if not s:
        return []
    out: list[str] = []
    for block in s.split("\n"):
        b = block.strip()
        if not b:
            continue
        if re.search(r"\s+and\s+", b, flags=re.IGNORECASE):
            out.extend(
                p.strip() for p in re.split(r"\s+and\s+", b, flags=re.IGNORECASE) if p.strip()
            )
        elif " и " in b:
            out.extend(p.strip() for p in b.split(" и ") if p.strip())
        elif " & " in b:
            out.extend(p.strip() for p in b.split(" & ") if p.strip())
        elif ", " in b and b.count(", ") >= 1:
            out.extend(p.strip() for p in b.split(", ") if p.strip())
        else:
            out.append(b)
    return out if out else [s]


def _split_real_name_lines(raw: str) -> list[str]:
    """Group members in artist_real_name: one line per name (commas, semicolons, newlines)."""
    s = (raw or "").replace("\r\n", "\n").strip()
    if not s:
        return []
    out: list[str] = []
    for block in s.split("\n"):
        b = block.strip()
        if not b:
            continue
        if re.search(r"\s+and\s+", b, flags=re.IGNORECASE):
            chunks = re.split(r"\s+and\s+", b, flags=re.IGNORECASE)
        elif " и " in b:
            chunks = b.split(" и ")
        elif ";" in b:
            chunks = re.split(r"\s*;\s*", b)
        elif ", " in b:
            chunks = b.split(", ")
        else:
            chunks = [b]
        for c in chunks:
            t = c.strip()
            if t:
                out.append(t)
    return out if out else [s]


def _ru_pobedy_word(n: int) -> str:
    """Склонение существительного «победа» для числительного n (1 победа, 3 победы, 7 побед)."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return "победа"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "победы"
    return "побед"


def _sentence_case(token: str) -> str:
    """Capitalize the first character of a token, leave the rest as-is.
    Source data mixes capitalized ("Литовский") and lowercase ("английский")
    forms; rendering them side-by-side in language pills looks accidental, so
    we force every pill label to start with an uppercase character.
    """
    t = token.strip()
    if not t:
        return t
    return t[0].upper() + t[1:]


def _country_stats_lines(c: dict[str, Any], lang: Lang, current_year: int) -> list[str]:
    """Country stats as a list of short factoids — one per line in the panel."""
    parts: list[str] = []
    won = int(c.get("won_times") or 0)
    last = int(c.get("last_participation") or 0)
    qstreak = int(c.get("qualify_streak") or 0)
    nqstreak = int(c.get("non_qualify_streak") or 0)

    if lang == "ru":
        if won >= 1:
            parts.append(f"\\TrophyIcons{{{won}}} {won} {_ru_pobedy_word(won)}")
        if last and last != current_year and last != 2025:
            parts.append(
                f"Возвращение, последний раз были в {last}"
            )
        if qstreak >= 2:
            parts.append(f"в финале {qstreak}× подряд")
        elif nqstreak >= 2:
            parts.append(f"мимо финала {nqstreak}× подряд")
    else:
        if won >= 1:
            parts.append(f"{won}× winner")
        if last and last != current_year and last != 2025:
            parts.append(f"Return, last time in {last}")
        if qstreak >= 2:
            parts.append(f"qualified for final {qstreak}× in a row")
        elif nqstreak >= 2:
            parts.append(f"missed final {nqstreak}× in a row")
    return parts


def _lgbtq_label(value: str, lang: Lang) -> str:
    """Localized, sentence-case label for the LGBTQ tag (e.g. Квир/Гей, Queer/Gay)."""
    v = (value or "").upper().strip()
    if not v:
        return ""
    table_ru = {"QUEER": "Квир", "GAY": "Гей", "LESBIAN": "Лесбиянка", "BI": "Би", "TRANS": "Транс"}
    table_en = {"QUEER": "Queer", "GAY": "Gay", "LESBIAN": "Lesbian", "BI": "Bi", "TRANS": "Trans"}
    if lang == "ru":
        return table_ru.get(v, v.title())
    return table_en.get(v, v.title())


def _selection_tag(c: dict[str, Any], lang: Lang) -> str:
    """Localized one-word tag for national_qualify_type."""
    nat = (c.get("national_qualify_type") or "").upper()
    if lang == "ru":
        return {"PUBLIC_CONTEST": "открытый отбор", "INTERNAL_SELECTION": "внутренний отбор"}.get(nat, "")
    return {"PUBLIC_CONTEST": "public selection", "INTERNAL_SELECTION": "internal selection"}.get(nat, "")


def _smart_truncate(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars].rsplit(" ", 1)[0].rstrip(" ,.;:\u2014\u2013-")
    return f"{cut}\u2026"


def _odds_to_percent(raw: str) -> str:
    """Convert a decimal bookmaker odds value (e.g. '1.15', '401') to a
    user-readable implied probability string like '87%', '2.3%', '<1%'.

    Returns '' when the input is missing or not numeric.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        odds = float(s.replace(",", "."))
    except ValueError:
        return ""
    if odds <= 1.0:
        return "99%"
    prob = 100.0 / odds
    if prob < 1.0:
        return "<1%"
    if prob < 10.0:
        return f"{prob:.1f}%"
    return f"{int(round(prob))}%"


def _pick_probs(
    *,
    country_code: str,
    round_sf: str,
    odds_by_country: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, str]:
    """Return implied probabilities for a country:
      - winner:  probability to win the Grand Final (derived from `F` odds)
      - qualify: probability to qualify from their semi-final (derived from SF1/SF2 odds)

    Countries that auto-qualify (host, Big Five) have no `qualify` value.
    Anything missing is returned as an empty string.
    """
    winner_odds = odds_by_country.get(("F", country_code))
    win_pct = _odds_to_percent(str(winner_odds.get("odds", ""))) if winner_odds else ""

    qual_pct = ""
    rs = (round_sf or "").upper().replace("_AUTO", "")
    if rs in {"SF1", "SF2"}:
        q = odds_by_country.get((rs, country_code))
        if q:
            qual_pct = _odds_to_percent(str(q.get("odds", "")))

    return {"win_percent": win_pct, "qualify_percent": qual_pct}


def _context_tag(
    *,
    variant: Variant,
    auto_qualify: str,
    round_sf: str,
    qualified_to_final: bool,
    lang: Lang,
) -> str:
    """Per-variant one-line context tag shown under the country name in the hero band."""
    aq = (auto_qualify or "").upper()
    is_host = aq == "HOST"
    is_big5 = aq == "BIG_FIVE"
    sf = (round_sf or "").upper().replace("_AUTO", "")
    if lang == "ru":
        HOST = "Хост Евровидения"
        BIG5 = "Член Большой пятёрки"
        SF1 = "Полуфинал 1"
        SF2 = "Полуфинал 2"
        SF_ANY = "Участвует в полуфинале"
        QUAL_SF1 = "Прошли из полуфинала 1"
        QUAL_SF2 = "Прошли из полуфинала 2"
        NOQ_SF1 = "Не прошли из полуфинала 1"
        NOQ_SF2 = "Не прошли из полуфинала 2"
        PLACE = "Место в финале"
    else:
        HOST = "Eurovision host"
        BIG5 = "Big Five"
        SF1 = "Semi-final 1"
        SF2 = "Semi-final 2"
        SF_ANY = "Competing in semi-final"
        QUAL_SF1 = "Qualified from semi-final 1"
        QUAL_SF2 = "Qualified from semi-final 2"
        NOQ_SF1 = "Did not qualify from semi-final 1"
        NOQ_SF2 = "Did not qualify from semi-final 2"
        PLACE = "Place in the final"

    if variant == "overall_pre":
        if is_host:
            return HOST
        if is_big5:
            return BIG5
        if sf == "SF1":
            return SF1
        if sf == "SF2":
            return SF2
        return ""

    if variant in ("sf1", "sf2"):
        if is_host:
            return HOST
        if is_big5:
            return BIG5
        return SF_ANY

    if variant == "final":
        if is_host:
            return HOST
        if is_big5:
            return BIG5
        if sf == "SF1":
            return QUAL_SF1
        if sf == "SF2":
            return QUAL_SF2
        return ""

    if variant == "overall_post":
        if qualified_to_final:
            # Final placement not yet in data; fall back to a neutral tag until results land.
            return PLACE
        if sf == "SF1":
            return NOQ_SF1
        if sf == "SF2":
            return NOQ_SF2
        return ""

    return ""


def _filter_country_codes(variant: Variant, songs: list[dict[str, Any]]) -> set[str]:
    if variant == "overall_pre" or variant == "overall_post":
        return {s["country_code"] for s in songs}
    if variant == "sf1":
        return {s["country_code"] for s in songs if s.get("round_sf") == "SF1"}
    if variant == "sf2":
        return {s["country_code"] for s in songs if s.get("round_sf") == "SF2"}
    if variant == "final":
        # Before results, finalists may be unknown. We include those marked as qualified, else none.
        return {s["country_code"] for s in songs if str(s.get("qualified_to_final") or "").strip().lower() in {"yes", "true", "1"}}
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
    artists = {a["country_code"]: a for a in _read_json(data_dir / "artists.json")}
    songs: list[dict[str, Any]] = _read_json(data_dir / "songs.json")
    odds_rows: list[dict[str, Any]] = _read_json(data_dir / "odds.json")
    rounds_doc: dict[str, Any] = _read_json(data_dir / "rounds.json")

    include_codes = _filter_country_codes(variant, songs)
    songs_included = [s for s in songs if s["country_code"] in include_codes]
    odds_by_country = {(o["round"], o["country_code"]): o for o in odds_rows}

    running_order: dict[tuple[str, str], int] = {}
    for row in rounds_doc.get("running_order", []):
        try:
            running_order[(str(row["round"]), str(row["country_code"]))] = int(row["order"])
        except (KeyError, ValueError, TypeError):
            continue

    L_VOTE = "Голосовать" if lang == "ru" else "Vote"
    current_year = int(config.get("year") or 0)

    entries: list[EntryView] = []
    for s in songs_included:
        cc = s["country_code"]
        c = countries.get(cc, {})
        a = artists.get(cc, {})

        country_name = (c.get("country_name", {}) or {}).get(lang, cc)
        bio_raw = (a.get("bio", {}) or {}).get(lang, "") or ""
        bio = _smart_truncate(bio_raw, BIO_MAX_CHARS)
        # Song facts are song-only. Do not fall back to artist facts —
        # artist metadata has dedicated structured rendering in the artist block.
        song_facts_raw = (s.get("facts", {}) or {}).get(lang, "") or ""
        song_facts = _smart_truncate(song_facts_raw, FACTS_MAX_CHARS)

        country_stats_lines = _country_stats_lines(c, lang, current_year)
        country_facts_raw = (c.get("basic_stats", {}) or {}).get(lang, "") or ""
        country_facts = _smart_truncate(country_facts_raw, COUNTRY_FACTS_MAX_CHARS)
        selection_tag = _selection_tag(c, lang)

        artist_birth_name = (a.get("artist_real_name", {}) or {}).get(lang, "") or ""
        artist_birth_year = str(a.get("year_born") or "")
        artist_birth_place = (a.get("place_born", {}) or {}).get(lang, "") or ""
        artist_grew_up = (a.get("place_growup", {}) or {}).get(lang, "") or ""
        if artist_grew_up.strip() and artist_grew_up.strip() == artist_birth_place.strip():
            artist_grew_up = ""
        lgbt_raw = (a.get("lgbt") or "").upper()
        artist_lgbtq = _lgbtq_label(lgbt_raw, lang) if lgbt_raw in {"QUEER", "GAY"} else ""

        langs_major = _split_csv_tokens((s.get("langs", {}) or {}).get(lang, "") or "")
        langs_minor = _split_csv_tokens((s.get("langs_minor", {}) or {}).get(lang, "") or "")
        genres = _split_csv_tokens((s.get("genre", {}) or {}).get(lang, "") or "")
        national_final_url = str(s.get("national_final_url") or "").strip()
        music_video_url = str(s.get("music_video_url") or "").strip()

        translation = s.get("translation_ru") if lang == "ru" else s.get("translation_en")
        translation = translation or ""

        flag_path = None
        photo_path = None

        flag_pdf = repo / "assets" / "flags" / "pdf" / f"{cc.upper()}.pdf"
        if flag_pdf.exists():
            flag_path = os.path.relpath(flag_pdf, build_dir)

        # Photo resolution: prefer an explicit local file listed in photo_file,
        # then fall back to the conventional assets/artists/artist_<CC>.<ext>.
        photo_file = str(a.get("photo_file") or "").strip()
        candidates: list[Path] = []
        if photo_file and not photo_file.lower().startswith(("http://", "https://")):
            candidates.append(repo / "assets" / "artists" / photo_file)
        for ext in ("jpg", "jpeg", "png"):
            candidates.append(repo / "assets" / "artists" / f"artist_{cc.upper()}.{ext}")
        for p in candidates:
            if p.exists():
                photo_path = os.path.relpath(p, build_dir)
                break

        rows = _lyrics_rows(
            original=str(s.get("lyrics_original") or ""),
            translation=str(translation or ""),
        )
        has_tr = bool(str(translation or "").strip())
        short = has_tr and len(rows) <= LYRICS_TWOUP_THRESHOLD
        left_rows, right_rows = _split_rows_for_twoup(rows)

        probs = _pick_probs(
            country_code=cc,
            round_sf=str(s.get("round_sf") or ""),
            odds_by_country=odds_by_country,
        )

        qualified = str(s.get("qualified_to_final") or "").strip().lower() in {"yes", "true", "1"}
        context_tag = _context_tag(
            variant=variant,
            auto_qualify=str(c.get("auto_qualify") or ""),
            round_sf=str(s.get("round_sf") or ""),
            qualified_to_final=qualified,
            lang=lang,
        )

        number_label = ""
        if variant in ("sf1", "sf2"):
            n_sf = int(s.get("number_sf") or 0)
            if n_sf:
                number_label = str(n_sf)
        elif variant == "final":
            n = running_order.get(("F", cc))
            if n is not None:
                number_label = str(n)

        vote_label = L_VOTE if number_label else ""

        song_title_original = (
            s.get("song_title") or s.get("song_title_en") or s.get("song_title_ru") or ""
        )
        song_title_translated = (
            s.get("song_title_ru") if lang == "ru" else s.get("song_title_en")
        ) or ""
        if song_title_translated.strip() == song_title_original.strip():
            song_title_translated = ""

        artist_name_fallback = str(a.get("artist_name", "") or "")
        artist_name_ru = str(a.get("artist_name_ru", "") or "").strip()
        if lang == "ru" and artist_name_ru:
            artist_name_raw = artist_name_ru
        else:
            artist_name_raw = artist_name_fallback
        artist_name_lines = [_safe_tex(x) for x in _split_stage_name_lines(artist_name_raw)]
        if not artist_name_lines and artist_name_raw.strip():
            artist_name_lines = [_safe_tex(artist_name_raw.strip())]
        artist_birth_name_lines = [_safe_tex(x) for x in _split_real_name_lines(artist_birth_name)]

        lyrics_font, lyrics_baseline = _lyrics_font_pt(rows, has_translation=has_tr)
        mod = _lyrics_size_modifier_from_song(s)
        lyrics_font, lyrics_baseline = _apply_lyrics_size_modifier(
            lyrics_font, lyrics_baseline, mod
        )
        entries.append(
            EntryView(
                country_code=cc,
                country_name=_safe_tex(country_name),
                artist_name=_safe_tex(artist_name_raw),
                artist_birth_name=_safe_tex(artist_birth_name),
                artist_name_lines=artist_name_lines,
                artist_birth_name_lines=artist_birth_name_lines,
                artist_birth_year=_safe_tex(artist_birth_year),
                artist_birth_place=_safe_tex(artist_birth_place),
                artist_grew_up=_safe_tex(artist_grew_up),
                artist_lgbtq=_safe_tex(artist_lgbtq),
                song_title=_safe_tex(song_title_original),
                song_title_translation=_safe_tex(song_title_translated),
                bio=_safe_tex_multiline(bio),
                bio_lines=_safe_tex_lines(bio),
                facts=_safe_tex_multiline(song_facts),
                facts_lines=_safe_tex_lines(song_facts),
                country_stats_lines=[_safe_tex_country_stat_line(s) for s in country_stats_lines],
                country_facts=_safe_tex_multiline(country_facts),
                country_facts_lines=_safe_tex_lines(country_facts),
                selection_tag=_safe_tex(selection_tag),
                langs_major=[_safe_tex(_sentence_case(t)) for t in langs_major],
                langs_minor=[_safe_tex(_sentence_case(t)) for t in langs_minor],
                genres=[_safe_tex(_sentence_case(t)) for t in genres],
                national_final_url=national_final_url,
                music_video_url=music_video_url,
                lyrics_original=_safe_tex_multiline(str(s.get("lyrics_original") or "")),
                translation=_safe_tex_multiline(str(translation)),
                lyrics_rows=rows,
                lyrics_rows_left=left_rows,
                lyrics_rows_right=right_rows,
                lyrics_short=short,
                has_translation=has_tr,
                lyrics_font_pt=lyrics_font,
                lyrics_baseline_pt=lyrics_baseline,
                win_percent=_safe_tex(probs["win_percent"]),
                qualify_percent=_safe_tex(probs["qualify_percent"]),
                round_sf=_safe_tex(str(s.get("round_sf") or "")),
                flag_path=flag_path,
                photo_path=photo_path,
                context_tag=_safe_tex(context_tag),
                number_label=_safe_tex(number_label),
                vote_label=_safe_tex(vote_label),
            )
        )

    # Order entries per variant.
    def _sort_key(e: EntryView) -> tuple[int, Any, str]:
        if variant in ("sf1", "sf2"):
            rnd = "SF1" if variant == "sf1" else "SF2"
            n = running_order.get((rnd, e.country_code))
            # auto-qualifiers (no running order in this SF) go to the end, alphabetical.
            return (0, n, e.country_name) if n is not None else (1, 0, e.country_name)
        if variant == "final":
            n = running_order.get(("F", e.country_code))
            return (0, n, e.country_name) if n is not None else (1, 0, e.country_name)
        if variant == "overall_post":
            # Final placement isn't in data yet; fall back to alphabetical.
            return (0, 0, e.country_name)
        return (0, 0, e.country_name)

    entries.sort(key=_sort_key)


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
        TEX_DASH=r"\Muted{—}",
    )

    out_tex = build_dir / f"booklet_{variant}_{lang}.tex"
    out_tex.write_text(tex, encoding="utf-8")

    if run_latex:
        if not shutil.which("latexmk"):
            raise RuntimeError(
                "latexmk not found. Install TeX Live + latexmk, or run without --run-latex to only generate .tex."
            )
        env_texinputs = f"{tex_styles_dir}{os.pathsep}" + os.environ.get("TEXINPUTS", "")
        stem = f"booklet_{variant}_{lang}"
        # Clean per-variant intermediates so each run is deterministic and doesn't
        # reuse stale aux/log from previous (possibly errored) builds.
        for ext in ("aux", "log", "out", "fls", "fdb_latexmk", "synctex.gz", "toc", "pdf"):
            p = build_dir / f"{stem}.{ext}"
            if p.exists():
                p.unlink()
        # Keep LuaTeX / fontspec / luaotfload caches inside the workspace so
        # builds are self-contained and don't fight external filesystem state.
        cache_dir = repo / ".texcache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        run_env = {
            **os.environ,
            "TEXINPUTS": env_texinputs,
            "TEXMFVAR": str(cache_dir),
            "TEXMFCACHE": str(cache_dir),
        }
        proc = subprocess.run(
            ["latexmk", "-lualatex", "-interaction=nonstopmode", out_tex.name],
            cwd=str(build_dir),
            check=False,
            env=run_env,
        )
        pdf = build_dir / f"{stem}.pdf"
        if pdf.exists():
            target = dist_dir / pdf.name
            target.write_bytes(pdf.read_bytes())
            return target
        if proc.returncode != 0:
            raise RuntimeError(f"latexmk failed with exit code {proc.returncode}; PDF was not produced.")

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

