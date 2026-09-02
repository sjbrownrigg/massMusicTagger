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
import re
from typing import NamedTuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from massmusictagger.core.album import Album
    from massmusictagger.core.tagger_config import TaggerConfig
    from massmusictagger.source_interface import SourceConnector

from massmusictagger.sources.hints import (
    _load_source_hints, _folder_format_hint, _folder_descriptor_hints)

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
    release_id_source: Optional[str] = None,
    notes: Optional[list] = None,
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
    notes
        Optional list. A source that fails may append one line describing what
        it compared, so a failed run can say whether nothing was found or the
        right release was refused over one field.
    """
    ctx = _Attempt(
        sourcedir=sourcedir, cfg=cfg,
        discogs_connector=discogs_connector,
        discogs_local_connector=discogs_local_connector,
        discogs_search=discogs_search,
        mb_connector=mb_connector, mb_search=mb_search,
        release_id_override=release_id_override,
        release_id_source=release_id_source,
        notes=notes,
    )

    priority = _get_priority(cfg)
    logger.debug('Source priority: %s', priority)

    for source in priority:
        resolve = _SOURCES.get(source)
        if resolve is None:
            # Previously this fell through the if/elif chain in silence, so a
            # typo in source.priority simply removed that source.
            logger.warning(
                'Unknown source %r in source.priority — ignored. Known sources: %s',
                source, ', '.join(sorted(_SOURCES)))
            continue

        logger.debug('Trying source: %s', source)
        resolved = resolve(source, ctx)
        if resolved is not None:
            return resolved

    return None



# ── One pipeline ─────────────────────────────────────────────────────────────
#
# Every source answers the same question -- "is this album yours, and if so
# what is it?" -- and returns (Album, connector) or None. Adding a fourth
# source is a registration below, not another branch in search_and_map.


class _Attempt(NamedTuple):
    """Everything a source needs to answer for one directory."""
    sourcedir: str
    cfg: 'TaggerConfig'
    discogs_connector: Optional['SourceConnector']
    discogs_local_connector: Optional['SourceConnector']
    discogs_search: object
    mb_connector: Optional['SourceConnector']
    mb_search: object
    release_id_override: Optional[str]
    #: Which source the override names. None means "whichever source accepts
    #: IDs first", the old behaviour. An id.txt always says, because a Discogs
    #: release number and a MusicBrainz MBID are not interchangeable and
    #: handing one to the other wastes a lookup at best.
    release_id_source: Optional[str] = None
    #: Caller-owned list a source may append one diagnosis line to when it
    #: fails. Per attempt, never on a shared searcher: the searcher object is
    #: reused across worker threads.
    notes: Optional[list] = None


def _override_for(source: str, ctx: '_Attempt') -> Optional[str]:
    """The explicit release ID, if it was meant for this source.

    An unqualified ID goes to whichever source is tried first, which is what
    --releaseid always did. A qualified one -- from an id.txt, or
    `--releaseid musicbrainz:<mbid>` -- only applies to the source it names,
    so the others fall back to searching instead of being handed an ID from
    a numbering scheme they do not use.
    """
    if not ctx.release_id_override:
        return None
    if ctx.release_id_source in (None, source):
        return ctx.release_id_override
    # 'local' reads the same Discogs numbering from a local JSON dump.
    if ctx.release_id_source == 'discogs' and source == 'local':
        return ctx.release_id_override
    return None


def _resolve_discogs(source: str, ctx: '_Attempt'):
    """discogs and local differ only in which connector fetches."""
    conn = (ctx.discogs_local_connector if source == 'local'
            else ctx.discogs_connector)
    found = _try_discogs(ctx.sourcedir, ctx.cfg, conn, ctx.discogs_search,
                         release_id_override=_override_for(source, ctx),
                         notes=ctx.notes)
    if found is None:
        return None
    raw, release_id = found
    from massmusictagger.source_factory import make_discogs_mapper
    album = make_discogs_mapper(ctx.cfg, connector=conn,
                                local_count=_local_audio_count(ctx.sourcedir)
                                ).map(raw)
    album.release_id_str = release_id
    return album, conn


def _prefers_discogs(cfg) -> bool:
    """Does this configuration want Discogs metadata over MusicBrainz?

    Following the link is only right for someone whose priority list puts
    Discogs first. Someone who asked for MusicBrainz first asked for
    MusicBrainz metadata, and should not be handed Discogs by a side door.
    """
    priority = _get_priority(cfg)
    if 'discogs' not in priority or 'musicbrainz' not in priority:
        return 'discogs' in priority
    return priority.index('discogs') < priority.index('musicbrainz')


_DISCOGS_RELEASE_URL = re.compile(r'discogs\.com/(?:[a-z]{2}/)?release/(\d+)')


def discogs_release_from_mb(raw: dict) -> Optional[str]:
    """The Discogs release a MusicBrainz release is linked to, if any.

    MusicBrainz editors curate these links, so the identifier is as trustworthy
    as a hand-written id.txt and far more available: about a third of the
    albums in this library that fell through to MusicBrainz carry one --
    Henry's Dream, Station to Station, Music For A Slaughtering Tribe. Every
    one of those is an album Discogs holds and our Discogs search failed to
    find.

    The relations ride along on the release fetch (`url-rels` in _INCLUDES),
    so reading them costs no additional request.
    """
    for rel in (raw.get('url-relation-list') or []):
        target = (rel.get('target') or '')
        if not target and isinstance(rel.get('url'), dict):
            target = rel['url'].get('resource') or ''
        m = _DISCOGS_RELEASE_URL.search(target or '')
        if m:
            return m.group(1)
    return None


def _resolve_musicbrainz(source: str, ctx: '_Attempt'):
    found = _try_musicbrainz(ctx.sourcedir, ctx.cfg, ctx.mb_connector,
                             ctx.mb_search,
                             release_id_override=_override_for(source, ctx))
    if found is None:
        return None
    raw, mbid = found

    # MusicBrainz found it; Discogs may hold it too and simply not have been
    # found. When the priority list prefers Discogs, follow the curated link
    # rather than handing back second-choice metadata. The release still has
    # to validate against the local track count, so a stale or wrong link
    # falls through to the MusicBrainz mapping below rather than replacing it.
    if _prefers_discogs(ctx.cfg) and ctx.discogs_connector is not None:
        drid = discogs_release_from_mb(raw)
        if drid:
            logger.info('MusicBrainz release %s links to Discogs release %s — '
                        'following it', mbid, drid)
            via_link = _fetch_discogs_with_validation(
                drid, ctx.discogs_connector, ctx.sourcedir,
                _local_audio_count(ctx.sourcedir), from_explicit=False)
            if via_link is not None:
                from massmusictagger.source_factory import make_discogs_mapper
                d_raw, d_id = via_link
                album = make_discogs_mapper(
                    ctx.cfg, connector=ctx.discogs_connector,
                    local_count=_local_audio_count(ctx.sourcedir)).map(d_raw)
                album.release_id_str = d_id
                return album, ctx.discogs_connector
            logger.info('Discogs release %s did not validate — keeping the '
                        'MusicBrainz match', drid)

    from massmusictagger.source_factory import make_mb_mapper
    album = make_mb_mapper(ctx.cfg).map(raw)
    album.release_id_str = mbid

    # The mapper leaves a placeholder image; the full typed Cover Art Archive
    # list (Front, Back, Medium, Booklet, …) is a second request. This is the
    # only per-source step left in the cascade, and phase 4 removes it by
    # carrying attachments in the mapped result.
    if ctx.mb_connector and mbid:
        caa_images = ctx.mb_connector.fetch_image_list(mbid)
        if caa_images:
            from massmusictagger.core.attachments import from_caa
            album.attachments = [from_caa(i) for i in caa_images]
    return album, ctx.mb_connector


def _resolve_existing_tags(source: str, ctx: '_Attempt'):
    """Last resort: whatever the files already say. No release, no connector."""
    album = _map_existing_tags(ctx.sourcedir, ctx.cfg)
    return (album, None) if album is not None else None


_SOURCES = {
    'discogs':       _resolve_discogs,
    'local':         _resolve_discogs,
    'musicbrainz':   _resolve_musicbrainz,
    'existing_tags': _resolve_existing_tags,
}


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
                 release_id_override=None, notes=None) -> Optional[tuple]:
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

        # id.txt used to be read here, by a parser that only ever looked
        # for discogs_id -- so a file naming musicbrainz was silently
        # ignored. The processor reads it once per directory now, routes
        # it to the source it names, and passes it in as
        # release_id_override above.

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
                relid = searcher.search(sourcedir, notes=notes)
                raw = connector.fetch_release(relid) if relid else None
                if raw is not None:
                    try:
                        release_count = _discogs_track_count(raw, local_count=local_count)
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
                        # Format hint check — warn when folder clues conflict
                        # with matched medium format (audit signal, not rejection).
                        _fmt_hint = _folder_format_hint(
                            sourcedir, _load_source_hints(cfg))
                        if _fmt_hint:
                            _mediums = [m.get('format', '').lower()
                                        for m in raw.get('medium-list', [])]
                            _is_vinyl   = any('vinyl'   in f for f in _mediums)
                            _is_digital = any('digital' in f for f in _mediums)
                            if _fmt_hint == 'digital' and _is_vinyl:
                                logger.warning(
                                    'Format hint mismatch: folder suggests digital '
                                    'but MB release %s contains vinyl media — '
                                    'consider setting an id.txt override (folder: %s)',
                                    mbid, os.path.basename(sourcedir),
                                )
                            elif _fmt_hint == 'vinyl' and _is_digital:
                                logger.warning(
                                    'Format hint mismatch: folder suggests vinyl '
                                    'but MB release %s contains digital media '
                                    '(folder: %s)',
                                    mbid, os.path.basename(sourcedir),
                                )
                        logger.info('MusicBrainz: matched release %s for %s',
                                    mbid, sourcedir)
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
    from massmusictagger.sources.discogs.utils import AUDIO_EXTENSIONS

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
        release_count = _discogs_track_count(raw, local_count=local_count)
        if not _validate_id_match(local_count, release_count, 'Discogs',
                                   relid, from_explicit=from_explicit):
            return None   # stale embedded tag; caller falls through
        logger.info('Discogs: matched release %s for %s', relid, sourcedir)
        return raw, relid
    except Exception as exc:
        logger.warning('Discogs fetch/validate failed for %s: %s', relid, exc)
        return None


def _discogs_track_count(raw, local_count: Optional[int] = None) -> Optional[int]:
    """Return total taggable track count from a Discogs Release object.

    When local_count is supplied and the flat count mismatches, tries the
    lettered sub-track merge (13a+13b+13c → 13) as a fallback so that
    explicit-ID validation doesn't emit a spurious mismatch warning.
    """
    from massmusictagger.sources.discogs.utils import (
        build_flat_tracklist, merge_indexed_subtracks, prefers_expanded_index)
    try:
        flat = build_flat_tracklist(raw.tracklist)
        if local_count is not None and len(flat) != local_count:
            merged = merge_indexed_subtracks(flat)
            if merged is not None and len(merged) == local_count:
                return len(merged)
            # An index entry with a parent duration and timed sub_tracks --
            # or neither -- reads equally as one file or several, and Discogs
            # carries nothing that settles it. Try the other reading before
            # calling it a mismatch.
            if prefers_expanded_index(raw.tracklist, local_count):
                return local_count
        return len(flat)
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
    from massmusictagger.sources.discogs.utils import AUDIO_EXTENSIONS
    try:
        from massmusictagger.core.mediafile import MediaFile
        for f in sorted(os.listdir(sourcedir)):
            if f.lower().endswith(AUDIO_EXTENSIONS) and os.path.isfile(os.path.join(sourcedir, f)):
                mf = MediaFile(os.path.join(sourcedir, f))
                did = getattr(mf, 'discogs_id', None)
                if did:
                    return str(did)
                break   # only read the first file
    except Exception:
        pass
    return None


def _parse_dirname_metadata(dirname: str) -> dict:
    """Extract structured metadata from a music directory name.

    Handles patterns commonly produced by taggers and rippers:
      [2009] Album Title
      (2009) Album Title
      [2009] (2010) - Album Title [bootleg]
      [2009-05-21] Album Title
      Album Title [bootleg] [DCD flac-lossless-44s]

    Returns a dict with keys:
      years   — list of year strings found (first = likely recording/event year)
      title   — cleaned album title (dates, status, format bracket stripped)
      status  — 'Bootleg', 'Promo', or None
    """
    name = dirname

    # Strip trailing mmt/dt3 format bracket: ends the dirname and contains a
    # codec name or quality indicator (e.g. "[DM flac-lossless-44s]", "[.B flac…]")
    name = re.sub(
        r'\s*\[[^\]]*(?:flac|mp3|aac|ogg|opus|wav|lossless|lossy|vbr|\d{2,4}kbps|\d{2,3}s)[^\]]*\]\s*$',
        '', name, flags=re.IGNORECASE,
    ).strip()

    # Extract and remove status indicators: [bootleg], [promo], [promo-only] etc.
    status = None
    def _absorb_status(m):
        nonlocal status
        val = m.group(1).lower().strip()
        if 'bootleg' in val:
            status = 'Bootleg'
        elif 'promo' in val:
            status = 'Promo'
        return ''
    name = re.sub(r'\[(bootleg|promo(?:tional)?(?:[- ]\w+)*)\]', _absorb_status, name, flags=re.IGNORECASE)
    name = name.strip()

    # Extract bracketed / parenthesised dates from the START of the remaining name.
    # A date token is [YYYY], (YYYY), [YYYY-MM-DD], or (YYYY-MM-DD).
    years: list[str] = []
    while True:
        m = re.match(
            r'^\s*(?:\[(\d{4}(?:-\d{2}(?:-\d{2})?)?)\]|\((\d{4}(?:-\d{2}(?:-\d{2})?)?)\))\s*',
            name,
        )
        if not m:
            break
        years.append((m.group(1) or m.group(2))[:4])   # store 4-digit year only
        name = name[m.end():]

    # Strip optional " - " or " – " separator left after the date tokens
    name = re.sub(r'^\s*[-–]\s*', '', name).strip()

    # Collapse internal whitespace
    title = re.sub(r'\s+', ' ', name).strip() or None

    return {'years': years, 'title': title, 'status': status}


def _clean_fallback_title(fname: str) -> str:
    """Derive a track title from a bare filename when no title tag exists.

    Strips trailing audio extensions and leading track-number prefixes
    (e.g. "01 ", "01-", "01.") repeatedly, so that re-running existing_tags
    on files it previously named (e.g. "01-Artist-01 Title.mp3.mp3") doesn't
    snowball duplicate track numbers and extensions into the title on every
    pass — each run converges to the same cleaned title instead.
    """
    from massmusictagger.sources.discogs.utils import AUDIO_EXTENSIONS

    name = fname
    while True:
        base, ext = os.path.splitext(name)
        if ext.lower() in AUDIO_EXTENSIONS:
            name = base
        else:
            break
    while True:
        m = re.match(r'^\d{1,3}[\s._-]+(.*)$', name)
        if not m:
            break
        name = m.group(1)
    return name.strip() or fname


def _map_existing_tags(sourcedir: str, cfg: 'TaggerConfig'):
    """Build a minimal Album from metadata already embedded in audio files.

    No API calls are made.  The album can be used to rename/organise files
    using the configured format strings.  No new tag values are written
    (tagging is skipped when album.source == 'existing_tags').
    """
    from massmusictagger.sources.discogs.utils import AUDIO_EXTENSIONS
    from massmusictagger.core.album import Album, Disc, Track

    try:
        from massmusictagger.core.mediafile import MediaFile
    except ImportError:
        logger.warning('existing_tags fallback requires discogstagger3 MediaFile')
        return None

    audio_files = sorted(
        f for f in os.listdir(sourcedir)
        if f.lower().endswith(AUDIO_EXTENSIONS)
        and os.path.isfile(os.path.join(sourcedir, f))
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

    # Parse current and parent directory names for metadata clues.
    # These fill gaps when embedded tags are absent — they never override
    # existing tag values.
    _dirname  = os.path.basename(sourcedir.rstrip('/\\'))
    _parentdir = os.path.basename(os.path.dirname(sourcedir.rstrip('/\\')))
    _dn = _parse_dirname_metadata(_dirname)

    # Artist: embedded albumartist → embedded artist → parent directory name.
    # The parent directory is almost always the artist folder.
    _parent_artist = _parentdir if _parentdir not in ('', '.', '..') else ''
    artist = (mf.albumartist or mf.artist or _parent_artist or 'Unknown Artist').strip()

    # Title: embedded album tag → dirname-derived clean title → dirname as-is.
    _dn_title = _dn['title']
    title = (mf.album or _dn_title or _dirname).strip()

    # Year: embedded year → first year found in dirname.
    _embedded_year = str(mf.year or '')
    _dirname_year  = _dn['years'][0] if _dn['years'] else ''
    year = _embedded_year or _dirname_year

    album = Album(identifier='0', title=title, artists=[artist])
    album._artist_display = artist
    album.sort_artist = artist
    album.year = year
    album.release_date = year or None
    album.labels = []
    album.catnumbers = []
    album.attachments = []
    album.genres = list(mf.genres or [])
    album.styles = []
    # Derive album.format and format_description from the embedded media tag so
    # that format_code / format_base resolve correctly for the directory name.
    # The media tag written by discogstagger3/mmt is "N x FormatName Desc1, Desc2"
    # e.g. "1 x Vinyl LP, Album, Repress" → format="Vinyl", descs=["LP","Album","Repress"]
    _media_raw = (mf.media or '').strip()
    _m = re.match(r'\d+\s*x\s*(.+)', _media_raw)
    if _m:
        _rest = _m.group(1).strip()
        if _rest.lower().startswith('digital media'):
            album.format = 'Digital Media'
            _desc_raw = _rest[len('digital media'):].strip()
        else:
            _parts = _rest.split(None, 1)
            album.format = _parts[0] if _parts else ''
            _desc_raw = _parts[1] if len(_parts) > 1 else ''
        album.format_description = [d.strip() for d in _desc_raw.split(',') if d.strip()] if _desc_raw else []
    else:
        album.format = ''
        album.format_description = []
    album.country = ''
    album.media = ''
    album.notes = ''
    album.is_compilation = bool(mf.comp)
    album.master_id = None
    album.identifiers = []
    album.barcode = ''
    album.extraartists = []
    album.source = 'existing_tags'

    # ── Read back previously-written tags ─────────────────────────────────────
    # If the files were tagged by a newer run of discogstagger3/mmt these custom
    # tags will be present and let us avoid losing info on re-organisation.
    album.status = getattr(mf, 'discogs_release_status', '') or ''
    _rt = getattr(mf, 'releasetype', '') or ''
    if _rt:
        album.release_type = _rt
        album.release_types = [_rt]
    else:
        album.release_type = ''
        album.release_types = []

    # ── Enrich status and finalise title ─────────────────────────────────────
    # Status: embedded tag → dirname hint.
    if not album.status and _dn['status']:
        album.status = _dn['status']

    # Title: append [Bootleg] / [Promo] when the status is known and not already
    # in the title, so the release character is visible in the directory name.
    if album.status in ('Bootleg', 'Promo'):
        _bracket = f'[{album.status}]'
        if _bracket.lower() not in album.title.lower():
            album.title = album.title + f' {_bracket}'

    disc = Disc(1)
    for i, fname in enumerate(audio_files, start=1):
        fpath = os.path.join(sourcedir, fname)
        try:
            tmf = MediaFile(fpath)
            track_title  = (tmf.title or _clean_fallback_title(fname)).strip()
            track_artist = (tmf.artist or artist).strip()
            track_artists = [track_artist]
        except Exception:
            track_title  = _clean_fallback_title(fname)
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

