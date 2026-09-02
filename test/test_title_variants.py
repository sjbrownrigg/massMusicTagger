"""An edition qualifier the rip carries and Discogs does not makes a search miss.

*The Assassination Of Jesse James By The Coward Robert Ford* is the case that
found this. The rip calls it "... (Music From The Original Motion Picture
Soundtrack)"; Discogs calls it "... (Music From The Motion Picture)".

Measured against the live API with the artist held constant at
`Nick Cave & Warren Ellis`:

    full title      0 results
    title trimmed  15 results, the right release first

Three earlier attempts blamed the artist credit and fixed that instead. The
artist was a real problem -- the album is credited to the duo and the rip says
`Nick Cave` -- but it was not the binding one, and only replaying the album
showed that the tier was by then trying the right credit and still finding
nothing.
"""

import unittest

from massmusictagger.sources.discogs.search import DiscogsSearch


def _variants(title):
    return DiscogsSearch.__new__(DiscogsSearch)._title_variants(title)


class TrimTest(unittest.TestCase):

    def test_the_jesse_james_title_is_cut_at_the_qualifier(self):
        """Stopwords are already stripped, so it reads "Music From Original"."""
        full = ('Assassination of Jesse James by Coward Robert Ford '
                'Music From Original Motion Picture Soundtrack')
        self.assertEqual(_variants(full)[1],
                         'Assassination of Jesse James by Coward Robert Ford')

    def test_the_earliest_marker_wins(self):
        """Cutting at a later one would leave the lead-in words behind."""
        self.assertEqual(
            _variants('Album Music From Original Motion Picture Soundtrack')[1],
            'Album')

    def test_an_edition_suffix_is_trimmed(self):
        self.assertEqual(_variants('Ultra Deluxe Edition')[1], 'Ultra')
        self.assertEqual(_variants('Low Remastered')[1], 'Low')

    def test_an_ordinary_title_is_left_alone(self):
        for title in ('Kapital', 'Henry\'s Dream', 'Station to Station'):
            self.assertEqual(_variants(title), [title])

    def test_the_full_title_is_always_tried_first(self):
        full = 'Album Deluxe Edition'
        self.assertEqual(_variants(full)[0], full)

    def test_a_title_that_is_only_a_qualifier_is_not_gutted(self):
        """Cutting "Soundtrack" to nothing would search for everything."""
        self.assertEqual(_variants('Soundtrack'), ['Soundtrack'])

    def test_a_short_album_title_survives_the_trim(self):
        """Low, Pop and IV are real albums; a length floor would lose them."""
        self.assertEqual(_variants('Low Remastered')[1], 'Low')
        self.assertEqual(_variants('Pop Deluxe Edition')[1], 'Pop')


class OrderTest(unittest.TestCase):
    """The trimmed title is a fallback, not a replacement."""

    def test_the_trim_only_runs_when_the_full_title_found_nothing(self):
        import inspect
        src = inspect.getsource(DiscogsSearch._search_release_fields)
        self.assertIn('if state.candidates or state.no_duration:', src)
        self.assertIn('return', src.split('for variant in variants:')[1][:200])

    def test_the_artist_anchor_is_kept(self):
        """This narrows the query; it does not become a bare title search."""
        import inspect
        src = inspect.getsource(DiscogsSearch._search_release_fields)
        self.assertNotIn("s['artist'] =", src)

    def test_the_original_title_is_restored(self):
        import inspect
        src = inspect.getsource(DiscogsSearch._search_release_fields)
        self.assertIn('finally:', src)
        self.assertIn("s['release'] = release_title", src)


if __name__ == '__main__':
    unittest.main()
