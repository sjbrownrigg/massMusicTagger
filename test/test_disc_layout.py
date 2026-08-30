"""Disc layout as a matching signal.

Matching compares the flat track total, so a single-disc release of seventeen
tracks scores exactly as well as the correct 13 + 4. The cost lands much
later, during tagging: the disc directory the chosen release does not have is
skipped, and then a per-disc count mismatch raises an error that never
mentions layout.

The releases below are the real Spirit candidates. Against a local 12 + 5:

    10023903  [17]     the release the batch actually chose
    10013737  [12, 5]  correct
    15363133  [12, 5]  correct
"""

import unittest

from massmusictagger.sources.discogs.utils import disc_distribution


class DistributionTest(unittest.TestCase):

    def test_local_multi_disc_positions(self):
        self.assertEqual(disc_distribution(['1-1', '1-2', '2-1']), (2, 1))

    def test_discogs_cd_prefixed_positions(self):
        self.assertEqual(
            disc_distribution(['CD1-1', 'CD1-2', 'CD2-1', 'CD2-2']), (2, 2))

    def test_flat_positions_are_one_disc(self):
        self.assertEqual(disc_distribution(['1', '2', '3']), (3,))

    def test_vinyl_sides_are_one_disc(self):
        """A1/A2/B1 is two sides of one record, not two discs."""
        self.assertEqual(disc_distribution(['A1', 'A2', 'B1']), (3,))

    def test_lettered_subtracks_do_not_create_discs(self):
        self.assertEqual(disc_distribution(['13a', '13b', '13c']), (3,))

    def test_delta_machine(self):
        positions = ([f'1-{i}' for i in range(1, 14)]
                     + [f'2-{i}' for i in range(1, 5)])
        self.assertEqual(disc_distribution(positions), (13, 4))

    def test_discs_are_ordered_by_number_not_appearance(self):
        self.assertEqual(disc_distribution(['2-1', '1-1', '1-2']), (2, 1))

    def test_empty_and_junk(self):
        self.assertEqual(disc_distribution([]), ())
        self.assertEqual(disc_distribution([None, '']), (2,))

    def test_a_wrong_layout_is_distinguishable_from_a_right_one(self):
        """The whole point: these must not compare equal."""
        local = disc_distribution([f'1-{i}' for i in range(1, 13)]
                                  + [f'2-{i}' for i in range(1, 6)])
        wrong = disc_distribution([str(i) for i in range(1, 18)])
        self.assertEqual(local, (12, 5))
        self.assertEqual(wrong, (17,))
        self.assertNotEqual(local, wrong)
        # Same flat total -- which is exactly why the count alone cannot tell
        # them apart.
        self.assertEqual(sum(local), sum(wrong))


class ScoringWiringTest(unittest.TestCase):
    """A helper nothing calls would pass its own tests and change nothing."""

    def test_the_scorer_consults_disc_layout(self):
        import inspect
        from massmusictagger.sources.discogs import search

        src = inspect.getsource(search._DiscogsSearch._candidate_score) \
            if hasattr(search, '_DiscogsSearch') else inspect.getsource(search)
        self.assertIn('disc_distribution', src)
        self.assertIn('cand_dist', src)

    def test_single_disc_albums_keep_the_older_nudge(self):
        """Only multi-disc locals use the distribution; don't regress the rest."""
        import inspect
        from massmusictagger.sources.discogs import search
        src = inspect.getsource(search)
        self.assertIn('len(local_dist) > 1', src)
        self.assertIn('local_disc_hint', src)



class BitDepthTest(unittest.TestCase):
    """A 24-bit source cannot be a CD rip; a 16-bit one rules nothing out.

    The same album matched both 'Codes (SBR331) [9xDM]' and
    'Codes (SBR331CD) [CD]' across two runs of a 24-bit/44.1 download. Only
    the first is possible.
    """

    def test_cd_media_are_listed(self):
        from massmusictagger.sources.discogs.search import _CD_ONLY_FMTS
        for fmt in ('cd', 'cdr', 'hdcd'):
            with self.subTest(fmt=fmt):
                self.assertIn(fmt, _CD_ONLY_FMTS)

    def test_hi_res_capable_media_are_not_listed(self):
        """SACD and DVD carry hi-res, so 24-bit does not rule them out."""
        from massmusictagger.sources.discogs.search import _CD_ONLY_FMTS
        for fmt in ('sacd', 'dvd', 'dvd-video', 'vinyl', 'file',
                    'digital media'):
            with self.subTest(fmt=fmt):
                self.assertNotIn(fmt, _CD_ONLY_FMTS)

    def test_the_rule_is_one_directional(self):
        """16-bit must not reject anything -- it may be a CD rip or a download."""
        import inspect
        from massmusictagger.sources.discogs import search
        src = inspect.getsource(search)
        self.assertIn('local_depth > 16', src)
        self.assertNotIn('local_depth == 16', src)

    def test_the_scan_records_bit_depth(self):
        import inspect
        from massmusictagger.sources.discogs import search
        src = inspect.getsource(search)
        self.assertIn("searchParams['bitdepth']", src)
        self.assertIn("getattr(metadata, 'bitdepth', None)", src)

if __name__ == '__main__':
    unittest.main()
