"""Tests for the image source preference feature.

Verifies:
  - MBConnector.fetch_image_list() parses the CAA response correctly
  - Front images map to type='primary', others to 'secondary'
  - Unapproved images are excluded
  - processor._apply_image_source() routes correctly for each image_source setting
  - _find_mbid_for_images() attempts barcode then text search
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

MMT_CONFIG = os.path.join(parentdir, 'conf', 'config.yaml')

_MBID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


def _make_cfg(**overrides):
    from discogstagger.tagger_config import TaggerConfig
    cfg = TaggerConfig(MMT_CONFIG)
    for sk, v in overrides.items():
        s, _, k = sk.partition('.')
        if not cfg.has_section(s):
            cfg.add_section(s)
        cfg.set(s, k, v)
    return cfg


# ── MBConnector.fetch_image_list() ────────────────────────────────────────────

class TestFetchImageList(unittest.TestCase):

    def _connector(self):
        from massmusictagger.sources.musicbrainz.connector import MBConnector
        conn = MBConnector.__new__(MBConnector)
        conn._cache_dir = '/tmp'
        return conn

    def _mock_caa_response(self, images):
        resp = MagicMock()
        resp.json.return_value = {'images': images}
        resp.raise_for_status = MagicMock()
        return resp

    def test_front_image_maps_to_primary(self):
        images = [{'types': ['Front'], 'front': True, 'back': False,
                   'approved': True, 'image': 'https://example.com/front.jpg'}]
        conn = self._connector()
        with patch('requests.get', return_value=self._mock_caa_response(images)):
            result = conn.fetch_image_list(_MBID)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 'primary')
        self.assertEqual(result[0]['caa_types'], ['Front'])

    def test_back_image_maps_to_secondary(self):
        images = [{'types': ['Back'], 'front': False, 'back': True,
                   'approved': True, 'image': 'https://example.com/back.jpg'}]
        conn = self._connector()
        with patch('requests.get', return_value=self._mock_caa_response(images)):
            result = conn.fetch_image_list(_MBID)
        self.assertEqual(result[0]['type'], 'secondary')
        self.assertEqual(result[0]['caa_types'], ['Back'])

    def test_medium_image_maps_to_secondary(self):
        images = [{'types': ['Medium'], 'front': False, 'back': False,
                   'approved': True, 'image': 'https://example.com/disc.jpg'}]
        conn = self._connector()
        with patch('requests.get', return_value=self._mock_caa_response(images)):
            result = conn.fetch_image_list(_MBID)
        self.assertEqual(result[0]['type'], 'secondary')

    def test_unapproved_images_excluded(self):
        images = [
            {'types': ['Front'], 'front': True, 'approved': True,
             'image': 'https://example.com/good.jpg'},
            {'types': ['Back'], 'front': False, 'approved': False,
             'image': 'https://example.com/bad.jpg'},
        ]
        conn = self._connector()
        with patch('requests.get', return_value=self._mock_caa_response(images)):
            result = conn.fetch_image_list(_MBID)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 'primary')

    def test_multiple_images_in_order(self):
        images = [
            {'types': ['Front'], 'front': True,  'approved': True,
             'image': 'https://example.com/front.jpg'},
            {'types': ['Back'],  'front': False, 'approved': True,
             'image': 'https://example.com/back.jpg'},
            {'types': ['Booklet'], 'front': False, 'approved': True,
             'image': 'https://example.com/booklet.jpg'},
        ]
        conn = self._connector()
        with patch('requests.get', return_value=self._mock_caa_response(images)):
            result = conn.fetch_image_list(_MBID)
        self.assertEqual(len(result), 3)
        types = [r['type'] for r in result]
        self.assertEqual(types, ['primary', 'secondary', 'secondary'])

    def test_network_error_returns_empty_list(self):
        conn = self._connector()
        with patch('requests.get', side_effect=Exception('timeout')):
            result = conn.fetch_image_list(_MBID)
        self.assertEqual(result, [])

    def test_404_returns_empty_list(self):
        import requests
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError('404')
        conn = self._connector()
        with patch('requests.get', return_value=resp):
            result = conn.fetch_image_list(_MBID)
        self.assertEqual(result, [])

    def test_image_dict_has_required_keys(self):
        images = [{'types': ['Front'], 'front': True, 'approved': True,
                   'image': 'https://example.com/front.jpg'}]
        conn = self._connector()
        with patch('requests.get', return_value=self._mock_caa_response(images)):
            result = conn.fetch_image_list(_MBID)
        img = result[0]
        self.assertIn('uri',       img)
        self.assertIn('type',      img)
        self.assertIn('caa_types', img)
        self.assertIn('width',     img)
        self.assertIn('height',    img)


# ── processor._apply_image_source() ─────────────────────────────────────────

class TestApplyImageSource(unittest.TestCase):

    def _make_processor(self, discogs_conn=None, mb_conn=None):
        from massmusictagger.processor import MassProcessor
        p = MassProcessor.__new__(MassProcessor)
        p._discogs_conn = discogs_conn
        p._mb_conn = mb_conn
        p._discogs_search = None
        p._mb_search = None
        return p

    def _make_album(self, source='discogs', barcode='', images=None):
        from discogstagger.album import Album
        a = Album('123', 'Test Album', ['Test Artist'])
        a.source = source
        a.barcode = barcode
        a.images = images or [{'uri': 'https://discogs.com/img.jpg',
                                'type': 'primary', 'width': 500, 'height': 500}]
        return a

    def test_auto_returns_original_connector(self):
        conn = MagicMock()
        p = self._make_processor()
        cfg = _make_cfg(**{'details.image_source': 'auto'})
        album = self._make_album()
        result = p._apply_image_source(album, conn, '/fake/dir', cfg)
        self.assertIs(result, conn)

    def test_auto_default_when_key_absent(self):
        conn = MagicMock()
        p = self._make_processor()
        cfg = _make_cfg()
        album = self._make_album()
        result = p._apply_image_source(album, conn, '/fake/dir', cfg)
        self.assertIs(result, conn)

    def test_discogs_returns_discogs_connector(self):
        discogs_conn = MagicMock()
        p = self._make_processor(discogs_conn=discogs_conn)
        cfg = _make_cfg(**{'details.image_source': 'discogs'})
        album = self._make_album(source='musicbrainz')
        result = p._apply_image_source(album, MagicMock(), '/fake/dir', cfg)
        self.assertIs(result, discogs_conn)

    def test_musicbrainz_source_uses_caa_for_mb_album(self):
        """When album came from MB, fetch_image_list() is called with album.id."""
        mb_conn = MagicMock()
        caa_images = [{'uri': 'https://caa.example.com/front.jpg',
                       'type': 'primary', 'caa_types': ['Front'],
                       'width': None, 'height': None}]
        mb_conn.fetch_image_list.return_value = caa_images
        p = self._make_processor(mb_conn=mb_conn)
        cfg = _make_cfg(**{'details.image_source': 'musicbrainz'})
        album = self._make_album(source='musicbrainz')
        album.id = _MBID
        result = p._apply_image_source(album, MagicMock(), '/fake/dir', cfg)
        mb_conn.fetch_image_list.assert_called_once_with(_MBID)
        self.assertIs(result, mb_conn)
        self.assertEqual(album.images, caa_images)

    def test_musicbrainz_source_fallback_when_no_mb_connector(self):
        """No MB connector available → fall back to original connector."""
        original_conn = MagicMock()
        p = self._make_processor(mb_conn=None)
        cfg = _make_cfg(**{'details.image_source': 'musicbrainz'})
        album = self._make_album(source='discogs')
        result = p._apply_image_source(album, original_conn, '/fake/dir', cfg)
        self.assertIs(result, original_conn)

    def test_musicbrainz_source_fallback_when_caa_empty(self):
        """CAA returns no images → fall back to original connector, images unchanged."""
        mb_conn = MagicMock()
        mb_conn.fetch_image_list.return_value = []
        p = self._make_processor(mb_conn=mb_conn)
        cfg = _make_cfg(**{'details.image_source': 'musicbrainz'})
        original_images = [{'uri': 'http://discogs.com/img.jpg', 'type': 'primary'}]
        album = self._make_album(source='musicbrainz', images=original_images)
        album.id = _MBID
        original_conn = MagicMock()
        result = p._apply_image_source(album, original_conn, '/fake/dir', cfg)
        # Images should be unchanged; original connector returned
        self.assertEqual(album.images, original_images)
        self.assertIs(result, original_conn)

    def test_musicbrainz_source_for_discogs_album_uses_barcode(self):
        """For a Discogs album, barcode is used to look up MBID for CAA images."""
        import musicbrainzngs as _mb
        mb_conn = MagicMock()
        caa_images = [{'uri': 'https://caa/front.jpg', 'type': 'primary',
                       'caa_types': ['Front'], 'width': None, 'height': None}]
        mb_conn.fetch_image_list.return_value = caa_images

        p = self._make_processor(mb_conn=mb_conn)
        cfg = _make_cfg(**{'details.image_source': 'musicbrainz'})
        album = self._make_album(source='discogs', barcode='5099749939523')

        with patch('massmusictagger.processor.musicbrainzngs') as mock_mb:
            mock_mb.search_releases.return_value = {
                'release-list': [{'id': _MBID, 'title': 'Test Album'}]
            }
            original_conn = MagicMock()
            result = p._apply_image_source(album, original_conn, '/fake/dir', cfg)

        mb_conn.fetch_image_list.assert_called_once_with(_MBID)
        self.assertIs(result, mb_conn)
        self.assertEqual(album.images, caa_images)


# ── _find_mbid_for_images() ───────────────────────────────────────────────────

class TestFindMbidForImages(unittest.TestCase):

    def _make_processor(self):
        from massmusictagger.processor import MassProcessor
        p = MassProcessor.__new__(MassProcessor)
        p._discogs_conn = None
        p._mb_conn = MagicMock()
        p._mb_search = MagicMock()
        return p

    def _make_album(self, barcode='', title='Test Album', artist='Test Artist'):
        from discogstagger.album import Album
        a = Album('123', title, [artist])
        a.barcode = barcode
        a.source = 'discogs'
        return a

    def test_returns_mbid_from_barcode(self):
        p = self._make_processor()
        cfg = _make_cfg()
        album = self._make_album(barcode='5099749939523')
        with patch('massmusictagger.processor.musicbrainzngs') as mock_mb:
            mock_mb.search_releases.return_value = {
                'release-list': [{'id': _MBID}]
            }
            result = p._find_mbid_for_images(album, '/fake', cfg)
        self.assertEqual(result, _MBID)

    def test_falls_back_to_text_search_when_no_barcode(self):
        # With no barcode the barcode tier is skipped entirely, so only the
        # text search call is made — one API call, not two.
        p = self._make_processor()
        cfg = _make_cfg()
        album = self._make_album(barcode='', title='Dark Side', artist='Pink Floyd')
        with patch('massmusictagger.processor.musicbrainzngs') as mock_mb:
            mock_mb.search_releases.return_value = {
                'release-list': [{'id': _MBID, 'title': 'Dark Side'}],
            }
            result = p._find_mbid_for_images(album, '/fake', cfg)
        self.assertEqual(result, _MBID)

    def test_returns_none_when_both_fail(self):
        p = self._make_processor()
        cfg = _make_cfg()
        album = self._make_album(barcode='')
        with patch('massmusictagger.processor.musicbrainzngs') as mock_mb:
            mock_mb.search_releases.return_value = {'release-list': []}
            result = p._find_mbid_for_images(album, '/fake', cfg)
        self.assertIsNone(result)

    def test_returns_none_when_both_searches_are_empty(self):
        """When barcode and text searches both return empty lists, None is returned."""
        p = self._make_processor()
        cfg = _make_cfg()
        album = self._make_album(barcode='0000000000000')
        with patch('massmusictagger.processor.musicbrainzngs') as mock_mb:
            mock_mb.search_releases.return_value = {'release-list': []}
            result = p._find_mbid_for_images(album, '/fake', cfg)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
