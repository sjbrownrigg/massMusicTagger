"""The global CPU cap, and that the call sites actually hold it.

The behaviour worth protecting is not the semaphore -- that is twenty lines
and obviously correct -- but the wiring. Twice in this project a fix passed
its unit tests with the call site reverted, so every test below either runs
real concurrent threads through the guard or asserts against the command
that is actually built.
"""

import contextlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from massmusictagger.core import cpuguard


class ConfigureTest(unittest.TestCase):

    def setUp(self):
        self.addCleanup(cpuguard.configure, cpuguard.DEFAULT_JOBS)

    def test_default_is_one(self):
        cpuguard.configure(cpuguard.DEFAULT_JOBS)
        self.assertEqual(cpuguard.jobs(), 1)

    def test_accepts_a_string_because_config_values_are_strings(self):
        cpuguard.configure('4')
        self.assertEqual(cpuguard.jobs(), 4)

    def test_nonsense_falls_back_rather_than_raising(self):
        # A bad config value must not take the run down; it warns and copes.
        with self.assertLogs('massmusictagger.core.cpuguard', 'WARNING'):
            cpuguard.configure('lots')
        self.assertEqual(cpuguard.jobs(), cpuguard.DEFAULT_JOBS)

    def test_zero_and_negative_are_clamped_to_one(self):
        for bad in ('0', '-3'):
            with self.subTest(value=bad):
                with self.assertLogs('massmusictagger.core.cpuguard', 'WARNING'):
                    cpuguard.configure(bad)
                self.assertEqual(cpuguard.jobs(), 1)


class ConcurrencyTest(unittest.TestCase):
    """Run real threads: a mocked semaphore would prove nothing."""

    def setUp(self):
        self.addCleanup(cpuguard.configure, cpuguard.DEFAULT_JOBS)

    def _run(self, threads, jobs):
        cpuguard.configure(jobs)
        live = 0
        peak = 0
        lock = threading.Lock()

        def work():
            nonlocal live, peak
            with cpuguard.slot('test'):
                with lock:
                    live += 1
                    peak = max(peak, live)
                time.sleep(0.05)
                with lock:
                    live -= 1

        ts = [threading.Thread(target=work) for _ in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return peak

    def test_one_job_serialises(self):
        self.assertEqual(self._run(threads=8, jobs=1), 1)

    def test_two_jobs_allow_exactly_two(self):
        self.assertEqual(self._run(threads=8, jobs=2), 2)

    def test_slot_is_released_when_the_body_raises(self):
        cpuguard.configure(1)
        with self.assertRaises(RuntimeError):
            with cpuguard.slot('boom'):
                raise RuntimeError('boom')
        # Still acquirable: a leaked slot would deadlock the next album.
        with cpuguard.slot('after'):
            pass


class ReplayGainCallSiteTest(unittest.TestCase):
    """-c must reach r128gain, and the scan must happen inside a slot."""

    def setUp(self):
        self.addCleanup(cpuguard.configure, cpuguard.DEFAULT_JOBS)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # One file with a taggable extension is enough: the call site groups
        # by extension and shells out once per group.
        open(os.path.join(self.tmp, '01.flac'), 'wb').close()

    def _tagger(self, application='r128gain', thread_count='2'):
        from massmusictagger.core import taggerutils

        t = taggerutils.FileHandler.__new__(taggerutils.FileHandler)
        t.rg_process = True
        t.rg_application = application
        t.rg_thread_count = thread_count
        t.album = mock.Mock(target_dir=self.tmp)
        return t

    def _capture(self, tagger):
        """Run the real method, recording the command and slot ordering."""
        from massmusictagger.core import taggerutils

        events = []

        @contextlib.contextmanager
        def fake_slot(what='CPU work'):
            events.append(('enter', what))
            try:
                yield
            finally:
                events.append(('exit', what))

        def fake_run(cmd, **kw):
            events.append(('run', list(cmd)))
            return subprocess.CompletedProcess(cmd, 0, '', '')

        with mock.patch.object(taggerutils.cpuguard, 'slot', fake_slot), \
             mock.patch('subprocess.run', side_effect=fake_run):
            tagger.add_replay_gain_tags()
        return events

    def test_thread_count_reaches_r128gain(self):
        events = self._capture(self._tagger(thread_count='2'))
        cmds = [e[1] for e in events if e[0] == 'run']
        self.assertEqual(len(cmds), 1, events)
        cmd = cmds[0]
        self.assertEqual(cmd[0], 'r128gain')
        self.assertIn('-c', cmd)
        self.assertEqual(cmd[cmd.index('-c') + 1], '2')

    def test_configured_value_is_honoured_not_hardcoded(self):
        cmd = [e[1] for e in self._capture(self._tagger(thread_count='5'))
               if e[0] == 'run'][0]
        self.assertEqual(cmd[cmd.index('-c') + 1], '5')

    def test_the_scan_runs_inside_a_slot(self):
        """The wiring, not the semaphore: run must sit between enter and exit."""
        events = self._capture(self._tagger())
        kinds = [e[0] for e in events]
        self.assertEqual(kinds, ['enter', 'run', 'exit'], events)

    def test_other_applications_are_also_guarded(self):
        # metaflac and loudgain decode too; they just take no thread flag.
        for app in ('metaflac', 'loudgain'):
            with self.subTest(application=app):
                events = self._capture(self._tagger(application=app))
                self.assertEqual([e[0] for e in events],
                                 ['enter', 'run', 'exit'], events)
                cmd = [e[1] for e in events if e[0] == 'run'][0]
                self.assertNotIn('-c', cmd)


if __name__ == '__main__':
    unittest.main()
