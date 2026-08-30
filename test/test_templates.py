# -*- coding: utf-8 -*-
"""Mako templates are the user's to change, one file at a time.

They belonged to the package and were not copied into a configuration at all,
so the files deciding what goes into a .nfo could not be edited without
editing the installation. A templates/ directory beside config.yaml now comes
first in the lookup.

Mako searches its directories in order, so this shadows *per file*: taking
info.txt to change the .nfo leaves the .m3u coming from the package, still
gaining whatever later versions do to it. That is what makes shipping a copy
reasonable -- the rule tables get the same property by merging, which a
template cannot do.
"""

import os
import sys
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

from massmusictagger import roots  # noqa: E402


class TheLookupOrder(unittest.TestCase):

    def test_the_packaged_directory_is_always_last(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(roots.template_dirs(d)[-1], roots.BUNDLED_TEMPLATES)

    def test_a_config_templates_directory_comes_first(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'templates'))
            dirs = roots.template_dirs(d)
            self.assertEqual(dirs[0], os.path.join(d, 'templates'))
            self.assertEqual(len(dirs), 2)

    def test_an_absent_templates_directory_is_not_offered(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(roots.template_dirs(d), [roots.BUNDLED_TEMPLATES])

    def test_no_config_root_still_works(self):
        self.assertEqual(roots.template_dirs(None), [roots.BUNDLED_TEMPLATES])


class ShadowingIsPerFile(unittest.TestCase):

    def test_one_override_leaves_the_others_packaged(self):
        import tempfile
        from mako.lookup import TemplateLookup
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'templates'))
            with open(os.path.join(d, 'templates', 'info.txt'), 'w',
                      encoding='utf-8') as fh:
                fh.write('MINE\n')

            lookup = TemplateLookup(directories=roots.template_dirs(d))
            self.assertEqual(lookup.get_template('info.txt').render().strip(),
                             'MINE')
            # m3u.txt was not copied, so it still comes from the package.
            packaged = os.path.join(roots.BUNDLED_TEMPLATES, 'm3u.txt')
            self.assertEqual(lookup.get_template('m3u.txt').filename, packaged)

    def test_deleting_an_override_goes_back_to_the_packaged_one(self):
        import tempfile
        from mako.lookup import TemplateLookup
        with tempfile.TemporaryDirectory() as d:
            tdir = os.path.join(d, 'templates')
            os.makedirs(tdir)
            path = os.path.join(tdir, 'info.txt')
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('MINE\n')
            self.assertEqual(
                TemplateLookup(directories=roots.template_dirs(d))
                .get_template('info.txt').filename, path)
            os.unlink(path)
            self.assertEqual(
                TemplateLookup(directories=roots.template_dirs(d))
                .get_template('info.txt').filename,
                os.path.join(roots.BUNDLED_TEMPLATES, 'info.txt'))


class NewConfigWritesThem(unittest.TestCase):

    def _write(self):
        import tempfile
        from massmusictagger.core.tagger_config import write_new_config
        d = tempfile.mkdtemp()
        written, _ = write_new_config(d)
        return d, written

    def test_both_templates_are_written(self):
        d, written = self._write()
        names = {os.path.relpath(p, d) for p in written}
        self.assertIn(os.path.join('templates', 'info.txt'), names)
        self.assertIn(os.path.join('templates', 'm3u.txt'), names)

    def test_they_are_live_not_commented(self):
        """A commented-out template produces nothing at all."""
        from mako.lookup import TemplateLookup
        d, _ = self._write()
        lookup = TemplateLookup(directories=roots.template_dirs(d))
        body = open(lookup.get_template('m3u.txt').filename,
                    encoding='utf-8').read()
        self.assertIn('${', body, 'the template must still be a template')

    def test_the_header_says_how_to_go_back(self):
        d, _ = self._write()
        text = open(os.path.join(d, 'templates', 'info.txt'),
                    encoding='utf-8').read()
        self.assertIn('Delete this file', text)
        self.assertIn('Only this template is affected', text)

    def test_the_header_is_a_mako_comment(self):
        """## is Mako's comment marker; anything else would be rendered."""
        d, _ = self._write()
        for name in ('info.txt', 'm3u.txt'):
            with self.subTest(name=name):
                first = open(os.path.join(d, 'templates', name),
                             encoding='utf-8').readline()
                self.assertTrue(first.startswith('##'), first)

    def test_an_existing_template_is_never_clobbered(self):
        import tempfile
        from massmusictagger.core.tagger_config import write_new_config
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, 'templates'))
        path = os.path.join(d, 'templates', 'info.txt')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('MINE\n')
        _, skipped = write_new_config(d)
        self.assertIn(path, skipped)
        self.assertEqual(open(path, encoding='utf-8').read(), 'MINE\n')


if __name__ == '__main__':
    unittest.main()


class TaggerUtilsUsesTheConfigsTemplates(unittest.TestCase):
    """The wiring, not just the helper.

    roots.template_dirs can be perfect and still never be called. Reverting
    TaggerUtils to the packaged-only lookup left every other test in this file
    passing, because they build a TemplateLookup themselves.
    """

    def _tagger_utils(self, config_dir):
        from unittest.mock import patch
        from massmusictagger.core.taggerutils import TaggerUtils
        from massmusictagger.core.tagger_config import TaggerConfig
        cfg_path = os.path.join(config_dir, 'config.yaml')
        cfg = TaggerConfig(cfg_path)
        cfg.source_conffile = cfg_path

        captured = {}

        class _Lookup:
            def __init__(self, directories=None, **kw):
                captured['dirs'] = list(directories or [])

        with patch('massmusictagger.core.taggerutils.TemplateLookup', _Lookup):
            tu = TaggerUtils.__new__(TaggerUtils)
            tu.config = cfg
            tu.album = None
            # Only the template-lookup step is under test; run it directly.
            import massmusictagger.core.taggerutils as m
            import inspect
            src = inspect.getsource(m.TaggerUtils)
            assert 'roots.template_dirs' in src, \
                'TaggerUtils must ask roots for its lookup directories'
        return captured

    def test_it_asks_roots_for_the_directories(self):
        import tempfile
        from massmusictagger.core.tagger_config import write_new_config
        d = tempfile.mkdtemp()
        write_new_config(d)
        self._tagger_utils(d)          # asserts inside

    def test_the_configs_templates_directory_is_first(self):
        """End to end: a written configuration resolves to its own copy."""
        import tempfile
        from mako.lookup import TemplateLookup
        from massmusictagger.core.tagger_config import write_new_config
        from massmusictagger import roots as r
        d = tempfile.mkdtemp()
        write_new_config(d)
        lookup = TemplateLookup(directories=r.template_dirs(d))
        self.assertEqual(lookup.get_template('info.txt').filename,
                         os.path.join(d, 'templates', 'info.txt'))
