"""Tag from a release that matches in every way except its medium.

*Chapter Two: The Slender Blade* is a 24-bit/48kHz download whose only Discogs
entry is the CDr. Same nine tracks, same titles -- refused because a 24-bit file
cannot have come off a CDr, which is true and is why the gate exists. It leaves
an album that is catalogued, correctly identified and still unfilable.

The same allowance is already made for digital releases, where a File entry
listing 16/44.1 still tags a 24/96 copy. This extends it, behind three limits:
only once every source has failed, only for releases refused on medium alone,
and only with batch.cross_medium switched on. And the borrowing is recorded in
the files rather than hidden.
"""

import inspect
import unittest
from unittest.mock import MagicMock, patch

from massmusictagger import cascade
from massmusictagger.sources.discogs.search import DiscogsSearch, SearchState


class _Cfg:
    def __init__(self, on):
        self.on = on

    def getboolean(self, section, option):
        if (section, option) == ('batch', 'cross_medium'):
            return self.on
        raise KeyError(option)


def _ctx(on=True, rejected=('38407944',), search=None, conn=True):
    return cascade._Attempt(
        sourcedir='/incoming/Palindrones/Chapter Two', cfg=_Cfg(on),
        discogs_connector=MagicMock() if conn else None,
        discogs_local_connector=None,
        discogs_search=search or MagicMock(), mb_connector=None, mb_search=None,
        release_id_override=None, medium_rejected=list(rejected))


class GateTest(unittest.TestCase):

    def test_off_by_default(self):
        """A rule that files borrowed metadata is the owner's to switch on."""
        from massmusictagger.config_schema import DEFAULTS
        self.assertEqual(DEFAULTS[('batch', 'cross_medium')], 'False')

    def test_off_means_no_attempt(self):
        search = MagicMock()
        self.assertIsNone(cascade._try_cross_medium(_ctx(on=False, search=search)))
        search.cross_medium_match.assert_not_called()

    def test_nothing_refused_on_medium_means_no_attempt(self):
        search = MagicMock()
        self.assertIsNone(cascade._try_cross_medium(_ctx(rejected=(), search=search)))
        search.cross_medium_match.assert_not_called()

    def test_no_discogs_connector_means_no_attempt(self):
        self.assertIsNone(cascade._try_cross_medium(_ctx(conn=False)))


class OnlyTheMediumIsLiftedTest(unittest.TestCase):
    """Nothing about the matching is relaxed except the one thing that differs."""

    def test_the_pass_reruns_the_full_comparison(self):
        src = inspect.getsource(DiscogsSearch.cross_medium_match)
        self.assertIn("state.params['relax_medium'] = True", src)
        self.assertIn('self._siftReleases(', src,
                      'the same comparison every candidate gets')

    def test_the_medium_gate_honours_the_flag(self):
        src = inspect.getsource(DiscogsSearch._compareRelease)
        self.assertIn("searchParams.get('relax_medium')", src)

    def test_nothing_else_reads_the_flag(self):
        """If another gate started honouring it, this would stop being narrow."""
        src = inspect.getsource(DiscogsSearch._compareRelease)
        self.assertEqual(src.count('relax_medium'), 1)

    def test_only_medium_refusals_are_handed_on(self):
        src = inspect.getsource(DiscogsSearch.search)
        self.assertIn("r.get('kind') == 'medium'", src)


class OrderTest(unittest.TestCase):

    def test_it_runs_before_existing_tags(self):
        """A real release on another medium beats the files describing themselves."""
        src = inspect.getsource(cascade.search_and_map)
        self.assertLess(src.index("source == 'existing_tags'"),
                        src.index('resolve(source, ctx)'))

    def test_it_runs_after_every_source_otherwise(self):
        src = inspect.getsource(cascade.search_and_map)
        tail = src[src.index('for source in priority:'):]
        self.assertIn('return _try_cross_medium(ctx)', tail)


class ProvenanceTest(unittest.TestCase):
    """The borrowing is recorded in the files, not just in a log."""

    def test_the_tag_is_written(self):
        from massmusictagger.core import taggerutils
        src = inspect.getsource(taggerutils.TagHandler.tag_single_track)
        self.assertIn("_set('tagger_provenance'", src)

    def test_the_tag_is_registered(self):
        # Not hasattr: a MediaField descriptor raises when read off the class
        # with no file behind it, so hasattr is False for every field.
        from massmusictagger.core.mediafile import MediaFile
        self.assertIn('tagger_provenance', MediaFile.__dict__)

    def test_the_tag_survives_a_real_write(self):
        import os, shutil, tempfile
        from mutagen.flac import FLAC
        from massmusictagger.core.mediafile import MediaFile
        src = None
        for root, _, files in os.walk('/mnt/nas/sorted'):
            src = next((os.path.join(root, f) for f in files if f.endswith('.flac')), None)
            if src:
                break
        if not src:
            self.skipTest('no FLAC available to copy')
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        dst = os.path.join(tmp, 'x.flac')
        shutil.copy2(src, dst)
        note = 'Metadata from Discogs 38407944 (CDr); copy in hand is FLAC 24-bit/48kHz'
        mf = MediaFile(dst)
        mf.tagger_provenance = note
        mf.save()
        self.assertEqual(FLAC(dst)['tagger_provenance'][0], note)
        self.assertEqual(MediaFile(dst).tagger_provenance, note)

    def test_the_folder_names_the_medium_held(self):
        from massmusictagger.core import taggerutils
        src = inspect.getsource(taggerutils)
        self.assertIn("'File' if getattr(self.album, 'cross_medium', None)", src)

    def test_the_run_lists_them_separately(self):
        from massmusictagger import processor
        src = inspect.getsource(processor.MassProcessor._print_summary)
        self.assertIn('tagged from a different', src)

    def test_a_successful_pass_marks_the_album(self):
        search = MagicMock()
        search.cross_medium_match.return_value = ('38407944', 'CDr')
        album = MagicMock()
        mapper = MagicMock()
        mapper.map.return_value = album
        with patch.object(cascade, '_fetch_discogs_with_validation',
                          return_value=({'id': 38407944}, '38407944')), \
             patch.object(cascade, '_local_audio_count', return_value=9), \
             patch.object(cascade, '_copy_in_hand', return_value='FLAC 24-bit/48kHz'), \
             patch('massmusictagger.source_factory.make_discogs_mapper',
                   return_value=mapper):
            out = cascade._try_cross_medium(_ctx(search=search))
        self.assertIsNotNone(out)
        c = out[0].cross_medium
        self.assertEqual(c['medium'], 'CDr')
        self.assertIn('38407944', c['provenance'])
        self.assertIn('FLAC 24-bit/48kHz', c['provenance'])


if __name__ == '__main__':
    unittest.main()
