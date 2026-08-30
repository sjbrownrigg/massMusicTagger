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
import shutil
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
    superseded = False      # has the pre-existing local cover been dealt with
    folder_written = False  # folder.jpg takes the first front cover only
    front_settled = False   # image_policy decides the front cover once

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

        # image_policy governs *the* front cover -- the first one. A source
        # that returns several fronts sends the rest as extras, and they are
        # simply written. Applying the policy to each of them compared every
        # one against the same local cover, including after that cover had
        # been superseded and deleted: the release then lost both the local
        # cover and one of the downloads.
        if is_front and image_policy != 'always' and local_front_dims \
                and not front_settled:
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
                        # It is output now, not a leftover: a later front
                        # slot must not treat it as the cover to supersede.
                        superseded = True
                        front_settled = True
                        if use_folder_jpg and local_front_path and not folder_written:
                            _copy_to(local_front_path,
                                     os.path.join(target_dir, 'folder.jpg'))
                            folder_written = True
                        continue
                    logger.info('%s front cover %dx%d beats the local %dx%d',
                                att.provenance or 'Remote', *dims,
                                *local_front_dims)
                    front_settled = True

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

        # A connector need not raise to have failed: the Cover Art Archive
        # answers 404 for a release whose front it does not hold, and the
        # connector logs that and returns. Treating that as a download meant
        # the supersede step below deleted the release's own cover to make way
        # for a file that does not exist.
        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            logger.warning('%s produced no image for %s — keeping what the '
                           'release already had', att.provenance or 'the source',
                           filename)
            _discard(dest)
            continue

        # The extension came from the URL, before there were any bytes to
        # look at. Now there are: a CAA URL that ends .jpg can still serve a
        # PNG, and a PNG named .jpg is not read by every player. Correcting it
        # here keeps the promise extension_for's own docstring makes.
        dest = _correct_extension(dest, att)

        # A downloaded front cover supersedes the cover that was already in
        # the directory, so it is never left holding two of them.
        #
        # Only the pre-existing one. This used to reassign local_front_path to
        # each download, so when a source offered a *second* front image the
        # supersede fired again and deleted the first: a release with two CAA
        # fronts ended up with front-01.jpg and no front.jpg at all.
        if is_front and local_front_path and not superseded and \
                os.path.abspath(local_front_path) != os.path.abspath(dest):
            _discard(local_front_path)
            superseded = True

        # folder.jpg is what most players read, and there is one of it. It
        # takes the *first* front cover: a release with two fronts used to
        # end up with folder.jpg copied from whichever came last.
        if is_front and use_folder_jpg and not folder_written:
            _copy_to(dest, os.path.join(target_dir, 'folder.jpg'))
            folder_written = True


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
        if os.path.exists(tmp):
            return tmp, _measured(tmp, uri)
        # A connector need not raise. The Cover Art Archive answers 404 for a
        # release whose front cover it does not hold, and the connector logs
        # that and returns -- leaving no file. Handing the caller a path to a
        # file that was never created made it try to move one:
        #   Failed to download front.jpg image: [Errno 2] ... front.jpg.part
        logger.debug('No file at %s after fetching %s', tmp, uri)
        return None, None
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
    # mkstemp creates the file, so "it exists" proves nothing here -- an
    # empty one means the connector returned without writing anything.
    if not os.path.exists(alt) or os.path.getsize(alt) == 0:
        logger.debug('Nothing was written to %s for %s', alt, uri)
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

def embed_typed_images(album, cfg: 'TaggerConfig',
                       artist_image: 'Optional[str]' = None) -> None:
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
            # A description per image, and it must be distinct. ID3 keys a
            # picture frame by its description, so images written with the
            # same one overwrite each other: four images embedded into an MP3
            # read back as one, the last written, whatever its type. An album
            # with a front, a back and two extras kept only an untyped
            # thumbnail. FLAC was unaffected, which is why it went unnoticed.
            #
            # The basename is already unique within the release -- front,
            # back, image-01 -- so it is the description, and it says
            # something useful to anyone reading the tags.
            images.append(MFImage(data=data, type=img_type, desc=base))
            logger.debug('Queued %s (%s, type=%s) for embedding',
                         local_filename, att.kind, img_type.name)
        except Exception as exc:
            logger.warning('Could not read %s for embedding: %s', local_filename, exc)

    # The artist picture, as ID3/FLAC picture type 8. It is not one of the
    # release's attachments -- it belongs to the artist -- so it is appended
    # here rather than coming through the sorted attachment list.
    if artist_image and os.path.exists(artist_image):
        try:
            with open(artist_image, 'rb') as f:
                data = f.read()
            if len(data) > MAX_EMBEDDED_IMAGE_SIZE:
                logger.warning('Skipping the artist image for embedding — '
                               '%d bytes exceeds the metadata block limit',
                               len(data))
            elif data[:2] != b'\xff\xd8' and data[:4] != b'\x89PNG':
                logger.warning('Skipping a non-JPEG/PNG artist image')
            else:
                images.append(MFImage(data=data, type=ImageType.artist,
                                      desc='artist'))
        except Exception as exc:
            logger.warning('Could not read the artist image: %s', exc)

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


# ── Artist images ────────────────────────────────────────────────────────────
#
# An artist picture belongs to the artist, not to any one release, so it is
# fetched once per artist and cached. Only Discogs has them -- MusicBrainz
# stores no artist images at all, only release cover art through the Cover Art
# Archive -- so an album matched on MusicBrainz needs a Discogs artist lookup
# of its own.
#
# This only became worth doing alongside %albumartist_primary%. Without it a
# guest credit gets its own folder, so "David Bowie Featuring Al B. Sure!"
# would collect a second copy of the same picture.

ARTIST_IMAGE_NAME = 'artist.jpg'


def _artist_cache_path(artist_id) -> str:
    """Where a fetched artist image is kept between albums."""
    from massmusictagger import roots
    directory = os.path.join(roots.state_root(), 'artist-images')
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f'{artist_id}.jpg')


def _discogs_artist_id(album, connector):
    """The Discogs artist id for this album's primary artist, or None.

    A Discogs-matched album already carries the id. A MusicBrainz-matched one
    does not, so the artist is searched for by name -- the reason the lookup
    is cached by id further down rather than repeated per album.
    """
    ids = [i for i in (getattr(album, 'artist_ids', None) or []) if i]
    if ids and getattr(album, 'source', '') == 'discogs':
        return ids[0]

    name = (getattr(album, 'artists', None) or [None])[0]
    if not name:
        return None
    try:
        results = connector.discogs_client.search(name, type='artist')
        for result in results:
            if (getattr(result, 'name', '') or '').lower() == name.lower():
                return result.id
        first = next(iter(results), None)
        return getattr(first, 'id', None) if first else None
    except Exception as exc:
        logger.debug('Discogs artist search failed for %r: %s', name, exc)
        return None


def fetch_artist_image(album, connector, cfg) -> 'Optional[str]':
    """Download this album's artist image once, returning a local path.

    Returns None when the feature is off, no artist can be resolved, or the
    artist has no images -- all ordinary outcomes rather than failures.
    """
    if not cfg.getboolean('artwork', 'artist_image'):
        return None
    if connector is None:
        return None

    artist_id = _discogs_artist_id(album, connector)
    if not artist_id:
        logger.debug('No Discogs artist id for %r — no artist image',
                     getattr(album, 'artist', '?'))
        return None

    cached = _artist_cache_path(artist_id)
    if os.path.exists(cached) and os.path.getsize(cached) > 0:
        logger.debug('Artist image for %s already fetched', artist_id)
        return cached

    try:
        artist = connector.discogs_client.artist(int(artist_id))
        images = artist.images or []
    except Exception as exc:
        logger.info('Could not read Discogs artist %s: %s', artist_id, exc)
        return None
    if not images:
        logger.info('Discogs artist %s has no images', artist_id)
        return None

    # 'primary' is the picture Discogs itself leads with; fall back to the
    # first of whatever is there.
    chosen = next((i for i in images if i.get('type') == 'primary'), images[0])
    uri = chosen.get('uri') or chosen.get('resource_url')
    if not uri:
        return None

    try:
        connector.fetch_image(cached, uri)
    except Exception as exc:
        logger.info('Could not download the artist image for %s: %s',
                    artist_id, exc)
        return None

    if not os.path.exists(cached) or os.path.getsize(cached) == 0:
        _discard(cached)
        logger.info('Artist image for %s downloaded empty — ignoring', artist_id)
        return None

    logger.info('Fetched artist image for %s (%dx%d)', artist_id,
                chosen.get('width') or 0, chosen.get('height') or 0)
    return cached


def place_artist_image(image_path: str, album_dir: str) -> 'Optional[str]':
    """Copy the artist image into the artist folder beside the album.

    Called after the album has reached its real destination -- with staging
    enabled the album's parent during processing is a temporary directory, not
    the artist folder, so doing this earlier would file the picture nowhere
    useful.

    An existing file is left alone: the folder is shared by every album by
    that artist, and the first one to arrive has already done the work.
    """
    if not image_path or not os.path.isdir(album_dir):
        return None
    artist_dir = os.path.dirname(os.path.normpath(album_dir))
    if not artist_dir or not os.path.isdir(artist_dir):
        return None

    target = os.path.join(artist_dir, ARTIST_IMAGE_NAME)
    if os.path.exists(target):
        return target
    try:
        shutil.copy2(image_path, target)
        logger.info('Wrote %s', target)
        return target
    except Exception as exc:
        logger.warning('Could not write the artist image to %s: %s',
                       artist_dir, exc)
        return None
