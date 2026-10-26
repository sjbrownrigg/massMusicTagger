"""Artist images come from Discogs, whatever the cover art came from.

`_process_one` reassigns `connector` to the *image* connector once the
metadata is in hand, so with `image_source: musicbrainz` it is the MusicBrainz
connector even for a Discogs-matched album. The artist-image fetch was handed
that, and Discogs artist images cannot be read through it:

    Could not read Discogs artist 156788:
    'MBConnector' object has no attribute 'discogs_client'

277 such failures in one log, and 106 of 161 artist folders without a picture.
It failed exactly on the albums where Cover Art Archive *succeeded*, so the
better the cover art, the less likely the artist image.
"""

import inspect
import unittest

from massmusictagger import processor


class ConnectorTest(unittest.TestCase):

    def setUp(self):
        self.src = inspect.getsource(processor.MassProcessor._process_one)

    def test_artist_images_use_the_discogs_connector(self):
        self.assertIn('fetch_artist_image(album, self._discogs_conn, cfg)', self.src)

    def test_not_the_cover_art_connector(self):
        self.assertNotIn('fetch_artist_image(album, connector, cfg)', self.src,
                         'connector is the image source by then, not Discogs')

    def test_the_swap_still_happens_before_it(self):
        """The ordering is what made this a bug; pin that it is still the order."""
        self.assertLess(self.src.index('_apply_image_source'),
                        self.src.index('fetch_artist_image'))


class NoDiscogsTest(unittest.TestCase):
    """A deployment without Discogs must skip artist images, not crash."""

    def test_a_missing_connector_is_skipped_quietly(self):
        from massmusictagger.image_utils import fetch_artist_image

        class Cfg:
            def getboolean(self, *a):
                return True
        self.assertIsNone(fetch_artist_image(object(), None, Cfg()))


if __name__ == '__main__':
    unittest.main()
