# -*- coding: utf-8 -*-
"""Artwork follows the Cover Art Archive convention, whatever the source.

Recognised kinds keep their own name -- front, back, medium, booklet -- and
gain a number only when there is more than one. Anything untyped becomes
image-01, image-02, …, which is where Discogs secondary images land: Discogs
says only primary/secondary, so there is no single "the" unknown image.

Extensions follow the actual format. Everything used to be written .jpg, which
leaves a PNG that some players will not read.
"""

import os
import sys
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parentdir)

from massmusictagger.core.attachments import (
    Attachment, basename_for, extension_for, from_caa, from_discogs,
    FRONT, BACK, MEDIUM, BOOKLET, OTHER, sort_key)


class Naming(unittest.TestCase):

    def _names(self, attachments):
        counter = {}
        return [basename_for(a, counter) + extension_for(a)
                for a in sorted(attachments, key=sort_key)]

    def test_caa_convention_for_recognised_kinds(self):
        names = self._names([
            Attachment('u/1.jpg', FRONT), Attachment('u/2.jpg', BACK),
            Attachment('u/3.jpg', MEDIUM), Attachment('u/4.jpg', BOOKLET),
        ])
        self.assertEqual(names, ['front.jpg', 'back.jpg', 'booklet.jpg', 'medium.jpg'])

    def test_repeats_are_numbered_but_the_first_is_not(self):
        names = self._names([Attachment(f'u/{i}.jpg', BOOKLET) for i in range(3)])
        self.assertEqual(names, ['booklet.jpg', 'booklet-01.jpg', 'booklet-02.jpg'])

    def test_untyped_images_are_numbered_from_one(self):
        """image-01, not image — there is no single 'the' unknown image."""
        names = self._names([Attachment(f'u/{i}.jpg', OTHER) for i in range(2)])
        self.assertEqual(names, ['image-01.jpg', 'image-02.jpg'])

    def test_discogs_main_image_is_cover_and_the_rest_are_numbered(self):
        """Discogs primary/secondary is not an image type, so: cover, not front."""
        atts = [from_discogs({'uri': 'https://img/a.jpg', 'type': 'primary'}),
                from_discogs({'uri': 'https://img/b.jpg', 'type': 'secondary'}),
                from_discogs({'uri': 'https://img/c.jpg', 'type': 'secondary'})]
        self.assertEqual(self._names(atts),
                         ['cover.jpg', 'image-01.jpg', 'image-02.jpg'])

    def test_caa_and_discogs_name_their_album_art_differently(self):
        """The name records how much the source told us.

        The Cover Art Archive distinguishes a front from a back, so `front`
        is a claim it supports. Discogs says only primary/secondary, so
        `cover` is the honest name -- this is the album art, without asserting
        which face of the sleeve it shows.
        """
        caa = from_caa({'uri': 'https://caa/x', 'caa_types': ['Front']})
        dg = from_discogs({'uri': 'https://img/y.jpg', 'type': 'primary'})
        self.assertEqual(basename_for(caa, {}), 'front')
        self.assertEqual(basename_for(dg, {}), 'cover')

    def test_both_are_treated_as_album_art(self):
        """Different names, same handling: policy and embedding see one thing."""
        from massmusictagger.image_utils import attachment_image_type
        from mediafile import ImageType
        caa = from_caa({'uri': 'https://caa/x', 'caa_types': ['Front']})
        dg = from_discogs({'uri': 'https://img/y.jpg', 'type': 'primary'})
        for a in (caa, dg):
            self.assertTrue(a.is_front)
            self.assertEqual(attachment_image_type(a), ImageType.front)

    def test_front_sorts_first_so_naming_is_stable(self):
        atts = [Attachment('u/b.jpg', BACK), Attachment('u/f.jpg', FRONT)]
        self.assertEqual(self._names(atts), ['front.jpg', 'back.jpg'])


class Extensions(unittest.TestCase):

    def test_taken_from_the_url(self):
        for url, want in (('https://x/a.png', '.png'), ('https://x/a.JPG', '.jpg'),
                          ('https://x/a.jpeg', '.jpg'), ('https://x/a.webp', '.webp')):
            self.assertEqual(extension_for(Attachment(url, FRONT)), want, url)

    def test_query_strings_do_not_confuse_it(self):
        self.assertEqual(
            extension_for(Attachment('https://x/a.png?width=500', FRONT)), '.png')

    def test_bytes_win_when_the_url_is_silent(self):
        """CAA front URLs have no extension at all."""
        att = Attachment('https://coverartarchive.org/release/abc/front', FRONT)
        self.assertEqual(extension_for(att, b'\x89PNG\r\n\x1a\n'), '.png')
        self.assertEqual(extension_for(att, b'\xff\xd8\xff\xe0'), '.jpg')

    def test_falls_back_to_jpg_when_nothing_says(self):
        att = Attachment('https://coverartarchive.org/release/abc/front', FRONT)
        self.assertEqual(extension_for(att), '.jpg')


class DiscogsFrontCoverPromotion(unittest.TestCase):
    """Discogs releases without a 'primary' image still get a front cover.

    21% of the 22,811 cached Discogs releases carrying images have no entry
    marked primary -- every one is secondary. Mapped individually those all
    become `other`, so the release got image-01.jpg and its embedded art was
    typed `other`, which players do not necessarily show as album art. A real
    tagging run produced exactly that before this was added.
    """

    def test_first_image_is_promoted_when_nothing_is_primary(self):
        from massmusictagger.core.attachments import from_discogs_list
        atts = from_discogs_list([
            {'uri': 'https://img/a.jpg', 'type': 'secondary'},
            {'uri': 'https://img/b.jpg', 'type': 'secondary'},
        ])
        from massmusictagger.core.attachments import COVER
        self.assertEqual(atts[0].kind, COVER)
        self.assertEqual(atts[0].url, 'https://img/a.jpg',
                         'Discogs lists images cover-first')
        self.assertFalse(atts[1].is_front)

    def test_an_explicit_primary_is_not_overridden(self):
        from massmusictagger.core.attachments import from_discogs_list
        atts = from_discogs_list([
            {'uri': 'https://img/a.jpg', 'type': 'secondary'},
            {'uri': 'https://img/b.jpg', 'type': 'primary'},
        ])
        self.assertFalse(atts[0].is_front)
        self.assertTrue(atts[1].is_front)

    def test_promotion_preserves_everything_else(self):
        from massmusictagger.core.attachments import from_discogs_list
        att = from_discogs_list([{'uri': 'https://img/a.jpg', 'type': 'secondary',
                                  'width': 600, 'height': 600}])[0]
        self.assertEqual(att.dimensions, (600, 600))
        self.assertEqual(att.provenance, 'discogs')

    def test_empty_list_is_not_a_problem(self):
        from massmusictagger.core.attachments import from_discogs_list
        self.assertEqual(from_discogs_list([]), [])
        self.assertEqual(from_discogs_list(None), [])

    def test_a_promoted_front_embeds_as_front(self):
        """The point: the picture type players actually look for."""
        from massmusictagger.core.attachments import from_discogs_list
        from massmusictagger.image_utils import attachment_image_type
        from mediafile import ImageType
        att = from_discogs_list([{'uri': 'https://img/a.jpg',
                                  'type': 'secondary'}])[0]
        self.assertEqual(attachment_image_type(att), ImageType.front)


class CoverCollidesWithTheSourceFolder(unittest.TestCase):
    """`cover.jpg` is also what a source folder often already contains.

    copy_other_files() brings the ripper's own cover.jpg across before any
    download happens, so the downloaded album art can land on the same name.
    That is handled, not accidental: the local-cover check looks for
    front.jpg, folder.jpg and cover.jpg, so image_policy compares against
    whatever is already there and prefer_larger keeps the better one.
    """

    def test_local_cover_check_includes_the_name_we_now_write(self):
        import inspect
        from massmusictagger import image_utils
        src = inspect.getsource(image_utils._local_front_dimensions)
        for name in ('front.jpg', 'folder.jpg', 'cover.jpg'):
            self.assertIn(name, src,
                          f'{name} must be recognised as an existing cover')

    def test_untyped_album_art_still_drives_folder_jpg(self):
        """use_folder_jpg keys off is_front, which `cover` satisfies."""
        from massmusictagger.core.attachments import from_discogs_list
        att = from_discogs_list([{'uri': 'https://img/a.jpg',
                                  'type': 'secondary'}])[0]
        self.assertTrue(att.is_front,
                        'a promoted cover must still count as album art')
