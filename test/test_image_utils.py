"""Tests for CAA typed image downloading and embedding utilities."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

# The packaged reference config, not a live conf/config.yaml. The suite used
# to point at the latter -- a gitignored file that only exists on a machine
# where someone has configured the tool -- so 68 tests passed here and would
# have failed on a fresh clone or in CI.
from massmusictagger import roots as _roots
MMT_CONFIG = os.path.join(_roots.BUNDLED_CONF, 'config_sample.yaml')


def _make_cfg(**overrides):
    from massmusictagger.core.tagger_config import TaggerConfig
    cfg = TaggerConfig(MMT_CONFIG)
    for sk, v in overrides.items():
        s, _, k = sk.partition('.')
        if not cfg.has_section(s):
            cfg.add_section(s)
        cfg.set(s, k, v)
    return cfg


def _written(connector):
    """Basenames the connector was asked to write.

    The download step used to record its choice on the image dict as
    local_filename; the name is now derived from the sorted attachment list,
    so the observable behaviour is what it asked the connector to write.
    """
    import os as _os
    names = []
    for call in connector.fetch_image.call_args_list:
        for arg in call.args:
            if isinstance(arg, str) and arg.lower().endswith(('.jpg', '.png')):
                names.append(_os.path.basename(arg))
    return names


def _make_album(images):
    """images may be legacy CAA-style dicts; they become Attachments here.

    Keeping the dict fixtures means these tests still describe what the Cover
    Art Archive actually returns, while the code under test sees the one
    normalised shape.
    """
    from massmusictagger.core.album import Album, Disc, Track
    from massmusictagger.core.attachments import Attachment, from_caa
    a = Album('mbid-123', 'Test Album', ['Test Artist'])
    a.attachments = [i if isinstance(i, Attachment) else from_caa(i)
                     for i in (images or [])]
    a.target_dir = '/fake/sorted/Test Artist/[2020] Test Album'
    a.source = 'musicbrainz'
    disc = Disc(1)
    track = Track(1, 'Track One', ['Test Artist'])
    track.new_file = '01 Track One.flac'
    disc.tracks = [track]
    disc.target_dir = None
    a.discs = [disc]
    return a


# ── CAA vocabulary → kind, basename, picture type ────────────────────────────

class TestCaaVocabulary(unittest.TestCase):
    """Replaces TestCaaBasename and TestCaaImageType.

    image_utils carried its own CAA type tables alongside attachments.py's,
    and the two had already drifted apart on five types -- image_utils named
    a tray scan `tray`, attachments flattened it to `other` and called it
    image-01. One table now answers, and these test it through the live path.
    """

    def _att(self, *caa_types):
        from massmusictagger.core.attachments import from_caa
        return from_caa({'uri': 'https://caa/x.jpg', 'caa_types': list(caa_types)})

    def _name(self, att, counter):
        from massmusictagger.core.attachments import basename_for
        return basename_for(att, counter)

    # naming

    def test_front(self):
        self.assertEqual(self._name(self._att('Front'), {}), 'front')

    def test_back(self):
        self.assertEqual(self._name(self._att('Back'), {}), 'back')

    def test_medium(self):
        self.assertEqual(self._name(self._att('Medium'), {}), 'medium')

    def test_booklet_numbering(self):
        c = {}
        self.assertEqual(self._name(self._att('Booklet'), c), 'booklet')
        self.assertEqual(self._name(self._att('Booklet'), c), 'booklet-01')

    def test_front_then_back_independent_counters(self):
        c = {}
        self.assertEqual(self._name(self._att('Front'), c), 'front')
        self.assertEqual(self._name(self._att('Back'), c), 'back')

    def test_a_type_caa_does_not_define_falls_back_to_image(self):
        self.assertEqual(self._name(self._att('Illustration'), {}), 'image-01')

    def test_empty_types_falls_back_to_image(self):
        self.assertEqual(self._name(self._att(), {}), 'image-01')

    def test_the_rest_of_the_vocabulary_is_named_not_numbered(self):
        """These five used to be flattened to `other` and numbered."""
        for caa_type, expected in [('Tray', 'tray'), ('Spine', 'spine'),
                                   ('Sticker', 'sticker'), ('Poster', 'poster'),
                                   ('Liner', 'liner'), ('Obi', 'obi')]:
            with self.subTest(caa_type):
                self.assertEqual(self._name(self._att(caa_type), {}), expected)

    def test_slashed_caa_types_are_handled(self):
        self.assertEqual(self._name(self._att('Matrix/Runout'), {}), 'matrix')
        self.assertEqual(self._name(self._att('Raw/Unedited'), {}), 'raw')

    # embedded picture type

    def test_front_maps_to_front(self):
        from mediafile import ImageType
        from massmusictagger.image_utils import attachment_image_type
        self.assertEqual(attachment_image_type(self._att('Front')), ImageType.front)

    def test_back_maps_to_back(self):
        from mediafile import ImageType
        from massmusictagger.image_utils import attachment_image_type
        self.assertEqual(attachment_image_type(self._att('Back')), ImageType.back)

    def test_booklet_maps_to_leaflet(self):
        from mediafile import ImageType
        from massmusictagger.image_utils import attachment_image_type
        self.assertEqual(attachment_image_type(self._att('Booklet')),
                         ImageType.leaflet)

    def test_liner_notes_are_a_leaflet_page_too(self):
        from mediafile import ImageType
        from massmusictagger.image_utils import attachment_image_type
        self.assertEqual(attachment_image_type(self._att('Liner')),
                         ImageType.leaflet)

    def test_medium_maps_to_media(self):
        from mediafile import ImageType
        from massmusictagger.image_utils import attachment_image_type
        self.assertEqual(attachment_image_type(self._att('Medium')), ImageType.media)

    def test_unknown_maps_to_other(self):
        from mediafile import ImageType
        from massmusictagger.image_utils import attachment_image_type
        self.assertEqual(attachment_image_type(self._att('Tray')), ImageType.other)
        self.assertEqual(attachment_image_type(self._att()), ImageType.other)

    def test_a_named_kind_still_sorts_after_the_album_art(self):
        from massmusictagger.core.attachments import sort_key
        atts = [self._att('Poster'), self._att('Front'), self._att('Back')]
        order = [a.kind for a in sorted(atts, key=sort_key)]
        self.assertEqual(order[0], 'front')
        self.assertEqual(order[-1], 'poster')

    def test_the_deleted_helpers_are_gone(self):
        """image_utils must not grow a second CAA table again."""
        import massmusictagger.image_utils as iu
        for name in ('caa_basename', 'caa_image_type', 'caa_image_type_id',
                     '_CAA_TYPE_BASENAME', '_CAA_TYPE_IMAGE_TYPE_ID',
                     'has_caa_type_metadata'):
            self.assertFalse(hasattr(iu, name),
                             f'{name} is back; there should be one CAA table')


# ── has_caa_type_metadata ─────────────────────────────────────────────────────

class TestProvenanceReplacesSniffing(unittest.TestCase):
    """The source is a property of the attachment, not something to detect.

    has_caa_type_metadata() looked for a caa_types key on the *first* image and
    inferred the source from it. Attachments carry provenance, so nothing has
    to guess -- and a mixed list no longer depends on which image happens to be
    first.
    """

    def test_provenance_survives_normalisation(self):
        from massmusictagger.core.attachments import from_caa, from_discogs
        caa = from_caa({'uri': 'http://x', 'caa_types': ['Front']})
        dg = from_discogs({'uri': 'http://y', 'type': 'primary',
                           'width': 500, 'height': 500})
        self.assertEqual(caa.provenance, 'coverartarchive')
        self.assertEqual(dg.provenance, 'discogs')
        self.assertTrue(caa.is_front and dg.is_front)

    def test_discogs_secondary_is_not_guessed_at(self):
        """Discogs says only primary/secondary, so anything else is `other`."""
        from massmusictagger.core.attachments import from_discogs, OTHER
        a = from_discogs({'uri': 'http://y', 'type': 'secondary'})
        self.assertEqual(a.kind, OTHER)


class TestDownloadTypedImages(unittest.TestCase):
    """Against a real directory, not a mocked filesystem.

    These ran entirely on mocks: a fake target_dir, a MagicMock connector that
    wrote nothing, and assertions on what the connector was *asked* to write.
    That is why prefer_larger could quietly replace a 1400x1400 local scan with
    a 600x600 download and leave two front covers in the directory -- nothing
    here ever looked at a directory. What matters is the files that end up on
    disk, so that is what these assert.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _jpeg(self, w, h):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new('RGB', (w, h), (90, 90, 90)).save(buf, 'JPEG')
        return buf.getvalue()

    def _local(self, name, w, h):
        """Put an existing cover in the target directory."""
        path = os.path.join(self.target, name)
        with open(path, 'wb') as f:
            f.write(self._jpeg(w, h))
        return path

    def _connector(self, size=(600, 600), fail=()):
        """A connector that actually writes bytes, at a stated pixel size."""
        conn = MagicMock()
        payload = self._jpeg(*size)

        def fetch_image(dest, uri):
            if uri in fail:
                raise OSError('404')
            with open(dest, 'wb') as f:
                f.write(payload)

        conn.fetch_image = MagicMock(side_effect=fetch_image)
        return conn

    def _run(self, images, cfg_overrides=None, connector=None):
        from massmusictagger.image_utils import download_typed_images
        cfg = _make_cfg(**(cfg_overrides or {}))
        album = _make_album(images)
        album.target_dir = self.target
        conn = connector or self._connector()
        download_typed_images(album, conn, cfg)
        return album, conn

    def _on_disk(self):
        return sorted(n for n in os.listdir(self.target)
                      if not n.startswith('.'))

    # ── naming ───────────────────────────────────────────────────────────────

    def test_front_downloaded_as_front_jpg(self):
        images = [{'uri': 'https://caa/front.jpg', 'type': 'primary',
                   'caa_types': ['Front'], 'width': None, 'height': None}]
        self._run(images, {'details.download_only_cover': 'false'})
        self.assertIn('front.jpg', self._on_disk())

    def test_back_downloaded_as_back_jpg(self):
        images = [
            {'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
             'type': 'primary', 'width': None, 'height': None},
            {'uri': 'https://caa/back.jpg', 'caa_types': ['Back'],
             'type': 'secondary', 'width': None, 'height': None},
        ]
        self._run(images, {'details.download_only_cover': 'false'})
        self.assertIn('back.jpg', self._on_disk())

    def test_multiple_booklets_numbered(self):
        images = [
            {'uri': 'https://caa/b1.jpg', 'caa_types': ['Booklet'],
             'type': 'secondary', 'width': None, 'height': None},
            {'uri': 'https://caa/b2.jpg', 'caa_types': ['Booklet'],
             'type': 'secondary', 'width': None, 'height': None},
        ]
        self._run(images, {'details.download_only_cover': 'false'})
        written = self._on_disk()
        self.assertIn('booklet.jpg', written)
        self.assertIn('booklet-01.jpg', written)

    def test_download_only_cover_skips_back(self):
        images = [
            {'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
             'type': 'primary', 'width': None, 'height': None},
            {'uri': 'https://caa/back.jpg', 'caa_types': ['Back'],
             'type': 'secondary', 'width': None, 'height': None},
        ]
        self._run(images, {'details.download_only_cover': 'true'})
        written = self._on_disk()
        self.assertIn('front.jpg', written)
        self.assertNotIn('back.jpg', written)

    # ── folder.jpg ───────────────────────────────────────────────────────────

    def test_folder_jpg_written_for_front(self):
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        self._run(images, {'details.use_folder_jpg': 'true',
                           'details.download_only_cover': 'false'})
        written = self._on_disk()
        self.assertIn('folder.jpg', written)
        self.assertEqual(
            open(os.path.join(self.target, 'folder.jpg'), 'rb').read(),
            open(os.path.join(self.target, 'front.jpg'), 'rb').read())

    def test_folder_jpg_is_a_copy_not_a_second_download(self):
        """It used to fetch the same URL twice, once per filename."""
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        _, conn = self._run(images, {'details.use_folder_jpg': 'true',
                                     'details.download_only_cover': 'false'})
        self.assertEqual(conn.fetch_image.call_count, 1)

    # ── image_policy ─────────────────────────────────────────────────────────

    def test_prefer_existing_skips_front_when_local_exists(self):
        self._local('cover.jpg', 1200, 1200)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        _, conn = self._run(images, {'details.image_policy': 'prefer_existing'})
        conn.fetch_image.assert_not_called()

    def test_prefer_larger_measures_a_source_that_states_no_dimensions(self):
        """The bug: CAA never reports width/height.

        att.dimensions is None for every CAA image, so the comparison was
        skipped and the download always won -- prefer_larger was a no-op
        against the one source it was most needed for. A real album lost a
        1400x1400 scan to a 600x600 CAA front this way.
        """
        self._local('cover.jpg', 1400, 1400)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        conn = self._connector(size=(600, 600))
        self._run(images, {'details.image_policy': 'prefer_larger'}, conn)

        from massmusictagger.image_utils import _measure
        self.assertEqual(_measure(os.path.join(self.target, 'front.jpg')),
                         (1400, 1400),
                         'the larger local scan must survive')

    def test_prefer_larger_still_takes_a_bigger_remote_image(self):
        self._local('cover.jpg', 300, 300)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        conn = self._connector(size=(1000, 1000))
        self._run(images, {'details.image_policy': 'prefer_larger'}, conn)

        from massmusictagger.image_utils import _measure
        self.assertEqual(_measure(os.path.join(self.target, 'front.jpg')),
                         (1000, 1000))

    def test_the_measured_image_is_not_downloaded_twice(self):
        """Measuring costs one fetch; keeping it must not cost another."""
        self._local('cover.jpg', 300, 300)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        conn = self._connector(size=(1000, 1000))
        self._run(images, {'details.image_policy': 'prefer_larger',
                           'details.use_folder_jpg': 'false'}, conn)
        self.assertEqual(conn.fetch_image.call_count, 1)

    # ── extension follows the bytes ──────────────────────────────────────────

    def _png(self, w, h):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new('RGB', (w, h), (90, 90, 90)).save(buf, 'PNG')
        return buf.getvalue()

    def test_a_png_served_from_a_jpg_url_is_saved_as_png(self):
        """The extension was chosen from the URL, before any bytes existed.

        extension_for can read the format from the first bytes and its
        docstring says why -- a PNG named .jpg is not read by every player --
        but the pipeline only ever called it with the URL, so that branch
        never ran.
        """
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        conn = MagicMock()
        payload = self._png(600, 600)
        conn.fetch_image = MagicMock(
            side_effect=lambda dest, uri: open(dest, 'wb').write(payload))
        self._run(images, {'details.download_only_cover': 'false',
                           'details.use_folder_jpg': 'false'}, conn)
        written = self._on_disk()
        self.assertIn('front.png', written)
        self.assertNotIn('front.jpg', written)

    def test_a_jpeg_keeps_its_extension(self):
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        self._run(images, {'details.download_only_cover': 'false',
                           'details.use_folder_jpg': 'false'})
        self.assertIn('front.jpg', self._on_disk())

    def test_a_corrected_image_is_still_embedded(self):
        """Embedding looks the file up by basename, so it must find front.png."""
        from massmusictagger.image_utils import _find_written
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        conn = MagicMock()
        payload = self._png(600, 600)
        conn.fetch_image = MagicMock(
            side_effect=lambda dest, uri: open(dest, 'wb').write(payload))
        self._run(images, {'details.download_only_cover': 'false',
                           'details.use_folder_jpg': 'false'}, conn)
        found = _find_written(self.target, 'front')
        self.assertIsNotNone(found)
        self.assertTrue(found.endswith('front.png'))

    # ── one front cover, one name ────────────────────────────────────────────

    def test_a_kept_local_cover_takes_the_canonical_name(self):
        """cover.jpg beside front.jpg is two front covers and no tiebreak.

        The directory ended up holding a 1400x1400 cover.jpg and a 600x600
        front.jpg, with folder.jpg copied from the smaller one -- so what a
        player showed depended on which name it happened to look for first.
        """
        self._local('cover.jpg', 1400, 1400)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        self._run(images, {'details.image_policy': 'prefer_larger',
                           'details.use_folder_jpg': 'true'},
                  self._connector(size=(600, 600)))
        written = self._on_disk()
        self.assertIn('front.jpg', written)
        self.assertNotIn('cover.jpg', written)

        from massmusictagger.image_utils import _measure
        self.assertEqual(_measure(os.path.join(self.target, 'folder.jpg')),
                         (1400, 1400),
                         'folder.jpg must be the cover that won, not the loser')

    def test_a_downloaded_front_replaces_a_local_one_under_another_name(self):
        self._local('cover.jpg', 300, 300)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        self._run(images, {'details.image_policy': 'prefer_larger'},
                  self._connector(size=(1000, 1000)))
        written = self._on_disk()
        self.assertIn('front.jpg', written)
        self.assertNotIn('cover.jpg', written)

    def test_a_discogs_cover_keeps_its_own_name(self):
        """Discogs is untyped, so its album art is `cover`, not `front`."""
        from massmusictagger.core.attachments import from_discogs_list
        images = from_discogs_list([
            {'uri': 'https://img.discogs/a.jpg', 'type': 'primary',
             'width': 600, 'height': 600}])
        self._run(images, {'details.download_only_cover': 'false'})
        self.assertIn('cover.jpg', self._on_disk())

    # ── failure ──────────────────────────────────────────────────────────────

    def test_a_failed_download_leaves_the_local_cover_alone(self):
        self._local('cover.jpg', 1400, 1400)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        conn = self._connector(fail=('https://caa/front.jpg',))
        self._run(images, {'details.image_policy': 'prefer_larger'}, conn)

        from massmusictagger.image_utils import _measure
        self.assertEqual(_measure(os.path.join(self.target, 'cover.jpg')),
                         (1400, 1400))

    def test_a_share_that_refuses_the_scratch_file_still_compares(self):
        """The SMB share this runs against rejected a hidden scratch file.

        "Operation not permitted" was caught and logged, the run carried on,
        and the 600x600 download replaced the 1400x1400 local scan -- the very
        outcome the measurement exists to prevent. A refused scratch write must
        cost a temp-directory round trip, not the comparison.
        """
        self._local('cover.jpg', 1400, 1400)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]

        conn = self._connector(size=(600, 600))
        real = conn.fetch_image.side_effect

        def hostile(dest, uri):
            if os.path.dirname(dest) == self.target and dest.endswith('.part'):
                raise OSError(1, 'Operation not permitted')
            return real(dest, uri)

        conn.fetch_image = MagicMock(side_effect=hostile)
        self._run(images, {'details.image_policy': 'prefer_larger'}, conn)

        from massmusictagger.image_utils import _measure
        self.assertEqual(_measure(os.path.join(self.target, 'front.jpg')),
                         (1400, 1400),
                         'the larger local scan must still win')

    def test_no_scratch_files_are_left_behind(self):
        self._local('cover.jpg', 1400, 1400)
        images = [{'uri': 'https://caa/front.jpg', 'caa_types': ['Front'],
                   'type': 'primary', 'width': None, 'height': None}]
        self._run(images, {'details.image_policy': 'prefer_larger'},
                  self._connector(size=(600, 600)))
        leftovers = [n for n in os.listdir(self.target)
                     if n.startswith('.') or n.endswith('.part')]
        self.assertEqual(leftovers, [])


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

    def test_attachment_whose_file_is_not_on_disk_is_skipped(self):
        """Replaces a test for a missing local_filename key.

        The name is derived now, so that state cannot occur; what can is the
        download having failed, leaving nothing to embed.
        """
        from massmusictagger.image_utils import embed_typed_images
        cfg = _make_cfg(**{'details.embed_coverart': 'true'})
        album = _make_album([{'caa_types': ['Front'], 'uri': 'https://caa/x.jpg',
                              'type': 'primary'}])
        saved = {}

        def mock_mf_factory(path):
            mf = MagicMock()
            mf.save.side_effect = lambda: saved.setdefault(path, mf.images)
            return mf

        with patch('massmusictagger.image_utils.MediaFile', side_effect=mock_mf_factory):
            with patch('os.path.exists', return_value=False):
                embed_typed_images(album, cfg)
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


class TestDiscogsFileHandlerPath(unittest.TestCase):
    """The Discogs download path, which no unit test covered.

    Phase 4 changed FileHandler.get_images() from dict access to Attachment
    attributes, and left a reference to a variable it had removed. The suite
    passed; two real albums failed with "name 'image_type' is not defined".
    """

    def _album_with(self, attachments):
        from massmusictagger.core.album import Album
        a = Album('123', 'Test Album', ['Test Artist'])
        a.attachments = attachments
        a.target_dir = '/fake/target'
        return a

    def test_get_images_runs_over_attachments(self):
        from massmusictagger.core.attachments import from_discogs
        from massmusictagger.core.taggerutils import FileHandler

        album = self._album_with([
            from_discogs({'uri': 'https://img/front.jpg', 'type': 'primary',
                          'width': 600, 'height': 600}),
            from_discogs({'uri': 'https://img/other.jpg', 'type': 'secondary',
                          'width': 300, 'height': 300}),
        ])
        cfg = _make_cfg(**{'details.download_only_cover': 'false',
                           'details.image_policy': 'always',
                           'details.use_folder_jpg': 'false',
                           'file-formatting.image': 'image'})
        fh = FileHandler.__new__(FileHandler)
        fh.album, fh.config = album, cfg
        fh.create_album_dir = lambda: None
        fh._best_local_cover = lambda: (None, None, None)

        conn = MagicMock()
        with patch('os.makedirs'), \
             patch('massmusictagger.core.taggerutils.write_file'):
            fh.get_images(conn)

        # The point: it completes and asks for both images, rather than
        # raising NameError partway through.
        self.assertEqual(conn.fetch_image.call_count, 2)

    def test_front_policy_reads_dimensions_from_the_attachment(self):
        """prefer_larger compares against Attachment.dimensions, not a dict."""
        from massmusictagger.core.attachments import from_discogs
        from massmusictagger.core.taggerutils import FileHandler

        fh = FileHandler.__new__(FileHandler)
        small = from_discogs({'uri': 'u', 'type': 'primary',
                              'width': 100, 'height': 100})
        big = from_discogs({'uri': 'u', 'type': 'primary',
                            'width': 2000, 'height': 2000})
        unknown = from_discogs({'uri': 'u', 'type': 'primary'})

        self.assertTrue(fh._should_skip_front_cover(small, (500, 500), 'prefer_larger'))
        self.assertFalse(fh._should_skip_front_cover(big, (500, 500), 'prefer_larger'))
        # CAA reports no dimensions; not knowing must not mean "skip".
        self.assertFalse(fh._should_skip_front_cover(unknown, (500, 500), 'prefer_larger'))
