"""Tests for the cascade source-selection logic."""
import os
import sys
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))


MMT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'conf', 'config.yaml')


class TestGetPriority(unittest.TestCase):
    """_get_priority() reads source.priority from config."""

    def _make_cfg(self, priority=None, name=None):
        from discogstagger.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if priority is not None:
            cfg.set('source', 'priority', priority)
        if name is not None:
            cfg.set('source', 'name', name)
        return cfg

    def test_list_syntax(self):
        from massmusictagger.cascade import _get_priority
        cfg = self._make_cfg(priority="['discogs', 'musicbrainz', 'existing_tags']")
        self.assertEqual(_get_priority(cfg), ['discogs', 'musicbrainz', 'existing_tags'])

    def test_comma_string(self):
        from massmusictagger.cascade import _get_priority
        cfg = self._make_cfg(priority='discogs, musicbrainz')
        self.assertEqual(_get_priority(cfg), ['discogs', 'musicbrainz'])

    def test_legacy_name_fallback(self):
        from massmusictagger.cascade import _get_priority
        cfg = self._make_cfg(name='discogs')
        # Remove 'priority' so that the fallback to legacy 'name' is exercised
        cfg.remove_option('source', 'priority')
        self.assertEqual(_get_priority(cfg), ['discogs'])

    def test_musicbrainz_first(self):
        from massmusictagger.cascade import _get_priority
        cfg = self._make_cfg(priority='musicbrainz, discogs, existing_tags')
        self.assertEqual(_get_priority(cfg)[0], 'musicbrainz')


class TestExistingTagsFallback(unittest.TestCase):
    """existing_tags fallback builds an Album from embedded metadata."""

    def setUp(self):
        import tempfile, shutil
        self.tmpdir = tempfile.mkdtemp()
        # Create a minimal fake FLAC using discogstagger3's test fixture
        dt3 = os.path.join(parentdir, '..', 'discogstagger3', 'test', 'files', 'test.flac')
        if os.path.exists(dt3):
            import shutil as sh
            for i in range(1, 4):
                sh.copy(dt3, os.path.join(self.tmpdir, f'0{i}.flac'))
            self._has_files = True
        else:
            self._has_files = False

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_none_when_no_audio(self):
        import tempfile
        from discogstagger.tagger_config import TaggerConfig
        from massmusictagger.cascade import _map_existing_tags
        empty = tempfile.mkdtemp()
        try:
            cfg = TaggerConfig(MMT_CONFIG)
            result = _map_existing_tags(empty, cfg)
            self.assertIsNone(result)
        finally:
            import shutil; shutil.rmtree(empty, ignore_errors=True)

    @unittest.skipUnless(
        os.path.exists(os.path.join(
            os.path.dirname(__file__), '..', '..', 'discogstagger3', 'test', 'files', 'test.flac'
        )),
        'requires discogstagger3 test fixture'
    )
    def test_album_built_from_files(self):
        from discogstagger.tagger_config import TaggerConfig
        from massmusictagger.cascade import _map_existing_tags
        cfg = TaggerConfig(MMT_CONFIG)
        album = _map_existing_tags(self.tmpdir, cfg)
        self.assertIsNotNone(album)
        self.assertEqual(album.source, 'existing_tags')
        self.assertEqual(len(album.discs[0].tracks), 3)


class TestIdTxtReader(unittest.TestCase):
    """_read_id_txt() returns the right value for various id.txt formats."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_id(self, content):
        path = os.path.join(self.tmpdir, 'id.txt')
        with open(path, 'w') as fh:
            fh.write(content)

    def _make_cfg(self):
        from discogstagger.tagger_config import TaggerConfig
        return TaggerConfig(MMT_CONFIG)

    def _read(self, key=None):
        from massmusictagger.cascade import _read_id_txt
        return _read_id_txt(self.tmpdir, self._make_cfg(), key=key)

    def test_plain_id(self):
        self._write_id('12345678\n')
        self.assertEqual(self._read(), '12345678')

    def test_mbid_key(self):
        self._write_id('12345678\nmbid=550e8400-e29b-41d4-a716-446655440000\n')
        self.assertEqual(self._read(key='mbid'), '550e8400-e29b-41d4-a716-446655440000')

    def test_missing_key_returns_none(self):
        self._write_id('12345678\n')
        self.assertIsNone(self._read(key='mbid'))

    def test_comment_lines_ignored(self):
        self._write_id('# Discogs release\n12345678\n')
        self.assertEqual(self._read(), '12345678')

    def test_no_file_returns_none(self):
        self.assertIsNone(self._read())


# ── Source format hints ────────────────────────────────────────────────────────

class TestFolderFormatHint(unittest.TestCase):
    """_folder_format_hint() classifies a folder by keyword matching."""

    HINTS = {'digital': ['24 Bit', 'Remaster'], 'vinyl': ['Vinyl Rip']}

    def test_digital_keyword_matched(self):
        from massmusictagger.cascade import _folder_format_hint
        self.assertEqual('digital',
                         _folder_format_hint('/x/Artist/2020 - Album (24 Bit)', self.HINTS))

    def test_vinyl_keyword_matched(self):
        from massmusictagger.cascade import _folder_format_hint
        self.assertEqual('vinyl',
                         _folder_format_hint('/x/Artist/Album Vinyl Rip', self.HINTS))

    def test_no_match_returns_empty(self):
        from massmusictagger.cascade import _folder_format_hint
        self.assertEqual('',
                         _folder_format_hint('/x/Artist/Plain Album', self.HINTS))

    def test_empty_hints_returns_empty(self):
        from massmusictagger.cascade import _folder_format_hint
        self.assertEqual('', _folder_format_hint('/x/any', {}))

    def test_case_insensitive(self):
        from massmusictagger.cascade import _folder_format_hint
        self.assertEqual('digital',
                         _folder_format_hint('/x/24 bit album', self.HINTS))

    def test_uses_basename_only(self):
        """Keyword in a parent directory component is not matched."""
        from massmusictagger.cascade import _folder_format_hint
        self.assertEqual('',
                         _folder_format_hint('/x/24 Bit Collection/Plain Album', self.HINTS))


class TestLoadSourceHints(unittest.TestCase):
    """_load_source_hints() reads keyword lists from YAML, returns {} on error."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, hints_path=''):
        from discogstagger.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if not cfg.has_section('musicbrainz'):
            cfg.add_section('musicbrainz')
        cfg.set('musicbrainz', 'source_hints_file', hints_path)
        return cfg

    def test_returns_dict_from_valid_yaml(self):
        import yaml
        from massmusictagger.cascade import _load_source_hints
        hints_file = os.path.join(self.tmpdir, 'hints.yaml')
        with open(hints_file, 'w') as f:
            yaml.dump({'source_hints': {'digital': ['WEB'], 'vinyl': ['Vinyl Rip']}}, f)
        result = _load_source_hints(self._make_cfg(hints_file))
        self.assertEqual(result, {'digital': ['WEB'], 'vinyl': ['Vinyl Rip']})

    def test_missing_file_returns_empty(self):
        from massmusictagger.cascade import _load_source_hints
        result = _load_source_hints(self._make_cfg('/nonexistent/hints.yaml'))
        self.assertEqual(result, {})

    def test_empty_path_returns_empty(self):
        from massmusictagger.cascade import _load_source_hints
        self.assertEqual(_load_source_hints(self._make_cfg('')), {})

    def test_no_musicbrainz_section_returns_empty(self):
        from massmusictagger.cascade import _load_source_hints
        from discogstagger.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if cfg.has_section('musicbrainz'):
            cfg.remove_section('musicbrainz')
        self.assertEqual(_load_source_hints(cfg), {})


if __name__ == '__main__':
    unittest.main()
