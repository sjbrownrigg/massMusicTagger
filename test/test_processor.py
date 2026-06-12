"""Unit tests for processor module helpers."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call

import pytest

from massmusictagger.processor import (
    ProcessingResult,
    _cleanup_empty_parents,
    _expand_move_template,
    _post_process_source,
    _verify_target_or_raise,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_cfg(action='done_file', archive_dir='', template='', source_dir=''):
    cfg = MagicMock()
    def _get(section, key):
        return {
            ('details', 'source_action'):       action,
            ('details', 'source_archive_dir'):  archive_dir,
            ('details', 'source_move_template'): template,
            ('common', 'source_dir'):           source_dir,
        }.get((section, key), '')
    cfg.get.side_effect = _get
    return cfg


def _make_result(sourcedir='/src/Album', target_dir='/dest/Album'):
    r = ProcessingResult(sourcedir)
    r.target_dir = target_dir
    return r


# ─────────────────────────────────────────────────────────────────────────────
# ProcessingResult
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessingResult:
    def test_archive_path_defaults_none(self):
        r = ProcessingResult('/src/test')
        assert r.archive_path is None

    def test_archive_path_in_as_dict(self):
        r = ProcessingResult('/src/test')
        r.archive_path = '/archive/discogs/Artist/Album'
        d = r.as_dict()
        assert d['archive_path'] == '/archive/discogs/Artist/Album'

    def test_archive_path_none_in_as_dict(self):
        r = ProcessingResult('/src/test')
        assert r.as_dict()['archive_path'] is None


# ─────────────────────────────────────────────────────────────────────────────
# _expand_move_template
# ─────────────────────────────────────────────────────────────────────────────

class TestExpandMoveTemplate:
    def _make_tu(self, return_value):
        tu = MagicMock()
        tu._value_from_tag_format.return_value = return_value
        return tu

    def test_current_folder_substituted_before_dt3(self):
        tu = self._make_tu('discogs/Ohota/My Album (2020)')
        result = _expand_move_template(
            '%source%/%albumartist%/%current_folder%',
            tu,
            '/incoming/My Album (2020)',
        )
        # %current_folder% should be replaced before dt3 expansion
        tu._value_from_tag_format.assert_called_once_with(
            '%source%/%albumartist%/My Album (2020)'
        )
        assert result == 'discogs/Ohota/My Album (2020)'

    def test_trailing_slash_stripped_from_sourcedir(self):
        tu = self._make_tu('mb/Artist/folder')
        _expand_move_template('%current_folder%', tu, '/incoming/folder/')
        tu._value_from_tag_format.assert_called_once_with('folder')

    def test_no_current_folder_token_passes_through(self):
        tu = self._make_tu('discogs/Artist')
        _expand_move_template('%source%/%albumartist%', tu, '/incoming/Folder')
        tu._value_from_tag_format.assert_called_once_with('%source%/%albumartist%')

    def test_multiple_current_folder_tokens_all_replaced(self):
        tu = self._make_tu('x')
        _expand_move_template('%current_folder%/%current_folder%', tu, '/src/mydir')
        tu._value_from_tag_format.assert_called_once_with('mydir/mydir')


# ─────────────────────────────────────────────────────────────────────────────
# _verify_target_or_raise
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifyTargetOrRaise:
    def test_missing_target_raises(self):
        with pytest.raises(RuntimeError, match='not found'):
            _verify_target_or_raise('/nonexistent/path')

    def test_none_target_raises(self):
        with pytest.raises(RuntimeError, match='not found'):
            _verify_target_or_raise(None)

    def test_empty_string_target_raises(self):
        with pytest.raises(RuntimeError, match='not found'):
            _verify_target_or_raise('')

    @patch('os.path.isdir', return_value=True)
    @patch('os.walk')
    def test_no_audio_files_raises(self, mock_walk, _isdir):
        mock_walk.return_value = [('/dest/Album', [], ['cover.jpg', 'info.txt'])]
        with pytest.raises(RuntimeError, match='no audio files'):
            _verify_target_or_raise('/dest/Album')

    @patch('os.path.isdir', return_value=True)
    @patch('os.walk')
    def test_audio_in_root_passes(self, mock_walk, _isdir):
        mock_walk.return_value = [('/dest/Album', [], ['01 Track.flac', 'folder.jpg'])]
        _verify_target_or_raise('/dest/Album')  # no exception

    @patch('os.path.isdir', return_value=True)
    @patch('os.walk')
    def test_audio_in_subdirectory_passes(self, mock_walk, _isdir):
        # split_discs layout — audio only in disc subdirectory
        mock_walk.return_value = [
            ('/dest/Album', ['Disc 1'], ['folder.jpg']),
            ('/dest/Album/Disc 1', [], ['01 Track.mp3']),
        ]
        _verify_target_or_raise('/dest/Album')  # no exception

    @patch('os.path.isdir', return_value=True)
    @patch('os.walk')
    def test_all_audio_extensions_recognised(self, mock_walk, _isdir):
        for ext in ('.flac', '.mp3', '.ape', '.wav', '.wv'):
            mock_walk.return_value = [('/d', [], [f'track{ext}'])]
            _verify_target_or_raise('/d')  # no exception


# ─────────────────────────────────────────────────────────────────────────────
# _post_process_source
# ─────────────────────────────────────────────────────────────────────────────

class TestPostProcessSource:

    # ── done_file ─────────────────────────────────────────────────────────────

    def test_done_file_calls_create_done_file(self):
        fh = MagicMock()
        r = _make_result()
        _post_process_source(r, _make_cfg('done_file'), fh, MagicMock())
        fh.create_done_file.assert_called_once()

    def test_default_action_is_done_file(self):
        fh = MagicMock()
        # cfg.get returns empty string → action resolves to 'done_file'
        cfg = MagicMock()
        cfg.get.return_value = ''
        r = _make_result()
        _post_process_source(r, cfg, fh, MagicMock())
        fh.create_done_file.assert_called_once()

    # ── remove ────────────────────────────────────────────────────────────────

    @patch('massmusictagger.processor._verify_target_or_raise')
    @patch('shutil.rmtree')
    def test_remove_deletes_sourcedir(self, mock_rmtree, mock_verify):
        fh = MagicMock()
        r = _make_result(sourcedir='/src/Album')
        _post_process_source(r, _make_cfg('remove'), fh, MagicMock())
        mock_verify.assert_called_once_with('/dest/Album')
        mock_rmtree.assert_called_once_with('/src/Album')
        fh.create_done_file.assert_not_called()

    @patch('massmusictagger.processor._verify_target_or_raise',
           side_effect=RuntimeError('no audio'))
    @patch('shutil.rmtree')
    def test_remove_aborts_if_verify_fails(self, mock_rmtree, _mock_verify):
        fh = MagicMock()
        with pytest.raises(RuntimeError, match='no audio'):
            _post_process_source(r := _make_result(), _make_cfg('remove'), fh, MagicMock())
        mock_rmtree.assert_not_called()

    # ── move ──────────────────────────────────────────────────────────────────

    @patch('massmusictagger.processor._verify_target_or_raise')
    @patch('os.makedirs')
    @patch('shutil.move')
    def test_move_uses_template_and_archive_root(self, mock_move, mock_makedirs, mock_verify):
        tu = MagicMock()
        tu._value_from_tag_format.return_value = 'discogs/Ohota/My Album'
        fh = MagicMock()
        r = _make_result(sourcedir='/src/My Album')
        _post_process_source(
            r,
            _make_cfg('move', archive_dir='~/Music/archive',
                      template='%source%/%albumartist%/%current_folder%'),
            fh, tu,
        )
        mock_verify.assert_called_once()
        expected_dest = os.path.join(
            os.path.expanduser('~/Music/archive'), 'discogs/Ohota/My Album')
        mock_move.assert_called_once_with('/src/My Album', expected_dest)
        assert r.archive_path == expected_dest
        fh.create_done_file.assert_not_called()

    @patch('massmusictagger.processor._verify_target_or_raise')
    @patch('shutil.move')
    def test_move_without_archive_dir_falls_back_to_done_file(self, mock_move, _verify):
        fh = MagicMock()
        r = _make_result()
        _post_process_source(r, _make_cfg('move', archive_dir=''), fh, MagicMock())
        mock_move.assert_not_called()
        fh.create_done_file.assert_called_once()
        assert r.archive_path is None

    @patch('massmusictagger.processor._verify_target_or_raise')
    @patch('os.makedirs')
    @patch('shutil.move')
    def test_move_uses_default_template_when_none_set(self, mock_move, mock_makedirs, mock_verify):
        tu = MagicMock()
        tu._value_from_tag_format.return_value = 'musicbrainz/Artist/Folder'
        fh = MagicMock()
        r = _make_result(sourcedir='/src/Folder')
        _post_process_source(
            r,
            _make_cfg('move', archive_dir='/archive', template=''),
            fh, tu,
        )
        # Empty template → default '%source%/%albumartist%/%current_folder%' used
        tu._value_from_tag_format.assert_called_once_with(
            '%source%/%albumartist%/Folder'
        )

    @patch('massmusictagger.processor._verify_target_or_raise',
           side_effect=RuntimeError('no audio'))
    @patch('shutil.move')
    def test_move_aborts_if_verify_fails(self, mock_move, _verify):
        fh = MagicMock()
        with pytest.raises(RuntimeError, match='no audio'):
            _post_process_source(
                _make_result(),
                _make_cfg('move', archive_dir='/archive'),
                fh, MagicMock(),
            )
        mock_move.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# _cleanup_empty_parents
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanupEmptyParents:

    def test_removes_empty_artist_folder(self, tmp_path):
        root = tmp_path / 'incoming'
        artist = root / 'The Fair Sex'
        artist.mkdir(parents=True)
        # Album dir already removed/moved by the caller — only the now-empty
        # artist folder remains.
        _cleanup_empty_parents(str(artist / 'Thin Walls'), str(root))
        assert not artist.exists()
        assert root.exists()

    def test_removes_multiple_empty_levels(self, tmp_path):
        root = tmp_path / 'incoming'
        nested = root / 'Various' / 'Sublabel'
        nested.mkdir(parents=True)
        _cleanup_empty_parents(str(nested / 'Album'), str(root))
        assert not (root / 'Various').exists()
        assert root.exists()

    def test_keeps_non_empty_parent(self, tmp_path):
        root = tmp_path / 'incoming'
        artist = root / 'The Fair Sex'
        artist.mkdir(parents=True)
        (artist / 'Other Album').mkdir()
        _cleanup_empty_parents(str(artist / 'Thin Walls'), str(root))
        assert artist.exists()

    def test_does_not_remove_root_itself(self, tmp_path):
        root = tmp_path / 'incoming'
        root.mkdir()
        _cleanup_empty_parents(str(root / 'Album'), str(root))
        assert root.exists()

    def test_path_outside_root_is_ignored(self, tmp_path):
        root = tmp_path / 'incoming'
        other = tmp_path / 'elsewhere' / 'Artist'
        other.mkdir(parents=True)
        # Should not raise or remove anything outside root.
        _cleanup_empty_parents(str(other / 'Album'), str(root))
        assert other.exists()


# ─────────────────────────────────────────────────────────────────────────────
# _post_process_source — empty-parent cleanup integration
# ─────────────────────────────────────────────────────────────────────────────

class TestPostProcessSourceCleanup:

    @patch('massmusictagger.processor._verify_target_or_raise')
    def test_remove_cleans_up_empty_artist_folder(self, _verify, tmp_path):
        root = tmp_path / 'incoming'
        album = root / 'The Fair Sex' / 'Thin Walls'
        album.mkdir(parents=True)
        (album / 'track.flac').write_bytes(b'')

        fh = MagicMock()
        r = _make_result(sourcedir=str(album))
        _post_process_source(r, _make_cfg('remove', source_dir=str(root)), fh, MagicMock())

        assert not album.exists()
        assert not (root / 'The Fair Sex').exists()
        assert root.exists()

    @patch('massmusictagger.processor._verify_target_or_raise')
    def test_move_cleans_up_empty_artist_folder(self, _verify, tmp_path):
        root = tmp_path / 'incoming'
        album = root / 'The Fair Sex' / 'Thin Walls'
        album.mkdir(parents=True)
        (album / 'track.flac').write_bytes(b'')
        archive = tmp_path / 'archive'

        tu = MagicMock()
        tu._value_from_tag_format.return_value = 'discogs/The Fair Sex/Thin Walls'
        fh = MagicMock()
        r = _make_result(sourcedir=str(album))
        _post_process_source(
            r,
            _make_cfg('move', archive_dir=str(archive),
                      template='%source%/%albumartist%/%current_folder%',
                      source_dir=str(root)),
            fh, tu,
        )

        assert not album.exists()
        assert not (root / 'The Fair Sex').exists()
        assert root.exists()
        assert (archive / 'discogs/The Fair Sex/Thin Walls' / 'track.flac').exists()
