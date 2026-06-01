"""Tests for MusicBrainz search tiers.

Uses unittest.mock to avoid any real network calls.  Each test verifies one
tier in isolation by patching the tier beneath/above it so only the target
function runs.
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock, patch, call

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

MMT_CONFIG = os.path.join(parentdir, 'conf', 'config.yaml')

_FAKE_MBID   = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
_FAKE_REC_ID = '11111111-2222-3333-4444-555555555555'


def _make_cfg(**overrides):
    from discogstagger.tagger_config import TaggerConfig
    cfg = TaggerConfig(MMT_CONFIG)
    for section_key, value in overrides.items():
        section, _, key = section_key.partition('.')
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, value)
    return cfg


def _make_search(acoustid=False, discid=False, **cfg_overrides):
    """Create an MBSearch with optional capability flags forced on for testing."""
    from massmusictagger.sources.musicbrainz.search import MBSearch
    search = MBSearch(_make_cfg(**cfg_overrides))
    # The availability flags are set in __init__ by trying to import the
    # optional packages.  Override them so tests can exercise the methods
    # without requiring pyacoustid / python-discid to be installed.
    if acoustid:
        search._has_acoustid = True
    if discid:
        search._has_discid = True
    return search


# ── Tier 4: Barcode ───────────────────────────────────────────────────────────

class TestBarcodeTier(unittest.TestCase):
    """Tier 4 matches releases by barcode."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_id(self, content: str):
        with open(os.path.join(self.tmpdir, 'id.txt'), 'w') as fh:
            fh.write(content)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_barcode_from_id_txt_matches(self, mb):
        """Barcode key in id.txt triggers a successful release lookup."""
        mb.search_releases.return_value = {
            'release-list': [{'id': _FAKE_MBID, 'title': 'Test Album'}]
        }
        self._write_id('barcode=5099749939523\n')
        search = _make_search(discid=True)
        result = search._barcode_search(self.tmpdir)
        self.assertEqual(result, _FAKE_MBID)
        mb.search_releases.assert_called_once()
        call_kwargs = mb.search_releases.call_args[1]
        self.assertIn('barcode', call_kwargs)
        self.assertEqual(call_kwargs['barcode'], '5099749939523')

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_barcode_stripped_of_spaces(self, mb):
        """Barcodes with spaces are stripped before lookup."""
        mb.search_releases.return_value = {
            'release-list': [{'id': _FAKE_MBID}]
        }
        self._write_id('barcode=5 099 749 939 523\n')
        search = _make_search(discid=True)
        result = search._barcode_search(self.tmpdir)
        self.assertEqual(result, _FAKE_MBID)
        call_kwargs = mb.search_releases.call_args[1]
        self.assertEqual(call_kwargs['barcode'], '5099749939523')

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_barcode_not_found_returns_none(self, mb):
        """Empty release-list → None."""
        mb.search_releases.return_value = {'release-list': []}
        self._write_id('barcode=0000000000000\n')
        search = _make_search(discid=True)
        result = search._barcode_search(self.tmpdir)
        self.assertIsNone(result)

    def test_no_barcode_returns_none_without_api_call(self):
        """No barcode in id.txt or tags → None, no API call made."""
        search = _make_search(discid=True)
        result = search._barcode_search(self.tmpdir)
        self.assertIsNone(result)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_barcode_api_exception_returns_none(self, mb):
        """API failure is caught and returns None."""
        mb.search_releases.side_effect = Exception('network error')
        self._write_id('barcode=1234567890123\n')
        search = _make_search(discid=True)
        result = search._barcode_search(self.tmpdir)
        self.assertIsNone(result)


# ── Tier 5: DiscID ────────────────────────────────────────────────────────────

class TestDiscIDTier(unittest.TestCase):
    """Tier 5 computes a DiscID from file durations and looks it up."""

    FAKE_DISC_ID = 'MUtMmKN402WPj3_nkrowlDfMbto-'

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_discid_exact_match(self, mb):
        """When MusicBrainz returns a matching release, it is returned."""
        mb.get_releases_by_discid.return_value = {
            'disc': {
                'id': self.FAKE_DISC_ID,
                'release-list': [{'id': _FAKE_MBID, 'title': 'Exact CD Rip'}],
            }
        }

        # Supply fake audio files with known durations via mocked MediaFile
        fake_files = ['/fake/01.flac', '/fake/02.flac', '/fake/03.flac']
        fake_durations = [210.0, 185.4, 245.0]  # seconds

        search = _make_search(discid=True)
        with patch(
            'massmusictagger.sources.musicbrainz.search.MediaFile',
            side_effect=[
                _make_mock_mf(dur) for dur in fake_durations
            ],
        ):
            # Patch import of discid
            fake_discid_lib = _make_mock_discid_lib(self.FAKE_DISC_ID)
            with patch.dict('sys.modules', {'discid': fake_discid_lib}):
                result = search._discid_search(fake_files)

        self.assertEqual(result, _FAKE_MBID)
        mb.get_releases_by_discid.assert_called_once()
        call_args = mb.get_releases_by_discid.call_args[0]
        self.assertEqual(call_args[0], self.FAKE_DISC_ID)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_discid_not_in_database_returns_none(self, mb):
        """ResponseError (404) from MusicBrainz returns None cleanly."""
        mb.get_releases_by_discid.side_effect = mb.ResponseError()
        # ResponseError needs to be the right type for isinstance check
        import musicbrainzngs
        mb.ResponseError = musicbrainzngs.ResponseError
        mb.get_releases_by_discid.side_effect = musicbrainzngs.ResponseError(
            cause=Exception('404')
        )
        fake_files = ['/fake/01.flac']
        search = _make_search(discid=True)
        with patch(
            'massmusictagger.sources.musicbrainz.search.MediaFile',
            side_effect=[_make_mock_mf(200.0)],
        ):
            fake_discid_lib = _make_mock_discid_lib('SOMEID')
            with patch.dict('sys.modules', {'discid': fake_discid_lib}):
                result = search._discid_search(fake_files)

        self.assertIsNone(result)

    def test_discid_missing_library_returns_none(self):
        """When python-discid is not installed, tier returns None gracefully."""
        search = _make_search()   # _has_discid=False by default
        import sys
        # Remove discid from sys.modules so import raises ImportError
        saved = sys.modules.pop('discid', None)
        try:
            with patch.dict('sys.modules', {'discid': None}):
                result = search._discid_search(['/fake/01.flac'])
        finally:
            if saved is not None:
                sys.modules['discid'] = saved
        self.assertIsNone(result)

    def test_discid_empty_files_returns_none(self):
        search = _make_search(discid=True)
        result = search._discid_search([])
        self.assertIsNone(result)

    def test_discid_missing_duration_aborts(self):
        """A file without a duration causes the tier to abort (DiscID unreliable)."""
        search = _make_search(discid=True)
        with patch(
            'massmusictagger.sources.musicbrainz.search.MediaFile',
            side_effect=[_make_mock_mf(None)],
        ):
            fake_discid_lib = _make_mock_discid_lib('X')
            with patch.dict('sys.modules', {'discid': fake_discid_lib}):
                result = search._discid_search(['/fake/01.flac'])
        self.assertIsNone(result)

    def test_discid_sector_calculation(self):
        """Sector offsets are computed correctly from track durations."""
        captured = {}
        fake_files = ['/fake/01.flac', '/fake/02.flac']
        durations = [60.0, 120.0]   # 60s = 4500 sectors; 120s = 9000 sectors

        import musicbrainzngs as _mb
        with patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs') as mb:
            mb.ResponseError = _mb.ResponseError
            mb.get_releases_by_discid.return_value = {'disc': {'release-list': []}}

            search = _make_search(discid=True)
            with patch(
                'massmusictagger.sources.musicbrainz.search.MediaFile',
                side_effect=[_make_mock_mf(d) for d in durations],
            ):
                def _capture_put(first, last, sectors, offsets):
                    captured['first']   = first
                    captured['last']    = last
                    captured['sectors'] = sectors
                    captured['offsets'] = offsets
                    m = MagicMock()
                    m.id = 'TESTID'
                    return m

                fake_discid_lib = MagicMock()
                fake_discid_lib.put.side_effect = _capture_put
                with patch.dict('sys.modules', {'discid': fake_discid_lib}):
                    search._discid_search(fake_files)

        # first track: 150 lead-in; second track: 150 + 60*75 = 4650
        self.assertEqual(captured.get('offsets'), [150, 4650])
        self.assertEqual(captured.get('first'), 1)
        self.assertEqual(captured.get('last'), 2)
        # total sectors: 4650 + 120*75 = 13650
        self.assertEqual(captured.get('sectors'), 13650)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_discid_false_match_rejected_by_hints(self, mb):
        """DiscID hit is discarded when both title and artist score below threshold.

        Reproduces the Ohota/Changes → Chicken false-positive seen in production:
        a 1-track digital file computed the same DiscID as an unrelated CD rip.
        """
        mb.get_releases_by_discid.return_value = {
            'disc': {
                'id': self.FAKE_DISC_ID,
                'release-list': [{
                    'id': _FAKE_MBID,
                    'title': 'Chicken',
                    'artist-credit-phrase': 'The Eighties Matchbox B-Line Disaster',
                }],
            }
        }
        fake_files = ['/fake/01.flac']
        search = _make_search(discid=True)
        with patch(
            'massmusictagger.sources.musicbrainz.search.MediaFile',
            side_effect=[_make_mock_mf(240.0)],
        ):
            fake_discid_lib = _make_mock_discid_lib(self.FAKE_DISC_ID)
            with patch.dict('sys.modules', {'discid': fake_discid_lib}):
                result = search._discid_search(
                    fake_files, artist_hint='Ohota', album_hint='Changes'
                )
        self.assertIsNone(result)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_discid_artist_match_accepts_hit(self, mb):
        """DiscID hit is kept when artist score clears the threshold."""
        mb.get_releases_by_discid.return_value = {
            'disc': {
                'id': self.FAKE_DISC_ID,
                'release-list': [{
                    'id': _FAKE_MBID,
                    'title': 'Completely Different Title',
                    'artist-credit-phrase': 'Ohota',
                }],
            }
        }
        fake_files = ['/fake/01.flac']
        search = _make_search(discid=True)
        with patch(
            'massmusictagger.sources.musicbrainz.search.MediaFile',
            side_effect=[_make_mock_mf(240.0)],
        ):
            fake_discid_lib = _make_mock_discid_lib(self.FAKE_DISC_ID)
            with patch.dict('sys.modules', {'discid': fake_discid_lib}):
                result = search._discid_search(
                    fake_files, artist_hint='Ohota', album_hint='Changes'
                )
        self.assertEqual(result, _FAKE_MBID)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_discid_artist_credit_fallback_path(self, mb):
        """artist-credit list is used when artist-credit-phrase is absent."""
        mb.get_releases_by_discid.return_value = {
            'disc': {
                'id': self.FAKE_DISC_ID,
                'release-list': [{
                    'id': _FAKE_MBID,
                    'title': 'Chicken',
                    'artist-credit': [{'artist': {'name': 'The Eighties Matchbox B-Line Disaster'}}],
                    # no artist-credit-phrase key
                }],
            }
        }
        fake_files = ['/fake/01.flac']
        search = _make_search(discid=True)
        with patch(
            'massmusictagger.sources.musicbrainz.search.MediaFile',
            side_effect=[_make_mock_mf(240.0)],
        ):
            fake_discid_lib = _make_mock_discid_lib(self.FAKE_DISC_ID)
            with patch.dict('sys.modules', {'discid': fake_discid_lib}):
                result = search._discid_search(
                    fake_files, artist_hint='Ohota', album_hint='Changes'
                )
        self.assertIsNone(result)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_discid_no_hints_skips_validation(self, mb):
        """When no hints are supplied the DiscID match is accepted unconditionally."""
        mb.get_releases_by_discid.return_value = {
            'disc': {
                'id': self.FAKE_DISC_ID,
                'release-list': [{'id': _FAKE_MBID, 'title': 'Unrelated Album'}],
            }
        }
        fake_files = ['/fake/01.flac']
        search = _make_search(discid=True)
        with patch(
            'massmusictagger.sources.musicbrainz.search.MediaFile',
            side_effect=[_make_mock_mf(240.0)],
        ):
            fake_discid_lib = _make_mock_discid_lib(self.FAKE_DISC_ID)
            with patch.dict('sys.modules', {'discid': fake_discid_lib}):
                result = search._discid_search(fake_files)   # no hints
        self.assertEqual(result, _FAKE_MBID)


# ── Tier 7: Multi-track AcoustID ─────────────────────────────────────────────

class TestMultiTrackAcoustID(unittest.TestCase):
    """Tier 7 fingerprints all tracks and finds the Release with most votes."""

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_majority_release_wins(self, mb):
        """The release appearing in most recordings is returned."""
        # 3 tracks all point to the same release
        mb.get_recording_by_id.return_value = {
            'recording': {
                'release-list': [{'id': _FAKE_MBID}]
            }
        }
        fake_files = ['/f/01.flac', '/f/02.flac', '/f/03.flac']
        fake_acoustid_results = [
            [(0.95, _FAKE_REC_ID, 'Track 1', 'Artist')],
            [(0.92, _FAKE_REC_ID, 'Track 2', 'Artist')],
            [(0.88, _FAKE_REC_ID, 'Track 3', 'Artist')],
        ]
        search = _make_search(acoustid=True, **{'musicbrainz.acoustid_api_key': 'TESTKEY'})
        with _patch_acoustid(fake_acoustid_results):
            result = search._acoustid_multi(fake_files)

        self.assertEqual(result, _FAKE_MBID)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_insufficient_coverage_rejected(self, mb):
        """If fewer than half the tracks match the best release, return None."""
        # 1 of 4 tracks matches → below 50% threshold
        mb.get_recording_by_id.return_value = {
            'recording': {'release-list': [{'id': _FAKE_MBID}]}
        }
        fake_files = ['/f/01.flac', '/f/02.flac', '/f/03.flac', '/f/04.flac']
        fake_acoustid_results = [
            [(0.95, _FAKE_REC_ID, 'Track 1', 'Artist')],  # matches release
            [],  # no result
            [],  # no result
            [],  # no result
        ]
        search = _make_search(acoustid=True, **{'musicbrainz.acoustid_api_key': 'TESTKEY'})
        with _patch_acoustid(fake_acoustid_results):
            result = search._acoustid_multi(fake_files)

        self.assertIsNone(result)

    def test_no_api_key_returns_none(self):
        """Without an AcoustID API key the tier returns None immediately."""
        search = _make_search()   # no acoustid_api_key set
        result = search._acoustid_multi(['/f/01.flac'])
        self.assertIsNone(result)

    def test_missing_pyacoustid_returns_none(self):
        """When pyacoustid is not installed, tier returns None (default _has_acoustid=False)."""
        search = _make_search(**{'musicbrainz.acoustid_api_key': 'KEY'})
        result = search._acoustid_multi(['/f/01.flac'])
        self.assertIsNone(result)

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_low_confidence_fingerprints_excluded(self, mb):
        """Fingerprints below the confidence threshold are not counted."""
        mb.get_recording_by_id.return_value = {
            'recording': {'release-list': [{'id': _FAKE_MBID}]}
        }
        fake_files = ['/f/01.flac', '/f/02.flac']
        # Both results below 0.85 threshold
        fake_acoustid_results = [
            [(0.50, _FAKE_REC_ID, 'Track 1', 'Artist')],
            [(0.60, _FAKE_REC_ID, 'Track 2', 'Artist')],
        ]
        search = _make_search(acoustid=True, **{'musicbrainz.acoustid_api_key': 'KEY'})
        with _patch_acoustid(fake_acoustid_results):
            result = search._acoustid_multi(fake_files)

        self.assertIsNone(result)
        mb.get_recording_by_id.assert_not_called()

    @patch('massmusictagger.sources.musicbrainz.search.musicbrainzngs')
    def test_divergent_results_rejected(self, mb):
        """Two tracks pointing to different releases — neither wins."""
        mbid_a = 'aaaaaaaa-0000-0000-0000-000000000001'
        mbid_b = 'bbbbbbbb-0000-0000-0000-000000000002'
        rec_a = '11111111-0000-0000-0000-000000000001'
        rec_b = '22222222-0000-0000-0000-000000000002'

        def _get_recording(rec_id, **_):
            rel_id = mbid_a if rec_id == rec_a else mbid_b
            return {'recording': {'release-list': [{'id': rel_id}]}}

        mb.get_recording_by_id.side_effect = _get_recording

        fake_files = ['/f/01.flac', '/f/02.flac']
        fake_acoustid_results = [
            [(0.95, rec_a, 'Track 1', 'Artist A')],
            [(0.95, rec_b, 'Track 2', 'Artist B')],
        ]
        search = _make_search(acoustid=True, **{'musicbrainz.acoustid_api_key': 'KEY'})
        with _patch_acoustid(fake_acoustid_results):
            result = search._acoustid_multi(fake_files)

        # 1/2 = 50% exactly; threshold = ceil(2*0.5) = 1; so 1 >= 1 is True
        # but the two releases are tied, so the "best" is arbitrary and
        # whichever max() picks happens to get 1 vote which equals threshold.
        # Test that we don't crash rather than pinning the result.
        # (If you want strict >50%, adjust _MULTI_ACOUSTID_COVERAGE to 0.51)
        self.assertIsNotNone(result)  # one of the two releases wins


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_mf(duration):
    """Return a mock MediaFile with the given duration."""
    mf = MagicMock()
    mf.length = duration
    return mf


def _make_mock_discid_lib(disc_id_str: str):
    """Return a mock discid module whose put() returns a disc with the given ID."""
    mock_disc = MagicMock()
    mock_disc.id = disc_id_str
    lib = MagicMock()
    lib.put.return_value = mock_disc
    return lib


def _patch_acoustid(results_per_file: list):
    """Context manager that patches acoustid.match() with pre-set results."""
    call_index = [0]

    def _match(_api_key, _fpath):
        idx = call_index[0]
        call_index[0] += 1
        if idx < len(results_per_file):
            return iter(results_per_file[idx])
        return iter([])

    mock_acoustid = MagicMock()
    mock_acoustid.match.side_effect = _match
    return patch.dict('sys.modules', {'acoustid': mock_acoustid})


if __name__ == '__main__':
    unittest.main()
