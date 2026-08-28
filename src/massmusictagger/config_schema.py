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
    ('common', 'formats_file'),
})


# Every known key, with the default applied when the user omits it.
DEFAULTS = {

    # ── [common] ──────────────────────────────────────────────────────
    ('common', 'user_agent'): 'discogstagger/4.0 +https://github.com/sjbrownrigg/discogstagger',
    ('common', 'source_dir'): '',
    ('common', 'dest_dir'): '',
    ('common', 'watch_poll_interval'): '30',

    # ── [details] ─────────────────────────────────────────────────────
    ('details', 'keep_original'): 'True',
    ('details', 'embed_coverart'): 'True',
    ('details', 'image_policy'): 'prefer_larger',
    ('details', 'char_profile'): 'linux',
    ('details', 'char_substitutions'): '',
    ('details', 'format_codes'): '',
    ('details', 'path_sep_replacement'): '',
    ('details', 'control_replacement'): '',
    ('details', 'keep_tags'): 'freedb_id',
    ('details', 'case_dir'): 'lower',
    ('details', 'case_disc'): 'lower',
    ('details', 'case_song'): 'lower',
    ('details', 'case_va_song'): 'lower',
    ('details', 'case_nfo'): 'lower',
    ('details', 'case_m3u'): 'lower',
    ('details', 'use_folder_jpg'): 'True',
    ('details', 'use_anv'): 'True',
    ('details', 'join_artists'): '',
    ('details', 'split_discs'): 'False',
    ('details', 'copy_other_files'): 'False',
    ('details', 'done_file'): 'dt.done',
    ('details', 'variousartists'): 'Various',
    ('details', 'download_only_cover'): 'True',

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
    ('tags', 'encoder'): '',

    # ── [replaygain] ──────────────────────────────────────────────────
    ('replaygain', 'add_tags'): 'True',
    ('replaygain', 'application'): 'r128gain',

    # ── [cache] ───────────────────────────────────────────────────────
    ('cache', 'directory'): '',

    # ── [source] ──────────────────────────────────────────────────────
    ('source', 'discogs'): 'discogs_id',
    ('source', 'amg'): 'amg_id',
    ('source', 'local'): 'discogs_id',
    ('source', 'name'): 'discogs',

    # ── [discogs] ─────────────────────────────────────────────────────
    ('discogs', 'user_token'): '',
    ('discogs', 'skip_auth'): 'False',
    ('discogs', 'consumer_key'): '',
    ('discogs', 'consumer_secret'): '',

    # ── [logging] ─────────────────────────────────────────────────────
    ('logging', 'level'): '20',
    ('logging', 'config_file'): '',
}


# massMusicTagger's own settings -- source priority, MusicBrainz, concurrency.
# These were registered at import time when the schema lived in a separate
# package; with one package they are simply declared.
#
# A key added to conf/config_sample.yaml must be added here too, or it will be
# reported as unknown at runtime.
MMT_KEYS = (
    ('batch',       'audit_log'),
    ('batch',       'workers'),
    ('details',     'image_source'),
    ('details',     'source_action'),
    ('details',     'source_archive_dir'),
    ('details',     'source_hints_file'),
    ('details',     'source_move_template'),
    ('logging',     'log_file'),
    ('musicbrainz', 'acoustid_api_key'),
    # Reserved: the second argument to acoustid.submit(). Nothing reads it yet
    # -- massMusicTagger only calls acoustid.match(), which takes the
    # application key alone.
    #
    # Named for its role rather than its type because AcoustID calls both
    # credentials an "API key": the page at /api-key hands you this one, while
    # acoustid_api_key above is the application key from the app registration.
    # "submitter" collides with neither.
    ('musicbrainz', 'acoustid_submitter_key'),
    ('musicbrainz', 'acoustid_early'),
    ('musicbrainz', 'caa_request_delay'),
    ('musicbrainz', 'cache_directory'),
    ('musicbrainz', 'user_agent'),
    ('source',      'priority'),
)

_EXTRA_KNOWN = set(MMT_KEYS)


def register_freeform_sections(sections):
    """Declare additional sections whose keys are not checked individually.

    For sections holding free-form or structural content rather than known
    settings -- massMusicTagger's deprecated ``extra_configs`` is a list of
    file paths, so its "keys" are paths and checking them as setting names
    reports every one as a typo.
    """
    global FREEFORM_SECTIONS
    FREEFORM_SECTIONS = FREEFORM_SECTIONS | frozenset(str(s) for s in sections)


def register_known_keys(keys):
    """Declare additional (section, key) pairs as valid.

    Call once at import time from the embedding package. Unknown-key checking
    then covers the combined set, so genuine typos in an embedder's own
    settings are still caught.
    """
    for section, key in keys:
        _EXTRA_KNOWN.add((str(section), str(key)))


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

    known = set(DEFAULTS) | set(REQUIRED) | set(DEPRECATED) | _EXTRA_KNOWN
    known_sections = KNOWN_SECTIONS | frozenset(s for s, _ in _EXTRA_KNOWN)
    for section in config.sections():
        if section in FREEFORM_SECTIONS:
            continue
        if section not in known_sections:
            logger.warning(
                "Unknown config section [%s]%s -- ignored. Check for a typo.",
                section, where)
            continue
        for key, _ in config.items(section):
            if (section, key) not in known:
                logger.warning(
                    "Unknown config key %s.%s%s -- ignored. Check for a typo.",
                    section, key, where)
