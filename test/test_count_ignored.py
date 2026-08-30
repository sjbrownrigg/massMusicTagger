"""_count_ignored must count the root when the root IS the finished album."""
import os, shutil, tempfile, unittest
from unittest import mock
from massmusictagger.__main__ import _count_ignored


class _Cfg:
    def get(self, section, option):
        return '.done' if option == 'done_file' else ''


class CountIgnoredRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _album(self, path, done=True):
        os.makedirs(path, exist_ok=True)
        open(os.path.join(path, '01.flac'), 'wb').close()
        if done:
            open(os.path.join(path, '.done'), 'wb').close()

    def test_the_root_itself_is_counted_when_it_is_the_album(self):
        """What a batch script passing one album per run actually does."""
        self._album(self.tmp)
        self.assertEqual(_count_ignored(self.tmp, [], _Cfg(), False), 1)

    def test_a_root_without_a_done_marker_is_not_counted(self):
        self._album(self.tmp, done=False)
        self.assertEqual(_count_ignored(self.tmp, [], _Cfg(), False), 0)

    def test_a_root_being_processed_is_not_counted(self):
        self._album(self.tmp)
        self.assertEqual(_count_ignored(self.tmp, [self.tmp], _Cfg(), False), 0)

    def test_force_counts_nothing(self):
        self._album(self.tmp)
        self.assertEqual(_count_ignored(self.tmp, [], _Cfg(), True), 0)

    def test_a_tree_of_finished_albums_still_counts_each(self):
        for name in ('A', 'B'):
            self._album(os.path.join(self.tmp, name))
        self.assertEqual(_count_ignored(self.tmp, [], _Cfg(), False), 2)

    def test_a_done_marker_with_no_audio_at_the_root_is_not_an_album(self):
        open(os.path.join(self.tmp, '.done'), 'wb').close()
        self.assertEqual(_count_ignored(self.tmp, [], _Cfg(), False), 0)


if __name__ == '__main__':
    unittest.main()
