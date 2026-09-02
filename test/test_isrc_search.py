"""Finding a release by the recordings it carries.

An ISRC identifies a recording, not a release, so no single code answers the
question: the same recording sits on the album, the single, and every
compilation that ever licensed it. Agreement answers it — the release carrying
several of this directory's recordings is the release this directory is.

Worth having because the codes are already present. 55% of a sample of files
in /incoming carry one, and EAC writes them into CUE sheets too, so a rip that
has never been near a metadata service still arrives with identifiers on it.
"""

import unittest
from unittest.mock import MagicMock, patch

from massmusictagger.sources.musicbrainz.search import MBSearch


def _searcher():
    s = MBSearch.__new__(MBSearch)
    s._conn = None
    return s


def _isrc_reply(*release_ids):
    return {'isrc': {'recording-list': [
        {'release-list': [{'id': r} for r in release_ids]}]}}


class CollectTest(unittest.TestCase):

    def _files(self, codes):
        objs = {}
        for i, c in enumerate(codes):
            m = MagicMock(); m.isrc = c
            objs['f%d' % i] = m
        return objs

    def _collect(self, codes, limit=4):
        objs = self._files(codes)
        with patch('massmusictagger.sources.musicbrainz.search.MediaFile',
                   side_effect=lambda p: objs[p]):
            return MBSearch._collect_isrcs(list(objs), limit)

    def test_codes_are_normalised(self):
        self.assertEqual(self._collect(['gb-ajh-04-01310']), ['GBAJH0401310'])

    def test_duplicates_are_dropped(self):
        """One recording used twice corroborates nothing."""
        self.assertEqual(self._collect(['GBAJH0401310', 'GBAJH0401310']),
                         ['GBAJH0401310'])

    def test_files_without_a_code_are_skipped(self):
        self.assertEqual(self._collect([None, '', 'GBAJH0401310']),
                         ['GBAJH0401310'])

    def test_malformed_codes_are_rejected(self):
        self.assertEqual(self._collect(['NOTANISRC', 'GBAJH0401310']),
                         ['GBAJH0401310'])

    def test_the_limit_bounds_the_lookups(self):
        codes = ['GBAJH040131%d' % i for i in range(6)]
        self.assertEqual(len(self._collect(codes, limit=3)), 3)


class AgreementTest(unittest.TestCase):

    def _search(self, replies, files=('a', 'b', 'c')):
        s = _searcher()
        codes = ['GBAJH040131%d' % i for i in range(len(files))]
        objs = {f: MagicMock(isrc=c) for f, c in zip(files, codes)}
        with patch('massmusictagger.sources.musicbrainz.search.MediaFile',
                   side_effect=lambda p: objs[p]), \
             patch('massmusictagger.sources.musicbrainz.search.'
                   'musicbrainzngs.get_recordings_by_isrc',
                   side_effect=replies):
            return s._isrc_search(list(files))

    def test_a_release_carrying_two_recordings_wins(self):
        self.assertEqual(
            self._search([_isrc_reply('ALBUM'), _isrc_reply('ALBUM'),
                          _isrc_reply('ALBUM')]),
            'ALBUM')

    def test_one_agreement_is_not_enough(self):
        """A single shared recording names every compilation it ever reached."""
        self.assertIsNone(
            self._search([_isrc_reply('COMP-A'), _isrc_reply('COMP-B'),
                          _isrc_reply('COMP-C')]))

    def test_the_album_beats_a_compilation_that_shares_one_track(self):
        self.assertEqual(
            self._search([_isrc_reply('ALBUM', 'COMP'), _isrc_reply('ALBUM'),
                          _isrc_reply('ALBUM')]),
            'ALBUM')

    def test_a_code_nothing_knows_is_not_an_error(self):
        self.assertEqual(
            self._search([Exception('404'), _isrc_reply('ALBUM'),
                          _isrc_reply('ALBUM')]),
            'ALBUM')

    def test_too_few_codes_means_no_lookup_at_all(self):
        called = []
        s = _searcher()
        objs = {'a': MagicMock(isrc='GBAJH0401310')}
        with patch('massmusictagger.sources.musicbrainz.search.MediaFile',
                   side_effect=lambda p: objs[p]), \
             patch('massmusictagger.sources.musicbrainz.search.'
                   'musicbrainzngs.get_recordings_by_isrc',
                   side_effect=lambda *a, **k: called.append(1)):
            self.assertIsNone(s._isrc_search(['a']))
        self.assertEqual(called, [], 'no API call on a single code')


class LadderTest(unittest.TestCase):

    def test_isrc_runs_after_barcode_and_before_discid(self):
        import inspect
        src = inspect.getsource(MBSearch.search)
        self.assertLess(src.index('self._barcode_search'), src.index('self._isrc_search'))
        self.assertLess(src.index('self._isrc_search'), src.index('self._discid_search'))


if __name__ == '__main__':
    unittest.main()
