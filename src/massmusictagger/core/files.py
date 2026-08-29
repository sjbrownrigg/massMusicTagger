# -*- coding: utf-8 -*-
import os
from pathlib import Path
import shutil
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
import re
from typing import NamedTuple

from massmusictagger.core.cue import CUE, Track
from massmusictagger.sources.discogs.utils import AUDIO_EXTENSIONS, ignored_source_dirs

import logging
logger = logging.getLogger(__name__)


class PrepTask(NamedTuple):
    """Work a source directory needs before it can be tagged."""
    dirpath: str
    kind: str       # 'cue' | 'm4a'
    files: tuple


def _actual_audio_format(path: str) -> str:
    """Return the true audio format of a file by reading its magic bytes.

    Useful when the file extension is wrong (e.g. an APE file named .wav).
    Returns 'wav', 'flac', 'ape', or 'wavpack' when recognised; empty string
    otherwise so callers can fall back to extension-based logic.
    """
    try:
        with open(path, 'rb') as f:
            magic = f.read(4)
        if magic == b'RIFF':
            return 'wav'
        if magic == b'fLaC':
            return 'flac'
        if magic[:3] == b'MAC':   # 'MAC ' — Monkey's Audio
            return 'ape'
        if magic == b'wvpk':
            return 'wavpack'
    except OSError:
        pass
    return ''


def _m4a_codec(path: str) -> str:
    """Return the audio codec inside an M4A/MP4 container.

    .m4a files may hold either ALAC (lossless) or AAC (lossy) audio — the
    extension alone doesn't say which.  mutagen reports the sample-entry atom
    name as MP4Info.codec: 'alac' for ALAC, and 'mp4a.<oti>.<level>' (e.g.
    'mp4a.40.2') for AAC variants.  Returns 'alac', 'aac', or '' when the
    container holds neither (e.g. AC-3) or can't be read.
    """
    try:
        codec = MP4(path).info.codec or ''
    except Exception:
        return ''
    if codec == 'alac':
        return 'alac'
    if codec.startswith('mp4a'):
        return 'aac'
    return ''


def _fssafe(path):
    """Return a UTF-8-safe string representation of a filesystem path.

    os.walk() uses surrogateescape to represent bytes that aren't valid in the
    current locale encoding.  Logging streams reject those surrogate code points
    when encoding to UTF-8.  This helper round-trips the path back through bytes
    and replaces any undecodable sequences with '?' so the message still prints.
    """
    if not isinstance(path, str):
        return str(path)
    try:
        return path.encode('utf-8', errors='surrogateescape').decode('utf-8', errors='replace')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return repr(path)

class FileUtils(object):
    def __init__(self, tagger_config, options):
        self.config = tagger_config
        self.source_dirs = []
        self.cue_done_dir = self.config.get('cue', 'cue_done_dir')
        self.convert_m4a_files = self.config.getboolean('m4a', 'convert_m4a_files')
        self.alac_action = self.config.get('m4a', 'alac_action')
        self.aac_action = self.config.get('m4a', 'aac_action')
        self.m4a_done_dir = self.config.get('m4a', 'm4a_done_dir')
        self.flac_compression_level = self.config.get('conversion', 'flac_compression_level')
        self.mp3_quality = self.config.get('conversion', 'mp3_quality')
        self.ogg_quality = self.config.get('conversion', 'ogg_quality')
        self.done_file = self.config.get("archiving", "done_file")
        self.forceUpdate = options.forceUpdate
        #: A dry run must not touch the source. get_audio_dirs sounds like a
        #: scan but also splits CUE sheets and converts m4a, so without this
        #: --dry-run rewrote the directory it was only meant to report on.
        self.dry_run = getattr(options, 'dry_run', False)

    #: Sources an id.txt may name. A bare ID means discogs, which is what
    #: id.txt meant when discogstagger3 was the only thing reading it.
    ID_SOURCES = ('discogs', 'musicbrainz', 'local')

    def read_id_file(self, dirpath, file_name=None):
        """Return (source, release_id) declared by an id.txt, or (None, None).

        Every shape this file has ever taken is accepted, because they are all
        out there in people's libraries:

            [source]                    discogs_id = 14726546     14726546
            name = discogs
            discogs_id = 14726546

        The first is discogstagger3's. The second is the same thing without
        the section header. The third is a bare ID, which means Discogs --
        what id.txt meant when discogstagger3 was the only reader.

        A named source is read as <name>_id. discogstagger3 went through a
        source.<name> mapping in the main config, so a file could only name a
        source the config had a mapping for, and that mapping's only other job
        was choosing a tag field. Reading it directly lets an id.txt name
        musicbrainz without anything being declared first -- which the reader
        in cascade.py never could: it looked for discogs_id and nothing else.

        Parsed without touching the run configuration. The old implementation
        called self.config.read(idfile), merging each album's id.txt into the
        shared config, so values leaked from one directory into the next.
        """
        idfile = os.path.join(dirpath, file_name or 'id.txt')
        if not os.path.exists(idfile):
            return None, None

        try:
            with open(idfile, encoding='utf-8') as fh:
                lines = fh.read().splitlines()
        except OSError as exc:
            logger.warning('Ignoring unreadable %s: %s', _fssafe(idfile), exc)
            return None, None

        named, pairs, bare = None, {}, None
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if line.startswith('['):
                continue                       # [source] and friends
            if '=' in line:
                key, _, val = line.partition('=')
                key, val = key.strip().lower(), val.strip()
                if key == 'name':
                    named = val.lower()
                elif key.endswith('_id'):
                    pairs[key] = val
            elif bare is None and line.isdigit():
                # A bare ID must look like one. Without this, the first line
                # of any stray text file called id.txt became a release
                # number and the run went off to fetch it.
                bare = line

        source, release_id = None, None
        if named:
            source = named
            release_id = pairs.get(f'{named}_id')
            if not release_id:
                logger.warning('%s names source %r but has no %s_id — ignoring',
                               _fssafe(idfile), named, named)
                return None, None
        else:
            for candidate in self.ID_SOURCES:
                if pairs.get(f'{candidate}_id'):
                    source, release_id = candidate, pairs[f'{candidate}_id']
                    break
            if not release_id and bare:
                source, release_id = 'discogs', bare

        if not release_id:
            logger.warning('%s declares no release ID — ignoring',
                           _fssafe(idfile))
            return None, None
        if source not in self.ID_SOURCES:
            logger.warning('%s names source %r, which is not one of %s — '
                           'ignoring', _fssafe(idfile), source,
                           ', '.join(self.ID_SOURCES))
            return None, None

        logger.info('%s: %s release %s (from %s)', _fssafe(dirpath),
                    source, release_id, file_name or 'id.txt')
        return source, release_id

    def walk_dir_tree(self, start_dir, id_file):
        source_dirs = []
        for root, dirs, files in os.walk(start_dir):
            if id_file in files:
                logger.debug("found %s in %s", id_file, root)
                source_dirs.append(root)

        return source_dirs

    def scan(self, start_dir):
        """Find album directories. Reads; never writes.

        Returns (source_dirs, tasks), where tasks are the transformations
        those directories need before they can be tagged -- CUE sheets to
        split, .m4a files to convert. Running them is prepare()'s job.

        These were one function. get_audio_dirs() walked the tree and split
        and transcoded as it went, so "list the albums" rewrote the library:
        --dry-run destroyed a single-file CUE album while reporting that it
        had changed nothing. Separating them also means a conversion failure
        can be reported as a conversion failure, rather than surfacing later
        as "no audio source directories found".
        """
        parse_cue_files = self.config.getboolean('cue', 'parse_cue_files')
        done_dirs = ignored_source_dirs(self.config)
        source_dirs = []
        tasks = []

        for root, dirs, files in os.walk(start_dir, topdown=True):
            dirs[:] = [d for d in dirs if d not in done_dirs]

            if self.convert_m4a_files:
                m4a_files = [f for f in files if f.endswith('.m4a')]
                if m4a_files:
                    tasks.append(PrepTask(root, 'm4a', tuple(sorted(m4a_files))))

            done = []
            cue_files = []
            audio_files = []
            unwalk = []
            if not self.forceUpdate:
                for dir in dirs:
                    if os.path.exists(os.path.join(root, dir, self.done_file)):
                        done.append(dir)
                if len(done) > 0:
                    dirs[:] = [d for d in dirs if d not in done]

            for file in files:
                if file.endswith('.cue'):
                    cue_files.append(file)
                elif file.endswith(AUDIO_EXTENSIONS):
                    audio_files.append(file)
            for dir in dirs:
                if re.search(r'(?i)^(cd|disc|disk)\s*\d+', dir):
                    logger.debug('Directory has cd/disc/disk subdirectories')
                    unwalk.append(dir)
                    disc_path = os.path.join(root, dir)
                    if self.convert_m4a_files:
                        disc_m4a = [f for f in os.listdir(disc_path)
                                    if f.endswith('.m4a')
                                    and os.path.isfile(os.path.join(disc_path, f))]
                        if disc_m4a:
                            tasks.append(
                                PrepTask(disc_path, 'm4a', tuple(sorted(disc_m4a))))
                    d = Path(disc_path)
                    for file in d.iterdir():
                        if str(file).endswith('.cue'):
                            cue_files.append(str(file))
                        if str(file).endswith(AUDIO_EXTENSIONS):
                            audio_files.append(str(file))
            dirs[:] = [d for d in dirs if d not in unwalk]

            if parse_cue_files and cue_files and len(cue_files) == len(audio_files):
                tasks.append(PrepTask(root, 'cue', tuple(sorted(cue_files))))
                source_dirs.append(root + '/')
            elif audio_files and (self.forceUpdate or self.done_file not in files):
                source_dirs.append(root + '/')
                logger.debug('found audio in %s', _fssafe(root + '/'))

        return source_dirs, tasks

    def prepare(self, tasks, dry_run=False):
        """Run the transformations scan() identified.

        Returns (prepared, failed) as lists of PrepTask. A failure is
        reported and the other tasks still run: one album with a broken CUE
        sheet should not stop the rest of a batch.
        """
        prepared, failed = [], []
        for task in tasks:
            what = ('%d CUE sheet(s)' % len(task.files) if task.kind == 'cue'
                    else '%d .m4a file(s)' % len(task.files))
            if dry_run:
                logger.info('Would convert %s in %s', what, _fssafe(task.dirpath))
                if task.kind == 'cue':
                    # Worth saying plainly: the album is one file until the
                    # sheet is split, so a dry run matches against a single
                    # untagged track and usually reports no match. That is
                    # the dry run being honest about not having written
                    # anything, not a prediction that the real run fails.
                    logger.warning(
                        '%s is a single-file CUE album. A dry run does not '
                        'split it, so there is nothing per-track to match on '
                        'and this will likely report no match — run without '
                        '--dry-run to see the real result.',
                        _fssafe(os.path.basename(task.dirpath.rstrip('/'))))
                continue
            try:
                if task.kind == 'cue':
                    ok = self._processCueFiles(task.dirpath, list(task.files)) == 0
                else:
                    ok = bool(self._processM4aFiles(task.dirpath, list(task.files)))
            except Exception as exc:
                logger.error('Failed preparing %s in %s: %s',
                             what, _fssafe(task.dirpath), exc)
                failed.append(task)
                continue
            (prepared if ok else failed).append(task)
            if not ok:
                logger.error('Could not prepare %s in %s', what,
                             _fssafe(task.dirpath))
        return prepared, failed

    def get_audio_dirs(self, start_dir):
        """scan() then prepare(), which is what this used to be in one pass.

        Kept for callers that want both at once; __main__ runs the two stages
        separately so a dry run can stop after the first.
        """
        source_dirs, tasks = self.scan(start_dir)
        self.prepare(tasks, dry_run=self.dry_run)
        return source_dirs

    def _processCueFiles(self, dir, files):
        """ Process CUE files.  Work out multi-disc sets
        """
        files.sort()
        logger.info('Found %d CUE file(s) in %s', len(files), dir)
        for idx, file in enumerate(files):
            cue_in = os.path.join(dir, file)
            cue = CUE(cue_in)
            if cue.title is not None:
                cue.title = re.sub(r'(?i)\s+(cd|disc)\s*\d+\Z', '', cue.title)
            cue.output_format = str(idx + 1) + '-%n' if len(files) > 1 else '%n'
            if len(files) > 1:
                cue.discnumber = str(idx + 1)
                cue.disctotal = str(len(files))
            result = self._splitCueFile(cue)
            if result != 0:
                logger.error('CUE processing failed for %s', dir)
                return 1

        return 0

    def _processM4aFiles(self, dir, files):
        """ Convert or stash .m4a files according to the configured actions
            for ALAC (lossless) vs AAC (lossy) content.

            ALAC defaults to a lossless transcode to FLAC (matching the
            format the rest of the library standardises on).  AAC defaults
            to being kept and tagged in place — converting lossy audio to
            FLAC would only inflate the file with no quality gain, so that
            combination isn't offered; AAC may instead be re-encoded to
            another lossy format (MP3/Ogg Vorbis) for compatibility.

            Returns True if anything was converted (and so the caller should
            re-scan the directory for the resulting files), False otherwise.
        """
        import subprocess

        encoders = {'mp3': 'libmp3lame', 'ogg': 'libvorbis'}
        converted_any = False

        for file in files:
            path = os.path.join(dir, file)
            codec = _m4a_codec(path)
            if codec == 'alac':
                action = self.alac_action
            elif codec == 'aac':
                action = self.aac_action
            else:
                logger.warning('M4A: could not determine codec for %s — leaving as-is',
                               _fssafe(file))
                continue

            quality_args = []
            if action == 'keep':
                continue
            elif action == 'convert_to_flac':
                target_ext, encoder = 'flac', 'flac'
                quality_args = ['-compression_level', self.flac_compression_level]
            elif action == 'convert_to_mp3':
                target_ext, encoder = 'mp3', encoders['mp3']
                quality_args = ['-q:a', self.mp3_quality]
            elif action == 'convert_to_ogg':
                target_ext, encoder = 'ogg', encoders['ogg']
                quality_args = ['-q:a', self.ogg_quality]
            else:
                logger.warning('M4A: unknown action %r for %s (%s) — leaving as-is',
                               action, _fssafe(file), codec)
                continue

            out = os.path.splitext(path)[0] + '.' + target_ext
            logger.info('M4A: converting %s (%s) → %s (%s)',
                        _fssafe(file), codec, _fssafe(os.path.basename(out)), action)
            cmd = (['ffmpeg', '-y', '-i', path, '-map_metadata', '0', '-c:a', encoder]
                   + quality_args + [out])
            logger.debug('M4A: running %s', ' '.join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error('ffmpeg conversion failed (exit %d):\n%s',
                             result.returncode, result.stderr.strip())
                continue

            done_dir = os.path.join(dir, self.m4a_done_dir)
            Path(done_dir).mkdir(exist_ok=True)
            shutil.move(path, done_dir)
            converted_any = True

        return converted_any

    def _tagFiles(self, cue):
        """ Tags files with the metadata present in cue file
        """
        file_path = cue.image_file_directory
        if cue.disctotal is not None and int(cue.disctotal) > 1:
            file_path = os.path.join(file_path, 'cd' + str(cue.discnumber))
        for track in cue.tracks:
            if track.number is not None:
                src_file_name = cue.discnumber + '-' + str(track.number).zfill(2)+'.flac' if cue.discnumber is not None else str(track.number).zfill(2)+'.flac'
                audio = FLAC(os.path.join(file_path, src_file_name))
                if track.title is not None:
                    audio["title"] = track.title
                # Track-level PERFORMER takes precedence over album-level;
                # fall back to the album PERFORMER when the track has none.
                track_artist = track.performer or cue.performer
                if track_artist:
                    audio["artist"] = track_artist
                # Album-level PERFORMER → albumartist (always, when present)
                if cue.performer:
                    audio["albumartist"] = cue.performer
                if track.number is not None:
                    audio["tracknumber"] = str(track.number)
                if cue.title is not None:
                    audio["album"] = cue.title
                if track.isrc is not None:
                    audio["isrc"] = track.isrc
                if cue.genre is not None:
                    audio["genre"] = cue.genre
                if cue.date is not None:
                    audio["date"] = cue.date
                if cue.discid is not None:
                    audio["discid"] = cue.discid
                if cue.comment is not None:
                    audio["comment"] = cue.comment
                if cue.discnumber is not None:
                    audio["discnumber"] = cue.discnumber
                if cue.disctotal is not None:
                    audio["disctotal"] = cue.disctotal
                # 0th track left blank
                audio["tracktotal"] = str(len(cue.tracks) - 1)

                audio.pprint()
                audio.save()

    def _splitCueFile(self, cue):
        """ Handles the splitting and tidy up of cue files and associated audio
        """
        destination = cue.image_file_directory
        if cue.disctotal is not None and int(cue.disctotal) > 1:
            destination = os.path.join(cue.image_file_directory, 'cd' + str(cue.discnumber))
        p = Path(destination)
        if not p.exists():
            p.mkdir()

        track_count = len([t for t in cue.tracks if t.number is not None])
        disc_label = ' (disc {}/{})'.format(cue.discnumber, cue.disctotal) if cue.discnumber else ''
        logger.info('Splitting "%s"%s — %d tracks → %s',
                    cue.title or os.path.basename(cue.file_name), disc_label,
                    track_count, destination)

        if cue.image_file_name is None:
            logger.error(
                'CUE: cannot locate audio image file — check that the filename '
                'in the FILE directive matches a file in the same directory'
            )
            return 1

        # If the on-disk filename differs from what the CUE FILE directive says
        # (e.g. CIFS encoding mismatch mangled a non-ASCII character), rename
        # the file to restore the match before splitting.
        cue.repair_image_filename()

        import subprocess

        if track_count == 1:
            # A single-track CUE has no split points — shntool split would
            # fail with "no split points given".  The source file is already
            # the complete track; copy or convert it to the expected output
            # name so that tagging and cleanup can proceed normally.
            logger.info('Single-track CUE — skipping split, copying source directly')
            src = str(cue.image_file_name)
            out = os.path.join(destination, '01.flac')
            if src.lower().endswith('.flac'):
                shutil.copy2(src, out)
            else:
                # Use ffmpeg (already a hard dependency) rather than shntool
                # conv so that APE and other formats work without needing the
                # monkeys-audio OS package for this single-track case.
                cmd = ['ffmpeg', '-y', '-i', src, '-c:a', 'flac',
                       '-compression_level', self.flac_compression_level, out]
                logger.debug('CUE: running %s', ' '.join(cmd))
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error('ffmpeg conversion failed (exit %d):\n%s',
                                 result.returncode, result.stderr.strip())
                    return 1
        else:
            # shntool split only has built-in support for FLAC and WAV.
            # For any other format (APE, WavPack, etc.) decode to a temporary
            # WAV first using ffmpeg, which supports all common formats and is
            # already a hard dependency.  This avoids needing monkeys-audio,
            # wavpack, or other format-specific OS packages.
            src_image = str(cue.image_file_name)
            src_ext = os.path.splitext(src_image)[1].lower()
            # Check actual file content — extension may be wrong (e.g. APE named .wav)
            actual_fmt = _actual_audio_format(src_image)
            effective_ext = ('.' + actual_fmt) if actual_fmt else src_ext
            if actual_fmt and actual_fmt != src_ext.lstrip('.'):
                logger.warning(
                    'CUE: image file extension is %s but content is %s — '
                    'using actual format for decode decision',
                    src_ext, actual_fmt,
                )
            native_formats = {'.flac', '.wav'}
            tmp_wav = None

            if effective_ext not in native_formats:
                tmp_wav = src_image.rsplit('.', 1)[0] + '_tmp_decode.wav'
                logger.info('Decoding %s → WAV for shntool (ffmpeg)', effective_ext)
                decode = subprocess.run(
                    ['ffmpeg', '-y', '-i', src_image, tmp_wav],
                    capture_output=True, text=True,
                )
                if decode.returncode != 0:
                    logger.error('ffmpeg decode failed (exit %d):\n%s',
                                 decode.returncode, decode.stderr.strip())
                    return 1
                src_image = tmp_wav

            cmd = [
                'shntool', 'split',
                '-f', str(cue.file_name),
                src_image,
                '-t', cue.output_format,
                '-o', f'flac flac -{self.flac_compression_level} -o %f -',
                '-d', str(destination),
            ]
            logger.debug('CUE: running %s', ' '.join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True)

            if tmp_wav and os.path.exists(tmp_wav):
                os.unlink(tmp_wav)

            if result.returncode != 0:
                logger.error('shntool split failed (exit %d):\n%s',
                             result.returncode, result.stderr.strip())
                return 1

        logger.info('Split complete — tagging %d tracks', track_count)
        self._tagFiles(cue)

        logger.info('Stashing source CUE and image files in %s', self.cue_done_dir)
        done_dir = os.path.join(cue.image_file_directory, self.cue_done_dir)
        Path(done_dir).mkdir(exist_ok=True)
        for file in (cue.file_name, cue.image_file_name):
            dest = Path(done_dir) / Path(file).name
            if dest.exists():
                logger.warning('Overwriting existing stashed file %s', dest)
                dest.unlink()
            shutil.move(str(file), str(dest))
        for f in Path(destination).glob('*00.flac'):
            f.unlink()
        return 0
