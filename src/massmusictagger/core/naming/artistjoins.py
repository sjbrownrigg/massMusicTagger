# -*- coding: utf-8 -*-
"""Reading a multi-artist credit for the purpose of filing an album.

A release credited "David Bowie Featuring Al B. Sure!" gets its own artist
folder, which fragments Bowie's discography. Filing it under Bowie is right.
Doing the same to "D.A.R.P.A. / Dive / :wumpscut:" is wrong: that is a split
release, and collapsing it hides two artists entirely.

Two tests separate them, and the first matters more than the second.

**Identity, before phrasing.** Measured over the cached Discogs releases,
48 of 73 join tokens were ``=`` -- not a collaboration marker at all, but
Discogs' transliteration form, the same artist listed twice:

    name='David Bowie' anv=''               join='=' id=10263
    name='David Bowie' anv='デビッド・ボウイー' join=''  id=10263

So credits that resolve to a single artist entity are one artist, whatever
sits between them. Anything reading "several credits" as "several artists"
gets the common case wrong.

**Then the join phrase**, for genuinely different artists -- and that is a
judgement call, so it lives in ``artist_joins.yaml`` where the user owns it
rather than in this file. Unlisted joins are coordinating, which is the safe
default: a featuring credit left uncollapsed costs one surplus folder,
visible and cheap to fix, while a collapsed split hides artists and leaves no
trace that it happened.

Nothing here touches the ``albumartist`` tag, which always keeps the full
credit -- the tag should say what the release says. This is consulted only by
``%albumartist_primary%``, so a configuration whose format strings never
mention it is unaffected.
"""

import logging
import os

logger = logging.getLogger(__name__)

#: Read when no table can be loaded at all. Deliberately conservative: with
#: nothing subordinating, every credit keeps all its artists, which is the
#: behaviour that predates this module.
_FALLBACK = {'subordinating': [], 'coordinating': []}


def _packaged_path() -> str:
    from massmusictagger import roots
    return os.path.join(roots.BUNDLED_CONF, 'artist_joins.yaml')


def _read(path: str) -> dict:
    try:
        import yaml
        with open(path, encoding='utf-8') as f:
            return (yaml.safe_load(f) or {}).get('artist_joins', {}) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning('Could not read artist joins from %s (%s)', path, exc)
        return {}


def _merged_over_packaged(user: dict, path: str) -> dict:
    """A user's table adds to the packaged one rather than replacing it.

    Same reasoning as source_hints: a copy taken into a config directory
    otherwise freezes the list at whatever shipped that day, and later
    additions never reach anyone who has customised a single line.
    """
    packaged_path = _packaged_path()
    if os.path.abspath(path) == os.path.abspath(packaged_path):
        return user

    packaged = _read(packaged_path)
    if not packaged:
        return user

    merged = dict(packaged)
    for key, value in (user or {}).items():
        if isinstance(value, list) and isinstance(merged.get(key), list):
            seen, combined = set(), []
            for item in list(merged[key]) + list(value):
                if item not in seen:
                    seen.add(item)
                    combined.append(item)
            merged[key] = combined
        else:
            merged[key] = value
    return merged


def load_artist_joins(yaml_path: 'str | None' = None) -> dict:
    """Return the join table: {'subordinating': [...], 'coordinating': [...]}.

    A named file that is missing is a mistake worth hearing about, so it warns
    and falls back to the packaged table rather than switching the feature off
    in silence -- the failure mode that left ``char_profile: windows`` inert
    across a whole library.
    """
    if yaml_path:
        if os.path.exists(yaml_path):
            return _merged_over_packaged(_read(yaml_path), yaml_path)
        logger.warning('Artist joins file not found: %s — using the packaged table',
                       yaml_path)

    packaged = _read(_packaged_path())
    return packaged or dict(_FALLBACK)


def _normalise(join: str) -> str:
    return (join or '').strip().strip(',').strip().lower()


def is_subordinating(join: str, table: dict) -> bool:
    """Does *join* mark what follows it as a guest rather than a co-artist?

    Unlisted joins are coordinating. See the module docstring for why that
    asymmetry is the right way round.
    """
    needle = _normalise(join)
    if not needle:
        return False
    return any(_normalise(t) == needle
               for t in (table or {}).get('subordinating', []) or [])


def primary_artist(artists, joins, display, table, ids=None):
    """The name an album should file under.

    *artists* are the individual credited names, *joins* the phrases between
    them (``joins[i]`` follows ``artists[i]``), *display* the full credit
    string, and *ids* the source's identifier per credit when it has one.

    Returns *display* unchanged unless the credit is unambiguously one artist
    with guests, in which case the first artist alone is returned.
    """
    names = [a for a in (artists or []) if a]
    if len(names) < 2:
        return display or (names[0] if names else '')

    # Identity first: several credits naming one artist are one artist.
    # Discogs' '=' transliteration form is the common case.
    known = [i for i in (ids or []) if i]
    if known and len(known) == len(names) and len(set(known)) == 1:
        logger.debug('Credits resolve to one artist (%s) — filing under %s',
                     known[0], names[0])
        return names[0]

    # Every join between the artists must subordinate. A credit like
    # "A feat. B / C" is part collaboration and keeps its full billing.
    between = [j for j in (joins or []) if _normalise(j)]
    if not between:
        return display or names[0]
    if all(is_subordinating(j, table) for j in between):
        logger.info('Filing under primary artist %r (credit: %r)',
                    names[0], display)
        return names[0]
    return display or names[0]
