"""Mass processing engine.

Orchestrates the tag-and-file workflow across a list of source directories,
with concurrent execution, rich progress display, and a structured audit log.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from rich.console import Console
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
    TaskProgressColumn, TextColumn, TimeElapsedColumn,
)
from rich.table import Table

if TYPE_CHECKING:
    from discogstagger.tagger_config import TaggerConfig

logger = logging.getLogger(__name__)
console = Console(stderr=True)

# Outcome constants written to the audit log
OUTCOME_OK      = 'ok'
OUTCOME_FAILED  = 'failed'
OUTCOME_SKIPPED = 'skipped'
OUTCOME_DRY_RUN = 'dry_run'


class ProcessingResult:
    __slots__ = ('sourcedir', 'outcome', 'source', 'release_id', 'title',
                 'elapsed', 'error', 'target_dir')

    def __init__(self, sourcedir: str):
        self.sourcedir = sourcedir
        self.outcome: str = OUTCOME_FAILED
        self.source: Optional[str] = None
        self.release_id: Optional[str] = None
        self.title: Optional[str] = None
        self.target_dir: Optional[str] = None
        self.elapsed: float = 0.0
        self.error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            'sourcedir':  self.sourcedir,
            'outcome':    self.outcome,
            'source':     self.source,
            'release_id': self.release_id,
            'title':      self.title,
            'target_dir': self.target_dir,
            'elapsed':    round(self.elapsed, 2),
            'error':      self.error,
            'timestamp':  datetime.now(timezone.utc).isoformat(),
        }


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
                 audit_log_path: Optional[str] = None):
        self.cfg = cfg
        self.workers = workers
        self.dry_run = dry_run
        self.review = review
        self.audit_log_path = audit_log_path

        # Build connectors and searchers once per session (they hold caches)
        from massmusictagger.source_factory import (
            make_discogs_connector, make_discogs_local_connector,
            make_discogs_search, make_mb_connector, make_mb_search,
        )
        source = cfg.get('source', 'name') or 'auto'

        self._discogs_conn = None
        self._discogs_local_conn = None
        self._discogs_search = None
        self._mb_conn = None
        self._mb_search = None

        if source in ('discogs', 'local', 'auto'):
            self._discogs_conn = make_discogs_connector(cfg)
            self._discogs_local_conn = make_discogs_local_connector(cfg, self._discogs_conn)
            self._discogs_search = make_discogs_search(cfg)

        if source in ('musicbrainz', 'auto'):
            try:
                self._mb_conn = make_mb_connector(cfg)
                self._mb_search = make_mb_search(cfg)
            except ImportError:
                logger.warning('MusicBrainz adapter not available — skipping MB path')

    def process_all(self, source_dirs: list[str]) -> list[ProcessingResult]:
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
        self._print_summary(results)
        return results

    def _process_one(self, sourcedir: str, **_) -> ProcessingResult:
        result = ProcessingResult(sourcedir)
        t0 = time.monotonic()

        try:
            from discogstagger.tagger_config import TaggerConfig
            cfg = TaggerConfig(self.cfg.source_conffile)

            done_file = cfg.get('details', 'done_file') or 'dt.done'
            done_path = os.path.join(sourcedir, done_file)
            if os.path.exists(done_path):
                logger.info('Skipping %s (done file exists)', sourcedir)
                result.outcome = OUTCOME_SKIPPED
                result.elapsed = time.monotonic() - t0
                return result

            from massmusictagger.cascade import search_and_map
            match = search_and_map(
                sourcedir, cfg,
                discogs_connector=self._discogs_conn,
                discogs_local_connector=self._discogs_local_conn,
                discogs_search=self._discogs_search,
                mb_connector=self._mb_conn,
                mb_search=self._mb_search,
            )

            if match is None:
                result.outcome = OUTCOME_FAILED
                result.error = 'No match found'
                result.elapsed = time.monotonic() - t0
                return result

            album, connector = match
            result.source = getattr(album, 'source', None)
            result.release_id = str(album.id)
            result.title = album.title

            if self.review and not self._confirm(sourcedir, album):
                result.outcome = OUTCOME_SKIPPED
                result.elapsed = time.monotonic() - t0
                return result

            destdir = cfg.get('common', 'dest_dir') or sourcedir

            from discogstagger.taggerutils import TaggerUtils, TagHandler, FileHandler
            tu = TaggerUtils(sourcedir, destdir, cfg, album)
            tu._get_target_list()
            result.target_dir = album.target_dir

            if self.dry_run:
                result.outcome = OUTCOME_DRY_RUN
                result.elapsed = time.monotonic() - t0
                return result

            fh = FileHandler(album, cfg)
            fh.create_album_dir()
            fh.copy_files()
            fh.copy_other_files()

            th = TagHandler(album, cfg)
            th.tag_album()

            if connector:
                fh.get_images(connector)
            fh.embed_coverart_album()
            fh.add_replay_gain_tags()
            fh.create_done_file()

            result.outcome = OUTCOME_OK

        except Exception as exc:
            logger.error('Failed to process %s: %s', sourcedir, exc, exc_info=True)
            result.outcome = OUTCOME_FAILED
            result.error = str(exc)

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

    @staticmethod
    def _print_summary(results: list[ProcessingResult]) -> None:
        ok = sum(1 for r in results if r.outcome == OUTCOME_OK)
        failed = sum(1 for r in results if r.outcome == OUTCOME_FAILED)
        skipped = sum(1 for r in results if r.outcome == OUTCOME_SKIPPED)
        dry = sum(1 for r in results if r.outcome == OUTCOME_DRY_RUN)
        total = len(results)
        console.print(
            f'\n[bold]Summary:[/] {total} processed — '
            f'[green]{ok} ok[/]  [red]{failed} failed[/]  '
            f'[yellow]{skipped} skipped[/]  [dim]{dry} dry-run[/]'
        )
        if failed:
            console.print('[red]Failed directories:[/]')
            for r in results:
                if r.outcome == OUTCOME_FAILED:
                    console.print(f'  [red]{r.sourcedir}[/]: {r.error}')


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
