"""A failed search is retried under the artist's other names.

Every Discogs tier is anchored on the artist string from the local tags, so
when that names the wrong artist the right release is never retrieved -- not
ranked poorly, absent. Nick Cave's *Idiot Prayer* is credited on Discogs to
`Nick Cave`; the rip said `Nick Cave & The Bad Seeds`; 111 releases of the
wrong artist were compared and refused, and the two correct releases -- which
agree on 22 of 22 track lengths -- were never fetched.

The names were already in hand. `/artists/36665`, which the browse tier
fetches, returns:

    namevariations  Bad Seeds, Nick Cave, Nick Cave And The Bad Seeds, …
    aliases         Nick Cave & The Cavemen
    members         Mick Harvey, Nick Cave, Blixa Bargeld, Warren Ellis, …

so this tier costs no extra artist lookups.
"""

import unittest
from unittest.mock import MagicMock

from massmusictagger.sources.discogs.search import DiscogsSearch, SearchState


BAD_SEEDS = {
    'namevariations': ['Bad Seeds', 'Nick Cave', 'Nick Cave & Bad Seeds',
                       'Nick Cave And The Bad Seeds'],
    'aliases': [{'name': 'Nick Cave & The Cavemen'}],
    'members': [{'name': 'Mick Harvey'}, {'name': 'Nick Cave'},
                {'name': 'Blixa Bargeld'}],
}


def _searcher(limit=6):
    s = DiscogsSearch.__new__(DiscogsSearch)
    s.artist_name_variations = limit
    s.normalize = lambda x: (x or '').strip()
    return s


def _state(artist='Nick Cave & The Bad Seeds', data=BAD_SEEDS):
    st = SearchState()
    st.params = {'search': {'artist': artist}}
    if data is not None:
        entity = MagicMock()
        entity.data = data
        st.artist_entity = entity
    return st


class AlternateNameTest(unittest.TestCase):

    def test_the_solo_credit_is_offered(self):
        names = _searcher().artist_alternate_names(_state())
        self.assertIn('Nick Cave', names)

    def test_namevariations_come_before_members(self):
        """Same act spelled differently is a stronger prior than a member."""
        names = _searcher().artist_alternate_names(_state())
        self.assertLess(names.index('Bad Seeds'), names.index('Mick Harvey'))

    def test_the_searched_name_is_not_repeated(self):
        names = _searcher().artist_alternate_names(_state(artist='Bad Seeds'))
        self.assertNotIn('Bad Seeds', names, 'that search has just failed')

    def test_duplicates_across_the_three_lists_appear_once(self):
        names = _searcher().artist_alternate_names(_state())
        self.assertEqual(names.count('Nick Cave'), 1,
                         'it is both a namevariation and a member')

    def test_no_entity_means_no_names(self):
        st = _state(); st.artist_entity = None
        self.assertEqual(_searcher().artist_alternate_names(st), [])

    def test_an_entity_without_the_fields_is_harmless(self):
        self.assertEqual(_searcher().artist_alternate_names(_state(data={})), [])


class TierTest(unittest.TestCase):

    def _run(self, limit=6, stop_after=None):
        s = _searcher(limit)
        st = _state()
        tried = []
        def fake(state, include_year=False):
            tried.append(state.params['search']['artist'])
            if stop_after is not None and len(tried) >= stop_after:
                state.candidates[0.0] = MagicMock()
            return None
        s._search_release_fields = fake
        s.search_artist_variations(st)
        return tried, st

    def test_it_searches_under_each_name(self):
        tried, _ = self._run()
        self.assertIn('Nick Cave', tried)

    def test_it_stops_as_soon_as_something_is_found(self):
        tried, _ = self._run(stop_after=1)
        self.assertEqual(len(tried), 1, 'no calls after a candidate exists')

    def test_the_limit_caps_the_calls(self):
        tried, _ = self._run(limit=2)
        self.assertEqual(len(tried), 2)

    def test_zero_disables_the_tier(self):
        tried, _ = self._run(limit=0)
        self.assertEqual(tried, [])

    def test_the_original_artist_is_restored(self):
        """Later tiers must not inherit a name this one was trying."""
        _, st = self._run()
        self.assertEqual(st.params['search']['artist'], 'Nick Cave & The Bad Seeds')


class WiringTest(unittest.TestCase):

    def test_the_browse_tier_keeps_the_entity_it_fetched(self):
        import inspect
        src = inspect.getsource(DiscogsSearch.search_artist)
        self.assertIn('state.artist_entity = result', src)

    def test_the_tier_runs_after_the_artist_browse(self):
        import inspect
        src = inspect.getsource(DiscogsSearch.search_discogs)
        self.assertLess(src.index('self.search_artist(state)'),
                        src.index('self.search_artist_variations(state)'))


if __name__ == '__main__':
    unittest.main()


class ANVResolutionTest(unittest.TestCase):
    """An act credited differently across a career still resolves.

    Discogs keeps `namevariations` because acts are credited differently over
    time. Matching the search only against the canonical name meant a rip
    tagged "Nick Cave And The Bad Seeds" or "Einsturzende Neubauten" resolved
    to no artist at all -- so the browse tier found nothing and the variations
    tier had no names to work from either.
    """

    def _result(self, name, variations=()):
        r = MagicMock()
        r.name = name
        r.data = {'namevariations': list(variations)}
        return r

    def test_the_canonical_name_matches_without_a_fetch(self):
        s = _searcher()
        r = self._result('Nick Cave & The Bad Seeds')
        self.assertTrue(s._artist_result_matches(
            'Nick Cave & The Bad Seeds', r, inspect_variations=False))

    def test_a_name_variation_matches(self):
        s = _searcher()
        r = self._result('Einstürzende Neubauten',
                         ['Einsturzende Neubauten', 'E.N.'])
        self.assertTrue(s._artist_result_matches(
            'Einsturzende Neubauten', r, inspect_variations=True))

    def test_variations_are_not_read_when_inspection_is_off(self):
        """The cost bound: reading them forces the full artist fetch."""
        s = _searcher()
        r = self._result('Einstürzende Neubauten', ['Einsturzende Neubauten'])
        self.assertFalse(s._artist_result_matches(
            'Einsturzende Neubauten', r, inspect_variations=False))

    def test_an_unrelated_artist_still_does_not_match(self):
        s = _searcher()
        r = self._result('Nick Drake', ['Nicholas Drake'])
        self.assertFalse(s._artist_result_matches(
            'Nick Cave', r, inspect_variations=True))

    def test_a_result_without_data_is_harmless(self):
        s = _searcher()
        r = MagicMock(); r.name = 'X'; r.data = None
        self.assertFalse(s._artist_result_matches('Y', r, inspect_variations=True))

    def test_an_unmatched_search_still_leaves_names_to_retry(self):
        """Otherwise a mis-credited album has nothing to fall back on."""
        import inspect
        src = inspect.getsource(DiscogsSearch.search_artist)
        self.assertIn('if state.artist_entity is None and fallback is not None:', src)


NICK_CAVE_PERSON = {
    # The real shape: ten-plus initialisms, and the answer sitting in groups.
    'namevariations': ['Cave', 'Cave N', 'Cave Nicholas Edward', 'N Cave',
                       'N. Cave', 'N. E. Cave', 'N.Cave', 'N.E. Cave',
                       'N.E.Cave', 'Nicholas Cave'],
    'aliases': [{'name': 'A Drunk Cowboy Junkie'}, {'name': 'Her Dead Twin'}],
    'groups': [{'name': 'Nick Cave & The Bad Seeds'},
               {'name': 'The Birthday Party'},
               {'name': 'Nick Cave & Warren Ellis'}],
}


class GroupsTest(unittest.TestCase):
    """The other direction: a collaboration filed under the person.

    *The Assassination Of Jesse James* is credited on Discogs to `Nick Cave &
    Warren Ellis`; the rip says `Nick Cave`. The Discogs search returned no
    candidates at all — not a poor match, nothing — because every tier was
    looking at the solo catalogue.
    """

    def _names(self, limit=6):
        s = _searcher(limit)
        st = _state(artist='Nick Cave', data=NICK_CAVE_PERSON)
        return s.artist_alternate_names(st)

    def test_groups_are_offered(self):
        self.assertIn('Nick Cave & Warren Ellis', self._names())

    def test_a_group_is_reached_within_the_default_budget(self):
        """Draining namevariations first would spend it all on initialisms."""
        self.assertIn('Nick Cave & The Bad Seeds', self._names()[:6])

    def test_every_source_gets_a_turn_before_any_repeats(self):
        first_four = self._names()[:4]
        self.assertEqual(len(set(first_four)), 4)
        self.assertTrue(any(n.startswith('Nick Cave &') for n in first_four),
                        'a group must appear in the first round')

    def test_both_directions_are_covered(self):
        from massmusictagger.sources.discogs.search import DiscogsSearch
        self.assertIn('groups', DiscogsSearch._NAME_SOURCES)
        self.assertIn('members', DiscogsSearch._NAME_SOURCES)


class RelevanceOrderTest(unittest.TestCase):
    """List order is not relevance.

    Nick Cave's groups list runs ten deep and `Nick Cave & Warren Ellis` is
    ninth, so a budget of six spent in list order went on `Cave`, `Cave N`,
    `Her Dead Twin` and `The Birthday Party` — and never reached the credit
    that actually holds *The Assassination Of Jesse James*. Confirmed by
    replaying the album against 3.16.0, which still returned no candidates.
    """

    FULL = {
        'namevariations': ['Cave', 'Cave N', 'Nicholas Cave', 'N. Cave'],
        'aliases': [{'name': 'A Drunk Cowboy Junkie'}, {'name': 'Her Dead Twin'}],
        'groups': [{'name': 'Nick Cave & The Bad Seeds'},
                   {'name': 'The Birthday Party'},
                   {'name': 'The Boys Next Door'},
                   {'name': 'Grinderman'},
                   {'name': 'Nick Cave & The Cavemen'},
                   {'name': 'The Tuff Monks'},
                   {'name': 'Nick Cave & Warren Ellis'}],
    }

    def _names(self):
        return _searcher().artist_alternate_names(
            _state(artist='Nick Cave', data=self.FULL))

    def test_the_credit_that_holds_the_album_is_within_budget(self):
        self.assertIn('Nick Cave & Warren Ellis', self._names()[:6])

    def test_every_shared_credit_fits_in_the_budget(self):
        """All three "Nick Cave & X" groups, plus the short variation."""
        first_six = self._names()[:6]
        for name in ('Nick Cave & The Bad Seeds', 'Nick Cave & The Cavemen',
                     'Nick Cave & Warren Ellis'):
            self.assertIn(name, first_six)

    def test_unrelated_names_rank_below_shared_ones(self):
        """A fellow band member has nothing to do with this album."""
        names = self._names()
        self.assertLess(names.index('Nick Cave & Warren Ellis'),
                        names.index('Her Dead Twin'))
        self.assertLess(names.index('Nick Cave & The Cavemen'),
                        names.index('The Birthday Party'))

    def test_a_shorter_variation_is_still_kept(self):
        """"Cave" shares the credit; it is not junk to be ranked away."""
        names = self._names()
        self.assertLess(names.index('Cave'), names.index('Her Dead Twin'))
