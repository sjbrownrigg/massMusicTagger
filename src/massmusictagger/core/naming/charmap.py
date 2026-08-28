# -*- coding: utf-8 -*-
"""Character substitution maps for filename generation.

Profiles are defined in conf/char_substitutions.yaml.  Select a profile
by setting ``char_profile`` in the ``[details]`` section of your config.

The ``[character_exceptions]`` INI section is applied on top of the YAML
profile, so you can still use per-config INI overrides for individual tweaks
without touching the YAML file.

Architecture note
-----------------
This module is intentionally service-agnostic.  When the project is extended
to support MusicBrainz or other metadata sources, this module can be reused
without modification — it knows nothing about Discogs, tagging, or file I/O.
"""
import logging
import os
import re

from massmusictagger import roots

logger = logging.getLogger(__name__)

# Resolved through roots rather than a path relative to this module: the
# package layout moved when this was absorbed, and a hand-built ../conf path
# is exactly the kind of thing that then resolves to nothing in silence.
_DEFAULT_YAML = os.path.join(roots.BUNDLED_CONF, 'char_substitutions.yaml')

# Characters that are unconditionally invalid on Linux filesystems.
# / is the path separator; \x00 terminates C strings.
# Control characters \x01–\x1f and \x7f are technically legal on ext4 but
# universally problematic (terminals, editors, shell scripts all choke on them).
#
# These are handled separately from the user-configurable substitution map so
# that the substitution map can define *what to replace them with* rather than
# simply dropping them.  See ``_FS_INVALID_RE`` and the ``fs_invalid``
# profile key below.
_CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')


def load_substitutions(yaml_path: str | None, profile: str) -> dict:
    """Load a substitution map from a YAML profile file.

    Returns a dict of ``{from_str: to_str}`` pairs for the named profile.
    An empty dict is returned (and a warning logged) if the file is missing,
    the profile is not found, or PyYAML is not installed.

    Parameters
    ----------
    yaml_path:
        Path to the YAML file.  ``None`` falls back to
        ``conf/char_substitutions.yaml`` relative to this package.
    profile:
        Name of the profile to load (e.g. ``"linux"``, ``"windows"``).
    """
    path = yaml_path or _DEFAULT_YAML

    try:
        import yaml
    except ImportError:
        logger.warning(
            'pyyaml is not installed — char_substitutions.yaml will not be loaded. '
            'Run: pip install pyyaml'
        )
        return {}

    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.debug('Char substitutions file not found: %s', path)
        return {}
    except Exception as e:
        logger.warning('Failed to load char substitutions from %s: %s', path, e)
        return {}

    profiles = (data or {}).get('profiles', {})
    subs = profiles.get(profile)
    if subs is None:
        if profile != 'linux':
            logger.warning('Char substitution profile "%s" not found in %s', profile, path)
        return {}

    result = {str(k): (str(v) if v is not None else '') for k, v in subs.items()}
    logger.debug('Loaded %d substitution(s) for profile "%s" from %s',
                 len(result), profile, path)
    return result


def build_map(tagger_config, yaml_path: str | None = None) -> dict:
    """Build the combined substitution map for a TaggerConfig.

    Loads the YAML profile first, then overlays the ``[character_exceptions]``
    INI section so that per-config overrides take precedence.

    Gracefully handles configs that predate the char_profile / char_substitutions
    keys by falling back to an empty YAML load (no substitutions from YAML).
    """
    try:
        profile = tagger_config.get('details', 'char_profile') or 'linux'
    except Exception:
        profile = 'linux'

    try:
        resolved_yaml = yaml_path or tagger_config.resolve_path(
            tagger_config.get('details', 'char_substitutions'),
            'details.char_substitutions')
    except Exception:
        resolved_yaml = None

    combined = load_substitutions(resolved_yaml, profile)

    # INI [character_exceptions] are applied on top — they win over the profile
    ini = dict(getattr(tagger_config, 'character_exceptions', {}))
    combined.update(ini)

    return combined


def apply_substitutions(text: str, substitutions: dict) -> str:
    """Apply a substitution map to *text*, returning the result.

    Substitutions are applied in insertion order (Python 3.7+ dict guarantee).
    Each key is replaced by its value; an empty value removes the character.
    """
    for from_str, to_str in substitutions.items():
        text = text.replace(from_str, to_str)
    return text


def strip_invalid(text: str, path_sep_replacement: str = '',
                  control_replacement: str = '') -> str:
    """Strip or replace characters that are invalid on any real filesystem.

    Parameters
    ----------
    text:
        The string to sanitise.
    path_sep_replacement:
        What to replace ``/`` with.  Default is ``''`` (remove).
        Use ``'-'`` to turn path separators into hyphens.
    control_replacement:
        What to replace control characters (``\\x00–\\x1f``, ``\\x7f``) with.
        Default is ``''`` (remove).
    """
    text = text.replace('/', path_sep_replacement)
    text = _CONTROL_RE.sub(control_replacement, text)
    return text
