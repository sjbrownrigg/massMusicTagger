"""A release short of its own metadata is not tagged at all.

The tracktotal came with the rip, so this is a statement about the material
rather than about any database, and it can be made before a search runs. That
matters: tagging a fragment files it away as though it were the album, and it
stops being visible as a gap. A library that holds whole releases wants the
run to hand back a re-acquisition list instead.

Measured on /incoming when this was written: of 118 album folders, 90 were
complete, 7 short, 8 held more files than expected, 10 were unsplit CUE images
and 3 declared no tracktotal at all.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from massmusictagger.core.completeness import assess, enabled, Completeness


class _Meta:
    def __init__(self, disc, track, tracktotal):
        self.disc, self.track, self.tracktotal = disc, track, tracktotal


def _assess(files):
    """files: [(disc, track, tracktotal), …]"""
    paths = ['f%d' % i for i in range(len(files))]
    lookup = dict(zip(paths, [_Meta(*f) for f in files]))
    with patch('massmusictagger.core.mediafile.MediaFile',
               side_effect=lambda p: lookup[p]):
        return assess(paths)


class SingleDiscTest(unittest.TestCase):

    def test_a_full_album_is_complete(self):
        c = _assess([(1, n, 3) for n in (1, 2, 3)])
        self.assertTrue(c.complete)
        self.assertTrue(c.judged)
        self.assertEqual((c.present, c.expected), (3, 3))

    def test_a_missing_track_is_caught_and_named(self):
        c = _assess([(1, 1, 3), (1, 3, 3)])
        self.assertFalse(c.complete)
        self.assertEqual(c.gaps, ((1, [2]),))
        self.assertIn('missing 2', c.describe())

    def test_more_files_than_expected_is_not_complete_either(self):
        """Two editions in one folder is the shape that defeats matching."""
        c = _assess([(1, 1, 2), (1, 2, 2), (1, 2, 2)])
        self.assertFalse(c.complete)
        self.assertEqual((c.present, c.expected), (3, 2))


class MultiDiscTest(unittest.TestCase):
    """tracktotal counts one disc, so the expectation is summed per disc."""

    def test_two_full_discs_are_complete(self):
        c = _assess([(1, 1, 2), (1, 2, 2), (2, 1, 3), (2, 2, 3), (2, 3, 3)])
        self.assertTrue(c.complete)
        self.assertEqual(c.expected, 5)

    def test_a_gap_is_reported_against_its_own_disc(self):
        c = _assess([(1, 1, 2), (1, 2, 2), (2, 1, 3), (2, 3, 3)])
        self.assertFalse(c.complete)
        self.assertEqual(c.gaps, ((2, [2]),))
        self.assertIn('disc 2', c.describe())


class NotJudgedTest(unittest.TestCase):
    """Absence of a tracktotal is not evidence of incompleteness."""

    def test_no_tracktotal_is_allowed_through(self):
        c = _assess([(1, 1, None), (1, 2, None)])
        self.assertTrue(c.complete, 'must not block what it cannot judge')
        self.assertFalse(c.judged)
        self.assertIn('no tracktotal', c.describe())

    def test_a_partial_tracktotal_still_judges(self):
        """One file carrying the total is enough to check the rest against."""
        c = _assess([(1, 1, 3), (1, 2, None)])
        self.assertTrue(c.judged)
        self.assertFalse(c.complete)


class GateTest(unittest.TestCase):

    def test_the_guard_is_off_unless_configured(self):
        class Cfg:
            def getboolean(self, *a): raise KeyError
        self.assertFalse(enabled(Cfg()))

    def test_it_runs_before_any_lookup(self):
        """The point is not to search for a release we will not tag."""
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertLess(src.index('completeness.enabled'),
                        src.index('search_and_map'))

    def test_an_incomplete_release_gets_its_own_outcome(self):
        """Not 'failed' — the databases were never asked."""
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertIn('OUTCOME_INCOMPLETE', src)
        self.assertNotEqual(processor.OUTCOME_INCOMPLETE, processor.OUTCOME_FAILED)
        self.assertNotEqual(processor.OUTCOME_INCOMPLETE, processor.OUTCOME_SKIPPED)

    def test_the_report_lists_them_with_what_is_missing(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._print_summary)
        self.assertIn('OUTCOME_INCOMPLETE', src)
        self.assertIn('fewer tracks than their own metadata expects', src)


class WalkTest(unittest.TestCase):
    """Multi-disc tracks live in subdirectories and must all be seen."""

    def test_it_finds_tracks_in_disc_subdirectories(self):
        from massmusictagger.processor import _audio_files_in
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        for disc in ('CD 1', 'CD 2'):
            os.makedirs(os.path.join(tmp, disc))
            open(os.path.join(tmp, disc, '01.flac'), 'wb').close()
        open(os.path.join(tmp, 'cover.jpg'), 'wb').close()
        found = _audio_files_in(tmp)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(f.endswith('.flac') for f in found))


if __name__ == '__main__':
    unittest.main()
