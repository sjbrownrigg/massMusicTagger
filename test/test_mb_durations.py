"""MusicBrainz never checked that the audio was the same audio.

Tier 3 ranks on `(title_score, artist_score, has_date)` and validates the track
count. Durations are not consulted anywhere on that path, so a release with the
right number of tracks and a similar name wins without anything confirming the
recordings match. Discogs has compared lengths since 3.11.0; this is the same
hole on the other source.

Applied to the release already fetched for mapping, so it costs no extra
request, and as a veto: it can only refuse a winner, never promote a loser.
"""

import unittest
from unittest.mock import patch

from massmusictagger import cascade


class _Cfg:
    def __init__(self, tolerance=10.0, agreement=0.75, raises=False):
        self._t, self._a, self._raises = tolerance, agreement, raises

    def getfloat(self, section, option):
        if self._raises:
            raise KeyError(option)
        return self._t if option == 'tracklength_tolerance' else self._a


def _release(*seconds):
    return {'medium-list': [{'track-list': [
        {'length': None if s is None else int(s * 1000),
         'recording': {'title': 'T%d' % i}}
        for i, s in enumerate(seconds)]}]}


def _check(local, release_seconds, cfg=None):
    with patch.object(cascade, '_local_tracks',
                      return_value=[('T%d' % i, s) for i, s in enumerate(local)]):
        return cascade._durations_corroborate(cfg or _Cfg(), 'dir',
                                              _release(*release_seconds))


class AgreementTest(unittest.TestCase):

    def test_matching_lengths_are_accepted(self):
        self.assertTrue(_check([180, 240], [181, 239]))

    def test_a_release_wrong_throughout_is_refused(self):
        self.assertFalse(_check([180, 240], [220, 300]))

    def test_one_bad_length_does_not_refuse_an_album(self):
        """Same reasoning as the Discogs side: agreement, not average."""
        self.assertTrue(_check([180, 240, 200, 210],
                               [180, 240, 200, 999]))

    def test_the_red_cell_pair_still_passes_on_length_alone(self):
        """Which is exactly why the title veto is needed as well."""
        self.assertTrue(_check([180, 182], [176, 180]))


class SafetyTest(unittest.TestCase):
    """A veto that fires on missing data would be worse than no veto."""

    def test_a_release_without_lengths_is_not_refused(self):
        self.assertTrue(_check([180, 240], [None, None]))

    def test_a_count_mismatch_is_left_to_the_count_check(self):
        self.assertTrue(_check([180], [180, 240]))

    def test_no_local_files_is_not_a_refusal(self):
        with patch.object(cascade, '_local_tracks', return_value=[]):
            self.assertTrue(cascade._durations_corroborate(
                _Cfg(), 'dir', _release(180)))

    def test_a_config_without_the_keys_does_not_refuse(self):
        self.assertTrue(_check([180, 240], [220, 300], cfg=_Cfg(raises=True)))


class WiringTest(unittest.TestCase):

    def test_it_runs_on_the_release_already_fetched(self):
        import inspect
        src = inspect.getsource(cascade._try_musicbrainz)
        self.assertLess(src.index('connector.fetch_release(mbid)'),
                        src.index('_durations_corroborate'))

    def test_it_runs_after_the_title_check(self):
        import inspect
        src = inspect.getsource(cascade._try_musicbrainz)
        self.assertLess(src.index('_titles_corroborate'),
                        src.index('_durations_corroborate'))

    def test_local_tracks_are_ordered_by_disc_then_number(self):
        import inspect
        src = inspect.getsource(cascade._local_tracks)
        self.assertIn('rows.sort(key=lambda r: (r[0], r[1]))', src)


if __name__ == '__main__':
    unittest.main()
