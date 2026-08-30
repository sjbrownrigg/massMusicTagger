"""The artist picture: fetched once per artist, embedded, filed in the folder.

Only Discogs has artist images -- MusicBrainz stores none -- so a
MusicBrainz-matched album needs a Discogs artist lookup of its own, which is
why the result is cached by artist id rather than re-fetched per album.

The ordering is the part worth pinning. The artist folder only exists at the
real destination, so with staging enabled the album's parent during
processing is a temporary directory. Placing the image before the move would
file it nowhere useful.
"""

import os
import shutil
import tempfile
import unittest

from massmusictagger import image_utils


class PlaceArtistImageTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.artist_dir = os.path.join(self.tmp, 'Artist')
        self.album_dir = os.path.join(self.artist_dir, 'Album')
        os.makedirs(self.album_dir)
        self.src = os.path.join(self.tmp, 'src.jpg')
        with open(self.src, 'wb') as f:
            f.write(b'\xff\xd8jpegbytes')

    def test_it_lands_in_the_artist_folder_not_the_album(self):
        out = image_utils.place_artist_image(self.src, self.album_dir)
        self.assertEqual(out, os.path.join(self.artist_dir, 'artist.jpg'))
        self.assertTrue(os.path.isfile(out))
        self.assertFalse(
            os.path.exists(os.path.join(self.album_dir, 'artist.jpg')))

    def test_an_existing_image_is_left_alone(self):
        """The folder is shared; the first album there has done the work."""
        existing = os.path.join(self.artist_dir, 'artist.jpg')
        with open(existing, 'wb') as f:
            f.write(b'original')
        image_utils.place_artist_image(self.src, self.album_dir)
        with open(existing, 'rb') as f:
            self.assertEqual(f.read(), b'original')

    def test_no_image_is_a_no_op(self):
        self.assertIsNone(image_utils.place_artist_image('', self.album_dir))
        self.assertIsNone(image_utils.place_artist_image(None, self.album_dir))

    def test_a_missing_album_directory_is_a_no_op(self):
        self.assertIsNone(
            image_utils.place_artist_image(self.src, '/nonexistent/album'))


class ArtistIdTest(unittest.TestCase):

    class _Album:
        def __init__(self, source, ids, artists):
            self.source, self.artist_ids, self.artists = source, ids, artists

    class _Result:
        def __init__(self, id_, name): self.id, self.name = id_, name

    class _Client:
        def __init__(self, results): self._results = results
        def search(self, name, type=None): return list(self._results)

    class _Conn:
        def __init__(self, client): self.discogs_client = client

    def test_a_discogs_album_uses_the_id_it_already_has(self):
        album = self._Album('discogs', [10263, 999], ['David Bowie'])
        conn = self._Conn(self._Client([]))
        self.assertEqual(image_utils._discogs_artist_id(album, conn), 10263)

    def test_a_musicbrainz_album_falls_back_to_a_search(self):
        """MB carries artist MBIDs, which mean nothing to Discogs."""
        album = self._Album('musicbrainz', ['257180c1'], ['DHS'])
        conn = self._Conn(self._Client([self._Result(555, 'DHS')]))
        self.assertEqual(image_utils._discogs_artist_id(album, conn), 555)

    def test_the_search_prefers_an_exact_name_match(self):
        album = self._Album('musicbrainz', [], ['DHS'])
        conn = self._Conn(self._Client([
            self._Result(1, 'DHS Project'),
            self._Result(2, 'dhs'),
        ]))
        self.assertEqual(image_utils._discogs_artist_id(album, conn), 2)

    def test_no_artist_name_yields_nothing(self):
        album = self._Album('musicbrainz', [], [])
        conn = self._Conn(self._Client([]))
        self.assertIsNone(image_utils._discogs_artist_id(album, conn))


class WiringTest(unittest.TestCase):

    def test_the_image_is_placed_after_the_move_out_of_staging(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        move_at = src.index('_move_staged')
        place_at = src.index('place_artist_image')
        self.assertLess(move_at, place_at,
                        'the artist folder only exists after the move')

    def test_it_is_fetched_before_embedding(self):
        import inspect
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._process_one)
        self.assertLess(src.index('fetch_artist_image'),
                        src.index('embed_typed_images'))
        self.assertIn('artist_image=artist_image', src)

    def test_embedding_uses_picture_type_artist(self):
        import inspect
        src = inspect.getsource(image_utils.embed_typed_images)
        self.assertIn('ImageType.artist', src)

    def test_the_feature_is_off_by_default(self):
        from massmusictagger.config_schema import DEFAULTS
        self.assertEqual(DEFAULTS[('artwork', 'artist_image')], 'False')


if __name__ == '__main__':
    unittest.main()
