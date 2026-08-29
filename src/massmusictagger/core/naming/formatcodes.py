# -*- coding: utf-8 -*-
"""Discogs format code computation.

Translates the three format fields that Discogs provides — format name,
format descriptions, and disc count — into a compact, human-readable code
that can be used in directory/file naming format strings as ``%format_code%``.

Examples
--------
Vinyl  + ["Album"]                + 1  →  LP
Vinyl  + ["7\\"", "Single"]       + 1  →  7″      (7" always shows)
Vinyl  + ["12\\"", "Single"]      + 1  →  12″     (12" single shows size)
Vinyl  + ["12\\"", "Album"]       + 1  →  LP      (12" album = LP)
Vinyl  + ["12\\"", "Maxi-Single"] + 1  →  12″
Vinyl  + ["Album"]                + 2  →  DLP
CD     + ["Album"]                + 1  →  CD
CD     + ["Single"]               + 1  →  CD      (type via %releasetype%)
CD     + ["Album","Limited Ed."]  + 2  →  DCD     (edition via %edition%)
File   + ["Album", "FLAC"]        + 1  →  DM
""      + []                       + 1  →  UU      (unknown / no media tag)

Architecture note
-----------------
This module is purely computational — no I/O except YAML loading via
``load_format_codes()``.  It has no dependency on Discogs, tagging or file
I/O, making it easy to reuse in a future service-agnostic tagger.
"""
import logging
import os
import re as _re

from massmusictagger import roots

logger = logging.getLogger(__name__)

# Resolved through roots rather than a path relative to this module: the
# package layout moved when this was absorbed, and a hand-built ../conf path
# is exactly the kind of thing that then resolves to nothing in silence.
_DEFAULT_YAML = os.path.join(roots.BUNDLED_CONF, 'format_codes.yaml')


def _read_yaml(path: str) -> dict | None:
    """Parse a YAML mapping, or None when it is not there or not readable."""
    try:
        import yaml
    except ImportError:
        logger.warning('pyyaml is not installed — format codes unavailable')
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning('Failed to load format codes from %s: %s', path, exc)
        return None


def load_format_codes(yaml_path: str | None = None) -> dict:
    """The format-code rules: the bundled table, with a user file merged over.

    A missing user file falls back to the bundled table and says so. It used
    to return {} instead, and at debug level -- so a config naming a path that
    did not resolve turned every abbreviation off in silence, and a release on
    Digital Media was filed as "Digital Media" rather than "DM". That is the
    same shape as the char_substitutions path that left char_profile: windows
    inert across a whole library.

    Merged rather than replaced, one level deep, because the table has several
    independent sections. Supplying a file with only base_formats used to
    discard vinyl_sizes and the quantity rules with it, and an upgrade that
    added a section would never reach anyone who had overridden one line.
    """
    base = _read_yaml(_DEFAULT_YAML)
    if base is None:
        logger.warning('The bundled format code table is missing at %s',
                       _DEFAULT_YAML)
        base = {}

    if not yaml_path:
        return base

    user = _read_yaml(yaml_path)
    if user is None:
        logger.warning('format_codes names %s, which does not exist — using '
                       'the bundled table', yaml_path)
        return base

    merged = dict(base)
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    logger.info('Format codes: %s merged over the bundled table', yaml_path)
    return merged


def compute_edition(descriptions: list, format_codes: dict, *,
                    loose: bool = False) -> str:
    """Return the first edition qualifier found in descriptions, or ''.

    Edition qualifiers (e.g. ``'Deluxe Edition'``, ``'Anniversary Edition'``)
    are listed under the ``editions`` key in format_codes.yaml.  They are
    intended to be displayed alongside the album title:

        [2012] The Young Gods (Deluxe Edition) [DCD flac-lossless-44s]

    Parameters
    ----------
    descriptions:
        Strings to search.  For structured Discogs ``descriptions`` arrays
        these are short standardised tags ("Album", "Deluxe Edition", …).
        For free-text ``format.text`` notes ("30th Anniversary 2CD Edition")
        use ``loose=True``.
    loose:
        When False (default) a pattern must be an exact substring of the
        description (case-insensitive).  When True every *word* of the pattern
        must appear somewhere in the description — useful for free-text notes
        where format info ("2CD") may be interleaved with the edition phrase.
    """
    patterns = [p.lower() for p in format_codes.get('editions', [])]

    def _matches(pat: str, text: str) -> bool:
        if loose:
            text_words = set(text.split())
            return all(pw in text_words for pw in pat.split())
        return pat in text

    for desc in (descriptions or []):
        desc_lower = desc.lower()
        if any(_matches(pat, desc_lower) for pat in patterns):
            return desc   # full string, not the pattern
    return ''


def compute_format_code(format_name: str,
                        descriptions: list,
                        disctotal: int,
                        format_codes: dict) -> str:
    """Return the physical format code for a release.

    Produces the physical medium abbreviation and multi-disc quantity prefix.
    Release type (Single, EP, Compilation) and edition qualifiers are NOT
    encoded here — use ``%releasetype%`` and ``%edition%`` in format strings
    to include those dimensions independently.

    Parameters
    ----------
    format_name:
        The format name, e.g. ``"Vinyl"``, ``"CD"``, ``"Digital Media"``.
    descriptions:
        Format descriptions list (used for vinyl size override only).
    disctotal:
        Total number of physical discs/records.
    format_codes:
        Rules dict as returned by ``load_format_codes()``.

    Returns
    -------
    str
        Examples: ``"CD"``, ``"LP"``, ``"7″"``, ``"DCD"``, ``"3xLP"``, ``"DM"``.
        Returns ``"UU"`` when format_name is empty or unknown — following the
        bibliographic metadata convention (MARC ``uuuu`` = date unknown,
        ``20uu`` = century known but year not).  Used when no media tag is
        embedded and the source is ``existing_tags``.
        Falls back to ``format_name`` for unrecognised but non-empty names.
    """
    # Code for unknown/absent format — configurable via format_codes.yaml
    _UU = format_codes.get('unknown_format_code', 'UU') if format_codes else 'UU'

    if not format_codes:
        return format_name or _UU

    desc_set = set(descriptions or [])

    # ── Step 1: base code from format name ───────────────────────────────────
    base_formats = format_codes.get('base_formats', {})
    # Unknown format (empty/None) → configured unknown code (default: UU);
    # unrecognised but non-empty name → keep raw name as code
    base = base_formats.get(format_name, format_name if format_name else _UU)

    # ── Step 2: vinyl size override ───────────────────────────────────────────
    # vinyl_sizes:            applied unconditionally (7", 10")
    # vinyl_sizes_conditional: applied only when a non-album type is present (12")
    if format_name == 'Vinyl':
        vinyl_sizes = format_codes.get('vinyl_sizes', {})
        for size_key, size_code in vinyl_sizes.items():
            if size_key in desc_set:
                base = size_code
                break   # first matching size wins
        else:
            # Conditional sizes: only apply when a non-album type is in descriptions.
            # 12" without any non-album type indicator is just an LP.
            vinyl_sizes_cond = format_codes.get('vinyl_sizes_conditional', {})
            vinyl_nonalbum = set(format_codes.get('vinyl_non_album_types', []))
            if not vinyl_nonalbum or desc_set & vinyl_nonalbum:
                for size_key, size_code in vinyl_sizes_cond.items():
                    if size_key in desc_set:
                        base = size_code
                        break

    # ── Step 3: quantity prefix ───────────────────────────────────────────────
    # Multi-disc quantity is still a physical property worth encoding.
    # D (double), 3x, 4x, etc.
    code = base
    qty = int(disctotal or 1)
    if qty > 1:
        aliases = format_codes.get('quantity_aliases', {})
        qty_fmt = format_codes.get('quantity_format', '{n}x')
        qty_str = str(aliases.get(qty, qty_fmt.replace('{n}', str(qty))))
        code = qty_str + code

    return code


def extract_vinyl_size(descriptions: list) -> str:
    """Return the vinyl size descriptor from a format_description list, or ''.

    Scans the list for entries matching NN" (e.g. '7"', '10"', '12"') and
    returns the first match with ASCII double-quote replaced by the double prime
    character ″ (U+2033), which is safe in filenames and consistent with the
    values produced by vinyl_sizes in format_codes.yaml.

    Returns '' when no size descriptor is found (standard LP with no explicit
    size, or any non-vinyl release).  Available as ``%vinyl_size%`` in format
    strings — combine with ``%releasetype%`` and ``%format_base%`` to build
    custom naming logic entirely within formats_personal.ini.
    """
    for desc in (descriptions or []):
        if _re.match(r'^\d+"$', str(desc)):
            return str(desc).replace('"', '″')  # ASCII " → double prime ″
    return ''


def compute_release_types(
    format_name: str,
    descriptions: list,
    is_compilation: bool,
    format_codes: dict,
) -> tuple:
    """Infer MusicBrainz-style release types from Discogs format data.

    Returns
    -------
    (primary_type, secondary_types)
        primary_type   — str, e.g. "Album", "Single", "EP"
        secondary_types — list[str], e.g. ["Compilation", "Live"]

    The mapping is driven by the ``release_type_map`` section of
    ``format_codes.yaml`` so users can extend it without code changes.

    Discogs mixes release-type information ("Single", "Compilation") with
    physical-edition information ("Limited Edition", "Gatefold") in the same
    descriptions list.  This function extracts only the type-relevant entries.
    """
    rtm = format_codes.get('release_type_map', {})
    primary_map = {k.lower(): v for k, v in rtm.get('primary', {}).items()}
    secondary_map = {k.lower(): v for k, v in rtm.get('secondary', {}).items()}
    fn_primary_map = {k.lower(): v for k, v in rtm.get('format_name_primary', {}).items()}

    # Default primary type
    primary = 'Album'

    # Check format name first (e.g. 7" vinyl → Single)
    if format_name.lower() in fn_primary_map:
        primary = fn_primary_map[format_name.lower()]
    else:
        # Check descriptions for primary type override
        for desc in (descriptions or []):
            if desc.lower() in primary_map:
                primary = primary_map[desc.lower()]
                break   # first match wins

    # Collect secondary types (all that match)
    secondary: list[str] = []
    seen: set[str] = set()
    for desc in (descriptions or []):
        mb_type = secondary_map.get(desc.lower())
        if mb_type and mb_type not in seen:
            secondary.append(mb_type)
            seen.add(mb_type)

    # is_compilation ensures "Compilation" appears even when not in descriptions
    if is_compilation and 'Compilation' not in seen:
        secondary.insert(0, 'Compilation')

    return primary, secondary
