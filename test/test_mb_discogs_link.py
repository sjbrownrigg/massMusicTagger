"""Following the Discogs link MusicBrainz already gave us.

MusicBrainz editors curate a URL relation to the equivalent Discogs release.
Measured on this library, about a third of the albums that fell through to
MusicBrainz carry one -- Henry's Dream, Station to Station, Music For A
Slaughtering Tribe -- every one an album Discogs holds and our Discogs search
failed to find.

The relations ride along on the release fetch (`url-rels` in _INCLUDES), so
reading them costs no additional request.
"""

import unittest
from unittest.mock import MagicMock, patch

from massmusictagger import cascade


class ExtractionTest(unittest.TestCase):

    def test_it_finds_the_release_id(self):
        raw = {'url-relation-list': [
            {'target': 'https://www.discogs.com/release/600966'}]}
        self.assertEqual(cascade.discogs_release_from_mb(raw), '600966')

    def test_it_reads_the_json_shape_too(self):
        """musicbrainzngs and the raw JSON API disagree on the key."""
        raw = {'url-relation-list': [
            {'url': {'resource': 'https://www.discogs.com/release/193537'}}]}
        self.assertEqual(cascade.discogs_release_from_mb(raw), '193537')

    def test_a_localised_url_still_matches(self):
        raw = {'url-relation-list': [
            {'target': 'https://www.discogs.com/de/release/4513513'}]}
        self.assertEqual(cascade.discogs_release_from_mb(raw), '4513513')

    def test_an_artist_link_is_not_a_release_link(self):
        raw = {'url-relation-list': [
            {'target': 'https://www.discogs.com/artist/36665'}]}
        self.assertIsNone(cascade.discogs_release_from_mb(raw))

    def test_other_relations_are_ignored(self):
        raw = {'url-relation-list': [
            {'target': 'https://en.wikipedia.org/wiki/Henry%27s_Dream'},
            {'target': 'https://www.discogs.com/release/600966'}]}
        self.assertEqual(cascade.discogs_release_from_mb(raw), '600966')

    def test_no_relations_is_not_an_error(self):
        self.assertIsNone(cascade.discogs_release_from_mb({}))
        self.assertIsNone(cascade.discogs_release_from_mb({'url-relation-list': []}))


class PreferenceTest(unittest.TestCase):
    """Someone who asked for MusicBrainz first must not be handed Discogs."""

    def _cfg(self, priority):
        cfg = MagicMock()
        with patch.object(cascade, '_get_priority', return_value=priority):
            return cascade._prefers_discogs(cfg)

    def test_discogs_first_follows_the_link(self):
        self.assertTrue(self._cfg(['discogs', 'musicbrainz']))

    def test_musicbrainz_first_does_not(self):
        self.assertFalse(self._cfg(['musicbrainz', 'discogs']))

    def test_musicbrainz_only_does_not(self):
        self.assertFalse(self._cfg(['musicbrainz']))

    def test_discogs_only_does(self):
        self.assertTrue(self._cfg(['discogs']))


class WiringTest(unittest.TestCase):

    def test_the_relations_are_requested_on_the_existing_call(self):
        from massmusictagger.sources.musicbrainz import connector
        self.assertIn('url-rels', connector._INCLUDES)

    def test_the_link_is_validated_before_it_is_used(self):
        """A stale link must not replace a good MusicBrainz match."""
        import inspect
        src = inspect.getsource(cascade._resolve_musicbrainz)
        self.assertIn('_fetch_discogs_with_validation', src)
        self.assertIn('keeping the ', src)

    def test_it_happens_before_the_musicbrainz_mapping(self):
        import inspect
        src = inspect.getsource(cascade._resolve_musicbrainz)
        self.assertLess(src.index('discogs_release_from_mb'),
                        src.index('make_mb_mapper'))


if __name__ == '__main__':
    unittest.main()
