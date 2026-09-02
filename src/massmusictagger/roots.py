# -*- coding: utf-8 -*-
"""Where massMusicTagger finds its configuration.

Mirrors discogstagger3's ``massmusictagger.roots``, with massMusicTagger's own
environment variable and application directory. The reasoning is the same:

A configuration is a **directory**, not a file. ``config.yaml``, ``formats.ini``
and ``credentials/`` resolve relative to each other, so the configuration moves
as a unit and the directory is what gets selected.

The previous behaviour walked up from ``__file__`` looking for a ``conf/``
directory at a repo root, which only worked from a source checkout, and fell
back to loading ``config_sample.yaml`` when it found nothing -- so a pip-installed
copy silently ran on sample settings.
"""

import glob
import logging
import os

logger = logging.getLogger(__name__)

APP_NAME = "massmusictagger"

#: Shipped defaults that travel inside the package.
PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))
BUNDLED_CONF = os.path.join(PACKAGE_ROOT, "conf")
CONFIG_FILENAME = "config.yaml"

# The fixed layout inside a configuration directory. As with discogstagger3,
# it holds what the *user* owns and nothing else:
#
#   config.yaml            settings
#   formats.ini            file and directory naming (discovered by dt3)
#   credentials/*.yaml     API tokens, one file per source
#
# The tagging rule tables ship inside the package as defaults, and Mako
# templates ship there as the fallback for anything a configuration does not
# provide its own copy of. All of them are overridable from a config directory.
CREDENTIALS_DIRNAME = "credentials"


def config_dir():
    """Return the directory massMusicTagger looks for its configuration in.

    ``MMT_CONFIG_DIR`` wins when set -- the container points it at the mounted
    ``/config``. Otherwise ``$XDG_CONFIG_HOME/massmusictagger``, falling back
    to ``~/.config/massmusictagger``.
    """
    explicit = os.environ.get("MMT_CONFIG_DIR")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))

    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(os.path.expanduser(xdg), APP_NAME)


def discover_config():
    """Return the path to config.yaml, or None when there isn't one."""
    path = os.path.join(config_dir(), CONFIG_FILENAME)
    return path if os.path.exists(path) else None


def discover_credentials(config_root_dir):
    """Return every credentials file in *config_root_dir*, sorted by name.

    Any ``credentials/*.yaml`` is loaded. Nothing has to be listed in
    config.yaml, which is what ``extra_configs`` used to be for: with a single
    configuration directory there was nowhere else for these files to be, so
    naming them individually was a list to keep in sync for no benefit.
    """
    if not config_root_dir:
        return []

    # glob.escape on the directory, not the pattern: [ and ] are character
    # classes to glob, so a configuration directory whose path contains them
    # -- "/mnt/nas/[2024] config" -- matches nothing and every credential is
    # silently skipped, leaving the run unauthenticated with no error. This
    # project puts brackets in directory names as a matter of convention.
    pattern = os.path.join(glob.escape(config_root_dir),
                           CREDENTIALS_DIRNAME, "*.yaml")
    return sorted(glob.glob(pattern))


def cache_root():
    """Return the directory for massMusicTagger's cached API responses.

    ``MMT_CACHE_DIR`` wins when set -- the container points it at a mounted
    volume. Otherwise ``$XDG_CACHE_HOME/massmusictagger``, falling back to
    ``~/.cache/massmusictagger``.

    The MusicBrainz cache previously defaulted to a literal
    ``~/.cache/massmusictagger/mb``. In the container the mmt user's home is
    /app, which is not writable, so the run died on startup -- the same class
    of failure as a path resolved against the working directory, just rooted
    at HOME instead.
    """
    explicit = os.environ.get("MMT_CACHE_DIR")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))

    xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")
    return os.path.join(os.path.expanduser(xdg), APP_NAME)


# ── Package resources ────────────────────────────────────────────────────────
# Mako templates for .nfo/.m3u. Absorbed from discogstagger3 along with the
# rest of the tagging core, so they now ship inside massMusicTagger.
BUNDLED_TEMPLATES = os.path.join(PACKAGE_ROOT, "templates")


# ── Config-relative resolution ───────────────────────────────────────────────

# The fixed layout inside a configuration directory.
#
# The configuration directory holds what the *user* owns, and nothing else:
#
#   config.yaml    the entry point -- their settings
#   formats.ini    their file and directory naming
#
# The rule tables -- format_codes.yaml, char_substitutions.yaml,
# source_hints.yaml -- are found here too when present. They are not written
# by --new-config: the packaged table is the default, so it keeps improving
# with each upgrade instead of freezing at whatever version was installed the
# day the config was made. Drop a file here to override, and what it contains
# is merged over the packaged one, so changing a single line neither discards
# the rest of the table nor opts out of later additions to it.
#
# They live here rather than only inside the package because they decide how a
# release is *named* -- whether it is filed as DM or Digital Media -- and a
# rule that decides that should be somewhere its owner can read it.
#
# Mako templates are found in a templates/ directory beside config.yaml, and
# fall back to the packaged ones. Mako searches its lookup directories in
# order, so this shadows *per file*: copy info.txt out to change the .nfo and
# the .m3u still comes from the package, and keeps improving with it.
#
# formats.ini is optional: absent means the bundled format strings are used.
#
# This replaced a set of config keys that named paths to these files. With one
# configuration directory there was nothing for them to point at but the
# obvious place, so they were four more things to get wrong for no benefit.
LAYOUT = {
    "formats": "formats.ini",
    # The format-code rule table. Bundled by default so it keeps improving
    # with each upgrade, but discoverable here because it decides how a
    # release is *named* -- "Digital Media" or "DM" -- and anything that
    # decides that belongs where the user can see it. A file here is merged
    # over the bundled one, so overriding a single abbreviation does not
    # discard the rest of the table.
    "format_codes": "format_codes.yaml",
    "char_substitutions": "char_substitutions.yaml",
    "source_hints": "source_hints.yaml",
    # How a multi-artist credit is read when filing -- which join phrases mark
    # a guest ("feat.") and which mark equal billing ("/"). A judgement call
    # that decides which folder an album lands in, so it belongs where the user
    # can change it. Merged over the bundled table like the others.
    "artist_joins": "artist_joins.yaml",
    # How much the medium a release was issued on counts when ranking
    # candidates. Here because the right weights depend on the collection: a
    # library of needle drops wants vinyl preferred at 16/44.1, not penalised,
    # and only its owner knows that. Merged over the bundled table like the
    # others.
    "medium_preference": "medium_preference.yaml",
}


#: Where a configuration keeps its own Mako templates.
TEMPLATES_DIRNAME = "templates"


def template_dirs(config_root_dir):
    """Template lookup directories, most specific first.

    A user's templates/ shadows the packaged one file by file, so taking a
    copy of one template does not freeze the others.
    """
    dirs = []
    if config_root_dir:
        user = os.path.join(config_root_dir, TEMPLATES_DIRNAME)
        if os.path.isdir(user):
            dirs.append(user)
    dirs.append(BUNDLED_TEMPLATES)
    return dirs


def discover(config_root_dir, what):
    """Return the path to *what* inside *config_root_dir*, if it is there.

    *what* is a key of :data:`LAYOUT`. Returns None when the config directory
    does not provide that file, meaning the bundled default should be used.
    """
    try:
        relative = LAYOUT[what]
    except KeyError:
        raise ValueError(
            f"Unknown config resource {what!r}; expected one of "
            f"{sorted(LAYOUT)}") from None

    if not config_root_dir:
        return None

    path = os.path.join(config_root_dir, relative)
    return path if os.path.exists(path) else None


def config_root(config_file):
    """Return the directory *config_file* lives in, or None when there isn't one.

    Used as the base for paths a config file names.
    """
    if not config_file:
        return None
    return os.path.dirname(os.path.abspath(config_file))


def resolve_config_path(value, base_dir, key_name="path"):
    """Resolve *value*, a path read from a config file, to an absolute path.

    Resolution order:

    1. ``~`` expansion, and absolute paths returned as-is.
    2. Relative to *base_dir* -- the directory of the config file naming it.
    3. Relative to the working directory, which is the historic behaviour.
       This still works but emits a deprecation warning naming both paths
       tried, so the fix is obvious from the log.

    Returns None when *value* is empty.  Returns the step-2 candidate when
    nothing exists, so callers raise a "not found" error naming the path the
    user is meant to create rather than the legacy one.
    """
    if not value:
        return None

    expanded = os.path.expanduser(value)

    if os.path.isabs(expanded):
        return expanded

    preferred = (os.path.join(base_dir, expanded)
                 if base_dir else os.path.abspath(expanded))
    if os.path.exists(preferred):
        return preferred

    legacy = os.path.abspath(expanded)
    if legacy != preferred and os.path.exists(legacy):
        logger.warning(
            "%s resolved relative to the working directory, which is "
            "deprecated: %s\n"
            "  Move it beside the config file (expected at %s), or make the "
            "value an absolute path. The working-directory fallback will be "
            "removed in a future release.",
            key_name, legacy, preferred)
        return legacy

    return preferred


# ── State root ───────────────────────────────────────────────────────────────

_LEGACY_STATE_FILENAMES = (".token",)


# ── State root ───────────────────────────────────────────────────────────────

_LEGACY_STATE_FILENAMES = (".token",)


def state_root():
    """Return the directory for mutable runtime state, creating it if needed.

    MMT_STATE_DIR wins, then DISCOGSTAGGER_STATE_DIR -- which deployments
    already set and which keeps working unchanged -- then the XDG state
    directory. Never the working directory.
    """
    explicit = (os.environ.get("MMT_STATE_DIR")
                or os.environ.get("DISCOGSTAGGER_STATE_DIR"))
    if explicit:
        base = os.path.expanduser(explicit)
    else:
        xdg = os.environ.get("XDG_STATE_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "state")
        base = os.path.join(os.path.expanduser(xdg), APP_NAME)
    try:
        os.makedirs(base, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create state directory %s: %s", base, exc)
    return base


def state_path(filename):
    """Return the path to *filename* within the state root.

    When the file is absent there but a legacy copy exists in the working
    directory, the legacy path is returned so an existing OAuth token keeps
    working instead of silently forcing re-authentication.
    """
    current = os.path.join(state_root(), filename)
    if os.path.exists(current):
        return current

    if filename in _LEGACY_STATE_FILENAMES:
        legacy = os.path.join(os.getcwd(), filename)
        if os.path.exists(legacy):
            logger.warning(
                "Using %s from the working directory. This location is "
                "deprecated; move it to %s (or set DISCOGSTAGGER_STATE_DIR).",
                legacy, current)
            return legacy

    return current

