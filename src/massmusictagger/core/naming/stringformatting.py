# -*- coding: utf-8 -*-
import logging
import re, os

logger = logging.getLogger(__name__)

# Alias built-ins before the class defines methods with the same names.
builtins_any = any
builtins_all = all


def _literal_list(raw):
    """Parse a Python-literal list without executing it, or None.

    This was eval(). $inarray and $flatten fall back to it whenever the value
    is not valid JSON, and the value is metadata -- so pointing $inarray at an
    album title, which is a reasonable thing for a format string to do, ran
    that title as Python. A title of

        __import__('sys').modules.setdefault('PWNED', 1) or []

    imported sys. Discogs titles are editable by anyone with an account.

    ast.literal_eval understands the same literals and cannot call anything.
    """
    import ast
    text = re.sub(r'\\', '', str(raw))
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, list) else None


class StringFormatting(object):
    """ The goal here is to have one formatting string that can cope with any
        type of release.  We don't want different strings for Various Artists,
        or multidisc releases, where each disc has a separate title.

        One string to rule them all.

        Some string formatting functions. Loosely based on:
        http://wiki.hydrogenaud.io/index.php?title=Foobar2000:Title_Formatting_Reference

        Limitations:
            don't leave empty conditions (or potentiall empty), blank
            placeholders.

            $if1($strcmp('%artist%','%albumartist%'),'','%artist% - ') -- good
            $if1($strcmp(%artist%,%albumartist%),,%artist% - ) -- bad

        Example:
        stringFormatting = StringFormatting()
        stringFormatting.test()

        string = "%albumartist%/[%year%] %album%/$num(%track%,2) $if1($strcmp('%artist%','%albumartist%'),'','%artist% - ')%title%%fileext%"
        new_string = stringFormatting.parseString(string)

        See tests for more examples
    """

    def __init__(self):
        self.functions = {
            # ── Conditionals ──────────────────────────────────────────────────
            '$if1':      3,  # $if1(cond, then, else='')
            '$if2':      2,  # $if2(x, fallback)   — x if non-empty, else fallback
            '$if3':      0,  # $if3(a, b, c, …)    — first non-empty value
            '$ifequal':  4,  # $ifequal(n1, n2, a, b)
            '$ifgreater':4,  # $ifgreater(n1, n2, a, b)
            '$ifeq':     0,  # $ifeq(a, b, then, else='')  — string equality branch
            '$ieq':      0,  # $ieq(a, b, then, else='')   — case-insensitive $ifeq
            '$switch':   0,  # $switch(val, k1,v1, …, default='') — lookup table
            '$iswitch':  0,  # $iswitch(…) — case-insensitive $switch
            # ── Boolean ───────────────────────────────────────────────────────
            '$any':      0,  # $any(c1, c2, …)  — True if any arg is truthy
            '$all':      0,  # $all(c1, c2, …)  — True if all args are truthy
            '$neg':      1,  # $neg(cond)        — invert truthiness
            '$valid':    1,  # $valid(val)       — True when val is non-empty/non-None
            # ── String functions ──────────────────────────────────────────────
            '$inarray':  3,
            '$flatten':  0,  # $flatten(array, slice=':', join=', ') — slice+join a JSON array
            '$lower':    2,
            '$upper':    2,
            '$num':      2,
            '$contains':  2,  # $contains(text, substring)    — case-sensitive substring test
            '$icontains': 2,  # $icontains(text, substring)   — case-insensitive substring test
            '$strchr':   2,
            '$strcmp':   2,
            '$stricmp':  2,
            '$substr':   3,
            '$wrap':     0,  # $wrap(val, before, after='') — surround if non-empty
        }

    def if1(self, cond, string1, string2=''):
        """Explicit conditional: return string1 if cond is truthy, else string2."""
        return str(string1) if cond else str(string2)

    def if2(self, x, fallback=''):
        """Null-coalescing: return x if x is non-empty/non-None, else fallback.

        Unlike $if1, $if2 uses the value itself as the condition, so you only
        need to write it once:
            $if2('%catno%','no-cat')
        is equivalent to:
            $if1($strcmp('%catno%',''),'%catno%','no-cat')
        """
        val = str(x) if x is not None else ''
        return val if val and val != 'None' else str(fallback)

    def if3(self, *args):
        """Return the first non-empty, non-None value from the argument list.

        Useful as a priority chain of fallbacks:
            $if3('%albumartist%','%artist%','Unknown')
        """
        for arg in args:
            val = str(arg) if arg is not None else ''
            if val and val != 'None':
                return val
        return ''

    def ifequal(self, int1, int2, oui, non):
        int1 = 0 if int1 is None or int1 == '' else int(int1)
        int2 = 0 if int2 is None or int2 == '' else int(int2)
        result = oui if int1 == int2 else non
        return result

    def ifgreater(self, int1, int2, oui, non):
        # for convenience if int1 or int2 are None make 0
        int1 = 0 if int1 is None or int1 == '' else int(int1)
        int2 = 0 if int2 is None or int2 == '' else int(int2)
        result = oui if int1 > int2 else non
        return result

    def flatten(self, arr, slice_=':', join=', '):
        """Slice a JSON array and join the elements into a string.

        $flatten(array, slice=':', join=', ')

        array  — a JSON array string from a variable like %catnos% or
                 %format_description%.  Both sources produce catnumbers
                 as a list, exposed as JSON via %catnos%.
        slice  — Python slice or index notation (as a string):
                   ':'      all elements (default)
                   '0'      first element only
                   '-1'     last element only
                   ':2'     first two elements
                   '1:'     all except the first
                   '0:3:2'  every other element from 0 to 2
        join   — separator between elements when more than one is returned
                 (default: ', ')

        Examples:
            $flatten('%catnos%','0')        → 'MUTE 066'
            $flatten('%catnos%',':2',' / ') → 'MUTE 066 / MUTE-066'
            $flatten('%catnos%',':',', ')   → 'MUTE 066, MUTE-066, P-66'
            $flatten('%format_description%','-1') → last format description
        """
        import json as _json
        # Parse the JSON array (same fallback as $inarray)
        raw = str(arr) if arr is not None else '[]'
        try:
            lst = _json.loads(raw)
        except (ValueError, TypeError):
            lst = _literal_list(raw)
            if lst is None:
                return ''
        if not isinstance(lst, list) or not lst:
            return ''

        slice_s = str(slice_).strip()

        if ':' not in slice_s:
            # Single index: '0', '-1', '2', …
            try:
                return str(lst[int(slice_s)])
            except (ValueError, IndexError):
                return ''

        # Slice notation: 'start:stop' or 'start:stop:step'
        parts = slice_s.split(':')
        def _i(s):
            s = s.strip()
            return int(s) if s else None
        start = _i(parts[0])
        stop  = _i(parts[1]) if len(parts) > 1 else None
        step  = _i(parts[2]) if len(parts) > 2 else None
        return str(join).join(str(x) for x in lst[start:stop:step])

    def inarray(self, l, i):
        """Return True if item i is in the list l.

        l is a JSON-encoded list string that arrives after Python's eval has
        processed escape sequences in execute().  The caller doubles backslashes
        before substitution so that JSON escapes (\\u2153 → \\u2153, \\" → \\")
        survive as valid JSON by the time they reach here.
        """
        import json as _json
        itm = '' if i == 'None' else str(i)
        try:
            lst = _json.loads(l)
        except (ValueError, TypeError):
            # Fallback for non-JSON lists, e.g. a simple ['a','b'].
            lst = _literal_list(l) or []
        return itm in [str(x) for x in lst]

    def lower(self, string):
        ''' Make string lowercase
        '''
        return str(string).lower()

    def num(self, num, places):
        val = str(num)
        # Non-numeric values (vinyl positions like 'A', 'A1', 'B3') are returned
        # as-is — zero-padding only makes sense for bare track numbers.
        if val and not val[0].isdigit():
            return val
        string = '{:0>%%}'
        string = re.sub(r'\%\%', str(places), string)
        string = string.format(val)
        return string

    def strchr(self, string, char):
        "Returns position of first occurrence of character char(s) in string str."
        string = '' if string == 'None' else str(string)
        char = '' if char == 'None' else str(char)
        return string.find(char)

    def contains(self, text, substring):
        """Return True if text contains substring (case-sensitive).

            $contains('%format%','Vinyl')   → True for 'Vinyl', '12\" Vinyl'
            $contains('%album%','(Remix)')  → True when title includes '(Remix)'

        Use $icontains() for case-insensitive matching.
        """
        text = '' if text is None else str(text)
        substring = '' if substring is None else str(substring)
        return substring in text

    def icontains(self, text, substring):
        """Return True if text contains substring (case-insensitive).

            $icontains('%format%','vinyl')       → True for 'Vinyl', '12\" Vinyl'
            $icontains('%releasetype%','live')   → True for 'Live', 'Live Concert'
        """
        text = '' if text is None else str(text)
        substring = '' if substring is None else str(substring)
        return substring.lower() in text.lower()

    def strcmp(self, string1, string2):
        string1 = '' if string1 == 'None' else str(string1)
        string2 = '' if string2 == 'None' else str(string2)
        result = string1 == string2
        return result

    def stricmp(self, string1, string2):
        string1 = '' if string1 == 'None' else str(string1)
        string2 = '' if string2 == 'None' else str(string2)
        result = string1.lower() == string2.lower()
        return result

    @staticmethod
    def _truthy(val) -> bool:
        """Format-string truthiness: False/None/empty-string/the-string-'None' are falsy."""
        if val is None or val is False:
            return False
        s = str(val)
        return bool(s) and s != 'None'

    def any(self, *args):
        """True if at least one argument is truthy.

        Use inside $if1() to express OR conditions over many tests:
            $if1($any($strcmp('%x%','a'),$strcmp('%x%','b')),'matched','')
        """
        return builtins_any(self._truthy(a) for a in args)

    def all(self, *args):
        """True if every argument is truthy.

        Use inside $if1() to express AND conditions over many tests:
            $if1($all($inarray('%fd%','Limited Edition'),$strcmp('%status%','Promo')),'LP','')
        """
        return builtins_all(self._truthy(a) for a in args)

    def neg(self, cond):
        """Invert a boolean condition.

        Useful to negate any function that returns a bool:
            $if1($neg($strcmp('%releasetype%','Album')),'%releasetype%','')
        """
        return not self._truthy(cond)

    def substr(self, string, start, finish):
        string = '' if string is None else string
        start = None if start == '' else int(start)
        finish = None if finish == '' else int(finish)
        s = string[start:finish]
        return s

    def upper(self, string):
        ''' Make string uppercase
        '''
        return str(string).upper()

    def ifeq(self, a, b, then, else_=''):
        """String equality branch — replaces $if1($strcmp(a,b),then,else).

        Returns then when a == b (exact), else else_ (default '').
        Cleaner than $if1($strcmp(...)) for every string comparison branch:
            $ifeq('%channels%','stereo','s','%channels%')
        """
        a = '' if a is None else str(a)
        b = '' if b is None else str(b)
        return str(then) if a == b else str(else_)

    def ieq(self, a, b, then, else_=''):
        """Case-insensitive equality branch — replaces $if1($stricmp(a,b),then,else).

        Returns then when a == b (ignoring case), else else_ (default '').
            $ieq('%format%','vinyl','Disk','CD')
        """
        a = '' if a is None else str(a).lower()
        b = '' if b is None else str(b).lower()
        return str(then) if a == b else str(else_)

    def switch(self, val, *args):
        """String lookup table — replaces deeply-nested $ifeq chains.

        $switch(val, k1,v1, k2,v2, …, default='')

        Args are key-value pairs.  An odd trailing argument is the default.
        Returns the value paired with the first matching key, or the default.

            $switch('%releasetype%','Single','S','Maxi-Single','M','EP','EP','Album','','%releasetype%')
            $switch('%disctotal%','1','','2','D','%disctotal%x')
        """
        val_s = '' if val is None else str(val)
        if len(args) % 2 == 1:
            pairs, default = args[:-1], str(args[-1])
        else:
            pairs, default = args, ''
        it = iter(pairs)
        for key in it:
            value = next(it)
            if str(key) == val_s:
                return str(value)
        return default

    def iswitch(self, val, *args):
        """Case-insensitive lookup table — like $switch but ignores case.

            $iswitch('%status%','bootleg','.B','promo','.P','')
        """
        val_s = ('' if val is None else str(val)).lower()
        if len(args) % 2 == 1:
            pairs, default = args[:-1], str(args[-1])
        else:
            pairs, default = args, ''
        it = iter(pairs)
        for key in it:
            value = next(it)
            if str(key).lower() == val_s:
                return str(value)
        return default

    def valid(self, val):
        r"""Return True when val is non-empty and non-None — a boolean validity test.

        Useful for composing existence checks with $any/$all/$neg/$if1:
            $if1($valid('%edition%'),'has edition','')
            $if1($all($valid('%edition%'),$valid('%catno%')),'both set','')
            $wrap('%edition%',' \\(','\)')  — usually simpler for single checks

        Different from $if2 (which returns the value itself) — $valid returns
        a bool so it can be used anywhere a condition is expected.
        """
        return self._truthy(val)

    def wrap(self, val, before='', after=''):
        """Return before+val+after when val is non-empty/non-None, else ''.

        Replaces the verbose pattern used for optional separators and brackets:
            $if1($strcmp('%discsubtitle%',''),'',', %discsubtitle%')
            →  $wrap('%discsubtitle%',', ')

            $if1($strcmp('%edition%',''),'', ' \\(%edition%\\)')
            ->  $wrap('%edition%',' \\(','\\)')

        Arguments:
            val    — the value to test; empty/None → returns ''
            before — prefix prepended when val is non-empty  (default: '')
            after  — suffix appended  when val is non-empty  (default: '')
        """
        s = str(val) if val is not None else ''
        return (str(before) + s + str(after)) if self._truthy(s) else ''

    def parseString(self, string):
        """Evaluate a format string.

        The dialect is unchanged; how it is evaluated is not. This used to
        find a balanced $fn(...), rewrite $ to self., and eval() the result --
        so nesting worked because Python's parser did it, and every metadata
        value had to be neutralised before it could be spliced into that
        source. naming.formatparser parses the dialect directly.

        values maps a bare variable name to its value, resolved at evaluation
        time so it is never parsed. Callers that substitute %tokens% into the
        text beforehand pass nothing and keep the old behaviour, because an
        unresolved %name% evaluates to itself.
        """
        return self.render(string, values=None)

    def render(self, string, values=None):
        """Parse and evaluate, with variables resolved from *values*."""
        from massmusictagger.core.naming import formatparser
        try:
            return formatparser.render(string, self._function_table(), values)
        except formatparser.FormatSyntaxError as exc:
            logger.warning('Bad format string: %s', exc)
            return ''

    def _function_table(self):
        """Bare name -> bound method, built once per instance."""
        table = getattr(self, '_fn_table', None)
        if table is None:
            table = {name.lstrip('$'): getattr(self, name.lstrip('$'))
                     for name in self.functions}
            self._fn_table = table
        return table

    def test(self):
        track = {

            'formatted_string': "%albumartist%/[%year%] %album%$if1($strcmp('%totaldiscs%',''),'',$ifgreater('%totaldiscs%', 1,'/CD %discnumber%',''))$if1($strcmp('%disctitle%',''),'',', %disctitle%')/$num('%track%','2') $if1($strcmp('%artist%','%albumartist%'),'','%artist% - ')%title%%fileext%",
            'test': 'Advance/[2014] Deus Ex Machina/09 When we return.flac',
            '%artist%': 'Advance',
            '%albumartist%': 'Advance',
            '%year%': '2014',
            '%album%': 'Deus Ex Machina',
            '%title%': 'When we return',
            '%track%': '9',
            '%fileext%': '.flac',
        }

        multidisctrack = {
            'formatted_string': "%albumartist%/[%year%] %album%$if1($strcmp('%totaldiscs%',''),'',$ifgreater('%totaldiscs%', 1,'/CD %discnumber%',''))$if1($strcmp('%disctitle%',''),'',', %disctitle%')/$num('%track%','2') $if1($strcmp('%artist%','%albumartist%'),'','%artist% - ')%title%%fileext%",
            'test': 'Advance/[2014] Deus Ex Machina/CD 2, Bonus tracks/09 When we return.flac',
            '%artist%': 'Advance',
            '%albumartist%': 'Advance',
            '%year%': '2014',
            '%album%': 'Deus Ex Machina',
            '%discnumber%': '2',
            '%totaldiscs%': '2',
            '%disctitle%': 'Bonus tracks',
            '%title%': 'When we return',
            '%track%': '9',
            '%fileext%': '.flac',
        }

        various = {
            'formatted_string': r"%albumartist%/[%year%] %album% \(%catnumber%\)$if1($strcmp('%totaldiscs%',''),'',$ifgreater('%totaldiscs%', 1,'/CD %discnumber%',''))$if1($strcmp('%disctitle%',''),'',', %disctitle%')/$num('%track%','2') $if1($strcmp('%artist%','%albumartist%'),'','%artist% - ')%title%%fileext%",
            'test': 'Various Artists/[2016] Modern EBM/05 Advance - Dead technology.flac',
            '%artist%': 'Advance',
            '%albumartist%': 'Various Artists',
            '%year%': '2016',
            '%album%': 'Modern EBM',
            '%title%': 'Dead technology',
            '%track%': '5',
            '%fileext%': '.flac',
        }

        passMessage = 'Pass'
        failMessage = 'Fail'

        """Test 1: directly calling function"""
        result = self.num(8,4)
        test = '0008'
        output = 'Output should read: "{}": {}'.format(test, failMessage if result != test else passMessage)
        print(output)

        """Test 2: track from a single artist album"""
        result = stringFormatting.parseString(track['formatted_string'], track)
        output = 'Output should read "{}": {}'.format(track['test'], failMessage if result != track['test'] else passMessage)
        print(output)

        """Test 3: track from a various artist album"""
        result = stringFormatting.parseString(various['formatted_string'], various)
        output = 'Output should read "{}": {}'.format(various['test'], failMessage if result != various['test'] else passMessage)
        print(output)

        """Test 4: track from a multidisc album"""
        result = stringFormatting.parseString(multidisctrack['formatted_string'], multidisctrack)
        output = 'Output should read "{}": {}'.format(multidisctrack['test'], failMessage if result != multidisctrack['test'] else passMessage)
        print(output)

# stringFormatting = StringFormatting()
# stringFormatting.test()
