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


class ScanReadsPrepareWrites(unittest.TestCase):
    """Discovery and transformation are separate stages now.

    They were one function: get_audio_dirs() walked the tree and split CUE
    sheets and transcoded .m4a as it went, so "list the albums" rewrote the
    library. Splitting them also means a conversion failure can be reported
    as one, instead of surfacing later as "no audio source directories found".
    """

    def _album(self, tmp):
        album = os.path.join(tmp, 'album')
        os.makedirs(album)
        open(os.path.join(album, 'whole.flac'), 'wb').write(b'\0' * 16)
        open(os.path.join(album, 'whole.cue'), 'w').write('FILE "whole.flac" WAVE\n')
        return album

    def test_scan_never_writes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            album = self._album(tmp)
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            with patch.object(fu, '_processCueFiles') as split, \
                 patch.object(fu, '_processM4aFiles') as convert:
                dirs, tasks = fu.scan(tmp)
            split.assert_not_called()
            convert.assert_not_called()
            self.assertEqual(sorted(os.listdir(album)), ['whole.cue', 'whole.flac'])
            self.assertTrue(any(album in d for d in dirs))
            self.assertEqual([t.kind for t in tasks], ['cue'])

    def test_prepare_runs_what_scan_found(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._album(tmp)
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            _, tasks = fu.scan(tmp)
            with patch.object(fu, '_processCueFiles', return_value=0) as split:
                prepared, failed = fu.prepare(tasks)
            split.assert_called_once()
            self.assertEqual(len(prepared), 1)
            self.assertEqual(failed, [])

    def test_a_failed_preparation_is_reported_not_swallowed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._album(tmp)
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            _, tasks = fu.scan(tmp)
            with patch.object(fu, '_processCueFiles', return_value=1):
                prepared, failed = fu.prepare(tasks)
            self.assertEqual(prepared, [])
            self.assertEqual(len(failed), 1)

    def test_one_broken_album_does_not_stop_the_batch(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('a', 'b'):
                d = os.path.join(tmp, name)
                os.makedirs(d)
                open(os.path.join(d, 'whole.flac'), 'wb').write(b'\0' * 16)
                open(os.path.join(d, 'whole.cue'), 'w').write('FILE "x" WAVE\n')
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            _, tasks = fu.scan(tmp)
            self.assertEqual(len(tasks), 2)
            calls = {'n': 0}
            def flaky(dirpath, files, outdir=None):
                calls['n'] += 1
                if calls['n'] == 1:
                    raise OSError('broken cue')
                return 0
            with patch.object(fu, '_processCueFiles', side_effect=flaky):
                prepared, failed = fu.prepare(tasks)
            self.assertEqual(len(prepared), 1)
            self.assertEqual(len(failed), 1)

    def test_prepare_honours_dry_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._album(tmp)
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            _, tasks = fu.scan(tmp)
            with patch.object(fu, '_processCueFiles') as split:
                prepared, failed = fu.prepare(tasks, dry_run=True)
            split.assert_not_called()
            self.assertEqual((prepared, failed), ([], []))

    def test_main_runs_the_two_stages_separately(self):
        import inspect
        from massmusictagger import __main__ as mmt_main
        src = inspect.getsource(mmt_main._get_source_dirs)
        self.assertIn('fu.scan(source_dir)', src)
        self.assertIn('fu.prepare(prep_tasks', src)


class ADryRunSaysWhyACueAlbumCannotMatch(unittest.TestCase):
    """A dry run does not split, so a CUE album has nothing to match on.

    That is correct -- the flag promises not to write -- but it reports the
    album as failed, which reads as a prediction about the real run. It is
    not: the real run splits first and matches the tracks.
    """

    def test_it_warns(self):
        import tempfile, logging
        with tempfile.TemporaryDirectory() as tmp:
            album = os.path.join(tmp, 'album')
            os.makedirs(album)
            open(os.path.join(album, 'whole.flac'), 'wb').write(b'\0' * 16)
            open(os.path.join(album, 'whole.cue'), 'w').write('FILE "x" WAVE\n')
            fu = _fileutils(True, **{'cue.parse_cue_files': 'true'})
            _, tasks = fu.scan(tmp)
            with self.assertLogs('massmusictagger.core.files', level='WARNING') as cm:
                fu.prepare(tasks, dry_run=True)
        joined = '\n'.join(cm.output)
        self.assertIn('single-file CUE album', joined)
        self.assertIn('--dry-run', joined)

    def test_a_real_run_does_not_warn(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            album = os.path.join(tmp, 'album')
            os.makedirs(album)
            open(os.path.join(album, 'whole.flac'), 'wb').write(b'\0' * 16)
            open(os.path.join(album, 'whole.cue'), 'w').write('FILE "x" WAVE\n')
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            _, tasks = fu.scan(tmp)
            with patch.object(fu, '_processCueFiles', return_value=0):
                with self.assertNoLogs('massmusictagger.core.files', level='WARNING'):
                    fu.prepare(tasks)


class DuplicateCueSheets(unittest.TestCase):
    """A ripper often leaves two sheets describing the same album.

    "album.cue" beside "album.flac.cue", or "album FLAC.CUE" beside
    "album WAV.CUE". Counted separately they outnumber the audio, and the
    test for a single-file album is that the counts match -- so a genuine
    one-file rip with a spare sheet was never split. It reached the tagger as
    one untagged track and matched nothing.
    """

    def _dedupe(self, cues, audio):
        from massmusictagger.core.files import dedupe_cue_sheets
        return sorted(dedupe_cue_sheets(cues, audio))

    def test_a_format_suffixed_duplicate_collapses(self):
        self.assertEqual(
            self._dedupe(['Modern Blues.cue', 'Modern Blues.flac.cue'],
                         ['01 Modern Blues.flac']),
            ['Modern Blues.flac.cue'])

    def test_a_space_separated_format_word_collapses(self):
        self.assertEqual(
            self._dedupe(['Ziggy Disc 1 FLAC.CUE', 'Ziggy Disc 1 WAV.CUE'],
                         ['01.flac']),
            ['Ziggy Disc 1 FLAC.CUE'])

    def test_the_sheet_naming_the_format_present_is_preferred(self):
        self.assertEqual(
            self._dedupe(['x WAV.CUE', 'x FLAC.CUE'], ['01.flac']),
            ['x FLAC.CUE'])

    def test_genuinely_different_albums_are_not_merged(self):
        self.assertEqual(
            self._dedupe(['disc one.cue', 'disc two.cue'], ['a.flac', 'b.flac']),
            ['disc one.cue', 'disc two.cue'])

    def test_a_single_sheet_is_unchanged(self):
        self.assertEqual(self._dedupe(['album.cue'], ['a.flac']), ['album.cue'])

    def test_a_one_file_album_with_a_spare_sheet_is_split(self):
        """The case this exists for, through scan()."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            album = os.path.join(tmp, 'album')
            os.makedirs(album)
            open(os.path.join(album, 'whole.flac'), 'wb').write(b'\0' * 16)
            for name in ('whole.cue', 'whole.flac.cue'):
                open(os.path.join(album, name), 'w').write('FILE "whole.flac" WAVE\n')
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            _, tasks = fu.scan(tmp)
        self.assertEqual([t.kind for t in tasks], ['cue'])
        self.assertEqual(len(tasks[0].files), 1)

    def test_an_already_split_album_is_still_left_alone(self):
        """1 sheet describing 11 separate tracks is not a single-file rip."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            album = os.path.join(tmp, 'album')
            os.makedirs(album)
            for i in range(11):
                open(os.path.join(album, f'{i:02d}.flac'), 'wb').write(b'\0' * 16)
            for name in ('set FLAC.CUE', 'set WAV.CUE'):
                open(os.path.join(album, name), 'w').write('FILE "x" WAVE\n')
            fu = _fileutils(False, **{'cue.parse_cue_files': 'true'})
            _, tasks = fu.scan(tmp)
        self.assertEqual([t.kind for t in tasks], [])
