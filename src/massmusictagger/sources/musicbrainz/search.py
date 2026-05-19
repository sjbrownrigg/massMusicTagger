"""MusicBrainz release search.

Seven-tier strategy (most-certain to least-certain):

  Tier 1  — id.txt containing an MBID (mbid= key)
  Tier 2  — Existing musicbrainz_releaseid tag in audio files
  Tier 3  — Text search (artist + album title + track count)
  Tier 4  — Barcode lookup (from existing tag or id.txt barcode= key)
  Tier 5  — DiscID (CD TOC hash computed from file durations)
  Tier 6  — Single-track AcoustID (optional; requires pyacoustid + fpcalc)
  Tier 7  — Multi-track AcoustID (fingerprints all tracks; most reliable
             fingerprint strategy — finds the release with most matching
             recordings)

Optional dependencies
─────────────────────
  pyacoustid  — tiers 6 & 7 (pip install massmusictagger[acoustid])
  discid — tier 5   (pip install massmusictagger[discid])
"""
from __future__ import annotations

import logging
import os
from typing import Optional, TYPE_CHECKING

import musicbrainzngs
from rapidfuzz import fuzz

from discogstagger.discogs_utils import AUDIO_EXTENSIONS
from discogstagger.mediafile_ext import MediaFile

if TYPE_CHECKING:
    from discogstagger.tagger_config import TaggerConfig

logger = logging.getLogger(__name__)

# Text-search acceptance thresholds
_MIN_TITLE_SCORE = 70
_TRACK_TOLERANCE = 2

# Multi-track AcoustID: minimum proportion of tracks that must match a release
_MULTI_ACOUSTID_MIN_SCORE = 0.85   # per-track confidence threshold
_MULTI_ACOUSTID_COVERAGE  = 0.5    # at least half the tracks must agree


class MBSearch:
    """Searches MusicBrainz for a release given a source directory of audio files."""

    def __init__(self, cfg: 'TaggerConfig'):
        self.cfg = cfg

        # Check optional fingerprinting library availability once at startup
        # so that per-album skip messages are suppressed — the capability check
        # is logged at INFO level here instead of at DEBUG for every album.
        try:
            import discid as _discid_check  # noqa: F401
            self._has_discid = True
        except ImportError:
            self._has_discid = False
            logger.info('MB tier 5 (DiscID) unavailable: discid not installed. '
                        'Install with: pip install massmusictagger[discid]  '
                        '(also requires: apt install libdiscid0)')

        try:
            import acoustid as _acoustid_check  # noqa: F401
            self._has_acoustid = True
        except ImportError:
            self._has_acoustid = False
            logger.info('MB tiers 6 & 7 (AcoustID) unavailable: pyacoustid not installed. '
                        'Install with: pip install massmusictagger[acoustid]  '
                        '(also requires: apt install libchromaprint-tools)')

    def search(self, sourcedir: str) -> Optional[str]:
        """Return a MusicBrainz release MBID, or None."""

        # Count local audio files — used for track count validation.
        # For multi-disc source dirs (CD1/, CD2/ structure) we sum across subdirs.
        meta = _read_directory_metadata(sourcedir)
        local_count = meta.get('track_count', 0)

        # ── Tier 1: MBID in id.txt ─────────────────────────────────────────
        # User-supplied MBIDs are validated: if the track count doesn't match
        # we warn loudly but still trust the user's explicit choice.
        mbid = _read_id_txt(sourcedir, self.cfg, key='mbid')
        if mbid:
            logger.info('MB tier 1: MBID from id.txt: %s', mbid)
            if local_count and not self._tracks_match(mbid, local_count):
                logger.warning(
                    'MB tier 1: id.txt MBID %s track count does not match '
                    'local files (%d) — proceeding anyway (user-supplied)',
                    mbid, local_count,
                )
            return mbid

        # ── Tier 2: Existing musicbrainz_releaseid tag ─────────────────────
        # Validate before trusting: embedded MBIDs may be stale (e.g. tagged
        # by an older tool against a different version of the release).
        # If the track count mismatches, fall through to text search so a
        # better match can be found rather than crashing downstream.
        mbid = self._read_existing_releaseid_tag(sourcedir)
        if mbid:
            if local_count and not self._tracks_match(mbid, local_count):
                logger.info(
                    'MB tier 2: existing tag MBID %s track count does not match '
                    'local files (%d) — tag is stale, falling through to search',
                    mbid, local_count,
                )
                mbid = None   # fall through
            else:
                logger.info('MB tier 2: MBID from existing tag: %s', mbid)
                return mbid

        # ── Read shared directory metadata (artist, album, track count) ────
        meta = _read_directory_metadata(sourcedir)
        audio_files = meta.get('files', [])

        # ── Tier 3: Text search ────────────────────────────────────────────
        mbid = self._text_search(
            meta.get('artist', ''), meta.get('album', ''), meta.get('track_count', 0)
        )
        if mbid:
            return mbid

        # ── Tier 4: Barcode lookup ─────────────────────────────────────────
        mbid = self._barcode_search(sourcedir)
        if mbid:
            return mbid

        # ── Tier 5: DiscID (CD TOC hash from file durations) ──────────────
        mbid = self._discid_search(audio_files)
        if mbid:
            return mbid

        # ── Tier 6: Single-track AcoustID ─────────────────────────────────
        if audio_files:
            mbid = self._acoustid_single(audio_files[0])
            if mbid:
                return mbid

        # ── Tier 7: Multi-track AcoustID ──────────────────────────────────
        if audio_files:
            mbid = self._acoustid_multi(audio_files)
            if mbid:
                return mbid

        logger.info('MB: no match found for %s', sourcedir)
        return None

    # ── Tier 2 ────────────────────────────────────────────────────────────

    @staticmethod
    def _read_existing_releaseid_tag(sourcedir: str) -> Optional[str]:
        """Read musicbrainz_releaseid from the first tagged audio file."""
        try:
            for f in sorted(os.listdir(sourcedir)):
                if f.lower().endswith(AUDIO_EXTENSIONS):
                    mf = MediaFile(os.path.join(sourcedir, f))
                    mbid = getattr(mf, 'musicbrainz_releaseid', None)
                    if mbid:
                        return mbid
                    break
        except Exception:
            pass
        return None

    # ── Tier 3 ────────────────────────────────────────────────────────────

    def _text_search(self, artist: str, album: str, track_count: int) -> Optional[str]:
        if not artist or not album:
            logger.debug('MB tier 3: skipped — missing artist or album')
            return None
        logger.info('MB tier 3: text search — artist=%r album=%r tracks=%d',
                    artist, album, track_count)
        try:
            result = musicbrainzngs.search_releases(
                artist=artist, release=album, limit=10,
            )
        except Exception as exc:
            logger.warning('MB API search failed: %s', exc)
            return None

        # Ranking tuple: (title_score, artist_score, has_date).
        # Artist score prevents wrong matches when multiple albums share a title
        # (e.g. several "The Remixes" albums by different artists with the same
        # track count).  has_date breaks further ties in favour of documented releases.
        best_mbid: Optional[str] = None
        best_rank = (-1, -1, 0)   # (title_score, artist_score, has_date)

        for rel in result.get('release-list', []):
            candidate_title = rel.get('title', '')
            title_score = fuzz.token_sort_ratio(album.lower(), candidate_title.lower())
            if title_score < _MIN_TITLE_SCORE:
                continue
            if track_count:
                candidate_tracks = sum(
                    int(m.get('track-count', 0))
                    for m in rel.get('medium-list', [])
                )
                if abs(candidate_tracks - track_count) > _TRACK_TOLERANCE:
                    logger.debug('MB tier 3: skipping %r — track count %d vs %d',
                                 candidate_title, candidate_tracks, track_count)
                    continue
            # Artist similarity: score the candidate's credited artist against
            # our search artist.  Zero when no search artist is provided.
            candidate_artist = (rel.get('artist-credit-phrase') or '').strip()
            artist_score = (
                fuzz.token_sort_ratio(artist.lower(), candidate_artist.lower())
                if artist and candidate_artist else 0
            )
            has_date = 1 if rel.get('date', '') else 0
            rank = (title_score, artist_score, has_date)
            if rank > best_rank:
                best_rank = rank
                best_mbid = rel.get('id')

        if best_mbid:
            t_score, a_score, has_date = best_rank
            logger.info('MB tier 3: matched %s (title=%d artist=%d%s)',
                        best_mbid, t_score, a_score,
                        '' if has_date else ', no date')
        else:
            logger.info('MB tier 3: no confident text match')
        return best_mbid

    # ── Tier 4: Barcode ───────────────────────────────────────────────────

    def _barcode_search(self, sourcedir: str) -> Optional[str]:
        """Tier 4: Look up a release by its barcode (EAN/UPC).

        Reads the barcode from (in priority order):
          1. The 'barcode=' key in id.txt
          2. The 'barcode' tag already embedded in the first audio file
        """
        barcode = (
            _read_id_txt(sourcedir, self.cfg, key='barcode')
            or self._read_barcode_tag(sourcedir)
        )
        if not barcode:
            logger.debug('MB tier 4: no barcode available')
            return None

        barcode_clean = barcode.replace(' ', '').replace('-', '')
        logger.info('MB tier 4: barcode search — %s', barcode_clean)
        try:
            result = musicbrainzngs.search_releases(barcode=barcode_clean, limit=5)
        except Exception as exc:
            logger.warning('MB barcode search failed: %s', exc)
            return None

        releases = result.get('release-list', [])
        if releases:
            mbid = releases[0].get('id')
            logger.info('MB tier 4: barcode matched release %s', mbid)
            return mbid

        logger.info('MB tier 4: barcode %s not found in MusicBrainz', barcode_clean)
        return None

    @staticmethod
    def _read_barcode_tag(sourcedir: str) -> Optional[str]:
        try:
            for f in sorted(os.listdir(sourcedir)):
                if f.lower().endswith(AUDIO_EXTENSIONS):
                    mf = MediaFile(os.path.join(sourcedir, f))
                    return getattr(mf, 'barcode', None) or None
        except Exception:
            pass
        return None

    # ── Tier 5: DiscID ────────────────────────────────────────────────────

    def _discid_search(self, audio_files: list[str]) -> Optional[str]:
        """Tier 5: Construct a MusicBrainz DiscID from audio file durations
        and look it up.

        A DiscID is a SHA-1 hash of the disc's Table of Contents (track count,
        first/last track numbers, and sector offsets).  This approach is only
        reliable for **exact CD rips** where file durations match the original
        CD sectors precisely.  For re-encodes or vinyl rips the hash will not
        match any database entry.

        Requires: discid  (pip install massmusictagger[discid])
        System library: libdiscid  (apt install libdiscid0)
        """
        if not self._has_discid:
            return None
        try:
            import discid as discid_lib
        except ImportError:
            return None

        if not audio_files:
            return None

        SECTORS_PER_SEC = 75   # CD standard: 75 sectors per second
        LEAD_IN_SECTORS = 150  # CD standard 2-second lead-in

        # Read track durations from MediaFile
        durations: list[float] = []
        try:
            for fpath in audio_files:
                mf = MediaFile(fpath)
                dur = mf.length   # float seconds
                if not dur:
                    logger.debug('MB tier 5: missing duration for %s — aborting DiscID', fpath)
                    return None
                durations.append(dur)
        except Exception as exc:
            logger.debug('MB tier 5: duration read failed: %s', exc)
            return None

        # Build track offsets (sectors from disc start)
        offsets: list[int] = []
        cumulative = LEAD_IN_SECTORS
        for dur in durations:
            offsets.append(cumulative)
            cumulative += round(dur * SECTORS_PER_SEC)
        total_sectors = cumulative

        try:
            disc = discid_lib.put(
                first=1,
                last=len(durations),
                sectors=total_sectors,
                offsets=offsets,
            )
            disc_id_str = disc.id
        except Exception as exc:
            logger.debug('MB tier 5: DiscID construction failed: %s', exc)
            return None

        logger.info('MB tier 5: DiscID lookup — %s (%d tracks)', disc_id_str, len(durations))
        try:
            result = musicbrainzngs.get_releases_by_discid(
                disc_id_str, includes=['artists', 'labels', 'recordings']
            )
            # Result structure depends on whether there's an exact match or
            # fuzzy (TOC) matches.
            disc_data = result.get('disc', {})
            releases = disc_data.get('release-list', [])
            if not releases:
                releases = result.get('release-list', [])
            if releases:
                mbid = releases[0].get('id')
                logger.info('MB tier 5: DiscID matched release %s', mbid)
                return mbid
        except musicbrainzngs.ResponseError:
            logger.debug('MB tier 5: DiscID %s not in MusicBrainz database', disc_id_str)
        except Exception as exc:
            logger.warning('MB tier 5: DiscID lookup failed: %s', exc)

        return None

    # ── Tier 6: Single-track AcoustID ─────────────────────────────────────

    def _acoustid_single(self, audio_path: str) -> Optional[str]:
        """Tier 6: Fingerprint the first track and look up via AcoustID.

        Requires: pyacoustid  (pip install massmusictagger[acoustid])
        System dependency: fpcalc (chromaprint package)
        """
        if not self._has_acoustid:
            return None
        api_key = self._acoustid_api_key()
        if not api_key:
            return None
        import acoustid
        logger.info('MB tier 6: single-track AcoustID — %s', os.path.basename(audio_path))
        try:
            results = list(acoustid.match(api_key, audio_path))
        except Exception as exc:
            logger.warning('MB tier 6: AcoustID failed: %s', exc)
            return None

        results.sort(key=lambda r: r[0], reverse=True)
        for score, recording_id, *_ in results:
            if score < _MULTI_ACOUSTID_MIN_SCORE:
                break
            mbid = _recording_to_release(recording_id)
            if mbid:
                logger.info('MB tier 6: AcoustID matched release %s (score %.2f)', mbid, score)
                return mbid
        return None

    # ── Tier 7: Multi-track AcoustID ──────────────────────────────────────

    def _acoustid_multi(self, audio_files: list[str]) -> Optional[str]:
        """Tier 7: Fingerprint every track, then find the Release that contains
        the most matching Recordings.

        Strategy:
          1. Fingerprint each file → AcoustID lookup → Recording MBID (if
             confidence ≥ threshold).
          2. For each Recording MBID, fetch the containing Releases.
          3. The Release that appears most frequently (across all tracks) wins,
             provided it accounts for at least half the total tracks.

        This is the most reliable fingerprint strategy because it requires
        many independent tracks to agree on a single release, making false
        positives extremely unlikely.

        Requires: pyacoustid  (pip install massmusictagger[acoustid])
        System dependency: fpcalc (chromaprint package)
        """
        if not self._has_acoustid:
            return None
        api_key = self._acoustid_api_key()
        if not api_key:
            return None
        import acoustid
        logger.info('MB tier 7: multi-track AcoustID — %d file(s)', len(audio_files))

        # Step 1: fingerprint → Recording MBID for each file
        recording_ids: list[str] = []
        for fpath in audio_files:
            try:
                results = list(acoustid.match(api_key, fpath))
                results.sort(key=lambda r: r[0], reverse=True)
                for score, rec_id, *_ in results:
                    if score >= _MULTI_ACOUSTID_MIN_SCORE:
                        recording_ids.append(rec_id)
                    break  # only the best result per file
            except Exception as exc:
                logger.debug('MB tier 7: AcoustID failed for %s: %s',
                             os.path.basename(fpath), exc)

        if not recording_ids:
            logger.info('MB tier 7: no AcoustID matches above threshold')
            return None

        logger.debug('MB tier 7: %d/%d tracks fingerprinted successfully',
                     len(recording_ids), len(audio_files))

        # Step 2: Recording MBIDs → Release MBID vote tally
        release_votes: dict[str, int] = {}
        for rec_id in recording_ids:
            try:
                result = musicbrainzngs.get_recording_by_id(rec_id, includes=['releases'])
                for rel in result.get('recording', {}).get('release-list', []):
                    rel_id = rel.get('id')
                    if rel_id:
                        release_votes[rel_id] = release_votes.get(rel_id, 0) + 1
            except Exception as exc:
                logger.debug('MB tier 7: recording lookup failed for %s: %s', rec_id, exc)

        if not release_votes:
            return None

        # Step 3: pick the winner if it meets the coverage threshold.
        # Threshold is based on total files attempted, not just those that were
        # successfully fingerprinted, so that a single match out of many files
        # does not pass if most could not be identified.
        best_mbid = max(release_votes, key=release_votes.__getitem__)
        best_votes = release_votes[best_mbid]
        threshold = max(1, round(len(audio_files) * _MULTI_ACOUSTID_COVERAGE))

        if best_votes >= threshold:
            logger.info('MB tier 7: multi-track AcoustID matched release %s '
                        '(%d/%d tracks)', best_mbid, best_votes, len(recording_ids))
            return best_mbid

        logger.info('MB tier 7: best candidate %s matched only %d/%d tracks '
                    '(need %d) — rejected', best_mbid, best_votes,
                    len(recording_ids), threshold)
        return None

    # ── Helpers ───────────────────────────────────────────────────────────

    def _tracks_match(self, mbid: str, local_count: int) -> bool:
        """Return True if the MB release track count matches the local file count.

        Fetches the release with only 'media' included (lightweight — usually
        cached from a previous fetch).  Returns True on any API error so the
        caller can still proceed rather than silently skipping the MBID.
        """
        try:
            result = musicbrainzngs.get_release_by_id(mbid, includes=['media'])
            medium_list = result['release'].get('medium-list', [])
            mb_count = sum(int(m.get('track-count', 0)) for m in medium_list)
            if mb_count != local_count:
                logger.debug('MB %s: %d track(s) vs %d local file(s)',
                             mbid, mb_count, local_count)
                return False
            return True
        except Exception as exc:
            logger.debug('MB track-count validation failed for %s: %s', mbid, exc)
            return True   # fail open: trust the MBID rather than silently dropping it

    def _acoustid_api_key(self) -> Optional[str]:
        try:
            key = self.cfg.get('musicbrainz', 'acoustid_api_key')
            if key:
                return key
        except Exception:
            pass
        logger.debug('AcoustID search skipped: acoustid_api_key not configured')
        return None


# ── Module-level helpers ──────────────────────────────────────────────────────

def _read_id_txt(sourcedir: str, cfg, key: str = None) -> Optional[str]:
    """Read a release ID from the id.txt file in sourcedir."""
    id_file = (cfg.get('batch', 'id_file')
               if cfg.has_option('batch', 'id_file') else 'id.txt')
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


def _read_directory_metadata(sourcedir: str) -> dict:
    """Read artist/album/file list from the directory.

    For multi-disc album roots (e.g. Liberty/ containing CD1/ and CD2/),
    no audio files exist directly in sourcedir.  In that case we descend
    one level into disc subdirectories, aggregate the total track count,
    and read metadata from the first file found.

    Artist preference order:
      1. albumartist tag — most reliable for compilations with track artists
      2. artist tag — fallback when albumartist is absent
      3. Parent directory name — used when both tags are absent or look
         like a track-specific credit (common for rips without albumartist)
    """
    import re

    audio_files = sorted(
        os.path.join(sourcedir, f) for f in os.listdir(sourcedir)
        if f.lower().endswith(AUDIO_EXTENSIONS)
        and os.path.isfile(os.path.join(sourcedir, f))
    )

    if not audio_files:
        # Multi-disc layout: audio is in subdirectories (CD1/, CD2/, ...)
        try:
            subdirs = sorted(
                d for d in os.listdir(sourcedir)
                if os.path.isdir(os.path.join(sourcedir, d))
                and not d.startswith('.')
            )
        except OSError:
            return {}
        all_files: list[str] = []
        for sub in subdirs:
            sub_path = os.path.join(sourcedir, sub)
            sub_audio = sorted(
                os.path.join(sub_path, f) for f in os.listdir(sub_path)
                if f.lower().endswith(AUDIO_EXTENSIONS)
                and os.path.isfile(os.path.join(sub_path, f))
            )
            all_files.extend(sub_audio)
        audio_files = all_files

    if not audio_files:
        return {}

    track_count = len(audio_files)
    try:
        mf = MediaFile(audio_files[0])
    except Exception:
        return {'files': audio_files, 'track_count': track_count}

    # Prefer albumartist — essential for compilations where track artist ≠ album artist.
    artist = (mf.albumartist or '').strip()
    if not artist:
        artist = (mf.artist or '').strip()

    # Fallback: when no usable artist tag exists, use the parent directory name.
    # Music libraries are commonly organised as Artist/Album/, so the parent
    # often contains the correct album artist even when tags are missing.
    if not artist:
        parent_name = os.path.basename(os.path.dirname(os.path.abspath(sourcedir)))
        # Strip leading year and separators: '2010 - The Remixes' → 'The Remixes'
        # but 'Deadmau5' stays as 'Deadmau5'
        parent_clean = re.sub(r'^\d{4}\s*[-–]\s*', '', parent_name).strip()
        if len(parent_clean) > 2 and parent_clean.lower() not in ('music', 'incoming', 'albums', 'artists'):
            artist = parent_clean
            logger.debug('No albumartist/artist tag — using parent dir as artist hint: %r', artist)

    return {
        'files':       audio_files,
        'track_count': track_count,
        'artist':      artist,
        'album':       (mf.album or '').strip(),
    }


def _recording_to_release(recording_id: str) -> Optional[str]:
    """Return the first Release MBID containing the given MB Recording."""
    try:
        result = musicbrainzngs.get_recording_by_id(
            recording_id, includes=['releases']
        )
        releases = result.get('recording', {}).get('release-list', [])
        if releases:
            return releases[0].get('id')
    except Exception as exc:
        logger.debug('MB recording lookup failed for %s: %s', recording_id, exc)
    return None
