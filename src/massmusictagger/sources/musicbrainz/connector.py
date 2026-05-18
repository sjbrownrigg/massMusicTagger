"""MusicBrainz source connector.

Wraps musicbrainzngs to fetch release data and Cover Art Archive images.
Release data is cached to disk as JSON so subsequent runs are instant.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, TYPE_CHECKING

import musicbrainzngs

if TYPE_CHECKING:
    from discogstagger.tagger_config import TaggerConfig

logger = logging.getLogger(__name__)

_INCLUDES = [
    'artists', 'recordings', 'labels', 'media',
    'artist-credits', 'isrcs', 'release-groups',
]

_CAA_FRONT = 'https://coverartarchive.org/release/{mbid}/front'


class MBConnector:
    """Fetches MusicBrainz releases with disk-level JSON caching."""

    def __init__(self, cfg: 'TaggerConfig'):
        user_agent = (cfg.get('musicbrainz', 'user_agent')
                      if cfg.has_option('musicbrainz', 'user_agent') else None)
        if user_agent:
            app, _, contact = user_agent.partition('/')
            version, _, contact = contact.partition(' (')
            contact = contact.rstrip(')')
            musicbrainzngs.set_useragent(app.strip(), version.strip(), contact.strip())
        else:
            musicbrainzngs.set_useragent('massMusicTagger', '1.0.0',
                                         'https://github.com/sjbrownrigg/massMusicTagger')

        cache_dir = (cfg.get('musicbrainz', 'cache_directory')
                     if cfg.has_option('musicbrainz', 'cache_directory') else None)
        self._cache_dir = os.path.expanduser(cache_dir or '~/.cache/massmusictagger/mb')
        os.makedirs(self._cache_dir, exist_ok=True)

    def fetch_release(self, mbid: str) -> dict:
        """Return the full MusicBrainz release dict for the given MBID."""
        cached = self._load_cache(mbid)
        if cached:
            logger.debug('MusicBrainz cache hit: %s', mbid)
            return cached
        logger.info('Fetching MusicBrainz release %s', mbid)
        result = musicbrainzngs.get_release_by_id(mbid, includes=_INCLUDES)
        release = result['release']
        self._save_cache(mbid, release)
        return release

    def cache_release(self, release: dict) -> None:
        mbid = release.get('id')
        if mbid:
            self._save_cache(mbid, release)

    def fetch_image(self, dest_path: str, image_url: str) -> None:
        """Download an image URL (Cover Art Archive or custom) to dest_path."""
        import requests
        headers = {'User-Agent': 'massMusicTagger/1.0.0'}
        try:
            resp = requests.get(image_url, headers=headers, timeout=30, stream=True)
            resp.raise_for_status()
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, 'wb') as fh:
                for chunk in resp.iter_content(65536):
                    fh.write(chunk)
            logger.info('Downloaded image → %s', dest_path)
        except Exception as exc:
            logger.warning('Failed to download image %s: %s', image_url, exc)

    def front_cover_url(self, mbid: str) -> str:
        return _CAA_FRONT.format(mbid=mbid)

    # ── Cache helpers ──────────────────────────────────────────────────────

    def _cache_path(self, mbid: str) -> str:
        return os.path.join(self._cache_dir, f'{mbid}.json')

    def _load_cache(self, mbid: str) -> Optional[dict]:
        path = self._cache_path(mbid)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_cache(self, mbid: str, data: dict) -> None:
        try:
            with open(self._cache_path(mbid), 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning('Could not write MB cache for %s: %s', mbid, exc)
