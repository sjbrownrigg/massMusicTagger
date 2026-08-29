"""The contract every metadata source presents.

Satisfied at the source_factory boundary rather than by the source classes
themselves: both album classes take the raw release in their constructor and
expose `map(self)`, and LocalDiscogsConnector takes an extra source_dir on
fetch_release, so neither can declare SourceMapper/SourceConnector directly.
The factory adapters reconcile that, and test_discogs_search.py checks the
objects it returns actually satisfy these signatures.

SourceSearch is the exception: DiscogsSearch and MBSearch both implement
search(sourcedir) directly, so the cascade treats them identically.

Each source (Discogs, MusicBrainz, …) provides concrete implementations of:
  SourceConnector — fetches raw release data from the remote service or cache
  SourceSearch    — locates a release ID for a given source directory
  SourceMapper    — converts raw release data into the shared Album model
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from massmusictagger.core.album import Album


class SourceConnector(ABC):
    """Fetches and caches raw release objects from a metadata source."""

    @abstractmethod
    def fetch_release(self, release_id: str) -> Any:
        """Return a raw release object (source-specific type)."""
        ...

    @abstractmethod
    def cache_release(self, release: Any) -> None:
        """Persist a fetched release to disk so the next run is instant."""
        ...

    @abstractmethod
    def fetch_image(self, dest_path: str, image_url: str) -> None:
        """Download an image URL and write it to dest_path."""
        ...


class SourceSearch(ABC):
    """Locates a release ID for an audio source directory."""

    @abstractmethod
    def search(self, sourcedir: str) -> Optional[str]:
        """Return a release ID string, or None when no confident match is found.

        Implementations should log the tier that produced the result and the
        confidence score so that audit logs are informative.
        """
        ...


class SourceMapper(ABC):
    """Converts a raw source-specific release into the shared Album model."""

    @abstractmethod
    def map(self, raw_release: Any) -> Album:
        """Return a fully-populated Album/Disc/Track tree ready for tagging."""
        ...
