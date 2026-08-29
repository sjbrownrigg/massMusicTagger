"""massMusicTagger — multi-source mass audio tagger.

CLI entry point for the 'mmt' command.
"""
from __future__ import annotations

import argparse
import logging
import re
import os
import shutil
import sys

from massmusictagger.config_schema import ConfigError
from massmusictagger import roots, __version__

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='mmt',
        description=(
            'massMusicTagger — tag audio files from Discogs and/or MusicBrainz. '
            'By default tries Discogs first then falls back to MusicBrainz (--source auto).'
        ),
    )
    p.add_argument('--version', action='version',
                   version=f'massMusicTagger {__version__}')
    p.add_argument('--new-config', dest='new_config', nargs='?',
                   const=roots.config_dir(), metavar='DIR',
                   help='Write a fresh config.yaml and formats.ini into DIR '
                        'and exit. Defaults to the configuration directory, '
                        'so plain --new-config sets you up where the next run '
                        'will look. Existing files are never overwritten.')
    p.add_argument('--migrate-config', dest='migrate_config', nargs='?',
                   const='', metavar='DIR',
                   help='Move settings that changed section in 3.0.0 into '
                        'their new homes, in place. Writes a .bak first. '
                        'Defaults to the configuration directory in use.')
    p.add_argument('--force-new-config', dest='force_new_config',
                   action='store_true',
                   help='With --new-config, overwrite files that already exist. '
                        'This discards credentials and format strings.')
    p.add_argument('-r', '--releaseid',
                   default=None,
                   metavar='ID',
                   help='Override: use this release ID instead of searching. '
                        'Qualify it with a source when the ID is not a Discogs '
                        'release number, e.g. musicbrainz:<mbid>. For a whole '
                        'tree, put an id.txt beside each release instead.')
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


def _parse_level(value, default=logging.INFO) -> int:
    """Accept a level name or a number, as the logging module itself does."""
    if value is None or value == '':
        return default
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    resolved = logging.getLevelName(text.upper())
    if isinstance(resolved, int):
        return resolved
    logger.warning('logging.level %r is not a level name or number — '
                   'using INFO', value)
    return default


def _setup_logging(verbose: bool, log_file: str | None = None,
                   configured_level: str | None = None) -> None:
    """Console and file logging.

    logging.level was in the schema and nothing read it, so setting it did
    nothing at all. It matters for a daemon: the container runs mmt -w with
    no tty and no way to pass -v, so the config file is the only place the
    level can come from. -v still wins, being the more immediate instruction.
    """
    level = logging.DEBUG if verbose else _parse_level(configured_level)
    full_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    datefmt  = '%Y-%m-%d %H:%M:%S'

    # Use RichHandler for console output so log messages are queued by Rich
    # and rendered cleanly above the progress bar rather than interleaving.
    from rich.logging import RichHandler
    from massmusictagger.processor import console as _console
    rich_handler = RichHandler(
        level=level,
        console=_console,        # same console used by the progress bar
        show_time=True,
        show_path=False,
        markup=False,
        rich_tracebacks=False,
    )
    logging.basicConfig(
        level=level,
        format='%(message)s',    # RichHandler adds its own timestamp/level
        datefmt=datefmt,
        handlers=[rich_handler],
        force=True,              # override any handlers added by imported libs
    )

    if log_file:
        log_file = os.path.expanduser(log_file)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setLevel(logging.DEBUG)   # file always captures DEBUG for troubleshooting
            fh.setFormatter(logging.Formatter(full_fmt, datefmt=datefmt))
            logging.getLogger().addHandler(fh)
            logging.getLogger(__name__).info('Logging to file: %s', log_file)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                'Could not set up log file %s (%s) — logging to console only', log_file, exc
            )

    # musicbrainzngs logs INFO for every unrecognised XML attribute in the MB
    # API response (e.g. 'uncaught attribute type-id').  These are harmless
    # library-version-lag messages — suppress to WARNING so they don't clutter
    # the output.  Actual warnings and errors from the library still show.
    logging.getLogger('musicbrainzngs').setLevel(logging.WARNING)


def _validate_config(cfg, config_path: str, source_arg: str | None = None) -> list[tuple[str, str]]:
    """Check all required settings immediately after loading.

    Returns a list of (level, message) tuples — collect all problems so the
    user sees every issue in one run, not one at a time.  Call before any
    processing; print errors and exit if any have level 'ERROR'.
    """
    from massmusictagger.core.tagger_config import extract_sample_section
    from massmusictagger.cascade import _get_priority

    here = os.path.dirname(os.path.abspath(__file__))
    sample = os.path.abspath(os.path.join(here, '..', '..', 'conf', 'config_sample.yaml'))

    issues: list[tuple[str, str]] = []

    # Credentials that discogstagger3 will accept from the environment at
    # connect time. Validation has to honour the same overrides, or a container
    # passing DISCOGS_USER_TOKEN -- which is exactly what compose.yaml does --
    # is refused at startup for a credential it does in fact have.
    _ENV_OVERRIDES = {
        ('discogs', 'user_token'):       'DISCOGS_USER_TOKEN',
        ('discogs', 'consumer_key'):     'DISCOGS_CONSUMER_KEY',
        ('discogs', 'consumer_secret'):  'DISCOGS_CONSUMER_SECRET',
        ('musicbrainz', 'acoustid_api_key'): 'ACOUSTID_API_KEY',
        ('musicbrainz', 'acoustid_submitter_key'): 'ACOUSTID_SUBMITTER_KEY',
    }

    def _get(section, key):
        env_name = _ENV_OVERRIDES.get((section, key))
        if env_name:
            from_env = (os.environ.get(env_name) or '').strip()
            if from_env:
                return from_env
        try:
            v = cfg.get(section, key)
            return (v or '').strip()
        except Exception:
            return ''

    def _issue(level, section, key, detail=''):
        snippet = extract_sample_section(section, sample)
        msg = f"{level}: {section}.{key} is missing or empty."
        if detail:
            msg += f'\n  {detail}'
        if snippet:
            msg += f'\n\n  From conf/config_sample.yaml (section \'{section}\'):\n'
            msg += '\n'.join('    ' + line.rstrip() for line in snippet.splitlines())
        issues.append((level, msg))

    # source_dir — required unless passed as a positional CLI argument
    if not source_arg and not _get('common', 'source_dir'):
        _issue('ERROR', 'common', 'source_dir',
               'Set to the directory containing albums to tag, or pass it as a positional argument.')

    # Per-source credential checks (only for sources in the active priority list)
    priority = _get_priority(cfg)
    if 'discogs' in priority:
        token = _get('discogs', 'user_token')
        ck    = _get('discogs', 'consumer_key')
        cs    = _get('discogs', 'consumer_secret')
        if not (token or (ck and cs)):
            _issue('ERROR', 'discogs', 'user_token',
                   'Discogs is in source.priority but no credentials are set.\n'
                   '  Set discogs.user_token (or consumer_key + consumer_secret) in\n'
                   '  credentials/discogs.yaml, or export DISCOGS_USER_TOKEN.')

    if 'musicbrainz' in priority:
        if not _get('musicbrainz', 'user_agent'):
            _issue('ERROR', 'musicbrainz', 'user_agent',
                   'MusicBrainz is in source.priority but musicbrainz.user_agent is not set.\n'
                   '  Set user_agent in credentials/musicbrainz.yaml.')

    return issues


def _load_side_configs(cfg, primary_config_path: str) -> None:
    """Load the credentials files sitting beside the primary config.

    Every ``credentials/*.yaml`` in the configuration directory is loaded, in
    name order. Nothing has to be listed in config.yaml: with one configuration
    directory there is nowhere else these files can be, so naming them
    individually was a list to keep in sync for no benefit.

    ``extra_configs`` still works and warns, so existing configs keep running.
    Paths in it resolve against the config file's own directory.
    """
    import yaml

    config_dir = os.path.dirname(os.path.abspath(primary_config_path))

    paths = list(roots.discover_credentials(config_dir))
    if paths:
        logger.debug('Credentials discovered: %s', ', '.join(paths))

    try:
        with open(primary_config_path, 'r', encoding='utf-8') as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:
        raw = {}

    legacy = raw.get('extra_configs') or []
    if legacy:
        logger.warning(
            'extra_configs is deprecated and no longer needed: every '
            'credentials/*.yaml beside config.yaml is loaded automatically. '
            'Move these files into %s and remove the setting.',
            os.path.join(config_dir, roots.CREDENTIALS_DIRNAME))

    for entry in legacy:
        path = os.path.expanduser(str(entry).strip())
        if not os.path.isabs(path):
            beside = os.path.normpath(os.path.join(config_dir, path))
            path = beside if os.path.exists(beside) else os.path.normpath(path)
        if path not in paths:
            paths.append(path)

    for path in paths:
        if not os.path.exists(path):
            logger.warning('config: file not found — %s', path)
            continue
        _merge_config_file(cfg, path)


def _merge_config_file(cfg, path: str) -> None:
    """Merge one YAML or INI file into the loaded config."""
    import yaml

    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in ('.yaml', '.yml'):
            with open(path, 'r', encoding='utf-8') as fh:
                data = yaml.safe_load(fh) or {}
            for section, values in data.items():
                if section == 'extra_configs':
                    continue
                if not isinstance(values, (dict, list)):
                    continue
                if not cfg.has_section(section):
                    cfg.add_section(section)
                if isinstance(values, list):
                    for item in values:
                        item = str(item).strip()
                        if item:
                            cfg.set(section, item, None)
                else:
                    for key, val in values.items():
                        cfg.set(section, str(key),
                                None if val is None else str(val))
        else:
            cfg.read(path)
        logger.debug('Loaded config: %s', path)
    except Exception as exc:
        logger.warning('config: failed to load %s: %s', path, exc)

def _drop_empty_sections(text: str) -> str:
    """Remove a section header with no settings under it.

    [details] is empty once everything has moved out, and an empty section is
    not merely untidy -- it reads as though something belongs there. Done by
    walking the lines rather than by regex, so a section at the end of the
    file is handled like any other, which a lookahead pattern was not.
    """
    lines = text.splitlines(keepends=True)
    header_at = [i for i, l in enumerate(lines)
                 if re.match(r'^[a-z_][a-z_0-9-]*:\s*$', l)]
    drop = set()
    for n, i in enumerate(header_at):
        end = header_at[n + 1] if n + 1 < len(header_at) else len(lines)
        has_setting = any(re.match(r'^\s+\S', lines[j]) and
                          not lines[j].lstrip().startswith('#')
                          for j in range(i + 1, end))
        if not has_setting:
            drop.add(i)
    return ''.join(l for i, l in enumerate(lines) if i not in drop)


def _migrate_config(parser, opts):
    """Rewrite a config.yaml for the 3.0.0 section names.

    [details] held 28 keys and was split across [naming], [artwork] and
    [archiving]; a few settings were removed outright. The load-time warnings
    say where each one went, but a configuration of any size is tedious to
    move by hand, and moving it by hand is how a setting gets dropped.

    Line-based on purpose. Round-tripping through a YAML parser would
    reformat the file and discard every comment in it, and these files are
    heavily commented -- that is most of their value.
    """
    from massmusictagger import roots
    from massmusictagger.config_schema import MOVED, REMOVED

    target = opts.migrate_config or roots.config_dir()
    path = os.path.join(os.path.abspath(os.path.expanduser(target)),
                        roots.CONFIG_FILENAME)
    if not os.path.exists(path):
        parser.error(f'No {roots.CONFIG_FILENAME} in {target}')

    with open(path, encoding='utf-8') as fh:
        lines = fh.readlines()

    moved, removed, new_lines, section = [], [], [], None
    buckets = {}
    pending = []          # comment lines that belong to the next setting

    for line in lines:
        stripped = line.strip()
        header = re.match(r'^([a-z_][a-z_0-9-]*):\s*$', line)
        if header:
            section = header.group(1)
            new_lines.extend(pending); pending = []
            new_lines.append(line)
            continue
        setting = re.match(r'^(\s+)([a-z_][a-z_0-9-]*):', line)
        if setting and section:
            key = setting.group(2)
            if (section, key) in REMOVED:
                removed.append(f'{section}.{key}')
                pending = []
                continue
            dest = MOVED.get((section, key))
            if dest:
                moved.append(f'{section}.{key} -> {dest}.{key}')
                buckets.setdefault(dest, []).extend(pending + [line])
                pending = []
                continue
            new_lines.extend(pending); pending = []
            new_lines.append(line)
            continue
        if stripped.startswith('#') or not stripped:
            pending.append(line)     # hold: it may describe a moving setting
            continue
        new_lines.extend(pending); pending = []
        new_lines.append(line)
    new_lines.extend(pending)

    if not moved and not removed:
        print(f'{path} needs no changes.')
        return

    text = ''.join(new_lines)
    for dest, block in buckets.items():
        body = ''.join(block).rstrip('\n') + '\n'
        existing = re.search(rf'^{dest}:\s*$', text, re.M)
        if existing:
            text = text[:existing.end() + 1] + body + text[existing.end() + 1:]
        else:
            rule = '# ' + '\u2500' * 77 + '\n'
            text = text.rstrip('\n') + f'\n\n{rule}{dest}:\n{rule}\n{body}'

    text = _drop_empty_sections(text)

    backup = path + '.bak'
    os.replace(path, backup)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)

    print(f'Migrated {path}')
    print(f'  previous version kept at {backup}')
    for m in moved:
        print(f'  moved   {m}')
    for r in removed:
        print(f'  removed {r} -- {REMOVED[tuple(r.split(".", 1))]}')
    print('\nRun massMusicTagger once to confirm it loads without warnings.')


def _new_config(parser, opts):
    """Scaffold a fresh configuration and print what to do next."""
    from massmusictagger.core.tagger_config import write_new_config

    dest = os.path.abspath(os.path.expanduser(opts.new_config))
    try:
        written, skipped = write_new_config(dest, force=opts.force_new_config)
    except OSError as exc:
        parser.error(f"Could not write the new config: {exc}")

    # massMusicTagger's own sample documents the settings discogstagger3's
    # does not -- source priority, MusicBrainz, concurrency.
    mmt_sample = _bundled_sample()
    mmt_target = os.path.join(dest, "config.yaml")
    if os.path.exists(mmt_sample) and mmt_target in written:
        shutil.copyfile(mmt_sample, mmt_target)

    creds = os.path.join(dest, roots.CREDENTIALS_DIRNAME)
    os.makedirs(creds, exist_ok=True)

    for name in ('discogs', 'musicbrainz'):
        src = _bundled_sample(f'{name}_sample.yaml')
        dst = os.path.join(creds, f'{name}.yaml')
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copyfile(src, dst)
            written.append(dst)

    for path in written:
        print(f"created  {path}")
    for path in skipped:
        print(f"exists   {path}  (left alone)")

    if not written:
        print(
            "\nNothing written -- every file already exists.\n"
            "  Use --force-new-config to overwrite them, but note that this\n"
            "  discards any credentials and format strings they contain.")
        return 1

    print(f"""
Next:

  1. Edit {mmt_target}
     At minimum set common.source_dir and common.dest_dir.

  2. Put your API tokens in {creds}/
     Every credentials/*.yaml there is loaded automatically -- nothing to
     declare. DISCOGS_USER_TOKEN in the environment overrides the file.

  3. Run it:
       mmt

     That works when the config is in the default location. Elsewhere:
       MMT_CONFIG_DIR={dest} mmt

Paths inside config.yaml resolve against its own directory, so formats.ini is
found because it sits beside it. Move this whole directory anywhere and it
keeps working.
""")
    return 0


def _bundled_sample(name: str = 'config_sample.yaml') -> str:
    """Path to a packaged reference file.

    These are the source --new-config copies from, so they have to be inside
    the package. This used to walk up from __file__ to a repo-root conf/,
    which resolved to nonsense once installed
    (site-packages/massmusictagger/../../conf) -- so --new-config silently
    produced a discogstagger3 config with none of massMusicTagger's settings,
    and skipped the credentials files entirely.
    """
    return os.path.join(roots.BUNDLED_CONF, name)


def _get_source_dirs(cfg, sourcedir_arg: str | None, force: bool = False,
                     dry_run: bool = False) -> tuple[list[str], int]:
    """Return (dirs_to_process, n_ignored).

    dirs_to_process — flat list of audio directories to tag.
    n_ignored       — count of directories that already have a done file and
                      were silently excluded before reaching the processor.
                      Directories that DO reach the processor but are skipped
                      there (e.g. id.txt albums) are NOT counted here —
                      they appear in the processor's own SKIPPED results.

    Delegates to discogstagger3's FileUtils for:
      • CD/Disc subdirectory detection (Liberty/CD1/ → Liberty/)
      • done_file exclusion (get_audio_dirs skips them)
      • CUE directory exclusion
    """
    source_dir = sourcedir_arg or cfg.get('common', 'source_dir') or None
    if source_dir is None:
        logger.error('No source directory specified (use positional arg or config source_dir)')
        sys.exit(1)
    source_dir = os.path.expanduser(source_dir)

    if not os.path.isdir(source_dir):
        logger.error('Source directory does not exist: %s', source_dir)
        sys.exit(1)

    from massmusictagger.sources.discogs.utils import AUDIO_EXTENSIONS
    from massmusictagger.core.files import FileUtils

    _dry_run = dry_run
    id_file = cfg.get('batch', 'id_file') if cfg.has_option('batch', 'id_file') else 'id.txt'
    searchdiscogs = (cfg.getboolean('batch', 'searchdiscogs')
                     if cfg.has_option('batch', 'searchdiscogs') else False)

    class _FakeOptions:
        forceUpdate = force   # when --force, walk past existing .done markers
        releaseid = None
        dry_run = _dry_run    # scanning must not convert or split on a dry run

    fu = FileUtils(cfg, _FakeOptions())

    # If the directory itself has audio (single-album run), process it directly.
    # This also covers the common --force case where the user passes a specific
    # album that already has a done file.
    files_here = os.listdir(source_dir)
    has_audio_here = any(f.lower().endswith(AUDIO_EXTENSIONS) for f in files_here)
    has_id_here = id_file in files_here

    if has_audio_here and not has_id_here and not searchdiscogs:
        return [source_dir], 0

    if has_audio_here and has_id_here:
        return [source_dir], 0

    # Walk for id.txt directories (highest priority).
    id_dirs = fu.walk_dir_tree(source_dir, id_file)
    if has_id_here and source_dir not in id_dirs:
        id_dirs = [source_dir] + id_dirs

    if not searchdiscogs:
        dirs = id_dirs if id_dirs else ([source_dir] if has_audio_here else [])
        return dirs, _count_ignored(source_dir, dirs, cfg, force)

    # searchdiscogs=true: also include audio dirs without an ancestor id.txt.
    # Two stages, deliberately. scan() only reads; prepare() runs the CUE
    # splitting and .m4a conversion it identified, and reports what it did.
    # These used to be one function, so listing the albums rewrote them --
    # and a dry run destroyed a single-file CUE album while reporting that
    # it had changed nothing. It also means a conversion failure reads as a
    # conversion failure, not as 'no audio source directories found'.
    id_dir_set = set(id_dirs)
    scanned, prep_tasks = fu.scan(source_dir)
    if prep_tasks:
        prepared, failed = fu.prepare(prep_tasks, dry_run=dry_run)
        if prepared:
            logger.info('Prepared %d source director%s', len(prepared),
                        'y' if len(prepared) == 1 else 'ies')
        if failed:
            logger.error('%d source director%s could not be prepared and '
                         'will not be tagged', len(failed),
                         'y' if len(failed) == 1 else 'ies')
            unprepared = {t.dirpath.rstrip('/') for t in failed}
            scanned = [d for d in scanned
                       if d.rstrip('/') not in unprepared]
    all_audio = [d.rstrip('/') for d in scanned]
    orphan_audio = [
        d for d in all_audio
        if not any(
            d == id_d or d.startswith(id_d + os.sep)
            for id_d in id_dir_set
        )
    ]
    dirs = id_dirs + orphan_audio
    return dirs, _count_ignored(source_dir, dirs, cfg, force)


def _count_ignored(source_dir: str, source_dirs: list[str], cfg, force: bool) -> int:
    """Count album directories excluded because they already have a done file.

    Only counts directories that are NOT already in source_dirs (those go
    through the processor and are reported as OUTCOME_SKIPPED there).
    Directories at the top of a known CD1/CD2 tree are counted once.
    """
    if force:
        return 0
    done_file = cfg.get('archiving', 'done_file') or 'dt.done'
    src_set = {os.path.normpath(d) for d in source_dirs}
    n = 0
    for root, dirs, files in os.walk(source_dir, topdown=True):
        if root == source_dir:
            continue
        if done_file in files and os.path.normpath(root) not in src_set:
            n += 1
            dirs[:] = []   # don't descend — done dir's children are part of this album
    return n


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
    done_file = os.path.join(dir_path, cfg.get('archiving', 'done_file') or 'dt.done')
    if os.path.exists(done_file):
        os.remove(done_file)
        print(f'Removed done file: {done_file}')
    print('Undo complete.')


def main(argv: list[str] | None = None) -> None:
    """Entry point. Turns a configuration problem into a message, not a stack.

    Config problems are found in two places: _validate_config at startup, and
    later, when something first tries to use a setting -- a rejected Discogs
    token cannot be detected without asking Discogs. The first path already
    printed and exited 78; the second reached the user as a traceback, which
    buries an actionable message under a call stack that is no help to anyone
    reading it.
    """
    try:
        return _main(argv)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(78)   # EX_CONFIG, as the startup validation path uses


def _main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    opts = parser.parse_args(argv)

    # Handled before anything else: the whole point is to work when there is
    # no usable configuration yet.
    if opts.new_config is not None:
        return _new_config(parser, opts)

    if opts.migrate_config is not None:
        return _migrate_config(parser, opts)

    # Show help when invoked with no arguments and no persistent source_dir
    # is configured — avoids a confusing error about missing source directory.
    if (not opts.sourcedir and not opts.watch and not opts.undo):
        config_path = roots.discover_config()
        if config_path:
            try:
                from massmusictagger.core.tagger_config import TaggerConfig
                _cfg = TaggerConfig(config_path)
                _has_source = bool(
                    _cfg.has_option('common', 'source_dir')
                    and (_cfg.get('common', 'source_dir') or '').strip()
                )
            except Exception:
                _has_source = False
        else:
            _has_source = False
        if not _has_source:
            parser.print_help()
            sys.exit(0)

    config_path = roots.discover_config()
    if not config_path:
        expected = os.path.join(roots.config_dir(), roots.CONFIG_FILENAME)
        print(
            f'No configuration found at {expected}\n'
            f'\n'
            f'  Create one:\n'
            f'    mmt --new-config\n'
            f'\n'
            f'  Or point at an existing configuration directory:\n'
            f'    MMT_CONFIG_DIR=/path/to/config mmt\n'
            f'\n'
            f'  Refusing to run: tagging renames and moves files, so it will\n'
            f'  not run against settings you have not reviewed.',
            file=sys.stderr,
        )
        sys.exit(78)  # EX_CONFIG

    from massmusictagger.core.tagger_config import TaggerConfig

    # The user's config is the sole source of settings. Credentials come from
    # credentials/*.yaml beside it, and formats.ini is discovered by
    # TaggerConfig -- nothing needs declaring.
    cfg = TaggerConfig(config_path)
    cfg.source_conffile = config_path
    _load_side_configs(cfg, config_path)

    # Set up logging before validation so validation errors go through the logger.
    _log_file = (cfg.get('logging', 'log_file')
                 if cfg.has_option('logging', 'log_file') else None) or None
    _level = (cfg.get('logging', 'level')
              if cfg.has_option('logging', 'level') else None)
    _setup_logging(opts.verbose, log_file=_log_file, configured_level=_level)

    # Validate all required settings at startup — collect every problem so the
    # user sees them all at once rather than one per run.
    _issues = _validate_config(cfg, config_path, source_arg=opts.sourcedir)
    if _issues:
        for _level, _msg in _issues:
            print(_msg, file=sys.stderr)
        sys.exit(1)

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
        release_id=opts.releaseid,
    )

    if opts.watch:
        _watch_mode(opts, cfg, processor)
    else:
        source_dirs, n_ignored = _get_source_dirs(cfg, opts.sourcedir, force=opts.force,
                                                 dry_run=opts.dry_run)
        if not source_dirs:
            if n_ignored:
                logger.info('All %d album(s) already tagged — nothing to do', n_ignored)
            else:
                logger.warning('No audio source directories found')
            return

        # --releaseid names one release, so it can only mean one album.
        # Applied to a tree it would tag every album found as that release.
        if opts.releaseid and len(source_dirs) > 1:
            print(
                f'--releaseid names a single release, but {len(source_dirs)} '
                f'album directories were found under\n'
                f'  {opts.sourcedir}\n'
                f'\n'
                f'  Point it at one album directory, drop --releaseid to '
                f'search for each, or put an\n'
                f'  id.txt beside each release that needs an explicit ID.',
                file=sys.stderr)
            sys.exit(2)

        from massmusictagger.cascade import _get_priority
        _priority = _get_priority(cfg)
        _ignored_note = f', {n_ignored} previously tagged' if n_ignored else ''
        _flags = (' [DRY RUN]' if opts.dry_run else '') + (' [FORCE]' if opts.force else '')
        logger.info('Processing %d director%s%s | source priority: %s | workers=%d%s',
                    len(source_dirs),
                    'y' if len(source_dirs) == 1 else 'ies',
                    _ignored_note,
                    ' → '.join(_priority) or 'auto',
                    workers,
                    _flags)
        processor.process_all(source_dirs, n_ignored=n_ignored)


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
            source_dirs, n_ignored = _get_source_dirs(cfg, source_root)
            new_dirs = [d for d in source_dirs if d not in processed]
            if new_dirs:
                logger.info('Found %d new director%s to process',
                            len(new_dirs), 'y' if len(new_dirs) == 1 else 'ies')
                processor.process_all(new_dirs, n_ignored=n_ignored)
                processed.update(new_dirs)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info('Watch mode stopped')
    finally:
        observer.stop()
        observer.join()


if __name__ == '__main__':
    main()
