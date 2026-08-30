"""Factory functions that instantiate the correct connector, search, and mapper
objects based on the 'source.name' config value."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from massmusictagger.core.tagger_config import TaggerConfig
    from massmusictagger.source_interface import SourceConnector, SourceSearch, SourceMapper

logger = logging.getLogger(__name__)

_KNOWN_SOURCES = ('discogs', 'musicbrainz', 'local', 'auto')


def make_discogs_connector(cfg: 'TaggerConfig') -> 'SourceConnector':
    from massmusictagger.sources.discogs.connector import DiscogsConnector
    return DiscogsConnector(cfg)


def make_discogs_local_connector(cfg: 'TaggerConfig', delegate) -> 'SourceConnector':
    from massmusictagger.sources.discogs.connector import LocalDiscogsConnector
    return LocalDiscogsConnector(delegate)


def make_discogs_search(cfg: 'TaggerConfig') -> 'SourceSearch':
    from massmusictagger.sources.discogs.search import DiscogsSearch
    return DiscogsSearch(cfg)


def make_mb_connector(cfg: 'TaggerConfig') -> 'SourceConnector':
    from massmusictagger.sources.musicbrainz.connector import MBConnector
    return MBConnector(cfg)


def make_mb_search(cfg: 'TaggerConfig', connector=None) -> 'SourceSearch':
    from massmusictagger.sources.musicbrainz.search import MBSearch
    return MBSearch(cfg, connector=connector)


def make_discogs_mapper(cfg: 'TaggerConfig', connector=None,
                        local_count=None, **kwargs) -> 'SourceMapper':
    """Return a callable that maps a raw Discogs Release to an Album.

    A connector is optional but worth passing: a reissue frequently carries no
    year of its own, and the master it belongs to almost always does.

    local_count is worth passing too. An index entry with a parent duration
    and timed sub_tracks -- or neither -- reads equally as one file or
    several, and only the number of files on disk settles it. Without the
    count the mapper takes the collapsed reading, which is what it has always
    done; with it, the mapper reaches the same conclusion the search did.
    """
    use_anv = cfg.getboolean('naming', 'use_anv') if cfg.has_option('naming', 'use_anv') else True

    class _DiscogsMapper:
        def map(self, raw_release):
            from massmusictagger.sources.discogs.album import DiscogsAlbum
            from massmusictagger.sources.discogs.utils import (
                prefers_expanded_index)
            expand = False
            try:
                expand = prefers_expanded_index(raw_release.tracklist,
                                                local_count)
            except Exception as exc:
                logger.debug('Could not choose an index reading: %s', exc)
            if expand:
                logger.info('Release %s: index sub-tracks read as separate '
                            'files to match %d local file(s)',
                            getattr(raw_release, 'id', '?'), local_count)
            album = DiscogsAlbum(raw_release, use_anv=use_anv,
                                 expand_ambiguous_index=expand).map()
            album.source = 'discogs'

            # The mapper reports honestly that the release has no year; the
            # master usually knows it. Done here rather than in the mapper so
            # the mapper stays a transformation of what it was handed.
            if not album.year and album.master_id and connector is not None:
                lookup = getattr(connector, 'fetch_master_year', None)
                if lookup:
                    year = lookup(album.master_id)
                    if year:
                        album.year = year
                        logger.info(
                            'Release %s has no year; using %s from master %s',
                            album.id, year, album.master_id)
            return album

    return _DiscogsMapper()


def make_mb_mapper(cfg: 'TaggerConfig') -> 'SourceMapper':
    from massmusictagger.sources.musicbrainz.album import MusicBrainzAlbum

    use_anv = (cfg.getboolean('naming', 'use_anv')
               if cfg.has_option('naming', 'use_anv') else True)

    class _MBMapper:
        def map(self, raw_release):
            album = MusicBrainzAlbum(raw_release, use_anv=use_anv).map()
            album.source = 'musicbrainz'
            return album

    return _MBMapper()
