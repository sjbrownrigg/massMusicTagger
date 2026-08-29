# -*- coding: utf-8 -*-
"""
Disk cache for Discogs API responses and downloaded images.

Layout under the cache root:
    <cache_dir>/
        releases/
            <id>.json               — full release JSON (avoids re-fetching)
        images/
            <sha256_of_url>.jpg     — downloaded cover art
        master_versions/
            <master_id>.json        — ordered list of version IDs for a master
        searches/
            <sha256_of_query>.json  — search result IDs for a (query, type) pair

All layers are optional and controlled via [cache] directory= in the config.
The JSON files are human-readable and can be inspected directly for
troubleshooting without making any API calls.
"""

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _read_json(path: Path):
    """Read a JSON file, returning None on any error."""
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning('Cache read failed (%s): %s', path.name, e)
        return None


def _write_json(path: Path, data, label: str = '') -> bool:
    """Write data as JSON, returning True on success."""
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding='utf-8')
        if label:
            logger.debug('Cached %s → %s', label, path)
        return True
    except (OSError, TypeError) as e:
        logger.warning('Cache write failed (%s): %s', path.name, e)
        return False


class ReleaseCache:
    """Cache individual Discogs release JSON on disk.

    Files are stored as <cache_dir>/releases/<id>.json and contain the raw
    API response dict.  They can be read directly for troubleshooting.
    """

    def __init__(self, cache_dir: str):
        self._dir = Path(cache_dir) / 'releases'
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, release_id) -> Path:
        return self._dir / f'{release_id}.json'

    def get(self, release_id) -> dict | None:
        p = self._path(release_id)
        if p.exists():
            logger.debug('Cache hit: release %s', release_id)
            return _read_json(p)
        return None

    def put(self, release_id, data: dict) -> None:
        _write_json(self._path(release_id), data, f'release {release_id}')


class ImageCache:
    """Cache downloaded Discogs images on disk."""

    def __init__(self, cache_dir: str):
        self._dir = Path(cache_dir) / 'images'
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self._dir / f'{digest}.jpg'

    def get(self, url: str) -> bytes | None:
        p = self._path(url)
        if p.exists():
            logger.debug('Cache hit: image %s', url)
            try:
                return p.read_bytes()
            except OSError as e:
                logger.warning('Cache read failed for image %s: %s', url, e)
        return None

    def put(self, url: str, data: bytes) -> None:
        p = self._path(url)
        try:
            p.write_bytes(data)
            logger.debug('Cached image → %s', p)
        except OSError as e:
            logger.warning('Cache write failed for image %s: %s', url, e)


class MasterVersionsCache:
    """Cache the ordered list of version IDs for a Discogs master release.

    Files are stored as <cache_dir>/master_versions/<master_id>.json and
    contain a list of release IDs.  Each ID corresponds to a file in the
    releases/ subdirectory.
    """

    def __init__(self, cache_dir: str):
        self._dir = Path(cache_dir) / 'master_versions'
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, master_id) -> Path:
        return self._dir / f'{master_id}.json'

    def get(self, master_id) -> list | None:
        p = self._path(master_id)
        if p.exists():
            logger.debug('Cache hit: master %s versions', master_id)
            return _read_json(p)
        return None

    def put(self, master_id, version_ids: list) -> None:
        _write_json(self._path(master_id), version_ids,
                    f'master {master_id} ({len(version_ids)} versions)')


class SearchCache:
    """Cache Discogs search results by (query, type).

    Files are stored as <cache_dir>/searches/<sha256>.json and contain the
    list of result IDs and their types returned by the API.
    """

    def __init__(self, cache_dir: str):
        self._dir = Path(cache_dir) / 'searches'
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, query: str, type_: str) -> Path:
        key = f'{type_}:{query}'
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self._dir / f'{digest}.json'

    def get(self, query: str, type_: str) -> list | None:
        p = self._path(query, type_)
        if p.exists():
            logger.debug('Cache hit: search "%s" (%s)', query, type_)
            data = _read_json(p)
            return data.get('results') if isinstance(data, dict) else None
        return None

    def put(self, query: str, type_: str, results: list) -> None:
        data = {'query': query, 'type': type_, 'results': results}
        _write_json(self._path(query, type_), data,
                    f'search "{query}" ({type_}, {len(results)} results)')
