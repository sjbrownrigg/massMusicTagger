# -*- coding: utf-8 -*-
"""A different artist is a different record, not a lower-ranked one.

MusicBrainz tier 3 ranked candidates by a lexicographic
(title_score, artist_score, has_date) tuple, so a perfect title beat any
artist score at all — and nothing rejected a candidate on artist alone.

"Pariah" by Anja Huwe (2024, two tracks) was tagged as "Pariah" by Red Dons
(2010, two tracks): same title, same track count, fourteen years and one
completely different artist apart. Tier 3 compares title and track count and
nothing else, so there was nothing left to catch it.

Discogs does not have this hole — it validates on track durations, or on
track-title similarity when durations are missing, either of which a
different artist's record fails.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

from massmusictagger.sources.musicbrainz import search as mbsearch  # noqa: E402


def _release(mbid, title, artist, tracks=2, date='2010'):
    return {'id': mbid, 'title': title, 'artist-credit-phrase': artist,
            'date': date, 'medium-list': [{'track-count': tracks}]}


class _Searcher:
    """MBSearch with only what _text_search touches."""
    def __init__(self):
        self._conn = None


def _search(results, artist, album, tracks=2):
    s = mbsearch.MBSearch.__new__(mbsearch.MBSearch)
    s._conn = None
    with patch.object(mbsearch.musicbrainzngs, 'search_releases',
                      return_value={'release-list': results}):
        return mbsearch.MBSearch._text_search(s, artist, album, tracks)


class TheArtistMustResemble(unittest.TestCase):

    def test_the_real_mismatch_is_refused(self):
        got = _search([_release('red-dons', 'Pariah', 'Red Dons')],
                      'Anja Huwe', 'Pariah')
        self.assertIsNone(got, 'a different artist is not a match')

    def test_the_right_artist_still_matches(self):
        got = _search([_release('anja', 'Pariah', 'Anja Huwe', date='2024')],
                      'Anja Huwe', 'Pariah')
        self.assertEqual(got, 'anja')

    def test_the_right_one_is_chosen_from_a_mixed_list(self):
        got = _search([_release('red-dons', 'Pariah', 'Red Dons'),
                       _release('anja', 'Pariah', 'Anja Huwe', date='2024')],
                      'Anja Huwe', 'Pariah')
        self.assertEqual(got, 'anja')

    def test_order_does_not_decide_it(self):
        got = _search([_release('anja', 'Pariah', 'Anja Huwe', date='2024'),
                       _release('red-dons', 'Pariah', 'Red Dons')],
                      'Anja Huwe', 'Pariah')
        self.assertEqual(got, 'anja')


class LegitimateVariationsStillMatch(unittest.TestCase):
    """The threshold has to let real credits through.

    Measured against the mismatch at 35, these are the shapes that must not
    be caught by the same net.
    """

    CASES = [
        ('The Waterboys', 'Waterboys'),
        (':wumpscut:', 'wumpscut'),
        ('X-Fusion', 'X Fusion'),
        ('Various', 'Various Artists'),
        ('Anja Huwe', 'Anja Huwe & Mona Mur'),
        ('Depeche Mode', 'Depeche Mode'),
    ]

    def test_each_variation_is_accepted(self):
        for ours, credited in self.CASES:
            with self.subTest(ours=ours, credited=credited):
                got = _search([_release('x', 'An Album', credited)],
                              ours, 'An Album')
                self.assertEqual(got, 'x', f'{ours!r} vs {credited!r} rejected')


class WhenThereIsNothingToCompare(unittest.TestCase):

    def test_a_candidate_with_no_credited_artist_is_not_rejected(self):
        """The floor applies only when both names are known."""
        got = _search([_release('x', 'An Album', '')], 'Anja Huwe', 'An Album')
        self.assertEqual(got, 'x')

    def test_a_wrong_title_is_still_rejected(self):
        got = _search([_release('x', 'Something Else Entirely', 'Anja Huwe')],
                      'Anja Huwe', 'Pariah')
        self.assertIsNone(got)

    def test_a_wrong_track_count_is_still_rejected(self):
        got = _search([_release('x', 'Pariah', 'Anja Huwe', tracks=11)],
                      'Anja Huwe', 'Pariah', tracks=2)
        self.assertIsNone(got)


if __name__ == '__main__':
    unittest.main()
