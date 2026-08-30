"""Catalog-number hints extracted from a folder's trailing parenthetical.

The hint is worth -10 in candidate ranking -- decisive, because regional and
format reissues routinely share a track count and near-identical durations,
and the catalog number is the only thing separating them. When extraction
fails the signal is simply absent and the wrong pressing can win, silently.

The old extractor required a single token containing both a letter and a
digit, which missed every space-separated number. Measured over a 554-album
library it failed on 372 of the 456 titles carrying a trailing group.
"""

import unittest

from massmusictagger.sources.discogs.utils import (
    catalog_hint_from_tag,
    extract_catalog_hint,
    extract_catalog_hints,
    normalize_catalog_number,
)


class SpaceSeparatedTest(unittest.TestCase):
    """The regression that cost the most: numbers written with spaces."""

    def test_purely_numeric_with_spaces(self):
        # Sony/Columbia style. Previously returned None.
        hints = extract_catalog_hints('Delta Machine (Deluxe Edition) (88765 46063 2)')
        self.assertIn('88765460632', hints)

    def test_matches_the_discogs_side_after_normalising(self):
        """Both sides must normalise to the same string, or the -10 never fires."""
        hints = extract_catalog_hints('Delta Machine (Deluxe Edition) (88765 46063 2)')
        self.assertIn(normalize_catalog_number('88765460632'), hints)

    def test_short_numeric_with_space(self):
        self.assertIn('5119369', extract_catalog_hints('Hours... (511936 9)'))

    def test_letters_then_digits(self):
        # 'CK' carries no digit and '86656' no letter, so neither token
        # matched the old rule; taken whole it is a valid catalog number.
        self.assertIn('ck86656', extract_catalog_hints('Heathen (CK 86656)'))

    def test_label_prefix_forms_seen_in_the_library(self):
        for title, expected in (
            ('Headless (MET 1010)', 'met1010'),
            ('What Remains Is Black (SCAN 106)', 'scan106'),
            ('Music For A Slaughtering Tribe (VUZ 03)', 'vuz03'),
            ('Black Door (DIGITAL FACT 025)', 'digitalfact025'),
        ):
            with self.subTest(title=title):
                self.assertIn(expected, extract_catalog_hints(title))

    def test_non_alphanumeric_separator_is_preserved_on_both_sides(self):
        # normalize strips only whitespace and hyphens, so '~' survives in
        # both the folder name and the Discogs catno and still compares equal.
        hints = extract_catalog_hints('Spirit (SICP 30937~8)')
        self.assertIn(normalize_catalog_number('SICP 30937~8'), hints)


class DescriptorTest(unittest.TestCase):
    """A descriptor before the number must not swallow it."""

    def test_descriptor_plus_number_yields_the_number_alone(self):
        hints = extract_catalog_hints('In Your Room (Maxi XLCDBong24)')
        self.assertIn('xlcdbong24', hints)

    def test_single_token_still_works(self):
        self.assertIn('bxstumm300',
                      extract_catalog_hints('Sounds Of The Universe (Deluxe Edition) (BXSTUMM300)'))
        self.assertIn('tocp70150', extract_catalog_hints('Low (TOCP-70150)'))


class RejectionTest(unittest.TestCase):
    """False positives cost more than misses: -10 on a wrong release."""

    def test_plain_descriptor_is_not_a_catalog_number(self):
        for title in ('Some Album (Deluxe Edition)',
                      'Octopus (special edition)',
                      'TRON- Ares (hi-res)'):
            with self.subTest(title=title):
                self.assertEqual(extract_catalog_hints(title), frozenset())

    def test_a_bare_year_is_a_date_not_a_catalog_number(self):
        for year in ('(1976)', '(2013)', '(1999)'):
            with self.subTest(year=year):
                self.assertEqual(extract_catalog_hints(f'Some Album {year}'),
                                 frozenset())

    def test_no_trailing_group(self):
        self.assertEqual(extract_catalog_hints('Just A Title'), frozenset())

    def test_too_short_to_be_distinctive(self):
        # 'V 9' -> 'v9'. A real catalog number, but two characters collide
        # with too much; a miss is safer than a wrong -10.
        self.assertEqual(extract_catalog_hints('The Oma Thule Single (V 9)'),
                         frozenset())


class SingularWrapperTest(unittest.TestCase):

    def test_returns_the_most_specific_candidate(self):
        # '88765460632' and '460632' are both offered; the longer one is the
        # least likely to collide.
        self.assertEqual(
            extract_catalog_hint('Delta Machine (Deluxe Edition) (88765 46063 2)'),
            '88765460632')

    def test_none_when_nothing_looks_like_a_catalog_number(self):
        self.assertIsNone(extract_catalog_hint('Some Album (Deluxe Edition)'))


class ScoringWiringTest(unittest.TestCase):
    """The extractor is useless if the ranking never consults it."""

    def test_search_stores_hints_and_score_consumes_them(self):
        import inspect
        from massmusictagger.sources.discogs import search

        src = inspect.getsource(search)
        # Producer and consumer must agree on the key, or the signal is lost
        # silently -- which is exactly how this defect survived.
        self.assertIn("searchParams['catalog_hints']", src)
        self.assertIn("searchParams.get('catalog_hints')", src)
        self.assertIn('catnos & catalog_hints', src)


class TagHintTest(unittest.TestCase):
    """The catalognum tag, which is where the number usually actually is.

    Delta Machine matched the wrong pressing for exactly this reason: its
    album tag was 'Delta Machine' with no number in it, so title parsing
    yielded nothing -- while the files carried catalognum '88765 46063 2'
    all along. 73% of a 60-album sample had the tag.
    """

    def test_spaced_number_from_a_tag(self):
        self.assertEqual(catalog_hint_from_tag('88765 46063 2'), '88765460632')

    def test_matches_the_discogs_side(self):
        self.assertEqual(catalog_hint_from_tag('88765 46063 2'),
                         normalize_catalog_number('88765 46063 2'))

    def test_empty_and_none(self):
        self.assertIsNone(catalog_hint_from_tag(''))
        self.assertIsNone(catalog_hint_from_tag(None))

    def test_junk_values_are_rejected(self):
        for junk in ('none', 'n/a', '--'):
            with self.subTest(value=junk):
                self.assertIsNone(catalog_hint_from_tag(junk))

    def test_a_year_in_the_tag_is_not_a_catalog_number(self):
        self.assertIsNone(catalog_hint_from_tag('2013'))

    def test_search_consults_the_tag(self):
        """Wiring: the tag must reach the hint set, not just the title."""
        import inspect
        from massmusictagger.sources.discogs import search
        src = inspect.getsource(search)
        self.assertIn('catalog_hint_from_tag', src)
        self.assertIn("getattr(metadata, 'catalognum', None)", src)


class SearchCacheVersionTest(unittest.TestCase):
    """A cached decision must not outlive the rules that produced it.

    Spirit matched a single-disc release because a cached entry named one
    release, it was accepted, and the search stopped there -- the correct
    pressing was never compared. Cold, the same album compared 40 releases.
    The fix existed; the cache hid it.
    """

    def _cache(self, tmp):
        from massmusictagger.core.cache import SearchCache
        return SearchCache(tmp)

    def test_version_is_part_of_the_key(self):
        import tempfile, shutil
        from massmusictagger.core.cache import SearchCache
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)

        c = SearchCache(tmp)
        first = c._path('Depeche Mode|Spirit|2017', 'fields_year')

        original = SearchCache.SEARCH_LOGIC_VERSION
        try:
            SearchCache.SEARCH_LOGIC_VERSION = original + 1
            bumped = SearchCache(tmp)._path('Depeche Mode|Spirit|2017', 'fields_year')
        finally:
            SearchCache.SEARCH_LOGIC_VERSION = original

        self.assertNotEqual(first, bumped,
                            'bumping the version must retire stored decisions')

    def test_a_stored_decision_is_not_read_back_after_a_bump(self):
        import tempfile, shutil
        from massmusictagger.core.cache import SearchCache
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)

        SearchCache(tmp).put('q', 'fields', [{'id': 1, 'is_master': False}])
        self.assertIsNotNone(SearchCache(tmp).get('q', 'fields'))

        original = SearchCache.SEARCH_LOGIC_VERSION
        try:
            SearchCache.SEARCH_LOGIC_VERSION = original + 1
            self.assertIsNone(SearchCache(tmp).get('q', 'fields'))
        finally:
            SearchCache.SEARCH_LOGIC_VERSION = original

    def test_same_version_still_round_trips(self):
        import tempfile, shutil
        from massmusictagger.core.cache import SearchCache
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        results = [{'id': 10013737, 'is_master': False}]
        SearchCache(tmp).put('q', 'fields', results)
        self.assertEqual(SearchCache(tmp).get('q', 'fields'), results)


if __name__ == '__main__':
    unittest.main()
