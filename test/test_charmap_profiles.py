# -*- coding: utf-8 -*-
"""Character substitution: does the configured profile actually take effect?

These exist because `char_profile: windows` ran in production applying no
substitutions at all. The configured char_substitutions path pointed at a
repo-relative location that stopped existing when the layout changed, the
loader treated a missing file as a debug-level non-event, and the result was
filenames containing <, >, ? and " -- illegal on NTFS, broken over Samba.

The real-world case is Blue Eyed Christ's "World On Fire", whose tracklist
carries "<<Start The Show>>", "Stop The Show!" and ">Nation Of The Damned<".
Its titles are the fixture; no audio is needed to test the naming rules.
"""

import os
import sys

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parentdir)

from massmusictagger.core.naming.charmap import (
    load_substitutions, apply_substitutions, build_map)

# Real titles from that release — the shape that exposed the bug.
WORLD_ON_FIRE = [
    "<<Start The Show>>",
    "Stop The Show!",
    "Manic Adderall >Nation Of The Damned<",
    "Are You Feeling Free? (Basic Mixing)",
]

# Characters NTFS rejects outright.
NTFS_ILLEGAL = set('<>:"/\\|?*')


def test_windows_profile_removes_every_ntfs_illegal_character():
    subs = load_substitutions(None, 'windows')
    assert subs, 'the packaged windows profile should load'
    for title in WORLD_ON_FIRE:
        out = apply_substitutions(title, subs)
        offending = NTFS_ILLEGAL & set(out)
        assert not offending, (
            f'{title!r} -> {out!r} still contains {sorted(offending)}, '
            'which NTFS rejects')


def test_windows_profile_actually_changes_the_awkward_titles():
    """Guards against a profile that loads but substitutes nothing."""
    subs = load_substitutions(None, 'windows')
    assert apply_substitutions("<<Start The Show>>", subs) == "((Start The Show))"
    assert apply_substitutions("Are You Feeling Free?", subs) == "Are You Feeling Free"


def test_linux_profile_preserves_titles():
    """Linux only forbids / and NUL, so the profile is deliberately empty."""
    subs = load_substitutions(None, 'linux')
    for title in WORLD_ON_FIRE:
        assert apply_substitutions(title, subs) == title


def test_missing_configured_file_warns_rather_than_silently_doing_nothing(caplog):
    """The exact production failure: a configured path that is not there.

    It used to log at debug and return {}, so char_profile had no effect and
    nothing said so at INFO.
    """
    with caplog.at_level('WARNING'):
        subs = load_substitutions('/nowhere/char_substitutions.yaml', 'windows')
    assert subs == {}
    assert 'no effect' in caplog.text or 'does not exist' in caplog.text


def test_default_path_does_not_warn(caplog):
    """No configured path is normal, not a problem worth warning about."""
    with caplog.at_level('WARNING'):
        subs = load_substitutions(None, 'windows')
    assert subs
    assert 'does not exist' not in caplog.text


def test_build_map_honours_the_profile_from_config():
    """End to end through TaggerConfig, which is how the pipeline reaches it."""
    from massmusictagger.core.tagger_config import TaggerConfig
    from massmusictagger import roots
    cfg = TaggerConfig(os.path.join(roots.BUNDLED_CONF, 'config_sample.yaml'))
    cfg.set('details', 'char_profile', 'windows')
    cfg.set('details', 'char_substitutions', '')
    m = build_map(cfg)
    assert m, 'build_map should pick up the windows profile'
    assert apply_substitutions("<<Start The Show>>", m) == "((Start The Show))"
