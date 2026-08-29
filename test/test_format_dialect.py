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

    def test_a_value_is_never_parsed(self):
        """The reason the escaping could go.

        Values used to be spliced into Python source before eval(), so
        anything meaningful to Python had to be neutralised first: ' became
        \\x27 and $ became a private-use codepoint. The backslash never was,
        so an album called "AC\\" closed the string literal it had been
        interpolated into and raised SyntaxError -- it could not be tagged.

        Values are data now. None of these characters need escaping, which is
        just as well: escaping metadata reliably is the problem that keeps
        coming back.
        """
        from massmusictagger.core.naming.stringformatting import StringFormatting
        sf = StringFormatting()
        for album in ('Leaders + Followers', "Don't Stop", '$5 Shake',
                      'AC\\', 'Hits (Remastered)', 'Alpha, Beta',
                      "$upper('pwned')"):
            with self.subTest(album=album):
                self.assertEqual(
                    sf.render("$wrap('%album%','[',']')", {'album': album}),
                    f'[{album}]')

    def test_a_malformed_format_string_warns_rather_than_raising(self):
        """A format string is the user's; a bad one should not end the run."""
        self.assertEqual(self._r("$upper('unterminated"), '')

    def test_an_unknown_function_returns_a_string_not_an_error(self):
        self.assertEqual(self._r("$nosuchfunction('a')"), 'unknown command')


if __name__ == '__main__':
    unittest.main()


class MetadataIsNeverExecuted(unittest.TestCase):
    """$inarray and $flatten fell back to eval() on the value.

    Both parse a list, and both used json.loads first and eval() when that
    failed. The value is metadata, and pointing $inarray at an album title is
    a reasonable thing for a format string to do:

        $if1($inarray('%album%','Box Set'),'B','')

    so an album titled

        __import__('sys').modules.setdefault('PWNED', 1) or []

    imported sys during tagging. Discogs titles are editable by anyone with an
    account, and the release being tagged is chosen by matching against them.

    ast.literal_eval reads the same literals and cannot call anything.
    """

    def _sf(self):
        from massmusictagger.core.naming.stringformatting import StringFormatting
        return StringFormatting()

    def test_inarray_does_not_execute_its_argument(self):
        import sys
        marker = 'MMT_TEST_MARKER_INARRAY'
        sys.modules.pop(marker, None)
        self.addCleanup(sys.modules.pop, marker, None)
        probe = f"__import__('sys').modules.setdefault({marker!r}, 1) or []"
        self._sf().render("$if1($inarray('%album%','x'),'y','')", {'album': probe})
        self.assertNotIn(marker, sys.modules)

    def test_flatten_does_not_execute_its_argument(self):
        import sys
        marker = 'MMT_TEST_MARKER_FLATTEN'
        sys.modules.pop(marker, None)
        self.addCleanup(sys.modules.pop, marker, None)
        probe = f"__import__('sys').modules.setdefault({marker!r}, 1) or []"
        self._sf().render("$flatten('%catnos%','0','')", {'catnos': probe})
        self.assertNotIn(marker, sys.modules)

    def test_a_json_list_still_works(self):
        sf = self._sf()
        self.assertTrue(sf.inarray('["a","b"]', 'a'))
        self.assertFalse(sf.inarray('["a","b"]', 'z'))
        self.assertEqual(sf.flatten('["A","B","C"]', ':2', ' / '), 'A / B')

    def test_a_python_literal_list_still_works(self):
        """The fallback existed for these, and still handles them."""
        sf = self._sf()
        self.assertTrue(sf.inarray("['a','b']", 'a'))
        self.assertEqual(sf.flatten("['A','B','C']", ':2', ' / '), 'A / B')

    def test_something_that_is_not_a_list_is_not_a_list(self):
        sf = self._sf()
        self.assertFalse(sf.inarray('not a list', 'a'))
        self.assertEqual(sf.flatten('not a list', ':', ', '), '')
        self.assertEqual(sf.flatten('2 + 2', ':', ', '), '')

    def test_the_evaluator_has_no_eval_left(self):
        """Checked against the compiled code, not the source text.

        Grepping the source and skipping comments is fragile -- the word
        appears in several explanations of why it is gone. What a module
        actually calls is in its code objects.
        """
        from massmusictagger.core.naming import stringformatting, formatparser
        for mod in (stringformatting, formatparser):
            names, seen = set(), set()
            stack = [v for v in vars(mod).values()
                     if callable(v) and getattr(v, '__module__', '') == mod.__name__]
            while stack:
                obj = stack.pop()
                if isinstance(obj, type):
                    stack.extend(v for v in vars(obj).values() if callable(v))
                    continue
                code = getattr(obj, '__code__', None)
                if code is None or id(code) in seen:
                    continue
                seen.add(id(code))
                names |= set(code.co_names)
                stack.extend(c for c in code.co_consts if hasattr(c, 'co_names'))
            self.assertNotIn('eval', names,
                             mod.__name__ + ' still references eval')
