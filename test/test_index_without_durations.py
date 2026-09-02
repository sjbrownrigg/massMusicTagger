"""An index entry with no durations anywhere is one track, not a crash.

Einstürzende Neubauten's *Haus Der Luege* (Discogs release 23821019) holds
"Fiat Lux" as an `index` entry with sub_tracks 6a/6b/6c and no duration on the
parent or any sub. The rip holds it as a single file, which is what collapsing
the movements produces.

Three branches could have claimed it and none did. Pattern A expands an index
whose sub_tracks each carry a duration; these do not. `_ambiguous` recognises
the shape -- no parent duration, no sub durations -- but only expands when
`expand_ambiguous_index` is set, and it is off by default. Pattern B required a
parent duration. So the entry fell through to a branch whose body referenced a
name that had never been defined, and the album died with

    NameError: name 'discsubtitle' is not defined

Skipping the entry would not have been right either: the release would then
offer 10 tracks against the rip's 11 and be refused on track count.
"""

import unittest
from unittest.mock import MagicMock

from massmusictagger.sources.discogs.album import DiscogsAlbum


def _entry(type_, position, title, duration, subs=()):
    t = MagicMock()
    t.position, t.title, t.duration = position, title, duration
    t.artists = None
    t.data = {'type_': type_,
              'sub_tracks': [{'type_': 'track', 'position': p,
                              'title': s, 'duration': d}
                             for p, s, d in subs]}
    return t


def _haus_der_luege():
    """The real tracklist, trimmed to the shape that mattered."""
    return [
        _entry('track', '1', 'Prolog', '1:51'),
        _entry('track', '2', 'Feurio!', '6:03'),
        _entry('track', '3', 'Ein Stuhl In Der Hoelle', '2:09'),
        _entry('track', '4', 'Haus Der Luege', '4:00'),
        _entry('track', '5', 'Epilog', '0:30'),
        _entry('index', '', 'Fiat Lux', '',
               subs=(('6a', 'Fiat Lux', ''),
                     ('6b', 'Maifestspiele', ''),
                     ('6c', 'Hirnlego', ''))),
        _entry('track', '7', 'Schwindel', '3:58'),
        _entry('track', '8', 'Der Kuss', '4:07'),
        _entry('heading', '', 'Bonus Tracks', ''),
        _entry('track', '9', 'Feurio! ( Remix)', '4:49'),
        _entry('track', '10', 'Feurio! (Tueren Offen)', '4:52'),
        _entry('track', '11', 'Partymucke', '3:54'),
    ]


class IndexWithoutDurationsTest(unittest.TestCase):

    def _mapped(self, expand=False):
        release = MagicMock()
        release.tracklist = _haus_der_luege()
        mapper = DiscogsAlbum.__new__(DiscogsAlbum)
        mapper.release = release
        mapper.expand_ambiguous_index = expand
        album = MagicMock()
        album.artists, album.artist, album.sort_artist = ['EN'], 'EN', 'EN'
        return mapper, album

    def test_it_does_not_raise(self):
        """The whole point: this used to be a NameError."""
        mapper, album = self._mapped()
        mapper.discs_and_tracks(album)   # must not raise

    def test_the_index_becomes_one_track(self):
        """11 local files, 11 tracks -- not 10, which would fail on count."""
        mapper, album = self._mapped()
        discs = mapper.discs_and_tracks(album)
        titles = [t.title for d in discs for t in d.tracks]
        self.assertEqual(len(titles), 11)
        self.assertIn('Fiat Lux', titles)
        self.assertNotIn('Maifestspiele', titles,
                         'the movements collapse into the parent, not beside it')

    def test_expanding_is_still_available(self):
        """expand_ambiguous_index keeps its meaning: three separate files."""
        mapper, album = self._mapped(expand=True)
        titles = [t.title for d in mapper.discs_and_tracks(album) for t in d.tracks]
        self.assertIn('Maifestspiele', titles)
        self.assertEqual(len(titles), 13)

    def test_a_heading_is_still_a_heading(self):
        """The Bonus Tracks row must not become a track."""
        mapper, album = self._mapped()
        titles = [t.title for d in mapper.discs_and_tracks(album) for t in d.tracks]
        self.assertNotIn('Bonus Tracks', titles)


if __name__ == '__main__':
    unittest.main()
