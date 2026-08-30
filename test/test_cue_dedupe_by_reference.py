"""A cue sheet naming audio that is not present cannot split anything.

An EAC rip commonly leaves two sheets per disc: the real one, and an ISRC
sheet pointing at the scratch file it ripped through -- `FILE "Range.wav"` --
which was never kept. Two sheets against one image defeat the single-file
test, so the disc is never split and reaches the tagger as one untagged track
that matches nothing.

Nick Cave's Lovely Creatures arrived exactly so: six sheets, three images.
Grouping by filename could not pair them -- one sheet carries the artist
prefix, the other an "ISRC" suffix, sharing no stem at all. Asking the sheet
what it references is the reliable question.
"""

import os
import shutil
import tempfile
import unittest

from massmusictagger.core.files import cue_referenced_file, dedupe_cue_sheets


class ReferencedFileTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _cue(self, name, body, encoding='utf-8'):
        path = os.path.join(self.tmp, name)
        with open(path, 'wb') as f:
            f.write(body.encode(encoding))
        return path

    def test_quoted_filename(self):
        p = self._cue('a.cue', 'FILE "album.flac" WAVE\n  TRACK 01 AUDIO\n')
        self.assertEqual(cue_referenced_file(p), 'album.flac')

    def test_leading_metadata_before_the_file_line(self):
        p = self._cue('a.cue', 'REM GENRE "Rock"\nPERFORMER "X"\n'
                               'FILE "disc.flac" WAVE\n')
        self.assertEqual(cue_referenced_file(p), 'disc.flac')

    def test_latin1_sheet_is_still_read(self):
        """Sheets come from rippers on every platform and are rarely declared."""
        p = self._cue('a.cue', 'REM COMMENT "café"\nFILE "album.flac" WAVE\n',
                      encoding='latin-1')
        self.assertEqual(cue_referenced_file(p), 'album.flac')

    def test_utf16_sheet_is_still_read(self):
        p = self._cue('a.cue', 'FILE "album.flac" WAVE\n', encoding='utf-16')
        self.assertEqual(cue_referenced_file(p), 'album.flac')

    def test_no_file_line(self):
        p = self._cue('a.cue', 'REM nothing here\n')
        self.assertEqual(cue_referenced_file(p), '')

    def test_missing_sheet(self):
        self.assertEqual(cue_referenced_file('/nonexistent.cue'), '')


class DedupeByReferenceTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, body=''):
        with open(os.path.join(self.tmp, name), 'w') as f:
            f.write(body)

    def test_the_lovely_creatures_shape(self):
        """Real sheet plus an EAC ISRC sheet pointing at a scratch file."""
        self._write('Artist - Album CD1.flac')
        self._write('Artist - Album CD1.cue', 'FILE "Artist - Album CD1.flac" WAVE\n')
        self._write('Album CD1 ISRC.cue', 'FILE "Range.wav" WAVE\n')

        kept = dedupe_cue_sheets(
            ['Artist - Album CD1.cue', 'Album CD1 ISRC.cue'],
            ['Artist - Album CD1.flac'],
            directory=self.tmp)

        self.assertEqual(kept, ['Artist - Album CD1.cue'])

    def test_counts_match_so_the_disc_can_be_split(self):
        """The whole point: one sheet, one image."""
        self._write('disc.flac')
        self._write('disc.cue', 'FILE "disc.flac" WAVE\n')
        self._write('disc ISRC.cue', 'FILE "Range.wav" WAVE\n')
        kept = dedupe_cue_sheets(['disc.cue', 'disc ISRC.cue'], ['disc.flac'],
                                 directory=self.tmp)
        self.assertEqual(len(kept), 1)

    def test_a_sheet_with_no_file_line_is_not_discarded(self):
        """Saying nothing is not evidence against it."""
        self._write('disc.flac')
        self._write('quiet.cue', 'REM nothing\n')
        kept = dedupe_cue_sheets(['quiet.cue'], ['disc.flac'], directory=self.tmp)
        self.assertEqual(kept, ['quiet.cue'])

    def test_nothing_is_discarded_when_no_sheet_resolves(self):
        """A directory where none resolve says the check does not apply."""
        self._write('disc.flac')
        self._write('a.cue', 'FILE "missing-one.flac" WAVE\n')
        self._write('b.cue', 'FILE "missing-two.flac" WAVE\n')
        kept = dedupe_cue_sheets(['a.cue', 'b.cue'], ['disc.flac'],
                                 directory=self.tmp)
        self.assertEqual(sorted(kept), ['a.cue', 'b.cue'])

    def test_without_a_directory_the_old_behaviour_stands(self):
        """Callers that cannot say where the files are keep working."""
        kept = dedupe_cue_sheets(['a.cue'], ['a.flac'])
        self.assertEqual(kept, ['a.cue'])

    def test_the_original_duplicate_shape_still_dedupes(self):
        """album.cue beside album.flac.cue -- what this was written for."""
        self._write('album.flac')
        self._write('album.cue', 'FILE "album.flac" WAVE\n')
        self._write('album.flac.cue', 'FILE "album.flac" WAVE\n')
        kept = dedupe_cue_sheets(['album.cue', 'album.flac.cue'], ['album.flac'],
                                 directory=self.tmp)
        self.assertEqual(len(kept), 1)


if __name__ == '__main__':
    unittest.main()


class MultiDiscPathsTest(unittest.TestCase):
    """The scan gathers sheets from every disc subdirectory into one list.

    So dedupe_cue_sheets receives absolute paths spanning CD1/, CD2/, CD3/
    while `directory` is the album root. Resolving a sheet's FILE against the
    root looks for CD1's image beside CD2's and finds neither, so every sheet
    reads as unusable and the guard keeps them all -- which is exactly how the
    first attempt at this silently changed nothing.

    A cue's FILE is relative to the sheet, not to the album.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cues, self.audio = [], []
        for disc in ('CD1', 'CD2'):
            d = os.path.join(self.tmp, disc)
            os.makedirs(d)
            flac = f'Artist - Album {disc}.flac'
            open(os.path.join(d, flac), 'wb').close()
            real = os.path.join(d, f'Artist - Album {disc}.cue')
            with open(real, 'w') as f:
                f.write(f'FILE "{flac}" WAVE\n')
            isrc = os.path.join(d, f'Album {disc} ISRC.cue')
            with open(isrc, 'w') as f:
                f.write('FILE "Range.wav" WAVE\n')
            self.cues += [real, isrc]
            self.audio.append(os.path.join(d, flac))

    def test_absolute_paths_across_disc_directories(self):
        kept = dedupe_cue_sheets(self.cues, self.audio, directory=self.tmp)
        self.assertEqual(len(kept), 2, 'one sheet per disc')

    def test_the_counts_then_match_so_the_set_is_split(self):
        kept = dedupe_cue_sheets(self.cues, self.audio, directory=self.tmp)
        self.assertEqual(len(kept), len(self.audio),
                         'equal counts are what the single-file test needs')

    def test_the_scratch_sheets_are_the_ones_dropped(self):
        kept = dedupe_cue_sheets(self.cues, self.audio, directory=self.tmp)
        self.assertFalse([c for c in kept if 'ISRC' in c],
                         'the sheet naming Range.wav must go, not the real one')
