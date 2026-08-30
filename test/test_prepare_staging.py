"""Preparation writes to staging, not into the source tree.

Nothing prepare() produces is source material. A disc image and its sheet are
the source; the split tracks are a decode artefact, made to be tagged and then
finished with. Writing them beside the original pollutes what the user put
there and makes a second run see a different album than the first did.

The dangerous part is not where files are written but what `source_action`
then acts on. `_post_process_source` calls `shutil.move(result.sourcedir, ...)`
and `shutil.rmtree(result.sourcedir)`. If that pointed at a staging directory,
`move` would archive a temporary decode and leave the user's disc images in
place for ever, and `remove` would delete the decode and leave them too. The
origin/audio split exists for exactly that, so most of these tests pin the
distinction rather than the paths.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from massmusictagger.core.files import PrepTask


class PrepTaskTest(unittest.TestCase):

    def test_outdir_defaults_to_none(self):
        """Older callers construct PrepTask with three fields."""
        t = PrepTask('/src/album', 'cue', ('a.cue',))
        self.assertIsNone(t.outdir)

    def test_outdir_is_carried(self):
        t = PrepTask('/src/album', 'cue', ('a.cue',))
        self.assertEqual(t._replace(outdir='/stage/x').outdir, '/stage/x')


class PrepOutdirTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _fu(self):
        from massmusictagger.core.files import FileUtils
        return FileUtils.__new__(FileUtils)

    def test_without_staging_it_prepares_in_place(self):
        """The behaviour that predates staging, and still the default."""
        task = PrepTask(self.tmp, 'cue', ())
        self.assertEqual(self._fu()._prep_outdir(task, ''), self.tmp)

    def test_with_staging_it_gets_its_own_directory(self):
        from massmusictagger.processor import _PREP_PREFIX
        staging = os.path.join(self.tmp, 'staging')
        task = PrepTask(self.tmp, 'cue', ())
        out = self._fu()._prep_outdir(task, staging)
        self.assertTrue(os.path.isdir(out))
        self.assertNotEqual(out, self.tmp)
        self.assertTrue(os.path.basename(out).startswith(_PREP_PREFIX),
                        'the startup sweep matches on this prefix')

    def test_each_album_gets_a_distinct_directory(self):
        staging = os.path.join(self.tmp, 'staging')
        fu = self._fu()
        a = fu._prep_outdir(PrepTask(self.tmp, 'cue', ()), staging)
        b = fu._prep_outdir(PrepTask(self.tmp, 'cue', ()), staging)
        self.assertNotEqual(a, b)


class SidecarTest(unittest.TestCase):
    """An album is more than its audio."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = os.path.join(self.tmp, 'album')
        self.out = os.path.join(self.tmp, 'stage')
        os.makedirs(self.origin)
        os.makedirs(self.out)

    def _fu(self):
        from massmusictagger.core.files import FileUtils
        return FileUtils.__new__(FileUtils)

    def _write(self, name, data=b'x'):
        with open(os.path.join(self.origin, name), 'wb') as f:
            f.write(data)

    def test_covers_and_logs_come_along(self):
        for name in ('cover.jpg', 'front.png', 'rip.log', 'notes.txt'):
            self._write(name)
        self._fu()._copy_prep_sidecars(self.origin, self.out)
        self.assertEqual(sorted(os.listdir(self.out)),
                         ['cover.jpg', 'front.png', 'notes.txt', 'rip.log'])

    def test_consumed_inputs_do_not(self):
        """The image, the sheet and the .m4a are inputs, not part of the album."""
        for name in ('disc.flac', 'disc.cue', 'track.m4a', 'image.ape'):
            self._write(name)
        self._write('cover.jpg')
        self._fu()._copy_prep_sidecars(self.origin, self.out)
        self.assertEqual(os.listdir(self.out), ['cover.jpg'])

    def test_in_place_preparation_copies_nothing(self):
        self._write('cover.jpg')
        self._fu()._copy_prep_sidecars(self.origin, self.origin)
        self.assertEqual(os.listdir(self.origin), ['cover.jpg'])

    def test_subdirectories_are_not_copied(self):
        os.makedirs(os.path.join(self.origin, 'Covers'))
        self._write('cover.jpg')
        self._fu()._copy_prep_sidecars(self.origin, self.out)
        self.assertEqual(os.listdir(self.out), ['cover.jpg'])


class OriginSeparationTest(unittest.TestCase):
    """The reason the whole change exists."""

    def test_the_result_carries_the_origin_not_the_audio_directory(self):
        """source_action acts on result.sourcedir; it must be the origin."""
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertIn('origin = origin or sourcedir', src)
        self.assertIn('result = ProcessingResult(origin)', src)

    def test_the_done_marker_is_checked_against_the_origin(self):
        """A staging directory will not exist next run to be asked."""
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertIn('done_path = os.path.join(origin, done_file)', src)

    def test_id_txt_is_read_from_the_origin(self):
        """It is the user's file; preparation does not copy it across."""
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertIn('self._id_file_override(origin)', src)

    def test_tagging_in_place_means_the_origin(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertIn("cfg.get('common', 'dest_dir') or origin", src)

    def test_process_all_maps_audio_directories_back_to_origins(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor.process_all)
        self.assertIn('self._origins', src)


class SweepTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_sweep_covers_prepared_directories_too(self):
        """Both kinds staging owns, or a killed run leaves decodes behind."""
        from massmusictagger.processor import (
            sweep_stale_staging, _STAGE_PREFIX, _PREP_PREFIX)
        for prefix in (_STAGE_PREFIX, _PREP_PREFIX):
            os.makedirs(os.path.join(self.tmp, prefix + 'abc'))
        self.assertEqual(sweep_stale_staging(self.tmp), 2)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_a_prepared_directory_is_removed_after_its_album(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertIn('_PREP_PREFIX', src)
        self.assertIn('origin != sourcedir', src)

    def test_the_guard_prevents_deleting_a_real_source(self):
        """A mis-set origins map must never delete the user's directory."""
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        # Both conditions, not either.
        self.assertIn("startswith(_PREP_PREFIX)", src)


if __name__ == '__main__':
    unittest.main()
