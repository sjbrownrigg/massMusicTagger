# -*- coding: utf-8 -*-
import os
from pathlib import Path
import shutil
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
import re
from massmusictagger.core.cue import CUE, Track
from massmusictagger.sources.discogs.utils import AUDIO_EXTENSIONS, ignored_source_dirs

import logging
logger = logging.getLogger(__name__)


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
        self.done_file = self.config.get("details", "done_file")
        self.forceUpdate = options.forceUpdate
        #: A dry run must not touch the source. get_audio_dirs sounds like a
        #: scan but also splits CUE sheets and converts m4a, so without this
        #: --dry-run rewrote the directory it was only meant to report on.
        self.dry_run = getattr(options, 'dry_run', False)

    def read_id_file(self, dir, file_name, options):
        # read tags from batch file if available
        releaseid = None
        idfile = os.path.join(dir, file_name)
        if os.path.exists(idfile):
            logger.info("reading id file %s in %s", file_name, dir)
            self.config.read(idfile)
            source_type = self.config.get("source", "name")
            id_name = self.config.get("source", source_type)
            releaseid = self.config.get("source", id_name)
        elif options.releaseid:
            releaseid = options.releaseid

        return releaseid

    def walk_dir_tree(self, start_dir, id_file):
        source_dirs = []
        for root, dirs, files in os.walk(start_dir):
            if id_file in files:
                logger.debug("found %s in %s", id_file, root)
                source_dirs.append(root)

        return source_dirs

    def get_audio_dirs(self, start_dir):
        """ Returns a list of directories with audio track to be processed.
            Any CUE files encountered will be split automatically
        """
        parse_cue_files = self.config.getboolean('cue', 'parse_cue_files')
        done_dirs = ignored_source_dirs(self.config)
        source_dirs = []

        for root, dirs, files in os.walk(start_dir, topdown=True):
            dirs[:] = [d for d in dirs if d not in done_dirs]

            if self.convert_m4a_files:
                m4a_files = [f for f in files if f.endswith('.m4a')]
                if m4a_files and self.dry_run:
                    logger.info('Would convert %d .m4a file(s) in %s',
                                len(m4a_files), _fssafe(root))
                elif m4a_files and self._processM4aFiles(root, m4a_files):
                    # Conversions changed the directory contents (originals
                    # moved to m4a_done_dir, new .flac/.mp3/.ogg files added)
                    # — re-read so the audio-file scan below sees the result.
                    # Filter to files only: os.listdir() also returns
                    # subdirectory names, and m4a_done_dir defaults to '.m4a'
                    # — which would otherwise match AUDIO_EXTENSIONS itself.
                    files = [f for f in os.listdir(root)
                             if os.path.isfile(os.path.join(root, f))]

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
                        if disc_m4a and self.dry_run:
                            logger.info('Would convert %d .m4a file(s) in %s',
                                        len(disc_m4a), _fssafe(disc_path))
                        elif disc_m4a:
                            self._processM4aFiles(disc_path, disc_m4a)
                    d = Path(disc_path)
                    for file in d.iterdir():
                        if str(file).endswith('.cue'):
                            cue_files.append(str(file))
                        if str(file).endswith(AUDIO_EXTENSIONS):
                            audio_files.append(str(file))
            dirs[:] = [d for d in dirs if d not in unwalk]
            if parse_cue_files and len(cue_files) > 0 and len(cue_files) == len(audio_files):
                if self.dry_run:
                    logger.info('Would split %d CUE sheet(s) in %s',
                                len(cue_files), _fssafe(root))
                    source_dirs.append(root + '/')
                else:
                    result = self._processCueFiles(root, cue_files)
                    if result == 0:
                        source_dirs.append(root + '/')
            elif len(audio_files) > 0 and (self.forceUpdate or self.done_file not in files):
                source_dirs.append(root + '/')
                logger.debug('found %s in %s', _fssafe(file), _fssafe(root + '/'))

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
