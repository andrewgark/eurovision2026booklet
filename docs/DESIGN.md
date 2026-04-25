# Booklet design rules

Target design for every per-country page in the Eurovision 2026 booklet, across all five variants (`overall_pre`, `sf1`, `sf2`, `final`, `overall_post`) and both languages (`en`, `ru`).

This document is a specification. It deliberately does not describe the current template; some rules below retire choices visible in [tex/templates/song_page.tex.j2](../tex/templates/song_page.tex.j2) and [tex/styles/booklet.sty](../tex/styles/booklet.sty). Data and template wiring follow-ups are out of scope here.

## 1. Principles

- **One country = exactly one page.** No mid-entry page breaks, no two-country pages.
- **Minimalism.** Prefer symbols, emoji, and inline context over explicit field labels. Never render words like "Languages:", "Genres:", "Bookmaker:", "Type:" — convey them with tokens (flags, emoji, typography).
- **No CAPS.** No `\MakeUppercase`, no small caps, no display fonts that render as all-caps. This applies to kickers, section titles, panel titles, and lyrics headers alike.
- **No country maps.** Maps are removed from the page layout.
- **Facts are optional decoration.** Artist / country / song fact fields are additive. When a field is empty, its slot disappears — no empty boxes, no placeholder dashes.

## 2. Variants — which countries and in what order

| Variant | Countries included | Order |
| --- | --- | --- |
| `overall_pre` | All participating countries | Alphabetical by country name in the booklet language |
| `sf1` | `round_sf ∈ {SF1, SF1_AUTO}` | `order_sf` (running order in SF1) |
| `sf2` | `round_sf ∈ {SF2, SF2_AUTO}` | `order_sf` (running order in SF2) |
| `final` | Countries that qualified to the final | `order_f` (running order in the final) |
| `overall_post` | All participating countries | Final placement ascending; non-finalists alphabetical after finalists |

`SF1_AUTO` / `SF2_AUTO` are assignment buckets for Big Five + host — countries that rehearse in a given semi-final but do not compete there. They appear in the corresponding SF booklet.

## 3. Page layout

Each page has four stacked blocks, top to bottom.

### 3.1 Block 1 — Hero

Full-width band at the top of the page.

- **Flag** (downloaded asset) + **country name** — country name is large, the strongest typographic weight in this block.
- **Context tag** directly under the country name. The tag text depends on the variant:
  - `overall_pre`: one of *Semi-final 1*, *Semi-final 2*, *Eurovision host*, *Big Five*.
  - `sf1` / `sf2`: one of *Competing in semi-final*, *Eurovision host*, *Big Five*.
  - `final`: one of *Qualified from semi-final 1*, *Qualified from semi-final 2*, *Eurovision host*, *Big Five*.
  - `overall_post`: one of *Did not qualify from semi-final 1*, *Did not qualify from semi-final 2*, *Place X in the final*.
- **Running number + "Vote" label** on the right side of the band, shown only for `sf1`, `sf2`, `final`:
  - `sf1` / `sf2` use the explicit `number_sf` column from the `Songs` sheet (preferred over the legacy `order_sf`).
  - `final` uses `number_f` from the final running order (to be added to the sheet once the final draw is known).
  - The number is large; the word *Vote* sits next to it, smaller.
  - For `overall_pre` and `overall_post` the right side of the band is empty.

The host / Big-Five flag that feeds the context tag is driven by the `auto_qualify` column in the `Countries` sheet (`HOST`, `BIG_FIVE`, empty), not by hardcoded ISO codes.

### 3.2 Block 2 — About the country

Small block, dedicated to the country itself.

- Compact country stats, drawn from the `Countries` sheet (see §6 for the exact columns):
  - Number of Eurovision wins (omit when zero, or render as a muted dash).
  - Year of last participation.
  - Qualification streak — show either "qualified N in a row" or "missed final N in a row", whichever applies; omit when both are empty.
  - National selection method: *public contest* or *internal selection*, rendered as a small muted tag, not a full label.
- Free-form country facts (from `country_facts_*`) appear underneath the stat row in a small paragraph. Strictly optional.
- **Implied probabilities from the bookmaker**, shown as two minimal pills:
  - **Qualify %** — probability to qualify to the Grand Final (derived from the semi-final odds, `round = SF1` or `SF2`). Hidden for countries that auto-qualify.
  - **Win %** — probability to win the Grand Final (derived from the final odds, `round = F`).
  - Raw decimal bookmaker odds are converted to an implied probability via `1 / odds`. Rendering rules: integer percent for values ≥ 10 % ("12%"), one decimal for 1–10 % ("2.3%"), literal "<1%" below that.
  - Each pill carries a short label identifying the bet type (*Final* / *Win* in English; *В финал* / *Победа* in Russian). Bookmaker brand is still never shown.

### 3.3 Block 3 — About the artist

- **Stage name** — strongest emphasis in this block.
- **Real (birth) name** next to the stage name, muted gray.
- **Artist photo** (downloaded asset), fixed size, next to the name.
- **LGBTQ+ / gay badge** — a small tag shown only when the artist's flag is `QUEER` or `GAY`. No badge otherwise.
- **Lightly-emphasized row**: birth year · birth place · where they grew up. Do not render `Type:`.
- **Biography** in a smaller font below. Paragraph and line breaks from the source must be preserved (the current implementation collapses them — this is a bug the new design explicitly forbids).

### 3.4 Block 4 — About the song

- **Original title** — strong emphasis.
- **Translated title** next to it, muted gray.
- **Languages** — one pill per language from the `langs_*` column (major). Optional `langs_*_minor` languages appear in the same row in a lighter/smaller style (e.g. sub-scripted or muted) to distinguish "primarily English" from "also a line in Spanish". Never render the word "Languages".
- **Genres** — one pill per value from the `genre_*` column. Never render the word "Genres".
- Optional song facts (small, one short paragraph at most), from `facts_*`.
- **Hyperlinks** at the bottom of the block, shown only when the corresponding URL exists:
  - *National selection performance* — from `national_final_url`.
  - *Official video* — from `music_video_url`.
  - Rendered as muted text with a small video/play icon rather than a full "Watch on YouTube" phrase.
- **Lyrics** live inside this same block and take up most of the page (all the vertical space below the song header, facts, and links):
  - Two columns by default: original on the left, translation on the right, line-by-line aligned.
  - Font size is chosen so that a typical lyric line fits on one column without wrapping. When a line is unavoidably long, it wraps inside its column with a small hanging indent; the paired line on the other side stays visually aligned to the start of the original line.
  - Stanza breaks from the source are preserved as small vertical gaps (a thin divider, not a blank row).
  - When a translation is absent, the lyrics fall back to a single column (or a balanced two-up split of the original), still occupying the same page region.
  - No section labels like *[Verse 1]* / *[Chorus]* are rendered; they are stripped from both sides.

## 4. Typographic conventions

- **No CAPS anywhere.**
- **Body font is sans-serif everywhere** — the cover, the about page, info panels, and lyrics all use the same typeface (DejaVu Sans) so that a Latin-only English variant and a mixed Latin+Cyrillic Russian variant render identically. No serif/Computer-Modern fallback on intro pages.
- **Muted gray** is reserved for: translated song title, translated artist (birth) name, and secondary metadata (bookmaker-adjacent context, minor facts).
- **Strong emphasis** is reserved for: country name (Block 1), stage name (Block 3), original song title (Block 4).
- Emoji and flag tokens are first-class typography — prefer them to words when they fit the slot.

## 4.1 Page rhythm

- **Cover page** carries: large event title with a magenta accent rule underneath, a prominent variant pill (e.g. *Semi-final 1* / *Полуфинал 2*), the booklet kind in muted gray next to the pill, then the *Contents* section with arrow-led entries (no plain bullets).
- **Hero band** has tight vertical padding so the country name dominates without the band feeling top-heavy. Flag is left-aligned at a fixed height; running number + *Vote* sit flush right and collapse cleanly when absent (the `overall_*` variants).
- **Info row** holds three top-aligned panels (Artist · Country · Song). Their titles always line up on the same row, regardless of how tall any individual panel grows. Widths are fixed at roughly 38 % / 33 % / 28 % so the country panel has enough room for its compact stat line and the song panel has enough room for its language / genre pills.
- **Lyrics block** starts after a slightly larger vertical breathing space than the gap between hero and info row. Both columns of a 2-up split are anchored to the same top baseline so a long wrapping first row on one side never pushes the other side down. Stanza breaks are pure whitespace (no hairline rules); line stretch is set high enough that adjacent lines never touch their wrap continuations.

## 5. Assets

- **Flags** — downloaded and cached under `assets/`, rendered from PDF in-page.
- **Artist photos** — downloaded and cached under `assets/`, rendered from a local file in-page.
- **Maps** — not used anywhere in the page layout.

## 6. Source-of-truth: Google Sheets columns

The booklet is generated from the `Eurovision Booklet Content` Google Sheet (see `scripts/pull_sheets.py` for tab GIDs). This table is the contract: every column listed here has a corresponding rendering slot above; columns marked *unused* are intentionally not rendered.

### 6.1 `Countries` tab

| Column | Render slot |
| --- | --- |
| `country_code` | Identity / join key. Not rendered directly. |
| `country_name_en` / `country_name_ru` | Block 1 — country name. |
| `auto_qualify` | Block 1 — drives the *Eurovision host* / *Big Five* context tag. Values: `HOST`, `BIG_FIVE`, empty. |
| `qualify_streak` | Block 2 — "qualified N in a row" stat (when ≥ 2). |
| `non_qualify_streak` | Block 2 — "missed final N in a row" stat (when ≥ 2). |
| `last_participation` | Block 2 — "last on stage: YYYY" stat (only when not the current year). |
| `won_times` | Block 2 — "N wins" stat (omit when zero). |
| `national_qualify_type` | Block 2 — small muted tag. Values: `PUBLIC_CONTEST`, `INTERNAL_SELECTION`. |
| `country_facts_en` / `country_facts_ru` | Block 2 — short free-form paragraph below the stat row. |

### 6.2 `Artists` tab

| Column | Render slot |
| --- | --- |
| `country_code` | Join key. |
| `artist_name_en` / `artist_name_ru` | Block 3 — stage name. |
| `artist_real_name_en` / `artist_real_name_ru` | Block 3 — birth name (muted, next to stage name). |
| `year born` | Block 3 — birth year in the meta row. |
| `place_born_en` / `place_born_ru` | Block 3 — birth place in the meta row. |
| `place_growup_en` / `place_growup_ru` | Block 3 — "grew up in" in the meta row, when different from birth place. |
| `lgbt` | Block 3 — LGBTQ+ pill (only when value is `QUEER` or `GAY`). |
| `bio_en` / `bio_ru` | Block 3 — biography paragraph. Line breaks must be preserved. |
| `photo_file` | Block 3 — artist photo asset (falls back to `assets/artists/artist_<CC>.<ext>`). |
| `type` | *Unused.* Explicitly suppressed by the design. |

### 6.3 `Songs` tab

| Column | Render slot |
| --- | --- |
| `country_code` | Join key. |
| `song_title` | Block 4 — original title. |
| `song_title_en` | Lyrics column header / fallback when the original is in a non-Latin script. |
| `song_title_translation_en` / `song_title_translation_ru` | Block 4 — translated title (muted). |
| `langs_en` / `langs_ru` | Block 4 — language pills (major). Comma-separated values become one pill each. |
| `langs_en_minor` / `langs_ru_minor` | Block 4 — language pills (minor), rendered lighter / smaller next to the major ones. |
| `genre_en` / `genre_ru` | Block 4 — genre pills. Comma-separated values become one pill each. |
| `lyrics_original` | Block 4 — left lyrics column. |
| `lyrics_en` / `lyrics_ru` | Block 4 — right lyrics column (translation). |
| `facts_en` / `facts_ru` | Block 4 — optional song facts paragraph. Strictly song-only; never falls back to artist facts. |
| `national_final_url` | Block 4 — *National selection performance* link. |
| `music_video_url` | Block 4 — *Official video* link. |
| `round_sf` | Variant routing (SF1 / SF2 / SF1_AUTO / SF2_AUTO / F). |
| `order_sf` | Variant ordering for `sf1` / `sf2`. |
| `number_sf` | Block 1 — running number for `sf1` / `sf2`. |
| `qualified_to_final` | Variant routing for `final` and post-show context tags. |

### 6.4 `Odds` tab

| Column | Render slot |
| --- | --- |
| `country_id` | Join key. |
| `SF` | Identifies which semi-final the country competes in (drives the qualify-odds bucket). |
| `odds_<DD_MM_YYYY>_<BOOKMAKER>_winner` | Block 2 — converted to *Win %* (round = `F`). |
| `odds_<DD_MM_YYYY>_<BOOKMAKER>_qualify` | Block 2 — converted to *Qualify %* (round = `SF1` / `SF2`). |
| `odds_type`, `country_name` | *Unused.* Informational only; the per-column suffix already encodes bet type and the join uses `country_id`. |

### 6.5 `Config` tab

| Column | Render slot |
| --- | --- |
| `key` = `year` | Booklet metadata. |
| `key` = `event_name` / `booklet_title` / `about_text` (`value_en`, `value_ru`) | Cover and intro pages. |

### 6.6 Fields the design needs that the sheet does not yet expose

These are blocking items for fully realising §3:

- **`number_f`** in the `Songs` tab — running number in the Grand Final, used by the `final` variant's hero band. Add once the final draw is known.
- **Final placement** (`place_f` or similar) — drives the *Place X in the final* tag in `overall_post` and the post-show ordering.

Any other column not listed in §6 should be assumed obsolete and proposed for removal from the sheet.
