# -*- coding: utf-8 -*-
# CUE sheet parser, originally derived from the lolcut project
# (https://pypi.org/project/lolcut/). Adopted into discogstagger and
# extended with discnumber, disctotal, discid, comment and output_format
# attributes needed for multi-disc CUE processing.
#
# CUE sheet syntax reference: http://digitalx.org/cue-sheet/syntax/

import logging
import os
import codecs
import tempfile

import chardet

logger = logging.getLogger(__name__)

allowed_formats   = ['BINARY', 'MOTOROLA', 'AIFF', 'WAVE', 'MP3', 'FLAC']
allowed_flags     = ['DCP', '4CH', 'PRE', 'SCMS']
allowed_datatypes = [
    'AUDIO', 'CDG', 'MODE1/2048', 'MODE1/2352',
    'MODE2/2336', 'MODE2/2352', 'CDI/2336', 'CDI/2352',
]
allowed_extensions = ('.flac', '.wav', '.ape', '.alac', '.wv')


class Track:
    def __init__(self):
        self.flags      = []
        self.indexes    = []
        self.isrc       = None
        self.performer  = None
        self.pregap     = None
        self.postgap    = None
        self.songwriter = None
        self.title      = None
        self.number     = None
        self.datatype   = None


class CUE:
    def __init__(self, file_name):
        self.file_name      = file_name
        self.file_encoding  = self._detect_encoding()
        self.content        = None
        # discogstagger-specific attributes set by the caller before splitting
        self.output_format  = '%n'
        self.discnumber     = None
        self.disctotal      = None
        self.load()
        self.parse()

    def __str__(self):
        return '\n'.join(self.content)

    def _detect_encoding(self):
        with open(self.file_name, 'rb') as f:
            return chardet.detect(f.read()).get('encoding') or 'utf-8'

    def load(self):
        with open(self.file_name, 'r', encoding=self.file_encoding) as f:
            self.content = [line.replace('/', '\\') for line in f.readlines()]

    def parse(self):
        scope = 'global'
        self.tracks             = []
        self.remarks            = []
        self.catalog_number     = None
        self.cdtext_file_name   = None
        self.image_file_format  = None
        self.image_file_name    = None   # resolved on-disk path
        self.image_file_ref     = None   # intended path as written in FILE directive
        self.image_file_directory = None
        self.performer          = None
        self.songwriter         = None
        self.title              = None
        self.genre              = None
        self.date               = None
        self.discid             = None
        self.comment            = None

        current_track = Track()
        for line in (l.strip() for l in self.content):
            cmd = line.split(' ')[0]

            if cmd == 'CATALOG':
                self.catalog_number = line.split(' ')[1]
                if len(self.catalog_number) != 13:
                    logger.warning('CUE: catalog number has incorrect length')

            elif cmd == 'CDTEXTFILE':
                value = line.split(' ')[1].strip('"')
                self.cdtext_file_name = value

            elif cmd == 'FILE':
                file_name_value = line[5:]
                format_value = file_name_value.split(' ')[-1]
                self.image_file_format = format_value.upper()
                file_name_value = file_name_value[:-(len(format_value) + 1)].strip('"')
                if not os.path.dirname(file_name_value):
                    file_name_value = os.path.join(
                        os.path.dirname(self.file_name), file_name_value)
                self.image_file_directory = os.path.dirname(self.file_name)
                self.image_file_ref = file_name_value  # intended path from FILE directive
                if os.path.exists(file_name_value):
                    self.image_file_name = file_name_value
                else:
                    self.image_file_name = self.locate_image(file_name_value)
                if self.image_file_name is None:
                    logger.warning('CUE: image file not found: %s', file_name_value)
                if self.image_file_format not in allowed_formats:
                    logger.warning('CUE: image format %s is not in allowed list', self.image_file_format)

            elif cmd == 'FLAGS':
                current_track.flags = [x.upper() for x in line.split(' ')[1:]]
                for flag in current_track.flags:
                    if flag not in allowed_flags:
                        logger.warning('CUE: flag %s is not allowed', flag)

            elif cmd == 'INDEX':
                parts = line.split(' ')
                current_track.indexes.append((parts[1], parts[2]))
                idx = int(parts[1])
                if not 0 <= idx <= 99:
                    logger.warning('CUE: index number %s out of range', parts[1])

            elif cmd == 'ISRC':
                current_track.isrc = line.split(' ')[1]
                if len(current_track.isrc) != 12:
                    logger.warning('CUE: ISRC must be 12 characters')

            elif cmd == 'PERFORMER':
                value = line[10:].strip().strip('"')
                if scope == 'global':
                    self.performer = value
                else:
                    current_track.performer = value

            elif cmd == 'POSTGAP':
                current_track.postgap = line.split(' ')[1]

            elif cmd == 'PREGAP':
                current_track.pregap = line.split(' ')[1]

            elif cmd == 'REM':
                self.remarks.append(line[4:])
                if line.startswith('REM GENRE'):
                    self.genre = line[10:]
                elif line.startswith('REM DATE'):
                    self.date = line[9:]
                elif line.startswith('REM DISCID'):
                    self.discid = line[11:]
                elif line.startswith('REM COMMENT'):
                    self.comment = line[12:].strip().strip('"')

            elif cmd == 'SONGWRITER':
                value = line[11:].strip().strip('"')
                if scope == 'global':
                    self.songwriter = value
                else:
                    current_track.songwriter = value

            elif cmd == 'TITLE':
                value = line[6:].strip().strip('"')
                if scope == 'global':
                    self.title = value
                else:
                    current_track.title = value

            elif cmd == 'TRACK':
                scope = 'track'
                self.tracks.append(current_track)
                current_track = Track()
                parts = line.split(' ')
                current_track.number   = int(parts[1])
                current_track.datatype = parts[2].upper()
                if not 1 <= current_track.number <= 99:
                    logger.warning('CUE: track number %d out of range', current_track.number)
                if current_track.datatype not in allowed_datatypes:
                    logger.warning('CUE: track datatype %s is not allowed', current_track.datatype)

        self.tracks.append(current_track)

    def locate_image(self, file_name_value):
        """Find an audio image file when the exact path in the CUE sheet
        cannot be resolved.

        Three strategies are tried in order:

        1. Exact stem prefix match — handles stale extensions (e.g. the image
           was compressed to FLAC after the CUE was written with a .wav name).

        2. ASCII-only stem comparison — handles CIFS/encoding mismatches where
           a non-ASCII character in the CUE filename differs from the same
           character in the on-disk filename (e.g. latin-1 ú vs Windows-1251 ъ
           both stored as byte 0xFA but decoded differently by the OS and the
           CUE parser).

        3. Single-file fallback — if exactly one audio file exists in the
           directory, it must be the image (the caller already verified that
           the CUE count equals the audio file count).
        """
        stem = os.path.splitext(os.path.basename(file_name_value))[0]
        audio_files = [
            os.path.join(self.image_file_directory, f)
            for f in os.listdir(self.image_file_directory)
            if f.endswith(allowed_extensions)
        ]

        # 1. Exact stem prefix match
        for candidate in audio_files:
            if os.path.basename(candidate).startswith(stem) and os.path.exists(candidate):
                return candidate

        # 2. ASCII-only comparison (encoding mismatch tolerance)
        ascii_stem = ''.join(c for c in stem if c.isascii())
        if ascii_stem:
            for candidate in audio_files:
                base = os.path.splitext(os.path.basename(candidate))[0]
                ascii_base = ''.join(c for c in base if c.isascii())
                if ascii_stem == ascii_base and os.path.exists(candidate):
                    logger.info(
                        'CUE: matched image via ASCII-only comparison '
                        '(encoding mismatch): %s', candidate
                    )
                    return candidate

        # 3. Single-file fallback
        existing = [f for f in audio_files if os.path.exists(f)]
        if len(existing) == 1:
            logger.info(
                'CUE: using sole audio file as image (no stem match): %s',
                existing[0]
            )
            return existing[0]

        return None

    def repair_image_filename(self):
        """Rename the on-disk audio image to match the filename in the FILE
        directive when the two differ (e.g. due to a CIFS encoding mismatch
        where a non-ASCII character is stored differently in the CUE text and
        the filesystem).

        Returns True if a rename was performed, False if names already match
        or the repair could not be done.
        """
        if self.image_file_name is None or self.image_file_ref is None:
            return False
        if self.image_file_name == self.image_file_ref:
            return False
        if os.path.basename(self.image_file_name) == os.path.basename(self.image_file_ref):
            return False

        try:
            os.rename(self.image_file_name, self.image_file_ref)
            logger.info(
                'CUE: renamed audio image to match FILE directive:\n'
                '  from: %s\n'
                '    to: %s',
                os.path.basename(self.image_file_name),
                os.path.basename(self.image_file_ref),
            )
            self.image_file_name = self.image_file_ref
            return True
        except OSError as e:
            logger.warning(
                'CUE: could not rename audio image to match FILE directive '
                '(%s) — proceeding with original name', e.strerror
            )
            return False

    def get_temporary_copy(self):
        """Write a UTF-8 temporary copy of the CUE sheet and return its path."""
        fd, fname = tempfile.mkstemp(suffix='.cue', prefix='tmp', dir=None, text=True)
        with codecs.open(fname, encoding='utf-8', mode='w') as f:
            f.writelines(self.content)
        os.close(fd)
        return fname
