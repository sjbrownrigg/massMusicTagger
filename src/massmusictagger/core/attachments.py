# -*- coding: utf-8 -*-
"""Images and other files a release carries, in one shape.

Discogs and the Cover Art Archive describe artwork differently, and until now
both shapes travelled as raw dicts on ``album.images``:

    Discogs   {'uri', 'type': 'primary'|'secondary', 'width', 'height', ...}
    CAA       {'uri', 'type': 'primary', 'caa_types': ['Front'], 'width': None}

Downstream code told them apart with ``has_caa_type_metadata()``, which looked
for a ``caa_types`` key on the *first* image and branched. Two download paths
grew behind that branch -- one in taggerutils for Discogs, one in image_utils
for CAA -- doing substantially the same job.

An Attachment is what both become. The kind is decided once, in the mapper that
knows the source's vocabulary, so nothing downstream has to ask where a picture
came from in order to know what it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: What an attachment depicts. `other` is honest about not knowing rather than
#: guessing, and is what unrecognised source values become.
#: `front` means a source told us so, in a vocabulary that distinguishes front
#: from back. `cover` means this is the album art but nothing typed it -- the
#: name is deliberately the weaker claim.
COVER, FRONT, BACK, BOOKLET, MEDIUM, OTHER = (
    'cover', 'front', 'back', 'booklet', 'medium', 'other')

#: The rest of the Cover Art Archive's vocabulary. These were being flattened
#: to `other` and named image-01, image-02, … which threw away type
#: information the source had already given us -- a tray scan and a poster
#: became indistinguishable on disk. CAA names them, so we name them.
LINER, TRAY, SPINE, OBI, STICKER, POSTER = (
    'liner', 'tray', 'spine', 'obi', 'sticker', 'poster')
TOP, BOTTOM, MATRIX, RAW, TRACK, WATERMARK = (
    'top', 'bottom', 'matrix', 'raw', 'track', 'watermark')

#: Also the naming and sort order: album art first, then the rest of the
#: package roughly as you would meet it, with the obscure types last.
KINDS = (COVER, FRONT, BACK, BOOKLET, LINER, MEDIUM, TRAY, SPINE, OBI,
         STICKER, POSTER, TOP, BOTTOM, MATRIX, RAW, TRACK, WATERMARK, OTHER)

#: Kinds that are the album art, whichever name they carry. Policy decisions --
#: download_only_cover, prefer_larger -- apply to all of these.
ALBUM_ART = (COVER, FRONT)

#: Cover Art Archive type strings → our kinds. CAA gives a list per image, and
#: the first recognised entry wins.
_CAA_KIND = {
    'Front': FRONT,
    'Back': BACK,
    'Booklet': BOOKLET,
    'Liner': LINER,
    'Medium': MEDIUM,
    'Tray': TRAY,
    'Spine': SPINE,
    'Obi': OBI,
    'Sticker': STICKER,
    'Poster': POSTER,
    'Top': TOP,
    'Bottom': BOTTOM,
    'Matrix/Runout': MATRIX,
    'Raw/Unedited': RAW,
    'Track': TRACK,
    'Watermark': WATERMARK,
    'Other': OTHER,
}


@dataclass(frozen=True)
class Attachment:
    """One file a release carries — artwork today, room for more later."""

    url: str
    kind: str = OTHER
    width: Optional[int] = None
    height: Optional[int] = None
    provenance: str = ''          # 'discogs' | 'coverartarchive'
    #: The source's own type vocabulary, kept so nothing is silently discarded.
    source_types: tuple = field(default_factory=tuple)

    @property
    def is_front(self) -> bool:
        """Is this the album art? True for both `front` and `cover`."""
        return self.kind in ALBUM_ART

    @property
    def dimensions(self) -> Optional[tuple]:
        """(width, height), or None when the source did not say.

        CAA never reports dimensions, so callers deciding whether a remote
        image beats a local one must handle not knowing.
        """
        if self.width and self.height:
            return self.width, self.height
        return None


def from_discogs(image: dict) -> Attachment:
    """Normalise one entry of a Discogs release's ``images`` list.

    Discogs says only 'primary' or 'secondary', which is not an image type in
    the sense the Cover Art Archive means -- it does not distinguish a front
    from a back. So its main image becomes `cover`, not `front`: the album art,
    without claiming to know which face of the sleeve it shows.
    """
    kind = COVER if image.get('type') == 'primary' else OTHER
    return Attachment(
        url=image.get('uri') or '',
        kind=kind,
        width=image.get('width') or None,
        height=image.get('height') or None,
        provenance='discogs',
        source_types=(image.get('type'),) if image.get('type') else (),
    )


def from_discogs_list(images) -> list:
    """Normalise a Discogs release's whole ``images`` list.

    Discogs marks a cover with type 'primary', but 21% of releases carrying
    images have none -- every entry is 'secondary'. Mapped one at a time those
    all become `other`, so the release ends up with no front cover: the files
    get image-01.jpg and the embedded art is typed `other`, which players do
    not necessarily show as album art.

    Discogs lists images cover-first, so when nothing is marked primary the
    first entry is promoted. That is a convention rather than a guarantee,
    which is why it happens here -- at the list level, where the ordering is
    visible -- and not inside from_discogs().
    """
    atts = [from_discogs(i) for i in (images or [])]
    if atts and not any(a.is_front for a in atts):
        first = atts[0]
        atts[0] = Attachment(
            url=first.url, kind=COVER,
            width=first.width, height=first.height,
            provenance=first.provenance, source_types=first.source_types)
    return atts


def from_caa(image: dict) -> Attachment:
    """Normalise one entry of a Cover Art Archive image list.

    CAA types are a list -- an image can be both Front and Medium -- so the
    first recognised entry decides the kind.
    """
    types = tuple(image.get('caa_types') or ())
    kind = OTHER
    for t in types:
        if t in _CAA_KIND:
            kind = _CAA_KIND[t]
            break
    return Attachment(
        url=image.get('uri') or image.get('image') or '',
        kind=kind,
        width=image.get('width') or None,
        height=image.get('height') or None,
        provenance='coverartarchive',
        source_types=types,
    )


#: Extensions we are willing to write, mapped from what a URL or the bytes say.
_EXTENSIONS = {'jpg': '.jpg', 'jpeg': '.jpg', 'png': '.png',
               'gif': '.gif', 'webp': '.webp'}


#: Filenames an existing local cover may already have, in preference order.
#: Shared so the "is there already a cover here?" checks cannot drift apart --
#: there were two lists, and only one of them knew about image-01.jpg.
LOCAL_COVER_NAMES = ('front.jpg', 'cover.jpg', 'folder.jpg', 'image-01.jpg')


def extension_for(att: 'Attachment', data: Optional[bytes] = None) -> str:
    """The file extension to write this attachment as.

    Everything used to be written as .jpg regardless. The URL usually says,
    and when it does not the first bytes do -- guessing wrong leaves a PNG
    named .jpg, which some players will not read.
    """
    if data:
        if data[:2] == b'\xff\xd8':
            return '.jpg'
        if data[:4] == b'\x89PNG':
            return '.png'
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return '.webp'
        if data[:3] == b'GIF':
            return '.gif'

    tail = att.url.rsplit('?', 1)[0].rsplit('.', 1)
    if len(tail) == 2:
        ext = _EXTENSIONS.get(tail[1].lower())
        if ext:
            return ext
    return '.jpg'


def basename_for(att: 'Attachment', counter: dict) -> str:
    """The on-disk basename, without extension, following CAA convention.

    A recognised kind keeps its own name -- front, back, medium, booklet --
    and only gains a number when there is more than one of it. Anything we
    could not type becomes image-01, image-02, …, which is where Discogs
    secondary images land: numbered from the start, because there is no
    single "the" unknown image.

    counter is mutated across calls, so the download and embed steps agree by
    walking the same sorted list rather than passing filenames between them.
    """
    if att.kind == OTHER:
        n = counter.get(OTHER, 0) + 1
        counter[OTHER] = n
        return f'image-{n:02d}'

    n = counter.get(att.kind, 0)
    counter[att.kind] = n + 1
    return att.kind if n == 0 else f'{att.kind}-{n:02d}'


def front(attachments) -> Optional[Attachment]:
    """The front cover, or None. Every consumer wanted this and open-coded it."""
    for a in attachments or ():
        if a.is_front:
            return a
    return None


def sort_key(a: Attachment) -> tuple:
    """Front first, then the rest in a stable order.

    Downstream naming depends on this being deterministic: a booklet that
    becomes booklet-01.jpg on one run and booklet-02.jpg on the next is worse
    than either choice.
    """
    return (KINDS.index(a.kind) if a.kind in KINDS else len(KINDS), a.url)
