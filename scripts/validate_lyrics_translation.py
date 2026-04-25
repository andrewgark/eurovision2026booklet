#!/usr/bin/env python3
"""Validate that lyrics and a translation share structure.

Rules:
- Lines that consist only of a bracketed tag (e.g. ``[Verse 1]``, ``[Интро]``) are ignored.
- After removing those lines, both sides must have the same number of lines.
- At each index, both lines must be empty or both non-empty (whitespace-only counts as empty).

Usage:
  python scripts/validate_lyrics_translation.py
  python scripts/validate_lyrics_translation.py --json data/songs.json --lang en
  python scripts/validate_lyrics_translation.py --stanza-report
  python scripts/validate_lyrics_translation.py --original a.txt --translation b.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Whole-line section marker: optional whitespace, one [ ... ] block, optional whitespace.
_SECTION_LINE = re.compile(r"^\s*\[[^\]]+\]\s*$")


def split_lines(text: str) -> list[str]:
    # splitlines() does not append a final "" when text ends with a newline (unlike split("\n")).
    return text.replace("\r\n", "\n").replace("\r", "\n").splitlines()


def is_ignored_line(line: str) -> bool:
    return bool(_SECTION_LINE.match(line))


def structural_lines(lines: list[str]) -> list[str]:
    return [ln for ln in lines if not is_ignored_line(ln)]


def is_empty_line(line: str) -> bool:
    return line.strip() == ""


def _has_line_break(text: str) -> bool:
    return "\n" in text or "\r" in text


def stanza_lengths(text: str) -> list[int]:
    """Line counts per blank-line-separated stanza (non-heading lines only; see is_ignored_line)."""
    lines = structural_lines(split_lines(text))
    out: list[int] = []
    cur = 0
    for ln in lines:
        if not ln.strip():
            if cur:
                out.append(cur)
                cur = 0
            continue
        cur += 1
    if cur:
        out.append(cur)
    return out


def format_stanza_lengths(lengths: list[int]) -> str:
    return " ".join(str(x) for x in lengths) if lengths else "(empty)"


def validate_pair(*, original: str, translation: str, label: str = "") -> list[str]:
    """Return human-readable issues; empty list means OK."""
    o = structural_lines(split_lines(original))
    t = structural_lines(split_lines(translation))
    prefix = f"{label}: " if label else ""

    if len(o) != len(t):
        return [
            f"{prefix}line count mismatch after ignoring […] headings: "
            f"original {len(o)} vs translation {len(t)}"
        ]

    issues: list[str] = []
    for i, (lo, lt) in enumerate(zip(o, t, strict=True), start=1):
        eo, et = is_empty_line(lo), is_empty_line(lt)
        if eo != et:
            issues.append(
                f"{prefix}line {i}: empty mismatch "
                f"(original {'blank' if eo else 'text'} vs translation {'blank' if et else 'text'})"
            )
    return issues


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--json",
        type=Path,
        default=REPO_ROOT / "data" / "songs.json",
        help="Path to songs.json (default: data/songs.json)",
    )
    p.add_argument(
        "--lang",
        choices=("en", "ru", "both"),
        default="both",
        help="Which translation field to check against lyrics_original",
    )
    p.add_argument(
        "--original",
        type=Path,
        help="Plain text file: original lyrics (implies --translation)",
    )
    p.add_argument(
        "--translation",
        type=Path,
        help="Plain text file: translation",
    )
    p.add_argument(
        "--stanza-report",
        action="store_true",
        help="Print blank-line stanza sizes (orig / en / ru) and OK or FAIL per translation vs original.",
    )
    args = p.parse_args()

    if (args.original or args.translation) and not (args.original and args.translation):
        p.error("--original and --translation must be given together")

    all_issues: list[str] = []
    pairs_checked = 0
    pairs_with_newlines = 0

    if args.original and args.translation:
        orig = args.original.read_text(encoding="utf-8")
        trans = args.translation.read_text(encoding="utf-8")
        if args.stanza_report:
            issues = validate_pair(original=orig, translation=trans, label="")
            status = "OK" if not issues else "FAIL"
            print(f"{args.original}\torig\t{format_stanza_lengths(stanza_lengths(orig))}")
            print(f"{args.translation}\ttranslation\t{format_stanza_lengths(stanza_lengths(trans))}\t{status}")
            print()
        pairs_checked = 1
        if _has_line_break(orig) or _has_line_break(trans):
            pairs_with_newlines = 1
        all_issues.extend(
            validate_pair(original=orig, translation=trans, label=f"{args.original} vs {args.translation}")
        )
    else:
        path = args.json
        if not path.is_file():
            print(f"error: JSON not found: {path}", file=sys.stderr)
            return 2
        songs = json.loads(path.read_text(encoding="utf-8"))
        langs: list[str]
        if args.lang == "both":
            langs = ["en", "ru"]
        else:
            langs = [args.lang]

        if args.stanza_report:
            for song in sorted(songs, key=lambda s: str(s.get("country_code", ""))):
                code = str(song.get("country_code", "?"))
                lyrics = str(song.get("lyrics_original") or "")
                print(f"{code}\torig\t{format_stanza_lengths(stanza_lengths(lyrics))}")
                for lang, key in (("en", "translation_en"), ("ru", "translation_ru")):
                    if lang not in langs:
                        continue
                    trans = str(song.get(key) or "")
                    if not trans.strip():
                        continue
                    issues = validate_pair(original=lyrics, translation=trans, label="")
                    status = "OK" if not issues else "FAIL"
                    print(f"{code}\t{lang}\t{format_stanza_lengths(stanza_lengths(trans))}\t{status}")
                print()

        for song in songs:
            code = song.get("country_code", "?")
            lyrics = str(song.get("lyrics_original") or "")
            for lang in langs:
                key = "translation_en" if lang == "en" else "translation_ru"
                trans = str(song.get(key) or "")
                if not trans.strip():
                    continue
                pairs_checked += 1
                if _has_line_break(lyrics) or _has_line_break(trans):
                    pairs_with_newlines += 1
                label = f"{code} ({lang})"
                all_issues.extend(validate_pair(original=lyrics, translation=trans, label=label))

    if all_issues:
        for msg in all_issues:
            print(msg, file=sys.stderr)
        return 1
    print("OK: all checked pairs pass structure validation.")
    if pairs_checked == 0:
        print("Note: no non-empty translation rows were checked.")
    elif pairs_with_newlines == 0:
        print(
            f"Note: {pairs_checked} pair(s) checked, but none have line breaks in lyrics or translation. "
            "Blank-line and per-line checks only matter after you split content across lines (e.g. in the Sheet)."
        )
    else:
        print(
            f"Checked {pairs_checked} pair(s); {pairs_with_newlines} have line breaks (line structure was exercised)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
