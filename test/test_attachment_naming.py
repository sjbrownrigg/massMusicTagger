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

    def test_discogs_secondaries_become_image_xx(self):
        """The case this convention exists to catch."""
        atts = [from_discogs({'uri': 'https://img/a.jpg', 'type': 'primary'}),
                from_discogs({'uri': 'https://img/b.jpg', 'type': 'secondary'}),
                from_discogs({'uri': 'https://img/c.jpg', 'type': 'secondary'})]
        self.assertEqual(self._names(atts),
                         ['front.jpg', 'image-01.jpg', 'image-02.jpg'])

    def test_caa_and_discogs_name_the_front_cover_identically(self):
        caa = from_caa({'uri': 'https://caa/x', 'caa_types': ['Front']})
        dg = from_discogs({'uri': 'https://img/y.jpg', 'type': 'primary'})
        self.assertEqual(basename_for(caa, {}), basename_for(dg, {}))

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
