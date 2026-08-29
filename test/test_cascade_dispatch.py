# -*- coding: utf-8 -*-
"""The cascade as one loop over interchangeable sources.

search_and_map used to be an if/elif chain, one branch per source. Every
branch did the same three things -- find, map, return (Album, connector) --
with the differences buried in the middle. Adding a source meant editing the
chain; mistyping one in source.priority meant it silently did nothing, because
an unrecognised name simply fell out of the bottom.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parentdir)

from massmusictagger import roots
from massmusictagger.core.tagger_config import TaggerConfig
from massmusictagger import cascade

MMT_CONFIG = os.path.join(roots.BUNDLED_CONF, 'config_sample.yaml')


def _cfg(priority):
    cfg = TaggerConfig(MMT_CONFIG)
    if not cfg.has_section('source'):
        cfg.add_section('source')
    cfg.set('source', 'priority', str(priority))
    return cfg


class Dispatch(unittest.TestCase):

    def test_every_known_source_is_registered(self):
        self.assertEqual(sorted(cascade._SOURCES),
                         ['discogs', 'existing_tags', 'local', 'musicbrainz'])

    def test_unknown_source_warns_instead_of_silently_doing_nothing(self):
        """A typo in source.priority used to just remove that source."""
        with self.assertLogs('massmusictagger.cascade', level='WARNING') as logs:
            result = cascade.search_and_map('/nowhere', _cfg(['discogz']))
        self.assertIsNone(result)
        joined = '\n'.join(logs.output)
        self.assertIn('discogz', joined)
        self.assertIn('Unknown source', joined)

    def test_sources_are_tried_in_priority_order(self):
        calls = []

        def _record(name):
            def _resolve(source, ctx):
                calls.append(source)
                return None
            return _resolve

        with patch.dict(cascade._SOURCES,
                        {'discogs': _record('discogs'),
                         'musicbrainz': _record('musicbrainz')},
                        clear=False):
            cascade.search_and_map('/nowhere', _cfg(['musicbrainz', 'discogs']))
        self.assertEqual(calls, ['musicbrainz', 'discogs'])

    def test_first_source_to_answer_wins(self):
        album = MagicMock()
        conn = MagicMock()

        def _hit(source, ctx):
            return album, conn

        def _miss(source, ctx):
            return None

        with patch.dict(cascade._SOURCES,
                        {'discogs': _miss, 'musicbrainz': _hit}, clear=False):
            got = cascade.search_and_map('/nowhere',
                                         _cfg(['discogs', 'musicbrainz']))
        self.assertEqual(got, (album, conn))

    def test_a_new_source_is_a_registration_not_a_branch(self):
        """The point of the phase: no edit to search_and_map required."""
        album, conn = MagicMock(), MagicMock()
        with patch.dict(cascade._SOURCES,
                        {'bandcamp': lambda source, ctx: (album, conn)},
                        clear=False):
            got = cascade.search_and_map('/nowhere', _cfg(['bandcamp']))
        self.assertEqual(got, (album, conn))

    def test_local_and_discogs_share_a_resolver_but_not_a_connector(self):
        seen = {}

        def _capture(source, ctx):
            seen[source] = (ctx.discogs_connector, ctx.discogs_local_connector)
            return None

        # Assert against the real registry, before patching anything -- the
        # obvious version of this check sits inside the patch that made the two
        # entries identical, and so passes whatever the registry says.
        self.assertIs(cascade._SOURCES['discogs'], cascade._SOURCES['local'],
                      'both should route through the same resolver')

        dc, lc = MagicMock(name='discogs'), MagicMock(name='local')
        with patch.dict(cascade._SOURCES,
                        {'discogs': _capture, 'local': _capture}, clear=False):
            cascade.search_and_map('/nowhere', _cfg(['discogs', 'local']),
                                   discogs_connector=dc,
                                   discogs_local_connector=lc)
        self.assertEqual(seen['discogs'], (dc, lc),
                         'both connectors reach the resolver via the context')


class ReleaseIdOverrideIsWired(unittest.TestCase):
    """--releaseid was accepted, documented in --help, and thrown away.

    cascade.search_and_map takes release_id_override and implements it fully:
    it fetches the release directly, validates the track count against the
    directory and warns on a mismatch. MassProcessor simply never passed it,
    so `-r 249504` against a Blue Eyed Christ folder searched anyway and
    tagged what the search found.
    """

    def test_the_processor_accepts_a_release_id(self):
        import inspect
        from massmusictagger.processor import MassProcessor
        sig = inspect.signature(MassProcessor.__init__)
        self.assertIn('release_id', sig.parameters)

    def test_it_reaches_search_and_map(self):
        """The wiring, asserted at the call site rather than by running it."""
        import inspect
        from massmusictagger import processor as proc
        src = inspect.getsource(proc)
        call = src[src.index('search_and_map('):]
        call = call[:call.index(')')]
        self.assertIn('release_id_override=self.release_id', call)

    def test_main_passes_the_flag_to_the_processor(self):
        import inspect
        from massmusictagger import __main__ as mmt_main
        src = inspect.getsource(mmt_main)
        call = src[src.index('MassProcessor('):]
        call = call[:call.index('\n    )')]
        self.assertIn('release_id=opts.releaseid', call)

    def test_a_release_id_with_many_directories_is_refused(self):
        """One release ID cannot describe a tree of albums."""
        import inspect
        from massmusictagger import __main__ as mmt_main
        src = inspect.getsource(mmt_main)
        self.assertIn('opts.releaseid and len(source_dirs) > 1', src)
