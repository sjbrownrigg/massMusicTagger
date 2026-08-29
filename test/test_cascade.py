"""Tests for the cascade source-selection logic."""
import os
import sys
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))


# The packaged reference config, not a live conf/config.yaml. The suite used
# to point at the latter -- a gitignored file that only exists on a machine
# where someone has configured the tool -- so 68 tests passed here and would
# have failed on a fresh clone or in CI.
from massmusictagger import roots as _roots
MMT_CONFIG = os.path.join(_roots.BUNDLED_CONF, 'config_sample.yaml')


class TestGetPriority(unittest.TestCase):
    """_get_priority() reads source.priority from config."""

    def _make_cfg(self, priority=None, name=None):
        from massmusictagger.core.tagger_config import TaggerConfig
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
        from massmusictagger.core.tagger_config import TaggerConfig
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
        from massmusictagger.core.tagger_config import TaggerConfig
        from massmusictagger.cascade import _map_existing_tags
        cfg = TaggerConfig(MMT_CONFIG)
        album = _map_existing_tags(self.tmpdir, cfg)
        self.assertIsNotNone(album)
        self.assertEqual(album.source, 'existing_tags')
        self.assertEqual(len(album.discs[0].tracks), 3)


class TestCleanFallbackTitle(unittest.TestCase):
    """_clean_fallback_title() derives a stable title from a bare filename.

    Regression: existing_tags fallback used the raw filename (with
    extension) as the track title when no title tag was present. On
    repeated existing_tags runs (no source/discogs/musicbrainz match,
    no tags ever written), this snowballed into filenames like
    '01 01 01-Deathboy-...mp3.mp3.mp3.mp3'.
    """

    def test_strips_extension(self):
        from massmusictagger.cascade import _clean_fallback_title
        self.assertEqual(
            _clean_fallback_title('Amphetamine Zoo - DeathBoy.mp3'),
            'Amphetamine Zoo - DeathBoy')

    def test_strips_leading_track_number_with_space(self):
        from massmusictagger.cascade import _clean_fallback_title
        self.assertEqual(
            _clean_fallback_title('01 Amphetamine Zoo - DeathBoy.mp3'),
            'Amphetamine Zoo - DeathBoy')

    def test_strips_leading_track_number_with_hyphen(self):
        from massmusictagger.cascade import _clean_fallback_title
        self.assertEqual(
            _clean_fallback_title('01-Amphetamine Zoo - DeathBoy.mp3'),
            'Amphetamine Zoo - DeathBoy')

    def test_strips_accumulated_extensions_and_prefixes(self):
        from massmusictagger.cascade import _clean_fallback_title
        self.assertEqual(
            _clean_fallback_title(
                '01 01 01-Deathboy-Amphetamine Zoo - DeathBoy.mp3.mp3.mp3.mp3'),
            'Deathboy-Amphetamine Zoo - DeathBoy')

    def test_idempotent_on_cleaned_title(self):
        from massmusictagger.cascade import _clean_fallback_title
        cleaned = _clean_fallback_title('01 Amphetamine Zoo - DeathBoy.mp3')
        self.assertEqual(_clean_fallback_title(cleaned), cleaned)

    def test_no_extension_or_prefix_returned_unchanged(self):
        from massmusictagger.cascade import _clean_fallback_title
        self.assertEqual(_clean_fallback_title('Plain Title'), 'Plain Title')

    def test_extensionless_all_digits_falls_back_to_original(self):
        from massmusictagger.cascade import _clean_fallback_title
        # Degenerate case: stripping would leave nothing — keep the original.
        self.assertEqual(_clean_fallback_title('01'), '01')


class TestIdTxtReader(unittest.TestCase):
    """Moved to test_id_file.py.

    cascade had its own id.txt parser alongside FileUtils.read_id_file.
    It only ever looked for discogs_id, so a file naming musicbrainz was
    silently ignored. One reader now handles every format, and the
    processor routes the result to the source the file names.
    """

    def test_the_duplicate_parser_is_gone(self):
        import massmusictagger.cascade as c
        self.assertFalse(hasattr(c, '_read_id_txt'),
                         'there should be one id.txt reader')


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


class _FakeSubtrackRelease:
    """Minimal Discogs release stand-in with lettered sub-track positions.

    Mirrors the real-world 'Sounds Of The Universe' (1734706) shape: a track
    split into 13a/13b/13c by a Discogs data entry error.  build_flat_tracklist
    sees 3 entries where local has 1 file for that track.
    """
    class _Track:
        def __init__(self, position, title, duration):
            self.position = position
            self.title = title
            self.duration = duration
            self.data = {'type_': 'track'}

    def __init__(self, rid, extra_normal=10):
        self.id = rid
        tracks = [self._Track(str(i), f'T{i}', '3:00') for i in range(1, extra_normal + 1)]
        tracks += [
            self._Track('13a', 'Corrupt', '5:04'),
            self._Track('13b', '(silence)', '3:13'),
            self._Track('13c', 'Untitled', '0:41'),
        ]
        self._tracklist = tracks

    @property
    def tracklist(self):
        return self._tracklist


class TestDiscogsPostSearchSubtrackMerge(unittest.TestCase):
    """Regression: _try_discogs() must pass local_count into _discogs_track_count()
    after search_discogs() returns a candidate, or the lettered sub-track merge
    fallback never runs and a release the search already accepted gets rejected
    again by the post-search count re-validation.
    """

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_accepted_when_merge_resolves_count(self):
        from unittest.mock import MagicMock, patch
        from massmusictagger.cascade import _try_discogs

        cfg_path = MMT_CONFIG
        from massmusictagger.core.tagger_config import TaggerConfig
        cfg = TaggerConfig(cfg_path)
        if not cfg.has_section('batch'):
            cfg.add_section('batch')
        cfg.set('batch', 'searchdiscogs', 'true')

        # 10 normal tracks + merged 13(a/b/c) = 11 local files.
        raw = _FakeSubtrackRelease('1734706', extra_normal=10)
        connector = MagicMock()
        searcher = MagicMock()
        searcher.search_params = {'tracks': []}
        # cascade now asks for an id, then fetches through the connector
        searcher.search.return_value = raw.id
        connector.fetch_release.return_value = raw

        folder = os.path.join(self.tmpdir, 'Sounds Of The Universe')
        os.makedirs(folder)

        with patch('massmusictagger.cascade._read_existing_discogs_id_tag',
                   return_value=None), \
             patch('massmusictagger.cascade._local_audio_count', return_value=11):
            result = _try_discogs(folder, cfg, connector, searcher)

        self.assertIsNotNone(result)
        self.assertEqual(result[1], '1734706')

    def test_rejected_when_merge_does_not_resolve_count(self):
        from unittest.mock import MagicMock, patch
        from massmusictagger.cascade import _try_discogs

        cfg_path = MMT_CONFIG
        from massmusictagger.core.tagger_config import TaggerConfig
        cfg = TaggerConfig(cfg_path)
        if not cfg.has_section('batch'):
            cfg.add_section('batch')
        cfg.set('batch', 'searchdiscogs', 'true')

        raw = _FakeSubtrackRelease('1734706', extra_normal=10)  # 13 flat, 11 merged
        connector = MagicMock()
        searcher = MagicMock()
        searcher.search_params = {'tracks': []}
        # cascade now asks for an id, then fetches through the connector
        searcher.search.return_value = raw.id
        connector.fetch_release.return_value = raw

        folder = os.path.join(self.tmpdir, 'Sounds Of The Universe Partial')
        os.makedirs(folder)

        with patch('massmusictagger.cascade._read_existing_discogs_id_tag',
                   return_value=None), \
             patch('massmusictagger.cascade._local_audio_count', return_value=12):
            result = _try_discogs(folder, cfg, connector, searcher)

        self.assertIsNone(result)


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

    _load_source_hints() checks source.source_hints_file first (the canonical
    location), then musicbrainz.source_hints_file as a backward-compat fallback.
    Tests must clear source.source_hints_file to avoid the default value in
    config.yaml from shadowing the test-controlled path.
    """

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, hints_path=''):
        from massmusictagger.core.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if not cfg.has_section('details'):
            cfg.add_section('details')
        cfg.set('source', 'source_hints_file', hints_path)
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

    def test_empty_path_falls_back_to_the_packaged_hints(self):
        """No configured path means the shipped defaults, not no hints at all.

        This used to return {}, so the feature was silently inert for every
        installed copy: the sample config named conf/source_hints.yaml, a
        working-directory-relative path that only ever resolved from a source
        checkout.
        """
        from massmusictagger.cascade import _load_source_hints
        hints = _load_source_hints(self._make_cfg(''))
        self.assertTrue(hints, 'packaged source hints should have loaded')
        self.assertIn('digital', hints)

    def test_no_hints_configured_uses_the_packaged_hints(self):
        """Neither details nor musicbrainz set: still the shipped defaults."""
        from massmusictagger.cascade import _load_source_hints
        from massmusictagger.core.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        for section in ('details', 'musicbrainz'):
            if cfg.has_section(section) and cfg.has_option(section, 'source_hints_file'):
                cfg.set(section, 'source_hints_file', '')
        hints = _load_source_hints(cfg)
        self.assertTrue(hints)
        self.assertIn('digital', hints)

    def test_packaged_hints_are_installed(self):
        """The defaults must be in the package, not just the source tree."""
        import os
        from massmusictagger import roots
        self.assertTrue(
            os.path.exists(os.path.join(roots.BUNDLED_CONF, 'source_hints.yaml')),
            'source_hints.yaml is missing from the installed package')

    def test_musicbrainz_fallback_used_when_details_empty(self):
        """musicbrainz.source_hints_file is used when source.source_hints_file is empty."""
        import yaml
        from massmusictagger.cascade import _load_source_hints
        from massmusictagger.core.tagger_config import TaggerConfig
        cfg = TaggerConfig(MMT_CONFIG)
        if not cfg.has_section('details'):
            cfg.add_section('details')
        cfg.set('source', 'source_hints_file', '')
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
