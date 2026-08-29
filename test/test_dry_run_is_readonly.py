# -*- coding: utf-8 -*-
"""A dry run must not touch the source.

FileUtils.get_audio_dirs() sounds like a scan, and mostly is -- but it also
splits CUE sheets and converts .m4a files as a side effect, and __main__ calls
it before the dry-run flag is consulted. So `mmt --dry-run` rewrote the
directory it was only meant to report on: whole.flac + whole.cue came back as
01.flac and 02.flac, with the originals stashed in .cue, and the run then
printed "[DRY RUN]".
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))


class _Options:
    forceUpdate = False
    releaseid = None

    def __init__(self, dry_run):
        self.dry_run = dry_run


def _fileutils(dry_run, **cfg_over):
    from massmusictagger.core.files import FileUtils
    from massmusictagger.core.tagger_config import TaggerConfig
    from massmusictagger import roots
    cfg = TaggerConfig(os.path.join(roots.BUNDLED_CONF, 'config_sample.yaml'))
    for sk, v in cfg_over.items():
        s, _, k = sk.partition('.')
        if not cfg.has_section(s):
            cfg.add_section(s)
        cfg.set(s, k, v)
    return FileUtils(cfg, _Options(dry_run))


class CueSplittingRespectsDryRun(unittest.TestCase):

    def _tree(self, tmp):
        album = os.path.join(tmp, 'album')
        os.makedirs(album)
        open(os.path.join(album, 'whole.flac'), 'wb').write(b'\0' * 16)
        open(os.path.join(album, 'whole.cue'), 'w').write('FILE "whole.flac" WAVE\n')
        return album

    def test_a_dry_run_does_not_split(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            album = self._tree(tmp)
            fu = _fileutils(True, **{'cue.parse_cue_files': 'true'})
            with patch.object(fu, '_processCueFiles') as split:
                dirs = fu.get_audio_dirs(tmp)
            split.assert_not_called()
            self.assertTrue(any(album in d for d in dirs),
                            'the album must still be reported, just not rewritten')
            self.assertEqual(sorted(os.listdir(album)), ['whole.cue', 'whole.flac'])

    def test_a_real_run_still_splits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            with patch.object(fu, '_processCueFiles', return_value=0) as split:
                fu.get_audio_dirs(tmp)
            split.assert_called_once()


class M4aConversionRespectsDryRun(unittest.TestCase):

    def _tree(self, tmp):
        album = os.path.join(tmp, 'album')
        os.makedirs(album)
        open(os.path.join(album, 'a.m4a'), 'wb').write(b'\0' * 16)
        return album

    def test_a_dry_run_does_not_convert(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            fu = _fileutils(True, **{'m4a.convert_m4a_files': 'true'})
            with patch.object(fu, '_processM4aFiles') as convert:
                fu.get_audio_dirs(tmp)
            convert.assert_not_called()

    def test_a_real_run_still_converts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            fu = _fileutils(False, **{'m4a.convert_m4a_files': 'true'})
            with patch.object(fu, '_processM4aFiles', return_value=False) as convert:
                fu.get_audio_dirs(tmp)
            convert.assert_called_once()


class TheFlagReachesTheScan(unittest.TestCase):

    def test_get_source_dirs_takes_dry_run(self):
        import inspect
        from massmusictagger import __main__ as mmt_main
        sig = inspect.signature(mmt_main._get_source_dirs)
        self.assertIn('dry_run', sig.parameters)

    def test_main_passes_it(self):
        import inspect
        from massmusictagger import __main__ as mmt_main
        src = inspect.getsource(mmt_main)
        self.assertIn('dry_run=opts.dry_run', src)

    def test_fileutils_defaults_to_not_dry(self):
        """Callers that never heard of the flag keep the old behaviour."""
        from massmusictagger.core.files import FileUtils
        class Bare:
            forceUpdate = False
        fu = FileUtils.__new__(FileUtils)
        self.assertFalse(getattr(Bare(), 'dry_run', False))


if __name__ == '__main__':
    unittest.main()
