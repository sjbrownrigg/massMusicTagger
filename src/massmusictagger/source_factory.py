"""Factory functions that instantiate the correct connector, search, and mapper
objects based on the 'source.name' config value."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discogstagger.tagger_config import TaggerConfig
    from massmusictagger.source_interface import SourceConnector, SourceSearch, SourceMapper

logger = logging.getLogger(__name__)

_KNOWN_SOURCES = ('discogs', 'musicbrainz', 'local', 'auto')


def make_discogs_connector(cfg: 'TaggerConfig') -> 'SourceConnector':
    from discogstagger.discogs_connector import DiscogsConnector
    return DiscogsConnector(cfg)


def make_discogs_local_connector(cfg: 'TaggerConfig', delegate) -> 'SourceConnector':
    from discogstagger.discogs_connector import LocalDiscogsConnector
    return LocalDiscogsConnector(delegate)


def make_discogs_search(cfg: 'TaggerConfig') -> 'SourceSearch':
    from discogstagger.discogs_search import DiscogsSearch
    return DiscogsSearch(cfg)


def make_mb_connector(cfg: 'TaggerConfig') -> 'SourceConnector':
    from massmusictagger.sources.musicbrainz.connector import MBConnector
    return MBConnector(cfg)


def make_mb_search(cfg: 'TaggerConfig', connector=None) -> 'SourceSearch':
    from massmusictagger.sources.musicbrainz.search import MBSearch
    return MBSearch(cfg, connector=connector)


def make_discogs_mapper(cfg: 'TaggerConfig', **kwargs) -> 'SourceMapper':
    """Return a callable that maps a raw Discogs Release to an Album."""
    use_anv = cfg.getboolean('details', 'use_anv') if cfg.has_option('details', 'use_anv') else True

    class _DiscogsMapper:
        def map(self, raw_release):
            from discogstagger.discogsalbum import DiscogsAlbum
            album = DiscogsAlbum(raw_release, use_anv=use_anv).map()
            album.source = 'discogs'
            return album

    return _DiscogsMapper()


def make_mb_mapper(cfg: 'TaggerConfig') -> 'SourceMapper':
    from massmusictagger.sources.musicbrainz.album import MusicBrainzAlbum

    class _MBMapper:
        def map(self, raw_release):
            album = MusicBrainzAlbum(raw_release).map()
            album.source = 'musicbrainz'
            return album

    return _MBMapper()
