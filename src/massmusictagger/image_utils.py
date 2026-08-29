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
    from massmusictagger.core.tagger_config import TaggerConfig

from massmusictagger.core.mediafile import MediaFile
from massmusictagger.core.attachments import (
    basename_for, extension_for, LOCAL_COVER_NAMES,
    sort_key as attachment_sort_key)

logger = logging.getLogger(__name__)

# FLAC metadata blocks use a 24-bit length field — 16,777,215 bytes is the
# hard ceiling for a single embedded picture, regardless of target format.
# High-resolution booklet/tray scans from Cover Art Archive occasionally
# exceed this. Embedding is done as one batch per file (mf.images = [...]),
# so a single oversized image fails the save for every other image too;
# better to skip just that one image than lose the whole embed.
MAX_EMBEDDED_IMAGE_SIZE = 2 ** 24 - 1

def _find_written(target_dir: str, base: str):
    """The file the download step wrote for this basename, whatever extension."""
    from massmusictagger.core.attachments import _EXTENSIONS
    for ext in dict.fromkeys(_EXTENSIONS.values()):
        candidate = os.path.join(target_dir, base + ext)
        if os.path.exists(candidate):
            return candidate
    return None


def attachment_image_type(att):
    """Embedded picture type for an attachment, from its kind."""
    from mediafile import ImageType
    from massmusictagger.core.attachments import (
        COVER, FRONT, BACK, BOOKLET, LINER, MEDIUM)
    return {
        # Both are the album art; the distinction is how much the source told
        # us, not what the picture is, so both embed as the front cover.
        COVER:   ImageType.front,
        FRONT:   ImageType.front,
        BACK:    ImageType.back,
        MEDIUM:  ImageType.media,
        BOOKLET: ImageType.leaflet,
        # ID3 picture type 5 is "Leaflet page", which is what liner notes are.
        LINER:   ImageType.leaflet,
    }.get(att.kind, ImageType.other)
    # Everything else embeds as `other`: tray, spine, obi and the rest have
    # names on disk but no ID3 picture type of their own.


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
      artwork.use_folder_jpg      — also write folder.jpg for the front image
      artwork.download_only_cover — skip non-front images
      artwork.image_policy        — always | prefer_existing | prefer_larger
    """
    if not album.attachments or not album.target_dir:
        return

    target_dir = album.target_dir
    os.makedirs(target_dir, exist_ok=True)

    use_folder_jpg = (cfg.getboolean('artwork', 'use_folder_jpg')
                      if cfg.has_option('artwork', 'use_folder_jpg') else True)
    download_only_cover = (cfg.getboolean('artwork', 'download_only_cover')
                           if cfg.has_option('artwork', 'download_only_cover') else True)
    image_policy = (cfg.get('artwork', 'image_policy')
                    if cfg.has_option('artwork', 'image_policy') else 'always')

    # Local front cover — used for image_policy decisions
    local_front_path, local_front_dims = _local_front(target_dir)
    if local_front_dims:
        logger.info('Existing local front cover: %s, %dx%d px',
                    os.path.basename(local_front_path), *local_front_dims)

    basename_counter: dict[str, int] = {}

    for att in sorted(album.attachments, key=attachment_sort_key):
        uri = att.url
        if not uri:
            continue

        # The kind was decided in the mapper, so this no longer asks which
        # source the image came from in order to name it.
        base = basename_for(att, basename_counter)
        filename = f'{base}{extension_for(att)}'
        is_front = att.is_front
        fetched = None      # a measured download, reused instead of re-fetched

        # Skip non-front images when download_only_cover is set
        if download_only_cover and not is_front:
            continue

        # Apply image_policy for the front cover
        if is_front and image_policy != 'always' and local_front_dims:
            if image_policy == 'prefer_existing':
                logger.info('Skipping front cover download (prefer_existing policy)')
                continue
            if image_policy == 'prefer_larger':
                # Discogs states dimensions; the Cover Art Archive never does.
                # Trusting att.dimensions alone therefore made prefer_larger a
                # no-op against CAA -- it fell straight through and downloaded,
                # so a 1400x1400 local scan was quietly demoted behind a
                # 600x600 download, the opposite of what the setting asks for.
                # When the source will not say, fetch the image and measure it.
                dims = att.dimensions
                if not dims:
                    fetched, dims = _fetch_and_measure(
                        connector, uri, _dest_tmp(target_dir, filename))
                if dims:
                    remote_px = dims[0] * dims[1]
                    local_px = local_front_dims[0] * local_front_dims[1]
                    if local_px >= remote_px:
                        logger.info(
                            'Keeping local front cover %dx%d (%s offers %dx%d)',
                            *local_front_dims, att.provenance or 'remote', *dims)
                        _discard(fetched)
                        # Give the kept file the canonical name so the rest of
                        # the run treats it like any other front cover: the
                        # embed step looks that basename up, and a local
                        # cover.jpg left beside a downloaded front.jpg would
                        # otherwise leave two front covers in the directory
                        # with nothing to say which one wins.
                        local_front_path = _promote_local(
                            local_front_path, target_dir, base)
                        if use_folder_jpg and local_front_path:
                            _copy_to(local_front_path,
                                     os.path.join(target_dir, 'folder.jpg'))
                        continue
                    logger.info('%s front cover %dx%d beats the local %dx%d',
                                att.provenance or 'Remote', *dims,
                                *local_front_dims)

        dest = os.path.join(target_dir, filename)
        try:
            if fetched:
                # Already downloaded to measure it; don't ask for it twice.
                # shutil.move, not os.replace: the scratch file may have
                # landed in the system temp directory on another device.
                import shutil
                shutil.move(fetched, dest)
                fetched = None
            else:
                connector.fetch_image(dest, uri)
            # No local_filename written back: embedding derives the same name
            # from the same sorted list, so the album carries no scratch state.
            logger.info('Downloaded %s image → %s', att.kind, filename)
        except Exception as exc:
            logger.error('Failed to download %s image (%s): %s', filename, uri, exc)
            _discard(fetched)
            continue

        # The extension came from the URL, before there were any bytes to
        # look at. Now there are: a CAA URL that ends .jpg can still serve a
        # PNG, and a PNG named .jpg is not read by every player. Correcting it
        # here keeps the promise extension_for's own docstring makes.
        dest = _correct_extension(dest, att)

        # A downloaded front cover supersedes a local one under a different
        # name, so the directory is never left holding two of them.
        if is_front and local_front_path and \
                os.path.abspath(local_front_path) != os.path.abspath(dest):
            _discard(local_front_path)
            local_front_path = dest

        # Also write folder.jpg for the front cover (media-player compatibility)
        if is_front and use_folder_jpg:
            _copy_to(dest, os.path.join(target_dir, 'folder.jpg'))


def _measure(path: str) -> Optional[tuple[int, int]]:
    """(width, height) of an image file, or None if it cannot be read."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
        from massmusictagger.core.taggerutils import _image_dimensions
        return _image_dimensions(data)
    except Exception:
        return None


#: Subdirectories that hold album artwork, in preference order. A whitelist,
#: because the alternative is not: `quality/` in this library holds dynamic
#: range reports and spectrograms, and `info/` holds a photograph per track.
#: Treating either as cover art would embed a spectrogram as the front cover.
ARTWORK_SUBDIRS = ('covers', 'artwork', 'art', 'scans', 'scan', 'images', 'img')


def _cover_in(directory: str):
    """(path, dimensions) of a recognisable front cover in one directory.

    Matched on the stem, so front.png counts, and without regard to case, so
    Cover.jpg does. Preference order decides first: front beats cover beats
    folder, whatever the spelling or extension.

    Only a name that *says* front cover is accepted. Choosing the largest
    image instead would be a guess, and the wrong guess is specific: these
    directories mostly hold cd.jpg, back.jpg, matrix.jpg and booklet scans,
    so guessing by size embeds a disc label or a back cover as the front.
    """
    from massmusictagger.core.attachments import LOCAL_COVER_STEMS, LOCAL_IMAGE_EXTS
    try:
        present = os.listdir(directory)
    except OSError:
        return None, None

    candidates = {}
    for name in present:
        stem, ext = os.path.splitext(name)
        if ext.lower() in LOCAL_IMAGE_EXTS:
            candidates.setdefault(stem.lower(), []).append(name)

    for stem in LOCAL_COVER_STEMS:
        # Exact spelling first, then any other casing, so a directory holding
        # both front.jpg and Front.jpg behaves as it always did.
        for name in sorted(candidates.get(stem, []),
                           key=lambda n: (os.path.splitext(n)[0] != stem, n)):
            path = os.path.join(directory, name)
            dims = _measure(path)
            if dims:
                return path, dims
    return None, None


def _local_front(target_dir: str):
    """(path, dimensions) of the front cover already with this release.

    The release directory first, then the artwork subdirectories people keep
    scans in -- Covers/, artwork/, scans/. 58 of the 412 albums in this
    library have one, and the best image is often only in there: a release
    can carry a 300x300 folder.jpg beside a 600x600 scan nothing looked at.

    Returns (None, None) when there is no identifiable cover, or when a file
    is there but unreadable as an image -- a policy that cannot measure both
    sides must not pretend it made a comparison.
    """
    root_path, root_dims = _cover_in(target_dir)

    best_path, best_dims = None, None
    try:
        entries = os.listdir(target_dir)
    except OSError:
        return root_path, root_dims
    by_lower = {e.lower(): e for e in entries
                if os.path.isdir(os.path.join(target_dir, e))}

    for wanted in ARTWORK_SUBDIRS:
        actual = by_lower.get(wanted)
        if not actual:
            continue
        path, dims = _cover_in(os.path.join(target_dir, actual))
        if dims and (best_dims is None
                     or dims[0] * dims[1] > best_dims[0] * best_dims[1]):
            best_path, best_dims = path, dims

    if best_dims is None:
        return root_path, root_dims
    if root_dims is None:
        logger.info('Front cover from %s', os.path.relpath(best_path, target_dir))
        return best_path, best_dims

    if best_dims[0] * best_dims[1] <= root_dims[0] * root_dims[1]:
        return root_path, root_dims

    if not _same_shape(best_dims, root_dims):
        # Bigger, but a different picture. These directories hold wraparound
        # sleeve scans: measured over this library, 15 of the 18 subdirectory
        # covers larger than the release's own are around 2.4:1, and two are
        # 0.5 -- front and back on one sheet. Exactly one was a genuine
        # higher-resolution front. Taking the larger image on size alone
        # would embed a sleeve spread as the front cover 17 times out of 18.
        logger.debug('Ignoring %s: %dx%d is a different shape from the '
                     'release cover %dx%d, so it is a spread rather than a '
                     'front', os.path.relpath(best_path, target_dir),
                     *best_dims, *root_dims)
        return root_path, root_dims

    logger.info('Front cover from %s (%dx%d, better than %dx%d)',
                os.path.relpath(best_path, target_dir), *best_dims, *root_dims)
    return best_path, best_dims


def _same_shape(a, b, tolerance: float = 0.15) -> bool:
    """Do these two images have close to the same aspect ratio?

    The test for "the same picture, scanned bigger" rather than "a different
    picture that happens to be bigger". A front cover reproduced at higher
    resolution keeps its proportions; a sleeve spread does not.
    """
    if not a or not b or not a[1] or not b[1]:
        return False
    ra, rb = a[0] / a[1], b[0] / b[1]
    return abs(ra - rb) <= tolerance * max(ra, rb)


def _local_front_dimensions(target_dir: str) -> Optional[tuple[int, int]]:
    """Dimensions only, for callers that do not need the path."""
    return _local_front(target_dir)[1]


def _dest_tmp(target_dir: str, filename: str) -> str:
    """Scratch path beside the destination, so the later move stays on-device.

    Deliberately not dot-prefixed. A hidden name was rejected outright by the
    SMB share this runs against -- "Operation not permitted" -- and because the
    failure was handled gracefully the run carried on and downloaded the
    smaller image anyway, which is the exact outcome the measurement exists to
    prevent. A visible .part file works on every share tried, and is removed
    either way.
    """
    return os.path.join(target_dir, f'{filename}.part')


def _fetch_and_measure(connector, uri: str, tmp: str):
    """Download to a scratch path and measure it: (path, dims).

    Falls back to the system temp directory when the target filesystem will
    not take the scratch file, so a share with unusual rules costs a
    cross-device copy rather than the comparison itself.

    Either element may be None -- the caller still holds the local image and
    proceeds without a comparison, which is why this warns rather than raises.
    """
    try:
        connector.fetch_image(tmp, uri)
        return tmp, _measured(tmp, uri)
    except Exception as exc:
        logger.debug('Scratch download to %s failed (%s); trying the system '
                     'temp directory', tmp, exc)

    import tempfile
    fd, alt = tempfile.mkstemp(suffix=os.path.splitext(tmp)[0][-4:] or '.jpg')
    os.close(fd)
    try:
        connector.fetch_image(alt, uri)
    except Exception as exc:
        logger.warning('Could not fetch %s to compare sizes: %s', uri, exc)
        _discard(alt)
        return None, None
    return alt, _measured(alt, uri)


def _measured(path: str, uri: str):
    dims = _measure(path)
    if not dims:
        logger.warning('Downloaded %s but could not read its dimensions', uri)
    return dims


def _correct_extension(dest: str, att) -> str:
    """Rename a downloaded image whose bytes disagree with its extension.

    Returns the path the file now has -- unchanged when it was already right,
    or when the rename fails, since a slightly misnamed image that exists
    beats a correctly named one that does not.
    """
    try:
        with open(dest, 'rb') as f:
            head = f.read(16)
    except OSError:
        return dest

    base, ext = os.path.splitext(dest)
    actual = extension_for(att, head)
    if actual == ext:
        return dest

    corrected = base + actual
    try:
        os.replace(dest, corrected)
    except OSError as exc:
        logger.warning('Could not rename %s to %s: %s', dest, corrected, exc)
        return dest
    logger.info('%s is really %s — saved as %s', os.path.basename(dest),
                actual.lstrip('.').upper(), os.path.basename(corrected))
    return corrected


def _discard(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _promote_local(path: Optional[str], target_dir: str, base: str):
    """Put a kept local cover in the release root under the canonical name.

    Returns its new path, or the original when nothing could be done -- a
    slightly awkwardly named cover that exists beats a tidy one that does not.

    Two details this gets right that a plain rename did not:

    * The file keeps **its own** extension. Naming was taken from the remote
      attachment, so a local front.png became front.jpg while still being PNG
      bytes -- the same misnaming that _correct_extension exists to prevent.

    * A cover found in Covers/ or scans/ is **copied** out, not moved. Those
      directories are carried into the tagged release by copy_other_files,
      and quietly removing a file from someone's scan set to promote it would
      leave the set incomplete.
    """
    if not path:
        return path

    ext = os.path.splitext(path)[1].lower()
    if ext == '.jpeg':
        ext = '.jpg'                       # same format, one spelling
    dest = os.path.join(target_dir, base + ext)
    if os.path.abspath(path) == os.path.abspath(dest):
        return path

    in_subdir = (os.path.dirname(os.path.abspath(path))
                 != os.path.abspath(target_dir))
    try:
        if in_subdir:
            import shutil
            shutil.copyfile(path, dest)
            logger.info('Using %s as the front cover',
                        os.path.relpath(path, target_dir))
        else:
            os.replace(path, dest)
            logger.info('Renamed local %s \u2192 %s',
                        os.path.basename(path), os.path.basename(dest))
        return dest
    except OSError as exc:
        logger.warning('Could not promote %s to %s: %s', path, dest, exc)
        return path


def _copy_to(src: str, dest: str) -> None:
    """folder.jpg and friends: a local copy, never a second download."""
    if os.path.abspath(src) == os.path.abspath(dest):
        return
    try:
        import shutil
        shutil.copyfile(src, dest)
    except OSError as exc:
        logger.debug('Optional copy %s → %s failed: %s', src, dest, exc)


# ── Embed ───────────────────────────────────────────────────────────────────

def embed_typed_images(album, cfg: 'TaggerConfig') -> None:
    """Embed all downloaded typed images into every audio file.

    Each image is tagged with its correct picture type so media players
    display front cover, back cover, disc label, booklet pages etc. in their
    designated slots.

    Only images that were successfully downloaded (have a 'local_filename'
    key set by download_typed_images()) are embedded.
    """
    if not cfg.has_option('artwork', 'embed_coverart'):
        return
    if not cfg.getboolean('artwork', 'embed_coverart'):
        return
    if not album.target_dir:
        return

    target_dir = album.target_dir

    # Build the list of Image objects to embed, front cover first
    from mediafile import Image as MFImage, ImageType
    images: list = []

    # Sort: front cover first, then back, then everything else
    embed_counter: dict[str, int] = {}

    for att in sorted(album.attachments, key=attachment_sort_key):
        # Derived, not carried. The download step names files from the same
        # sorted list with the same counter, so both agree without the album
        # having to ferry a local_filename between them.
        # Find the file rather than predict its extension: the download may
        # have chosen one from the image's own bytes when the URL did not say.
        base = basename_for(att, embed_counter)
        path = _find_written(target_dir, base)
        if path is None:
            continue
        local_filename = os.path.basename(path)
        img_type = attachment_image_type(att)
        try:
            with open(path, 'rb') as f:
                data = f.read()
            if len(data) > MAX_EMBEDDED_IMAGE_SIZE:
                logger.warning(
                    'Skipping %s for embedding — %d bytes exceeds the FLAC '
                    'metadata block limit (%d bytes)',
                    local_filename, len(data), MAX_EMBEDDED_IMAGE_SIZE,
                )
                continue
            header = data[:4]
            if header[:2] != b'\xff\xd8' and header != b'\x89PNG':
                logger.warning('Skipping non-JPEG/PNG image: %s', local_filename)
                continue
            images.append(MFImage(data=data, type=img_type))
            logger.debug('Queued %s (%s, type=%s) for embedding',
                         local_filename, att.kind, img_type.name)
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
