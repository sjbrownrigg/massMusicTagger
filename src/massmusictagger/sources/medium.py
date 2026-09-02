"""The medium-preference table: how much a release's format counts when ranking.

Loaded the same way as the other rule tables -- packaged by default, and a file
beside config.yaml is merged over it, so changing one number neither discards
the rest of the table nor opts out of later additions.

Why this is a table and not a constant: the right weights depend on the
collection. Someone whose library is mostly needle drops wants vinyl preferred
at 16/44.1, not penalised, and only they know that.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Read when no table can be loaded at all. Empty on purpose: with no weights,
#: every medium scores 0 and ranking falls back to tracks and durations alone,
#: which is the behaviour that predates this table.
_FALLBACK = {'cd_spec': {}, 'hi_res': {}}

#: A weight this large stops being a tie-breaker against a base score of 50 and
#: starts deciding matches by itself. Clamped rather than rejected, so a typo
#: costs a warning instead of a run.
_MAX_WEIGHT = 5.0


def _packaged_path() -> str:
    from massmusictagger import roots
    return os.path.join(roots.BUNDLED_CONF, 'medium_preference.yaml')


def _read(path: str) -> dict:
    try:
        import yaml
        with open(path, encoding='utf-8') as f:
            return (yaml.safe_load(f) or {}).get('medium_preference', {}) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning('Could not read medium preferences from %s (%s)', path, exc)
        return {}


def _clean(table: dict) -> dict:
    """Lowercase the medium names and keep the weights within bounds."""
    out = {}
    for section in ('cd_spec', 'hi_res'):
        weights = {}
        for medium, weight in (table.get(section) or {}).items():
            try:
                value = float(weight)
            except (TypeError, ValueError):
                logger.warning('medium_preference.%s: %r is not a number — ignored',
                               section, medium)
                continue
            if abs(value) > _MAX_WEIGHT:
                logger.warning(
                    'medium_preference.%s.%s is %.1f, beyond the %.1f a '
                    'tie-breaker should reach — clamped',
                    section, medium, value, _MAX_WEIGHT)
                value = _MAX_WEIGHT if value > 0 else -_MAX_WEIGHT
            weights[str(medium).strip().lower()] = value
        out[section] = weights
    return out


def _merged_over_packaged(user: dict, path: str) -> dict:
    """A user's table adds to the packaged one rather than replacing it."""
    if os.path.abspath(path) == os.path.abspath(_packaged_path()):
        return user
    packaged = _read(_packaged_path())
    if not packaged:
        return user
    merged = {}
    for section in set(packaged) | set(user or {}):
        base = dict(packaged.get(section) or {})
        base.update(user.get(section) or {})
        merged[section] = base
    return merged


def load_medium_preference(yaml_path: 'str | None' = None) -> dict:
    """Return {'cd_spec': {medium: weight}, 'hi_res': {medium: weight}}.

    A named file that is missing warns and falls back to the packaged table,
    rather than switching the feature off in silence.
    """
    if yaml_path:
        if os.path.exists(yaml_path):
            return _clean(_merged_over_packaged(_read(yaml_path), yaml_path))
        logger.warning('Medium preference file not found: %s — using the '
                       'packaged table', yaml_path)
    packaged = _read(_packaged_path())
    return _clean(packaged) if packaged else dict(_FALLBACK)
