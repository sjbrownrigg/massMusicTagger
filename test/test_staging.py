"""Assembling an album on local disk before copying it to the destination.

Tagging otherwise reads the source from the share and writes it back there,
then ReplayGain reads the destination again and tagging rewrites it -- every
pass crossing the link. Measured NAS-to-NAS: 9.8 MiB/s, against 1280 MiB/s
local.

The dangerous part is not the speed but the ordering: the source is archived
or deleted only after the output is verified to hold audio, and that check
looks at `result.target_dir`. If staging moved the album without updating
that, the check would verify a directory that no longer exists -- or worse,
pass against the staging copy just before it was cleaned up. These tests pin
the ordering as much as the paths.
"""

import os
import shutil
import tempfile
import unittest

from massmusictagger.processor import _move_staged, _stage_root


class _Cfg:
    def __init__(self, value=None, raises=False):
        self._value = value
        self._raises = raises

    def get(self, section, option):
        if self._raises:
            raise KeyError(option)
        return self._value


class StageRootTest(unittest.TestCase):

    def test_absent_setting_disables_staging(self):
        self.assertEqual(_stage_root(_Cfg('')), '')
        self.assertEqual(_stage_root(_Cfg(None)), '')

    def test_whitespace_only_disables_staging(self):
        self.assertEqual(_stage_root(_Cfg('   ')), '')

    def test_a_config_without_the_key_does_not_raise(self):
        """Older configs predate the key; they must keep working."""
        self.assertEqual(_stage_root(_Cfg(raises=True)), '')

    def test_a_path_is_expanded(self):
        self.assertEqual(_stage_root(_Cfg('~/staging')),
                         os.path.expanduser('~/staging'))


class MoveStagedTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.staging = os.path.join(self.tmp, 'staging')
        self.final = os.path.join(self.tmp, 'sorted')
        os.makedirs(self.staging)
        os.makedirs(self.final)

    def _staged_album(self, rel='Artist/Album', tracks=2):
        path = os.path.join(self.staging, rel)
        os.makedirs(path)
        for i in range(1, tracks + 1):
            open(os.path.join(path, f'{i:02d}.flac'), 'wb').close()
        return path

    def test_the_album_lands_at_the_same_relative_path(self):
        staged = self._staged_album()
        out = _move_staged(staged, self.staging, self.final)
        self.assertEqual(out, os.path.join(self.final, 'Artist', 'Album'))
        self.assertTrue(os.path.isdir(out))

    def test_the_files_come_with_it(self):
        staged = self._staged_album(tracks=3)
        out = _move_staged(staged, self.staging, self.final)
        self.assertEqual(
            sorted(f for f in os.listdir(out) if f.endswith('.flac')),
            ['01.flac', '02.flac', '03.flac'])

    def test_staging_is_left_empty_of_the_album(self):
        staged = self._staged_album()
        _move_staged(staged, self.staging, self.final)
        self.assertFalse(os.path.exists(staged))

    def test_disc_subdirectories_survive(self):
        staged = os.path.join(self.staging, 'Artist/Album')
        for disc in ('CD 1', 'CD 2'):
            os.makedirs(os.path.join(staged, disc))
            open(os.path.join(staged, disc, '01.flac'), 'wb').close()
        out = _move_staged(staged, self.staging, self.final)
        self.assertTrue(os.path.isfile(os.path.join(out, 'CD 1', '01.flac')))
        self.assertTrue(os.path.isfile(os.path.join(out, 'CD 2', '01.flac')))

    def test_a_collision_is_suffixed_not_overwritten(self):
        """Losing an album to a name clash is worse than an odd folder name."""
        existing = os.path.join(self.final, 'Artist', 'Album')
        os.makedirs(existing)
        open(os.path.join(existing, 'keep-me.flac'), 'wb').close()

        staged = self._staged_album()
        out = _move_staged(staged, self.staging, self.final)

        self.assertEqual(out, existing + ' (2)')
        # The original is untouched.
        self.assertTrue(os.path.isfile(os.path.join(existing, 'keep-me.flac')))

    def test_repeated_collisions_keep_counting(self):
        for suffix in ('', ' (2)'):
            path = os.path.join(self.final, 'Artist', 'Album' + suffix)
            os.makedirs(path)
        staged = self._staged_album()
        out = _move_staged(staged, self.staging, self.final)
        self.assertTrue(out.endswith('Album (3)'))

    def test_missing_intermediate_directories_are_created(self):
        staged = self._staged_album(rel='New Artist/Deep/Album')
        out = _move_staged(staged, self.staging, self.final)
        self.assertTrue(os.path.isdir(out))


class OrderingTest(unittest.TestCase):
    """The source must not be touched until the album is at its real home."""

    def test_target_dir_is_updated_before_post_processing(self):
        import inspect
        from massmusictagger import processor

        src = inspect.getsource(processor.MassProcessor._process_one)
        move_at = src.index('_move_staged')
        post_at = src.index('_post_process_source(result')
        self.assertLess(move_at, post_at,
                        'the album must leave staging before the source is '
                        'archived or deleted')
        self.assertIn('result.target_dir = album.target_dir', src)

    def test_staging_is_cleaned_up_on_failure(self):
        """A failed album must not leave gigabytes behind."""
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertIn('finally:', src)
        self.assertIn('shutil.rmtree(staged, ignore_errors=True)', src)


if __name__ == '__main__':
    unittest.main()
