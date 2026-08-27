# -*- coding: utf-8 -*-
"""massMusicTagger — multi-source mass audio tagger built on discogstagger3."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("massmusictagger")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0+unknown"

# Declared at import so discogstagger3's config validator recognises
# massMusicTagger's own settings rather than reporting them as typos.
from massmusictagger import config_schema as _config_schema

_config_schema.register()

__all__ = ["__version__"]
