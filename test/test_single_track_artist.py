"""A one-track release has to be carried by its artist alone.

Every other check is satisfied trivially by a single track: the track count is
1 == 1, and duration agreement is one comparison. Thomas Feiner's *The Ship
Song* was filed as Thomas Anders' *The Christmas Song* and sat in the library
looking entirely normal.

Raising the fuzzy thresholds cannot fix it. Measured with rapidfuzz:

    the wrong match      title 86, artist 76
    a real variation     artist 62  ("Anja Huwe" vs "Anja Huwe & Mona Mur")

Any floor high enough to reject 76 rejects 62 as well. The scores genuinely
overlap, so the discriminator has to be kind rather than degree: a real
variation is one name contained in the other, or the same name spelled with
different punctuation or diacritics. A wrong match is two different names that
merely resemble each other.
"""

import unittest

from massmusictagger.sources.musicbrainz.search import (
    artists_are_related, _fold_artist)


class RelatednessTest(unittest.TestCase):

    def test_the_wrong_match_is_refused(self):
        self.assertFalse(artists_are_related('Thomas Feiner', 'Thomas Anders'))

    def test_a_collaboration_credit_is_accepted(self):
        self.assertTrue(artists_are_related('Anja Huwe', 'Anja Huwe & Mona Mur'))

    def test_various_artists_spellings_agree(self):
        self.assertTrue(artists_are_related('Various', 'Various Artists'))

    def test_case_and_punctuation_are_ignored(self):
        self.assertTrue(artists_are_related('Nick Cave & the Bad Seeds',
                                            'Nick Cave & The Bad Seeds'))
        self.assertTrue(artists_are_related('-wumpscut-', 'wumpscut'))

    def test_diacritics_are_folded(self):
        self.assertTrue(artists_are_related('Sigur Rós', 'Sigur Ros'))
        self.assertTrue(artists_are_related('Einstürzende Neubauten',
                                            'Einsturzende Neubauten'))

    def test_the_slashed_o_is_folded_too(self):
        """It is a letter in its own right, not a decomposable diacritic."""
        self.assertEqual(_fold_artist('Trentemøller'), 'trentemoller')
        self.assertTrue(artists_are_related('Trentemøller', 'Trentemoller'))

    def test_two_unrelated_artists_are_refused(self):
        self.assertFalse(artists_are_related('Nick Cave', 'Nick Drake'))
        self.assertFalse(artists_are_related('Red Dons', 'Anja Huwe'))

    def test_an_empty_side_is_not_a_match(self):
        self.assertFalse(artists_are_related('', 'Thomas Anders'))
        self.assertFalse(artists_are_related('Thomas Feiner', ''))


class GateTest(unittest.TestCase):
    """It applies to single tracks only; an album has its tracklist."""

    def test_the_rule_is_conditioned_on_one_track(self):
        import inspect
        from massmusictagger.sources.musicbrainz.search import MBSearch
        src = inspect.getsource(MBSearch._text_search)
        self.assertIn('track_count == 1', src)
        self.assertIn('artists_are_related', src)

    def test_it_runs_after_the_similarity_floor(self):
        """The cheap numeric test first, the structural one second."""
        import inspect
        from massmusictagger.sources.musicbrainz.search import MBSearch
        src = inspect.getsource(MBSearch._text_search)
        self.assertLess(src.index('_MIN_ARTIST_SCORE'),
                        src.index('artists_are_related'))


if __name__ == '__main__':
    unittest.main()


class DiscogsGateTest(unittest.TestCase):
    """The same rule on the Discogs side.

    Three albums in this library are single-track covers filed under the artist
    of the original -- Lunar Paths' reading of *The Ship Song* went in as
    Marianne Faithfull, and Marco Velocci's karaoke *Into My Arms* as Nick Cave
    & The Bad Seeds. Two came from Discogs, so guarding MusicBrainz alone would
    have left most of the pattern in place.

    It also matters more since tier 3b, which deliberately searches under other
    names for the artist: widening what is retrieved widens what can be wrongly
    accepted, unless the artist is checked again at the point of acceptance.
    """

    def test_the_rule_is_applied_to_discogs_candidates(self):
        import inspect
        from massmusictagger.sources.discogs.search import DiscogsSearch
        src = inspect.getsource(DiscogsSearch._compareRelease)
        self.assertIn('local_count == 1', src)
        self.assertIn('artists_are_related', src)

    def test_it_is_checked_before_durations(self):
        """No point comparing lengths of a record by someone else."""
        import inspect
        from massmusictagger.sources.discogs.search import DiscogsSearch
        src = inspect.getsource(DiscogsSearch._compareRelease)
        self.assertLess(src.index('artists_are_related'),
                        src.index('_compareTrackLengths'))

    def test_the_rejection_is_reported(self):
        """It has to reach the no-match line, or it is another silent refusal."""
        import inspect
        from massmusictagger.sources.discogs.search import DiscogsSearch
        src = inspect.getsource(DiscogsSearch._compareRelease)
        self.assertIn("'kind': 'artist'", src)

    def test_an_artist_rejection_ranks_in_the_diagnosis(self):
        from massmusictagger.sources.discogs.search import SearchState
        s = SearchState()
        s.rejections = [
            {'kind': 'medium', 'rid': 'm', 'distance': 0.0, 'detail': 'x'},
            {'kind': 'artist', 'rid': 'a', 'distance': 500.0,
             'detail': 'single track credited to Marianne Faithfull'},
        ]
        self.assertIn('Marianne Faithfull', s.diagnosis())
