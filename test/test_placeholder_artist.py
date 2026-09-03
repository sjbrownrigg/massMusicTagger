"""A placeholder artist names nobody, and every tier is anchored on the artist.

Einstürzende Neubauten's *Ende Neu (Remixes)* arrived with `artist='temp'` on
all ten files, no albumartist at all, and the real artist folded into the album
tag as `Einsturzende Neubauten - Ende Neu Remixes`. Discogs holds the release
(360802) with the same ten tracks under nearly the same titles, and the search
never had a chance: it asked for artist "temp".

A placeholder is worse than an empty tag, because it looks like an answer. The
folder is weaker evidence than a tag — which is why it is not consulted
otherwise — but far better than a name that means nothing, and the MusicBrainz
path has always fallen back this way while the Discogs path never did.
"""

import unittest

from massmusictagger.sources.discogs.search import (
    artist_from_folder, strip_artist_prefix, _is_placeholder_artist)


class PlaceholderTest(unittest.TestCase):

    def test_the_names_rippers_leave_behind(self):
        for name in ('temp', 'TEMP', ' Temp ', 'unknown', 'Unknown Artist',
                     'artist', 'none', 'n/a', 'test'):
            self.assertTrue(_is_placeholder_artist(name), name)

    def test_a_real_artist_is_not_a_placeholder(self):
        for name in ('Einstürzende Neubauten', 'Nick Cave', 'Temple of the Dog',
                     'Test Department'):
            self.assertFalse(_is_placeholder_artist(name), name)


class FolderTest(unittest.TestCase):

    def test_the_leading_segment_is_taken_as_the_artist(self):
        self.assertEqual(
            artist_from_folder('/incoming/EN/Einsturzende Neubauten - Ende Neu Remixes'),
            'Einsturzende Neubauten')

    def test_trailing_qualifiers_are_dropped(self):
        self.assertEqual(
            artist_from_folder('/incoming/X/Snog - Shop (2023) [FLAC]'), 'Snog')

    def test_a_folder_with_no_artist_falls_back_to_its_parent(self):
        self.assertEqual(
            artist_from_folder('/incoming/Einstürzende Neubauten/Ende Neu'),
            'Einstürzende Neubauten')

    def test_a_year_prefix_is_not_an_artist(self):
        self.assertEqual(
            artist_from_folder('/incoming/Nick Cave/2003 - Nocturama'), 'Nick Cave')

    def test_a_disc_folder_is_not_an_artist(self):
        self.assertEqual(artist_from_folder('/incoming/Bowie/CD 1'), 'Bowie')

    def test_the_library_root_is_not_an_artist(self):
        self.assertEqual(artist_from_folder('/incoming/Album'), '')


class AlbumPrefixTest(unittest.TestCase):
    """The same rip usually folds the artist into the album title too."""

    def test_the_artist_prefix_is_removed(self):
        self.assertEqual(
            strip_artist_prefix('Einsturzende Neubauten - Ende Neu Remixes',
                                'Einsturzende Neubauten'),
            'Ende Neu Remixes')

    def test_other_separators_work(self):
        for sep in ('-', '–', ':'):
            self.assertEqual(strip_artist_prefix('Snog %s Shop' % sep, 'Snog'), 'Shop')

    def test_an_album_that_is_only_the_artist_is_left_alone(self):
        """Stripping to nothing would search for everything."""
        self.assertEqual(strip_artist_prefix('Snog', 'Snog'), 'Snog')

    def test_an_unrelated_album_is_untouched(self):
        self.assertEqual(strip_artist_prefix('Ende Neu Remixes', 'Snog'),
                         'Ende Neu Remixes')

    def test_an_artist_appearing_later_is_not_stripped(self):
        self.assertEqual(strip_artist_prefix('Tribute to Snog', 'Snog'),
                         'Tribute to Snog')


class WiringTest(unittest.TestCase):

    def test_the_fallback_runs_while_building_the_search(self):
        import inspect
        from massmusictagger.sources.discogs.search import DiscogsSearch
        src = inspect.getsource(DiscogsSearch.getSearchParams)
        self.assertIn('_is_placeholder_artist', src)
        self.assertIn('artist_from_folder', src)
        self.assertIn('strip_artist_prefix', src)

    def test_it_only_fires_when_the_tag_names_nobody(self):
        import inspect
        from massmusictagger.sources.discogs.search import DiscogsSearch
        src = inspect.getsource(DiscogsSearch.getSearchParams)
        self.assertIn("_is_placeholder_artist(searchParams['artist']) or not", src)


if __name__ == '__main__':
    unittest.main()
