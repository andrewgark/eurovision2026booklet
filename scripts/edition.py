"""Per-contest configuration used by PDF and HTML booklet builders."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_VARIANTS = ("overall_pre", "sf1", "sf2", "final", "overall_post")


@dataclass(frozen=True)
class BookletEdition:
    """Settings that vary between contest editions, kept beside their data."""

    edition_id: str
    variants: tuple[str, ...]
    country_sort: str
    output_stems: dict[str, str]
    legacy_data_dir: str = ""
    artist_photo_max_height_mm: float | None = None

    @classmethod
    def load(cls, edition_id: str, *, repo: Path | None = None) -> "BookletEdition":
        repo = (repo or Path(__file__).resolve().parents[1]).resolve()
        manifest_path = repo / "editions" / edition_id / "edition.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Unknown edition {edition_id!r}: expected settings in {manifest_path}"
            )
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("edition_id") != edition_id:
            raise ValueError(f"Edition id mismatch in {manifest_path}")
        variants = tuple(str(v) for v in manifest.get("variants", ()))
        if not variants:
            raise ValueError(f"No booklet variants configured in {manifest_path}")
        unsupported = set(variants).difference(SUPPORTED_VARIANTS)
        if unsupported:
            raise ValueError(f"Unsupported variants in {manifest_path}: {', '.join(sorted(unsupported))}")
        country_sort = str(manifest.get("country_sort", "localized"))
        if country_sort not in {"localized", "english"}:
            raise ValueError(f"country_sort must be 'localized' or 'english' in {manifest_path}")
        stems = {str(k): str(v) for k, v in (manifest.get("output_stems") or {}).items()}
        photo_height = manifest.get("artist_photo_max_height_mm")
        return cls(
            edition_id=edition_id,
            variants=variants,
            country_sort=country_sort,
            output_stems=stems,
            legacy_data_dir=str(manifest.get("legacy_data_dir", "")),
            artist_photo_max_height_mm=float(photo_height) if photo_height else None,
        )

    def data_dir(self, repo: Path) -> Path:
        edition_data = repo / "editions" / self.edition_id / "data"
        if edition_data.is_dir():
            return edition_data
        if self.legacy_data_dir:
            legacy = repo / self.legacy_data_dir
            if legacy.is_dir():
                return legacy
        return edition_data

    def build_dir(self, repo: Path) -> Path:
        return repo / "build" / self.edition_id

    def dist_dir(self, repo: Path) -> Path:
        return repo / "dist" / self.edition_id

    def pdf_jobname(self, variant: str, lang: str) -> str:
        stem = self.output_stems.get(variant)
        if not stem:
            stem = re.sub(r"[^a-zA-Z0-9]+", "_", self.edition_id).strip("_") + f"_{variant}"
        return f"{stem}_{lang}"

    def sort_name(self, country: dict[str, Any], lang: str) -> str:
        localized = country.get("country_name") or {}
        if self.country_sort == "english":
            return str(localized.get("en") or localized.get(lang) or "")
        return str(localized.get(lang) or localized.get("en") or "")
