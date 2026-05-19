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
                # Immediately replace the placeholder image with the full
                # typed CAA image list (Front, Back, Medium, Booklet, …).
                if mb_connector and mbid:
                    caa_images = mb_connector.fetch_image_list(mbid)
                    if caa_images:
                        album.images = caa_images
                return album, mb_connector

        elif source == 'existing_tags':
            album = _map_existing_tags(sourcedir, cfg)
            if album is not None:
                return album, None

    return None


# ── Source attempt helpers ────────────────────────────────────────────────────
#
# Both _try_discogs and _try_musicbrainz apply the same validation policy for
# release IDs obtained from different origins:
#
#   Explicit ID (CLI --releaseid or id.txt)
#     → fetch, validate track count, WARN if mismatched but PROCEED.
#       The user or a previous manual step chose this ID deliberately.
#
#   Embedded tag (discogs_id / musicbrainz_releaseid in audio files)
#     → fetch, validate track count, FALL THROUGH if mismatched.
#       The tag may be stale: Discogs/MB releases can gain bonus tracks,
#       be reissued, or be corrected after an earlier tagging run.
#
#   Search result (DiscogsSearch / MBSearch)
#     → track count already validated by the search logic; accept as-is.


def _try_discogs(sourcedir, cfg, connector, searcher,
                 release_id_override=None) -> Optional[tuple]:
    """Return (raw_release, release_id) or None.

    Lookup order:
      1. release_id_override (CLI --releaseid)  — explicit; warn on mismatch
      2. id.txt Discogs ID                      — explicit; warn on mismatch
      3. discogs_id embedded in audio file tags — validate; fall through on mismatch
      4. DiscogsSearch.search_discogs()         — already track-count-validated
    """
    if connector is None:
        return None
    try:
        local_count = _local_audio_count(sourcedir)

        # ── 1. CLI override ────────────────────────────────────────────────
        if release_id_override:
            return _fetch_discogs_with_validation(
                str(release_id_override), connector, sourcedir, local_count,
                from_explicit=True,
            )

        # ── 2. Explicit id.txt Discogs ID ──────────────────────────────────
        relid = _read_id_txt(sourcedir, cfg)
        if relid:
            return _fetch_discogs_with_validation(
                relid, connector, sourcedir, local_count, from_explicit=True,
            )

        # ── 3. Existing discogs_id tag (falls through on stale match) ──────
        relid = _read_existing_discogs_id_tag(sourcedir)
        if relid:
            result = _fetch_discogs_with_validation(
                relid, connector, sourcedir, local_count, from_explicit=False,
            )
            if result is not None:
                return result
            # mismatch → fall through to search

        # ── 4. DiscogsSearch — with track count validation ─────────────────
        # DiscogsSearch does duration-based scoring but cannot guarantee an
        # exact track count match (tier-2 / no-duration candidates skip it).
        # Validate here so mismatches fall through to MB / existing_tags
        # rather than crashing downstream in _get_target_list().
        if searcher is not None:
            searchdiscogs = (cfg.getboolean('batch', 'searchdiscogs')
                             if cfg.has_option('batch', 'searchdiscogs') else False)
            if searchdiscogs:
                searcher.getSearchParams(sourcedir)
                raw = searcher.search_discogs()
                if raw is not None:
                    try:
                        _ = raw.tracklist   # trigger lazy fetch; may raise on 404
                        relid = str(raw.id)
                        release_count = _discogs_track_count(raw)
                        if not _validate_id_match(local_count, release_count,
                                                   'Discogs', relid, from_explicit=False):
                            raw = None   # track count mismatch → fall through
                        else:
                            logger.info('Discogs: matched release %s for %s', relid, sourcedir)
                            return raw, relid
                    except Exception as fetch_exc:
                        logger.warning('Discogs search result fetch failed: %s', fetch_exc)

        return None
    except Exception as exc:
        logger.warning('Discogs failed for %s: %s', sourcedir, exc)
        return None


def _try_musicbrainz(sourcedir, cfg, connector, searcher,
                     release_id_override=None) -> Optional[tuple]:
    """Return (raw_release, mbid) or None.

    Lookup order:
      1. release_id_override (CLI --releaseid)  — explicit; warn on mismatch
      2. MBSearch.search() which internally handles:
           tier 1: id.txt mbid=          — explicit; warn on mismatch
           tier 2: musicbrainz_releaseid — validate; fall through on mismatch
           tiers 3-7: text search, barcode, DiscID, AcoustID
    """
    if connector is None:
        return None
    try:
        local_count = _local_audio_count(sourcedir)

        # ── 1. CLI override ────────────────────────────────────────────────
        if release_id_override:
            raw = connector.fetch_release(release_id_override)
            mb_count = _mb_track_count(raw)
            _validate_id_match(local_count, mb_count, 'MusicBrainz',
                               release_id_override, from_explicit=True)
            logger.info('MusicBrainz: matched release %s for %s',
                        release_id_override, sourcedir)
            return raw, release_id_override

        # ── 2. MBSearch handles all remaining tiers (incl. tag + text) ────
        # Validate track count AND album artist before accepting.
        # AcoustID / text search can return a release with a mismatched track
        # count (partial rip) or no album artist (malformed MB data).
        # Both cases fall through so existing_tags can organise by metadata.
        if searcher is not None:
            mbid = searcher.search(sourcedir)
            if mbid:
                raw = connector.fetch_release(mbid)
                mb_count = _mb_track_count(raw)
                if not _validate_id_match(local_count, mb_count, 'MusicBrainz',
                                          mbid, from_explicit=False):
                    pass   # mismatch → fall through
                else:
                    # Sanity-check: release must have a usable album artist.
                    # Empty artist-credit → albumartist tag would be absent.
                    ac = raw.get('artist-credit', []) or []
                    phrase = (raw.get('artist-credit-phrase') or '').strip()
                    has_artist = bool(ac or phrase)
                    if not has_artist:
                        logger.warning(
                            'MusicBrainz release %s has no album artist — '
                            'skipping (malformed MB data?)', mbid,
                        )
                    else:
                        logger.info('MusicBrainz: matched release %s for %s', mbid, sourcedir)
                        return raw, mbid
                # mismatch or no artist → fall through (existing_tags will organise)

        return None
    except Exception as exc:
        logger.warning('MusicBrainz failed for %s: %s', sourcedir, exc)
        return None


# ── Shared validation helpers ─────────────────────────────────────────────────

def _local_audio_count(sourcedir: str) -> int:
    """Return the number of audio files in sourcedir.

    For multi-disc album roots (CD1/, CD2/ layout), audio files are in
    subdirectories rather than directly in sourcedir — in that case the
    counts from all disc subdirs are summed.
    """
    from discogstagger.discogs_utils import AUDIO_EXTENSIONS

    def _count_direct(path: str) -> int:
        try:
            return sum(1 for f in os.listdir(path)
                       if f.lower().endswith(AUDIO_EXTENSIONS)
                       and os.path.isfile(os.path.join(path, f)))
        except OSError:
            return 0

    direct = _count_direct(sourcedir)
    if direct:
        return direct

    # Multi-disc: sum across immediate subdirectories
    try:
        subdirs = [d for d in os.listdir(sourcedir)
                   if os.path.isdir(os.path.join(sourcedir, d)) and not d.startswith('.')]
    except OSError:
        return 0
    return sum(_count_direct(os.path.join(sourcedir, d)) for d in subdirs)


def _validate_id_match(local_count: int, release_count: Optional[int],
                        source_name: str, release_id: str,
                        from_explicit: bool) -> bool:
    """Return True if track counts agree (or validation is skipped).

    from_explicit=True  — id.txt or CLI: warn but always return True (proceed).
    from_explicit=False — embedded tag:  return False on mismatch (fall through).
    """
    if not local_count or release_count is None:
        return True
    if release_count == local_count:
        return True
    if from_explicit:
        logger.warning(
            '%s release %s has %d track(s) but %d audio file(s) found locally. '
            'The release may have been updated on %s since this ID was recorded. '
            'Proceeding with the explicit ID.',
            source_name, release_id, release_count, local_count, source_name,
        )
        return True
    else:
        logger.info(
            '%s release %s track count (%d) does not match local files (%d) — '
            'embedded tag is stale, falling through to search.',
            source_name, release_id, release_count, local_count,
        )
        return False


def _fetch_discogs_with_validation(relid: str, connector, sourcedir: str,
                                    local_count: int,
                                    from_explicit: bool) -> Optional[tuple]:
    """Fetch a Discogs release by ID, validate track count, return (raw, relid) or None."""
    try:
        raw = connector.fetch_release(relid)
        _ = raw.tracklist   # trigger lazy fetch; raises on 404
        release_count = _discogs_track_count(raw)
        if not _validate_id_match(local_count, release_count, 'Discogs',
                                   relid, from_explicit=from_explicit):
            return None   # stale embedded tag; caller falls through
        logger.info('Discogs: matched release %s for %s', relid, sourcedir)
        return raw, relid
    except Exception as exc:
        logger.warning('Discogs fetch/validate failed for %s: %s', relid, exc)
        return None


def _discogs_track_count(raw) -> Optional[int]:
    """Return total taggable track count from a Discogs Release object."""
    from discogstagger.discogs_utils import build_flat_tracklist
    try:
        return len(build_flat_tracklist(raw.tracklist))
    except Exception:
        return None


def _mb_track_count(raw: dict) -> Optional[int]:
    """Return total track count from a MusicBrainz release dict."""
    try:
        return sum(int(m.get('track-count', 0)) for m in raw.get('medium-list', []))
    except Exception:
        return None


def _read_existing_discogs_id_tag(sourcedir: str) -> Optional[str]:
    """Read discogs_id from the first tagged audio file in sourcedir."""
    from discogstagger.discogs_utils import AUDIO_EXTENSIONS
    try:
        from discogstagger.mediafile_ext import MediaFile
        for f in sorted(os.listdir(sourcedir)):
            if f.lower().endswith(AUDIO_EXTENSIONS):
                mf = MediaFile(os.path.join(sourcedir, f))
                did = getattr(mf, 'discogs_id', None)
                if did:
                    return str(did)
                break   # only read the first file
    except Exception:
        pass
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
    album.format_description = []   # required by TaggerUtils.map_format_description()
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
