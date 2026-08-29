# -*- coding: utf-8 -*-
"""The format-string dialect, pinned exactly as it behaves today.

Format strings are the reason this project exists -- the foobar2000-style
$function() syntax is what discogstagger was forked to extend -- so any change
to how they are evaluated has to reproduce this file byte for byte. It exists
to make replacing the evaluator a verifiable change rather than a hopeful one.

test/fixtures/format_dialect_cases.txt   one format string per line
test/fixtures/format_dialect_golden.txt  what each renders to today

Regenerate deliberately, never casually:
    python -m test.regen_format_golden
"""

import os
import sys
import unittest

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
CASES = os.path.join(FIXTURES, 'format_dialect_cases.txt')
GOLDEN = os.path.join(FIXTURES, 'format_dialect_golden.txt')


def _cases():
    with open(CASES, encoding='utf-8') as fh:
        for line in fh:
            line = line.rstrip('\n')
            if line and not line.startswith('#'):
                yield line


def _render(fmt):
    from massmusictagger.core.naming.stringformatting import StringFormatting
    try:
        return repr(StringFormatting().parseString(fmt))
    except Exception as exc:
        return f'<{type(exc).__name__}: {exc}>'


def _golden():
    pairs, current = {}, None
    with open(GOLDEN, encoding='utf-8') as fh:
        for line in fh:
            line = line.rstrip('\n')
            if line.startswith('  -> '):
                pairs[current] = line[5:]
            elif line:
                current = line
    return pairs


class TheDialectIsUnchanged(unittest.TestCase):

    def test_every_case_renders_as_recorded(self):
        golden = _golden()
        for fmt in _cases():
            with self.subTest(fmt=fmt):
                self.assertIn(fmt, golden, 'case missing from the golden file')
                self.assertEqual(_render(fmt), golden[fmt])

    def test_the_golden_file_covers_every_case(self):
        missing = [f for f in _cases() if f not in _golden()]
        self.assertEqual(missing, [])

    def test_every_function_appears_in_the_corpus(self):
        """A function nothing exercises is one a rewrite could quietly break."""
        from massmusictagger.core.naming.stringformatting import StringFormatting
        corpus = '\n'.join(_cases())
        untested = sorted(fn for fn in StringFormatting().functions
                          if fn + '(' not in corpus)
        self.assertEqual(untested, [],
                         'these functions are not covered by the dialect corpus')


class KnownQuirks(unittest.TestCase):
    """Behaviour worth naming, so a rewrite decides about it rather than
    reproducing or dropping it by accident."""

    def _r(self, fmt):
        from massmusictagger.core.naming.stringformatting import StringFormatting
        return StringFormatting().parseString(fmt)

    def test_plus_concatenates_inside_an_argument_but_not_outside(self):
        """eval() gives Python's + inside arguments; nothing gives it outside.

        parseString extracts each $fn(...) and copies the text between calls
        through verbatim, so a top-level + lands in the filename. Inside an
        argument the whole expression goes through eval(), where + is Python's
        string concatenation. The same characters mean two different things
        depending on depth.
        """
        self.assertEqual(
            self._r("$upper('a')+' '+$upper('b')"), "A+' '+B")
        self.assertEqual(
            self._r("$if1('x',$upper('a')+' '+$upper('b'))"), 'A B')

    def test_a_trailing_backslash_in_a_value_raises(self):
        """Values are spliced into the eval'd source, and \\ is not escaped.

        _value_from_tag_format escapes ' and $ before substitution but not the
        backslash, so a title ending in one closes the Python string literal
        it was interpolated into. An album called "AC\\" cannot be tagged.
        """
        with self.assertRaises(SyntaxError):
            self._r("$upper('AC\\')")

    def test_an_unknown_function_returns_a_string_not_an_error(self):
        self.assertEqual(self._r("$nosuchfunction('a')"), 'unknown command')


if __name__ == '__main__':
    unittest.main()
