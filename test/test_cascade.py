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
    """_folder_format_hint() classifies a folder by keyword matching.

    Note: 'Remaster'/'Remastered' are NOT in the digital hints — they live in
    descriptor_boost because remasters exist on vinyl too.  Only keywords that
    unambiguously imply a specific medium belong in digital/vinyl.
    """

    HINTS = {'digital': ['24 Bit'], 'vinyl': ['Vinyl Rip']}

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


class TestDiscogsFmtHintInjection(unittest.TestCase):
    """Format hint is injected into searcher.search_params before search_discogs()."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, hints_path=''):
        from discogstagger.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if not cfg.has_section('details'):
            cfg.add_section('details')
        cfg.set('details', 'source_hints_file', hints_path)
        if not cfg.has_section('batch'):
            cfg.add_section('batch')
        cfg.set('batch', 'searchdiscogs', 'true')
        return cfg

    def test_digital_hint_injected_and_year_suppressed(self):
        import yaml
        from unittest.mock import MagicMock, patch
        from massmusictagger.cascade import _try_discogs

        hints_file = os.path.join(self.tmpdir, 'hints.yaml')
        with open(hints_file, 'w') as f:
            yaml.dump({'source_hints': {'digital': ['24 Bit'], 'vinyl': []}}, f)

        cfg = self._make_cfg(hints_file)
        connector = MagicMock()
        connector.fetch_release = MagicMock(return_value=None)

        searcher = MagicMock()
        searcher.search_params = {'year': '1974', 'tracks': []}
        searcher.search_discogs.return_value = None

        folder = os.path.join(self.tmpdir, '1974 - Album (24 Bit Remaster)')
        os.makedirs(folder)

        with patch('massmusictagger.cascade._read_id_txt', return_value=None), \
             patch('massmusictagger.cascade._read_existing_discogs_id_tag', return_value=None), \
             patch('massmusictagger.cascade._local_audio_count', return_value=0):
            _try_discogs(folder, cfg, connector, searcher)

        self.assertEqual(searcher.search_params.get('format_hint'), 'digital')
        self.assertNotIn('year', searcher.search_params)

    def test_no_hint_leaves_year_intact(self):
        import yaml
        from unittest.mock import MagicMock, patch
        from massmusictagger.cascade import _try_discogs

        hints_file = os.path.join(self.tmpdir, 'hints.yaml')
        with open(hints_file, 'w') as f:
            yaml.dump({'source_hints': {'digital': ['24 Bit'], 'vinyl': []}}, f)

        cfg = self._make_cfg(hints_file)
        connector = MagicMock()
        searcher = MagicMock()
        searcher.search_params = {'year': '1974', 'tracks': []}
        searcher.search_discogs.return_value = None

        folder = os.path.join(self.tmpdir, '1974 - Plain Album')
        os.makedirs(folder)

        with patch('massmusictagger.cascade._read_id_txt', return_value=None), \
             patch('massmusictagger.cascade._read_existing_discogs_id_tag', return_value=None), \
             patch('massmusictagger.cascade._local_audio_count', return_value=0):
            _try_discogs(folder, cfg, connector, searcher)

        self.assertNotIn('format_hint', searcher.search_params)
        self.assertEqual(searcher.search_params.get('year'), '1974')


class TestFolderDescriptorHints(unittest.TestCase):
    """_folder_descriptor_hints() returns matched descriptor_boost keywords."""

    HINTS = {'descriptor_boost': ['Remaster', 'Remastered', 'Live']}

    def test_remastered_matched(self):
        from massmusictagger.cascade import _folder_descriptor_hints
        result = _folder_descriptor_hints('/x/Artist/2002 - Album (Remastered)', self.HINTS)
        self.assertIn('Remastered', result)

    def test_live_matched(self):
        from massmusictagger.cascade import _folder_descriptor_hints
        result = _folder_descriptor_hints('/x/Artist/Album Live At Carnegie Hall', self.HINTS)
        self.assertIn('Live', result)

    def test_no_match_returns_empty_list(self):
        from massmusictagger.cascade import _folder_descriptor_hints
        result = _folder_descriptor_hints('/x/Artist/Plain Album', self.HINTS)
        self.assertEqual(result, [])

    def test_empty_hints_returns_empty_list(self):
        from massmusictagger.cascade import _folder_descriptor_hints
        self.assertEqual(_folder_descriptor_hints('/x/any', {}), [])

    def test_multiple_keywords_all_returned(self):
        from massmusictagger.cascade import _folder_descriptor_hints
        result = _folder_descriptor_hints('/x/Artist/Album Live (Remastered)', self.HINTS)
        self.assertIn('Remastered', result)
        self.assertIn('Live', result)

    def test_uses_basename_only(self):
        from massmusictagger.cascade import _folder_descriptor_hints
        result = _folder_descriptor_hints('/x/Remastered Collection/Plain Album', self.HINTS)
        self.assertEqual(result, [])

    def test_remaster_no_longer_a_digital_format_hint(self):
        """Remaster belongs in descriptor_boost, not digital — it applies to vinyl too."""
        from massmusictagger.cascade import _folder_format_hint
        digital_only_hints = {'digital': ['24 Bit', 'WEB'], 'vinyl': ['Vinyl Rip']}
        self.assertEqual('', _folder_format_hint('/x/Album (Remastered)', digital_only_hints))


class TestLoadSourceHints(unittest.TestCase):
    """_load_source_hints() reads keyword lists from YAML, returns {} on error.

    _load_source_hints() checks details.source_hints_file first (the canonical
    location), then musicbrainz.source_hints_file as a backward-compat fallback.
    Tests must clear details.source_hints_file to avoid the default value in
    config.yaml from shadowing the test-controlled path.
    """

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, hints_path=''):
        from discogstagger.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if not cfg.has_section('details'):
            cfg.add_section('details')
        cfg.set('details', 'source_hints_file', hints_path)
        if cfg.has_section('musicbrainz') and cfg.has_option('musicbrainz', 'source_hints_file'):
            cfg.set('musicbrainz', 'source_hints_file', '')
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

    def test_no_hints_configured_returns_empty(self):
        """When neither details nor musicbrainz has a source_hints_file, return {}."""
        from massmusictagger.cascade import _load_source_hints
        from discogstagger.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if cfg.has_section('details') and cfg.has_option('details', 'source_hints_file'):
            cfg.set('details', 'source_hints_file', '')
        if cfg.has_section('musicbrainz') and cfg.has_option('musicbrainz', 'source_hints_file'):
            cfg.set('musicbrainz', 'source_hints_file', '')
        self.assertEqual(_load_source_hints(cfg), {})

    def test_musicbrainz_fallback_used_when_details_empty(self):
        """musicbrainz.source_hints_file is used when details.source_hints_file is empty."""
        import yaml
        from massmusictagger.cascade import _load_source_hints
        from discogstagger.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if not cfg.has_section('details'):
            cfg.add_section('details')
        cfg.set('details', 'source_hints_file', '')
        hints_file = os.path.join(self.tmpdir, 'mb_hints.yaml')
        with open(hints_file, 'w') as f:
            yaml.dump({'source_hints': {'digital': ['WEB']}}, f)
        if not cfg.has_section('musicbrainz'):
            cfg.add_section('musicbrainz')
        cfg.set('musicbrainz', 'source_hints_file', hints_file)
        result = _load_source_hints(cfg)
        self.assertEqual(result, {'digital': ['WEB']})


if __name__ == '__main__':
    unittest.main()
