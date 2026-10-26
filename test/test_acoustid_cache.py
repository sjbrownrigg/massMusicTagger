"""AcoustID answers are remembered, so a restart does not re-fingerprint.

Every restart used to re-run acoustid.match() for every album that had failed
the cheaper tiers -- decoding each track through fpcalc and querying AcoustID
again for an answer that had not changed. On the residue left in /incoming that
was most of a 45-minute stretch before anything was filed.

The cached value is AcoustID's answer, not a decision, so the comparison logic
still runs on it each time and a later matching fix still gets its chance.
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from massmusictagger.sources.musicbrainz.search import MBSearch


class _Conn:
    """Just enough of the connector for its cache helpers."""

    def __init__(self, root):
        self._cache_root = Path(root)
        self._cache_search = True

    @staticmethod
    def _load_json(path):
        try:
            return json.loads(Path(path).read_text())
        except Exception:
            return None

    @staticmethod
    def _save_json(path, data):
        Path(path).write_text(json.dumps(data))


class CacheTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.s = MBSearch.__new__(MBSearch)
        self.s._conn = _Conn(os.path.join(self.tmp, 'cache'))
        self.audio = os.path.join(self.tmp, 'a.flac')
        with open(self.audio, 'wb') as f:
            f.write(os.urandom(300000))

    def _match(self, path, answer=((0.95, 'rec-1', 'T', 'A'),)):
        fake = MagicMock()
        fake.match.return_value = list(answer)
        with patch.dict('sys.modules', {'acoustid': fake}):
            out = self.s._acoustid_match('key', path)
        return out, fake.match.call_count

    def test_a_second_lookup_does_not_fingerprint_again(self):
        _, first = self._match(self.audio)
        out, second = self._match(self.audio)
        self.assertEqual((first, second), (1, 0))
        self.assertEqual(out[0][1], 'rec-1')

    def test_the_same_audio_at_a_new_path_still_hits(self):
        """Staging writes prepared albums somewhere new on every run."""
        self._match(self.audio)
        moved = os.path.join(self.tmp, 'mmt-prep-xyz', 'a.flac')
        os.makedirs(os.path.dirname(moved))
        shutil.copy(self.audio, moved)
        _, calls = self._match(moved)
        self.assertEqual(calls, 0)

    def test_an_edited_file_is_fingerprinted_again(self):
        self._match(self.audio)
        with open(self.audio, 'r+b') as f:
            f.write(b'changed')
        _, calls = self._match(self.audio)
        self.assertEqual(calls, 1)

    def test_no_match_is_remembered_too(self):
        """That is the common case for the residue, and the whole point."""
        self._match(self.audio, answer=())
        _, calls = self._match(self.audio, answer=())
        self.assertEqual(calls, 0)

    def test_but_no_match_expires(self):
        """Fingerprints are submitted continually; unknown goes stale."""
        self._match(self.audio, answer=())
        for p in Path(self.tmp, 'cache', 'acoustid').glob('*.json'):
            raw = json.loads(p.read_text())
            raw['at'] = time.time() - MBSearch._ACOUSTID_EMPTY_TTL - 1
            p.write_text(json.dumps(raw))
        _, calls = self._match(self.audio, answer=())
        self.assertEqual(calls, 1)

    def test_a_match_does_not_expire(self):
        self._match(self.audio)
        for p in Path(self.tmp, 'cache', 'acoustid').glob('*.json'):
            raw = json.loads(p.read_text())
            raw['at'] = 0
            p.write_text(json.dumps(raw))
        _, calls = self._match(self.audio)
        self.assertEqual(calls, 0)

    def test_caching_off_means_no_cache(self):
        self.s._conn._cache_search = False
        self._match(self.audio)
        _, calls = self._match(self.audio)
        self.assertEqual(calls, 1)


class RecordingCacheTest(unittest.TestCase):

    def test_a_recording_is_looked_up_once(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        s = MBSearch.__new__(MBSearch)
        s._conn = _Conn(tmp)
        with patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs') as mb:
            mb.get_recording_by_id.return_value = {
                'recording': {'release-list': [{'id': 'rel-1'}]}}
            s._recording_releases('rec-1')
            out = s._recording_releases('rec-1')
        self.assertEqual(mb.get_recording_by_id.call_count, 1)
        self.assertEqual(out[0]['id'], 'rel-1')


class WiringTest(unittest.TestCase):

    def test_both_tiers_go_through_the_cache(self):
        import inspect
        for name in ('_acoustid_single', '_acoustid_multi'):
            src = inspect.getsource(getattr(MBSearch, name))
            self.assertIn('self._acoustid_match(', src, name)
            self.assertNotIn('acoustid.match(', src, name)


if __name__ == '__main__':
    unittest.main()
