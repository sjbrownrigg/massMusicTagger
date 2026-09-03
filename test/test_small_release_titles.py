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


class DiscogsOrderTest(unittest.TestCase):
    """The veto sits after the length match, not inside the score.

    Stewart's framing, and the right one: a title mismatch on a short release
    has to be able to refuse a candidate outright. Folding it into the score
    would only move a wrong release down the ranking, and on a two-track single
    there is often nothing else in the ranking to beat it.
    """

    def _src(self):
        import inspect
        from massmusictagger.sources.discogs.search import DiscogsSearch
        return inspect.getsource(DiscogsSearch._compareRelease)

    def test_it_runs_after_the_length_comparison(self):
        src = self._src()
        self.assertLess(src.index('_compareTrackLengths'),
                        src.index('tracks_are_accounted_for'))

    def test_it_refuses_rather_than_rescores(self):
        src = self._src()
        after = src[src.index('tracks_are_accounted_for'):]
        self.assertIn('return False', after,
                      'a title mismatch must veto, not adjust the score')

    def test_the_refusal_is_reported(self):
        """Otherwise it is another silent rejection."""
        self.assertIn("'kind': 'titles'", self._src())

    def test_it_only_applies_once_the_lengths_have_agreed(self):
        """A candidate rejected on length never reaches the title check."""
        src = self._src()
        veto = src.index('tracks_are_accounted_for')
        accept = src.index('share >= self.tracklength_agreement')
        self.assertLess(accept, veto)


class UntaggedSourceTest(unittest.TestCase):
    """The veto must not fire when the titles name nothing.

    Stewart's objection, and a fair one: an untagged or placeholder-tagged rip
    carries titles like "Track 01" or "02", which score near zero against real
    ones. A check meant to catch wrong matches would then refuse right ones —
    and untagged sources are exactly the material that most needs a database to
    tell it what it is. The evidence is absent, not contradictory.
    """

    def test_untitled_files_do_not_veto(self):
        self.assertTrue(tracks_are_accounted_for([None, None], RELEASE))
        self.assertTrue(tracks_are_accounted_for(['', '  '], RELEASE))

    def test_track_number_placeholders_do_not_veto(self):
        for placeholder in (['Track 01', 'Track 02'], ['01', '02'],
                            ['Track1', 'Track2'], ['Untitled', 'Untitled 2'],
                            ['audio_01', 'audio_02']):
            self.assertTrue(tracks_are_accounted_for(placeholder, RELEASE),
                            placeholder)

    def test_a_partly_tagged_rip_does_not_veto(self):
        """Judging on the half that happens to be tagged invents evidence."""
        self.assertTrue(tracks_are_accounted_for(['Only Night', '02'], RELEASE))

    def test_a_release_with_placeholder_titles_does_not_veto(self):
        self.assertTrue(tracks_are_accounted_for(RELEASE, ['1', '2']))

    def test_real_titles_still_veto(self):
        """The guard must not have disarmed the check it protects."""
        self.assertFalse(tracks_are_accounted_for(
            ['Good Morning, Good Light (Radio Edit)', 'Only Night'], RELEASE))
