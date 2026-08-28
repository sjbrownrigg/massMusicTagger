# -*- coding: utf-8 -*-
"""Signals read from the source folder itself, before any source is asked.

These describe what is already on disk -- the folder name, the tags -- and are
consumed by more than one source: the format hint gates Discogs candidates and
steers MusicBrainz, and the descriptor hints boost Discogs scoring. They live
here rather than inside either source because neither owns them.

This is the first piece of the "search shape": a declared view of what the
local files say, which every source matches against rather than each deriving
its own privately.
"""

import logging
import os

logger = logging.getLogger(__name__)


def _load_source_hints(cfg) -> dict:
    """Return source_hints dict from the configured YAML file, or {}.

    Tries details.source_hints_file first (shared by all sources), then
    musicbrainz.source_hints_file for backward compatibility.
    """
    path = ''
    for section, key in (('details', 'source_hints_file'),
                          ('musicbrainz', 'source_hints_file')):
        try:
            p = (cfg.get(section, key) or '').strip()
            if p:
                path = p
                break
        except Exception:
            pass
    if path:
        # An override named by the config resolves beside that config file.
        try:
            path = cfg.resolve_path(path, 'details.source_hints_file') or path
        except Exception:
            path = os.path.expanduser(path)
    else:
        # No override: use the copy shipped inside the package. This used to
        # return {} instead, so the feature was silently off for every
        # installed copy -- the repo-relative default in the sample config
        # only ever resolved from a source checkout.
        from massmusictagger import roots
        path = os.path.join(roots.BUNDLED_CONF, 'source_hints.yaml')
    path = os.path.normpath(path)
    try:
        import yaml as _yaml
        with open(path, encoding='utf-8') as f:
            data = _yaml.safe_load(f) or {}
        return data.get('source_hints', {})
    except FileNotFoundError:
        logger.debug('source_hints_file not found: %s', path)
        return {}
    except Exception as exc:
        logger.warning('Failed to load source hints from %s: %s', path, exc)
        return {}

def _folder_format_hint(sourcedir: str, hints: dict) -> str:
    """Return 'digital', 'vinyl', or '' based on folder name keywords."""
    if not hints:
        return ''
    folder = os.path.basename(sourcedir.rstrip('/\\'))
    folder_lower = folder.lower()
    for kw in hints.get('digital', []):
        if str(kw).lower() in folder_lower:
            logger.debug("Format hint 'digital' matched keyword %r in %r", kw, folder)
            return 'digital'
    for kw in hints.get('vinyl', []):
        if str(kw).lower() in folder_lower:
            logger.debug("Format hint 'vinyl' matched keyword %r in %r", kw, folder)
            return 'vinyl'
    return ''

def _folder_descriptor_hints(sourcedir: str, hints: dict) -> list:
    """Return descriptor_boost keywords matched in the folder name.

    Unlike format hints (which hard-reject mismatched releases), these are
    passed to the Discogs searcher as a soft scoring signal: candidates whose
    Discogs descriptions include a matched keyword receive a ranking bonus.
    """
    if not hints:
        return []
    folder = os.path.basename(sourcedir.rstrip('/\\'))
    folder_lower = folder.lower()
    matched = []
    for kw in hints.get('descriptor_boost', []):
        if str(kw).lower() in folder_lower:
            logger.debug("Descriptor hint %r matched in %r", kw, folder)
            matched.append(kw)
    return matched
