# -*- coding: utf-8 -*-
"""The schema is the source of truth; the sample documents it.

massMusicTagger absorbed discogstagger3's schema but not the tests that keep
its sample honest, so conf/config_sample.yaml -- never loaded at runtime --
had nothing checking it still described the code. It had already drifted: the
sample advertised massMusicTagger/1.0 while the schema handed Discogs
discogstagger/4.0, and neither matched the installed version.
"""

import os
import sys

import pytest
import yaml

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

from massmusictagger import config_schema, roots

#: Every reference sample, because the configuration is a *directory*:
#: credentials live in their own files beside config.yaml, so checking
#: config_sample.yaml alone would report [discogs] and [musicbrainz] as
#: undocumented when they are documented in the file that actually holds them.
SAMPLES = ('config_sample.yaml', 'discogs_sample.yaml',
           'musicbrainz_sample.yaml')


def _sample_pairs(names=SAMPLES):
    """Flatten the samples the way TaggerConfig flattens a config."""
    pairs = {}
    for name in names:
        path = os.path.join(roots.BUNDLED_CONF, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as fh:
            data = yaml.safe_load(fh) or {}
        for section, values in data.items():
            if not isinstance(values, dict):
                continue    # suppress_tags is a list of bare keys
            for key, val in values.items():
                pairs[(section, key)] = '' if val is None else str(val)
    return pairs


def test_every_sample_named_here_exists():
    """A renamed sample must not silently drop out of the checks above."""
    missing = [n for n in SAMPLES
               if not os.path.exists(os.path.join(roots.BUNDLED_CONF, n))]
    assert not missing, f'sample files named but not shipped: {missing}'


# ── sample and schema agree ──────────────────────────────────────────────────

def test_sample_documents_every_schema_key():
    documented = set(_sample_pairs())
    known = (set(config_schema.DEFAULTS) | set(config_schema.REQUIRED)
             | set(config_schema.MMT_KEYS))
    undocumented = {k for k in known - documented
                    if k[0] not in config_schema.FREEFORM_SECTIONS}
    assert not undocumented, (
        'these keys exist in config_schema but not in config_sample.yaml: '
        f'{sorted(undocumented)}')


def test_schema_knows_every_sample_key():
    documented = set(_sample_pairs())
    known = (set(config_schema.DEFAULTS) | set(config_schema.REQUIRED)
             | set(config_schema.DEPRECATED) | set(config_schema.MMT_KEYS))
    unknown = {k for k in documented - known
               if k[0] not in config_schema.FREEFORM_SECTIONS}
    assert not unknown, (
        'config_sample.yaml documents keys the schema does not know, so they '
        f'would be reported as typos: {sorted(unknown)}')


def test_sample_values_match_schema_defaults():
    sample = _sample_pairs()
    mismatched = {
        key: (sample[key], default)
        for key, default in config_schema.DEFAULTS.items()
        if key in sample and key not in config_schema.COMPUTED
        and sample[key] != default
    }
    assert not mismatched, (
        'config_sample.yaml shows a different value than the schema applies '
        f'(key: sample vs schema): {mismatched}')


# ── the Discogs identity ─────────────────────────────────────────────────────

def test_the_user_agent_names_this_program():
    """It said discogstagger/4.0 -- another program, at a version it has not.

    Discogs registers applications by name and issues one personal token at a
    time across them, so identifying as a different client is not cosmetic.
    """
    ua = config_schema.DEFAULTS[('common', 'user_agent')]
    assert ua.startswith('massMusicTagger/')
    assert 'discogstagger' not in ua


def test_the_user_agent_carries_the_running_version():
    """The written-out copy went stale: 1.0 two major versions later."""
    from massmusictagger import __version__
    assert __version__ in config_schema.DEFAULTS[('common', 'user_agent')]


def test_the_sample_user_agent_names_this_program_too():
    """The version is exempt from the exact-match test; the name is not."""
    ua = _sample_pairs(('config_sample.yaml',))[('common', 'user_agent')]
    assert ua.startswith('massMusicTagger/')
    assert 'discogstagger' not in ua


# ── deprecations explain themselves ──────────────────────────────────────────

def test_every_deprecated_key_says_what_replaced_it():
    """A warning that names a key and stops is not much help.

    common.formats_file warned without a note for as long as the mechanism
    existed, so the one place a user could learn what to do instead was the
    commit that deprecated it.
    """
    silent = sorted(set(config_schema.DEPRECATED)
                    - set(config_schema.DEPRECATION_NOTES))
    assert not silent, (
        f'deprecated with no explanation: {silent}')
