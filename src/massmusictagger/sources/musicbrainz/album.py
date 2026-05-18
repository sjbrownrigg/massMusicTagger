"""MusicBrainz → Album/Disc/Track mapper.

Maps a MusicBrainz release dict (as returned by musicbrainzngs) to the shared
Album/Disc/Track domain model used by discogstagger3's tagging engine.

MusicBrainz hierarchy:
  Release
    └── Medium (= physical disc)
          └── Track
                └── Recording (the master audio entity, carries ISRCs)

The mapper flattens this into the Album → Disc → Track model where each
Medium becomes one Disc and each Track stays as a Track.

Album shape alignment
─────────────────────
Every attribute set by DiscogsAlbum.map() is also set here, using the closest
MusicBrainz equivalent.  Source-specific extras (isrc, mbid on Track) are
additive and do not conflict.

  format_description  ← release-group['secondary-types'] (Compilation, Live, …)
  images              ← placeholder pointing at Cover Art Archive; replaced by
                        MBConnector.fetch_image_list() in the cascade after map()
  identifiers         ← [] (MB stores identifiers differently; barcode is direct)
  extraartists        ← [] (MB credits come from relations, not extraartists;
                        future work: map recording/release relations)
  genres / styles     ← [] (MB genre data requires a separate user-tag lookup)
  notes               ← release annotation
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from discogstagger.album import Album, Disc, Track

logger = logging.getLogger(__name__)

_VARIOUS_ARTIST_NAMES = {'various artists', 'various'}
_THE_SUFFIX_RE = re.compile(r"(.*),\s+The$", re.IGNORECASE)


class MusicBrainzAlbum:
    """Maps a raw MusicBrainz release dict to an Album."""

    def __init__(self, release: dict):
        self.release = release

    def map(self) -> Album:
        r = self.release
        mbid = r.get('id', '')

        artists, artist_display = self._map_artist_credit(r.get('artist-credit', []))
        album = Album(mbid, r.get('title', '').strip(), artists)
        album._artist_display = artist_display
        album.sort_artist = artists[0] if artists else ''

        # Label / catalogue number — musicbrainzngs uses 'label-info-list' (XML origin)
        label_info = r.get('label-info-list', [])
        album.labels = self._labels(label_info)
        album.catnumbers = self._catnumbers(label_info)

        # Date / year
        date_str = r.get('date', '') or ''
        album.release_date = self._normalise_date(date_str)
        album.year = date_str[:4] if len(date_str) >= 4 else ''

        album.country = r.get('country', '') or ''
        album.status = r.get('status', '') or ''

        # Release-group gives format and format_description equivalents.
        # primary-type ('Album', 'Single', 'EP', …) → format
        # secondary-types (['Compilation', 'Live', 'Remix', …]) → format_description
        rg = r.get('release-group', {})
        # musicbrainzngs: primary type in 'type' or 'primary-type'; secondary types in 'secondary-type-list'
        album.format = rg.get('primary-type') or rg.get('type', '') or ''
        album.format_description = list(rg.get('secondary-type-list') or [])

        album.genres = []   # MB genre data requires a separate user-tag lookup
        album.styles = []

        album.media = self._media_string(r.get('medium-list', []))
        album.is_compilation = self._is_compilation(r)
        album.master_id = rg.get('id', None)

        # Images: a CAA front placeholder is set here.  The cascade replaces
        # this with the full typed image list from MBConnector.fetch_image_list()
        # immediately after map() returns, so downstream code always sees a
        # complete list.
        album.images = (
            [{'uri': f'https://coverartarchive.org/release/{mbid}/front',
              'type': 'primary', 'caa_types': ['Front'],
              'width': None, 'height': None}]
            if mbid else []
        )

        # Notes from the release annotation — key may vary; absent if no annotation
        album.notes = r.get('annotation', {}).get('text', '') if isinstance(r.get('annotation'), dict) else (r.get('annotation') or '')

        # Identifiers: Discogs stores as a typed list; MB doesn't have an
        # equivalent list at this level.  barcode is available as a direct field.
        album.identifiers = []
        album.barcode = r.get('barcode', '') or ''

        # Extra artist credits (composers, producers, etc.) from release relations.
        # Relations are a richer but more complex structure than Discogs extraartists;
        # mapping them is future work.  Set to empty list for shape consistency.
        album.extraartists = []

        # Build discs — musicbrainzngs uses 'medium-list' (XML origin), not 'media'
        album.discs = self._map_mediums(r.get('medium-list', []), album)
        album.disctotal = len(album.discs)
        album.url = f'https://musicbrainz.org/release/{mbid}'

        return album

    # ── Artist credit ──────────────────────────────────────────────────────

    def _map_artist_credit(self, credits: list) -> tuple[list[str], str]:
        """Return (individual_names, display_string) from an artist-credit list."""
        names: list[str] = []
        display_parts: list[str] = []

        for item in credits:
            if isinstance(item, str):
                # joinphrase between artists (e.g. ' & ', ' feat. ')
                if display_parts:
                    display_parts[-1] = display_parts[-1] + item
                continue
            if not isinstance(item, dict):
                continue
            # 'name' is the credited form (MB's ANV equivalent)
            credited = (item.get('name') or '').strip()
            canonical = (item.get('artist', {}).get('name') or '').strip()
            display = self._normalise_the(credited or canonical)
            names.append(display)
            joinphrase = item.get('joinphrase', '')
            display_parts.append(display + (joinphrase or ''))

        display_str = ''.join(display_parts).strip()
        return names, display_str

    @staticmethod
    def _normalise_the(name: str) -> str:
        """Convert 'Artist, The' → 'The Artist'."""
        return _THE_SUFFIX_RE.sub(r"The \g<1>", name) if name else name

    # ── Labels / catalogue numbers ─────────────────────────────────────────

    @staticmethod
    def _labels(label_info: list) -> list[str]:
        seen: dict = {}
        for li in label_info:
            lbl = (li.get('label') or {}).get('name', '').strip()
            if lbl:
                seen.setdefault(lbl, None)
        return list(seen)

    @staticmethod
    def _catnumbers(label_info: list) -> list[str]:
        seen: dict = {}
        for li in label_info:
            catno = (li.get('catalog-number') or '').strip()
            if catno and catno.lower() != 'none':
                seen.setdefault(catno, None)
        return list(seen)

    # ── Date normalisation ─────────────────────────────────────────────────

    @staticmethod
    def _normalise_date(raw: str) -> Optional[str]:
        """Strip zero-padded zero components. '1995-00-00' → '1995'."""
        if not raw:
            return None
        parts = raw.split('-')
        while parts and parts[-1] in ('00', '0'):
            parts.pop()
        result = '-'.join(parts)
        return result if re.match(r'^\d{4}', result) else None

    # ── Media / format ────────────────────────────────────────────────────

    @staticmethod
    def _media_string(media: list) -> str:
        seen = []
        for m in media:
            fmt = m.get('format', '')
            if fmt and fmt not in seen:
                seen.append(fmt)
        return '; '.join(seen)

    @staticmethod
    def _is_compilation(release: dict) -> bool:
        credits = release.get('artist-credit', [])
        for item in credits:
            if isinstance(item, dict):
                name = (item.get('artist', {}).get('name') or '').lower()
                if name in _VARIOUS_ARTIST_NAMES:
                    return True
        rg = release.get('release-group', {})
        # musicbrainzngs: secondary types in 'secondary-type-list'
        rg_types = rg.get('secondary-type-list') or []
        return 'Compilation' in rg_types

    # ── Mediums → Discs ───────────────────────────────────────────────────

    def _map_mediums(self, media: list, album: Album) -> list[Disc]:
        discs: list[Disc] = []
        for medium in media:
            discno = int(medium.get('position', len(discs) + 1))
            disc = Disc(discno)
            disc.discsubtitle = (medium.get('title') or '').strip() or None
            disc.mediatype = medium.get('format', '')
            # musicbrainzngs returns tracks as 'track-list' within each medium
            tracks = self._map_tracks(medium.get('track-list', []), album, disc)
            disc.tracks = tracks
            discs.append(disc)
        return discs

    def _map_tracks(self, raw_tracks: list, album: Album, disc: Disc) -> list[Track]:
        # musicbrainzngs uses 'track-list' inside each medium, but the tracks
        # passed here are already the list (unwrapped by _map_mediums).
        tracks: list[Track] = []
        for i, rt in enumerate(raw_tracks, start=1):
            title = (rt.get('title') or rt.get('recording', {}).get('title', '')).strip()

            # Per-track artist credit (if different from album)
            tc = rt.get('artist-credit') or []
            if tc:
                t_artists, t_display = self._map_artist_credit(tc)
            else:
                t_artists = album.artists
                t_display = album._artist_display or album.artist

            track = Track(i, title, t_artists)
            track._artist_display = t_display
            track.tracknumber = i
            track.real_tracknumber = rt.get('number', str(i))
            track.discnumber = disc.discnumber
            track.discsubtitle = disc.discsubtitle
            track.mediatype = disc.mediatype   # inherit from medium (shape parity)
            track.sort_artist = t_artists[0] if t_artists else ''
            track.position = i - 1
            track.notes = None                 # set if recording annotation present
            track.extraartists = []            # shape parity with Discogs tracks

            # MB-specific: ISRC and Recording MBID
            # musicbrainzngs: ISRCs in 'isrc-list' when the 'isrcs' include is used
            recording = rt.get('recording', {})
            isrcs = recording.get('isrc-list', [])
            if isrcs:
                track.isrc = isrcs[0]
            track.mbid = recording.get('id', '')

            tracks.append(track)
        return tracks
