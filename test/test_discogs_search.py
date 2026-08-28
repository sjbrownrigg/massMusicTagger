# -*- coding: utf-8 -*-
"""DiscogsSearch as a SourceSearch: one entry point, self-contained.

Discogs used to require the caller to prepare it -- call getSearchParams, work
out the folder hints, reach into .search_params to inject them, conditionally
pop the year, then call search_discogs(), which returned a release object
rather than an ID and needed a lazy fetch triggering by hand. MusicBrainz was
one call. These tests hold Discogs to the same shape.

The hint tests moved here from the cascade suite: they were asserting against a
MagicMock searcher, so once the behaviour moved they passed nothing meaningful.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock, patch

import yaml

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parentdir)

from massmusictagger import roots
from massmusictagger.core.tagger_config import TaggerConfig

MMT_CONFIG = os.path.join(roots.BUNDLED_CONF, 'config_sample.yaml')


class DiscogsSearchContract(unittest.TestCase):
    """search(sourcedir) -> id, the same shape MBSearch presents."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.hints = os.path.join(self.tmpdir, 'hints.yaml')
        with open(self.hints, 'w') as f:
            yaml.dump({'source_hints': {'digital': ['24 Bit'], 'vinyl': ['LP']}}, f)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _searcher(self):
        """A real DiscogsSearch with only the network boundary stubbed."""
        from massmusictagger.sources.discogs.search import DiscogsSearch
        cfg = TaggerConfig(MMT_CONFIG)
        for section in ('details', 'batch'):
            if not cfg.has_section(section):
                cfg.add_section(section)
        cfg.set('details', 'source_hints_file', self.hints)
        with patch.object(DiscogsSearch, '__init__', lambda self, c: None):
            s = DiscogsSearch(cfg)
        s.config = cfg
        s.search_params = {'year': '1974', 'tracks': []}
        s.getSearchParams = MagicMock()
        return s

    def _folder(self, name):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(path, exist_ok=True)
        return path

    # ── the contract ────────────────────────────────────────────────────────

    def test_search_returns_a_release_id(self):
        s = self._searcher()
        release = MagicMock(); release.id = 12345; release.tracklist = ['a']
        s.search_discogs = MagicMock(return_value=release)
        self.assertEqual(s.search(self._folder('Album')), '12345')

    def test_search_returns_none_when_nothing_matches(self):
        s = self._searcher()
        s.search_discogs = MagicMock(return_value=None)
        self.assertIsNone(s.search(self._folder('Album')))

    def test_search_swallows_a_deleted_release(self):
        """Touching .tracklist forces the fetch; a 404 there is not a match.

        The caller used to have to know this and do it itself.
        """
        s = self._searcher()
        release = MagicMock(); release.id = 999
        type(release).tracklist = property(
            lambda self: (_ for _ in ()).throw(Exception('404 not found')))
        s.search_discogs = MagicMock(return_value=release)
        self.assertIsNone(s.search(self._folder('Album')))

    # ── the hint behaviour, now owned by Discogs ────────────────────────────

    def test_digital_hint_injected_and_year_suppressed(self):
        s = self._searcher()
        s.search_discogs = MagicMock(return_value=None)
        s.search(self._folder('1974 - Album (24 Bit Remaster)'))
        self.assertEqual(s.search_params.get('format_hint'), 'digital')
        self.assertNotIn('year', s.search_params,
                         'the album year hides the digital remaster')

    def test_no_hint_leaves_the_year_intact(self):
        s = self._searcher()
        s.search_discogs = MagicMock(return_value=None)
        s.search(self._folder('1974 - Plain Album'))
        self.assertNotIn('format_hint', s.search_params)
        self.assertEqual(s.search_params.get('year'), '1974')

    def test_vinyl_hint_does_not_suppress_the_year(self):
        s = self._searcher()
        s.search_discogs = MagicMock(return_value=None)
        s.search(self._folder('1974 - Album LP'))
        self.assertEqual(s.search_params.get('format_hint'), 'vinyl')
        self.assertEqual(s.search_params.get('year'), '1974')


class BothSourcesPresentTheSameSearch(unittest.TestCase):
    def test_search_signature_matches(self):
        """The point of the phase: one entry point, same name, same shape."""
        import inspect
        from massmusictagger.sources.discogs.search import DiscogsSearch
        from massmusictagger.sources.musicbrainz.search import MBSearch
        for cls in (DiscogsSearch, MBSearch):
            self.assertTrue(hasattr(cls, 'search'), f'{cls.__name__} needs search()')
            params = list(inspect.signature(cls.search).parameters)
            self.assertEqual(params[:2], ['self', 'sourcedir'],
                             f'{cls.__name__}.search should take (self, sourcedir)')


class FactoryProducesTheContract(unittest.TestCase):
    """The source_factory adapters are what actually present SourceMapper.

    The album classes cannot declare it themselves: both take the raw release
    in their constructor and expose `map(self)`, while the ABC declares
    `map(self, raw_release)`. LocalDiscogsConnector likewise takes an extra
    source_dir on fetch_release. The factory shims reconcile that, so the
    contract is real at the factory boundary rather than on the classes -- and
    this test says so out loud instead of leaving the ABCs looking implemented
    when nothing implements them.
    """

    def test_both_mappers_expose_map_with_a_raw_release(self):
        import inspect
        from massmusictagger.source_factory import make_discogs_mapper, make_mb_mapper
        cfg = TaggerConfig(MMT_CONFIG)
        for make in (make_discogs_mapper, make_mb_mapper):
            mapper = make(cfg)
            self.assertTrue(hasattr(mapper, 'map'))
            params = list(inspect.signature(mapper.map).parameters)
            self.assertEqual(params[:1], ['raw_release'],
                             f'{make.__name__} should map(raw_release), '
                             'matching SourceMapper')

    def test_both_connectors_expose_the_connector_contract(self):
        from massmusictagger.source_factory import (
            make_discogs_connector, make_mb_connector)
        cfg = TaggerConfig(MMT_CONFIG)
        for make in (make_discogs_connector, make_mb_connector):
            conn = make(cfg)
            for method in ('fetch_release', 'cache_release', 'fetch_image'):
                self.assertTrue(callable(getattr(conn, method, None)),
                                f'{make.__name__} is missing {method}()')
