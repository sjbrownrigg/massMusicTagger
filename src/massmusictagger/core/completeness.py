"""Is a release complete, by its own metadata?

Compares the audio files present against the `tracktotal` the files carry.
That number came with the rip, so this is a check on the material rather than
on anything the tagger decided, and it can be made before any search runs.

The point of checking early is that an incomplete release should not be tagged
at all. A library that holds whole releases treats a missing track as a defect
to re-acquire; tagging the fragment files it away as though it were the album,
and it stops being visible as a gap.

Three things it has to get right or the answer is noise:

  * `tracktotal` counts one disc, so a multi-disc set is summed per disc;
  * an unsplit CUE image is one file standing for a whole disc -- this runs
    after preparation, so by here the tracks are split and the count is real;
  * a missing `tracktotal` is not evidence of anything, and must not be read
    as "zero expected".
"""
from __future__ import annotations

import logging
import os
from typing import NamedTuple

logger = logging.getLogger(__name__)


class Completeness(NamedTuple):
    """What the files say about themselves."""

    #: True when every disc holds as many files as it says it should.
    complete: bool
    #: False when nothing declared a tracktotal, so there was nothing to check.
    judged: bool
    present: int
    expected: int
    #: (disc, [missing track numbers]) for each disc that is short.
    gaps: tuple
    #: How many discs declared a tracktotal. A gap on a multi-disc release has
    #: to name its disc: "missing 2" is ambiguous when there are two of them,
    #: and which disc is short is the first thing anyone re-acquiring needs.
    discs: int = 1

    def describe(self) -> str:
        if not self.judged:
            return 'no tracktotal in the files'
        if self.complete:
            return '%d of %d' % (self.present, self.expected)
        parts = []
        for disc, missing in self.gaps:
            nums = ', '.join(str(n) for n in missing[:8])
            if len(missing) > 8:
                nums += ', …'
            parts.append(('disc %d: ' % disc if self.discs > 1 else '') + nums)
        detail = '; missing %s' % '; '.join(parts) if parts else ''
        return '%d of %d%s' % (self.present, self.expected, detail)


def assess(audio_files) -> Completeness:
    """Read every file's disc, track and tracktotal, and compare."""
    from massmusictagger.core.mediafile import MediaFile

    per_disc_expected: dict[int, int] = {}
    per_disc_seen: dict[int, set] = {}
    present = 0

    for path in audio_files:
        present += 1
        try:
            meta = MediaFile(path)
        except Exception as exc:
            logger.debug('Completeness: could not read %s (%s)', path, exc)
            continue
        try:
            disc = int(getattr(meta, 'disc', None) or 1)
        except (TypeError, ValueError):
            disc = 1
        total = getattr(meta, 'tracktotal', None)
        if total:
            try:
                per_disc_expected[disc] = max(int(total),
                                              per_disc_expected.get(disc, 0))
            except (TypeError, ValueError):
                pass
        number = getattr(meta, 'track', None)
        if number:
            try:
                per_disc_seen.setdefault(disc, set()).add(int(number))
            except (TypeError, ValueError):
                pass

    if not per_disc_expected:
        return Completeness(True, False, present, 0, (), 1)

    expected = sum(per_disc_expected.values())
    gaps = []
    for disc, want in sorted(per_disc_expected.items()):
        missing = sorted(set(range(1, want + 1)) - per_disc_seen.get(disc, set()))
        if missing:
            gaps.append((disc, missing))

    return Completeness(present == expected, True, present, expected,
                        tuple(gaps), len(per_disc_expected))


def enabled(cfg) -> bool:
    try:
        return cfg.getboolean('batch', 'completeness_guard')
    except Exception:
        return False
