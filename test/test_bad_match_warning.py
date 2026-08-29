# -*- coding: utf-8 -*-
"""The bad-match warning fires on compilations, not on every album.

It used to warn whenever the album artist equalled the first track's artist,
described in the commit that added it as "a reliable indicator that a wrong
release was matched". On a single-artist album the two match by definition,
so it fired on 371 of 379 albums in this library -- 97%. A warning that
common is not a signal; in a bulk run it buries the ones that are.

The case it was reaching for is real but narrower: on a compilation, an album
artist equal to the first track's artist means the album-level credit was not
picked up, and the release should be credited to Various.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))


def _album(artist, track_artist, tracks=5, compilation=False):
    from massmusictagger.core.album import Album, Disc, Track
    a = Album('1', 'An Album', [artist])
    a.is_compilation = compilation
    disc = Disc(1)
    for i in range(tracks):
        # Track.artist is derived from artists / _artist_display, not settable.
        t = Track(i + 1, f'Track {i + 1}', [track_artist])
        disc.tracks.append(t)
    a.discs = [disc]
    return a


def _processor(various='Various Artists'):
    from massmusictagger.processor import MassProcessor
    p = MassProcessor.__new__(MassProcessor)
    cfg = MagicMock()
    cfg.has_option.return_value = True
    cfg.get.return_value = various
    p.cfg = cfg
    return p


class WhatCountsAsVarious(unittest.TestCase):

    def test_the_source_saying_so(self):
        self.assertTrue(_processor()._is_various(
            _album('Someone', 'Someone', compilation=True)))

    def test_the_configured_various_artists_name(self):
        self.assertTrue(_processor()._is_various(
            _album('Various Artists', 'Anyone')))

    def test_the_usual_spellings(self):
        for name in ('Various', 'various artists', 'VA'):
            with self.subTest(name=name):
                self.assertTrue(_processor()._is_various(_album(name, 'Anyone')))

    def test_an_ordinary_artist_is_not_various(self):
        self.assertFalse(_processor()._is_various(_album('Visage', 'Visage')))

    def test_a_missing_config_key_is_not_fatal(self):
        from massmusictagger.processor import MassProcessor
        p = MassProcessor.__new__(MassProcessor)
        cfg = MagicMock()
        cfg.has_option.return_value = False
        p.cfg = cfg
        self.assertFalse(p._is_various(_album('Visage', 'Visage')))
        self.assertTrue(p._is_various(_album('Various', 'Anyone')))


class TheWarningIsScoped(unittest.TestCase):
    """Asserted at the call site: the guard must be there."""

    def _source(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor)
        i = src.index('first_track_artist = ')
        return src[max(0, i - 900):i + 400]

    def test_a_single_artist_album_does_not_warn(self):
        self.assertIn('self._is_various(album)', self._source())

    def test_the_message_describes_the_compilation_case(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor)
        self.assertIn('Compilation credited to', src)
        self.assertNotIn('this may indicate a wrong release match', src)


if __name__ == '__main__':
    unittest.main()
