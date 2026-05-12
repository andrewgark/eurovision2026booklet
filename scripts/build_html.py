from __future__ import annotations

import argparse
import html
import shutil
import sys
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.build import (
    VARIANTS,
    BookletEntryRaw,
    Lang,
    Variant,
    _intro_inline_to_html,
    _intro_text_to_html,
    _lyrics_orig_line_html,
    _pdf_jobname,
    _split_rows_for_twoup,
    load_booklet_raw_context,
)


_FILL_CSS = {
    "BookletProbRed": "prob-pill--red",
    "BookletProbAmber": "prob-pill--amber",
    "BookletProbGreen": "prob-pill--green",
}


def _repo_media_url(*, repo: Path, build_dir: Path, rel: str | None, depth: int) -> str | None:
    if not rel:
        return None
    p = (build_dir / rel).resolve()
    try:
        rel_to_repo = p.relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
    prefix = "../" * depth
    return prefix + rel_to_repo


def _cover_lines_html(raw: str) -> str:
    if not (raw or "").strip():
        return ""
    lines = [ln.strip() for ln in str(raw).replace("\r\n", "\n").split("\n") if ln.strip()]
    return "<br>\n".join(_intro_inline_to_html(ln) for ln in lines)


def _fact_lines_html(lines: list[str]) -> list[str]:
    return [_intro_inline_to_html(x) for x in lines]


def _bio_chunks_html(chunks: list[Any]) -> list[dict[str, Any]]:
    """``ArtistBioChunkPlain`` list → template-friendly dicts."""
    out: list[dict[str, Any]] = []
    for ch in chunks:
        if ch.bullets:
            intro_html = ""
            if ch.intro.strip():
                intro_html = "<br>\n".join(
                    _intro_inline_to_html(p) for p in ch.intro.split("\n") if p.strip()
                )
            bullets = [_intro_inline_to_html(b) for b in ch.bullets]
            out.append({"has_bullets": True, "intro_html": intro_html, "bullets_html": bullets})
        else:
            out.append({"has_bullets": False, "intro_html": _intro_inline_to_html(ch.intro)})
    return out


def _lyrics_layout_html(raw: BookletEntryRaw) -> dict[str, Any]:
    rows_h: list[dict[str, Any]] = []
    for r in raw.lyrics_rows_source:
        if r.get("kind") == "gap":
            rows_h.append({"kind": "gap"})
        else:
            rows_h.append(
                {
                    "kind": "line",
                    "orig": _lyrics_orig_line_html(str(r.get("orig", ""))),
                    "trans": html.escape(str(r.get("trans", ""))),
                }
            )
    if not raw.has_translation:
        return {"mode": "solo", "rows": rows_h}
    if raw.lyrics_short:
        left, right = _split_rows_for_twoup(rows_h)
        return {"mode": "twoup", "left": left, "right": right}
    return {"mode": "pair", "rows": rows_h}


def _lang_labels(lang: Lang) -> dict[str, str]:
    if lang == "ru":
        return {
            "toc": "Содержание",
            "aria_contents": "К содержанию — первая страница",
            "aria_site_hub": "Портал буклетов Евровидения на interoves.com",
            "aria_prev": "Предыдущая страница",
            "aria_next": "Следующая страница",
            "about": "Про Евровидение",
            "contents_link_about": "Про Евровидение",
            "country": "Страна",
            "artist": "Исполнитель",
            "song": "Песня",
            "born": "р.",
            "win": "Победа",
            "qualify": "В финал",
            "bookies": "Букмекеры считают:",
            "nf": "Нацотбор",
            "mv": "Клип",
            "results": "Результаты",
            "prev": "Назад",
            "next": "Дальше",
        }
    return {
        "toc": "Contents",
        "aria_contents": "Contents — first page",
        "aria_site_hub": "Eurovision booklet portal at interoves.com",
        "aria_prev": "Previous page",
        "aria_next": "Next page",
        "about": "About",
        "contents_link_about": "About",
        "country": "Country",
        "artist": "Artist",
        "song": "Song",
        "born": "b.",
        "win": "Win",
        "qualify": "Qualify",
        "bookies": "Bookies expect:",
        "nf": "National selection",
        "mv": "Official video",
        "results": "Results",
        "prev": "Previous",
        "next": "Next",
    }


def build_html_one(variant: Variant, lang: Lang, *, repo: Path | None = None) -> Path:
    repo = (_REPO if repo is None else repo).resolve()
    ctx = load_booklet_raw_context(variant, lang)
    stem = _pdf_jobname(variant, lang)
    dist_dir = repo / "dist"
    html_root = dist_dir / "html"
    out_dir = html_root / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    css_src = repo / "html_static" / "booklet.css"
    if css_src.exists():
        shutil.copyfile(css_src, out_dir / "booklet.css")

    templates_dir = repo / "html_templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    mode: Literal["pre", "post"] = "post" if variant == "overall_post" else "pre"
    labels = _lang_labels(lang)
    depth = len(out_dir.relative_to(repo).parts)
    build_dir = ctx.build_dir

    plan: list[tuple[str, str, dict[str, Any]]] = []
    plan.append(("cover", "cover.html.j2", {"kind": "cover"}))
    plan.append(("about", "about.html.j2", {"kind": "about"}))
    for e in ctx.raw_entries:
        plan.append((f"song-{e.country_code.lower()}", "song.html.j2", {"kind": "song", "entry": e}))
    if mode == "post":
        plan.append(("results", "results.html.j2", {"kind": "results"}))

    total = len(plan)

    toc_nav_items: list[dict[str, Any]] = []
    for i, e in enumerate(ctx.raw_entries):
        page_num = i + 3
        toc_nav_items.append(
            {
                "href": f"./page-{page_num:03d}-song-{e.country_code.lower()}.html",
                "flag_url": _repo_media_url(repo=repo, build_dir=build_dir, rel=e.flag_path, depth=depth),
                "country": e.country_name,
                "artists_joined": ", ".join(e.artist_name_lines),
                "song": e.song_title,
            }
        )

    def title_html(kind: str, extra: dict[str, Any]) -> str:
        if kind == "cover":
            return html.escape(ctx.booklet_title)
        if kind == "about":
            return html.escape(labels["about"])
        if kind == "results":
            return html.escape(labels["results"])
        raw_e: BookletEntryRaw = extra["entry"]
        return html.escape(f"{raw_e.country_name} — {raw_e.song_title}")

    for idx, (slug, tpl_name, extra) in enumerate(plan, start=1):
        fname = f"page-{idx:03d}-{slug}.html"
        kind = str(extra["kind"])
        prev_url = f"./page-{idx - 1:03d}-{plan[idx - 2][0]}.html" if idx > 1 else None
        next_url = f"./page-{idx + 1:03d}-{plan[idx][0]}.html" if idx < total else None

        base_ctx: dict[str, Any] = {
            "lang": lang,
            "variant": variant,
            "mode": mode,
            "labels": labels,
            "css_href": "./booklet.css",
            "page_index": idx,
            "page_total": total,
            "prev_url": prev_url,
            "next_url": next_url,
            "stem": stem,
            "page_title_html": title_html(kind, extra),
            "event_name_html": html.escape(ctx.event_name),
            "booklet_title_html": html.escape(ctx.booklet_title),
            "cover_subtitle_html": _cover_lines_html(ctx.cover_subtitle_raw),
            "intro_html": _intro_text_to_html(ctx.intro_raw) if ctx.intro_raw else "",
            "toc_nav_items": toc_nav_items,
        }

        if kind == "song":
            raw_e: BookletEntryRaw = extra["entry"]
            flag_u = _repo_media_url(repo=repo, build_dir=build_dir, rel=raw_e.flag_path, depth=depth)
            photo_u = _repo_media_url(repo=repo, build_dir=build_dir, rel=raw_e.photo_path, depth=depth)
            win_cls = _FILL_CSS.get(raw_e.win_fill, "prob-pill--amber")
            qual_cls = _FILL_CSS.get(raw_e.qualify_fill, "prob-pill--amber")
            base_ctx.update(
                {
                    "e": raw_e,
                    "country_name_html": html.escape(raw_e.country_name),
                    "context_html": html.escape(raw_e.context_tag),
                    "number_html": html.escape(raw_e.number_label),
                    "vote_html": html.escape(raw_e.vote_label),
                    "song_title_html": html.escape(raw_e.song_title),
                    "song_trans_html": html.escape(raw_e.song_title_translation),
                    "artist_lines_html": [html.escape(x) for x in raw_e.artist_name_lines],
                    "birth_lines_html": [html.escape(x) for x in raw_e.artist_birth_name_lines],
                    "artist_birth_year_html": html.escape(raw_e.artist_birth_year),
                    "artist_birth_place_html": html.escape(raw_e.artist_birth_place),
                    "artist_grew_up_html": html.escape(raw_e.artist_grew_up),
                    "artist_lgbtq_html": html.escape(raw_e.artist_lgbtq),
                    "bio_chunks_html": _bio_chunks_html(raw_e.bio_chunks_plain),
                    "facts_lines_html": _fact_lines_html(raw_e.facts_lines),
                    "country_stats_html": [_intro_inline_to_html(s) for s in raw_e.country_stats_lines_plain],
                    "country_facts_lines_html": _fact_lines_html(raw_e.country_facts_lines),
                    "selection_html": html.escape(raw_e.selection_tag),
                    "flag_url": flag_u,
                    "photo_url": photo_u,
                    "langs_major_html": [html.escape(t) for t in raw_e.langs_major],
                    "langs_minor_html": [html.escape(t) for t in raw_e.langs_minor],
                    "genres_html": [html.escape(t) for t in raw_e.genres],
                    "win_pct_html": html.escape(raw_e.win_percent),
                    "qual_pct_html": html.escape(raw_e.qualify_percent),
                    "win_fill_class": win_cls,
                    "qual_fill_class": qual_cls,
                    "lyrics": _lyrics_layout_html(raw_e),
                    "lyrics_font_pt": raw_e.lyrics_font_pt,
                    "lyrics_baseline_pt": raw_e.lyrics_baseline_pt,
                    "nf_url": raw_e.national_final_url,
                    "mv_url": raw_e.music_video_url,
                }
            )

        tpl = env.get_template(tpl_name)
        (out_dir / fname).write_text(tpl.render(**base_ctx), encoding="utf-8")

    cover = out_dir / "page-001-cover.html"
    if cover.exists():
        shutil.copyfile(cover, out_dir / "index.html")

    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="Static HTML booklet under dist/html/<pdf-stem>/")
    p.add_argument("--variant", required=True, choices=list(VARIANTS))
    p.add_argument("--lang", required=True, choices=["en", "ru"])
    args = p.parse_args()
    out = build_html_one(args.variant, args.lang)  # type: ignore[arg-type]
    print(out)


if __name__ == "__main__":
    main()
