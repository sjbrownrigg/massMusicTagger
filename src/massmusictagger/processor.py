"""Mass processing engine.

Orchestrates the tag-and-file workflow across a list of source directories,
with concurrent execution, rich progress display, and a structured audit log.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import musicbrainzngs
from rich.console import Console
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
    TaskProgressColumn, TextColumn, TimeElapsedColumn,
)
from rich.table import Table

from massmusictagger.core import cpuguard

if TYPE_CHECKING:
    from massmusictagger.core.tagger_config import TaggerConfig

logger = logging.getLogger(__name__)


console = Console(stderr=True)


def _is_ebusy(exc: BaseException) -> bool:
    """Return True if exc or any chained cause is OSError(EBUSY=16)."""
    import errno as _errno
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, OSError) and e.errno == _errno.EBUSY:
            return True
        e = e.__cause__ or e.__context__
    return False

# Outcome constants written to the audit log
OUTCOME_OK      = 'ok'
OUTCOME_FAILED  = 'failed'
OUTCOME_SKIPPED = 'skipped'
OUTCOME_DRY_RUN = 'dry_run'


def _split_source_id(value):
    """Split "musicbrainz:<mbid>" into ("musicbrainz", "<mbid>").

    --releaseid was Discogs-only when it was written, so a bare value still
    means "whichever source is tried first" and keeps working. Qualifying it
    matters now that the sources have separate numbering: a Discogs release
    number handed to MusicBrainz is not a near miss, it is a different
    namespace.
    """
    if not value:
        return None, None
    text = str(value).strip()
    for source in ('discogs', 'musicbrainz', 'local'):
        if text.lower().startswith(source + ':'):
            return source, text[len(source) + 1:].strip()
    return None, text


class ProcessingResult:
    __slots__ = ('sourcedir', 'outcome', 'source', 'release_id', 'release_url',
                 'title', 'albumartist', 'elapsed', 'error', 'target_dir',
                 'archive_path')

    def __init__(self, sourcedir: str):
        self.sourcedir = sourcedir
        self.outcome: str = OUTCOME_FAILED
        self.source: Optional[str] = None
        self.release_id: Optional[str] = None
        self.release_url: Optional[str] = None
        self.title: Optional[str] = None
        self.albumartist: Optional[str] = None
        self.target_dir: Optional[str] = None
        self.archive_path: Optional[str] = None
        self.elapsed: float = 0.0
        self.error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            'sourcedir':   self.sourcedir,
            'outcome':     self.outcome,
            'source':      self.source,
            'release_id':  self.release_id,
            'release_url': self.release_url,
            'albumartist': self.albumartist,
            'title':       self.title,
            'target_dir':  self.target_dir,
            'archive_path': self.archive_path,
            'elapsed':     round(self.elapsed, 2),
            'error':       self.error,
            'timestamp':   datetime.now(timezone.utc).isoformat(),
        }


def _expand_move_template(template: str, tu, sourcedir: str) -> str:
    """Expand source_move_template into a relative archive path.

    Each path component is sanitised with the same char_profile the
    destination uses -- component by component, because get_clean_filename
    replaces a path separator rather than preserving it, and the template
    contains real separators between %source%, %albumartist% and the rest.

    It was not sanitised at all, despite a docstring here saying it was. The
    destination went to -wumpscut- under char_profile: windows, and the
    archive to :wumpscut: beside it -- the same artist under two names, and a
    path a Windows-hosted share would refuse outright.
    """
    folder = os.path.basename(sourcedir.rstrip('/\\'))
    t = template.replace('%current_folder%', folder)
    # _value_from_tag_format returns the format and its values separately now,
    # because values are handed to the evaluator as data rather than pasted
    # into the string. This template has no $functions, but it does have
    # %variables%, so it goes through the evaluator like any other.
    from massmusictagger.core.naming.stringformatting import StringFormatting
    fmt, values = tu._value_from_tag_format(t)
    expanded = StringFormatting().render(fmt, values)

    parts = [p for p in expanded.replace('\\', '/').split('/') if p]
    cleaned = []
    for part in parts:
        try:
            safe = tu.get_clean_filename(part)
        except Exception as exc:
            logger.debug('Could not sanitise %r: %s', part, exc)
            safe = part
        # Only a string is an answer. A stand-in TaggerUtils answers an
        # unrecognised call with another stand-in, which os.path.join will
        # happily turn into a directory named after it.
        cleaned.append(safe if isinstance(safe, str) and safe else part)
    return os.path.join(*cleaned) if cleaned else expanded


def _verify_target_or_raise(target_dir: Optional[str]) -> None:
    """Raise RuntimeError if the tagged output directory contains no audio files.

    Uses os.walk so multi-disc albums with audio in subdirectories (split_discs)
    are handled correctly.
    """
    from massmusictagger.sources.discogs.utils import AUDIO_EXTENSIONS
    if not target_dir or not os.path.isdir(target_dir):
        raise RuntimeError(
            f'source_action remove/move: target directory not found: {target_dir!r}')
    for _root, _dirs, files in os.walk(target_dir):
        if any(f.lower().endswith(AUDIO_EXTENSIONS) for f in files):
            return
    raise RuntimeError(
        f'source_action remove/move: no audio files found in target: {target_dir!r}')


def _cleanup_empty_parents(path: str, root: str) -> None:
    """Remove now-empty parent directories of `path`, stopping at `root`.

    Used after source_action=remove/move so that an artist/label folder
    left empty by removing its last release doesn't linger in source_dir.
    """
    root = os.path.normpath(root)
    current = os.path.normpath(path)
    while True:
        parent = os.path.dirname(current)
        if parent == current or parent == root or not parent.startswith(root + os.sep):
            break
        try:
            if os.listdir(parent):
                break
            os.rmdir(parent)
            logger.info('Removed empty source directory: %s', parent)
        except OSError:
            break
        current = parent



def _stage_root(cfg) -> str:
    """The configured staging directory, or '' when staging is off."""
    try:
        raw = cfg.get('batch', 'staging_dir') or ''
    except Exception:
        raw = ''
    return os.path.expanduser(raw.strip())


def _move_staged(staged_dir: str, staging_dest: str, final_dest: str) -> str:
    """Move a finished album out of staging and return its final path.

    *staged_dir* sits under *staging_dest*; the same relative path is
    recreated under *final_dest*, so the format string decides the layout
    exactly as it does without staging.

    A collision is suffixed rather than overwritten. Losing an album to a
    name clash is worse than an odd-looking folder, and the source is not
    archived until this path has been verified to hold audio.
    """
    rel = os.path.relpath(staged_dir, staging_dest)
    target = os.path.join(final_dest, rel)
    if os.path.exists(target):
        n = 2
        while os.path.exists(f'{target} ({n})'):
            n += 1
        target = f'{target} ({n})'
    os.makedirs(os.path.dirname(target) or final_dest, exist_ok=True)
    logger.info('Staging: moving finished album to %s', target)
    shutil.move(staged_dir, target)
    return target


def _post_process_source(result: 'ProcessingResult', cfg, fh, tu) -> None:
    """Apply source_action (done_file / remove / move) after a successful tag."""
    action = (cfg.get('archiving', 'source_action') or 'done_file').lower()
    source_root = os.path.expanduser(cfg.get('common', 'source_dir') or '')

    if action == 'remove':
        _verify_target_or_raise(result.target_dir)
        logger.warning('Removing source directory: %s', result.sourcedir)
        shutil.rmtree(result.sourcedir)
        if source_root:
            _cleanup_empty_parents(result.sourcedir, source_root)
        return

    if action == 'move':
        _verify_target_or_raise(result.target_dir)
        archive_root = os.path.expanduser(
            cfg.get('archiving', 'source_archive_dir') or '')
        if not archive_root:
            logger.warning(
                'source_action=move but source_archive_dir is not set '
                '— falling back to done_file')
        else:
            template = (cfg.get('archiving', 'source_move_template')
                        or '%source%/%albumartist%/%current_folder%')
            rel = _expand_move_template(template, tu, result.sourcedir)
            dest = os.path.join(archive_root, rel)
            if os.path.exists(dest):
                n = 2
                while os.path.exists(f'{dest} ({n})'):
                    n += 1
                dest = f'{dest} ({n})'
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(result.sourcedir, dest)
            result.archive_path = dest
            logger.info('Archived source to: %s', dest)
            if source_root:
                _cleanup_empty_parents(result.sourcedir, source_root)
            return

    # default: done_file
    fh.create_done_file()


class MassProcessor:
    """Process a list of source directories, writing tags and files.

    Parameters
    ----------
    cfg : TaggerConfig
    workers : int
        Number of concurrent worker threads.
    dry_run : bool
        If True, compute what would be done but write nothing.
    review : bool
        If True, pause before each album and ask the user to confirm.
    audit_log_path : str, optional
        JSON file to append processing results to.
    """

    def __init__(self, cfg: 'TaggerConfig', *,
                 workers: int = 1,
                 dry_run: bool = False,
                 review: bool = False,
                 force: bool = False,
                 release_id: Optional[str] = None,
                 audit_log_path: Optional[str] = None):
        self.cfg = cfg
        self.workers = workers

        # Workers overlap waiting on the share; cpu_jobs bounds the CPU-heavy
        # subprocesses they start. Sizing them together multiplies -- see
        # core/cpuguard.py. Configure before any worker runs.
        cpuguard.configure(cfg.get('batch', 'cpu_jobs'))
        self.dry_run = dry_run
        self.review = review
        self.force = force
        #: --releaseid. Skips search entirely for the one directory being
        #: processed, which is why __main__ refuses it for a multi-album run.
        #: An id.txt does the same per directory, and works across a whole
        #: tree in one run; the flag wins where both are present.
        self.release_id_source, self.release_id = _split_source_id(release_id)
        self.audit_log_path = audit_log_path

        # Build connectors and searchers once per session (they hold caches).
        # Use _get_priority() so source.priority list is respected, and fall
        # back gracefully when source.name is absent (e.g. personal config
        # without the defaults baseline loaded).
        from massmusictagger.source_factory import (
            make_discogs_connector, make_discogs_local_connector,
            make_discogs_search, make_mb_connector, make_mb_search,
        )
        from massmusictagger.cascade import _get_priority
        priority = _get_priority(cfg)

        self._discogs_conn = None
        self._discogs_local_conn = None
        self._discogs_search = None
        self._mb_conn = None
        self._mb_search = None

        if any(s in priority for s in ('discogs', 'local', 'auto')):
            self._discogs_conn = make_discogs_connector(cfg)
            self._discogs_local_conn = make_discogs_local_connector(cfg, self._discogs_conn)
            self._discogs_search = make_discogs_search(cfg)

        if any(s in priority for s in ('musicbrainz', 'auto')):
            try:
                self._mb_conn = make_mb_connector(cfg)
                self._mb_search = make_mb_search(cfg, connector=self._mb_conn)
            except ImportError:
                logger.warning('MusicBrainz adapter not available — skipping MB path')

    def process_all(self, source_dirs: list[str], n_ignored: int = 0) -> list[ProcessingResult]:
        """Process all directories, returning a list of results."""
        results: list[ProcessingResult] = []

        # Serial processing when workers=1 (simpler for review mode and debugging)
        if self.workers <= 1 or self.review:
            with _make_progress(len(source_dirs)) as progress:
                task = progress.add_task('Tagging', total=len(source_dirs))
                for sd in source_dirs:
                    result = self._process_one(sd, progress=progress, task=task)
                    results.append(result)
                    progress.advance(task)
        else:
            with _make_progress(len(source_dirs)) as progress:
                task = progress.add_task('Tagging', total=len(source_dirs))
                with ThreadPoolExecutor(max_workers=self.workers) as pool:
                    futures = {pool.submit(self._process_one, sd): sd
                               for sd in source_dirs}
                    for fut in as_completed(futures):
                        result = fut.result()
                        results.append(result)
                        progress.advance(task)

        self._write_audit_log(results)
        self._print_summary(results, n_ignored=n_ignored)
        return results

    def _process_one(self, sourcedir: str, **_) -> ProcessingResult:
        result = ProcessingResult(sourcedir)
        t0 = time.monotonic()

        try:
            # Re-use the session-level config rather than re-reading from disk.
            # Re-reading would drop all extra_configs overrides (credentials,
            # MB settings, personal format strings) loaded at startup.
            cfg = self.cfg

            done_file = cfg.get('archiving', 'done_file') or 'dt.done'
            done_path = os.path.join(sourcedir, done_file)
            if os.path.exists(done_path) and not self.force:
                logger.info('Skipping %s (done file exists)', sourcedir)
                result.outcome = OUTCOME_SKIPPED
                result.elapsed = time.monotonic() - t0
                return result

            # --releaseid wins; otherwise an id.txt in this directory.
            override_source, override_id = self.release_id_source, self.release_id
            if not override_id:
                override_source, override_id = self._id_file_override(sourcedir)

            from massmusictagger.cascade import search_and_map
            match = search_and_map(
                sourcedir, cfg,
                discogs_connector=self._discogs_conn,
                discogs_local_connector=self._discogs_local_conn,
                discogs_search=self._discogs_search,
                mb_connector=self._mb_conn,
                mb_search=self._mb_search,
                release_id_override=override_id,
                release_id_source=override_source,
            )

            if match is None:
                result.outcome = OUTCOME_FAILED
                result.error = 'No match found'
                result.elapsed = time.monotonic() - t0
                return result

            album, connector = match

            # Image source preference: may override album.attachments and the
            # connector used for downloading, independently of metadata source.
            connector = self._apply_image_source(album, connector, sourcedir, cfg)
            result.source = getattr(album, 'source', None)
            result.release_id = str(album.id)
            result.release_url = getattr(album, 'url', None) or None
            result.title = album.title
            result.albumartist = getattr(album, 'artist', None)

            # Log the matched release clearly — mirrors discogstagger3's
            # "Found release ID / Tagging album" log line, gives a clickable
            # URL for quick troubleshooting lookup.
            logger.info('Tagging: "%s – %s"  [%s]',
                        album.artist, album.title,
                        result.release_url or result.release_id or '?')

            # On a compilation, an album artist equal to the first track's
            # artist means the album-level credit was not picked up: the
            # release should be credited to Various, not to whoever happens
            # to be first on it.
            #
            # This used to warn whenever the two matched, on any release,
            # described as "a reliable indicator that a wrong release was
            # matched". It is not: on a single-artist album they match by
            # definition. Measured over this library it fired on 371 of 379
            # albums -- 97% -- which is not a signal, and in a bulk run it
            # buries the warnings that are.
            if album.discs and album.discs[0].tracks and self._is_various(album):
                first_track_artist = album.discs[0].tracks[0].artist or ''
                if (first_track_artist and album.artist
                        and first_track_artist.lower() == album.artist.lower()
                        and len(album.discs[0].tracks) > 1):
                    logger.warning(
                        'Compilation credited to "%s" rather than to a '
                        'various-artists credit — the album-level artist may '
                        'be missing from the release. Check: %s',
                        album.artist,
                        result.release_url or result.release_id or 'unknown',
                    )

            if self.review and not self._confirm(sourcedir, album):
                result.outcome = OUTCOME_SKIPPED
                result.elapsed = time.monotonic() - t0
                return result

            final_destdir = os.path.expanduser(
                cfg.get('common', 'dest_dir') or sourcedir)

            # Staging. Tagging otherwise reads the source from the share and
            # writes it back there, then ReplayGain reads the destination
            # again and tagging rewrites it -- every pass crossing the link.
            # Measured NAS-to-NAS: 9.8 MiB/s, against 1280 MiB/s local. With a
            # staging directory the album is copied in once, assembled at
            # local speed, and copied out once.
            staging_root = _stage_root(cfg)
            if staging_root:
                os.makedirs(staging_root, exist_ok=True)
                staging_dest = tempfile.mkdtemp(prefix='mmt-stage-',
                                                dir=staging_root)
                destdir = staging_dest
                logger.info('Staging %s in %s',
                            os.path.basename(sourcedir.rstrip('/\\')),
                            staging_dest)
            else:
                staging_dest = ''
                destdir = final_destdir

            from massmusictagger.core.taggerutils import TaggerUtils, TagHandler, FileHandler
            tu = TaggerUtils(sourcedir, destdir, cfg, album)

            # For MB releases: when compute_edition() finds no keyword match in
            # format_description (it's built for Discogs-style strings like
            # 'Deluxe Edition'), use the MB disambiguation field directly as the
            # edition so it appears in %edition% format strings and folder names.
            # Example: 'Beatport expanded version (US)' won't match keywords but
            # IS the edition and should appear as: Album (Beatport expanded version (US))
            if not tu._edition:
                mb_disambiguation = getattr(album, 'disambiguation', '') or ''
                if mb_disambiguation:
                    tu._edition = mb_disambiguation
                    # Recompute target_dir now that _edition is set (it was computed
                    # in TaggerUtils.__init__ before we had _edition).
                    album.target_dir = tu.dest_dir_name

            tu._get_target_list()

            # Read technical properties (codec, quality, samplerate, …) from the
            # source files now that full_path is set.  Then recompute the target
            # directory name so %codec%, %quality%, etc. resolve correctly in
            # the format string — mirroring discogstagger3's own call order.
            tu.gather_addional_properties()
            album.target_dir = tu.dest_dir_name

            result.target_dir = album.target_dir

            if self.dry_run:
                result.outcome = OUTCOME_DRY_RUN
                result.elapsed = time.monotonic() - t0
                return result

            fh = FileHandler(album, cfg)
            fh.create_album_dir()
            fh.copy_files()
            fh.copy_other_files()

            # existing_tags albums are organised by existing metadata only —
            # no new tag values are written (files are renamed/copied but not
            # re-tagged, so original metadata is preserved intact).
            if album.source != 'existing_tags':
                th = TagHandler(album, cfg)
                th.tag_album()

                if connector:
                    # One path for every source. Artwork follows the Cover Art
                    # Archive convention -- front, back, medium, booklet -- and
                    # anything we could not type becomes image-01, image-02,
                    # which is where Discogs secondary images land.
                    from massmusictagger.image_utils import download_typed_images
                    download_typed_images(album, connector, cfg)

                # Embed cover art
                embed_coverart = (cfg.getboolean('artwork', 'embed_coverart')
                                  if cfg.has_option('artwork', 'embed_coverart') else True)
                if embed_coverart:
                    from massmusictagger.image_utils import embed_typed_images
                    embed_typed_images(album, cfg)
            else:
                logger.info('existing_tags: skipping tag write for %r', album.title)

            fh.add_replay_gain_tags()

            # .nfo and .m3u, in discogstagger3's order: after the images and
            # ReplayGain, before the source is dealt with.
            #
            # massMusicTagger never wrote these -- only discogstagger3's CLI
            # did -- which is the drift you get from two places knowing the
            # assembly order. Guarded individually so a template problem costs
            # you the sidecar file, not the tagged album.
            for kind, write in (('m3u', tu.create_m3u), ('nfo', tu.create_nfo)):
                fmt = (cfg.get('file-formatting', kind) or '').strip()
                if not fmt:
                    logger.debug('%s not written: file-formatting.%s is empty',
                                 kind, kind)
                    continue
                try:
                    write(album.target_dir)
                except Exception as exc:
                    logger.warning('Could not write the .%s for %r: %s',
                                   kind, album.title, exc)

            if staging_dest:
                album.target_dir = _move_staged(
                    album.target_dir, staging_dest, final_destdir)
                result.target_dir = album.target_dir

            # Only now, with the album at its real destination, is it safe to
            # touch the source: _post_process_source verifies result.target_dir
            # holds audio before archiving or deleting anything.
            _post_process_source(result, cfg, fh, tu)

            result.outcome = OUTCOME_OK

        except Exception as exc:
            if _is_ebusy(exc):
                logger.warning(
                    'Cannot tag %s — a file in the output directory is locked by another '
                    'process (EBUSY).  The files have been copied but tags were not written.  '
                    'Close any media player or file manager pointing at that folder, then '
                    'delete the output directory and retry.',
                    os.path.basename(sourcedir.rstrip('/\\')),
                )
                result.error = 'File locked by another process (EBUSY)'
            else:
                logger.error('Failed to process %s: %s', sourcedir, exc, exc_info=True)
                result.error = str(exc)
            result.outcome = OUTCOME_FAILED

        finally:
            # A failed album must not leave gigabytes behind in staging.
            staged = locals().get('staging_dest') or ''
            if staged and os.path.isdir(staged):
                shutil.rmtree(staged, ignore_errors=True)

        result.elapsed = time.monotonic() - t0
        return result

    def _confirm(self, sourcedir: str, album) -> bool:
        """Interactive per-album confirmation (review mode)."""
        table = Table(title=f'Proposed match: {album.title}')
        table.add_column('Field')
        table.add_column('Value')
        table.add_row('Source',  getattr(album, 'source', ''))
        table.add_row('Artist',  album.artist)
        table.add_row('Label',   album.labels[0] if album.labels else '')
        table.add_row('Year',    str(album.year or ''))
        table.add_row('Discs',   str(len(album.discs)))
        table.add_row('Tracks',  str(sum(len(d.tracks) for d in album.discs)))
        console.print(table)
        console.print(f'[dim]Source dir:[/] {sourcedir}')
        while True:
            ans = console.input('[bold]Accept? [Y]es / [n]o / [q]uit:[/] ').strip().lower()
            if ans in ('', 'y', 'yes'):
                return True
            if ans in ('n', 'no'):
                return False
            if ans in ('q', 'quit'):
                raise KeyboardInterrupt

    def _write_audit_log(self, results: list[ProcessingResult]) -> None:
        if not self.audit_log_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.audit_log_path)), exist_ok=True)
        existing: list = []
        if os.path.exists(self.audit_log_path):
            try:
                with open(self.audit_log_path, 'r', encoding='utf-8') as fh:
                    existing = json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        existing.extend(r.as_dict() for r in results)
        with open(self.audit_log_path, 'w', encoding='utf-8') as fh:
            json.dump(existing, fh, indent=2, ensure_ascii=False)
        logger.debug('Audit log updated: %s', self.audit_log_path)

    def _id_file_override(self, sourcedir: str):
        """(source, release_id) from an id.txt in this directory, or (None, None).

        Read per directory rather than once per run: an id.txt sits with the
        release it names, which is the whole point of it -- one run over a
        tree can carry a different explicit ID for every album, where
        --releaseid can only carry one.
        """
        id_file = (self.cfg.get('batch', 'id_file')
                   if self.cfg.has_option('batch', 'id_file') else 'id.txt')
        if not id_file:
            return None, None
        from massmusictagger.core.files import FileUtils

        class _Opts:
            forceUpdate = False
            dry_run = False

        try:
            return FileUtils(self.cfg, _Opts()).read_id_file(sourcedir, id_file)
        except Exception as exc:
            logger.warning('Could not read %s in %s: %s', id_file, sourcedir, exc)
            return None, None

    def _is_various(self, album) -> bool:
        """Is this release credited to more than one artist?

        Either the source said so, or its album artist is whatever the
        configuration calls a various-artists credit.
        """
        if getattr(album, 'is_compilation', False):
            return True
        configured = (self.cfg.get('naming', 'variousartists')
                      if self.cfg.has_option('naming', 'variousartists') else '')
        names = {'various', 'various artists', 'va'}
        if configured:
            names.add(str(configured).strip().lower())
        return (album.artist or '').strip().lower() in names

    def _apply_image_source(self, album, connector, sourcedir: str, cfg) -> object:
        """Override album.attachments and the image connector, per image_source.

        Returns the connector that should be used for image downloading.

        image_source: auto
            Use whichever connector fetched the metadata (no change).
        image_source: musicbrainz
            Fetch the full typed CAA image list.  If the metadata came from
            Discogs, try a barcode-based MBID lookup first; fall back to
            Discogs images if no MBID can be found.
        image_source: discogs
            Use Discogs images even when metadata came from MusicBrainz.
        """
        image_source = (cfg.get('artwork', 'image_source')
                        if cfg.has_option('artwork', 'image_source') else 'auto')

        if image_source == 'auto' or not image_source:
            return connector

        if image_source == 'discogs':
            if self._discogs_conn and album.source != 'discogs':
                logger.info('image_source=discogs: using Discogs images for MB album %r',
                            album.title)
            return self._discogs_conn or connector

        if image_source == 'musicbrainz':
            mb_conn = self._mb_conn
            if not mb_conn:
                logger.warning('image_source=musicbrainz: no MB connector available — '
                               'falling back to %s images', album.source)
                return connector

            # If album came from MusicBrainz we already have the MBID
            if album.source == 'musicbrainz':
                mbid = album.id
            else:
                # Came from Discogs: try to find an MBID via barcode
                mbid = self._find_mbid_for_images(album, sourcedir, cfg)

            if mbid:
                caa_images = mb_conn.fetch_image_list(mbid)
                if caa_images:
                    from massmusictagger.core.attachments import from_caa
                    album.attachments = [from_caa(i) for i in caa_images]
                    logger.info('image_source=musicbrainz: %d CAA image(s) for %r',
                                len(caa_images), album.title)
                    return mb_conn
                logger.info('image_source=musicbrainz: CAA returned no images for %s '
                            '— falling back to %s images', mbid, album.source)
            else:
                logger.info('image_source=musicbrainz: no MBID found for Discogs release %r '
                            '— falling back to Discogs images', album.title)

        return connector

    def _find_mbid_for_images(self, album, sourcedir: str, cfg) -> Optional[str]:
        """Attempt to find a MusicBrainz MBID for a Discogs-sourced album.

        Tries (in order):
          1. Barcode embedded in album.barcode → MB barcode search
          2. Text search (album title + artist) — only if barcode yields nothing

        Returns None when no confident MBID is found.
        """
        # Tier 1: barcode is the fastest and most reliable path
        barcode = getattr(album, 'barcode', '') or ''
        if barcode:
            try:
                barcode_clean = barcode.replace(' ', '').replace('-', '')
                result = musicbrainzngs.search_releases(barcode=barcode_clean, limit=3)
                releases = result.get('release-list', [])
                if releases:
                    mbid = releases[0].get('id')
                    logger.debug('image MBID from barcode %s: %s', barcode_clean, mbid)
                    return mbid
            except Exception as exc:
                logger.debug('Barcode MBID lookup failed: %s', exc)

        # Tier 2: text search (less reliable; skip if no artist/title)
        from rapidfuzz import fuzz
        artist = getattr(album, 'artist', '') or ''
        title  = getattr(album, 'title', '') or ''
        if artist and title:
            try:
                result = musicbrainzngs.search_releases(
                    artist=artist, release=title, limit=5
                )
                for rel in result.get('release-list', []):
                    score = fuzz.token_sort_ratio(
                        title.lower(), rel.get('title', '').lower()
                    )
                    if score >= 80:
                        mbid = rel.get('id')
                        logger.debug('image MBID from text search: %s (score %d)',
                                     mbid, score)
                        return mbid
            except Exception as exc:
                logger.debug('Text MBID lookup failed: %s', exc)

        return None

    @staticmethod
    def _print_summary(results: list[ProcessingResult], n_ignored: int = 0) -> None:
        ok      = sum(1 for r in results if r.outcome == OUTCOME_OK)
        failed  = sum(1 for r in results if r.outcome == OUTCOME_FAILED)
        skipped = sum(1 for r in results if r.outcome == OUTCOME_SKIPPED)
        dry     = sum(1 for r in results if r.outcome == OUTCOME_DRY_RUN)
        total   = len(results)

        # 'ignored' = albums excluded before processing (done file, no id.txt).
        # 'skipped' = albums that reached the processor but were skipped (done file or review reject).
        ignored_part = f'  [dim]{n_ignored} ignored[/]' if n_ignored else ''
        console.print(
            f'\n[bold]Summary:[/] {total} processed — '
            f'[green]{ok} tagged[/]  [yellow]{skipped} skipped[/]  '
            f'[red]{failed} failed[/]  [dim]{dry} dry-run[/]{ignored_part}'
        )

        # Detailed per-album table — one row per processed directory.
        tbl = Table(show_header=True, header_style='bold', box=None,
                    show_edge=False, pad_edge=False, padding=(0, 1))
        tbl.add_column('',         width=2,  no_wrap=True)   # outcome icon
        tbl.add_column('Artist – Title',     no_wrap=False, overflow='fold')
        tbl.add_column('Source',   width=14, no_wrap=True)
        tbl.add_column('ID / URL',           no_wrap=False, overflow='fold')

        # Outcome → (icon, style)
        _style = {
            OUTCOME_OK:      ('✓', 'green'),
            OUTCOME_FAILED:  ('✗', 'red'),
            OUTCOME_SKIPPED: ('–', 'yellow'),
            OUTCOME_DRY_RUN: ('○', 'dim'),
        }

        _source_colour = {
            'discogs':       'cyan',
            'musicbrainz':  'blue',
            'existing_tags': 'dim',
        }

        for r in results:
            icon, style = _style.get(r.outcome, ('?', ''))
            if r.title:
                label = f'{r.albumartist} – {r.title}' if r.albumartist else r.title
            else:
                import os as _os
                label = _os.path.basename(r.sourcedir.rstrip('/\\'))

            source_str = r.source or '—'
            sc = _source_colour.get(source_str, '')
            source_fmt = f'[{sc}]{source_str}[/]' if sc else source_str

            # Prefer release URL; fall back to bare ID
            id_str = r.release_url or r.release_id or '—'

            error_suffix = f'  [red dim]{r.error}[/]' if r.error else ''
            tbl.add_row(
                f'[{style}]{icon}[/]',
                f'[{style}]{label}[/]{error_suffix}',
                source_fmt,
                f'[dim]{id_str}[/]',
            )

        console.print(tbl)


def _make_progress(total: int) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn('[progress.description]{task.description}'),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
