"""Configurable source cascade.

The 'source.priority' config key is an ordered list of sources to try for
each album.  Sources are tried left-to-right; the first confident match wins.

Built-in source names
─────────────────────
  discogs        — Discogs API via discogstagger3
  musicbrainz    — MusicBrainz API
  local          — local JSON fixture (offline / testing)
  existing_tags  — read metadata already in the audio files; organise without
                   making any API call; no new tags are written.

Configuration example
─────────────────────
  source:
    priority: [discogs, musicbrainz, existing_tags]

Backward compatibility
──────────────────────
  If 'priority' is absent but 'name' is present, 'name' is treated as a
  single-element priority list (discogstagger3 configs work unchanged).
"""
from __future__ import annotations

import logging
import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from discogstagger.album import Album
    from discogstagger.tagger_config import TaggerConfig
    from massmusictagger.source_interface import SourceConnector

logger = logging.getLogger(__name__)


def _get_priority(cfg: 'TaggerConfig') -> list[str]:
    """Return the ordered list of source names from config."""
    # YAML: priority: [discogs, musicbrainz, existing_tags]
    try:
        raw = cfg.get('source', 'priority')
        if raw:
            # Accept comma-separated string or JSON-ish list
            import ast
            try:
                val = ast.literal_eval(raw)
                if isinstance(val, list):
                    return [str(s).strip() for s in val]
            except (ValueError, SyntaxError):
                pass
            return [s.strip() for s in raw.split(',') if s.strip()]
    except Exception:
        pass
    # Backward compat: use legacy 'name' key
    try:
        name = cfg.get('source', 'name')
        if name:
            return [name.strip()]
    except Exception:
        pass
    return ['discogs']


def search_and_map(
    sourcedir: str,
    cfg: 'TaggerConfig',
    *,
    discogs_connector: Optional['SourceConnector'] = None,
    discogs_local_connector: Optional['SourceConnector'] = None,
    discogs_search=None,
    mb_connector: Optional['SourceConnector'] = None,
    mb_search=None,
    release_id_override: Optional[str] = None,
) -> Optional[tuple['Album', Optional['SourceConnector']]]:
    """Try each source in priority order; return (Album, connector) on first match.

    Returns None only when every source fails and existing_tags is not in the list.
    When existing_tags is in the list it always succeeds (returning whatever
    metadata is already in the files, or a minimal placeholder).

    Parameters
    ----------
    release_id_override
        Skip source-specific search and use this release ID directly.
        Applied to the first source in the priority list that accepts IDs.
    """
    priority = _get_priority(cfg)
    logger.debug('Source priority: %s', priority)

    for source in priority:
        logger.debug('Trying source: %s', source)

        if source in ('discogs', 'local'):
            conn = discogs_local_connector if source == 'local' else discogs_connector
            result = _try_discogs(sourcedir, cfg, conn, discogs_search,
                                  release_id_override=release_id_override)
            if result is not None:
                raw, release_id = result
                from massmusictagger.source_factory import make_discogs_mapper
                album = make_discogs_mapper(cfg).map(raw)
                album.release_id_str = release_id
                return album, conn

        elif source == 'musicbrainz':
            result = _try_musicbrainz(sourcedir, cfg, mb_connector, mb_search,
                                      release_id_override=release_id_override)
            if result is not None:
                raw, mbid = result
                from massmusictagger.source_factory import make_mb_mapper
                album = make_mb_mapper(cfg).map(raw)
                album.release_id_str = mbid
                return album, mb_connector

        elif source == 'existing_tags':
            album = _map_existing_tags(sourcedir, cfg)
            if album is not None:
                return album, None

    return None


# ── Source attempt helpers ────────────────────────────────────────────────────

def _try_discogs(sourcedir, cfg, connector, searcher,
                 release_id_override=None) -> Optional[tuple]:
    """Return (raw_release, release_id) or None."""
    if connector is None:
        return None
    try:
        relid = release_id_override or _read_id_txt(sourcedir, cfg)
        if relid is None and searcher is not None:
            searchdiscogs = cfg.getboolean('batch', 'searchdiscogs') if cfg.has_option('batch', 'searchdiscogs') else False
            if searchdiscogs:
                relid = searcher.search(sourcedir)
        if relid is None:
            return None
        raw = connector.fetch_release(relid)
        logger.info('Discogs: matched release %s for %s', relid, sourcedir)
        return raw, relid
    except Exception as exc:
        logger.warning('Discogs failed for %s: %s', sourcedir, exc)
        return None


def _try_musicbrainz(sourcedir, cfg, connector, searcher,
                     release_id_override=None) -> Optional[tuple]:
    """Return (raw_release, mbid) or None."""
    if connector is None:
        return None
    try:
        mbid = release_id_override or _read_id_txt(sourcedir, cfg, key='mbid')
        if mbid is None and searcher is not None:
            mbid = searcher.search(sourcedir)
        if mbid is None:
            return None
        raw = connector.fetch_release(mbid)
        logger.info('MusicBrainz: matched release %s for %s', mbid, sourcedir)
        return raw, mbid
    except Exception as exc:
        logger.warning('MusicBrainz failed for %s: %s', sourcedir, exc)
        return None


def _map_existing_tags(sourcedir: str, cfg: 'TaggerConfig'):
    """Build a minimal Album from metadata already embedded in audio files.

    No API calls are made.  The album can be used to rename/organise files
    using the configured format strings.  No new tag values are written
    (tagging is skipped when album.source == 'existing_tags').
    """
    from discogstagger.discogs_utils import AUDIO_EXTENSIONS
    from discogstagger.album import Album, Disc, Track

    try:
        from discogstagger.mediafile_ext import MediaFile
    except ImportError:
        logger.warning('existing_tags fallback requires discogstagger3 MediaFile')
        return None

    audio_files = sorted(
        f for f in os.listdir(sourcedir)
        if f.lower().endswith(AUDIO_EXTENSIONS)
    )
    if not audio_files:
        logger.warning('existing_tags: no audio files in %s', sourcedir)
        return None

    first_path = os.path.join(sourcedir, audio_files[0])
    try:
        mf = MediaFile(first_path)
    except Exception as exc:
        logger.warning('existing_tags: cannot read tags from %s: %s', first_path, exc)
        return None

    title   = (mf.album or os.path.basename(sourcedir)).strip()
    artist  = (mf.albumartist or mf.artist or 'Unknown Artist').strip()
    year    = str(mf.year or '')

    album = Album(identifier='0', title=title, artists=[artist])
    album._artist_display = artist
    album.sort_artist = artist
    album.year = year
    album.release_date = year or None
    album.labels = []
    album.catnumbers = []
    album.images = []
    album.genres = list(mf.genres or [])
    album.styles = []
    album.country = ''
    album.status = ''
    album.format = ''
    album.media = ''
    album.notes = ''
    album.is_compilation = bool(mf.comp)
    album.master_id = None
    album.identifiers = []
    album.barcode = ''
    album.extraartists = []
    album.source = 'existing_tags'

    disc = Disc(1)
    for i, fname in enumerate(audio_files, start=1):
        fpath = os.path.join(sourcedir, fname)
        try:
            tmf = MediaFile(fpath)
            track_title  = (tmf.title or fname).strip()
            track_artist = (tmf.artist or artist).strip()
            track_artists = [track_artist]
        except Exception:
            track_title  = fname
            track_artists = [artist]
        track = Track(i, track_title, track_artists)
        track._artist_display = track_artists[0]
        track.tracknumber = i
        track.real_tracknumber = str(i)
        track.discnumber = 1
        track.sort_artist = track_artists[0]
        track.position = i - 1
        disc.tracks.append(track)

    album.discs = [disc]
    album.disctotal = 1
    album.url = ''

    logger.info('existing_tags: built album %r (%d tracks) from %s',
                title, len(disc.tracks), sourcedir)
    return album


# ── id.txt reader ─────────────────────────────────────────────────────────────

def _read_id_txt(sourcedir: str, cfg, key: str = None) -> Optional[str]:
    """Read a release ID from the id.txt file in sourcedir.

    Without a key: return the first bare non-comment line (Discogs ID).
    With a key: return the value of 'key=value' from the file.
    """
    id_file = cfg.get('batch', 'id_file') if cfg.has_option('batch', 'id_file') else 'id.txt'
    path = os.path.join(sourcedir, id_file)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as fh:
        content = fh.read().strip()
    if not content:
        return None
    if key:
        for line in content.splitlines():
            if '=' in line:
                k, _, v = line.partition('=')
                if k.strip().lower() == key.lower():
                    return v.strip() or None
        return None
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' not in line:
            return line
    return None
