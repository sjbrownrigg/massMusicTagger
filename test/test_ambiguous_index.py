# -*- coding: utf-8 -*-
"""Index entries that read equally as one file or several.

Discogs marks a group of sub-tracks with type='index'. Two shapes are
unambiguous:

    A  no parent duration, every sub_track timed   → separate files
    B  a parent duration, no sub_track timed       → one file, movements

Anything else is genuinely ambiguous, and across 23,102 cached releases those
are 12% of index entries (85 of 711). Nothing in the Discogs data settles
them: the parent position is empty for *every* index entry, so it cannot be
used as a signal, and where both durations exist the sub-tracks usually sum
to the parent exactly -- which is equally true of one file or several.

So nothing guesses. The collapsed reading stays the default, and the number
of files on disk chooses when it disagrees.
"""

import os
import sys
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

from massmusictagger.sources.discogs.utils import (
    build_flat_tracklist, has_ambiguous_index, prefers_expanded_index)


def _cached_release(release_id):
    """Rehydrate a release from the on-disk Discogs cache, as the connector does."""
    import json
    for base in (os.path.expanduser('~/.cache/discogstagger3/releases'),
                 os.path.expanduser('~/.cache/massmusictagger/discogs/releases')):
        path = os.path.join(base, f'{release_id}.json')
        if os.path.exists(path):
            import discogs_client as discogs
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
            return discogs.Release(discogs.Client('massMusicTagger test'), data)
    return None


class _T:
    """A Discogs client track object, as far as these functions care."""
    def __init__(self, position='', title='', duration='', type_='track',
                 sub_tracks=None):
        self.position, self.title, self.duration = position, title, duration
        self.data = {'type_': type_, 'sub_tracks': sub_tracks or []}


def _sub(position, title, duration=''):
    return {'type_': 'track', 'position': position, 'title': title,
            'duration': duration}


# Real shapes from the cache.
#   release 3528     — parent 5:06, subs 1:42 + 3:24 (sums exactly)
AMBIGUOUS_BOTH = [
    _T('A1', 'Opener', '3:00'),
    _T('', 'Suite', '5:06', 'index',
       [_sub('10a', 'Section A', '1:42'), _sub('10b', 'Section B', '3:24')]),
]
#   release 7768803  — no duration anywhere
AMBIGUOUS_NEITHER = [
    _T('A1', 'Opener', '3:00'),
    _T('', 'Suite', '', 'index',
       [_sub('10a', 'Section A'), _sub('10b', 'Section B')]),
]
PATTERN_A = [
    _T('', 'Continuous Mix', '', 'index',
       [_sub('1', 'One', '3:00'), _sub('2', 'Two', '4:00')]),
]
PATTERN_B = [
    _T('', 'Mighty Mix', '9:00', 'index',
       [_sub('9a', 'Part 1'), _sub('9b', 'Part 2')]),
]


class WhatCountsAsAmbiguous(unittest.TestCase):

    def test_a_parent_duration_and_timed_subs_is_ambiguous(self):
        self.assertTrue(has_ambiguous_index(AMBIGUOUS_BOTH))

    def test_no_durations_anywhere_is_ambiguous(self):
        self.assertTrue(has_ambiguous_index(AMBIGUOUS_NEITHER))

    def test_pattern_a_is_not_ambiguous(self):
        self.assertFalse(has_ambiguous_index(PATTERN_A))

    def test_pattern_b_is_not_ambiguous(self):
        self.assertFalse(has_ambiguous_index(PATTERN_B))

    def test_a_release_with_no_index_entries_is_not_ambiguous(self):
        self.assertFalse(has_ambiguous_index([_T('A1', 'Song', '3:00')]))

    def test_an_index_with_no_sub_tracks_is_not_ambiguous(self):
        """A lightweight version object carries no sub_tracks at all."""
        self.assertFalse(has_ambiguous_index([_T('', 'Mix', '5:00', 'index')]))


class TheDefaultIsUnchanged(unittest.TestCase):
    """Collapsing is what has always happened; it stays the default."""

    def test_ambiguous_collapses_by_default(self):
        flat = build_flat_tracklist(AMBIGUOUS_BOTH)
        self.assertEqual(len(flat), 2)
        self.assertEqual(flat[1]['title'], 'Suite')

    def test_pattern_a_still_expands(self):
        self.assertEqual(len(build_flat_tracklist(PATTERN_A)), 2)

    def test_pattern_b_still_collapses(self):
        self.assertEqual(len(build_flat_tracklist(PATTERN_B)), 1)

    def test_expanding_does_not_disturb_the_unambiguous_patterns(self):
        self.assertEqual(
            build_flat_tracklist(PATTERN_A),
            build_flat_tracklist(PATTERN_A, expand_ambiguous_index=True))
        self.assertEqual(
            build_flat_tracklist(PATTERN_B),
            build_flat_tracklist(PATTERN_B, expand_ambiguous_index=True))


class TheOtherReading(unittest.TestCase):

    def test_expansion_yields_one_entry_per_sub_track(self):
        flat = build_flat_tracklist(AMBIGUOUS_BOTH, expand_ambiguous_index=True)
        self.assertEqual([t['title'] for t in flat],
                         ['Opener', 'Section A', 'Section B'])

    def test_expanded_entries_keep_their_positions(self):
        """All 85 ambiguous entries in the corpus carry sub-track positions.

        The collapsed entry uses the parent's position, which for an index
        entry is always empty -- so the expansion is the better-formed of the
        two whenever it is chosen.
        """
        flat = build_flat_tracklist(AMBIGUOUS_BOTH, expand_ambiguous_index=True)
        self.assertEqual([t['position'] for t in flat], ['A1', '10a', '10b'])

    def test_expanded_entries_keep_their_durations(self):
        flat = build_flat_tracklist(AMBIGUOUS_BOTH, expand_ambiguous_index=True)
        self.assertEqual([t['duration'] for t in flat],
                         ['3:00', '1:42', '3:24'])

    def test_untimed_sub_tracks_expand_with_no_duration(self):
        flat = build_flat_tracklist(AMBIGUOUS_NEITHER, expand_ambiguous_index=True)
        self.assertEqual([t['duration'] for t in flat], ['3:00', None, None])


class TheFileCountChooses(unittest.TestCase):

    def test_expanded_when_that_is_what_is_on_disk(self):
        self.assertTrue(prefers_expanded_index(AMBIGUOUS_BOTH, 3))

    def test_collapsed_when_that_is_what_is_on_disk(self):
        self.assertFalse(prefers_expanded_index(AMBIGUOUS_BOTH, 2))

    def test_neither_when_no_count_is_known(self):
        self.assertFalse(prefers_expanded_index(AMBIGUOUS_BOTH, None))

    def test_a_count_matching_neither_reading_changes_nothing(self):
        """No coincidence should overturn the default."""
        self.assertFalse(prefers_expanded_index(AMBIGUOUS_BOTH, 9))

    def test_the_default_is_never_overturned_when_it_already_fits(self):
        """Checked before the expansion is even built."""
        self.assertFalse(prefers_expanded_index(PATTERN_B, 1))

    def test_a_release_with_nothing_ambiguous_is_left_alone(self):
        self.assertFalse(prefers_expanded_index(PATTERN_A, 2))
        self.assertFalse(prefers_expanded_index(PATTERN_A, 1))


class SearchAndTaggerAgree(unittest.TestCase):
    """A release accepted under one reading must be tagged under the same one.

    The search scores a release on a flat track list; the mapper builds the
    Track objects separately, from its own copy of the pattern logic. If only
    one of them learned the second reading, a release would be accepted with
    N tracks and tagged with N-1.
    """

    def test_the_mapper_takes_the_same_decision(self):
        import inspect
        from massmusictagger import source_factory
        src = inspect.getsource(source_factory.make_discogs_mapper)
        self.assertIn('prefers_expanded_index', src)
        self.assertIn('expand_ambiguous_index=expand', src)

    def test_the_search_takes_the_same_decision(self):
        import inspect
        from massmusictagger.sources.discogs import search
        src = inspect.getsource(search)
        self.assertIn('prefers_expanded_index', src)

    def test_id_validation_takes_the_same_decision(self):
        import inspect
        from massmusictagger import cascade
        src = inspect.getsource(cascade._discogs_track_count)
        self.assertIn('prefers_expanded_index', src)

    def test_the_mapper_builds_the_expanded_tracks(self):
        """Through DiscogsAlbum.map(), on a real cached release.

        Release 3528 is one of the 85: a 5:06 parent whose two sub-tracks
        (1:42, 3:24) sum to it exactly.
        """
        release = _cached_release(3528)
        if release is None:
            self.skipTest('release 3528 is not in the local cache')

        from massmusictagger.sources.discogs.album import DiscogsAlbum
        collapsed = DiscogsAlbum(release).map()
        expanded = DiscogsAlbum(release, expand_ambiguous_index=True).map()

        n_collapsed = sum(len(d.tracks) for d in collapsed.discs)
        n_expanded = sum(len(d.tracks) for d in expanded.discs)
        self.assertEqual(n_expanded, n_collapsed + 1,
                         'the one ambiguous entry should become two tracks')

        titles = [t.title for d in expanded.discs for t in d.tracks]
        self.assertIn('Section A', titles)
        self.assertIn('Section B', titles)

        collapsed_titles = [t.title for d in collapsed.discs for t in d.tracks]
        self.assertNotIn('Section A', collapsed_titles)

    def test_every_expanded_track_gets_a_number(self):
        """The collapsed entry inherits the index entry's empty position."""
        release = _cached_release(3528)
        if release is None:
            self.skipTest('release 3528 is not in the local cache')
        from massmusictagger.sources.discogs.album import DiscogsAlbum
        album = DiscogsAlbum(release, expand_ambiguous_index=True).map()
        for disc in album.discs:
            for track in disc.tracks:
                self.assertTrue(track.tracknumber,
                                f'{track.title!r} has no track number')


if __name__ == '__main__':
    unittest.main()
