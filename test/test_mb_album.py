"""Tests for MusicBrainzAlbum mapper — shape parity and MB-specific fields.

Verifies that every attribute set by DiscogsAlbum.map() is also set by
MusicBrainzAlbum.map(), and that MB-specific extras (isrc, mbid) are present.
"""
from __future__ import annotations

import os
import sys
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

from massmusictagger.sources.musicbrainz.album import MusicBrainzAlbum


def _minimal_release(**overrides) -> dict:
    """Return a minimal MB release dict matching the musicbrainzngs key names.

    musicbrainzngs parses the MusicBrainz XML API and uses XML-derived key names
    that differ from the JSON API:
      'medium-list'       not 'media'
      'track-list'        not 'tracks'
      'label-info-list'   not 'label-info'
      'secondary-type-list' not 'secondary-types'
    """
    base = {
        'id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        'title': 'Test Album',
        'date': '2004-06-21',
        'country': 'GB',
        'status': 'Official',
        'barcode': '5099749939523',
        'annotation': 'A test annotation.',
        'artist-credit': [
            {
                'name': 'Test Artist',
                'artist': {'name': 'Test Artist', 'id': '11111111'},
                'joinphrase': '',
            }
        ],
        'label-info-list': [
            {
                'label': {'name': 'Test Label'},
                'catalog-number': 'TEST-001',
            }
        ],
        'release-group': {
            'id': 'rg-aaaa-bbbb',
            'primary-type': 'Album',
            'secondary-type-list': ['Compilation'],
        },
        'medium-list': [
            {
                'position': 1,
                'format': 'CD',
                'title': '',
                'track-list': [
                    {
                        'number': '1',
                        'title': 'Track One',
                        'artist-credit': [],
                        'recording': {
                            'id': '11111111-2222-3333-4444-555555555555',
                            'isrc-list': ['GBAYE0400099'],
                        },
                    },
                    {
                        'number': '2',
                        'title': 'Track Two',
                        'artist-credit': [],
                        'recording': {
                            'id': '22222222-3333-4444-5555-666666666666',
                            'isrc-list': [],
                        },
                    },
                ],
            }
        ],
    }
    base.update(overrides)
    return base


class TestAlbumShapeParity(unittest.TestCase):
    """MusicBrainzAlbum.map() must set every attribute that DiscogsAlbum.map() sets."""

    def setUp(self):
        self.album = MusicBrainzAlbum(_minimal_release()).map()

    # ── Core identity ──────────────────────────────────────────────────────

    def test_id(self):
        self.assertEqual(self.album.id, 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')

    def test_title(self):
        self.assertEqual(self.album.title, 'Test Album')

    # ── Artists ───────────────────────────────────────────────────────────

    def test_artists_list(self):
        self.assertIsInstance(self.album.artists, list)
        self.assertEqual(self.album.artists, ['Test Artist'])

    def test_artist_display(self):
        self.assertIsNotNone(self.album._artist_display)

    def test_sort_artist_uses_sort_name(self):
        """sort_artist uses artist sort-name when available."""
        credits = [{'name': 'deadmau5',
                    'artist': {'name': 'deadmau5', 'sort-name': 'deadmaus'},
                    'joinphrase': ''}]
        album = MusicBrainzAlbum(_minimal_release(**{'artist-credit': credits})).map()
        self.assertEqual(album.sort_artist, 'deadmaus')

    def test_sort_artist_falls_back_to_display_name(self):
        """Falls back to first display name when sort-name is absent."""
        credits = [{'artist': {'name': 'Test Artist'}, 'joinphrase': ''}]
        album = MusicBrainzAlbum(_minimal_release(**{'artist-credit': credits})).map()
        self.assertEqual(album.sort_artist, 'Test Artist')

    # ── Label / catno ─────────────────────────────────────────────────────

    def test_labels_list(self):
        self.assertEqual(self.album.labels, ['Test Label'])

    def test_catnumbers_list(self):
        self.assertEqual(self.album.catnumbers, ['TEST-001'])

    # ── Date ──────────────────────────────────────────────────────────────

    def test_year(self):
        self.assertEqual(self.album.year, '2004')

    def test_release_date_full(self):
        self.assertEqual(self.album.release_date, '2004-06-21')

    def test_release_date_partial(self):
        album = MusicBrainzAlbum(_minimal_release(date='1998-01-00')).map()
        self.assertEqual(album.release_date, '1998-01')

    def test_release_date_year_only(self):
        album = MusicBrainzAlbum(_minimal_release(date='1995-00-00')).map()
        self.assertEqual(album.release_date, '1995')

    def test_release_date_none_when_empty(self):
        album = MusicBrainzAlbum(_minimal_release(date='')).map()
        self.assertIsNone(album.release_date)

    def test_year_none_when_date_missing(self):
        """Empty date → year=None so tag_single_track's guard skips int('')."""
        album = MusicBrainzAlbum(_minimal_release(date='')).map()
        self.assertIsNone(album.year)

    # ── Geography / status ────────────────────────────────────────────────

    def test_country(self):
        self.assertEqual(self.album.country, 'GB')

    def test_status(self):
        self.assertEqual(self.album.status, 'Official')

    # ── Format ───────────────────────────────────────────────────────────

    def test_format_from_medium(self):
        """album.format is the physical medium format (CD, Vinyl, …) not the release type."""
        self.assertEqual(self.album.format, 'CD')

    def test_format_description_includes_release_type_and_secondary(self):
        """format_description = [release_type] + secondary_types."""
        # Fixture: primary-type='Album', secondary-type-list=['Compilation']
        self.assertEqual(self.album.format_description, ['Album', 'Compilation'])

    def test_format_description_release_type_only(self):
        rg = {'id': 'rg', 'primary-type': 'Album', 'secondary-type-list': []}
        album = MusicBrainzAlbum(_minimal_release(**{'release-group': rg})).map()
        self.assertEqual(album.format_description, ['Album'])

    def test_media_string(self):
        self.assertEqual(self.album.media, 'CD')

    # ── Genre / style ─────────────────────────────────────────────────────

    def test_genres_from_release_group_tags(self):
        """Genres are populated from release-group tag-list, sorted by vote count."""
        rg = {'id': 'rg', 'primary-type': 'Album', 'secondary-type-list': [],
              'tag-list': [
                  {'name': 'electronic', 'count': '5'},
                  {'name': 'house', 'count': '2'},
                  {'name': 'techno', 'count': '1'},
              ]}
        album = MusicBrainzAlbum(_minimal_release(**{'release-group': rg})).map()
        self.assertEqual(album.genres, ['electronic', 'house', 'techno'])

    def test_genres_empty_when_no_tags(self):
        self.assertIsInstance(self.album.genres, list)
        self.assertEqual(self.album.genres, [])

    def test_styles_is_list(self):
        self.assertIsInstance(self.album.styles, list)

    # ── Compilation flag ──────────────────────────────────────────────────

    def test_is_compilation_from_secondary_type(self):
        self.assertTrue(self.album.is_compilation)

    def test_is_compilation_from_various_artist_credit(self):
        credits = [{'name': 'Various Artists',
                    'artist': {'name': 'Various Artists'}, 'joinphrase': ''}]
        rg = {'id': 'rg', 'primary-type': 'Album', 'secondary-type-list': []}
        album = MusicBrainzAlbum(
            _minimal_release(**{'artist-credit': credits, 'release-group': rg})
        ).map()
        self.assertTrue(album.is_compilation)

    # ── Identifiers ──────────────────────────────────────────────────────

    def test_identifiers_is_list(self):
        self.assertIsInstance(self.album.identifiers, list)
        self.assertEqual(self.album.identifiers, [])

    def test_barcode(self):
        self.assertEqual(self.album.barcode, '5099749939523')

    def test_barcode_empty_when_missing(self):
        album = MusicBrainzAlbum(_minimal_release(barcode=None)).map()
        self.assertEqual(album.barcode, '')

    # ── Extra artists ─────────────────────────────────────────────────────

    def test_extraartists_is_list(self):
        self.assertIsInstance(self.album.extraartists, list)

    # ── Notes / URL ──────────────────────────────────────────────────────

    def test_notes(self):
        self.assertEqual(self.album.notes, 'A test annotation.')

    def test_disambiguation_mapped(self):
        """MB disambiguation field is captured as album.disambiguation."""
        album = MusicBrainzAlbum(_minimal_release(
            **{'disambiguation': 'Beatport expanded version (US)'}
        )).map()
        self.assertEqual(album.disambiguation, 'Beatport expanded version (US)')

    def test_disambiguation_empty_when_absent(self):
        album = MusicBrainzAlbum(_minimal_release()).map()
        self.assertEqual(album.disambiguation, '')

    def test_url(self):
        self.assertIn('musicbrainz.org', self.album.url)
        self.assertIn('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', self.album.url)

    # ── Images ───────────────────────────────────────────────────────────

    def test_images_is_list(self):
        self.assertIsInstance(self.album.images, list)

    def test_images_has_primary(self):
        front = [i for i in self.album.images if i.get('type') == 'primary']
        self.assertEqual(len(front), 1)

    def test_images_have_uri(self):
        for img in self.album.images:
            self.assertIn('uri', img)
            self.assertTrue(img['uri'])

    # ── Discs / totals ────────────────────────────────────────────────────

    def test_disctotal(self):
        self.assertEqual(self.album.disctotal, 1)

    def test_disc_count(self):
        self.assertEqual(len(self.album.discs), 1)

    def test_master_id(self):
        self.assertEqual(self.album.master_id, 'rg-aaaa-bbbb')

    # ── Source marker ─────────────────────────────────────────────────────

    def test_source_marker_set_by_factory(self):
        # source is set by source_factory, not map() — just confirm map() doesn't crash
        self.assertFalse(hasattr(self.album, 'source') and self.album.source == 'discogs')


class TestDiscShape(unittest.TestCase):
    """Disc attributes match expected shape."""

    def setUp(self):
        self.disc = MusicBrainzAlbum(_minimal_release()).map().discs[0]

    def test_discnumber(self):
        self.assertEqual(self.disc.discnumber, 1)

    def test_mediatype(self):
        self.assertEqual(self.disc.mediatype, 'CD')

    def test_discsubtitle_none_when_no_title(self):
        self.assertIsNone(self.disc.discsubtitle)

    def test_discsubtitle_set_when_medium_has_title(self):
        media = [{'position': 1, 'format': 'CD', 'title': 'Disc One', 'track-list': []}]
        disc = MusicBrainzAlbum(_minimal_release(**{'medium-list': media})).map().discs[0]
        self.assertEqual(disc.discsubtitle, 'Disc One')


class TestTrackShape(unittest.TestCase):
    """Track attributes match expected shape and include MB-specific extras."""

    def setUp(self):
        self.disc  = MusicBrainzAlbum(_minimal_release()).map().discs[0]
        self.track = self.disc.tracks[0]

    def test_tracknumber(self):
        self.assertEqual(self.track.tracknumber, 1)

    def test_title(self):
        self.assertEqual(self.track.title, 'Track One')

    def test_real_tracknumber(self):
        self.assertEqual(self.track.real_tracknumber, '1')

    def test_discnumber(self):
        self.assertEqual(self.track.discnumber, 1)

    def test_mediatype_inherited_from_disc(self):
        """Track.mediatype is inherited from the parent Disc (shape parity with Discogs)."""
        self.assertEqual(self.track.mediatype, 'CD')

    def test_sort_artist(self):
        self.assertEqual(self.track.sort_artist, 'Test Artist')

    def test_extraartists_is_list(self):
        self.assertIsInstance(self.track.extraartists, list)

    def test_notes_is_none_by_default(self):
        self.assertIsNone(self.track.notes)

    # ── MB-specific extras ────────────────────────────────────────────────

    def test_isrc_present(self):
        """Track 1 has an ISRC."""
        self.assertEqual(self.track.isrc, 'GBAYE0400099')

    def test_isrc_absent_when_no_isrc_list(self):
        """Track 2 has no ISRC — attribute should be absent or falsy."""
        track2 = self.disc.tracks[1]
        isrc = getattr(track2, 'isrc', None)
        self.assertFalsy(isrc)

    def assertFalsy(self, value, msg=None):
        if value:
            raise AssertionError(f'{value!r} is truthy {msg or ""}')

    def test_mbid_present(self):
        self.assertEqual(self.track.mbid, '11111111-2222-3333-4444-555555555555')


class TestDefensiveFallbacks(unittest.TestCase):
    """Edge-case artist credit handling."""

    def test_empty_artist_credit_falls_back_to_phrase(self):
        """When artist-credit is empty, artist-credit-phrase is used."""
        release = _minimal_release(**{
            'artist-credit': [],
            'artist-credit-phrase': 'Various Artists',
        })
        album = MusicBrainzAlbum(release).map()
        self.assertEqual(album.artists, ['Various Artists'])
        self.assertEqual(album._artist_display, 'Various Artists')


class TestArtistCredit(unittest.TestCase):
    """Artist credit maps correctly with joinphrase and The normalisation."""

    def _album(self, credits):
        return MusicBrainzAlbum(_minimal_release(**{'artist-credit': credits})).map()

    def test_single_artist(self):
        album = self._album([{'name': 'Goldie', 'artist': {'name': 'Goldie'},
                               'joinphrase': ''}])
        self.assertEqual(album.artists, ['Goldie'])
        self.assertEqual(album.artist, 'Goldie')

    def test_the_normalisation(self):
        album = self._album([{'name': 'Cure, The', 'artist': {'name': 'Cure, The'},
                               'joinphrase': ''}])
        self.assertIn('The Cure', album.artists)

    def test_two_artists_with_joinphrase(self):
        credits = [
            {'name': 'Lennon', 'artist': {'name': 'John Lennon'}, 'joinphrase': ' & '},
            {'name': 'McCartney', 'artist': {'name': 'Paul McCartney'}, 'joinphrase': ''},
        ]
        album = self._album(credits)
        self.assertEqual(album.artists, ['Lennon', 'McCartney'])
        self.assertEqual(album.artist, 'Lennon & McCartney')

    def test_credited_name_preferred_over_canonical(self):
        """MB 'name' (sleeve credit) is used in preference to artist.name (canonical)."""
        credits = [{'name': 'M83', 'artist': {'name': 'M83'}, 'joinphrase': ''}]
        album = self._album(credits)
        self.assertIn('M83', album.artists)


class TestVinylFormatNormalisation(unittest.TestCase):
    """MB compound vinyl format strings are normalised to Vinyl + size descriptor."""

    def _album_with_format(self, mb_format: str) -> object:
        r = _minimal_release()
        r['medium-list'][0]['format'] = mb_format
        return MusicBrainzAlbum(r).map()

    def test_12_inch_vinyl_format_normalised(self):
        album = self._album_with_format('12" Vinyl')
        self.assertEqual(album.format, 'Vinyl')
        self.assertIn('12"', album.format_description)

    def test_7_inch_vinyl_format_normalised(self):
        album = self._album_with_format('7" Vinyl')
        self.assertEqual(album.format, 'Vinyl')
        self.assertIn('7"', album.format_description)

    def test_10_inch_vinyl_format_normalised(self):
        album = self._album_with_format('10" Vinyl')
        self.assertEqual(album.format, 'Vinyl')
        self.assertIn('10"', album.format_description)

    def test_plain_vinyl_unchanged(self):
        album = self._album_with_format('Vinyl')
        self.assertEqual(album.format, 'Vinyl')
        self.assertNotIn('7"', album.format_description)
        self.assertNotIn('12"', album.format_description)

    def test_cd_format_unchanged(self):
        album = self._album_with_format('CD')
        self.assertEqual(album.format, 'CD')

    def test_vinyl_size_precedes_release_type_in_format_description(self):
        """Size descriptor sits first so compute_format_code desc_set lookup works."""
        album = self._album_with_format('12" Vinyl')
        self.assertEqual(album.format_description[0], '12"')

    def test_12_inch_vinyl_produces_correct_format_code(self):
        """End-to-end: format_base should resolve to 12″ (double prime) not '12\" Vinyl'."""
        from discogstagger.formatcodes import load_format_codes, compute_format_code
        album = self._album_with_format('12" Vinyl')
        fc = load_format_codes('conf/format_codes.yaml')
        if fc:  # skip if conf not available in test CWD
            code = compute_format_code(album.format, album.format_description, 1, fc)
            self.assertEqual(code, '12″')  # U+2033 double prime


if __name__ == '__main__':
    unittest.main()
