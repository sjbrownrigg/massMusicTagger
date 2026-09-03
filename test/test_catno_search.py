"""Search by catalogue number, not just score by it.

A catalogue number identifies one *pressing*, which is exactly what the other
tiers cannot do — they find the release and then guess the edition. That guess
has cost real mistakes: the Music On Vinyl pressing of *Ultra* (MOVLP945)
matched a CD with a different catalogue number, and DHS's *House Of God* was
filed twice because two databases described the same 12" release differently.

The number was already extracted from the folder name and the catalognum tag,
but only ever adjusted the score of candidates another tier had already
retrieved (`score -= 10.0`). A pressing nobody else found could not be scored
at all, because it was never fetched.
"""

import unittest
from unittest.mock import MagicMock

from massmusictagger.sources.discogs.search import DiscogsSearch, SearchState


def _searcher(results=None, recorder=None):
    s = DiscogsSearch.__new__(DiscogsSearch)
    client = MagicMock()

    def search(**kwargs):
        if recorder is not None:
            recorder.append(kwargs)
        return results or []
    client.search = search
    s.discogs_client = client
    s._siftReleases = lambda rels, state: state.candidates.setdefault(0.0, rels[0])
    return s


def _state(hints):
    st = SearchState()
    st.params = {'catalog_hints': frozenset(hints) if hints else None}
    return st


class TierTest(unittest.TestCase):

    def test_it_searches_on_the_catalogue_number(self):
        calls = []
        s = _searcher(results=[MagicMock()], recorder=calls)
        s._search_catalog_number(_state({'MOVLP945'}))
        self.assertEqual(calls[0]['catno'], 'MOVLP945')
        self.assertEqual(calls[0]['type'], 'release')

    def test_no_hint_means_no_request(self):
        calls = []
        _searcher(recorder=calls)._search_catalog_number(_state(None))
        self.assertEqual(calls, [], 'must not search when there is nothing to search for')

    def test_it_stops_once_something_is_found(self):
        calls = []
        s = _searcher(results=[MagicMock()], recorder=calls)
        s._search_catalog_number(_state({'AAA111', 'BBB222', 'CCC333'}))
        self.assertEqual(len(calls), 1, 'no further lookups after a candidate exists')

    def test_the_number_of_lookups_is_bounded(self):
        """More than a couple of hints means they are guesses, not numbers."""
        calls = []
        s = _searcher(results=[], recorder=calls)
        s._search_catalog_number(_state({'A1', 'B2', 'C3', 'D4', 'E5'}))
        self.assertLessEqual(len(calls), DiscogsSearch._CATNO_LOOKUPS)

    def test_an_api_failure_is_not_fatal(self):
        s = DiscogsSearch.__new__(DiscogsSearch)
        s.discogs_client = MagicMock()
        s.discogs_client.search.side_effect = Exception('502')
        s._siftReleases = lambda r, st: None
        s._search_catalog_number(_state({'AAA111'}))   # must not raise

    def test_artist_results_are_ignored(self):
        """The search endpoint can return artist entities; they are not releases."""
        artist = MagicMock()
        type(artist).__name__ = 'Artist'
        sifted = []
        s = _searcher(results=[artist])
        s._siftReleases = lambda rels, state: sifted.extend(rels)
        s._search_catalog_number(_state({'AAA111'}))
        self.assertEqual(sifted, [])


class LadderTest(unittest.TestCase):

    def test_it_runs_before_the_field_searches(self):
        """A pressing identified outright should not wait behind a guess."""
        import inspect
        src = inspect.getsource(DiscogsSearch.search_discogs)
        self.assertLess(src.index('_search_catalog_number'),
                        src.index('_search_release_fields'))

    def test_it_only_retrieves_and_does_not_accept(self):
        """A hint that is really a year must cost a request, not a wrong match."""
        import inspect
        src = inspect.getsource(DiscogsSearch._search_catalog_number)
        self.assertIn('_siftReleases', src)
        self.assertNotIn('return True', src)


if __name__ == '__main__':
    unittest.main()
