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

def _documented_keys():
    """Keys the samples describe, live or commented out.

    A setting shown commented out is still documented -- that is how the
    samples present a value better left to the code, such as the user agent
    built from the running version. Only counting live lines would call those
    undocumented and push someone to write them back in.
    """
    import re
    documented, section = set(), None
    for name in SAMPLES:
        path = os.path.join(roots.BUNDLED_CONF, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                header = re.match(r"^([a-z_][a-z_0-9-]*):\s*$", line)
                if header:
                    section = header.group(1)
                    continue
                setting = re.match(r"^\s+#?\s*([a-z_][a-z_0-9-]*):", line)
                if setting and section:
                    documented.add((section, setting.group(1)))
    return documented | set(_sample_pairs())


def test_sample_documents_every_schema_key():
    documented = _documented_keys()
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
        if key in sample
        and key not in config_schema.COMPUTED
        and key not in config_schema.PLACEHOLDERS
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


def test_the_sample_does_not_ship_a_user_agent_at_all():
    """It is derived from the running version, so a written value goes stale.

    The sample carried one live, so every configuration made from it pinned
    whatever literal happened to be there -- which said 2.0.0 through two
    major versions.
    """
    assert ('common', 'user_agent') not in _sample_pairs()
    assert ('common', 'user_agent') in _documented_keys(), \
        'still describe it, just commented out'


def test_the_sample_explains_why_the_user_agent_is_unset():
    path = os.path.join(roots.BUNDLED_CONF, 'config_sample.yaml')
    text = open(path, encoding='utf-8').read()
    assert 'built from the running version' in text


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


# ── credential discovery survives the paths this project creates ─────────────

def test_credentials_are_found_under_a_bracketed_path(tmp_path):
    """[ and ] are character classes to glob.

    massMusicTagger writes album directories like "[1991] Leaders + Followers",
    so a bracketed path is entirely ordinary here. Point the configuration
    directory at one and glob matched nothing: every credentials file was
    skipped and the run went out unauthenticated, with no error to say so.
    """
    cfg = tmp_path / "[2024] config"
    (cfg / "credentials").mkdir(parents=True)
    (cfg / "credentials" / "discogs.yaml").write_text("discogs: {}\n",
                                                      encoding="utf-8")
    found = roots.discover_credentials(str(cfg))
    assert [os.path.basename(p) for p in found] == ["discogs.yaml"]


def test_an_ordinary_path_still_works(tmp_path):
    cfg = tmp_path / "config"
    (cfg / "credentials").mkdir(parents=True)
    for name in ("musicbrainz.yaml", "discogs.yaml"):
        (cfg / "credentials" / name).write_text("{}\n", encoding="utf-8")
    found = roots.discover_credentials(str(cfg))
    assert [os.path.basename(p) for p in found] == ["discogs.yaml",
                                                    "musicbrainz.yaml"]


def test_placeholders_show_an_example_not_an_empty_string():
    """A credential's sample value teaches the format; "" teaches nothing."""
    sample = _sample_pairs()
    for key in sorted(config_schema.PLACEHOLDERS):
        if key not in sample:
            continue
        assert sample[key], f'{key} is a placeholder but the sample is empty'
        assert config_schema.DEFAULTS.get(key) == '', (
            f'{key} is a placeholder, so its schema default must be empty -- '
            'a credential must never have a working-looking default')


# ── logging.level does something ─────────────────────────────────────────────

def test_logging_level_accepts_a_name_or_a_number():
    """It was in the schema and nothing read it.

    A daemon container runs `mmt -w` with no tty, so the config file is the
    only place the level can come from; setting it did nothing at all.
    """
    import logging
    from massmusictagger.__main__ import _parse_level
    assert _parse_level('DEBUG') == logging.DEBUG
    assert _parse_level('debug') == logging.DEBUG
    assert _parse_level('10') == 10
    assert _parse_level('WARNING') == logging.WARNING


def test_an_unset_level_is_info():
    import logging
    from massmusictagger.__main__ import _parse_level
    assert _parse_level(None) == logging.INFO
    assert _parse_level('') == logging.INFO


def test_a_nonsense_level_warns_and_falls_back(caplog):
    import logging
    from massmusictagger.__main__ import _parse_level
    with caplog.at_level('WARNING'):
        assert _parse_level('chatty') == logging.INFO
    assert 'chatty' in caplog.text


def test_verbose_still_wins_over_the_config():
    """-v is the more immediate instruction."""
    import inspect, logging
    from massmusictagger.__main__ import _setup_logging
    src = inspect.getsource(_setup_logging)
    assert 'logging.DEBUG if verbose else' in src


# ── the 3.0.0 section move ───────────────────────────────────────────────────

def test_details_is_gone():
    """[details] was a 28-key catch-all: casing, artwork, archiving, tags."""
    sections = {s for s, _ in config_schema.DEFAULTS}
    assert 'details' not in sections


def test_every_moved_key_names_a_section_that_exists():
    """A key may have moved and later been deprecated, so accept either.

    naming.format_codes did both: [details] to [naming] in 3.0.0, then
    deprecated once format_codes.yaml became discoverable by name.
    """
    sections = {s for s, _ in config_schema.DEFAULTS}
    known = set(config_schema.DEFAULTS) | set(config_schema.DEPRECATED)
    for (old_section, key), new_section in config_schema.MOVED.items():
        assert new_section in sections, f'{key} moved to a section that is gone'
        assert (new_section, key) in known, (
            f'{old_section}.{key} says it moved to {new_section}, '
            'but that key is not there')


def test_a_moved_key_is_named_not_just_rejected(caplog):
    """"Unknown config key details.char_profile" is not actionable."""
    from massmusictagger.core.tagger_config import TaggerConfig
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        cf = os.path.join(tmp, 'config.yaml')
        with open(cf, 'w', encoding='utf-8') as fh:
            fh.write('details:\n  char_profile: windows\n')
        with caplog.at_level('WARNING'):
            TaggerConfig(cf)
    assert 'moved to [naming]' in caplog.text
    assert 'NOT being applied' in caplog.text


def test_a_removed_key_says_why(caplog):
    from massmusictagger.core.tagger_config import TaggerConfig
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        cf = os.path.join(tmp, 'config.yaml')
        with open(cf, 'w', encoding='utf-8') as fh:
            fh.write('tags:\n  encoder: lame\n')
        with caplog.at_level('WARNING'):
            TaggerConfig(cf)
    assert 'removed in 3.0.0' in caplog.text
    assert 'nothing read it' in caplog.text


def test_no_removed_key_is_still_in_the_schema():
    for key in config_schema.REMOVED:
        assert key not in config_schema.DEFAULTS, f'{key} is both removed and live'


# ── --migrate-config ─────────────────────────────────────────────────────────

def _migrate(tmp_path, body):
    import re as _re
    from massmusictagger import __main__ as mmt_main
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body, encoding="utf-8")

    class _Opts:
        migrate_config = str(tmp_path)

    class _Parser:
        @staticmethod
        def error(msg):
            raise AssertionError(msg)

    mmt_main._migrate_config(_Parser(), _Opts())
    return cfg.read_text(encoding="utf-8")


def test_migrate_moves_a_setting_to_its_new_section(tmp_path):
    import re
    out = _migrate(tmp_path, "details:\n  char_profile: windows\n")
    assert "naming:" in out
    assert "char_profile: windows" in out
    assert not re.search(r"^details:", out, re.M), "[details] should be gone"


def test_migrate_keeps_the_value(tmp_path):
    import yaml as _yaml
    out = _migrate(tmp_path, "details:\n  char_profile: windows\n"
                             "  image_policy: prefer_larger\n")
    data = _yaml.safe_load(out)
    assert data["naming"]["char_profile"] == "windows"
    assert data["artwork"]["image_policy"] == "prefer_larger"


def test_migrate_drops_a_removed_setting(tmp_path):
    out = _migrate(tmp_path, "details:\n  split_discs: false\n"
                             "  char_profile: linux\n")
    assert "split_discs" not in out


def test_migrate_keeps_the_comments(tmp_path):
    """These files are mostly comments; that is most of their value.

    A YAML round-trip would reformat the file and discard every one, which
    is why the migration is line-based.
    """
    body = ("details:\n"
            "  # Windows/Samba profile: replaces characters illegal on NTFS\n"
            "  char_profile: windows\n")
    out = _migrate(tmp_path, body)
    assert "# Windows/Samba profile" in out
    lines = out.splitlines()
    i = lines.index("  char_profile: windows")
    assert "Windows/Samba" in lines[i - 1], "the comment must travel with its setting"


def test_migrate_leaves_settings_that_did_not_move(tmp_path):
    out = _migrate(tmp_path, "common:\n  source_dir: /incoming\n"
                             "details:\n  char_profile: linux\n")
    assert "source_dir: /incoming" in out


def test_migrate_writes_a_backup(tmp_path):
    _migrate(tmp_path, "details:\n  char_profile: windows\n")
    assert (tmp_path / "config.yaml.bak").exists()


def test_migrate_leaves_an_already_migrated_file_alone(tmp_path, capsys):
    body = "naming:\n  char_profile: windows\n"
    out = _migrate(tmp_path, body)
    assert out == body
    assert "needs no changes" in capsys.readouterr().out
    assert not (tmp_path / "config.yaml.bak").exists()


def test_a_migrated_config_loads_without_moved_key_warnings(tmp_path, caplog):
    from massmusictagger.core.tagger_config import TaggerConfig
    _migrate(tmp_path, "details:\n  char_profile: windows\n"
                       "  image_policy: prefer_larger\n"
                       "  source_action: move\n"
                       "  split_discs: false\n")
    with caplog.at_level("WARNING"):
        TaggerConfig(str(tmp_path / "config.yaml"))
    assert "moved to" not in caplog.text
    assert "was removed" not in caplog.text


# ── --new-config writes the rule tables, commented out ───────────────────────

def test_new_config_writes_the_rule_tables(tmp_path):
    """They were not written at all, so nobody could see the rules.

    "I can't see in configuration where it is defined" is a fair complaint
    about a file that decides whether a release is filed as DM or Digital
    Media.
    """
    from massmusictagger.core.tagger_config import write_new_config
    written, _ = write_new_config(str(tmp_path))
    names = {os.path.basename(p) for p in written}
    assert {'format_codes.yaml', 'char_substitutions.yaml',
            'source_hints.yaml'} <= names


def test_the_written_tables_override_nothing(tmp_path):
    """Entirely commented out, so the packaged table is still in force."""
    import yaml as _yaml
    from massmusictagger.core.tagger_config import write_new_config
    write_new_config(str(tmp_path))
    for name in ('format_codes.yaml', 'char_substitutions.yaml',
                 'source_hints.yaml'):
        parsed = _yaml.safe_load((tmp_path / name).read_text(encoding='utf-8'))
        assert parsed is None, f'{name} should be inert until edited'


def test_the_written_table_says_what_it_is(tmp_path):
    from massmusictagger.core.tagger_config import write_new_config
    write_new_config(str(tmp_path))
    text = (tmp_path / 'format_codes.yaml').read_text(encoding='utf-8')
    assert 'merged over the packaged table' in text
    assert 'delete' in text.lower(), 'say how to go back'


def test_uncommenting_one_entry_overrides_only_that_entry(tmp_path):
    """The property that makes shipping a copy safe.

    A full live copy used to freeze the whole table: change one abbreviation
    and you lost vinyl_sizes, the quantity rules, and every later addition.
    """
    from massmusictagger.core.tagger_config import write_new_config
    from massmusictagger.core.naming.formatcodes import (
        load_format_codes, compute_format_code)
    write_new_config(str(tmp_path))
    path = tmp_path / 'format_codes.yaml'
    text = path.read_text(encoding='utf-8')
    text = text.replace('# base_formats:', 'base_formats:', 1)
    text = text.replace('#   Cassette:   MC', '  Cassette:   TAPE', 1)
    path.write_text(text, encoding='utf-8')

    rules = load_format_codes(str(path))
    assert compute_format_code('Cassette', [], 1, rules) == 'TAPE'
    assert compute_format_code('CD', [], 1, rules) == 'CD'
    assert compute_format_code('Digital Media', [], 1, rules) == 'DM'
    assert 'vinyl_sizes' in rules


def test_an_existing_table_is_never_clobbered(tmp_path):
    from massmusictagger.core.tagger_config import write_new_config
    (tmp_path / 'format_codes.yaml').write_text('# mine\n', encoding='utf-8')
    written, skipped = write_new_config(str(tmp_path))
    assert str(tmp_path / 'format_codes.yaml') in skipped
    assert (tmp_path / 'format_codes.yaml').read_text(encoding='utf-8') == '# mine\n'


# ── --migrate-config retires deprecated keys ─────────────────────────────────

def test_migrate_comments_out_a_deprecated_key(tmp_path):
    out = _migrate(tmp_path, 'naming:\n  format_codes: conf/format_codes.yaml\n')
    assert '# format_codes: conf/format_codes.yaml' in out
    assert '\n  format_codes:' not in out


def test_migrate_explains_why(tmp_path):
    out = _migrate(tmp_path, 'naming:\n  format_codes: conf/format_codes.yaml\n')
    assert 'found beside config.yaml' in out


def test_a_key_that_moves_into_deprecation_is_retired_not_moved(tmp_path):
    """details.char_substitutions moved to [naming] and is deprecated there.

    Moving it live would only make it warn from its new home.
    """
    out = _migrate(tmp_path,
                   'details:\n  char_substitutions: conf/char_substitutions.yaml\n')
    assert '# char_substitutions: conf/char_substitutions.yaml' in out
    assert '\n  char_substitutions:' not in out


def test_a_migrated_config_loads_with_no_warnings_at_all(tmp_path, caplog):
    from massmusictagger.core.tagger_config import TaggerConfig
    _migrate(tmp_path,
             'details:\n'
             '  char_profile: windows\n'
             '  char_substitutions: conf/char_substitutions.yaml\n'
             '  format_codes: conf/format_codes.yaml\n'
             '  source_hints_file: conf/source_hints.yaml\n'
             '  split_discs: false\n')
    with caplog.at_level('WARNING'):
        TaggerConfig(str(tmp_path / 'config.yaml'))
    assert caplog.text.strip() == '', f'still warns: {caplog.text}'


def test_migrating_twice_is_a_no_op(tmp_path, capsys):
    body = 'naming:\n  format_codes: conf/format_codes.yaml\n'
    _migrate(tmp_path, body)
    capsys.readouterr()
    from massmusictagger import __main__ as mmt_main

    class _Opts:
        migrate_config = str(tmp_path)

    class _Parser:
        @staticmethod
        def error(msg):
            raise AssertionError(msg)

    mmt_main._migrate_config(_Parser(), _Opts())
    assert 'needs no changes' in capsys.readouterr().out


# ── --annotate-config ────────────────────────────────────────────────────────
#
# A configuration carried forward for years holds the right settings and none
# of the explanation: the comments were in the sample it was first copied
# from, and nothing has put them back since.

def _annotate(tmp_path, body):
    from massmusictagger import __main__ as mmt_main
    (tmp_path / "config.yaml").write_text(body, encoding="utf-8")

    class _Opts:
        annotate_config = str(tmp_path)

    class _Parser:
        @staticmethod
        def error(msg):
            raise AssertionError(msg)

    mmt_main._annotate_config(_Parser(), _Opts())
    return (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_annotate_keeps_every_value(tmp_path):
    import yaml as _yaml
    body = ("common:\n  source_dir: /incoming\n  dest_dir: /sorted\n"
            "naming:\n  char_profile: windows\n"
            "artwork:\n  image_policy: prefer_larger\n")
    before = _yaml.safe_load(body)
    after = _yaml.safe_load(_annotate(tmp_path, body))
    assert after == before


def test_annotate_adds_the_comments(tmp_path):
    body = "naming:\n  char_profile: windows\n"
    out = _annotate(tmp_path, body)
    assert out.count('#') > body.count('#') + 10


def test_annotate_never_adds_a_setting(tmp_path):
    """The sample carries live lines for things a user may have left unset.

    Its user_agent line would pin a value that is otherwise derived from the
    running version -- writing it in would silently start applying it.
    """
    import yaml as _yaml
    body = "common:\n  source_dir: /incoming\n"
    after = _yaml.safe_load(_annotate(tmp_path, body))
    assert set(after['common']) == {'source_dir'}
    assert 'user_agent' not in after['common']


def test_an_unset_setting_appears_commented_out(tmp_path):
    """Documented, but not applied."""
    out = _annotate(tmp_path, "common:\n  source_dir: /incoming\n")
    assert '# user_agent' in out


def test_annotate_preserves_a_list_value(tmp_path):
    import yaml as _yaml
    body = ("source:\n  priority:\n    - discogs\n    - musicbrainz\n")
    after = _yaml.safe_load(_annotate(tmp_path, body))
    assert after['source']['priority'] == ['discogs', 'musicbrainz']


def test_annotate_keeps_a_setting_the_sample_does_not_know(tmp_path):
    import yaml as _yaml
    body = "common:\n  source_dir: /incoming\nmine:\n  something: 42\n"
    after = _yaml.safe_load(_annotate(tmp_path, body))
    assert after['mine']['something'] == 42


def test_annotate_writes_a_backup(tmp_path):
    _annotate(tmp_path, "naming:\n  char_profile: windows\n")
    assert (tmp_path / "config.yaml.bak").exists()


def test_annotate_is_stable(tmp_path):
    """Running it twice changes nothing the second time."""
    body = "naming:\n  char_profile: windows\n"
    once = _annotate(tmp_path, body)
    twice = _annotate(tmp_path, once)
    assert twice == once


def test_the_sample_does_not_pin_the_user_agent(tmp_path):
    """A fresh configuration must not freeze a derived value.

    The sample wrote user_agent live, so --new-config pinned every new
    configuration to whatever literal it happened to carry -- which said
    2.0.0 for two major versions.
    """
    import yaml as _yaml
    from massmusictagger.core.tagger_config import write_new_config
    write_new_config(str(tmp_path))
    fresh = _yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert 'user_agent' not in (fresh.get('common') or {})


def test_a_fresh_config_reports_the_running_version(tmp_path):
    from massmusictagger.core.tagger_config import write_new_config, TaggerConfig
    from massmusictagger import __version__
    write_new_config(str(tmp_path))
    cfg = TaggerConfig(str(tmp_path / "config.yaml"))
    assert __version__ in cfg.get('common', 'user_agent')


def test_the_safety_net_catches_a_gained_setting():
    """_settings_lost is the check that runs before anything is written.

    The rebuild already avoids adding settings, so this exercises the net
    itself rather than the mechanism -- it is what would stop a future change
    to the rebuild from quietly writing a value in.
    """
    from massmusictagger.__main__ import _settings_lost
    before = {'common': {'source_dir': '/in'}}
    after = {'common': {'source_dir': '/in', 'user_agent': 'pinned'}}
    assert _settings_lost(before, after) == [
        ('common', 'user_agent', None, 'pinned')]


def test_the_safety_net_catches_a_lost_setting():
    from massmusictagger.__main__ import _settings_lost
    assert _settings_lost({'common': {'source_dir': '/in'}}, {'common': {}}) == [
        ('common', 'source_dir', '/in', None)]


def test_the_safety_net_catches_a_changed_value():
    from massmusictagger.__main__ import _settings_lost
    assert _settings_lost({'naming': {'char_profile': 'windows'}},
                          {'naming': {'char_profile': 'linux'}}) == [
        ('naming', 'char_profile', 'windows', 'linux')]


def test_the_safety_net_passes_an_identical_config():
    from massmusictagger.__main__ import _settings_lost
    same = {'common': {'source_dir': '/in'}, 'naming': {'char_profile': 'linux'}}
    assert _settings_lost(same, dict(same)) == []
