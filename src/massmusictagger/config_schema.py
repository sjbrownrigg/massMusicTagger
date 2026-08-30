# -*- coding: utf-8 -*-
"""The configuration schema: every key, its default, and whether it is required.

Absorbed from discogstagger3 and merged with massMusicTagger's own keys, so
one table now answers "where did this value come from".

This table is the single source of truth for discogstagger3's defaults.  It
exists because defaults used to live in ``conf/config_sample.yaml``, which was
loaded as a silent baseline underneath the user's own config -- so a setting
could take effect without appearing anywhere in the file the user was reading,
and a typo in a config path fell back to those defaults instead of failing.

Now:

* Defaults live here, in code, where they can be read in one place.
* ``conf/config_sample.yaml`` is reference documentation only.  It is never
  loaded at runtime, and ``test_config_schema.py`` checks the two agree.
* A config file that does not exist is an error, not a fallback.
* Keys the schema does not know about are reported, so typos surface.

Values are strings because the config is flattened into a RawConfigParser,
whose values are strings.  An empty string reads back as None via
``TaggerConfig.get``, matching a key that was left blank.
"""

import logging

logger = logging.getLogger(__name__)


def _default_user_agent() -> str:
    """How massMusicTagger introduces itself to Discogs.

    Absorbing discogstagger3's schema brought its user agent along with it, so
    massMusicTagger presented itself to Discogs as discogstagger/4.0 -- another
    program, at a version it does not have. Discogs registers applications by
    name and issues one personal token at a time across them, so a client that
    misidentifies itself is not a cosmetic problem.

    Built from __version__ rather than written out, because the copy that was
    written out went stale: the live configuration still said 1.0 two major
    versions later.
    """
    from massmusictagger import __version__
    return (f'massMusicTagger/{__version__} '
            f'+https://github.com/sjbrownrigg/massMusicTagger')


#: Recomputed per release, so it can never be compared against a literal.
COMPUTED = frozenset({('common', 'user_agent')})

#: Keys whose sample value is an example to be replaced, not a default. The
#: schema default is empty and the run fails loudly if the setting is needed
#: and unset -- showing "" in the sample would document nothing.
PLACEHOLDERS = frozenset({
    # MusicBrainz requires a user agent that identifies you and gives them a
    # contact, so the sample shows the shape rather than an empty string.
    # The credentials proper stay blank in their samples on purpose -- they
    # come from the environment -- so they are not listed here.
    ('musicbrainz', 'user_agent'),
})


class ConfigError(Exception):
    """Raised when a configuration is missing something it cannot run without."""


# Keys with no safe default -- the user must set them deliberately.
#
# Deliberately empty. Every setting here has a default that is safe to apply,
# and the settings that genuinely must not be guessed -- dest_dir, whether
# originals are kept -- are supplied by the caller or the command line, so
# requiring them in the file would break embedders.
#
# What actually protects the user is not a required-key list:
#   * a config file that does not exist is an error, not a silent fallback
#   * defaults are visible here rather than hidden in a loaded sample
#   * unknown keys are reported, so typos surface
#
# The mechanism stays because a required key is a plausible future need.
REQUIRED = frozenset()


# Keys that still work but are no longer needed. Known, so they do not draw an
# "unknown key" warning on top of their own deprecation warning, and not
# expected to appear in config_sample.yaml.
#
# common.formats_file: formats.ini is found beside config.yaml. See roots.LAYOUT.
DEPRECATED = frozenset({
    ('naming', 'use_lower_filenames'),
    ('naming', 'format_codes'),
    ('naming', 'char_substitutions'),
    ('source', 'source_hints_file'),
    ('musicbrainz', 'source_hints_file'),
    ('common', 'formats_file'),
    ('file-formatting', 'image'),
})

#: Why a deprecated key no longer does anything, said at load time.
#:
#: Keys warned about elsewhere are absent here, so nobody is told twice:
#: common.formats_file warns from TaggerConfig.resource() when it is actually
#: used to resolve a path, which is more specific than anything sayable here.
DEPRECATION_NOTES = {
    ('naming', 'char_substitutions'):
        'char_substitutions.yaml is found beside config.yaml, so nothing '
        'needs to declare where it is. The key still works and warns; a path '
        'that does not resolve now falls back to the packaged table instead '
        'of applying no substitutions at all.',
    ('source', 'source_hints_file'):
        'source_hints.yaml is found beside config.yaml, so nothing needs to '
        'declare where it is. The key still works and warns.',
    ('musicbrainz', 'source_hints_file'):
        'source hints are shared by every source, not just MusicBrainz, and '
        'source_hints.yaml is found beside config.yaml. The key still works '
        'and warns.',
    ('naming', 'format_codes'):
        'format_codes.yaml is found beside config.yaml, so nothing needs to '
        'declare where it is, and what it finds is merged over the bundled '
        'table rather than replacing it. The key still works and warns; a '
        'path that does not resolve now falls back to the bundled table '
        'instead of turning every format abbreviation off.',
    ('naming', 'use_lower_filenames'):
        'it sets all six case keys at once. Use case_dir, case_song, '
        'case_disc, case_va_song, case_nfo and case_m3u instead, which can '
        'differ from each other.',
    ('common', 'formats_file'):
        'formats.ini is found beside config.yaml in the configuration '
        'directory, so nothing needs to declare where it is. The value is '
        'still honoured, but remove the key and move the file next to '
        'config.yaml instead.',
    ('file-formatting', 'image'):
        'artwork is named by a fixed convention now -- the Cover Art '
        'Archive vocabulary (front, back, booklet, liner, medium, tray, '
        'spine, obi, sticker, poster, ...) for typed images, cover for '
        'untyped album art, and image-01, image-02 for anything the source '
        'did not type. Remove the setting; it has no effect.',
}



#: Settings that moved section in 3.0.0. The value is NOT carried over -- a
#: config still using the old name has that setting switched off -- but naming
#: the new home turns "Unknown config key details.char_profile" into something
#: a person can act on. [details] had become a 28-key catch-all covering
#: filename casing, artwork policy, archiving and tag handling, which was the
#: single biggest reason the configuration read as confusing.
MOVED = {
    ('details', 'case_dir'): 'naming',
    ('details', 'case_disc'): 'naming',
    ('details', 'case_m3u'): 'naming',
    ('details', 'case_nfo'): 'naming',
    ('details', 'case_song'): 'naming',
    ('details', 'case_va_song'): 'naming',
    ('details', 'char_profile'): 'naming',
    ('details', 'char_substitutions'): 'naming',
    ('details', 'control_replacement'): 'naming',
    ('details', 'copy_other_files'): 'archiving',
    ('details', 'done_file'): 'archiving',
    ('details', 'download_only_cover'): 'artwork',
    ('details', 'embed_coverart'): 'artwork',
    ('details', 'format_codes'): 'naming',
    ('details', 'image_policy'): 'artwork',
    ('details', 'image_source'): 'artwork',
    ('details', 'join_artists'): 'naming',
    ('details', 'keep_original'): 'archiving',
    ('details', 'keep_tags'): 'tags',
    ('details', 'path_sep_replacement'): 'naming',
    ('details', 'source_action'): 'archiving',
    ('details', 'source_archive_dir'): 'archiving',
    ('details', 'source_hints_file'): 'source',
    ('details', 'source_move_template'): 'archiving',
    ('details', 'use_anv'): 'naming',
    ('details', 'use_folder_jpg'): 'artwork',
    ('details', 'variousartists'): 'naming',
}

#: Settings removed in 3.0.0 because nothing read them. Each loaded without
#: complaint and did nothing, which is worse than not existing.
REMOVED = {
    ('details', 'split_discs'):  'nothing read it; multi-disc layouts are '
                                 'detected from the directory tree',
    ('tags',    'encoder'):      'nothing read it; the encoder is chosen per '
                                 'target format in [conversion]',
    ('logging', 'config_file'):  'nothing read it; logging is configured by '
                                 'logging.level and logging.log_file',
    ('source',  'amg'):          'AllMusic is not a source; an id.txt names '
                                 'its source directly now',
    ('source',  'discogs'):      'the source-to-tag-field mapping is gone; '
                                 'an id.txt reads <source>_id directly',
    ('source',  'local'):        'the source-to-tag-field mapping is gone; '
                                 'an id.txt reads <source>_id directly',
}

# Every known key, with the default applied when the user omits it.
DEFAULTS = {

    # ── [common] ──────────────────────────────────────────────────────
    ('common', 'user_agent'): _default_user_agent(),
    ('common', 'source_dir'): '',
    ('common', 'dest_dir'): '',
    ('common', 'watch_poll_interval'): '30',

    ('archiving', 'keep_original'): 'True',
    ('artwork', 'embed_coverart'): 'True',
    ('artwork', 'image_policy'): 'prefer_larger',
    ('naming', 'char_profile'): 'linux',
    ('naming', 'path_sep_replacement'): '',
    ('naming', 'control_replacement'): '',
    ('tags', 'keep_tags'): 'freedb_id',
    ('naming', 'case_dir'): 'lower',
    ('naming', 'case_disc'): 'lower',
    ('naming', 'case_song'): 'lower',
    ('naming', 'case_va_song'): 'lower',
    ('naming', 'case_nfo'): 'lower',
    ('naming', 'case_m3u'): 'lower',
    ('artwork', 'use_folder_jpg'): 'True',
    ('naming', 'use_anv'): 'True',
    ('naming', 'join_artists'): '',
    ('archiving', 'copy_other_files'): 'False',
    ('archiving', 'done_file'): 'dt.done',
    ('naming', 'variousartists'): 'Various',
    ('artwork', 'download_only_cover'): 'True',

    # ── [batch] ───────────────────────────────────────────────────────
    ('batch', 'id_file'): 'id.txt',
    ('batch', 'searchdiscogs'): 'False',
    ('batch', 'tracklength_tolerance'): '5.0',
    ('batch', 'title_similarity_threshold'): '60',

    # ── [cue] ─────────────────────────────────────────────────────────
    ('cue', 'cue_done_dir'): '.cue',
    ('cue', 'parse_cue_files'): 'False',

    # ── [m4a] ─────────────────────────────────────────────────────────
    ('m4a', 'convert_m4a_files'): 'False',
    ('m4a', 'alac_action'): 'convert_to_flac',
    ('m4a', 'aac_action'): 'keep',
    ('m4a', 'm4a_done_dir'): '.m4a',

    # ── [conversion] ──────────────────────────────────────────────────
    ('conversion', 'flac_compression_level'): '8',
    ('conversion', 'mp3_quality'): '2',
    ('conversion', 'ogg_quality'): '5',

    # ── [tags] ────────────────────────────────────────────────────────

    # ── [replaygain] ──────────────────────────────────────────────────
    ('replaygain', 'add_tags'): 'True',
    ('replaygain', 'application'): 'r128gain',
    ('replaygain', 'thread_count'): '2',

    # ── [cache] ───────────────────────────────────────────────────────
    ('cache', 'directory'): '',

    # ── [source] ──────────────────────────────────────────────────────
    ('source', 'name'): 'discogs',

    # ── [discogs] ─────────────────────────────────────────────────────
    ('discogs', 'user_token'): '',
    ('discogs', 'skip_auth'): 'False',
    ('discogs', 'consumer_key'): '',
    ('discogs', 'consumer_secret'): '',

    # ── [logging] ─────────────────────────────────────────────────────
    ('logging', 'level'): '20',
    ('logging', 'log_file'): '',

    # ── massMusicTagger's own settings ────────────────────────────────
    # These had no defaults: the schema lived in the other package, so
    # massMusicTagger registered its key names without being able to give
    # them values. Every call site then carried its own idea of the
    # fallback -- `cfg.get(...) if cfg.has_option(...) else 'auto'` -- which
    # is the hidden-baseline problem again, spread across the code instead
    # of a sample file. Each value below is the fallback that call site was
    # already applying, so behaviour is unchanged.
    ('batch', 'audit_log'): '',
    ('batch', 'workers'): '1',
    ('batch', 'cpu_jobs'): '1',
    ('batch', 'staging_dir'): '',
    ('artwork', 'image_source'): 'auto',
    ('artwork', 'artist_image'): 'False',
    ('archiving', 'source_action'): 'done_file',
    ('archiving', 'source_archive_dir'): '',
    ('archiving', 'source_move_template'): '%source%/%albumartist%/%current_folder%',
    ('musicbrainz', 'acoustid_api_key'): '',
    ('musicbrainz', 'acoustid_submitter_key'): '',
    ('musicbrainz', 'acoustid_early'): 'False',
    ('musicbrainz', 'caa_request_delay'): '0.5',
    # The three disk caches. They were read by the connector with defaults of
    # their own, and documented, but never declared -- so setting one worked
    # and was reported as a typo in the same breath.
    ('musicbrainz', 'cache_metadata'): 'True',
    ('musicbrainz', 'cache_images'): 'True',
    ('musicbrainz', 'cache_search'): 'True',
    ('musicbrainz', 'cache_directory'): '',
    ('musicbrainz', 'user_agent'): '',
    # Written as a YAML list in the sample, which flattens to this string.
    # _get_priority accepts either that or a comma-separated form.
    ('source', 'priority'): "['discogs', 'musicbrainz', 'existing_tags']",
}


# Kept as a name for the keys that were once registered separately, so the
# tests that check the sample documents them can still say what they mean.
# They now carry defaults like everything else; this is a view, not a
# second class of key.
MMT_KEYS = tuple(sorted(k for k in DEFAULTS if k in {
    ('batch', 'audit_log'), ('batch', 'workers'),
    ('artwork', 'image_source'), ('archiving', 'source_action'),
    ('archiving', 'source_archive_dir'), ('source', 'source_hints_file'),
    ('archiving', 'source_move_template'), ('logging', 'log_file'),
    ('musicbrainz', 'acoustid_api_key'), ('musicbrainz', 'acoustid_early'),
    ('musicbrainz', 'acoustid_submitter_key'),
    ('musicbrainz', 'caa_request_delay'), ('musicbrainz', 'cache_directory'),
    ('musicbrainz', 'user_agent'), ('source', 'priority'),
}))




KNOWN_SECTIONS = (frozenset(s for s, _ in DEFAULTS)
                  | frozenset(s for s, _ in REQUIRED)
                  | frozenset(s for s, _ in DEPRECATED))

# Sections that hold free-form user content rather than known settings, and so
# cannot be validated key-by-key:
#
#   file-formatting   format strings, from the formats INI
#   custom-variables  user-defined format string variables -- names are the
#                     user's to choose, which is the whole point
#   suppress_tags     bare tag names, stored as valueless keys
#   character_exceptions  per-character substitutions keyed by the character
#   media_description     Discogs description -> abbreviation mappings
FREEFORM_SECTIONS = frozenset({
    'file-formatting',
    'extra_configs',   # deprecated list of paths, not settings
    'custom-variables',
    'suppress_tags',
    'character_exceptions',
    'media_description',
})


def apply_defaults(config):
    """Fill in any known key the loaded config did not set.

    Returns the list of (section, key) pairs that were defaulted, so callers
    can log them at debug level.
    """
    applied = []
    for (section, key), default in DEFAULTS.items():
        if not config.has_section(section):
            config.add_section(section)
        if not config.has_option(section, key):
            config.set(section, key, default)
            applied.append((section, key))
    return applied


def validate(config, source=None):
    """Check a loaded config for missing required keys and unknown keys.

    Missing required keys raise ConfigError naming every one of them at once,
    so a config is fixed in a single pass rather than one error per run.
    Unknown keys only warn: they are usually typos, but a forward-compatible
    config written for a newer version should not be fatal.
    """
    where = f" in {source}" if source else ""

    missing = [
        (section, key) for section, key in sorted(REQUIRED)
        if not (config.has_section(section) and config.has_option(section, key))
        or not (config.get(section, key) or "").strip()
    ]
    if missing:
        listed = "\n".join(f"  {s}.{k}" for s, k in missing)
        raise ConfigError(
            f"Configuration{where} is missing required settings:\n{listed}\n"
            f"  See the annotated reference in conf/config_sample.yaml."
        )

    for (section, key), note in DEPRECATION_NOTES.items():
        if not (config.has_section(section) and config.has_option(section, key)):
            continue
        # A deprecated key left empty is doing nothing, and saying so is
        # noise -- the sample config carries several of them precisely so a
        # reader can see they exist. Warn about the ones with a value, which
        # are the ones still having an effect.
        try:
            value = (config.get(section, key, raw=True) or '').strip()
        except Exception:
            value = ''
        if value:
            logger.warning('%s.%s is deprecated%s: %s',
                           section, key, where, note)

    known = set(DEFAULTS) | set(REQUIRED) | set(DEPRECATED)
    known_sections = KNOWN_SECTIONS
    for section in config.sections():
        if section in FREEFORM_SECTIONS:
            continue
        if section not in known_sections:
            # A section every one of whose keys moved -- [details] in 3.0.0 --
            # is not a typo, and saying so helps nobody. Fall through so each
            # key gets told where it went.
            retired = {sec for sec, _ in MOVED} | {sec for sec, _ in REMOVED}
            if section not in retired:
                logger.warning(
                    "Unknown config section [%s]%s -- ignored. Check for a "
                    "typo.", section, where)
                continue
        for key, _ in config.items(section):
            if (section, key) not in known:
                if (section, key) in MOVED:
                    logger.warning(
                        "%s.%s moved to [%s] in 3.0.0%s -- the setting is "
                        "NOT being applied. Move it to %s.%s.",
                        section, key, MOVED[(section, key)], where,
                        MOVED[(section, key)], key)
                elif (section, key) in REMOVED:
                    logger.warning(
                        "%s.%s was removed in 3.0.0%s -- %s. Delete it.",
                        section, key, where, REMOVED[(section, key)])
                else:
                    logger.warning(
                        "Unknown config key %s.%s%s -- ignored. Check for a "
                        "typo.", section, key, where)
