# -*- coding: utf-8 -*-
"""Where massMusicTagger finds its configuration.

Mirrors discogstagger3's ``discogstagger.roots``, with massMusicTagger's own
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
# Mako templates and the tagging rule tables belong to discogstagger3 and ship
# inside that package; they are never copied into a config directory.
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

    pattern = os.path.join(config_root_dir, CREDENTIALS_DIRNAME, "*.yaml")
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
