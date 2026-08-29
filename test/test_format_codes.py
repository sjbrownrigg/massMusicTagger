# -*- coding: utf-8 -*-
"""The format-code table decides how a release is named, so it must be visible.

A release on Digital Media should be filed as DM. It was being filed as
"Digital Media" because the live configuration named
`format_codes: conf/format_codes.yaml`, a path that resolves to nothing --
and a missing file returned an empty rule table, at debug level, so every
abbreviation silently switched off and the raw Discogs name came through.

That is the third setting to fail this exact way, after char_substitutions
and source_hints_file.
"""

import os
import sys
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

from massmusictagger.core.naming.formatcodes import (          # noqa: E402
    load_format_codes, compute_format_code)


class ThePathThatDidNotResolve(unittest.TestCase):

    def test_a_missing_file_falls_back_to_the_bundled_table(self):
        rules = load_format_codes('/definitely/not/here/format_codes.yaml')
        self.assertEqual(compute_format_code('Digital Media', [], 1, rules), 'DM')

    def test_and_says_so(self):
        with self.assertLogs('massmusictagger.core.naming.formatcodes',
                             level='WARNING') as cm:
            load_format_codes('/definitely/not/here/format_codes.yaml')
        self.assertIn('does not exist', '\n'.join(cm.output))

    def test_the_bundled_table_abbreviates_the_digital_formats(self):
        rules = load_format_codes()
        for name in ('File', 'Web', 'Digital Media'):
            with self.subTest(name=name):
                self.assertEqual(compute_format_code(name, [], 1, rules), 'DM')

    def test_an_unknown_format_still_comes_through_raw(self):
        rules = load_format_codes()
        self.assertEqual(compute_format_code('Wax Cylinder', [], 1, rules),
                         'Wax Cylinder')


class AUserTableIsMergedNotSubstituted(unittest.TestCase):
    """Supplying one override must not discard the rest of the table.

    A file with only base_formats used to replace everything, taking
    vinyl_sizes and the quantity rules with it -- and an upgrade that added a
    section would never reach anyone who had overridden a single line.
    """

    def _table(self, body):
        import tempfile
        fh = tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False,
                                         encoding='utf-8')
        fh.write(body)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_an_override_replaces_only_that_entry(self):
        path = self._table('base_formats:\n  Digital Media: Digital\n')
        rules = load_format_codes(path)
        self.assertEqual(compute_format_code('Digital Media', [], 1, rules),
                         'Digital')

    def test_the_other_entries_survive(self):
        path = self._table('base_formats:\n  Digital Media: Digital\n')
        rules = load_format_codes(path)
        self.assertEqual(compute_format_code('CD', [], 1, rules), 'CD')
        self.assertEqual(compute_format_code('Cassette', [], 1, rules), 'MC')

    def test_the_other_sections_survive(self):
        """vinyl_sizes and the quantity rules are separate sections."""
        path = self._table('base_formats:\n  CD: KOMPAKT\n')
        rules = load_format_codes(path)
        self.assertIn('vinyl_sizes', rules)
        # 12" is the default LP; 7" and 10" are the overrides.
        self.assertEqual(compute_format_code('Vinyl', ['7"'], 1, rules), '7″')

    def test_an_empty_user_file_changes_nothing(self):
        path = self._table('')
        self.assertEqual(
            compute_format_code('Digital Media', [], 1, load_format_codes(path)),
            'DM')


class ItIsDiscoveredByName(unittest.TestCase):
    """format_codes.yaml beside config.yaml, like formats.ini."""

    def test_the_layout_knows_it(self):
        from massmusictagger import roots
        self.assertEqual(roots.LAYOUT['format_codes'], 'format_codes.yaml')

    def test_discover_finds_it(self):
        import tempfile
        from massmusictagger import roots
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(roots.discover(d, 'format_codes'))
            open(os.path.join(d, 'format_codes.yaml'), 'w').write('{}\n')
            self.assertEqual(roots.discover(d, 'format_codes'),
                             os.path.join(d, 'format_codes.yaml'))

    def test_the_path_key_is_deprecated(self):
        from massmusictagger import config_schema
        self.assertIn(('naming', 'format_codes'), config_schema.DEPRECATED)
        self.assertIn(('naming', 'format_codes'), config_schema.DEPRECATION_NOTES)


class AnEmptyDeprecatedKeyIsQuiet(unittest.TestCase):
    """The sample carries deprecated keys so a reader can see they exist."""

    def _load(self, body):
        import tempfile
        from massmusictagger.core.tagger_config import TaggerConfig
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'config.yaml')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(body)
        return TaggerConfig, path

    def test_empty_does_not_warn(self):
        TaggerConfig, path = self._load('naming:\n  format_codes: ""\n')
        with self.assertNoLogs('massmusictagger.config_schema', level='WARNING'):
            TaggerConfig(path)

    def test_a_value_does_warn(self):
        TaggerConfig, path = self._load('naming:\n  format_codes: rules.yaml\n')
        with self.assertLogs('massmusictagger.config_schema', level='WARNING') as cm:
            TaggerConfig(path)
        self.assertIn('format_codes', '\n'.join(cm.output))


if __name__ == '__main__':
    unittest.main()


class EveryRuleTableBehavesTheSameWay(unittest.TestCase):
    """format_codes, char_substitutions and source_hints are one pattern.

    All three decide how a release is named, all three used to be reached
    through a config key naming a conf/ path, and all three failed the same
    way when that path did not resolve -- quietly, with the feature off.
    """

    TABLES = ('format_codes', 'char_substitutions', 'source_hints')

    def test_all_are_discoverable_in_the_config_directory(self):
        from massmusictagger import roots
        for name in self.TABLES:
            with self.subTest(name=name):
                self.assertIn(name, roots.LAYOUT)

    def test_all_ship_a_packaged_default(self):
        from massmusictagger import roots
        for name in self.TABLES:
            with self.subTest(name=name):
                self.assertTrue(
                    os.path.exists(os.path.join(roots.BUNDLED_CONF,
                                                roots.LAYOUT[name])))

    def test_the_path_keys_are_all_deprecated(self):
        from massmusictagger import config_schema
        for key in (('naming', 'format_codes'),
                    ('naming', 'char_substitutions'),
                    ('source', 'source_hints_file')):
            with self.subTest(key=key):
                self.assertIn(key, config_schema.DEPRECATED)
                self.assertIn(key, config_schema.DEPRECATION_NOTES)

    def test_none_of_them_is_both_deprecated_and_defaulted(self):
        from massmusictagger import config_schema
        self.assertEqual(
            sorted(set(config_schema.DEFAULTS) & set(config_schema.DEPRECATED)),
            [])

    def test_conf_holds_only_samples_and_rule_tables(self):
        """Nothing else belongs in the package's conf/.

        logger_default.conf sat there unreferenced after logging.config_file
        was removed -- a file nothing read, in the directory people look at to
        find out what the defaults are.
        """
        from massmusictagger import roots
        allowed = set(roots.LAYOUT.values()) | {
            'config_sample.yaml', 'formats_sample.ini',
            'discogs_sample.yaml', 'musicbrainz_sample.yaml'}
        present = {f for f in os.listdir(roots.BUNDLED_CONF)
                   if not f.startswith('.')}
        self.assertEqual(present - allowed, set())
