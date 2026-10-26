"""A transcode takes the audio and nothing else.

An m4a carries its cover as an attached video stream (mjpeg, attached_pic=1).
Without `-map 0:a`, ffmpeg's default stream selection takes that too and does
something different with it per container. FLAC and MP3 can hold a picture and
quietly embed it. Ogg cannot, so ffmpeg transcoded the cover into a Theora
*video* stream and put it first:

    source m4a  : 0 aac audio     1 mjpeg video (attached_pic)
    our ogg     : 0 theora video  1 vorbis audio

Mutagen then read the whole file as OggTheora and refused it. The Cassandra
Complex's *The Plague* failed on every track.
"""

import inspect
import unittest

from massmusictagger.core import files


class MapTest(unittest.TestCase):

    def _cmds(self):
        src = inspect.getsource(files)
        return [line for line in src.splitlines()
                if "['ffmpeg'" in line and "'-c:a'" in line]

    def test_every_audio_transcode_maps_audio_only(self):
        cmds = self._cmds()
        self.assertTrue(cmds, 'found no transcode commands to check')
        for line in cmds:
            self.assertIn("'-map', '0:a'", line, line.strip())

    def test_the_m4a_conversion_in_particular(self):
        src = inspect.getsource(files)
        self.assertIn("'-i', path, '-map', '0:a'", src)


class CommandTest(unittest.TestCase):
    """The command actually built for an AAC -> Ogg conversion."""

    def test_the_built_command_selects_audio(self):
        import os, tempfile, shutil
        from unittest.mock import MagicMock, patch
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        open(os.path.join(tmp, 'a.m4a'), 'wb').close()
        fu = files.FileUtils.__new__(files.FileUtils)
        fu.aac_action, fu.alac_action = 'convert_to_ogg', 'convert_to_flac'
        fu.ogg_quality, fu.mp3_quality, fu.flac_compression_level = '6', '2', '5'
        fu.m4a_done_dir = '.m4a'
        captured = []
        def run(cmd, **kw):
            captured.append(cmd)
            return MagicMock(returncode=0, stderr='')
        with patch.object(files, '_m4a_codec', return_value='aac'), \
             patch('subprocess.run', side_effect=run):
            try:
                fu._processM4aFiles(tmp, ['a.m4a'], outdir=tmp)
            except Exception:
                pass
        self.assertTrue(captured, 'no ffmpeg command was built')
        cmd = captured[0]
        i = cmd.index('-map')
        self.assertEqual(cmd[i + 1], '0:a')


if __name__ == '__main__':
    unittest.main()
