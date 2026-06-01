#!/usr/bin/env python3
"""Preview discogstagger3 format string evaluation against fixture cases.

Usage:
    python format_preview.py [--fixtures conf/preview_cases.yaml] [--watch]
"""
import os
import sys
import time
import argparse
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent
DT3_ROOT = REPO_ROOT.parent / 'discogstagger3'
if str(DT3_ROOT) not in sys.path:
    sys.path.insert(0, str(DT3_ROOT))

import yaml
from discogstagger.album import Album, Disc, Track
from discogstagger.tagger_config import TaggerConfig
from discogstagger.taggerutils import TaggerUtils


def _load_config(conf_dir: str) -> TaggerConfig:
    """Load config the same way MMT does: base → personal overlay → extra_configs.

    The personal config (config_personal.yaml) is loaded on top of the base
    config.yaml, then any files listed in extra_configs (including
    formats_personal.ini) are loaded in order.
    """
    cfg = TaggerConfig(os.path.join(conf_dir, 'config.yaml'))

    personal = os.path.normpath(os.path.join(conf_dir, 'config_personal.yaml'))
    if os.path.exists(personal):
        cfg._load_yaml(personal)
        try:
            with open(personal, encoding='utf-8') as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            raw = {}
        # extra_configs entries are relative to the project root (parent of conf/).
        # This mirrors the CWD-first resolution logic in MMT's _load_extra_configs.
        project_root = os.path.dirname(os.path.abspath(conf_dir))
        for entry in (raw.get('extra_configs') or []):
            path = os.path.expanduser(str(entry).strip())
            if not os.path.isabs(path):
                path = os.path.join(project_root, path)
            path = os.path.normpath(path)
            if os.path.exists(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in ('.yaml', '.yml'):
                    cfg._load_yaml(path)
                else:
                    cfg.read(path)
    return cfg


def _build_album(case: dict) -> Album:
    album = Album(
        identifier=case.get('release_id', 0),
        title=case.get('title', 'Unknown Title'),
        artists=[case.get('artist', 'Unknown Artist')],
    )
    album.year = str(case.get('year', ''))
    album.release_date = str(case.get('release_date', case.get('year', '')))
    album.format = case.get('format', '')
    album.format_description = case.get('descriptions', [])
    album.format_names = [album.format] if album.format else []
    album.catnumbers = [case['catno']] if case.get('catno') else []
    album.labels = [case['label']] if case.get('label') else []
    album.disctotal = int(case.get('disctotal', 1))
    album.status = case.get('status', 'Official')
    album.source = case.get('source', 'discogs')
    album.genres = case.get('genres', [])
    album.styles = case.get('styles', [])
    album.is_compilation = bool(case.get('is_compilation', False))
    album.release_type = case.get('releasetype', 'Album')
    album.quality = case.get('quality', '')
    album.codec = case.get('codec', 'flac')

    track = Track(
        tracknumber=1,
        title=case.get('track_title', 'Track 1'),
        artists=[case.get('artist', 'Unknown Artist')],
    )
    disc = Disc(discnumber=1)
    disc.discsubtitle = case.get('disc_title', '')
    disc.mediatype = album.format
    disc.tracks = [track]
    album.discs = [disc]
    return album


def _resolve_format_string(cfg: TaggerConfig, fmt: str) -> tuple:
    """Return (label, raw_format_string).

    If fmt contains no %, $, or spaces it may be a [file-formatting] key —
    look it up. Otherwise use it as-is.
    """
    if not any(c in fmt for c in ('%', '$', ' ')):
        try:
            raw = cfg.get('file-formatting', fmt)
            if raw:
                return fmt, raw
        except Exception:
            pass
    return fmt, fmt


def _run_preview(fixtures_path: str, conf_dir: str) -> None:
    with open(fixtures_path, encoding='utf-8') as f:
        data = yaml.safe_load(f)

    format_strings = data.get('format_strings', [])
    cases = data.get('cases', [])
    cfg = _load_config(conf_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        for case in cases:
            print(f"\n=== {case.get('name', 'Unnamed')} ===")
            album = _build_album(case)
            try:
                tu = TaggerUtils(tmpdir, tmpdir, cfg, album)
            except Exception as e:
                print(f'  <init error: {e}>')
                continue
            for fmt in format_strings:
                label, raw = _resolve_format_string(cfg, str(fmt))
                try:
                    result = tu._value_from_tag(raw, discno=1, trackno=1,
                                                filetype='.flac')
                except Exception as e:
                    result = f'<ERROR: {e}>'
                print(f'  {str(label):<22}  →  {result}')


def _watch_loop(fixtures_path: str, conf_dir: str, interval: float) -> None:
    watch_files = [
        fixtures_path,
        os.path.join(conf_dir, 'formats.ini'),
        os.path.join(conf_dir, 'formats_personal.ini'),
        os.path.join(conf_dir, 'config.yaml'),
        os.path.join(conf_dir, 'config_personal.yaml'),
    ]
    print(f'Watching {len(watch_files)} files. Ctrl-C to stop.\n')

    def _mtimes():
        return {f: os.stat(f).st_mtime for f in watch_files if os.path.exists(f)}

    last = {}
    try:
        while True:
            cur = _mtimes()
            if cur != last:
                if last:
                    changed = [os.path.basename(f) for f in cur
                               if cur.get(f) != last.get(f)]
                    print(f'\n--- changed: {", ".join(changed)} ---')
                last = cur
                try:
                    _run_preview(fixtures_path, conf_dir)
                except Exception as e:
                    print(f'<preview error: {e}>')
            time.sleep(interval)
    except KeyboardInterrupt:
        print('\nDone.')


def main():
    default_fixtures = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'conf', 'preview_cases.yaml')
    default_conf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'conf')

    p = argparse.ArgumentParser(
        description='Preview discogstagger3 format string evaluation')
    p.add_argument('--fixtures', '-f', default=default_fixtures,
                   help='YAML fixture file (default: conf/preview_cases.yaml)')
    p.add_argument('--conf', '-c', default=default_conf,
                   help='conf/ directory (default: massMusicTagger/conf/)')
    p.add_argument('--watch', '-w', action='store_true',
                   help='Re-run when any watched file changes')
    p.add_argument('--interval', type=float, default=0.5,
                   help='Watch poll interval in seconds (default: 0.5)')
    args = p.parse_args()

    if args.watch:
        _watch_loop(args.fixtures, args.conf, args.interval)
    else:
        _run_preview(args.fixtures, args.conf)


if __name__ == '__main__':
    main()
