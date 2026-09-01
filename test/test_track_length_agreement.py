"""Track lengths are compared by agreement, not by average.

The average could not separate "every track is moderately wrong", which means
a different release, from "one track is very wrong", which usually means one
mis-entered duration or one substituted version. Those need opposite verdicts
and the mean gave them the same one.

The case that forced the change is pinned below: Nick Cave's *Fifteen Feet Of
Pure White Snow* against release 35448229 -- same five titles in the same
order, four of them within a second, one 89s out because Discogs lists a 4:07
single version. Mean 18.2s against a 10s tolerance, so the correct release was
refused and the run reported "No match found".
"""

import unittest

from massmusictagger.sources.discogs.search import DiscogsSearch


def _cmp(tolerance=5.0, agreement=0.75):
    s = DiscogsSearch.__new__(DiscogsSearch)
    s.tracklength_tolerance = tolerance
    s.tracklength_agreement = agreement
    return s


def _pair(local, discogs):
    """(current, imported) in the shapes the comparison expects."""
    return ([{'duration': l} for l in local],
            [{'duration': d} for d in discogs])


class AgreementTest(unittest.TestCase):

    def test_identical_lengths_agree_completely(self):
        cur, imp = _pair(['3:00', '4:00'], ['3:00', '4:00'])
        self.assertEqual(_cmp()._compareTrackLengths(cur, imp), (2, 2, 0.0))

    def test_one_outlier_does_not_veto_the_others(self):
        """The Fifteen Feet case, in its own numbers."""
        local   = ['5:36', '5:53', '5:37', '4:14', '5:45']
        discogs = ['4:07', '5:53', '5:37', '4:15', '5:46']
        agreed, compared, median = _cmp()._compareTrackLengths(*_pair(local, discogs))
        self.assertEqual((agreed, compared), (4, 5))
        self.assertEqual(median, 1.0, 'the median ignores the 89s outlier')

    def test_a_uniformly_wrong_release_agrees_on_nothing(self):
        cur, imp = _pair(['3:00', '4:00', '5:00'], ['3:18', '4:20', '5:15'])
        agreed, compared, _ = _cmp()._compareTrackLengths(cur, imp)
        self.assertEqual((agreed, compared), (0, 3))

    def test_tracks_without_a_duration_are_not_counted(self):
        """A missing duration is not evidence either way."""
        cur, imp = _pair(['3:00', '', '5:00'], ['3:00', '4:00', None])
        agreed, compared, _ = _cmp()._compareTrackLengths(cur, imp)
        self.assertEqual((agreed, compared), (1, 1))

    def test_no_comparable_pair_reports_nothing_compared(self):
        cur, imp = _pair(['', ''], [None, None])
        agreed, compared, median = _cmp()._compareTrackLengths(cur, imp)
        self.assertEqual((agreed, compared), (0, 0))
        self.assertEqual(median, float('inf'))

    def test_the_tolerance_is_per_track(self):
        cur, imp = _pair(['3:00', '4:00'], ['3:04', '4:06'])
        agreed, _, _ = _cmp(tolerance=5.0)._compareTrackLengths(cur, imp)
        self.assertEqual(agreed, 1, '4s agrees, 6s does not')

    def test_the_median_is_even_length_safe(self):
        cur, imp = _pair(['3:00', '4:00', '5:00', '6:00'],
                         ['3:00', '4:02', '5:04', '6:20'])
        _, _, median = _cmp()._compareTrackLengths(cur, imp)
        self.assertEqual(median, 3.0, '(2+4)/2')


class ScoreOrderingTest(unittest.TestCase):
    """The score keeps its old contract: non-negative, lower is better."""

    def test_a_closer_release_scores_lower(self):
        close = _cmp()._compareTrackLengths(*_pair(['3:00'], ['3:01']))[2]
        loose = _cmp()._compareTrackLengths(*_pair(['3:00'], ['3:04']))[2]
        self.assertLess(close, loose)
        self.assertGreaterEqual(close, 0)


if __name__ == '__main__':
    unittest.main()
