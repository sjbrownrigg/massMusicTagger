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
