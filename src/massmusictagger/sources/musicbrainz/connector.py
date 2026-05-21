"""MusicBrainz source connector.

Wraps musicbrainzngs to fetch release data and Cover Art Archive images.
All network responses can be cached to disk to reduce API load during
development and repeated runs.

Cache layout under cache_directory (default ~/.cache/massmusictagger/mb):
    releases/
        <mbid>.json          — full release JSON including track listings
    caa/
        <mbid>.json          — Cover Art Archive image index for a release
    images/
        <sha256_of_url>.jpg  — downloaded CAA image files (keyed by URL hash)
    searches/
        <sha256_of_query>.json — text / barcode search results (keyed by query)

Each cache layer is controlled independently:
    musicbrainz.cache_metadata: true   # releases + CAA image lists (default: true)
    musicbrainz.cache_images:   true   # downloaded image files      (default: true)
    musicbrainz.cache_search:   true   # search result MBIDs         (default: true)

Set any flag to false to always re-fetch that layer from the network.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import musicbrainzngs

if TYPE_CHECKING:
    from discogstagger.tagger_config import TaggerConfig

logger = logging.getLogger(__name__)

_INCLUDES = [
    'artists', 'recordings', 'labels', 'media',
    'artist-credits', 'isrcs', 'release-groups',
    'tags',       # release-group.tag-list → genres
]

_CAA_FRONT  = 'https://coverartarchive.org/release/{mbid}/front'
_CAA_INDEX  = 'https://coverartarchive.org/release/{mbid}'


def _cfg_bool(cfg: 'TaggerConfig', section: str, key: str, default: bool) -> bool:
    """Read a boolean config key with a default."""
    try:
        return cfg.getboolean(section, key)
    except Exception:
        return default


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class MBConnector:
    """Fetches MusicBrainz releases with configurable disk caching."""

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
        self._cache_root = Path(os.path.expanduser(
            cache_dir or '~/.cache/massmusictagger/mb'
        ))

        self._cache_meta   = _cfg_bool(cfg, 'musicbrainz', 'cache_metadata', default=True)
        self._cache_images = _cfg_bool(cfg, 'musicbrainz', 'cache_images',   default=True)
        # cache_search is read by MBSearch directly; expose here for logging
        self._cache_search = _cfg_bool(cfg, 'musicbrainz', 'cache_search',   default=True)

        # Create subdirectories for enabled cache layers
        if self._cache_meta:
            (self._cache_root / 'releases').mkdir(parents=True, exist_ok=True)
            (self._cache_root / 'caa').mkdir(parents=True, exist_ok=True)
        if self._cache_images:
            (self._cache_root / 'images').mkdir(parents=True, exist_ok=True)
        if self._cache_search:
            (self._cache_root / 'searches').mkdir(parents=True, exist_ok=True)

        enabled = (
            (['metadata'] if self._cache_meta   else []) +
            (['images']   if self._cache_images else []) +
            (['search']   if self._cache_search else [])
        )
        if enabled:
            logger.info('MB disk cache [%s] at %s', ', '.join(enabled), self._cache_root)
        else:
            logger.info('MB disk cache disabled')

    # ── Public API ─────────────────────────────────────────────────────────

    def fetch_release(self, mbid: str) -> dict:
        """Return the full MusicBrainz release dict (with recordings) for mbid."""
        if self._cache_meta:
            cached = self._load_json(self._release_path(mbid))
            if cached is not None:
                logger.debug('MB metadata cache hit: %s', mbid)
                return cached
        logger.info('Fetching MusicBrainz release %s', mbid)
        result = musicbrainzngs.get_release_by_id(mbid, includes=_INCLUDES)
        release = result['release']
        if self._cache_meta:
            self._save_json(self._release_path(mbid), release)
        return release

    def cache_release(self, release: dict) -> None:
        mbid = release.get('id')
        if mbid and self._cache_meta:
            self._save_json(self._release_path(mbid), release)

    def fetch_image_list(self, mbid: str) -> list[dict]:
        """Return the Cover Art Archive image index for a release MBID.

        Each entry is a dict:
            {'uri': str, 'type': 'primary'|'secondary',
             'caa_types': list[str], 'width': None, 'height': None}

        The index JSON is cached alongside the release metadata so repeated
        runs for the same release don't hit the CAA API.
        """
        if self._cache_meta:
            cached = self._load_json(self._caa_path(mbid))
            if cached is not None:
                logger.debug('MB CAA cache hit: %s', mbid)
                return cached

        import requests
        url = _CAA_INDEX.format(mbid=mbid)
        headers = {'User-Agent': 'massMusicTagger/1.0', 'Accept': 'application/json'}
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning('Cover Art Archive index failed for %s: %s', mbid, exc)
            return []

        result: list[dict] = []
        for img in data.get('images', []):
            types = img.get('types') or []
            if not img.get('approved', True):
                continue
            is_front = img.get('front', False) or 'Front' in types
            result.append({
                'uri':       img.get('image') or img.get('url', ''),
                'type':      'primary' if is_front else 'secondary',
                'caa_types': types,
                'width':     None,
                'height':    None,
            })

        logger.info('Cover Art Archive: %d image(s) for release %s', len(result), mbid)
        if self._cache_meta:
            self._save_json(self._caa_path(mbid), result)
        return result

    def fetch_image(self, dest_path: str, image_url: str) -> None:
        """Download image_url to dest_path, using a local file cache.

        If the image has been downloaded before, the cached file is copied
        to dest_path without any network request.
        """
        if self._cache_images:
            cache_path = self._image_cache_path(image_url)
            if cache_path.exists():
                logger.debug('MB image cache hit: %s', image_url)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(cache_path, dest_path)
                return

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
            return

        if self._cache_images:
            try:
                cache_path = self._image_cache_path(image_url)
                shutil.copy2(dest_path, cache_path)
                logger.debug('Cached image %s', cache_path.name)
            except OSError as exc:
                logger.warning('Could not cache image: %s', exc)

    def front_cover_url(self, mbid: str) -> str:
        return _CAA_FRONT.format(mbid=mbid)

    # ── Search result cache ──────────────────────────────────────────────────
    # Used by MBSearch to cache text/barcode search results.

    def load_search(self, query_key: str) -> Optional[str]:
        """Return a cached MBID for query_key, or None if not cached."""
        if not self._cache_search:
            return None
        data = self._load_json(self._search_path(query_key))
        if data is not None:
            mbid = data.get('mbid')
            logger.debug('MB search cache hit for %r → %s', query_key[:40], mbid or 'None')
            return mbid
        return None

    def save_search(self, query_key: str, mbid: Optional[str]) -> None:
        """Cache an MBID (or None for no-match) for query_key."""
        if self._cache_search:
            self._save_json(self._search_path(query_key), {'mbid': mbid})

    # ── Path helpers ─────────────────────────────────────────────────────────

    def _release_path(self, mbid: str) -> Path:
        return self._cache_root / 'releases' / f'{mbid}.json'

    def _caa_path(self, mbid: str) -> Path:
        return self._cache_root / 'caa' / f'{mbid}.json'

    def _image_cache_path(self, url: str) -> Path:
        ext = url.rsplit('.', 1)[-1].split('?')[0].lower()
        ext = ext if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp') else 'jpg'
        return self._cache_root / 'images' / f'{_url_hash(url)}.{ext}'

    def _search_path(self, query_key: str) -> Path:
        return self._cache_root / 'searches' / f'{_url_hash(query_key)}.json'

    # ── JSON helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_json(path: Path) -> Optional[Any]:
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _save_json(path: Path, data: Any) -> None:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding='utf-8')
        except OSError as exc:
            logger.warning('MB cache write failed (%s): %s', path.name, exc)
