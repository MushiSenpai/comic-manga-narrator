"""Phase 3 — Freesound SFX client with curated mapping and local cache."""

from __future__ import annotations

import hashlib
import json
import yaml
import requests
from pathlib import Path
from typing import Optional


class FreesoundClient:
    """Fetches SFX from Freesound API with curated keyword→ID mapping and local cache."""

    def __init__(self, api_key: str, cache_dir: Path, sfx_map_path: Path):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_map = self._load_sfx_map(sfx_map_path)
        self.base_url = "https://freesound.org/apiv2"

    def _load_sfx_map(self, path: Path) -> dict:
        """Load curated keyword→sound_id mapping."""
        if path.exists():
            return yaml.safe_load(path.read_text()) or {}
        return {}

    def _cache_key(self, keyword: str) -> str:
        return hashlib.md5(keyword.encode()).hexdigest()[:12]

    def _cached_path(self, keyword: str) -> Path:
        return self.cache_dir / f"{self._cache_key(keyword)}.wav"

    def resolve_sfx(self, sfx_text: str) -> Optional[Path]:
        """Resolve SFX text to a local audio file path.

        1. Check sfx_map.yaml for curated mapping → download by sound ID if not cached.
        2. Fall back to Freesound text search → download top result.
        3. Cache result locally.

        Returns path to WAV file, or None if unresolvable.
        """
        keyword = sfx_text.lower().strip()

        # Check cache first
        cached = self._cached_path(keyword)
        if cached.exists():
            return cached

        # Try curated mapping
        if keyword in self.sfx_map:
            entries = self.sfx_map[keyword]
            for entry in entries:
                sound_id = entry.get("id")
                if sound_id:
                    path = self._download_by_id(sound_id, keyword)
                    if path:
                        return path

        # Fallback: text search
        return self._search_and_download(keyword)

    def _download_by_id(self, sound_id: int, keyword: str) -> Optional[Path]:
        """Download a specific Freesound ID."""
        cached = self._cached_path(keyword)
        try:
            r = requests.get(
                f"{self.base_url}/sounds/{sound_id}/",
                headers={"Authorization": f"Token {self.api_key}"},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()

            # Get download URL (Freesound requires OAuth2 or token-based download)
            preview_url = data.get("previews", {}).get("preview-hq-mp3", "")
            if not preview_url:
                preview_url = data.get("previews", {}).get("preview-lq-mp3", "")

            if preview_url:
                dl = requests.get(preview_url, timeout=60)
                dl.raise_for_status()
                cached.write_bytes(dl.content)
                return cached
        except Exception:
            pass
        return None

    def _search_and_download(self, keyword: str) -> Optional[Path]:
        """Text search Freesound and download top result."""
        cached = self._cached_path(keyword)
        try:
            r = requests.get(
                f"{self.base_url}/search/text/",
                params={
                    "query": keyword,
                    "filter": "duration:[0.5 TO 10.0]",
                    "sort": "rating_desc",
                    "page_size": 3,
                    "fields": "id,name,previews",
                },
                headers={"Authorization": f"Token {self.api_key}"},
                timeout=15,
            )
            r.raise_for_status()
            results = r.json().get("results", [])

            for result in results:
                preview_url = (
                    result.get("previews", {}).get("preview-hq-mp3")
                    or result.get("previews", {}).get("preview-lq-mp3")
                )
                if preview_url:
                    dl = requests.get(preview_url, timeout=60)
                    dl.raise_for_status()
                    cached.write_bytes(dl.content)
                    return cached
        except Exception:
            pass
        return None

    def resolve_ambient(self, cues: list[str]) -> Optional[Path]:
        """Try each ambient cue keyword until one resolves."""
        for cue in cues:
            path = self.resolve_sfx(cue)
            if path:
                return path
        return None
