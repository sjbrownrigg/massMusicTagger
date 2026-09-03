"""A comma between credited artists is a join, not an absence of one.

Discogs credits "High Time (Chinese Takeaway)" to `j:dead, FabrikC` — a
two-artist collaboration on a one-track release, with the join field set to
",". The mapper treated a comma as "no meaningful join", returned an empty
display string, and the album was filed under `j:dead` alone.

The decision belongs in conf/artist_joins.yaml, where a comma is deliberately
*unlisted* and therefore coordinating: keep the whole credit. Discarding the
second artist in the mapper meant the table never got to express that.
"""

import unittest

from massmusictagger.sources.discogs.album import DiscogsAlbum
from massmusictagger.core.naming import artistjoins


class _Credit:
    def __init__(self, name, join=''):
        self.name = name
        self.data = {'name': name, 'join': join, 'anv': ''}


def _display(*pairs):
    m = DiscogsAlbum.__new__(DiscogsAlbum)
    m.use_anv = False
    m._artist_name = lambda x: x.name
    return m.album_artist_display([_Credit(n, j) for n, j in pairs])


class DisplayTest(unittest.TestCase):

    def test_a_comma_keeps_both_artists(self):
        self.assertEqual(_display(('j:dead', ','), ('FabrikC', '')),
                         'j:dead, FabrikC')

    def test_the_comma_has_no_space_before_it(self):
        self.assertNotIn(' ,', _display(('A', ','), ('B', '')))

    def test_three_artists_comma_joined(self):
        self.assertEqual(_display(('A', ','), ('B', ','), ('C', '')),
                         'A, B, C')

    def test_other_joins_are_unchanged(self):
        self.assertEqual(_display(('A', 'Feat.'), ('B', '')), 'A Feat. B')
        self.assertEqual(_display(('A', '&'), ('B', '')), 'A & B')

    def test_no_join_at_all_still_defers_to_the_caller(self):
        """Empty means "TaggerUtils decides", which is the old behaviour."""
        self.assertEqual(_display(('A', ''), ('B', '')), '')

    def test_a_single_artist_is_untouched(self):
        self.assertEqual(_display(('A', '')), 'A')


class FilingTest(unittest.TestCase):
    """What the credit becomes once artist_joins.yaml has its say."""

    def setUp(self):
        self.table = artistjoins.load_artist_joins()

    def _primary(self, names, joins):
        display = _display(*zip(names, joins))
        return artistjoins.primary_artist(list(names), list(joins),
                                          display, self.table)

    def test_a_comma_collaboration_keeps_the_whole_credit(self):
        self.assertEqual(self._primary(('j:dead', 'FabrikC'), (',', '')),
                         'j:dead, FabrikC')

    def test_a_guest_credit_still_files_under_the_first_artist(self):
        self.assertEqual(self._primary(('A', 'B'), ('Feat.', '')), 'A')

    def test_an_ampersand_still_keeps_both(self):
        self.assertEqual(self._primary(('A', 'B'), ('&', '')), 'A & B')


if __name__ == '__main__':
    unittest.main()
