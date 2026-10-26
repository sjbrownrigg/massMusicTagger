"""The log should say what the format-codes file actually did.

A commented-out format_codes.yaml -- the template --new-config writes -- reads
as an empty mapping. The loader then merged nothing and logged

    Format codes: /config/format_codes.yaml merged over the bundled table

which implies overrides are in effect when none are. It also read differently
from char_substitutions in exactly the same situation, so a user comparing the
two could not tell whether either file was doing anything.
"""

import os
import shutil
import tempfile
import unittest

from massmusictagger.core.naming import formatcodes


class MessageTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _file(self, body):
        p = os.path.join(self.tmp, 'format_codes.yaml')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(body)
        return p

    def _load(self, path):
        with self.assertLogs('massmusictagger.core.naming.formatcodes', 'INFO') as cm:
            table = formatcodes.load_format_codes(path)
        return table, ' '.join(cm.output)

    def test_a_commented_template_says_it_defines_nothing(self):
        table, log = self._load(self._file('# all commented\n# base_formats:\n'))
        self.assertIn('defines nothing', log)
        self.assertNotIn('merged over', log, 'nothing was merged')

    def test_it_still_uses_the_bundled_table(self):
        table, _ = self._load(self._file('# nothing\n'))
        bundled = formatcodes.load_format_codes(None)
        self.assertEqual(table, bundled)

    def test_a_real_override_says_how_much_it_overrode(self):
        _, log = self._load(self._file('base_formats:\n  Vinyl: VINYL\n'))
        self.assertIn('merged over', log)
        self.assertIn('1 section overridden', log)


if __name__ == '__main__':
    unittest.main()
