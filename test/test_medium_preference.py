"""Prefer the medium the rip could plausibly have come from.

Track counts and durations cannot separate a CD from the cassette issued
alongside it: the tracklists are identical, so the two score the same and
either can win. Observed doing exactly that --

  * Dig, Lazarus, Dig!!!  a 16/44.1 FLAC rip matched an Indonesian *Cassette*
  * Final Countdown       a `Cass` folder matched a CD
  * Ultra (MOVLP945)      a Music On Vinyl LP folder matched a CD with a
                          different catalogue number

A veto would be the wrong tool: Discogs miscatalogues mediums -- one entry in
this library is a "Cassette" carrying the CD catalogue number CDSTUMM277 -- so
a hard gate would make correct releases unmatchable. These are nudges, small
against a base score of 50, and they must never outweigh agreement on tracks
and durations.
"""

import unittest

from massmusictagger.sources.discogs.search import DiscogsSearch


def _adj(fmt, **params):
    s = DiscogsSearch.__new__(DiscogsSearch)
    params.setdefault('tracks', [])
    return s._medium_adjustment(fmt, params)


CD_SPEC = dict(bitdepth=16, samplerate=44100, codec='flac')
HI_RES = dict(bitdepth=24, samplerate=96000, codec='flac')


class CdSpecTest(unittest.TestCase):
    """16-bit/44.1kHz is CD spec, so a CD is the likeliest origin."""

    def test_a_cd_is_preferred(self):
        self.assertLess(_adj('cd', **CD_SPEC), 0)

    def test_a_cassette_is_penalised(self):
        self.assertGreater(_adj('cassette', **CD_SPEC), 0)

    def test_the_cd_beats_the_cassette(self):
        """The Dig, Lazarus, Dig case, as a ranking."""
        self.assertLess(_adj('cd', **CD_SPEC), _adj('cassette', **CD_SPEC))

    def test_vinyl_is_penalised_without_positive_evidence(self):
        """A needle drop at 16/44.1 is unusual; the Ultra case."""
        self.assertGreater(_adj('vinyl', **CD_SPEC), 0)

    def test_a_download_stays_plausible(self):
        """A lossless download is a normal way to hold a CD-spec album."""
        adj = _adj('file', **CD_SPEC)
        self.assertLess(adj, 0)
        self.assertGreater(adj, _adj('cd', **CD_SPEC), 'but a CD fits better')


class HiResTest(unittest.TestCase):
    """Above 16-bit or 48kHz did not come off a CD."""

    def test_a_download_is_preferred(self):
        self.assertLess(_adj('file', **HI_RES), 0)

    def test_vinyl_stays_plausible(self):
        """Needle drops are usually captured at high resolution."""
        self.assertLessEqual(_adj('vinyl', **HI_RES), 0)

    def test_a_cassette_is_still_unlikely(self):
        self.assertGreater(_adj('cassette', **HI_RES), 0)

    def test_88_2khz_counts_as_hi_res(self):
        self.assertLess(_adj('file', bitdepth=16, samplerate=88200, codec='flac'), 0)


class EvidenceTest(unittest.TestCase):

    def test_side_positions_are_fact_not_inference(self):
        """A1/B2 track numbers say vinyl outright; the audio cannot override it."""
        tracks = [{'real_tracknumber': 'A1'}, {'real_tracknumber': 'B2'}]
        self.assertLess(_adj('vinyl', tracks=tracks, **CD_SPEC), 0)
        self.assertEqual(_adj('cd', tracks=tracks, **CD_SPEC), 0.0)

    def test_a_declared_vinyl_medium_is_honoured(self):
        self.assertLess(_adj('vinyl', media='vinyl', **CD_SPEC), 0)

    def test_a_lossy_file_says_nothing(self):
        """An mp3 has been transcoded; its rate reveals nothing about origin."""
        self.assertEqual(_adj('cassette', bitdepth=16, samplerate=44100,
                              codec='mp3'), 0.0)
        self.assertEqual(_adj('cd', bitdepth=16, samplerate=44100,
                              codec='mp3'), 0.0)

    def test_no_evidence_means_no_adjustment(self):
        self.assertEqual(_adj('cassette'), 0.0)

    def test_an_unknown_medium_is_neutral(self):
        self.assertEqual(_adj('betamax', **CD_SPEC), 0.0)


class ProportionTest(unittest.TestCase):

    def test_the_nudge_cannot_outweigh_real_agreement(self):
        """Against a base of 50, every adjustment stays a tie-breaker."""
        worst = max(abs(v) for v in
                    list(DiscogsSearch._MEDIUM_CD_SPEC.values())
                    + list(DiscogsSearch._MEDIUM_HI_RES.values()))
        self.assertLess(worst, 5.0)


if __name__ == '__main__':
    unittest.main()
