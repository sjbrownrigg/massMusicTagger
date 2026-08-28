# -*- coding: utf-8 -*-
import fnmatch
import logging
import os
from pathlib import Path
from unicodedata import normalize as unicode_normalize

logger = logging.getLogger(__name__)


def resolve_path(path: str) -> str:
    """Return the real filesystem path for *path*, working around encoding gaps.

    On some systems (notably WSL2 with files written from Windows) filenames
    containing non-ASCII bytes that are not valid UTF-8 (e.g. the Windows-1252
    right single quotation mark ``\\x92``) are decoded with the ``replace``
    error handler instead of ``surrogateescape``.  This turns the undecodable
    byte into a literal ``?`` (U+003F).  Subsequent ``open()`` calls look for
    a file whose name contains ``?``, which doesn't exist on disk, producing a
    spurious ``FileNotFoundError``.

    Strategies tried in order:
    1. The path as given — fast path for the common case.
    2. NFC then NFD Unicode normalisation — fixes composed/decomposed mismatch
       (common when macOS and Linux share a volume).
    3. ``fnmatch`` wildcard scan of the parent directory, treating every ``?``
       in the filename as a single-character wildcard.  This recovers the real
       path when a non-ASCII character was decoded as ``?``.

    Returns the resolved path string.  If no match is found the original path
    is returned unchanged so the caller still gets a ``FileNotFoundError`` with
    a useful message rather than a silent wrong-file open.
    """
    p = Path(path)

    # Fast path — file exists as given
    if p.exists():
        return path

    # Try Unicode normalisation variants (NFC / NFD round-trip)
    for form in ('NFC', 'NFD'):
        candidate = Path(unicode_normalize(form, str(p)))
        if candidate.exists():
            logger.debug('Path resolved via %s normalisation: %s', form, repr(p.name))
            return str(candidate)

    # Wildcard scan: treat '?' in the name as matching any single character.
    # fnmatch.fnmatchcase uses '?' as a single-char wildcard, which is exactly
    # what we need when a non-ASCII byte was decoded as '?'.
    parent = p.parent
    name = p.name

    if '?' not in name:
        # No wildcards → scan won't help; return original
        return path

    if not parent.is_dir():
        return path

    try:
        matches = [
            entry
            for entry in parent.iterdir()
            if entry.is_file() and fnmatch.fnmatchcase(entry.name, name)
        ]
    except OSError:
        return path

    if len(matches) == 1:
        resolved = str(matches[0])
        if resolved != path:
            logger.debug('Path resolved via directory scan: %s → %s',
                         repr(name), repr(matches[0].name))
        return resolved

    if len(matches) > 1:
        logger.warning(
            'Ambiguous filename — %d entries match %s; using first match',
            len(matches), repr(name),
        )
        return str(matches[0])

    return path  # no match; caller will get a FileNotFoundError with the original path
