# -*- coding: utf-8 -*-
"""id.txt: an explicit release ID that travels with the release.

--releaseid can only carry one ID per run. An id.txt sits in the directory it
describes, so one run over a tree can pin a different release for every album.
That is why it is the mechanism worth keeping.

It had stopped working: walk_dir_tree still treated a directory containing
id.txt as an album, but read_id_file -- which reads the ID out of it -- had no
callers, so the file was honoured as a marker and its contents ignored.
"""

import os
import sys
import textwrap
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))


class _Opts:
    forceUpdate = False
    dry_run = False


def _fu():
    from massmusictagger.core.files import FileUtils
    from massmusictagger.core.tagger_config import TaggerConfig
    from massmusictagger import roots
    cfg = TaggerConfig(os.path.join(roots.BUNDLED_CONF, 'config_sample.yaml'))
    return FileUtils(cfg, _Opts())


def _write(tmp, body):
    path = os.path.join(tmp, 'id.txt')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(textwrap.dedent(body))
    return path


class ReadIdFile(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def test_the_discogstagger3_format_still_works(self):
        _write(self.d, """\
            [source]
            name = discogs
            discogs_id = 14726546
        """)
        self.assertEqual(_fu().read_id_file(self.d), ('discogs', '14726546'))

    def test_musicbrainz_needs_nothing_declared_first(self):
        """discogstagger3 required a source.<name> mapping in the main config."""
        _write(self.d, """\
            [source]
            name = musicbrainz
            musicbrainz_id = 4fe0825c-7547-4f3f-adf3-a70ce762edc7
        """)
        self.assertEqual(
            _fu().read_id_file(self.d),
            ('musicbrainz', '4fe0825c-7547-4f3f-adf3-a70ce762edc7'))

    def test_no_file_is_not_an_error(self):
        self.assertEqual(_fu().read_id_file(self.d), (None, None))

    def test_a_file_with_no_source_section_is_ignored(self):
        _write(self.d, "[other]\nname = discogs\n")
        self.assertEqual(_fu().read_id_file(self.d), (None, None))

    def test_a_file_naming_no_source_is_ignored(self):
        _write(self.d, "[source]\ndiscogs_id = 123\n")
        self.assertEqual(_fu().read_id_file(self.d), (None, None))

    def test_a_source_with_no_matching_id_is_ignored(self):
        _write(self.d, "[source]\nname = discogs\nmusicbrainz_id = abc\n")
        self.assertEqual(_fu().read_id_file(self.d), (None, None))

    def test_unparseable_content_is_not_fatal(self):
        _write(self.d, "this is not an ini file at all\n= = =\n")
        self.assertEqual(_fu().read_id_file(self.d), (None, None))

    def test_it_does_not_leak_into_the_run_configuration(self):
        """The old version called self.config.read(idfile).

        That merged every album's id.txt into the shared configuration, so a
        value set for one directory was still set for the next.
        """
        _write(self.d, """\
            [source]
            name = discogs
            discogs_id = 14726546
        """)
        fu = _fu()
        before = fu.config.get('source', 'name')
        fu.read_id_file(self.d)
        self.assertEqual(fu.config.get('source', 'name'), before)
        self.assertIsNone(fu.config.get('source', 'discogs_id'))


class QualifiedReleaseIds(unittest.TestCase):
    """--releaseid was Discogs-only, so a bare ID keeps meaning that."""

    def _split(self, value):
        from massmusictagger.processor import _split_source_id
        return _split_source_id(value)

    def test_a_bare_id_names_no_source(self):
        self.assertEqual(self._split('14726546'), (None, '14726546'))

    def test_a_qualified_id_names_its_source(self):
        self.assertEqual(self._split('musicbrainz:abc-def'),
                         ('musicbrainz', 'abc-def'))

    def test_discogs_may_be_stated_explicitly(self):
        self.assertEqual(self._split('discogs:14726546'),
                         ('discogs', '14726546'))

    def test_nothing_is_nothing(self):
        self.assertEqual(self._split(None), (None, None))
        self.assertEqual(self._split(''), (None, None))


class OverrideRouting(unittest.TestCase):
    """A Discogs release number is not a near miss for MusicBrainz."""

    def _ctx(self, override, source):
        from massmusictagger.cascade import _Attempt
        return _Attempt(sourcedir='/x', cfg=None, discogs_connector=None,
                        discogs_local_connector=None, discogs_search=None,
                        mb_connector=None, mb_search=None,
                        release_id_override=override,
                        release_id_source=source)

    def _for(self, source, override, id_source):
        from massmusictagger.cascade import _override_for
        return _override_for(source, self._ctx(override, id_source))

    def test_an_unqualified_id_goes_to_every_source(self):
        """What --releaseid always did, kept for a bare value."""
        self.assertEqual(self._for('discogs', '123', None), '123')
        self.assertEqual(self._for('musicbrainz', '123', None), '123')

    def test_a_qualified_id_only_reaches_its_own_source(self):
        self.assertEqual(self._for('discogs', '123', 'discogs'), '123')
        self.assertIsNone(self._for('musicbrainz', '123', 'discogs'))

    def test_local_shares_the_discogs_numbering(self):
        self.assertEqual(self._for('local', '123', 'discogs'), '123')

    def test_no_override_stays_no_override(self):
        self.assertIsNone(self._for('discogs', None, 'discogs'))


if __name__ == '__main__':
    unittest.main()
