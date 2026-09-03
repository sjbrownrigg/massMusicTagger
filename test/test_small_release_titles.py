"""On a small release, lengths alone are not evidence.

Two different two-track singles have the same track count by definition, and
their durations line up by chance often enough to be worthless. Red Cell's
*Good Morning, Good Light* is the case:

    local    Good Morning, Good Light (Radio Edit)  180s
             Only Night                             182s
    release  Good Morning, Good Light (Acoustic…)   176s
             Good Morning, Good Light (Radio Edit)  180s

Every duration agreed inside the 10s tolerance and the counts were equal, so
nothing objected. "Only Night" — a different song — was retagged as a radio
edit of another one, destroying the title it arrived with.

Track titles separate them cleanly: the wrong folder scores 33 on its weakest
track, the right folder 100 on both.
"""

import unittest

from massmusictagger.sources.musicbrainz.search import (
    tracks_are_accounted_for, _SMALL_RELEASE)

RELEASE = ['Good Morning, Good Light (Acoustic Version)',
           'Good Morning, Good Light (Radio Edit)']


class SmallReleaseTest(unittest.TestCase):

    def test_the_wrong_single_is_refused(self):
        self.assertFalse(tracks_are_accounted_for(
            ['Good Morning, Good Light (Radio Edit)', 'Only Night'], RELEASE))

    def test_the_right_single_is_accepted(self):
        self.assertTrue(tracks_are_accounted_for(RELEASE, RELEASE))

    def test_order_does_not_matter(self):
        """The rip and the release need not agree on sequence."""
        self.assertTrue(tracks_are_accounted_for(list(reversed(RELEASE)), RELEASE))

    def test_a_version_suffix_still_matches(self):
        """"(2024 Remaster)" is the same song, not a different one."""
        self.assertTrue(tracks_are_accounted_for(
            ['Good Morning, Good Light (Radio Edit) [2024 Remaster]'],
            RELEASE))

    def test_one_stray_track_is_enough_to_refuse(self):
        """With so little evidence, all of it has to agree."""
        self.assertFalse(tracks_are_accounted_for(
            RELEASE + ['Something Else Entirely'], RELEASE))


class LargeReleaseTest(unittest.TestCase):
    """Above the threshold a stray track means a bonus track, not a wrong match."""

    def test_a_long_release_is_not_vetoed(self):
        release = ['Track %d' % n for n in range(1, 11)]
        self.assertGreater(len(release), _SMALL_RELEASE)
        self.assertTrue(tracks_are_accounted_for(
            release + ['A Bonus Nobody Catalogued'], release))


class SafetyTest(unittest.TestCase):
    """A veto that fires on missing data would be worse than no veto."""

    def test_no_titles_either_side_is_not_a_veto(self):
        self.assertTrue(tracks_are_accounted_for([], RELEASE))
        self.assertTrue(tracks_are_accounted_for(RELEASE, []))
        self.assertTrue(tracks_are_accounted_for(None, None))

    def test_blank_titles_are_ignored(self):
        self.assertTrue(tracks_are_accounted_for(['', None], RELEASE))


class WiringTest(unittest.TestCase):

    def test_it_runs_after_the_track_count_check(self):
        import inspect
        from massmusictagger import cascade
        src = inspect.getsource(cascade._try_musicbrainz)
        self.assertLess(src.index('_validate_id_match'),
                        src.index('_titles_corroborate'))

    def test_unreadable_local_files_do_not_veto(self):
        import inspect
        from massmusictagger import cascade
        src = inspect.getsource(cascade._titles_corroborate)
        self.assertIn('not vetoing', src)
        self.assertIn('return True', src)


if __name__ == '__main__':
    unittest.main()
