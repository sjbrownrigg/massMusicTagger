# -*- coding: utf-8 -*-
import errno
import json
import os
import re
import logging
import shutil
import struct
from shutil import copy2, copystat, Error
from datetime import timedelta, date as date_type



from mako.template import Template
from mako.lookup import TemplateLookup

from massmusictagger.sources.discogs.album import DiscogsAlbum
from massmusictagger.core.album import Album, Disc, Track
from massmusictagger.core.naming.stringformatting import StringFormatting

from massmusictagger.core.mediafile import MediaFile
from massmusictagger.core.naming.pathutils import resolve_path
from massmusictagger import roots
from massmusictagger.core.naming.charmap import build_map, apply_substitutions, strip_invalid
from massmusictagger.core.naming.formatcodes import (
    load_format_codes, compute_format_code, compute_edition, extract_vinyl_size,
)
from massmusictagger.sources.discogs.utils import VARIOUS_ARTIST_NAMES, parse_extraartists, natural_sort_key, AUDIO_EXTENSIONS, TAGGABLE_EXTENSIONS, ignored_source_dirs

logger = logging.getLogger(__name__)

# Bundled Mako templates ship inside the package, so they resolve from the
# installed location rather than the current working directory.
# See massmusictagger.roots for the roots this program resolves against.
_BUNDLED_TEMPLATES = roots.BUNDLED_TEMPLATES


def _image_dimensions(data: bytes):
    """Return (width, height) in pixels for JPEG or PNG data, or None on failure.

    Tries Pillow first (handles all formats and corrupt files gracefully).
    Falls back to direct header parsing so no hard dependency is needed:
      PNG  — width/height at fixed offsets 16–23 in the IHDR chunk
      JPEG — scans for a Start Of Frame marker (C0–C3, C5–C7, C9–CB, CD–CF)
    """
    try:
        from PIL import Image as PILImage
        import io
        img = PILImage.open(io.BytesIO(data))
        img.verify()   # catches truncated files before we trust the size
        img = PILImage.open(io.BytesIO(data))   # reopen after verify()
        return img.size  # (width, height)
    except ImportError:
        pass   # Pillow not installed — fall through to header parsing
    except Exception:
        return None

    # PNG: IHDR chunk at offset 8, width at 16-19, height at 20-23
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        try:
            w, h = struct.unpack('>II', data[16:24])
            return (w, h)
        except struct.error:
            return None

    # JPEG: scan segments until a Start Of Frame marker is found
    if data[:2] == b'\xff\xd8':
        sof_markers = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        try:
            i = 2
            while i + 3 < len(data):
                # Skip any 0xFF padding bytes
                while i < len(data) and data[i] == 0xFF:
                    i += 1
                if i >= len(data):
                    break
                marker = data[i]
                i += 1
                if marker in sof_markers:
                    if i + 8 <= len(data):
                        # SOF payload: 2-byte length, 1-byte precision, 2-byte height, 2-byte width
                        h, w = struct.unpack('>HH', data[i + 3: i + 7])
                        return (w, h)
                    break
                # Skip this segment: length field includes its own 2 bytes
                if i + 2 > len(data):
                    break
                seg_len = struct.unpack('>H', data[i: i + 2])[0]
                i += seg_len
        except (struct.error, IndexError):
            return None

    return None


def _merge_indexed_disc_sub_tracks(tracks: list) -> 'list | None':
    """Merge consecutive letter-indexed Track objects into single entries.

    Mirror of merge_indexed_subtracks() from discogs_utils, but operating on
    Track objects rather than flat dicts.  Used as a tagger-side fallback when
    the file count doesn't match the disc track list because Discogs has split
    a single track into lettered positions (13a, 13b, 13c).  Shares the
    grouping rule with discogs_utils via group_by_subtrack_position() so the
    {parent}{letter} pattern is only defined once.

    The merged track's title joins all sub-track titles with ' / ' (e.g.
    'Corrupt / (silence) / Untitled'). If that would make the title too long,
    only the first sub-track's title is kept and the rest are appended to
    track.notes instead, following the same comments-tag convention used for
    Pattern B sub-track movements in discogsalbum.py.

    Returns a new list (renumbered sequentially) if any merging occurred, or
    None when no mergeable groups are found.
    """
    from massmusictagger.sources.discogs.utils import combine_subtrack_titles, group_by_subtrack_position

    groups = group_by_subtrack_position(
        tracks, lambda t: t.real_tracknumber or str(t.tracknumber))
    if groups is None:
        return None

    merged = []
    for key, group in groups:
        if key.startswith('sub:') and len(group) > 1:
            primary = group[0]
            primary.real_tracknumber = key[4:]  # strip 'sub:'
            title, extra = combine_subtrack_titles([t.title for t in group])
            primary.title = title
            if extra:
                primary.notes = '\r\n'.join(filter(None, [primary.notes, extra]))
            merged.append(primary)
        else:
            merged.extend(group)

    for i, track in enumerate(merged, start=1):
        track.tracknumber = i

    return merged


class TaggerError(Exception):
    """ A central exception for all errors happening during the tagging
    """
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)

class TagHandler(object):
    """ Uses the album (taggerutils) and tags all given files using the given
        tags (album)
    """

    def __init__(self, album, tagger_config):
        self.album = album
        self.config = tagger_config

        self.keep_tags = self.config.get("details", "keep_tags")
        self.user_agent = self.config.get("common", "user_agent")
        self.variousartists = self.config.get("details", "variousartists")
        self._suppressed = tagger_config.suppressed_tags
        if self._suppressed:
            logger.info('Suppressed tags (not written to metadata): %s',
                        ', '.join(sorted(self._suppressed)))

    def tag_album(self):
        """Tag all tracks in the album, working on the destination copies.

        copy_files() must have run first so the destination files exist.
        Tagging the copies (not the originals) ensures source files are
        never modified.
        """
        for disc in self.album.discs:
            track_dir = (os.path.join(self.album.target_dir, disc.target_dir)
                         if disc.target_dir else self.album.target_dir)
            for track in disc.tracks:
                self.tag_single_track(track_dir, track)

    def tag_single_track(self, target_folder, track):
        logger.debug("target_folder: %s", target_folder)

        metadata = MediaFile(os.path.join(target_folder, track.new_file))

        # read already existing (and still wanted) properties
        keepTags = {}
        if self.keep_tags is not None:
            for name in self.keep_tags.split(","):
                name = name.strip()
                val = getattr(metadata, name, None)
                if val:
                    keepTags[name] = val
                    logger.debug("keeping tag %s=%r", name, val)

        metadata.delete()
        self.album.codec = metadata.type

        sup = self._suppressed  # shorthand

        def _set(attr, value):
            """Write tag unless it is in the suppressed set."""
            if attr not in sup:
                setattr(metadata, attr, value)

        # ── Album-level tags ─────────────────────────────────────────────────
        _set('album', self.album.title)

        # Composer: prefer track-level Discogs extra artist credits, then album-level.
        # Falls back to nothing (the album artist is not a reliable composer proxy).
        _track_credits = parse_extraartists(getattr(track, 'extraartists', None) or [])
        _album_credits = parse_extraartists(getattr(self.album, 'extraartists', None) or [])
        _composers = _track_credits['composers'] or _album_credits['composers']
        if _composers:
            _set('composer', ', '.join(_composers))

        if any(a.lower() in VARIOUS_ARTIST_NAMES for a in self.album.artists) and self.album.is_compilation:
            _set('albumartist', self.variousartists)
            _set('albumartists', [self.variousartists])
        else:
            _set('albumartist', self.album.artist)
            _set('albumartists', self.album.artists)

        _set('albumartist_sort', self.album.sort_artist)
        _set('label', self.album.labels[0] if self.album.labels else '')
        # year is always a string; mediafile converts it to int internally.
        # Guard against empty string (e.g. MB releases with no date) which
        # would cause int('') → ValueError inside mediafile.
        if self.album.year:
            _set('year', self.album.year)
        if self.album.release_date:
            _set('date', _parse_date(self.album.release_date))
        _set('country', self.album.country)
        _set('catalognum', self.album.catnumbers[0] if self.album.catnumbers else '')
        _set('grouping', ', '.join(self.album.styles or []))
        _set('genres', self.album.genres)

        # Write the release source ID to the appropriate tag.
        # For Discogs releases: write to the configured id_tag (discogs_id by default).
        # For MusicBrainz releases: write the MBID to musicbrainz_releaseid instead.
        # For existing_tags albums: skip — do not overwrite with empty values.
        _source = getattr(self.album, 'source', 'discogs') or 'discogs'
        if _source == 'musicbrainz':
            _set('musicbrainz_releaseid', str(self.album.id))
        elif _source != 'existing_tags':
            if self.config.id_tag_name not in sup:
                setattr(metadata, self.config.id_tag_name, self.album.id)

        _set('discogs_release_url', self.album.url)

        if getattr(self.album, 'status', ''):
            _set('discogs_release_status', self.album.status)
        if getattr(self.album, 'barcode', ''):
            _set('barcode', self.album.barcode)

        # Provenance: which metadata source was used to tag this file
        _source_name = getattr(self.album, 'source', '') or ''
        if _source_name:
            _set('tagger_source', _source_name)

        # Release type classification (MB-style, inferred for Discogs releases)
        _release_type = getattr(self.album, 'release_type', None) or ''
        if _release_type:
            _set('releasetype', _release_type)

        # Release group MBID — set for MB releases; for Discogs, master_id is the
        # Discogs master release integer ID (different type, not written here).
        if _source == 'musicbrainz':
            _rg_id = getattr(self.album, 'master_id', None)
            if _rg_id:
                _set('musicbrainz_releasegroupid', str(_rg_id))

        _set('disctitle', track.discsubtitle)
        _set('disc', track.discnumber)
        _set('disctotal', len(self.album.discs))
        _set('media', self.album.media)

        if self.album.is_compilation and 'comp' not in sup:
            metadata.comp = True

        if 'comments' not in sup:
            if track.notes:
                metadata.comments = '\r\n'.join((track.notes, self.album.notes))
            else:
                metadata.comments = self.album.notes

        # ── Extra tags from [tags] config section ────────────────────────────
        # Use TaggerConfig.get() so empty values (encoder=) are treated as None
        for name in self.config.configured_tags:
            value = self.config.get("tags", name)
            if name not in sup and value is not None:
                setattr(metadata, name, value)

        # ── Track-level tags ─────────────────────────────────────────────────
        _set('title', track.title)
        _set('artist', track.artist)
        _set('artists', track.artists)
        _set('artist_sort', track.sort_artist)

        if 'track' not in sup:
            if track.real_tracknumber is not None:
                metadata.track = track.real_tracknumber
            else:
                metadata.track = track.tracknumber

        _set('tracktotal', len(self.album.disc(track.discnumber).tracks))

        # ── MusicBrainz track-level identifiers ──────────────────────────────
        # Written whenever present on the track object regardless of source,
        # so that manually enriched or cross-source albums retain their ISRCs.
        _isrc = getattr(track, 'isrc', None)
        if _isrc:
            _set('isrc', _isrc)
        _mbid = getattr(track, 'mbid', None)
        if _mbid:
            _set('musicbrainz_trackid', _mbid)

        # ── Restore kept tags (always wins over suppression) ─────────────────
        for name, value in keepTags.items():
            setattr(metadata, name, value)

        metadata.save()

class FileHandler(object):
    """ this class contains all file handling tasks for the tagger,
        it loops over the album and discs (see copy_files) to copy
        the files for each album. This could be done in the TagHandler
        class, but this would mean a too strong relationship between
        FileHandling and Tagging, which is not as nice for testing and
        for future extensability.
    """


    def __init__(self, album, tagger_config):
        self.config = tagger_config
        self.album = album
        self.cue_done_dir = self.config.get('cue', 'cue_done_dir')
        self.rg_process = self.config.getboolean('replaygain', 'add_tags')
        self.rg_application = self.config.get('replaygain', 'application')


    def create_done_file(self):
        # could be, that the directory does not exist anymore ;-)
        if os.path.exists(self.album.sourcedir):
            done_file = os.path.join(self.album.sourcedir, self.config.get("details", "done_file"))
            from pathlib import Path; Path(done_file).touch()

    def create_album_dir(self):
        if not os.path.exists(self.album.target_dir):
            os.makedirs(self.album.target_dir, exist_ok=True)

    def copy_files(self):
        """
            copy an album and all its files to the new location, rename those
            files if necessary
        """
        logger.debug("copy_files: %s → %s", self.album.sourcedir, self.album.target_dir)

        for disc in self.album.discs:
            if disc.sourcedir is not None:
                source_folder = os.path.join(self.album.sourcedir, disc.sourcedir)
            else:
                source_folder = self.album.sourcedir

            if disc.target_dir is not None:
                target_folder = os.path.join(self.album.target_dir, disc.target_dir)
            else:
                target_folder = self.album.target_dir

            copy_needed = False
            if not source_folder == target_folder:
                if not os.path.exists(target_folder):
                    os.makedirs(target_folder, exist_ok=True)
                copy_needed = True

            if copy_needed:
                logger.debug("disc %d: %s → %s (%d track(s))",
                             disc.discnumber, source_folder, target_folder,
                             len(disc.tracks))

            for track in disc.tracks:
                source_file = os.path.join(source_folder, track.orig_file)
                target_file = os.path.join(target_folder, track.new_file)

                if copy_needed and not os.path.exists(target_file):
                    if not os.path.exists(source_file):
                        logger.error("Source file does not exist: %s", source_file)
                    shutil.copyfile(source_file, target_file)

    def remove_source_dir(self):
        """
            remove source directory, if configured as such (see config option
            details:keep_original)
        """
        keep_original = self.config.getboolean("details", "keep_original")
        source_dir = self.album.sourcedir

        logger.debug("keep_original: %s", keep_original)
        logger.debug("going to remove directory....")
        if not keep_original:
            logger.warning("Deleting source directory '%s'", source_dir)
            shutil.rmtree(source_dir)

    def copy_other_files(self):
        # copy "other files" on request
        copy_other_files = self.config.getboolean("details", "copy_other_files")

        if copy_other_files:
            logger.info("copying files from source directory")

            if not os.path.exists(self.album.target_dir):
                os.makedirs(self.album.target_dir, exist_ok=True)

            copy_files = self.album.copy_files

            if copy_files is not None:

                # Exclude cue done dir and the done_file marker — the done marker
                # belongs only in the source directory and must never appear in the
                # tagged output.  Previously extf was just cue_done_dir (a string),
                # so f not in extf was a substring check that accidentally worked.
                # Now use an explicit set for clarity and to add done_file.
                _done_file = self.config.get('details', 'done_file')
                _skip = ignored_source_dirs(self.config) | {_done_file}
                copy_files[:] = [f for f in copy_files if f not in _skip]

                for fname in copy_files:
                    if os.path.isdir(os.path.join(self.album.sourcedir, fname)):
                        copytree_multi(os.path.join(self.album.sourcedir, fname), os.path.join(self.album.target_dir, fname))
                    else:
                        shutil.copyfile(os.path.join(self.album.sourcedir, fname), os.path.join(self.album.target_dir, fname))

            for disc in self.album.discs:
                copy_files = disc.copy_files

                _done_file = self.config.get('details', 'done_file')
                _skip = ignored_source_dirs(self.config) | {_done_file}
                copy_files[:] = [f for f in copy_files if f not in _skip]

                for fname in copy_files:
                    if not fname.endswith(".m3u"):
                        if disc.sourcedir is not None:
                            source_path = os.path.join(self.album.sourcedir, disc.sourcedir)
                        else:
                            source_path = self.album.sourcedir

                        if disc.target_dir is not None:
                            target_path = os.path.join(self.album.target_dir, disc.target_dir)
                        else:
                            target_path = self.album.target_dir

                        if not os.path.exists(target_path):
                            os.makedirs(target_path, exist_ok=True)

                        if os.path.isdir(os.path.join(source_path, fname)):
                            copytree_multi(os.path.join(source_path, fname), os.path.join(target_path, fname))
                        else:
                            shutil.copyfile(os.path.join(source_path, fname), os.path.join(target_path, fname))

    def _first_track_file(self):
        """Return the absolute path to the first audio track in the target directory."""
        for disc in self.album.discs:
            for track in disc.tracks:
                track_dir = (os.path.join(self.album.target_dir, disc.target_dir)
                             if disc.target_dir else self.album.target_dir)
                return os.path.join(track_dir, track.new_file)
        return None

    def _best_local_cover(self):
        """Find the best existing cover image in the target directory or embedded in tracks.

        Checks named image files first (front.jpg, folder.jpg, cover.jpg, image-01.jpg),
        then falls back to embedded art in the first audio file.

        Returns (source_label, data_bytes, (width, height)) or (None, None, None).
        """
        image_format = self.config.get("file-formatting", "image")
        candidates = [
            os.path.join(self.album.target_dir, 'front.jpg'),
            os.path.join(self.album.target_dir, 'folder.jpg'),
            os.path.join(self.album.target_dir, 'cover.jpg'),
            os.path.join(self.album.target_dir, '{}-01.jpg'.format(image_format)),
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                    dims = _image_dimensions(data)
                    if dims:
                        return (os.path.basename(path), data, dims)
                except OSError:
                    pass

        # Fall back to embedded art in the first track
        first = self._first_track_file()
        if first and os.path.exists(first):
            try:
                mf = MediaFile(first)
                if mf.images:
                    data = mf.images[0].data
                    dims = _image_dimensions(data)
                    if dims:
                        return ('embedded', data, dims)
            except Exception:
                pass

        return (None, None, None)

    def _should_skip_front_cover(self, discogs_image, local_dims, policy):
        """Return True if the Discogs front cover download should be skipped.

        discogs_image — an Attachment from album.attachments; its dimensions
                        may be None when the source did not report them
        local_dims    — (width, height) of the best existing local cover, or None
        policy        — 'always' | 'prefer_existing' | 'prefer_larger'
        """
        if not local_dims:
            return False

        if policy == 'prefer_existing':
            logger.info('Skipping Discogs front cover (prefer_existing; local: %dx%d)',
                        *local_dims)
            return True

        if policy == 'prefer_larger':
            dims = discogs_image.dimensions
            disc_w, disc_h = dims if dims else (0, 0)
            if not dims:
                logger.info('Discogs image dimensions unknown — downloading anyway')
                return False
            if (local_dims[0] * local_dims[1]) >= (disc_w * disc_h):
                logger.info('Keeping local cover %dx%d (Discogs is %dx%d)',
                            local_dims[0], local_dims[1], disc_w, disc_h)
                return True
            logger.info('Discogs cover larger (%dx%d vs local %dx%d) — downloading',
                        disc_w, disc_h, local_dims[0], local_dims[1])
            return False

        return False

    def get_images(self, conn_mgr):
        """Download and store release images from Discogs.

        Discogs provides two image types:
          'primary'   — the front cover (named front.jpg, or folder.jpg when
                        use_folder_jpg=True for media-player compatibility)
          'secondary' — all other images (back, media, booklet, etc. — Discogs
                        does not distinguish further); named image-01.jpg, etc.

        The image_policy config key controls front-cover behaviour:
          always          — always download and replace (original behaviour)
          prefer_existing — skip download if any local cover already exists
          prefer_larger   — download only when the Discogs image is larger than
                            the existing local cover (file or embedded art);
                            falls back to downloading when dimensions are unknown
        """
        if not self.album.attachments:
            return

        image_format = self.config.get("file-formatting", "image")
        use_folder_jpg = self.config.getboolean("details", "use_folder_jpg")
        download_only_cover = self.config.getboolean("details", "download_only_cover")
        image_policy = self.config.get("details", "image_policy")

        self.create_album_dir()

        # Evaluate existing local cover once — used for all front-cover policy decisions
        local_source, _, local_dims = self._best_local_cover()
        if local_dims:
            logger.info('Existing local cover (%s): %dx%d px', local_source, *local_dims)

        secondary_no = 0
        for image in self.album.attachments:
            image_url = image.url
            is_front = image.is_front

            if is_front and image_policy != 'always':
                if self._should_skip_front_cover(image, local_dims, image_policy):
                    if download_only_cover:
                        break
                    continue

            logger.debug("Downloading %s image: %s", image.kind, image_url)
            try:
                if is_front:
                    conn_mgr.fetch_image(
                        os.path.join(self.album.target_dir, 'front.jpg'),
                        image_url,
                    )
                    if use_folder_jpg:
                        conn_mgr.fetch_image(
                            os.path.join(self.album.target_dir, 'folder.jpg'),
                            image_url,
                        )
                    if download_only_cover:
                        break
                else:
                    secondary_no += 1
                    picture_name = '{}-{:02d}.jpg'.format(image_format, secondary_no)
                    conn_mgr.fetch_image(
                        os.path.join(self.album.target_dir, picture_name),
                        image_url,
                    )
            except Exception as e:
                logger.error("Unable to download image '%s': %s", image_url, e)

    def embed_coverart_album(self):
        """Embed the front cover art into all album files.

        Uses mediafile's Image API to explicitly tag the image as
        ImageType.front (picture type 3), which is what music players and
        tagging tools expect.
        """
        from mediafile import Image, ImageType

        if not self.config.getboolean("details", "embed_coverart"):
            return

        # Search for the front cover in order of preference
        image_format = self.config.get("file-formatting", "image")
        candidates = [
            os.path.join(self.album.target_dir, 'front.jpg'),
            os.path.join(self.album.target_dir, 'folder.jpg'),
            os.path.join(self.album.target_dir, 'cover.jpg'),
            os.path.join(self.album.target_dir, '{}-01.jpg'.format(image_format)),
        ]
        front_image = next((p for p in candidates if os.path.exists(p)), None)
        if front_image is None:
            logger.debug('No front cover image found to embed')
            return

        with open(front_image, 'rb') as f:
            imgdata = f.read()

        header = imgdata[:4]
        if header[:2] == b'\xff\xd8':
            mime = 'image/jpeg'
        elif header == b'\x89PNG':
            mime = 'image/png'
        else:
            logger.warning('Front cover is not JPEG or PNG; skipping embed')
            return

        cover = Image(data=imgdata, type=ImageType.front)
        logger.info('Embedding front cover art (%s, %d bytes)', mime, len(imgdata))
        for disc in self.album.discs:
            for track in disc.tracks:
                self.embed_coverart_track(disc, track, cover)

    def embed_coverart_track(self, disc, track, cover):
        """Embed cover art into a single track file.

        ``cover`` may be a ``mediafile.Image`` instance (preferred — preserves
        the picture type) or raw ``bytes`` (treated as front cover).
        """
        from mediafile import Image, ImageType

        track_dir = (os.path.join(self.album.target_dir, disc.target_dir)
                     if disc.target_dir else self.album.target_dir)
        track_file = os.path.join(track_dir, track.new_file)
        try:
            if isinstance(cover, bytes):
                cover = Image(data=cover, type=ImageType.front)
            metadata = MediaFile(track_file)
            metadata.images = [cover]
            metadata.save()
        except Exception as e:
            logger.error("Unable to embed image in '%s': %s", track_file, e)

    def add_replay_gain_tags(self):
        """Add ReplayGain tags to all audio files in the album directory.

        Supported applications (configured via [replaygain] application=):
          r128gain  — pip-installable Python wrapper around ffmpeg (recommended)
          loudgain  — standalone C tool (OS dependency)
          metaflac  — part of the flac package; FLAC only (OS dependency)
        """
        if not self.rg_process:
            return

        import subprocess
        from pathlib import Path

        audio_extensions = set(TAGGABLE_EXTENSIONS)
        album_path = Path(self.album.target_dir)

        # Collect all audio files recursively, grouped by extension
        files_by_ext: dict[str, list[str]] = {}
        for f in sorted(album_path.rglob('*')):
            if f.suffix.lower() in audio_extensions:
                files_by_ext.setdefault(f.suffix.lower(), []).append(str(f))

        if not files_by_ext:
            logger.warning('No audio files found for ReplayGain in %s', album_path)
            return

        lg_flags = {
            '.flac': ['-a', '-k', '-s', 'e'],
            '.mp3':  ['-I', '4', '-S', '-L', '-a', '-k', '-s', 'e'],
        }

        for ext, file_paths in files_by_ext.items():
            logger.info('Adding ReplayGain (%s) to %d %s file(s)',
                        self.rg_application, len(file_paths), ext)

            if self.rg_application == 'r128gain':
                cmd = ['r128gain', '-a'] + file_paths
            elif self.rg_application == 'loudgain':
                cmd = ['loudgain'] + lg_flags.get(ext, []) + file_paths
            elif self.rg_application == 'metaflac':
                cmd = ['metaflac', '--add-replay-gain'] + file_paths
            else:
                logger.error('Unknown ReplayGain application: %s', self.rg_application)
                return

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error('ReplayGain failed (exit %d):\n%s',
                             result.returncode, result.stderr.strip())
            else:
                logger.debug('ReplayGain completed for %d file(s)', len(file_paths))


class TaggerUtils(object):
    """ Accepts a destination directory name and discogs release id.
        TaggerUtils returns a the corresponding metadata information, in which
        we can write to disk. The assumption here is that the destination
        direcory contains a single album in a support format (mp3 or flac).

        The class also provides a few methods that create supplimental files,
        relvant to a given album (m3u, nfo file and album art grabber.)"""

    FILE_TYPE = TAGGABLE_EXTENSIONS

    def __init__(self, sourcedir, destdir, tagger_config, album=None):
        self.config = tagger_config

        # ignore directory where old cue files are stashed
        self.cue_done_dir = self.config.get('cue', 'cue_done_dir')

        self.dir_format = self.config.get("file-formatting", "dir")
        self.song_format = self.config.get("file-formatting", "song")
        self.va_song_format = self.config.get("file-formatting", "va_song")
        self.images_format = self.config.get("file-formatting", "image")
        self.m3u_format = self.config.get("file-formatting", "m3u")
        self.nfo_format = self.config.get("file-formatting", "nfo")
        self.disc_folder_name = self.config.get("file-formatting", "discs")

        # Per-format case settings: 'lower', 'upper', or 'preserve'
        self.case_dir     = self.config.get('details', 'case_dir')     or 'lower'
        self.case_disc    = self.config.get('details', 'case_disc')    or 'lower'
        self.case_song    = self.config.get('details', 'case_song')    or 'lower'
        self.case_va_song = self.config.get('details', 'case_va_song') or 'lower'
        self.case_nfo     = self.config.get('details', 'case_nfo')     or 'lower'
        self.case_m3u     = self.config.get('details', 'case_m3u')     or 'lower'

        # Deprecated alias — override all six when present
        try:
            legacy = self.config.getboolean('details', 'use_lower_filenames')
            _override = 'lower' if legacy else 'preserve'
            logger.warning(
                "Config: 'use_lower_filenames' is deprecated — use the "
                "per-format case_dir / case_song / … keys instead"
            )
            self.case_dir = self.case_disc = self.case_song = \
                self.case_va_song = self.case_nfo = self.case_m3u = _override
        except Exception:
            pass

#        self.first_image_name = "folder.jpg"
        self.copy_other_files = self.config.getboolean("details", "copy_other_files")

        # Build the combined substitution map: YAML profile + INI [character_exceptions]
        self.char_exceptions = build_map(tagger_config)

        # What to replace filesystem-invalid characters with (user-configurable)
        try:
            self._path_sep_replacement = self.config.get('details', 'path_sep_replacement') or ''
        except Exception:
            self._path_sep_replacement = ''
        try:
            self._control_replacement = self.config.get('details', 'control_replacement') or ''
        except Exception:
            self._control_replacement = ''

        # Custom variables from [custom-variables] section of the formats INI.
        # Referenced in format strings as %__varname__% (double-underscore).
        # Each value is itself a format string and is expanded inline before
        # the standard %var% substitutions run, so the result of a custom
        # variable may itself contain %format%, $function() calls, etc.
        # Names are case-insensitive (stored lowercase).
        self.custom_variables: dict[str, str] = {}
        try:
            for name, value in self.config.items('custom-variables'):
                if value:
                    self.custom_variables[name.lower()] = value
        except Exception:
            pass

        self.sourcedir = sourcedir
        self.destdir = destdir

        if album is not None:
            self.album = album
        else:
            raise RuntimeError('Cannot tag, no album given')

        # ── Artist display string ─────────────────────────────────────────────
        # Priority: Discogs join text (album._artist_display set by DiscogsAlbum)
        #           → join_artists separator from config (fallback when Discogs
        #             provides no join between multiple artists)
        #           → first individual artist (final fallback via album.artist)
        #
        # albumartists / artists tags always store individual names as arrays,
        # regardless of what is set here.
        _join_sep = self.config.get("details", "join_artists")
        if not self.album._artist_display and len(self.album.artists) > 1 and _join_sep:
            self.album._artist_display = f' {_join_sep} '.join(self.album.artists)
            logger.debug("albumartist: applied join_artists separator %r → %r",
                         _join_sep, self.album._artist_display)

        # Propagate the album display to tracks that inherit album artists.
        # (Tracks with their own Discogs credits are unaffected.)
        for disc in self.album.discs or []:
            for track in disc.tracks:
                if track.artists is self.album.artists:
                    track._artist_display = self.album.artist

        # Compute format_code BEFORE map_format_description() rewrites the
        # descriptions list with abbreviated values from [media_description].
        # format_code needs the original Discogs strings ("Maxi-Single" etc).
        # An explicit escape hatch for tuning the rule table; normally unset,
        # in which case the version bundled in the package is used.
        try:
            _fc_path = tagger_config.resolve_path(
                tagger_config.get('details', 'format_codes'),
                'details.format_codes')
        except Exception:
            _fc_path = None
        _format_codes = load_format_codes(_fc_path)
        _raw_descs = list(self.album.format_description or [])
        self._vinyl_size = extract_vinyl_size(_raw_descs)
        self._format_code = compute_format_code(
            self.album.format or '',
            _raw_descs,
            int(self.album.disctotal or 1),
            _format_codes,
        )
        # format_base: physical medium abbreviation without any quantity prefix.
        # Same as format_code when disctotal=1; strips the D/3x/… prefix otherwise.
        # Use %format_base% in custom variables when you want the medium alone:
        #   medium = %format_base%   → CD, LP, 12″, CDr, file, …
        self._format_base = compute_format_code(
            self.album.format or '',
            _raw_descs,
            1,   # always single-disc to get base only
            _format_codes,
        )
        self._edition = compute_edition(_raw_descs, _format_codes)
        # If structured descriptions didn't yield an edition, try the free-text
        # format.text notes (e.g. "30th Anniversary 2CD Edition") with loose
        # word-set matching, since format info ("2CD") may appear mid-phrase.
        if not self._edition:
            _text_notes = list(getattr(self.album, 'format_text_notes', None) or [])
            if _text_notes:
                self._edition = compute_edition(_text_notes, _format_codes,
                                                loose=True)
        logger.debug('format_code: %s  format_base: %s  edition: %s',
                     self._format_code, self._format_base, self._edition or '(none)')

        self.map_format_description()

        # Warn when a format string references a tag that is suppressed from
        # metadata.  Suppression only affects what is written to the audio file;
        # the Discogs value is still available to format strings for naming, so
        # this is a heads-up rather than a hard error.
        _suppressed = tagger_config.suppressed_tags
        if _suppressed:
            self._warn_suppressed_format_refs(_suppressed)

        self.album.sourcedir = sourcedir
        # Preliminary target directory — technical properties (%codec%,
        # %quality%, %samplerate%, %channels%) are not yet available so any
        # format string that uses them will produce a placeholder value.
        # Callers that use technical tags in the dir format MUST recompute
        # after gather_addional_properties():
        #   tagger_utils.gather_addional_properties()
        #   album.target_dir = tagger_utils.dest_dir_name
        self.album.target_dir = self.dest_dir_name

        logger.debug("album.target_dir (preliminary): %s", self.album.target_dir)

        # Mako templates belong to discogstagger3, not to the user, so they
        # always come from the package. They are not part of a configuration
        # directory and are not copied into one.
        #
        # This was previously TemplateLookup(directories=["templates"]) -- a
        # path relative to the working directory, which resolved only when
        # running from a source checkout and silently produced no .nfo/.m3u
        # anywhere else.
        self.template_lookup = TemplateLookup(directories=[_BUNDLED_TEMPLATES])

    # Maps format string variable names (lowercase, no %) to the MediaFile
    # attribute that would be suppressed.  Only variables that have a direct
    # metadata counterpart need to appear here.
    _FORMAT_VAR_TO_TAG = {
        'album':           'album',
        'album artist':    'albumartist',
        'albumartist':     'albumartist',
        'artist':          'artist',
        'track artist':    'artist',
        'title':           'title',
        'year':            'year',
        'releasedate':     'date',
        'catno':           'catalognum',
        'genre':           'genres',
        'disctitle':       'disctitle',    # canonical (matches MediaFile attr)
        'discsubtitle':    'disctitle',    # alias — matches Vorbis DISCSUBTITLE tag name
        'discnumber':      'disc',
        'disctotal':       'disctotal',   # canonical name (matches MediaFile attr)
        'totaldiscs':      'disctotal',   # deprecated alias — prefer %disctotal%
        'tracknumber':     'track',
        'track number':    'track',
        'trackcount':      'tracktotal',
        'mediatype':       'media',
    }

    def _warn_suppressed_format_refs(self, suppressed: set):
        """Log a warning for each format string variable that maps to a suppressed tag."""
        import re
        formats = filter(None, [
            self.dir_format, self.song_format, self.va_song_format,
            self.m3u_format, self.nfo_format,
        ])
        seen = set()
        for fmt in formats:
            for raw in re.findall(r'%([^%]+)%', fmt):
                key = raw.lower().strip()
                tag = self._FORMAT_VAR_TO_TAG.get(key)
                if tag and tag in suppressed and key not in seen:
                    logger.warning(
                        'Format string uses %%%s%% but tag "%s" is suppressed — '
                        'the Discogs value is still used for naming; only the '
                        'file metadata is suppressed.',
                        raw, tag,
                    )
                    seen.add(key)

    def map_format_description(self):
        """ Gets format desription, and maps to user defined variations,
            e.g. Limited Edition -> ltd
        """
        self.format_mapping = {}
        try:
            self.media_desc_formatting = self.config.items('media_description')
        except Exception:
            self.media_desc_formatting = []

        # get the mapping from config and convert to dict (lowercase keys for matching)
        for i in self.media_desc_formatting:
            self.format_mapping[i[0].lower()] = i[1] if i[1] != '' else None

        for i, desc in enumerate(self.album.format_description):
            if desc.lower() in self.format_mapping:
                if self.format_mapping[desc.lower()] is not None:
                    self.album.format_description[i] = self.format_mapping[desc.lower()]

    def _value_from_tag_format(self, format, discno=1, trackno=1, filetype=".mp3"):
        """ Fill in the used variables using the track information
            Transform all variables and use them in the given format string, make this
            slightly more flexible to be able to add variables easier

            Transfer this via a map.
        """

        property_map = {

            '%album artist%': self.album.artist,
            '%albumartist%': self.album.artist,
            '%album%': self.album.title,
            '%catno%':  ', '.join(self.album.catnumbers),
            # All Discogs format names as a JSON array — use with $inarray():
            #   $if1($inarray('%format_names%','Box Set'),'B','')
            '%format_names%': json.dumps(
                getattr(self.album, 'format_names', []) or []
            ).replace('\\', '\\\\'),
            # JSON array of all catalogue numbers — use with $flatten() to
            # extract individual items or slices:
            #   $flatten('%catnos%','0')        → first catno only
            #   $flatten('%catnos%',':2',' / ') → first two, joined with ' / '
            '%catnos%':  json.dumps(self.album.catnumbers or []).replace('\\', '\\\\'),
            '%catnums%': json.dumps(self.album.catnumbers or []).replace('\\', '\\\\'),  # alias
            "%year%": self.album.year,
            '%releasedate%': self.album.release_date or self.album.year or '',
            '%artist%': self.album.disc(discno).track(trackno).artist,
            '%disctotal%': self.album.disctotal,    # canonical — matches MediaFile attr
            '%totaldiscs%': self.album.disctotal,   # deprecated alias
            '%status%': getattr(self.album, 'status', '') or '',
            '%source%': getattr(self.album, 'source', '') or '',
            '%discnumber%': discno,
            '%mediatype%': self.album.disc(discno).mediatype,
            '%disctitle%':    self.album.disc(discno).discsubtitle or '',   # canonical
            '%discsubtitle%': self.album.disc(discno).discsubtitle or '',   # alias
            '%track artist%': self.album.disc(discno).track(trackno).artist,
            '%title%': self.album.disc(discno).track(trackno).title,
            '%tracknumber%': self.get_real_track_number(format, discno, trackno),
            '%track number%': trackno,
            '%format%': self.album.format,
            '%format_code%': self._format_code,
            '%format_base%': self._format_base,   # medium only, no quantity prefix
            '%vinyl_size%':  self._vinyl_size,     # 7″/10″/12″ or '' — combine with %releasetype%
            '%edition%': self._edition,
            '%releasetype%': getattr(self.album, 'release_type', '') or '',
            # '%digital%' is '1' for any digital/file-based format (Discogs: File, Web;
            # MB: Digital Media) and '' for physical media.  Use in custom variables
            # to add per-track counts without enumerating every digital format name:
            #   format_desc = $if1('%digital%','%trackcount%x','')%format_code%
            '%digital%': '1' if str(self.album.format or '').lower() in {
                'file', 'web', 'digital media', 'digital',
            } else '',
            '%trackcount%': sum(len(d.tracks) for d in self.album.discs),
            # Double backslashes before substitution so that json.dumps escape
            # sequences (e.g. ⅓ for ⅓, \" for ") survive Python's eval
            # in execute() and arrive in inarray() as valid JSON.
            '%format_description%': json.dumps(self.album.format_description or []).replace('\\', '\\\\'),
            '%fileext%': filetype,
            # Technical properties — only populated after gather_addional_properties().
            #
            # String properties appear *inside quotes* in format strings, e.g.:
            #   $lower('%codec%')  →  $lower('flac')  or  $lower('')
            # These are guarded with '' so that a preliminary dest_dir_name call
            # produces '' rather than the string 'None', preventing '[CD none--NNone]'.
            #
            # Numeric properties appear *bare* (without quotes) in format strings, e.g.:
            #   $ifequal(%bitdepth%,24,'-24','')  →  $ifequal(24,24,...)
            # These must NOT use '' as the guard: '' would produce $ifequal(,24,...)
            # which is a SyntaxError when eval'd.  Keeping None is safe because
            # Python's eval sees the identifier None, and None != 24 → returns ''.
            '%bitdepth%': self.album.disc(discno).track(trackno).bitdepth,   # bare numeric — keep None
            '%bitrate%': self.album.disc(discno).track(trackno).bitrate,     # bare numeric — keep None
            '%channels%': self.album.disc(discno).track(trackno).channels or '',
            '%codec%': self.album.disc(discno).track(trackno).codec or '',
            '%filesize%':'',
            '%filesize_natural%':'',
            '%length_samples%':'',
            '%encoding%': self.album.disc(discno).track(trackno).encoding or '',
            '%quality%': getattr(self.album, 'quality', '') or '',
            '%samplerate%': self.album.disc(discno).track(trackno).samplerate or '',
            '%length_seconds_fp%': self.album.disc(discno).track(trackno).length_seconds_fp or '',
            '%length%': self.album.disc(discno).track(trackno).length or '',
            '%length_ex%': self.album.disc(discno).track(trackno).length_ex or '',
            '%length_seconds%': self.album.disc(discno).track(trackno).length_seconds or '',

            # ── Deprecated uppercase aliases (kept for backward compatibility) ──
            # Use the lowercase equivalents above in all new format strings.
            # %ALBTITLE%  → %album%          %ALBARTIST% → %albumartist%
            # %TRACKNO%   → %tracknumber%    %ARTIST%    → %artist%
            # %TITLE%     → %title%          %YEAR%      → %year%
            # %CATNO%     → %catno%          %DISCNO%    → %discnumber%
            # %TYPE%      → %fileext%        %GENRE%     → %genres% (first)
            # %STYLE%     → %grouping%       %CODEC%     → %codec%
            # %LABEL%     has no format-string equivalent; written as a tag only.
            "%ALBTITLE%": self.album.title,
            "%ALBARTIST%": self.album.artist,
            "%YEAR%": self.album.year,
            "%CATNO%": self.album.catnumbers[0] if self.album.catnumbers else '',
            "%GENRE%": self.album.genre,
            "%STYLE%": self.album.style,
            "%ARTIST%": self.album.disc(discno).track(trackno).artist,
            "%TITLE%": self.album.disc(discno).track(trackno).title,
            "%DISCNO%": discno,
            "%TRACKNO%": "%.2d" % trackno,
            "%TYPE%": filetype,
            "%LABEL%": self.album.labels[0] if self.album.labels else '',
            "%CODEC%": self.album.codec,
        }

        # ── Custom variable expansion (%__varname__%) ────────────────────────
        # Expand before standard substitutions so that any %var% or $func()
        # inside a custom variable value is processed by the normal pipeline.
        # Names are matched case-insensitively; unknown names are left as-is.
        # Runs up to _MAX_CUSTOM_DEPTH passes so that a custom variable may
        # reference other custom variables (e.g. format_desc = %__prefix__%...).
        # The loop stops early when no further expansions are possible.
        if self.custom_variables:
            import re as _re
            _CUSTOM_RE = _re.compile(r'%__([^%]+)__%')
            _MAX_CUSTOM_DEPTH = 5
            for _ in range(_MAX_CUSTOM_DEPTH):
                def _expand_custom(m):
                    name = m.group(1).lower()
                    if name in self.custom_variables:
                        return self.custom_variables[name]
                    logger.debug('custom-variable %%%s%% not found', m.group(1))
                    return m.group(0)
                expanded = _CUSTOM_RE.sub(_expand_custom, format)
                if expanded == format:
                    break   # no more %__name__% tokens to replace
                format = expanded

        for hashtag in property_map:
            value = str(property_map[hashtag])
            # Escape single quotes as the 4-char sequence \x27 so they survive
            # eval() safely when the value is interpolated into a function
            # argument (e.g. $strcmp('%disctitle%','')).  Python's eval()
            # interprets \x27 as the apostrophe character inside string
            # literals.  The escaping is reversed after parseString() runs.
            value = value.replace("'", '\\x27')
            # Escape literal '$' in tag values using a private-use-area
            # placeholder (U+E024) so parseString() never mistakes a dollar sign
            # in a title/artist/etc. for the start of a $function() call.
            # Reversed in _value_from_tag() after parseString() completes.
            value = value.replace('$', '')
            format = format.replace(hashtag, value)

        return format

    def get_real_track_number(self, format, discno=1, trackno=1):
        if self.album.disc(discno).track(trackno).real_tracknumber is not None:
            return self.album.disc(discno).track(trackno).real_tracknumber
        else:
            return "%.2d" % trackno

    def _value_from_tag(self, format, discno=1, trackno=1, filetype=".mp3"):
        """ Generates the filename tagging map
            avoid usage of file extension here already, could lead to problems
        """

        stringFormatting = StringFormatting()
        format = self._value_from_tag_format(format, discno, trackno, filetype)
        format = stringFormatting.parseString(format)
        # Restore apostrophes that were escaped as \x27 before substitution
        # to survive eval() inside function arguments.
        format = format.replace('\\x27', "'")
        # Restore literal dollar signs that were escaped as U+E024 to prevent
        # parseString() from interpreting them as $function() calls.
        format = format.replace('', '$')

        return format

    def _set_target_discs_and_tracks(self, filetype):
        """
            set the target names of the disc and tracks in the discnumber
            based on the configuration settings and the name of the disc
            or track
            these can be calculated without knowing the source (well, the
            filetype seems to be a different calibre)
        """
        for disc in self.album.discs:
            if not self.album.has_multi_disc:
                disc.target_dir = None
            else:
                target_dir = self._value_from_tag(self.disc_folder_name, disc.discnumber)
                disc.target_dir = self.get_clean_filename(target_dir, case=self.case_disc)

            for track in disc.tracks:
                # special handling for Various Artists discs
                if self.album.artist.lower() in VARIOUS_ARTIST_NAMES:
                    newfile = self._value_from_tag(self.va_song_format, disc.discnumber,
                                               track.tracknumber, filetype)
                    case = self.case_va_song
                else:
                    newfile = self._value_from_tag(self.song_format, disc.discnumber,
                                               track.tracknumber, filetype)
                    case = self.case_song

                track.new_file = self.get_clean_filename(newfile, case=case)

    def gather_addional_properties(self):
        ''' Fetches additional technical information about the tracks
        '''
        for disc in self.album.discs:
            dn = disc.discnumber
            for track in disc.tracks:
                tn = track.tracknumber
                metadata = MediaFile(track.full_path)
                # for field in metadata.readable_fields():
                #     print('fieldname: {}: '.format(field)) #, getattr(metadata, field)

                self.album.disc(dn).track(tn).codec = metadata.type
                codec = metadata.type
                lossless = ('flac', 'alac', 'wma', 'ape', 'wav')
                encod = 'lossless' if codec.lower() in lossless else 'lossy'
                self.album.disc(dn).track(tn).encoding = encod
                self.album.disc(dn).track(tn).samplerate = metadata.samplerate
                self.album.disc(dn).track(tn).bitrate = metadata.bitrate
                self.album.disc(dn).track(tn).bitdepth = metadata.bitdepth
                chans = metadata.channels
                ch_opts = {1: 'mono', 2: 'stereo'}
                self.album.disc(dn).track(tn).channels = ch_opts[chans] if chans in ch_opts else '{}ch'.format(chans)
                self.album.disc(dn).track(tn).length_seconds_fp = metadata.length
                length_seconds_fp = metadata.length
                self.album.disc(dn).track(tn).length_seconds = int(length_seconds_fp)
                self.album.disc(dn).track(tn).length = str(timedelta(seconds = int(length_seconds_fp)))
                length_ex_str = str(timedelta(seconds = round(length_seconds_fp, 4)))
                self.album.disc(dn).track(tn).length_ex = length_ex_str[:-2]

        # After all per-track data is collected, compute release-level quality
        self.album.quality = self._assess_quality()

    def _assess_quality(self):
        """Compute a release-level quality string from per-track technical data.

        Returns one of:
          'lossless'        — every track uses a lossless codec
          '<kbps>'          — all lossy tracks share the same bitrate (CBR),
                              e.g. '320', '192'
          'vbr'             — lossy tracks with varying bitrates (VBR / ABR)
          ''                — no data available

        Intended for use as %quality% in format strings.  Combined with
        %bitdepth%, %samplerate% and %channels% it produces strings like:
          lossless-24-96s   (24-bit / 96 kHz / stereo lossless)
          lossless-44s      (16-bit / 44.1 kHz / stereo lossless)
          320-44s           (320 kbps CBR / 44.1 kHz / stereo)
          vbr-44s           (VBR / 44.1 kHz / stereo)
        """
        encodings = set()
        lossy_bitrates_kbps = []

        for disc in self.album.discs:
            for track in disc.tracks:
                enc = getattr(track, 'encoding', None)
                br  = getattr(track, 'bitrate',  None)
                if enc:
                    encodings.add(enc)
                if enc == 'lossy' and br:
                    lossy_bitrates_kbps.append(round(br / 1000))

        if not encodings:
            return ''

        # All tracks lossless (or no lossy data at all)
        if 'lossy' not in encodings:
            return 'lossless'

        # Mixed lossless + lossy is unusual but handle gracefully
        if not lossy_bitrates_kbps:
            return 'lossless'

        min_br = min(lossy_bitrates_kbps)
        max_br = max(lossy_bitrates_kbps)
        # Treat as CBR if all track bitrates agree within 5 kbps
        if max_br - min_br <= 5:
            return str(round(sum(lossy_bitrates_kbps) / len(lossy_bitrates_kbps)))

        return 'vbr'

    def _directory_has_audio_files(self, dir):
        files = next(os.walk(dir))[2]
        return any(f.endswith(self.FILE_TYPE) for f in files)

    def _directory_prune_unwanted(self, dir_list):
        """ Remove directories without audio files / in ignore list
        """
        ignored = ignored_source_dirs(self.config)
        dir_list[:] = [d for d in dir_list if d not in ignored]

    def _audio_files_in_subdirs(self, dir_list):
        """ Are files in subdirectories rather than root dirs?
        """
        sourcedir = self.album.sourcedir
        for x in dir_list:
            if x.endswith(self.FILE_TYPE):
                return False
            elif os.path.isdir(os.path.join(sourcedir, x)) and \
            self._directory_has_audio_files(os.path.join(sourcedir, x)):
                return True
        return False

    def _get_target_list(self):
        """
            fetches a list of files with the defined file_type
            in the self.sourcedir location as target_list, other
            files in the sourcedir are returned in the copy_files list.
        """
        copy_files = []
        target_list = []
        disc_source_dir = None

        sourcedir = self.album.sourcedir

        logger.debug("target_dir: %s", self.album.target_dir)
        logger.debug("sourcedir: %s", sourcedir)

        try:
            dir_list = os.listdir(sourcedir)
            dir_list.sort(key=natural_sort_key)
            self._directory_prune_unwanted(dir_list)
            filetype = ""
            self.album.copy_files = []

            if self.album.has_multi_disc or self._audio_files_in_subdirs(dir_list) is True:
                logger.debug("multi-disc layout detected in %s", sourcedir)
                dirno = 0
                for y in dir_list:
                    if os.path.isdir(os.path.join(sourcedir, y)):
                        if self._directory_has_audio_files(os.path.join(sourcedir, y)):
                            if dirno < len(self.album.discs):
                                logger.debug("disc %d source dir: %s", dirno + 1, y)
                                self.album.discs[dirno].sourcedir = y
                                dirno = dirno + 1
                            else:
                                logger.warning(
                                    'Found audio directory %s but Discogs only lists %d disc(s) '
                                    '— skipping (DVD or extra disc not in this release ID?)',
                                    y, len(self.album.discs)
                                )
                    else:
                        self.album.copy_files.append(y)

                # Flat multi-disc: Discogs says multiple discs but all audio files
                # sit in one directory with no disc subdirectories.  Distribute the
                # sorted file list across discs in order: disc 1 gets the first N
                # files, disc 2 the next M, etc.
                flat_disc_files = {}
                if self.album.has_multi_disc and dirno == 0:
                    all_audio = sorted(
                        x for x in dir_list if x.lower().endswith(self.FILE_TYPE)
                    )
                    total_tracks = sum(len(d.tracks) for d in self.album.discs)
                    if len(all_audio) != total_tracks:
                        merged_any = False
                        for disc in self.album.discs:
                            merged = _merge_indexed_disc_sub_tracks(disc.tracks)
                            if merged is not None:
                                disc.tracks = merged
                                merged_any = True
                        total_tracks = sum(len(d.tracks) for d in self.album.discs)
                        if not merged_any or len(all_audio) != total_tracks:
                            raise TaggerError(
                                f"Flat multi-disc layout: {len(all_audio)} audio files found "
                                f"but Discogs lists {total_tracks} tracks across "
                                f"{len(self.album.discs)} discs. "
                                f"Check the release or arrange files into per-disc subdirectories."
                            )
                        logger.info(
                            "Flat multi-disc: collapsed lettered sub-track positions — "
                            "%d total tracks now match %d file(s)",
                            total_tracks, len(all_audio),
                        )
                    logger.info(
                        "Flat multi-disc: %d files across %d discs — distributing in sorted order",
                        total_tracks, len(self.album.discs),
                    )
                    idx = 0
                    for disc in self.album.discs:
                        flat_disc_files[disc.discnumber] = [
                            resolve_path(os.path.join(sourcedir, f))
                            for f in all_audio[idx : idx + len(disc.tracks)]
                        ]
                        idx += len(disc.tracks)

                    # Audio files were accumulated into album.copy_files (they're
                    # non-directories in the root).  Remove them now that they've
                    # been distributed to disc subdirectories — otherwise
                    # copy_other_files() would copy them again to the album root.
                    self.album.copy_files = [
                        f for f in self.album.copy_files
                        if not f.lower().endswith(TaggerUtils.FILE_TYPE)
                    ]
            else:
                logger.debug("Setting disc sourcedir to none")
                self.album.discs[0].sourcedir = None
                flat_disc_files = {}

            first_disc_no = self.album.discs[0].discnumber

            for disc in self.album.discs:
                if disc.discnumber in flat_disc_files:
                    # Flat multi-disc: use pre-split list, no per-disc dir scan.
                    # Non-audio files (artwork etc.) are assigned to disc 1 only.
                    target_list = flat_disc_files[disc.discnumber]
                    disc_source_dir = sourcedir
                    disc.copy_files = (
                        [x for x in dir_list if not x.lower().endswith(self.FILE_TYPE)]
                        if disc.discnumber == first_disc_no else []
                    )
                else:
                    if disc.sourcedir is not None:
                        disc_source_dir = os.path.join(self.album.sourcedir, disc.sourcedir)
                    else:
                        disc_source_dir = self.album.sourcedir

                    disc_list = os.listdir(disc_source_dir)
                    disc_list.sort()
                    self._directory_prune_unwanted(disc_list)

                    disc.copy_files = [x for x in disc_list
                                       if not x.lower().endswith(TaggerUtils.FILE_TYPE)]

                    target_list = [resolve_path(os.path.join(disc_source_dir, x))
                                   for x in disc_list
                                   if x.lower().endswith(TaggerUtils.FILE_TYPE)]

                    if len(target_list) > 0 and len(target_list) != len(disc.tracks):
                        merged = _merge_indexed_disc_sub_tracks(disc.tracks)
                        if merged is not None and len(target_list) == len(merged):
                            logger.info(
                                'disc %d: collapsed lettered sub-track positions → '
                                '%d track(s) now match %d file(s)',
                                disc.discnumber, len(merged), len(target_list),
                            )
                            disc.tracks = merged
                        else:
                            raise TaggerError(
                                f"number of audio files ({len(target_list)}) does not match "
                                f"number of tracks ({len(disc.tracks)}) for disc {disc.discnumber}"
                            )

                logger.debug("disc %d: %d audio file(s) from %s",
                             disc.discnumber, len(target_list), disc_source_dir)
                for position, filename in enumerate(target_list):
                    track = disc.tracks[position]
                    track.orig_file = os.path.basename(filename)
                    track.full_path = filename
                    filetype = os.path.splitext(filename)[1]
                    disc.filetype = filetype

            self._set_target_discs_and_tracks(filetype)

        except (OSError) as e:
            if e.errno == errno.EEXIST:
                logger.error("No such directory '%s'", self.sourcedir)
                raise TaggerError("No such directory '%s'" % self.sourcedir)
            else:
                raise TaggerError("General IO system error '%s'" % e.strerror)

    @property
    def dest_dir_name(self):
        """ generates new album directory name """

        path_name = os.path.normpath(self.destdir)

        dest_dir = ""
        for ddir in self.dir_format.split("/"):
            d_dir = self.get_clean_filename(self._value_from_tag(ddir), case=self.case_dir)
            if dest_dir == "":
                dest_dir = d_dir
            else:
                dest_dir = os.path.join(dest_dir, d_dir)

        dir_name = os.path.join(path_name, dest_dir)

        return dir_name

    @property
    def m3u_filename(self):
        """ generates the m3u file name """

        m3u = self._value_from_tag(self.m3u_format)
        return self.get_clean_filename(m3u, case=self.case_m3u)

    @property
    def nfo_filename(self):
        """ generates the nfo file name """

        nfo = self._value_from_tag(self.nfo_format)
        return self.get_clean_filename(nfo, case=self.case_nfo)


    def get_clean_filename(self, f, case='preserve'):
        """Return a filesystem-safe version of f.

        Only strips characters that are genuinely invalid on Linux:
          /   — path separator
          NUL — C string terminator
          control characters \x01-\x1f, \x7f

        Everything else — commas, apostrophes, smart quotes, parentheses,
        brackets, etc. — is left intact.  Add entries to [character_exceptions]
        in the config file for any further substitutions you want, e.g.:

          '=        # strip apostrophes
          '='       # smart apostrophe → straight
          *=        # strip asterisks (needed for Windows/NAS shares)
          :=-       # colon → hyphen  (Windows invalid)

        Processing order:
          1. character_exceptions substitutions (user config)
          2. Invalid-character strip (/ and control chars)
          3. Collapse consecutive underscores introduced by substitutions
        """
        filename, fileext = os.path.splitext(f)

        if fileext not in TaggerUtils.FILE_TYPE and fileext not in ('.m3u', '.nfo'):
            filename = f
            fileext = ''

        a = str(filename)

        # Strip trailing period — causes issues on Windows and with some tools
        a = a.rstrip('.')

        # 1. Character substitutions: YAML profile + INI [character_exceptions]
        a = apply_substitutions(a, self.char_exceptions)

        # 2. Replace/remove characters that are invalid on the filesystem.
        #    path_sep_replacement and control_replacement are user-configurable
        #    so you can turn slashes into hyphens instead of dropping them.
        a = strip_invalid(a,
                          path_sep_replacement=self._path_sep_replacement,
                          control_replacement=self._control_replacement)

        # 4. Collapse consecutive underscores that substitutions may produce
        a = re.sub(r'_+', '_', a)

        cf = a + fileext
        if case == 'lower':
            cf = cf.lower()
        elif case == 'upper':
            cf = cf.upper()
        return cf

    def create_file_from_template(self, template_name, file_name):
        file_template = self.template_lookup.get_template(template_name)
        return write_file(file_template.render(album=self.album),
            os.path.join(self.album.target_dir, file_name))

    def create_nfo(self, dest_dir):
        """ Writes the .nfo file to disk. """
        return self.create_file_from_template("info.txt", self.nfo_filename)

    def create_m3u(self, dest_dir):
        """ Generates the playlist for the given albm.
            Adhering to the following m3u format.

            ---
            #EXTM3U
            #EXTINF:233,Artist - Song
            directory\file_name.mp3.mp3
            #EXTINF:-1,My Cool Stream
            http://www.site.com:8000/listen.pls
            ---

            Taken from http://forums.winamp.com/showthread.php?s=&threadid=65772"""
        return self.create_file_from_template("m3u.txt", self.m3u_filename)


def _parse_date(date_str):
    """Convert a Discogs release date string to a datetime.date object.

    Discogs provides 'released' as YYYY-MM-DD, YYYY-MM, or YYYY.
    MediaFile's date field requires a datetime.date, so partial dates are
    padded: YYYY-MM → YYYY-MM-01, YYYY → YYYY-01-01.  The year is always
    correct; the padded components are never more wrong than having no date.
    Returns None if the string cannot be parsed.
    """
    if not date_str:
        return None
    parts = date_str.split('-')
    try:
        year  = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day   = int(parts[2]) if len(parts) > 2 else 1
        # Guard against out-of-range values (e.g. month=0 after normalisation)
        month = max(1, min(month, 12))
        day   = max(1, min(day, 31))
        return date_type(year, month, day)
    except (ValueError, IndexError):
        return None


def write_file(filecontents, filename):
    """ writes a string of data to disk """

    if not os.path.exists(os.path.dirname(filename)):
        os.makedirs(os.path.dirname(filename))

    logger.debug("Writing file '%s' to disk", filename)

    try:
        with open(filename, "w") as fh:
            fh.write(filecontents)
    except IOError:
        logger.error("Unable to write file '%s'", filename)

    return True


def copytree_multi(src, dst, symlinks=False, ignore=None):
    names = os.listdir(src)
    if ignore is not None:
        ignored_names = ignore(src, names)
    else:
        ignored_names = set()

    # -------- E D I T --------
    # os.path.isdir(dst)
    if not os.path.isdir(dst):
        os.makedirs(dst)
    # -------- E D I T --------

    errors = []
    for name in names:
        if name in ignored_names:
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if symlinks and os.path.islink(srcname):
                linkto = os.readlink(srcname)
                os.symlink(linkto, dstname)
            elif os.path.isdir(srcname):
                copytree_multi(srcname, dstname, symlinks, ignore)
            else:
                copy2(srcname, dstname)
        except (IOError, os.error) as why:
            errors.append((srcname, dstname, str(why)))
        except Error as err:
            errors.extend(err.args[0])
    try:
        copystat(src, dst)
    except OSError as why:
        errors.extend((src, dst, str(why)))
    if errors:
        raise Error(errors)
