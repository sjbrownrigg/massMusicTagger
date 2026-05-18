"""Cover Art Archive typed image downloading and embedding.

Discogs images carry only 'primary' / 'secondary' type information.
MusicBrainz Cover Art Archive images carry explicit type lists such as
['Front'], ['Back'], ['Medium'], ['Booklet'], etc.

This module uses that richer metadata to:
  - Name downloaded files meaningfully (back.jpg, medium.jpg, booklet-01.jpg)
  - Embed each image into audio file metadata with the correct picture type,
    so media players display front cover, back cover, disc label, etc. in
    their designated slots rather than lumping everything as 'other'.
  - Enable targeted per-type image comparison (front vs front, back vs back)
    when deciding whether to replace an existing local image.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from discogstagger.tagger_config import TaggerConfig

from discogstagger.mediafile_ext import MediaFile

logger = logging.getLogger(__name__)

# ── CAA type → file basename ────────────────────────────────────────────────
# Determines how each image is named on disk.  Types not listed here fall back
# to 'image'.  When multiple images share a basename the second and subsequent
# are numbered: booklet-01.jpg, booklet-02.jpg, …
_CAA_TYPE_BASENAME: dict[str, str] = {
    'Front':   'front',
    'Back':    'back',
    'Medium':  'medium',    # disc/vinyl label scan
    'Booklet': 'booklet',
    'Tray':    'tray',
    'Spine':   'spine',
    'Sticker': 'sticker',
    'Poster':  'poster',
    'Liner':   'liner',
}

# ── CAA type → mediafile ImageType ─────────────────────────────────────────
# Maps each CAA type to the ID3/FLAC picture-type value so media players
# (foobar2000, MusicBee, Picard, etc.) recognise each image's role.
# Numbers are ID3v2 APIC picture-type codes (also used by Vorbis).
_CAA_TYPE_IMAGE_TYPE_ID: dict[str, int] = {
    'Front':   3,   # Cover (front)
    'Back':    4,   # Cover (back)
    'Booklet': 5,   # Leaflet page
    'Medium':  6,   # Media (e.g. label side of a CD)
    'Tray':    0,   # Other
    'Spine':   0,   # Other
    'Sticker': 0,   # Other
    'Poster':  0,   # Other
    'Liner':   0,   # Other
}


def has_caa_type_metadata(images: list) -> bool:
    """Return True if the image list has CAA type metadata."""
    return bool(images and images[0].get('caa_types'))


def caa_basename(caa_types: list[str], counter: dict[str, int]) -> str:
    """Return the disk filename (without .jpg extension) for a CAA image.

    counter is mutated in-place to track how many images of each basename
    have been assigned, so that booklet-01.jpg, booklet-02.jpg, … are unique.
    """
    base = 'image'
    for t in caa_types:
        if t in _CAA_TYPE_BASENAME:
            base = _CAA_TYPE_BASENAME[t]
            break
    n = counter.get(base, 0)
    counter[base] = n + 1
    return base if n == 0 else f'{base}-{n:02d}'


def caa_image_type_id(caa_types: list[str]) -> int:
    """Return the ID3 picture-type integer for a CAA image type list."""
    for t in caa_types:
        if t in _CAA_TYPE_IMAGE_TYPE_ID:
            return _CAA_TYPE_IMAGE_TYPE_ID[t]
    return 0   # Other


def caa_image_type(caa_types: list[str]):
    """Return the mediafile ImageType enum value for a CAA image type list."""
    from mediafile import ImageType
    id_ = caa_image_type_id(caa_types)
    try:
        return ImageType(id_)
    except ValueError:
        return ImageType.other


# ── Download ────────────────────────────────────────────────────────────────

def download_typed_images(album, connector, cfg: 'TaggerConfig') -> None:
    """Download Cover Art Archive images with type-based filenames.

    Each image is saved as its canonical name (front.jpg, back.jpg,
    medium.jpg, booklet-01.jpg, …) rather than the generic image-01.jpg
    used for Discogs secondary images.

    The 'local_filename' key is added to each image dict so that
    embed_typed_images() can find the downloaded file without re-scanning
    the target directory.

    Respects config settings:
      details.use_folder_jpg      — also write folder.jpg for the front image
      details.download_only_cover — skip non-front images
      details.image_policy        — always | prefer_existing | prefer_larger
    """
    if not album.images or not album.target_dir:
        return

    target_dir = album.target_dir
    os.makedirs(target_dir, exist_ok=True)

    use_folder_jpg = (cfg.getboolean('details', 'use_folder_jpg')
                      if cfg.has_option('details', 'use_folder_jpg') else True)
    download_only_cover = (cfg.getboolean('details', 'download_only_cover')
                           if cfg.has_option('details', 'download_only_cover') else True)
    image_policy = (cfg.get('details', 'image_policy')
                    if cfg.has_option('details', 'image_policy') else 'always')

    # Local front cover — used for image_policy decisions
    local_front_dims = _local_front_dimensions(target_dir)
    if local_front_dims:
        logger.info('Existing local front cover: %dx%d px', *local_front_dims)

    basename_counter: dict[str, int] = {}

    for img in album.images:
        caa_types = img.get('caa_types') or []
        uri = img.get('uri', '')
        if not uri:
            continue

        base = caa_basename(caa_types, basename_counter)
        filename = f'{base}.jpg'
        is_front = (base == 'front')

        # Skip non-front images when download_only_cover is set
        if download_only_cover and not is_front:
            continue

        # Apply image_policy for the front cover
        if is_front and image_policy != 'always' and local_front_dims:
            if image_policy == 'prefer_existing':
                logger.info('Skipping front cover download (prefer_existing policy)')
                continue
            if image_policy == 'prefer_larger':
                disc_w = img.get('width') or 0
                disc_h = img.get('height') or 0
                if disc_w and disc_h:
                    local_px = local_front_dims[0] * local_front_dims[1]
                    caa_px = disc_w * disc_h
                    if local_px >= caa_px:
                        logger.info(
                            'Keeping local front cover %dx%d (CAA is %dx%d)',
                            *local_front_dims, disc_w, disc_h,
                        )
                        continue
                    logger.info('CAA front cover larger — downloading')

        dest = os.path.join(target_dir, filename)
        try:
            connector.fetch_image(dest, uri)
            img['local_filename'] = filename
            logger.info('Downloaded %s image → %s', '/'.join(caa_types) or 'unknown', filename)
        except Exception as exc:
            logger.error('Failed to download %s image (%s): %s', filename, uri, exc)
            continue

        # Also write folder.jpg for the front cover (media-player compatibility)
        if is_front and use_folder_jpg:
            folder_dest = os.path.join(target_dir, 'folder.jpg')
            try:
                connector.fetch_image(folder_dest, uri)
            except Exception:
                pass   # folder.jpg is optional


def _local_front_dimensions(target_dir: str) -> Optional[tuple[int, int]]:
    """Return (width, height) of the existing local front cover, or None."""
    for candidate in ('front.jpg', 'folder.jpg', 'cover.jpg'):
        path = os.path.join(target_dir, candidate)
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                from discogstagger.taggerutils import _image_dimensions
                dims = _image_dimensions(data)
                if dims:
                    return dims
            except Exception:
                pass
    return None


# ── Embed ───────────────────────────────────────────────────────────────────

def embed_typed_images(album, cfg: 'TaggerConfig') -> None:
    """Embed all downloaded typed images into every audio file.

    Each image is tagged with its correct picture type so media players
    display front cover, back cover, disc label, booklet pages etc. in their
    designated slots.

    Only images that were successfully downloaded (have a 'local_filename'
    key set by download_typed_images()) are embedded.
    """
    if not cfg.has_option('details', 'embed_coverart'):
        return
    if not cfg.getboolean('details', 'embed_coverart'):
        return
    if not album.target_dir:
        return

    target_dir = album.target_dir

    # Build the list of Image objects to embed, front cover first
    from mediafile import Image as MFImage, ImageType
    images: list = []

    # Sort: front cover first, then back, then everything else
    def _sort_key(img):
        types = img.get('caa_types') or []
        if 'Front' in types:
            return 0
        if 'Back' in types:
            return 1
        if 'Medium' in types:
            return 2
        if 'Booklet' in types:
            return 3
        return 9

    for img in sorted(album.images, key=_sort_key):
        local_filename = img.get('local_filename')
        if not local_filename:
            continue
        path = os.path.join(target_dir, local_filename)
        if not os.path.exists(path):
            continue
        caa_types = img.get('caa_types') or []
        img_type = caa_image_type(caa_types)
        try:
            with open(path, 'rb') as f:
                data = f.read()
            header = data[:4]
            if header[:2] != b'\xff\xd8' and header != b'\x89PNG':
                logger.warning('Skipping non-JPEG/PNG image: %s', local_filename)
                continue
            images.append(MFImage(data=data, type=img_type))
            logger.debug('Queued %s (%s, type=%s) for embedding',
                         local_filename, '/'.join(caa_types) or 'unknown', img_type.name)
        except Exception as exc:
            logger.warning('Could not read %s for embedding: %s', local_filename, exc)

    if not images:
        logger.debug('No typed images to embed')
        return

    logger.info('Embedding %d typed image(s) into %d disc(s)',
                len(images), len(album.discs))

    for disc in album.discs:
        track_dir = (os.path.join(target_dir, disc.target_dir)
                     if disc.target_dir else target_dir)
        for track in disc.tracks:
            track_file = os.path.join(track_dir, track.new_file)
            try:
                mf = MediaFile(track_file)
                mf.images = images
                mf.save()
            except Exception as exc:
                logger.error('Failed to embed images in %s: %s', track_file, exc)
