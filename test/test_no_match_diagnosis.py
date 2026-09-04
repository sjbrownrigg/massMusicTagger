"""A failed search says what it saw, not just that it saw nothing.

"No match found" was the same three words whether Discogs held nothing at all
-- a white-label bootleg, a single-track remix release -- or held the right
album and refused it over one field. The first is nothing to be done; the
second is usually an incomplete or mis-split rip, and is actionable. Telling
them apart meant re-running the album with -v and reassembling wrapped log
lines, which is why a batch of failures stayed an undifferentiated pile.

Worked examples pinned below:
  Planet Jarre  -- 36 local tracks against 41 on every Discogs version.
  Copy Steal    -- a single-track remix release nothing catalogues.
"""

import unittest

from massmusictagger.sources.discogs.search import SearchState


class DiagnosisTest(unittest.TestCase):

    def test_nothing_compared_says_so(self):
        """Genuinely absent. Nothing for the user to do."""
        self.assertEqual(SearchState().diagnosis(), 'no candidates returned')

    def test_a_track_count_miss_names_the_closest_release(self):
        s = SearchState()
        s.rejections = [
            {'kind': 'track_count', 'rid': '12530658', 'distance': 5,
             'detail': '41 tracks, local has 36'},
            {'kind': 'track_count', 'rid': '12523403', 'distance': 100,
             'detail': '136 tracks, local has 36'},
        ]
        d = s.diagnosis()
        self.assertIn('12530658', d, 'the nearest release, not the first seen')
        self.assertIn('41 tracks, local has 36', d)
        self.assertNotIn('12523403', d)

    def test_the_tally_reports_every_comparison(self):
        s = SearchState()
        s.rejections = [
            {'kind': 'track_count', 'rid': '1', 'distance': 2, 'detail': 'a'},
            {'kind': 'duration', 'rid': '2', 'distance': 9, 'detail': 'b'},
            {'kind': 'duration', 'rid': '3', 'distance': 8, 'detail': 'c'},
        ]
        d = s.diagnosis()
        self.assertIn('3 compared', d)
        self.assertIn('2 on duration', d)
        self.assertIn('1 on track count', d)

    def test_an_actionable_kind_outranks_a_closer_veto(self):
        """A medium veto says nothing about how close the release was."""
        s = SearchState()
        s.rejections = [
            {'kind': 'medium', 'rid': 'veto', 'distance': 0.0, 'detail': 'm'},
            {'kind': 'track_count', 'rid': 'real', 'distance': 50.0, 'detail': 't'},
        ]
        self.assertIn('real', s.diagnosis())

    def test_duration_beats_titles_and_titles_beat_medium(self):
        for worse, better in (('titles', 'duration'), ('medium', 'titles')):
            s = SearchState()
            s.rejections = [
                {'kind': worse,  'rid': 'worse',  'distance': 0.0, 'detail': 'x'},
                {'kind': better, 'rid': 'better', 'distance': 99.0, 'detail': 'y'},
            ]
            self.assertIn('better', s.diagnosis(), '%s should outrank %s' % (better, worse))


class WiringTest(unittest.TestCase):
    """The line has to reach the caller, and not via the shared searcher."""

    def test_search_takes_a_caller_owned_notes_list(self):
        import inspect
        from massmusictagger.sources.discogs.search import DiscogsSearch
        sig = inspect.signature(DiscogsSearch.search)
        self.assertIn('notes', sig.parameters)
        self.assertIsNone(sig.parameters['notes'].default,
                          'per call, never per instance — the searcher is shared')

    def test_the_cascade_forwards_it(self):
        import inspect
        from massmusictagger import cascade
        self.assertIn('notes', inspect.signature(cascade.search_and_map).parameters)
        self.assertIn('notes=notes',
                      inspect.getsource(cascade._try_discogs))

    def test_the_processor_uses_it_in_the_failure_message(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertIn("'No match — %s' % notes[0]", src)
        self.assertIn("else 'No match found'", src,
                      'a source that reported nothing still needs a message')


if __name__ == '__main__':
    unittest.main()


class ClosenessTest(unittest.TestCase):
    """"Closest" has to mean close, or it sends the reader somewhere useless.

    Simon Carter's *Judgement Day* (2026, one track) was reported as one track
    short of release 17382961 — which is Wilf Carter & The Calgary Stampeders'
    "Don't Wait Until Judgement Day (To Cast Your Sins Away)", a 1970s country
    7". Discogs holds nothing for the actual single.

    The ranking was by absolute gap, so on a one-track album every two-track
    release scores the smallest gap possible and whatever the search dragged in
    wins the label. A gap of one is nothing on a 36-track album and everything
    on a single, so closeness is judged in proportion to what we hold.
    """

    def _state(self, rejections):
        s = SearchState()
        s.rejections = rejections
        return s

    def test_an_unrelated_release_is_not_called_closest(self):
        d = self._state([{'kind': 'track_count', 'rid': '17382961',
                          'distance': 1, 'relative': 1.0,
                          'detail': '2 tracks, local has 1'}]).diagnosis()
        self.assertIn('nothing came close', d)
        self.assertNotIn('17382961', d, 'naming it invites checking it')

    def test_a_genuinely_near_release_is_still_named(self):
        """Planet Jarre: 5 short of 41 is worth chasing."""
        d = self._state([{'kind': 'track_count', 'rid': '12530658',
                          'distance': 5, 'relative': 5 / 36,
                          'detail': '41 tracks, local has 36'}]).diagnosis()
        self.assertIn('12530658', d)

    def test_the_counts_are_still_reported_either_way(self):
        """Suppressing the id must not suppress the evidence."""
        d = self._state([{'kind': 'track_count', 'rid': 'x', 'distance': 1,
                          'relative': 1.0,
                          'detail': '2 tracks, local has 1'}]).diagnosis()
        self.assertIn('2 tracks, local has 1', d)
        self.assertIn('1 compared', d)

    def test_the_nearest_in_proportion_wins_not_the_nearest_in_tracks(self):
        s = self._state([
            {'kind': 'track_count', 'rid': 'far', 'distance': 1,
             'relative': 1.0, 'detail': '2 tracks, local has 1'},
            {'kind': 'track_count', 'rid': 'near', 'distance': 2,
             'relative': 2 / 40, 'detail': '38 tracks, local has 40'},
        ])
        self.assertIn('near', s.diagnosis())

    def test_a_rejection_without_a_relative_still_reports(self):
        """Kinds other than track count carry no proportion."""
        d = self._state([{'kind': 'duration', 'rid': '99', 'distance': 18.0,
                          'detail': 'only 1 of 5 tracks agree'}]).diagnosis()
        self.assertIn('99', d)
