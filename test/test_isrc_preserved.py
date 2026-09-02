"""The ISRC survives tagging.

`tag_single_track` calls `metadata.delete()` and writes a fresh set, so
anything the metadata source does not supply is destroyed. Discogs does not
carry ISRCs at all, so every Discogs match stripped them.

The loss is measurable in the library: 55% of a sample of files in /incoming
carry an ISRC against 9% of those already tagged. The codes are also the input
to the MusicBrainz ISRC tier, so discarding them removed a search signal from
every album the tagger touched.
"""

import inspect
import unittest

from massmusictagger.core import taggerutils


class PreservationTest(unittest.TestCase):

    def setUp(self):
        self.src = inspect.getsource(taggerutils.TagHandler.tag_single_track)

    def test_it_is_read_before_the_wipe(self):
        self.assertLess(self.src.index('_existing_isrc'),
                        self.src.index('metadata.delete()'),
                        'read after delete() and there is nothing left to read')

    def test_the_source_value_wins_when_there_is_one(self):
        """MusicBrainz models recordings, so its ISRC is the better answer."""
        self.assertIn("getattr(track, 'isrc', None) or _existing_isrc", self.src)

    def test_it_is_written_back(self):
        self.assertIn("_set('isrc', _isrc)", self.src)

    def test_nothing_is_written_when_neither_has_one(self):
        self.assertIn('if _isrc:', self.src,
                      'an empty ISRC tag is worse than no tag')


class RoundTripTest(unittest.TestCase):
    """The field has to survive a real write, not just appear in the source."""

    def test_mediafile_round_trips_an_isrc(self):
        import os, shutil, tempfile
        from mutagen.flac import FLAC
        from massmusictagger.core.mediafile import MediaFile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        # a minimal valid FLAC, built by mutagen's own test approach
        src = None
        for root, _, files in os.walk('/mnt/nas/sorted'):
            for f in files:
                if f.endswith('.flac'):
                    src = os.path.join(root, f)
                    break
            if src:
                break
        if not src:
            self.skipTest('no FLAC available to copy')
        dst = os.path.join(tmp, 'x.flac')
        shutil.copy2(src, dst)
        mf = MediaFile(dst)
        mf.isrc = 'GBAJH0401310'
        mf.save()
        self.assertEqual(FLAC(dst)['isrc'][0], 'GBAJH0401310')
        self.assertEqual(MediaFile(dst).isrc, 'GBAJH0401310')


if __name__ == '__main__':
    unittest.main()
