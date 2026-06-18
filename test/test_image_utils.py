"""Tests for CAA typed image downloading and embedding utilities."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

MMT_CONFIG = os.path.join(parentdir, 'conf', 'config.yaml')


def _make_cfg(**overrides):
    from discogstagger.tagger_config import TaggerConfig
    cfg = TaggerConfig(MMT_CONFIG)
    for sk, v in overrides.items():
        s, _, k = sk.partition('.')
        if not cfg.has_section(s):
            cfg.add_section(s)
        cfg.set(s, k, v)
    return cfg


def _make_album(images):
    from discogstagger.album import Album, Disc, Track
    a = Album('mbid-123', 'Test Album', ['Test Artist'])
    a.images = images
    a.target_dir = '/fake/sorted/Test Artist/[2020] Test Album'
    a.source = 'musicbrainz'
    disc = Disc(1)
    track = Track(1, 'Track One', ['Test Artist'])
    track.new_file = '01 Track One.flac'
    disc.tracks = [track]
    disc.target_dir = None
    a.discs = [disc]
    return a


# ── caa_basename ──────────────────────────────────────────────────────────────

class TestCaaBasename(unittest.TestCase):

    def setUp(self):
        from massmusictagger.image_utils import caa_basename
        self.fn = caa_basename

    def test_front(self):
        c = {}
        self.assertEqual(self.fn(['Front'], c), 'front')

    def test_back(self):
        c = {}
        self.assertEqual(self.fn(['Back'], c), 'back')

    def test_medium(self):
        c = {}
        self.assertEqual(self.fn(['Medium'], c), 'medium')

    def test_booklet_numbering(self):
        c = {}
        self.assertEqual(self.fn(['Booklet'], c), 'booklet')
        self.assertEqual(self.fn(['Booklet'], c), 'booklet-01')
        self.assertEqual(self.fn(['Booklet'], c), 'booklet-02')

    def test_front_then_back_independent_counters(self):
        c = {}
        self.assertEqual(self.fn(['Front'], c), 'front')
        self.assertEqual(self.fn(['Back'], c), 'back')
        self.assertEqual(self.fn(['Front'], c), 'front-01')

    def test_unknown_type_falls_back_to_image(self):
        c = {}
        self.assertEqual(self.fn(['Illustration'], c), 'image')

    def test_empty_types_falls_back_to_image(self):
        c = {}
        self.assertEqual(self.fn([], c), 'image')


# ── caa_image_type ────────────────────────────────────────────────────────────

class TestCaaImageType(unittest.TestCase):

    def setUp(self):
        from massmusictagger.image_utils import caa_image_type
        from mediafile import ImageType
        self.fn = caa_image_type
        self.IT = ImageType

    def test_front_maps_to_front(self):
        self.assertEqual(self.fn(['Front']), self.IT.front)

    def test_back_maps_to_back(self):
        self.assertEqual(self.fn(['Back']), self.IT.back)

    def test_booklet_maps_to_leaflet(self):
        self.assertEqual(self.fn(['Booklet']), self.IT.leaflet)

    def test_medium_maps_to_media(self):
        self.assertEqual(self.fn(['Medium']), self.IT.media)

    def test_unknown_maps_to_other(self):
        self.assertEqual(self.fn(['Tray']), self.IT.other)
        self.assertEqual(self.fn([]), self.IT.other)


# ── has_caa_type_metadata ─────────────────────────────────────────────────────

class TestHasCaaTypeMetadata(unittest.TestCase):

    def setUp(self):
        from massmusictagger.image_utils import has_caa_type_metadata
        self.fn = has_caa_type_metadata

    def test_true_when_caa_types_present(self):
        images = [{'uri': 'http://x', 'type': 'primary',
                   'caa_types': ['Front'], 'width': None, 'height': None}]
        self.assertTrue(self.fn(images))

    def test_false_when_no_caa_types(self):
        images = [{'uri': 'http://x', 'type': 'primary', 'width': 500, 'height': 500}]
        self.assertFalse(self.fn(images))

    def test_false_for_empty_list(self):
        self.assertFalse(self.fn([]))


# ── download_typed_images ─────────────────────────────────────────────────────

class TestDownloadTypedImages(unittest.TestCase):

    def _run(self, images, cfg_overrides=None, local_front_dims=None):
        from massmusictagger.image_utils import download_typed_images
        cfg = _make_cfg(**(cfg_overrides or {}))
        album = _make_album(images)
        connector = MagicMock()
        connector.fetch_image = MagicMock()
        with patch('massmusictagger.image_utils._local_front_dimensions',
                   return_value=local_front_dims):
            with patch('os.makedirs'):
                download_typed_images(album, connector, cfg)
        return album, connector

    def test_front_downloaded_as_front_jpg(self):
        images = [{'uri': 'https://caa/front.jpg', 'type': 'primary',
                   'caa_types': ['Front'], 'width': None, 'height': None}]
        album, conn = self._run(images, {'details.download_only_cover': 'false'})
        calls = [str(c) for c in conn.fetch_image.call_args_list]
        self.assertTrue(any('front.jpg' in c for c in calls))
        self.assertEqual(images[0]['local_filename'], 'front.jpg')

    def test_back_downloaded_as_back_jpg(self):
        images = [
            {'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
             'type': 'primary', 'width': None, 'height': None},
            {'uri': 'https://caa/back.jpg', 'caa_types': ['Back'],
             'type': 'secondary', 'width': None, 'height': None},
        ]
        album, conn = self._run(images, {'details.download_only_cover': 'false'})
        self.assertEqual(images[1].get('local_filename'), 'back.jpg')

    def test_multiple_booklets_numbered(self):
        images = [
            {'uri': 'https://caa/b1.jpg', 'caa_types': ['Booklet'],
             'type': 'secondary', 'width': None, 'height': None},
            {'uri': 'https://caa/b2.jpg', 'caa_types': ['Booklet'],
             'type': 'secondary', 'width': None, 'height': None},
        ]
        album, conn = self._run(images, {'details.download_only_cover': 'false'})
        self.assertEqual(images[0].get('local_filename'), 'booklet.jpg')
        self.assertEqual(images[1].get('local_filename'), 'booklet-01.jpg')

    def test_download_only_cover_skips_back(self):
        images = [
            {'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
             'type': 'primary', 'width': None, 'height': None},
            {'uri': 'https://caa/back.jpg', 'caa_types': ['Back'],
             'type': 'secondary', 'width': None, 'height': None},
        ]
        album, conn = self._run(images, {'details.download_only_cover': 'true'})
        # Only front should be downloaded
        self.assertIn('local_filename', images[0])
        self.assertNotIn('local_filename', images[1])

    def test_folder_jpg_written_for_front(self):
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        album, conn = self._run(images, {'details.use_folder_jpg': 'true',
                                         'details.download_only_cover': 'false'})
        dest_args = [str(c.args[0]) for c in conn.fetch_image.call_args_list]
        self.assertTrue(any('folder.jpg' in d for d in dest_args))

    def test_prefer_existing_skips_front_when_local_exists(self):
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        album, conn = self._run(
            images,
            {'details.image_policy': 'prefer_existing'},
            local_front_dims=(1200, 1200),
        )
        conn.fetch_image.assert_not_called()


# ── embed_typed_images ────────────────────────────────────────────────────────

class TestEmbedTypedImages(unittest.TestCase):

    def _run(self, images):
        from massmusictagger.image_utils import embed_typed_images
        from mediafile import ImageType
        cfg = _make_cfg(**{'details.embed_coverart': 'true'})
        album = _make_album(images)

        saved_images = {}

        def mock_mf_factory(path):
            mf = MagicMock()
            def _save():
                saved_images[path] = mf.images
            mf.save.side_effect = _save
            return mf

        with patch('massmusictagger.image_utils.MediaFile', side_effect=mock_mf_factory):
            with patch('builtins.open', unittest.mock.mock_open(read_data=b'\xff\xd8test')):
                with patch('os.path.exists', return_value=True):
                    embed_typed_images(album, cfg)

        return saved_images

    def test_front_embedded_with_front_type(self):
        from mediafile import ImageType
        images = [{'caa_types': ['Front'], 'local_filename': 'front.jpg',
                   'uri': '', 'type': 'primary'}]
        saved = self._run(images)
        self.assertTrue(any(
            any(img.type == ImageType.front for img in imgs)
            for imgs in saved.values()
        ))

    def test_back_embedded_with_back_type(self):
        from mediafile import ImageType
        images = [
            {'caa_types': ['Front'], 'local_filename': 'front.jpg',
             'uri': '', 'type': 'primary'},
            {'caa_types': ['Back'], 'local_filename': 'back.jpg',
             'uri': '', 'type': 'secondary'},
        ]
        saved = self._run(images)
        all_types = [img.type for imgs in saved.values() for img in imgs]
        self.assertIn(ImageType.front, all_types)
        self.assertIn(ImageType.back, all_types)

    def test_images_without_local_filename_skipped(self):
        images = [{'caa_types': ['Front'], 'uri': 'https://caa/x.jpg',
                   'type': 'primary'}]   # no local_filename
        saved = self._run(images)
        self.assertEqual(len(saved), 0)

    def test_front_sorted_first(self):
        from mediafile import ImageType
        images = [
            {'caa_types': ['Back'],  'local_filename': 'back.jpg',  'uri': '', 'type': 'secondary'},
            {'caa_types': ['Front'], 'local_filename': 'front.jpg', 'uri': '', 'type': 'primary'},
        ]
        saved = self._run(images)
        for imgs in saved.values():
            self.assertEqual(imgs[0].type, ImageType.front)
            self.assertEqual(imgs[1].type, ImageType.back)

    def test_oversized_image_skipped_others_still_embedded(self):
        """Regression: a single oversized booklet scan (e.g. 17MB, over
        FLAC's 16,777,215-byte metadata block limit) must not sink embedding
        of the other, smaller images. All images share one mf.images = [...]
        batch save, so an oversized block previously failed the save for
        every image — front/back/medium all silently lost too.
        """
        from massmusictagger.image_utils import embed_typed_images, MAX_EMBEDDED_IMAGE_SIZE
        from mediafile import ImageType

        cfg = _make_cfg(**{'details.embed_coverart': 'true'})
        images = [
            {'caa_types': ['Front'],   'local_filename': 'front.jpg',   'uri': '', 'type': 'primary'},
            {'caa_types': ['Booklet'], 'local_filename': 'booklet.jpg', 'uri': '', 'type': 'secondary'},
        ]
        album = _make_album(images)

        oversized = b'\xff\xd8' + b'x' * MAX_EMBEDDED_IMAGE_SIZE  # one byte over the limit
        normal = b'\xff\xd8test'

        def fake_open(path, *args, **kwargs):
            data = oversized if 'booklet' in path else normal
            return unittest.mock.mock_open(read_data=data).return_value

        saved_images = {}

        def mock_mf_factory(path):
            mf = MagicMock()
            def _save():
                saved_images[path] = mf.images
            mf.save.side_effect = _save
            return mf

        with patch('massmusictagger.image_utils.MediaFile', side_effect=mock_mf_factory):
            with patch('builtins.open', side_effect=fake_open):
                with patch('os.path.exists', return_value=True):
                    embed_typed_images(album, cfg)

        all_types = [img.type for imgs in saved_images.values() for img in imgs]
        self.assertIn(ImageType.front, all_types)
        self.assertNotIn(ImageType.leaflet, all_types)  # 'Booklet' CAA type → leaflet
        # Front (the only valid image) is still embedded, not dropped entirely.
        self.assertTrue(any(len(imgs) == 1 for imgs in saved_images.values()))


if __name__ == '__main__':
    unittest.main()
