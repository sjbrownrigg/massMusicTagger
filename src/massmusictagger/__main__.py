"""massMusicTagger — multi-source mass audio tagger.

CLI entry point for the 'mmt' command.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='mmt',
        description=(
            'massMusicTagger — tag audio files from Discogs and/or MusicBrainz. '
            'By default tries Discogs first then falls back to MusicBrainz (--source auto).'
        ),
    )
    p.add_argument('-c', '--config',
                   default=None,
                   metavar='CONFIG',
                   help='Path to YAML config file (default: conf/config.yaml next to package)')
    p.add_argument('-r', '--releaseid',
                   default=None,
                   metavar='ID',
                   help='Override: use this release ID instead of searching')
    p.add_argument('-s', '--source',
                   default=None,
                   choices=['auto', 'discogs', 'musicbrainz', 'local'],
                   metavar='SOURCE',
                   help='Metadata source: auto (default) | discogs | musicbrainz | local')
    p.add_argument('-d', '--destination',
                   default=None,
                   metavar='DEST',
                   help='Destination directory (overrides config dest_dir)')
    p.add_argument('-n', '--dry-run',
                   action='store_true',
                   help='Show what would happen without writing anything')
    p.add_argument('--review',
                   action='store_true',
                   help='Interactive per-album confirm before writing')
    p.add_argument('--undo',
                   metavar='DIR',
                   help='Reverse tagging on DIR using the audit log')
    p.add_argument('-w', '--watch',
                   action='store_true',
                   help='Daemon mode: watch source_dir for new albums')
    p.add_argument('--workers',
                   type=int,
                   default=None,
                   metavar='N',
                   help='Concurrent worker threads (default from config, else 1)')
    p.add_argument('-f', '--force',
                   action='store_true',
                   help='Re-tag even if the done_file marker exists')
    p.add_argument('-v', '--verbose',
                   action='store_true',
                   help='Enable debug-level logging')
    p.add_argument('sourcedir',
                   nargs='?',
                   default=None,
                   help='Source directory to tag (overrides config source_dir)')
    return p


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    # musicbrainzngs logs INFO for every unrecognised XML attribute in the MB
    # API response (e.g. 'uncaught attribute type-id').  These are harmless
    # library-version-lag messages — suppress to WARNING so they don't clutter
    # the output.  Actual warnings and errors from the library still show.
    logging.getLogger('musicbrainzngs').setLevel(logging.WARNING)


def _load_extra_configs(cfg, primary_config_path: str) -> None:
    """Load additional config files listed in extra_configs of the primary YAML.

    Paths in extra_configs are resolved relative to the primary config file's
    directory, so you can use bare filenames like 'conf/discogs_personal.yaml'
    regardless of the working directory.

    Supports both YAML (.yaml/.yml) and INI (.ini/.conf) files.
    YAML files with 'extra_configs' are NOT recursed into — one level only.
    """
    import yaml

    try:
        with open(primary_config_path, 'r', encoding='utf-8') as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:
        return

    extra = raw.get('extra_configs') or []
    if not extra:
        return

    config_dir = os.path.dirname(os.path.abspath(primary_config_path))

    for entry in extra:
        path = os.path.expanduser(str(entry).strip())
        if not os.path.isabs(path):
            # Try relative to CWD first (most natural for paths like conf/discogs.yaml).
            # If not found there, try relative to the config file's own directory.
            cwd_path = os.path.normpath(path)
            if not os.path.exists(cwd_path):
                path = os.path.join(config_dir, path)
            else:
                path = cwd_path
        path = os.path.normpath(path)

        if not os.path.exists(path):
            logger.warning('extra_configs: file not found — %s', path)
            continue

        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in ('.yaml', '.yml'):
                cfg._load_yaml(path)
                logger.debug('Loaded extra YAML config: %s', path)
            else:
                cfg.read(path)
                logger.debug('Loaded extra INI config: %s', path)
        except Exception as exc:
            logger.warning('extra_configs: failed to load %s: %s', path, exc)


def _default_config_path() -> str:
    """Return the path to conf/config.yaml relative to this package."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, '..', '..', '..'))
    candidate = os.path.join(repo_root, 'conf', 'config.yaml')
    if os.path.exists(candidate):
        return candidate
    # Fall back to discogstagger3's bundled config
    try:
        import discogstagger
        dt3_conf = os.path.join(os.path.dirname(discogstagger.__file__),
                                '..', 'conf', 'config.yaml')
        if os.path.exists(dt3_conf):
            return dt3_conf
    except ImportError:
        pass
    return candidate


def _get_source_dirs(cfg, sourcedir_arg: str | None) -> list[str]:
    """Return a flat list of audio source directories to process.

    Uses discogstagger3's file utility functions directly (the get_source_dirs
    helper in discogstagger.__main__ is a closure inside main() and not
    importable).
    """
    source_dir = sourcedir_arg or cfg.get('common', 'source_dir') or None
    if source_dir is None:
        logger.error('No source directory specified (use positional arg or config source_dir)')
        sys.exit(1)
    source_dir = os.path.expanduser(source_dir)

    if not os.path.isdir(source_dir):
        logger.error('Source directory does not exist: %s', source_dir)
        sys.exit(1)

    from discogstagger.discogs_utils import AUDIO_EXTENSIONS

    id_file = cfg.get('batch', 'id_file') if cfg.has_option('batch', 'id_file') else 'id.txt'
    searchdiscogs = (cfg.getboolean('batch', 'searchdiscogs')
                     if cfg.has_option('batch', 'searchdiscogs') else False)

    def _walk_id_dirs(start):
        """Return directories that contain the id.txt marker file."""
        result = []
        for root, _dirs, files in os.walk(start):
            if id_file in files:
                result.append(root)
        return result

    cue_done_dir = cfg.get('cue', 'cue_done_dir') if cfg.has_option('cue', 'cue_done_dir') else '.cue'

    def _walk_audio_dirs(start):
        """Return directories that directly contain audio files, skipping cue_done_dir."""
        result = []
        for root, dirs, files in os.walk(start):
            dirs[:] = [d for d in dirs if d != cue_done_dir]
            if any(f.lower().endswith(AUDIO_EXTENSIONS) for f in files):
                result.append(root)
        return result

    def _consolidate_multidisc_roots(audio_dirs: list[str], scan_root: str) -> list[str]:
        """Replace sets of sibling disc directories with their common album parent.

        Multi-disc rips are often stored as:
            Album/
              CD1/ ← audio here
              CD2/ ← audio here

        The walk finds CD1 and CD2 as separate audio dirs, but TaggerUtils needs
        the parent Album/ so it can detect the disc subdirectory structure.

        Rule: when two or more audio dirs share a common parent that:
          (a) contains no audio files of its own, and
          (b) is not the scan root itself
        replace the siblings with that parent.

        Single-child parents (Album/Tracks/) are also promoted so TaggerUtils
        can handle the disc-subdir structure consistently.
        """
        from collections import defaultdict
        by_parent: dict[str, list[str]] = defaultdict(list)
        for d in audio_dirs:
            by_parent[os.path.dirname(d)].append(d)

        def _parent_has_audio(parent: str) -> bool:
            try:
                return any(f.lower().endswith(AUDIO_EXTENSIONS)
                           for f in os.listdir(parent)
                           if os.path.isfile(os.path.join(parent, f)))
            except OSError:
                return False

        # When ALL audio dirs share the same parent AND there are multiple dirs,
        # the scan_root exclusion may be lifted (e.g. user passed Liberty/
        # directly — CD1 and CD2 are both under Liberty/ = scan_root).
        all_share_one_parent = (
            len(audio_dirs) > 1
            and len(set(os.path.dirname(d) for d in audio_dirs)) == 1
        )

        scan_root_abs = os.path.abspath(scan_root) + os.sep

        seen: set[str] = set()
        consolidated: list[str] = []
        for d in audio_dirs:
            if d in seen:
                continue
            parent = os.path.dirname(d)
            parent_abs = os.path.abspath(parent)
            siblings = by_parent[parent]

            # Never promote above the scan root — this would collapse an entire
            # collection into one source dir.
            if not (parent_abs + os.sep).startswith(scan_root_abs) and parent_abs != os.path.abspath(scan_root):
                consolidated.append(d)
                seen.add(d)
                continue

            parent_is_scan_root = (parent_abs == os.path.abspath(scan_root))

            # Promote siblings to parent when:
            #   • parent has no audio files of its own
            #   • parent is not the scan root, OR all dirs share one parent
            #     (user passed this album dir directly and its disc subdirs are
            #     all at the same level as scan_root's children)
            if (not _parent_has_audio(parent)
                    and len(siblings) >= 1
                    and (not parent_is_scan_root or all_share_one_parent)):
                if parent not in seen:
                    consolidated.append(parent)
                    seen.add(parent)
                for sib in siblings:
                    seen.add(sib)
            else:
                consolidated.append(d)
                seen.add(d)
        return consolidated

    # If the directory itself has audio (single-album run), process it directly
    files_here = os.listdir(source_dir)
    has_audio_here = any(f.lower().endswith(AUDIO_EXTENSIONS) for f in files_here)
    has_id_here = id_file in files_here

    if has_audio_here and not has_id_here and not searchdiscogs:
        return [source_dir]

    if has_audio_here and has_id_here:
        return [source_dir]

    # source_dir has no direct audio — keep only the subdirs-with-audio check
    # for the non-search case. The searchdiscogs path handles this via
    # _consolidate_multidisc_roots below.

    # Walk for id.txt directories first
    id_dirs = _walk_id_dirs(source_dir)
    if has_id_here and source_dir not in id_dirs:
        id_dirs = [source_dir] + id_dirs

    if not searchdiscogs:
        return id_dirs if id_dirs else ([source_dir] if has_audio_here else [])

    # searchdiscogs=true: also include audio dirs without an ancestor id.txt,
    # then consolidate siblings into their multi-disc album parent.
    id_dir_set = set(id_dirs)
    raw_audio = [
        d for d in _walk_audio_dirs(source_dir)
        if not any(
            d == id_d or d.startswith(id_d + os.sep)
            for id_d in id_dir_set
        )
    ]
    orphan_audio = _consolidate_multidisc_roots(raw_audio, source_dir)
    return id_dirs + orphan_audio


def _undo(dir_path: str, cfg) -> None:
    """Attempt to reverse tagging on a directory using the audit log."""
    audit_path = cfg.get('batch', 'audit_log') or None
    if audit_path is None:
        print('No audit_log configured — cannot undo.')
        sys.exit(1)
    audit_path = os.path.expanduser(audit_path)
    if not os.path.exists(audit_path):
        print(f'Audit log not found: {audit_path}')
        sys.exit(1)
    import json
    with open(audit_path, 'r', encoding='utf-8') as fh:
        records = json.load(fh)
    matches = [r for r in records
               if r.get('sourcedir') == dir_path and r.get('outcome') == 'ok']
    if not matches:
        print(f'No successful tagging record found for: {dir_path}')
        sys.exit(1)
    record = matches[-1]
    target = record.get('target_dir')
    if not target or not os.path.exists(target):
        print(f'Target directory not found: {target}')
        sys.exit(1)
    import shutil
    print(f'Removing tagged directory: {target}')
    shutil.rmtree(target)
    done_file = os.path.join(dir_path, cfg.get('details', 'done_file') or 'dt.done')
    if os.path.exists(done_file):
        os.remove(done_file)
        print(f'Removed done file: {done_file}')
    print('Undo complete.')


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    opts = parser.parse_args(argv)
    _setup_logging(opts.verbose)

    config_path = opts.config or _default_config_path()
    if not os.path.exists(config_path):
        logger.error('Config file not found: %s', config_path)
        sys.exit(1)

    from discogstagger.tagger_config import TaggerConfig

    # Load massMusicTagger defaults first (lowest priority), then overlay the
    # user's personal config on top so personal values always win.
    # The defaults file is expected at conf/config.yaml alongside the personal config.
    config_dir = os.path.dirname(os.path.abspath(config_path))
    mmt_defaults = os.path.join(config_dir, 'config.yaml')
    if (os.path.exists(mmt_defaults)
            and os.path.abspath(mmt_defaults) != os.path.abspath(config_path)):
        cfg = TaggerConfig(mmt_defaults)    # baseline defaults
        cfg._load_yaml(config_path)         # personal overrides on top
    else:
        cfg = TaggerConfig(config_path)     # personal config is the only source

    cfg.source_conffile = config_path  # used by _load_extra_configs

    # Load extra config files listed in extra_configs.
    # Paths are resolved relative to the primary config file's directory.
    _load_extra_configs(cfg, config_path)

    # CLI overrides
    if opts.source:
        cfg.set('source', 'name', opts.source)
        # Also override the priority list so _get_priority() sees the right source.
        # '--source auto' restores the default priority order from config.
        if opts.source != 'auto':
            cfg.set('source', 'priority', opts.source)
    if opts.destination:
        cfg.set('common', 'dest_dir', opts.destination)
    # --force is passed to MassProcessor; do NOT modify done_file in the config
    # (that would cause FileHandler.create_done_file() to write a file named
    # '__never_matches__' into the sorted directory).

    # ── Undo mode ────────────────────────────────────────────────────────────
    if opts.undo:
        _undo(os.path.expanduser(opts.undo), cfg)
        return

    # ── Normal / watch mode ──────────────────────────────────────────────────
    workers = opts.workers or (
        int(cfg.get('batch', 'workers') or 1)
        if cfg.has_option('batch', 'workers') else 1
    )
    audit_log = cfg.get('batch', 'audit_log') if cfg.has_option('batch', 'audit_log') else None
    if audit_log:
        audit_log = os.path.expanduser(audit_log)

    from massmusictagger.processor import MassProcessor
    processor = MassProcessor(
        cfg,
        workers=workers,
        dry_run=opts.dry_run,
        review=opts.review,
        audit_log_path=audit_log,
        force=opts.force,
    )

    if opts.watch:
        _watch_mode(opts, cfg, processor)
    else:
        source_dirs = _get_source_dirs(cfg, opts.sourcedir)
        if not source_dirs:
            logger.warning('No audio source directories found')
            return
        logger.info('Processing %d director%s with source=%s, workers=%d%s',
                    len(source_dirs),
                    'y' if len(source_dirs) == 1 else 'ies',
                    cfg.get('source', 'name') or 'auto',
                    workers,
                    ' [DRY RUN]' if opts.dry_run else '')
        processor.process_all(source_dirs)


def _watch_mode(opts, cfg, processor) -> None:
    """Daemon mode: poll for new albums in source_dir and process them."""
    from watchdog.observers.polling import PollingObserver
    from watchdog.events import FileSystemEventHandler
    import time

    source_root = opts.sourcedir or cfg.get('common', 'source_dir') or None
    if source_root is None:
        logger.error('Watch mode requires a source directory')
        sys.exit(1)
    source_root = os.path.expanduser(source_root)
    poll_interval = int(cfg.get('common', 'watch_poll_interval') or 30)

    processed: set[str] = set()

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            pass  # We poll rather than react to events (NFS/CIFS safe)

    observer = PollingObserver(timeout=poll_interval)
    observer.schedule(_Handler(), source_root, recursive=True)
    observer.start()
    logger.info('Watching %s (poll interval %ds) — Ctrl-C to stop', source_root, poll_interval)

    try:
        while True:
            source_dirs = _get_source_dirs(cfg, source_root)
            new_dirs = [d for d in source_dirs if d not in processed]
            if new_dirs:
                logger.info('Found %d new director%s to process',
                            len(new_dirs), 'y' if len(new_dirs) == 1 else 'ies')
                processor.process_all(new_dirs)
                processed.update(new_dirs)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info('Watch mode stopped')
    finally:
        observer.stop()
        observer.join()


if __name__ == '__main__':
    main()
