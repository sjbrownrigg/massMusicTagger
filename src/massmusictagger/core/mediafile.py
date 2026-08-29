"""
Extends mediafile.MediaFile with Discogs- and MusicBrainz-specific tags and
re-exports it as the single import point for the rest of the codebase.

All custom fields are registered once at import time via MediaFile.add_field().
The guard against double-registration means this module is safe to import
from multiple places and in tests.

Tag name conventions used here:
  Vorbis/FLAC   — ALLCAPS_WITH_UNDERSCORES  (de-facto standard)
  MP3 TXXX      — 'Description String'       (Picard-compatible)
  MP4 freeform  — '----:com.apple.iTunes:KEY'
  ASF/WMA       — 'WM/KeyName'
"""
from mediafile import (
    MediaFile,
    MediaField,
    MP3DescStorageStyle,
    MP4StorageStyle,
    StorageStyle,
    ASFStorageStyle,
)

__all__ = ['MediaFile']


def _add(name, descriptor):
    """Register a custom field only if it hasn't been added already."""
    if name not in MediaFile.__dict__:
        MediaFile.add_field(name, descriptor)


# ---------------------------------------------------------------------------
# Discogs release identity
# ---------------------------------------------------------------------------

_add('discogs_id', MediaField(
    MP3DescStorageStyle('DiscogsReleaseId'),
    MP4StorageStyle('----:com.apple.iTunes:DISCOGS_RELEASE_ID'),
    StorageStyle('DISCOGSID'),
    ASFStorageStyle('DT/Release Id'),
))

_add('discogs_release_url', MediaField(
    MP3DescStorageStyle('DISCOGS_RELEASE_URL'),
    MP4StorageStyle('----:com.apple.iTunes:DISCOGS_RELEASE_URL'),
    StorageStyle('URL_DISCOGS_RELEASE_SITE'),
    ASFStorageStyle('WM/DiscogsReleaseUrl'),
))

# ---------------------------------------------------------------------------
# Alternative source IDs (used when source.name != discogs in config)
# ---------------------------------------------------------------------------

_add('amg_id', MediaField(
    MP3DescStorageStyle('AMGID'),
    MP4StorageStyle('----:com.apple.iTunes:AMG_ID'),
    StorageStyle('AMGID'),
    ASFStorageStyle('DT/AmgId'),
))

# ---------------------------------------------------------------------------
# Discogs release metadata
# ---------------------------------------------------------------------------

_add('discogs_release_status', MediaField(
    MP3DescStorageStyle('DISCOGS_RELEASE_STATUS'),
    MP4StorageStyle('----:com.apple.iTunes:DISCOGS_RELEASE_STATUS'),
    StorageStyle('DISCOGS_RELEASE_STATUS'),
    ASFStorageStyle('WM/DiscogsReleaseStatus'),
))

_add('barcode', MediaField(
    MP3DescStorageStyle('BARCODE'),
    MP4StorageStyle('----:com.apple.iTunes:BARCODE'),
    StorageStyle('BARCODE'),
    ASFStorageStyle('WM/Barcode'),
))

# ---------------------------------------------------------------------------
# MusicBrainz identifiers
#
# Field names follow the Picard / beets convention so files tagged here are
# recognised by MusicBrainz Picard and other MusicBrainz-aware software.
# ---------------------------------------------------------------------------

_add('musicbrainz_releaseid', MediaField(
    # MP3: TXXX with description 'MusicBrainz Release Id' (Picard standard)
    MP3DescStorageStyle('MusicBrainz Release Id'),
    MP4StorageStyle('----:com.apple.iTunes:MusicBrainz Release Id'),
    StorageStyle('MUSICBRAINZ_ALBUMID'),
    ASFStorageStyle('MusicBrainz/Album Id'),
))

_add('musicbrainz_trackid', MediaField(
    # Stores the MusicBrainz Recording MBID (Picard: MUSICBRAINZ_TRACKID).
    # Note: Picard also writes a separate MUSICBRAINZ_RELEASETRACKID; we use
    # the recording MBID here as it is more universally useful for deduplication.
    MP3DescStorageStyle('MusicBrainz Recording Id'),
    MP4StorageStyle('----:com.apple.iTunes:MusicBrainz Recording Id'),
    StorageStyle('MUSICBRAINZ_TRACKID'),
    ASFStorageStyle('MusicBrainz/Track Id'),
))

_add('isrc', MediaField(
    # ISRC (International Standard Recording Code) — ISO 3901.
    # MP3: TXXX frame with 'ISRC' description (widely supported).
    # Vorbis: ISRC tag (de-facto standard).
    MP3DescStorageStyle('ISRC'),
    MP4StorageStyle('----:com.apple.iTunes:ISRC'),
    StorageStyle('ISRC'),
    ASFStorageStyle('WM/ISRC'),
))

# ---------------------------------------------------------------------------
# Release classification (Picard-compatible tag names)
# ---------------------------------------------------------------------------

_add('releasetype', MediaField(
    # Primary release type: Album, Single, EP, Broadcast, Other
    # Matches MusicBrainz Picard's RELEASETYPE tag.
    MP3DescStorageStyle('MusicBrainz Release Group Type'),
    MP4StorageStyle('----:com.apple.iTunes:MusicBrainz Release Group Type'),
    StorageStyle('RELEASETYPE'),
    ASFStorageStyle('MusicBrainz/Release Group Type'),
))

_add('musicbrainz_releasegroupid', MediaField(
    # MusicBrainz Release Group MBID — groups all editions of the same album.
    # Picard: MUSICBRAINZ_RELEASEGROUPID
    MP3DescStorageStyle('MusicBrainz Release Group Id'),
    MP4StorageStyle('----:com.apple.iTunes:MusicBrainz Release Group Id'),
    StorageStyle('MUSICBRAINZ_RELEASEGROUPID'),
    ASFStorageStyle('MusicBrainz/Release Group Id'),
))

# ---------------------------------------------------------------------------
# Tagger provenance
# ---------------------------------------------------------------------------

_add('tagger_source', MediaField(
    # Which metadata source was used to tag this file.
    # Values: 'discogs', 'musicbrainz', 'existing_tags'
    MP3DescStorageStyle('TAGGER_SOURCE'),
    MP4StorageStyle('----:com.apple.iTunes:TAGGER_SOURCE'),
    StorageStyle('TAGGER_SOURCE'),
    ASFStorageStyle('WM/TaggerSource'),
))

# ---------------------------------------------------------------------------
# Legacy / compatibility fields
# ---------------------------------------------------------------------------

_add('freedb_id', MediaField(
    MP3DescStorageStyle('DiscId'),
    MP4StorageStyle('----:com.apple.iTunes:DISCID'),
    StorageStyle('DISCID'),
    ASFStorageStyle('DT/discid'),
))
