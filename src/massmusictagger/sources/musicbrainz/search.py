"""MusicBrainz release search.

Four-tier strategy (mirrors discogstagger3's DiscogsSearch):

  Tier 1 — id.txt / existing musicbrainz_releaseid tag  → direct MBID
  Tier 2 — Text search (artist + album title + track count) via MB API
  Tier 3 — AcoustID fingerprint (optional; requires pyacoustid + fpcalc)
"""
from __future__ import annotations

import logging
import os
from typing import Optional, TYPE_CHECKING

import musicbrainzngs
from rapidfuzz import fuzz

from discogstagger.discogs_utils import AUDIO_EXTENSIONS

if TYPE_CHECKING:
    from discogstagger.tagger_config import TaggerConfig

logger = logging.getLogger(__name__)

# Minimum fuzzy-title similarity to accept a MB search result (0–100)
_MIN_TITLE_SCORE = 70
# Track count must be within this tolerance to accept a match
_TRACK_TOLERANCE = 2


class MBSearch:
    """Searches MusicBrainz for a release given a source directory of audio files."""

    def __init__(self, cfg: 'TaggerConfig'):
        self.cfg = cfg
        self._tracklength_tolerance = int(
            cfg.get('details', 'tracklength_tolerance')
            if cfg.has_option('details', 'tracklength_tolerance') else 3
        )

    def search(self, sourcedir: str) -> Optional[str]:
        """Return a MusicBrainz release MBID, or None."""

        # ── Tier 1: id.txt with mbid= key ─────────────────────────────────
        mbid = self._read_mbid_file(sourcedir)
        if mbid:
            logger.info('MB tier 1: MBID from id.txt: %s', mbid)
            return mbid

        # ── Tier 1b: existing tag ─────────────────────────────────────────
        mbid = self._read_existing_tag(sourcedir)
        if mbid:
            logger.info('MB tier 1b: MBID from existing tag: %s', mbid)
            return mbid

        # ── Prepare metadata from audio files ─────────────────────────────
        metadata = self._read_directory_metadata(sourcedir)
        if not metadata:
            logger.warning('MB search: no readable audio files in %s', sourcedir)
            return None

        artist = metadata.get('artist', '')
        album  = metadata.get('album', '')
        tracks = metadata.get('track_count', 0)

        # ── Tier 2: Text search ────────────────────────────────────────────
        mbid = self._text_search(artist, album, tracks)
        if mbid:
            return mbid

        # ── Tier 3: AcoustID fingerprint ──────────────────────────────────
        mbid = self._acoustid_search(sourcedir)
        if mbid:
            return mbid

        logger.info('MB: no match found for %s', sourcedir)
        return None

    # ── Tier helpers ───────────────────────────────────────────────────────

    def _read_mbid_file(self, sourcedir: str) -> Optional[str]:
        id_file = self.cfg.get('batch', 'id_file') or 'id.txt'
        path = os.path.join(sourcedir, id_file)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                k, _, v = line.partition('=')
                if k.strip().lower() == 'mbid':
                    return v.strip() or None
        return None

    @staticmethod
    def _read_existing_tag(sourcedir: str) -> Optional[str]:
        """Read musicbrainz_releaseid from the first tagged audio file."""
        try:
            from discogstagger.mediafile_ext import MediaFile
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

    @staticmethod
    def _read_directory_metadata(sourcedir: str) -> dict:
        """Read artist/album/track-count from existing audio file tags."""
        try:
            from discogstagger.mediafile_ext import MediaFile
        except ImportError:
            return {}
        files = sorted(
            f for f in os.listdir(sourcedir)
            if f.lower().endswith(AUDIO_EXTENSIONS)
        )
        if not files:
            return {}
        track_count = len(files)
        mf = None
        try:
            mf = MediaFile(os.path.join(sourcedir, files[0]))
        except Exception:
            return {'track_count': track_count}
        return {
            'artist': (mf.albumartist or mf.artist or '').strip(),
            'album':  (mf.album or '').strip(),
            'track_count': track_count,
        }

    def _text_search(self, artist: str, album: str, track_count: int) -> Optional[str]:
        if not artist or not album:
            logger.debug('MB text search: insufficient metadata (artist=%r album=%r)', artist, album)
            return None
        logger.info('MB tier 2: text search — artist=%r album=%r tracks=%d', artist, album, track_count)
        try:
            result = musicbrainzngs.search_releases(
                artist=artist,
                release=album,
                limit=10,
            )
        except Exception as exc:
            logger.warning('MB API search failed: %s', exc)
            return None

        releases = result.get('release-list', [])
        best_mbid: Optional[str] = None
        best_score = 0

        for rel in releases:
            candidate_title = rel.get('title', '')
            score = fuzz.token_sort_ratio(album.lower(), candidate_title.lower())
            if score < _MIN_TITLE_SCORE:
                continue
            # Track count check
            medium_list = rel.get('medium-list', [])
            candidate_tracks = sum(
                int(m.get('track-count', 0)) for m in medium_list
            )
            if track_count and abs(candidate_tracks - track_count) > _TRACK_TOLERANCE:
                logger.debug('MB: skipping %r — track count %d vs %d',
                             candidate_title, candidate_tracks, track_count)
                continue
            if score > best_score:
                best_score = score
                best_mbid = rel.get('id')

        if best_mbid:
            logger.info('MB tier 2: matched MBID %s (score %d)', best_mbid, best_score)
        else:
            logger.info('MB tier 2: no confident match')
        return best_mbid

    def _acoustid_search(self, sourcedir: str) -> Optional[str]:
        """Tier 3: AcoustID fingerprint → MusicBrainz recording → release."""
        try:
            import acoustid
        except ImportError:
            return None

        api_key = (self.cfg.get('musicbrainz', 'acoustid_api_key')
                   if self.cfg.has_option('musicbrainz', 'acoustid_api_key') else None)
        if not api_key:
            logger.debug('AcoustID search skipped: no api_key configured')
            return None

        files = sorted(
            os.path.join(sourcedir, f) for f in os.listdir(sourcedir)
            if f.lower().endswith(AUDIO_EXTENSIONS)
        )
        if not files:
            return None

        logger.info('MB tier 3: AcoustID fingerprint for %s', files[0])
        try:
            results = list(acoustid.match(api_key, files[0]))
        except Exception as exc:
            logger.warning('AcoustID fingerprint failed: %s', exc)
            return None

        # Each result: (score, recording_id, title, artist)
        results.sort(key=lambda r: r[0], reverse=True)
        for score, recording_id, title, _artist in results:
            if score < 0.8:
                break
            logger.info('AcoustID: recording %s (score %.2f, title=%r)', recording_id, score, title)
            mbid = self._recording_to_release(recording_id)
            if mbid:
                logger.info('MB tier 3: matched release %s via AcoustID', mbid)
                return mbid
        return None

    @staticmethod
    def _recording_to_release(recording_id: str) -> Optional[str]:
        """Find the first release that contains the given MB recording."""
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
