"""Filing a multi-artist release under its primary artist.

Two tests separate a guest credit from a split release, and the first matters
more: identity before phrasing. 48 of 73 join tokens in the cached Discogs
data were '=', which is transliteration -- the same artist id twice, once with
a non-Latin name -- not collaboration at all.

The cases here are the ones that actually appeared in the library:

    David Bowie Featuring Al B. Sure!   -> file under David Bowie
    David Bowie Featuring Lenny Kravitz -> file under David Bowie
    D.A.R.P.A. / Dive / :wumpscut:      -> keep all three
"""

import unittest

from massmusictagger.core.naming import artistjoins


def table(subordinating=None, coordinating=None):
    return {
        'subordinating': subordinating if subordinating is not None
        else ['featuring', 'feat.', 'presents', 'remixed by', 'with'],
        'coordinating': coordinating if coordinating is not None
        else ['/', 'vs.', '&', '+', 'meets'],
    }


class PackagedTableTest(unittest.TestCase):

    def test_the_packaged_table_loads(self):
        t = artistjoins.load_artist_joins()
        self.assertIn('featuring', [x.lower() for x in t['subordinating']])
        self.assertIn('/', t['coordinating'])

    def test_ambiguous_joins_ship_unlisted(self):
        """'and' and ',' are not decidable, so they must not be guessed at."""
        t = artistjoins.load_artist_joins()
        listed = {x.lower() for x in t['subordinating']}
        self.assertNotIn('and', listed)
        self.assertNotIn(',', listed)

    def test_a_named_file_that_is_missing_warns_and_falls_back(self):
        with self.assertLogs('massmusictagger.core.naming.artistjoins',
                             'WARNING'):
            t = artistjoins.load_artist_joins('/nonexistent/artist_joins.yaml')
        self.assertIn('/', t['coordinating'])


class ClassificationTest(unittest.TestCase):

    def test_subordinating_and_coordinating(self):
        t = table()
        for join in ('featuring', 'Featuring', ' FEAT. ', 'presents'):
            with self.subTest(join=join):
                self.assertTrue(artistjoins.is_subordinating(join, t))
        for join in ('/', 'vs.', '&', 'meets'):
            with self.subTest(join=join):
                self.assertFalse(artistjoins.is_subordinating(join, t))

    def test_unlisted_joins_are_coordinating(self):
        """The safe default: keep every artist rather than hide one."""
        t = table()
        for join in ('and', ',', 'x', 'no idea'):
            with self.subTest(join=join):
                self.assertFalse(artistjoins.is_subordinating(join, t))


class PrimaryArtistTest(unittest.TestCase):

    def test_featuring_files_under_the_first_artist(self):
        self.assertEqual(
            artistjoins.primary_artist(
                ['David Bowie', 'Al B. Sure!'], ['Featuring', ''],
                'David Bowie Featuring Al B. Sure!', table()),
            'David Bowie')

    def test_a_split_keeps_every_artist(self):
        display = 'D.A.R.P.A. / Dive / :wumpscut:'
        self.assertEqual(
            artistjoins.primary_artist(
                ['D.A.R.P.A.', 'Dive', ':wumpscut:'], ['/', '/', ''],
                display, table()),
            display)

    def test_versus_keeps_both(self):
        display = 'DHS vs. DJ Slip'
        self.assertEqual(
            artistjoins.primary_artist(['DHS', 'DJ Slip'], ['vs.', ''],
                                       display, table()),
            display)

    def test_a_single_artist_is_unchanged(self):
        self.assertEqual(
            artistjoins.primary_artist(['Depeche Mode'], [''],
                                       'Depeche Mode', table()),
            'Depeche Mode')

    def test_mixed_joins_keep_the_whole_credit(self):
        """'A feat. B / C' is part collaboration; collapsing it loses C."""
        display = 'A Featuring B / C'
        self.assertEqual(
            artistjoins.primary_artist(['A', 'B', 'C'], ['Featuring', '/', ''],
                                       display, table()),
            display)

    def test_an_unlisted_join_keeps_the_whole_credit(self):
        display = 'Depeche Mode And Richard Morel'
        self.assertEqual(
            artistjoins.primary_artist(['Depeche Mode', 'Richard Morel'],
                                       ['And', ''], display, table()),
            display)

    def test_a_user_can_make_and_subordinating(self):
        """The point of the table being user-owned."""
        t = table(subordinating=['and'])
        self.assertEqual(
            artistjoins.primary_artist(['Depeche Mode', 'Richard Morel'],
                                       ['And', ''],
                                       'Depeche Mode And Richard Morel', t),
            'Depeche Mode')


class IdentityTest(unittest.TestCase):
    """Identity before phrasing -- the majority case in real data."""

    def test_the_same_artist_twice_is_one_artist(self):
        """Discogs '=' transliteration: id 10263 listed twice."""
        self.assertEqual(
            artistjoins.primary_artist(
                ['David Bowie', 'David Bowie'], ['=', ''],
                'David Bowie = David Bowie', table(),
                ids=[10263, 10263]),
            'David Bowie')

    def test_equal_ids_win_even_though_the_join_is_unlisted(self):
        """'=' is in neither list; identity settles it without the table."""
        t = table(subordinating=[], coordinating=[])
        self.assertEqual(
            artistjoins.primary_artist(
                ['David Bowie', 'デビッド・ボウイー'], ['=', ''],
                'David Bowie = デビッド・ボウイー', t,
                ids=[10263, 10263]),
            'David Bowie')

    def test_different_ids_are_not_collapsed(self):
        display = 'D.A.R.P.A. / Dive'
        self.assertEqual(
            artistjoins.primary_artist(['D.A.R.P.A.', 'Dive'], ['/', ''],
                                       display, table(), ids=[1, 2]),
            display)

    def test_missing_ids_fall_through_to_the_join(self):
        self.assertEqual(
            artistjoins.primary_artist(['David Bowie', 'Al B. Sure!'],
                                       ['Featuring', ''],
                                       'David Bowie Featuring Al B. Sure!',
                                       table(), ids=[None, None]),
            'David Bowie')


class WiringTest(unittest.TestCase):
    """The variable must reach format strings, and the table must be shipped."""

    def test_the_format_variable_exists(self):
        import inspect
        from massmusictagger.core import taggerutils
        src = inspect.getsource(taggerutils)
        self.assertIn("'%albumartist_primary%'", src)
        self.assertIn('_primary_album_artist', src)

    def test_the_table_is_discoverable_by_name(self):
        from massmusictagger import roots
        self.assertEqual(roots.LAYOUT['artist_joins'], 'artist_joins.yaml')

    def test_new_config_writes_it(self):
        from massmusictagger.core import tagger_config
        names = [dest for _, dest in tagger_config._NEW_CONFIG_TEMPLATES]
        self.assertIn('artist_joins.yaml', names)

    def test_the_album_model_keeps_joins_and_ids(self):
        from massmusictagger.core.album import Album
        a = Album('1', 'T', ['A', 'B'])
        self.assertEqual(a.artist_joins, [])
        self.assertEqual(a.artist_ids, [])


if __name__ == '__main__':
    unittest.main()
