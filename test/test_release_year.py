# -*- coding: utf-8 -*-
"""A missing release year must stay missing, not become 1900.

DiscogsAlbum.year returned the string "1900" whenever Discogs had no year --
16.5% of releases, 3,822 of the 23,102 in the local cache. That fabricated
year was written to the year tag and, through the %releasedate% fallback, into
the folder name, so albums were filed as [1900] with a date that does not
exist and whose only property was sorting first.

MusicBrainz already returned None for the same case, with a comment saying
why: the year tag is skipped rather than written wrong.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parentdir)

from massmusictagger.sources.discogs.album import DiscogsAlbum


def _year_for(raw):
    a = DiscogsAlbum.__new__(DiscogsAlbum)
    a.release = MagicMock()
    a.release.data = {'year': raw}
    return DiscogsAlbum.year.fget(a)


class MissingYearStaysMissing(unittest.TestCase):

    def test_a_real_year_survives(self):
        self.assertEqual(_year_for('1992'), '1992')
        self.assertEqual(_year_for(1992), '1992')

    def test_zero_is_not_a_year(self):
        """Discogs uses 0 for unknown; 996 cached releases also use "0" for
        the released field."""
        for raw in (0, '0', '0000'):
            self.assertIsNone(_year_for(raw), f'{raw!r} should be None')

    def test_absent_is_not_a_year(self):
        for raw in ('', None, 'nonsense'):
            self.assertIsNone(_year_for(raw), f'{raw!r} should be None')

    def test_never_1900(self):
        """The specific fabrication this replaces."""
        for raw in (0, '0', '', None, 'nonsense', '0000'):
            self.assertNotEqual(_year_for(raw), '1900')

    def test_both_sources_agree_on_absence(self):
        """MusicBrainz already returned None; Discogs now matches it."""
        from massmusictagger.sources.musicbrainz.album import MusicBrainzAlbum
        mb = MusicBrainzAlbum({'id': 'x', 'title': 'T', 'date': '',
                               'medium-list': []}).map()
        self.assertIsNone(mb.year)
        self.assertIsNone(_year_for(0))


class FolderNameOmitsAnAbsentDate(unittest.TestCase):

    def test_releasedate_is_empty_when_nothing_is_known(self):
        """%releasedate% falls back to year; with None it must end up blank so
        $wrap omits the bracket rather than printing [1900]."""
        from massmusictagger.core.album import Album
        album = Album('1', 'Test', ['A'])
        album.release_date = None
        album.year = None
        self.assertEqual(album.release_date or album.year or '', '')

    def test_releasedate_prefers_the_full_date(self):
        from massmusictagger.core.album import Album
        album = Album('1', 'Test', ['A'])
        album.release_date = '1992-04-21'
        album.year = '1992'
        self.assertEqual(album.release_date or album.year or '', '1992-04-21')


class MasterSuppliesTheMissingYear(unittest.TestCase):
    """A reissue with no year of its own inherits the master's.

    Blue Eyed Christ's "Leaders + Followers" digital reissue (release
    14726546) has year 0 and released "0", so it was filed with no date --
    while Discogs plainly shows 1991, on master 40822 that the release
    belongs to.

    99.6% of year-less releases have a master: 3,807 of 3,822 in the cache.
    """

    def _mapper(self, connector):
        from massmusictagger.source_factory import make_discogs_mapper
        from massmusictagger import roots
        from massmusictagger.core.tagger_config import TaggerConfig
        cfg = TaggerConfig(os.path.join(roots.BUNDLED_CONF, 'config_sample.yaml'))
        return make_discogs_mapper(cfg, connector=connector)

    def _album(self, year, master_id):
        """A mapped Album, with DiscogsAlbum stubbed to the fields under test."""
        from massmusictagger.core.album import Album
        import massmusictagger.sources.discogs.album as dg

        class _Stub:
            def __init__(self, raw, use_anv=True, **kw):
                pass

            def map(self):
                a = Album('14726546', 'Leaders + Followers', ['Blue Eyed Christ'])
                a.year = year
                a.master_id = master_id
                return a

        original, dg.DiscogsAlbum = dg.DiscogsAlbum, _Stub
        try:
            return self._mapper(self._connector).map(object())
        finally:
            dg.DiscogsAlbum = original

    def setUp(self):
        self._connector = MagicMock()
        self._connector.fetch_master_year.return_value = '1991'

    def test_missing_year_is_taken_from_the_master(self):
        album = self._album(year=None, master_id='40822')
        self.assertEqual(album.year, '1991')
        self._connector.fetch_master_year.assert_called_once_with('40822')

    def test_a_year_on_the_release_wins(self):
        album = self._album(year='1997', master_id='40822')
        self.assertEqual(album.year, '1997')
        self._connector.fetch_master_year.assert_not_called()

    def test_no_master_means_no_lookup(self):
        album = self._album(year=None, master_id=None)
        self.assertIsNone(album.year)
        self._connector.fetch_master_year.assert_not_called()

    def test_a_master_without_a_year_leaves_it_absent(self):
        """Better no date than a fabricated one — the 1900 lesson."""
        self._connector.fetch_master_year.return_value = None
        album = self._album(year=None, master_id='40822')
        self.assertIsNone(album.year)

    def test_no_connector_is_not_an_error(self):
        self._connector = None
        album = self._album(year=None, master_id='40822')
        self.assertIsNone(album.year)


class MasterFetchIsNotLazy(unittest.TestCase):
    """The client is lazy; .data on an unfetched object is an empty stub.

    fetch_master_year first read master.data.get('year'), which returns None
    for a master nobody has fetched -- so the lookup silently found nothing
    and the release stayed dateless. Reading the attribute forces the fetch.

    The same trap cost a fix in May, when a lazy attribute access on a search
    result triggered a 404 mid-map.
    """

    def _connector(self, master_obj):
        from massmusictagger.sources.discogs.connector import DiscogsConnector
        c = DiscogsConnector.__new__(DiscogsConnector)
        c._master_years = {}
        c.discogs_client = MagicMock()
        c.discogs_client.master.return_value = master_obj
        return c

    def test_reads_the_attribute_not_the_data_stub(self):
        master = MagicMock()
        master.year = 1991
        master.data = {}          # what an unfetched object looks like
        self.assertEqual(self._connector(master).fetch_master_year('40822'), '1991')

    def test_a_master_with_no_year_yields_none(self):
        master = MagicMock()
        master.year = 0
        self.assertIsNone(self._connector(master).fetch_master_year('40822'))

    def test_a_failed_fetch_is_not_fatal(self):
        master = MagicMock()
        type(master).year = property(
            lambda self: (_ for _ in ()).throw(Exception('404')))
        self.assertIsNone(self._connector(master).fetch_master_year('40822'))

    def test_the_result_is_memoised_per_run(self):
        """One lookup per master, however many releases point at it."""
        master = MagicMock()
        master.year = 1991
        conn = self._connector(master)
        for _ in range(3):
            conn.fetch_master_year('40822')
        self.assertEqual(conn.discogs_client.master.call_count, 1)

    def test_a_failure_is_memoised_too(self):
        master = MagicMock()
        type(master).year = property(
            lambda self: (_ for _ in ()).throw(Exception('404')))
        conn = self._connector(master)
        for _ in range(3):
            self.assertIsNone(conn.fetch_master_year('40822'))
        self.assertEqual(conn.discogs_client.master.call_count, 1,
                         'a failing master should not be retried all run')
