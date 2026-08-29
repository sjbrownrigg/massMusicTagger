# -*- coding: utf-8 -*-
"""A parser for the format-string dialect, replacing eval().

The dialect is foobar2000's title formatting: literal text with ``%variable%``
references and ``$function(...)`` calls that nest. It is the reason this
project exists, so this module's whole job is to evaluate it *identically* to
what came before, by a means that does not involve building Python source out
of user data.

How it used to work
-------------------
``StringFormatting.parseString`` scanned for a balanced ``$fn(...)``, rewrote
``$`` to ``self.``, and handed the result to ``eval()``. Nesting worked
because Python's parser did it. That was cheap and it worked, but it meant
metadata values were spliced into Python source, so every character that
means something to Python had to be neutralised on the way in:

  * ``'`` became the four characters ``\\x27``, undone after parsing.
  * ``$`` became U+E024, a private-use codepoint, undone after parsing.
  * ``\\`` was never handled at all, so an album called ``AC\\`` closed the
    string literal it had been interpolated into and raised SyntaxError.

Two contexts, which is the whole grammar
----------------------------------------
**Text** -- the top level, and the inside of a quoted string. Characters are
literal. ``$name(`` starts a call and ``%name%`` a variable; nothing else is
special. A ``+`` here is a plus sign, which is why ``Leaders + Followers``
needs no escaping.

**Expression** -- the inside of an argument list. Terms are quoted strings,
calls, variables and bare words; ``+`` concatenates them, as it did under
``eval``; ``,`` separates arguments. Write ``\\+`` for a literal plus.

That split is not a compromise, it is the same one foobar2000 makes, and it
is what the old evaluator did too -- a top-level ``+`` was copied through as
text because only argument contents ever reached ``eval``.

Values are data
---------------
``%variable%`` is resolved when the tree is evaluated, from a mapping the
caller supplies. A value is never parsed, so an apostrophe, a dollar sign, a
bracket or a backslash in an album title is simply a character. The three
escaping hacks above have nothing left to do.

For callers that still substitute values into the text before parsing, an
unresolved ``%name%`` evaluates to itself, exactly as it did before.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ['parse', 'evaluate', 'FormatSyntaxError',
           'Text', 'Variable', 'Call', 'Expression']


class FormatSyntaxError(ValueError):
    """A format string that cannot be parsed, with the offset that broke it."""

    def __init__(self, message: str, source: str, pos: int):
        self.source, self.pos = source, pos
        super().__init__(f'{message} at position {pos}: {source[:pos]}⟨here⟩'
                         f'{source[pos:]}')


# ── the tree ────────────────────────────────────────────────────────────────
# Deliberately dumb nodes. Everything interesting happens in evaluate().

class Text:
    __slots__ = ('value',)

    def __init__(self, value: str):
        self.value = value

    def __repr__(self):
        return f'Text({self.value!r})'

    def __eq__(self, other):
        return isinstance(other, Text) and other.value == self.value


class Variable:
    __slots__ = ('name',)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f'Variable({self.name!r})'

    def __eq__(self, other):
        return isinstance(other, Variable) and other.name == self.name


class Call:
    __slots__ = ('name', 'args')

    def __init__(self, name: str, args: list):
        self.name = name        # without the leading '$'
        self.args = args        # list[Expression]

    def __repr__(self):
        return f'Call({self.name!r}, {self.args!r})'

    def __eq__(self, other):
        return (isinstance(other, Call) and other.name == self.name
                and other.args == self.args)


class Expression:
    """A sequence of parts that concatenate.

    A single part keeps its Python value when evaluated -- a bool stays a
    bool. That matters: ``_truthy`` counts the *string* ``'False'`` as true,
    so stringifying ``$strcmp(...)`` before ``$neg`` receives it would invert
    the condition. Several parts are stringified and joined, because that is
    what concatenation means.
    """
    __slots__ = ('parts',)

    def __init__(self, parts: list):
        self.parts = parts

    def __repr__(self):
        return f'Expression({self.parts!r})'

    def __eq__(self, other):
        return isinstance(other, Expression) and other.parts == self.parts


# ── parsing ─────────────────────────────────────────────────────────────────

#: Recognised inside a quoted string and in expression context. Anything else
#: after a backslash is left alone, both characters intact -- which is how
#: \x27 survives to be turned back into an apostrophe by the caller that put
#: it there, and how a Windows path separator in a format string stays put.
_ESCAPES = {'(': '(', ')': ')', ',': ',', '$': '$', '%': '%',
            '+': '+', "'": "'", '\\': '\\'}

_NAME_CHARS = set('abcdefghijklmnopqrstuvwxyz'
                  'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')


class _Parser:

    def __init__(self, source: str):
        self.src = source
        self.i = 0

    # -- helpers ------------------------------------------------------------

    def _eof(self) -> bool:
        return self.i >= len(self.src)

    def _peek(self) -> str:
        return self.src[self.i] if self.i < len(self.src) else ''

    def _name_at(self, start: int) -> str:
        j = start
        while j < len(self.src) and self.src[j] in _NAME_CHARS:
            j += 1
        return self.src[start:j]

    # -- text context -------------------------------------------------------

    def parse_text(self, stop: str = '') -> Expression:
        """Literal text, with $calls and %variables% embedded in it."""
        parts, buf = [], []

        def flush():
            if buf:
                parts.append(Text(''.join(buf)))
                buf.clear()

        while not self._eof():
            c = self._peek()
            if c in stop:
                break
            if c == '$':
                call = self._try_call()
                if call is not None:
                    flush()
                    parts.append(call)
                    continue
                buf.append(c)
                self.i += 1
            elif c == '%':
                var = self._try_variable()
                if var is not None:
                    flush()
                    parts.append(var)
                    continue
                buf.append(c)
                self.i += 1
            else:
                # A backslash is literal here. parseString did the same: only
                # the contents of an argument ever reached eval, so an escape
                # written in the surrounding text was copied through and left
                # for get_clean_filename to strip.
                buf.append(c)
                self.i += 1

        flush()
        return Expression(parts)

    # -- expression context -------------------------------------------------

    def parse_expression(self) -> Expression:
        """One argument: terms joined by concatenation, ended by , or )"""
        parts = []

        while not self._eof():
            c = self._peek()
            if c in ',)':
                break
            if c in ' \t':
                self.i += 1          # whitespace between terms is not data
                continue
            if c == '+':
                self.i += 1          # an explicit join; adjacency joins too
                continue
            if c == '\\' and self.i + 1 < len(self.src) \
                    and self.src[self.i + 1] in _ESCAPES:
                parts.append(Text(_ESCAPES[self.src[self.i + 1]]))
                self.i += 2
                continue
            if c == "'":
                parts.append(self._quoted())
                continue
            if c == '$':
                call = self._try_call()
                if call is None:
                    raise FormatSyntaxError('malformed function call',
                                            self.src, self.i)
                parts.append(call)
                continue
            if c == '%':
                var = self._try_variable()
                if var is None:
                    raise FormatSyntaxError('malformed variable',
                                            self.src, self.i)
                parts.append(var)
                continue
            parts.append(self._bare_word())

        return Expression(parts)

    def _quoted(self) -> Expression:
        """A '...' literal. Its contents are text, so calls nest inside it."""
        self.i += 1                                  # opening quote
        parts, buf = [], []

        def flush():
            if buf:
                parts.append(Text(''.join(buf)))
                buf.clear()

        while True:
            if self._eof():
                raise FormatSyntaxError('unterminated quoted string',
                                        self.src, self.i)
            c = self._peek()
            if c == "'":
                self.i += 1
                break
            if c == '\\' and self.i + 1 < len(self.src):
                nxt = self.src[self.i + 1]
                if nxt in _ESCAPES:
                    buf.append(_ESCAPES[nxt])
                    self.i += 2
                    continue
                # Not an escape we define: keep both characters, so \x27
                # reaches the caller that is expecting to undo it.
                buf.append(c)
                self.i += 1
                continue
            if c == '$':
                call = self._try_call()
                if call is not None:
                    flush()
                    parts.append(call)
                    continue
                buf.append(c)
                self.i += 1
                continue
            if c == '%':
                var = self._try_variable()
                if var is not None:
                    flush()
                    parts.append(var)
                    continue
                buf.append(c)
                self.i += 1
                continue
            buf.append(c)
            self.i += 1

        flush()
        return Expression(parts)

    def _bare_word(self) -> Text:
        """An unquoted argument: a number, or a word. Ends at , ) + or space."""
        start = self.i
        while not self._eof() and self._peek() not in ",)+ \t'":
            if self._peek() in '$%':
                break
            self.i += 1
        if self.i == start:                          # never advance nothing
            self.i += 1
        return Text(self.src[start:self.i])

    # -- constructs ---------------------------------------------------------

    def _try_call(self) -> Optional[Call]:
        """A $name( ... ) at the cursor, or None if this $ is just a $."""
        start = self.i
        name = self._name_at(start + 1)
        if not name or self.src[start + 1 + len(name):start + 2 + len(name)] != '(':
            return None

        self.i = start + 2 + len(name)               # past '$name('
        args = []
        while True:
            if self._eof():
                raise FormatSyntaxError(f'unclosed $ {name}(', self.src, start)
            arg = self.parse_expression()
            c = self._peek()
            if c == ',':
                args.append(arg)
                self.i += 1
                continue
            if c == ')':
                # A trailing comma adds no argument -- $strcmp('','',) has
                # two, as it did when Python parsed the call.
                if arg.parts or not args:
                    args.append(arg)
                self.i += 1
                break
            raise FormatSyntaxError(f'unclosed ${name}(', self.src, start)

        return Call(name, args)

    def _try_variable(self) -> Optional[Variable]:
        """A %name% at the cursor, or None if this % is just a %."""
        start = self.i
        name = self._name_at(start + 1)
        if not name or self.src[start + 1 + len(name):start + 2 + len(name)] != '%':
            return None
        self.i = start + 2 + len(name)
        return Variable(name)


def parse(source: str) -> Expression:
    """Parse a format string into a tree. Text context: the top level."""
    return _Parser(source).parse_text()


# ── evaluation ──────────────────────────────────────────────────────────────

#: What an unknown function renders to. The old evaluator checked every
#: function name in a top-level call before evaluating any of it, so one
#: unknown name anywhere replaced the whole call -- not just itself.
UNKNOWN = 'unknown command'


def _stringify(value) -> str:
    if value is None:
        return ''
    if value is True:
        return 'True'
    if value is False:
        return 'False'
    return str(value)


def _names_in(node) -> set:
    if isinstance(node, Call):
        found = {node.name}
        for arg in node.args:
            found |= _names_in(arg)
        return found
    if isinstance(node, Expression):
        found = set()
        for part in node.parts:
            found |= _names_in(part)
        return found
    return set()


def evaluate(node, functions: dict, values: Optional[dict] = None):
    """Evaluate a tree.

    functions maps a bare name ('upper') to a callable.
    values maps a bare variable name ('album') to its value. A name that is
    not there evaluates to '%name%', which is what an unsubstituted variable
    did before and is how a caller that pre-substitutes still works.
    """
    if isinstance(node, Text):
        return node.value

    if isinstance(node, Variable):
        if values is not None and node.name in values:
            v = values[node.name]
            return '' if v is None else str(v)
        return f'%{node.name}%'

    if isinstance(node, Call):
        unknown = _names_in(node) - set(functions)
        if unknown:
            logger.debug('Unknown format function(s): %s', ', '.join(sorted(unknown)))
            return UNKNOWN
        args = [evaluate(a, functions, values) for a in node.args]
        return functions[node.name](*args)

    if isinstance(node, Expression):
        if not node.parts:
            return ''
        if len(node.parts) == 1:
            # Keep the Python value: a bool must reach $neg as a bool.
            return evaluate(node.parts[0], functions, values)
        return ''.join(_stringify(evaluate(p, functions, values))
                       for p in node.parts)

    raise TypeError(f'not a format node: {node!r}')


def render(source: str, functions: dict, values: Optional[dict] = None) -> str:
    """Parse and evaluate, returning the string a format produces."""
    return _stringify(evaluate(parse(source), functions, values))
