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
FRONT, BACK, BOOKLET, MEDIUM, OTHER = 'front', 'back', 'booklet', 'medium', 'other'

KINDS = (FRONT, BACK, BOOKLET, MEDIUM, OTHER)

#: Cover Art Archive type strings → our kinds. CAA gives a list per image, and
#: the first recognised entry wins.
_CAA_KIND = {
    'Front': FRONT,
    'Back': BACK,
    'Booklet': BOOKLET,
    'Medium': MEDIUM,
    'Tray': OTHER,
    'Obi': OTHER,
    'Spine': OTHER,
    'Track': OTHER,
    'Liner': BOOKLET,
    'Sticker': OTHER,
    'Poster': OTHER,
    'Watermark': OTHER,
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
        return self.kind == FRONT

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

    Discogs says only 'primary' or 'secondary'. Primary is the front cover;
    secondary could be anything, so it becomes `other` rather than a guess.
    """
    kind = FRONT if image.get('type') == 'primary' else OTHER
    return Attachment(
        url=image.get('uri') or '',
        kind=kind,
        width=image.get('width') or None,
        height=image.get('height') or None,
        provenance='discogs',
        source_types=(image.get('type'),) if image.get('type') else (),
    )


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
