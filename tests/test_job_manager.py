"""
The render queue itself, end to end, against the mock DCC harness.

`tests/test_mock_dcc.py` proves an engine can launch a renderer. This file proves
the thing a user actually clicks: that `JobManager` finds the software the
Settings tab configured, hands the job to the right engine, moves the job's
progress, and reaches a true status. Before Phase 4 the queue could only ever
run Blender, because `detect_available_software()` asked config.json for a
Blender path and nobody asked for the other three.

Nothing is monkeypatched: the manager runs in its own thread, the renderers are
real child processes, and `config.json` in the working directory is the app's own
configuration mechanism.

Run: python -X utf8 tests/test_job_manager.py
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from PyQt6.QtWidgets import QApplication

from mock_dcc import harness
from src.core.job_manager import JobManager, system_name
from src.core.models import JobStatus, RenderJob, SoftwareType

ALL_PACKAGES = ['blender', 'maya', 'cinema4d', 'unreal']


class JobManagerCase(unittest.TestCase):
    """A sandbox with the shims installed, config.json in cwd, and one JobManager."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.work = tempfile.mkdtemp(prefix='renderfox_queue_')
        cls.previous_cwd = os.getcwd()
        cls.executables = harness.install(cls.work)
        cls.out = os.path.join(cls.work, 'out')
        os.makedirs(cls.out, exist_ok=True)
        os.chdir(cls.work)  # config.json is read from the working directory

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.previous_cwd)
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.write_config(self.executables)
        for name in glob.glob(os.path.join(self.out, '*')):
            os.remove(name)
        self.manager = JobManager()
        self.events = []
        # A snapshot, not the job object: every emission carries the same
        # mutable instance, so keeping references would only ever show the last
        # state and a test could not tell when progress actually moved.
        self.manager.job_updated.connect(
            lambda job: self.events.append((job.id, job.status, job.progress)))

    def tearDown(self):
        self.manager.stop_processing()

    def write_config(self, software):
        """Replace config.json the way the Settings tab's Save button does."""
        with open(os.path.join(self.work, 'config.json'), 'w', encoding='utf-8') as handle:
            json.dump({'software': {key: path for key, path in software.items()}},
                      handle, indent=2)

    def job(self, key='maya', frames=(1, 3), name=None, **scene):
        scene.setdefault('seconds_per_frame', 0.02)
        scene.setdefault('output_dir', self.out)
        name = name or f'{key}-queue'
        scene.setdefault('prefix', name)
        project = harness.write_scene(self.work, key, name=name, **scene)
        return RenderJob(
            id='', name=name, project_file=project,
            software_type=SoftwareType(key),
            output_path=os.path.join(self.out, f'{name}.png'),
            resolution=(640, 360), frame_range=frames, output_format='png')

    def wait_for_status(self, job_id, expected, timeout=45):
        """Poll the job the queue is writing until it reaches a status."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.manager.get_job(job_id)
            if job and job.status in expected:
                return job
            time.sleep(0.05)
        job = self.manager.get_job(job_id)
        self.fail(f'job {job_id} never reached {expected}; it is '
                  f'{job.status if job else "gone"}: {job.error_message if job else ""}')

    def files(self, prefix):
        return sorted(os.path.basename(path) for path in
                      glob.glob(os.path.join(self.out, f'{prefix}_0*')))

    @staticmethod
    def path_key(path):
        """A path compared the way this OS compares paths.

        `shutil.which` rebuilds the name from PATHEXT, so a Windows PATH hit
        comes back as `maya.CMD` for the file written `maya.cmd` - the same
        executable, different casing.
        """
        return os.path.normcase(os.path.normpath(path))


class TestSoftwareDiscovery(JobManagerCase):
    """The queue refuses any job whose package is missing from the detector."""

    def test_01_every_configured_package_is_reported_available(self):
        info = self.manager.get_available_software_info()
        for key in ALL_PACKAGES:
            with self.subTest(package=key):
                self.assertTrue(info[key]['available'],
                                f'{key} is in config.json and the queue still calls it missing')
                self.assertEqual(self.path_key(self.executables[key]),
                                 self.path_key(info[key]['executable_path']),
                                 f'{key} resolved to a different executable than configured')

    def test_02_a_package_that_is_not_configured_is_not_available(self):
        self.write_config({'blender': self.executables['blender']})
        self.manager.refresh_software_cache()
        info = self.manager.get_available_software_info()
        self.assertTrue(info['blender']['available'])
        self.assertFalse(info['maya']['available'],
                         'Maya was reported installed with no path configured anywhere')

    def test_03_cache_invalidates_when_the_settings_change(self):
        """Saving a path in Settings has to reach the queue, not wait out 5 minutes."""
        first = self.manager._get_cached_available_software()
        self.assertIn(SoftwareType.MAYA, first)
        stamp = self.manager._cache_timestamp

        self.manager._get_cached_available_software()
        self.assertEqual(stamp, self.manager._cache_timestamp,
                         'an unchanged config.json was re-detected instead of reused')

        self.write_config({'blender': self.executables['blender']})
        second = self.manager._get_cached_available_software()
        self.assertNotEqual(stamp, self.manager._cache_timestamp,
                            'config.json changed and the cache did not notice')
        self.assertNotIn(SoftwareType.MAYA, second)

    def test_04_platform_keys_map_for_every_os(self):
        """`sys.platform` used to be read with `sys` never imported: a NameError on
        mac and Linux, swallowed by the broad except, so no path was ever found."""
        self.assertEqual('windows', system_name('nt', 'win32'))
        self.assertEqual('darwin', system_name('posix', 'darwin'))
        self.assertEqual('linux', system_name('posix', 'linux'))

    def test_05_found_from_the_path_with_no_config_at_all(self):
        """An installer that put the engine on PATH is enough: config.json may be empty.

        Every package has to ask, not just Blender. Before Phase 4 the PATH and
        config lookups were wired only into `_get_blender_paths`, so a Maya on
        PATH stayed invisible to the queue even though it was installed.
        """
        bin_dir = os.path.dirname(self.executables['blender'])
        self.write_config({})
        previous_path = os.environ['PATH']
        os.environ['PATH'] = bin_dir + os.pathsep + previous_path
        try:
            self.manager.refresh_software_cache()
            info = self.manager.get_available_software_info()
            for key in ALL_PACKAGES:
                with self.subTest(package=key):
                    self.assertTrue(info[key]['available'],
                                    f'{key} was on PATH and the queue still called it missing')
                    self.assertEqual(self.path_key(self.executables[key]),
                                     self.path_key(info[key]['executable_path']))
        finally:
            os.environ['PATH'] = previous_path
            self.write_config(self.executables)

    def test_06_queue_runs_a_job_found_only_from_the_path(self):
        """Discovery and execution must resolve the same file for the same package."""
        bin_dir = os.path.dirname(self.executables['blender'])
        self.write_config({})
        previous_path = os.environ['PATH']
        os.environ['PATH'] = bin_dir + os.pathsep + previous_path
        try:
            job = self.job('cinema4d')
            self.manager.add_job(job)
            self.manager.start_processing()
            done = self.wait_for_status(job.id, {JobStatus.COMPLETED, JobStatus.FAILED})
            self.assertEqual(JobStatus.COMPLETED, done.status,
                             f'a path-discovered engine could not run: {done.error_message}')
            self.assertEqual(3, len(self.files(job.name)))
        finally:
            os.environ['PATH'] = previous_path
            self.write_config(self.executables)


class TestQueueExecution(JobManagerCase):
    """A queued job runs, reports progress and lands on a true status."""

    def test_05_configured_maya_job_renders_through_the_queue(self):
        job = self.job('maya')
        self.manager.add_job(job)
        self.manager.start_processing()
        done = self.wait_for_status(job.id, {JobStatus.COMPLETED, JobStatus.FAILED})
        self.assertEqual(JobStatus.COMPLETED, done.status,
                         f'the queue could not render a configured Maya job: {done.error_message}')
        self.assertEqual(3, len(self.files(job.name)))
        self.assertEqual(100, done.progress)

    def test_06_progress_reaches_the_job_while_it_renders(self):
        """The engine's frame lines have to arrive at the job, not after the render."""
        job = self.job('blender', frames=(1, 6), seconds_per_frame=0.25)
        self.manager.add_job(job)
        self.manager.start_processing()

        # `job_updated` is emitted on the queue thread and delivered to this
        # thread, so the slots only run while the loop lets Qt work.
        deadline = time.time() + 30
        while time.time() < deadline and not self._mid_render_event():
            self.app.processEvents()
            time.sleep(0.02)
        self.assertTrue(self._mid_render_event(),
                        'no job_updated carried a live progress value while the job rendered: '
                        f'{self.events}')

        done = self.wait_for_status(job.id, {JobStatus.COMPLETED, JobStatus.FAILED})
        self.assertEqual(JobStatus.COMPLETED, done.status, done.error_message)

    def _mid_render_event(self):
        """A signal that fired during the render, not the one that closed it."""
        return any(status == JobStatus.RENDERING and 0 < progress < 100
                   for _, status, progress in self.events)

    def test_07_unconfigured_package_fails_with_a_message_that_names_the_package(self):
        self.write_config({'blender': self.executables['blender']})
        self.manager.refresh_software_cache()
        job = self.job('unreal')
        self.manager.add_job(job)
        self.manager.start_processing()
        done = self.wait_for_status(job.id, {JobStatus.FAILED})
        self.assertIn('unreal', (done.error_message or '').lower())

    def test_08_stop_leaves_the_job_pending_and_kills_the_renderer(self):
        """Stopping must not silently discard queued work."""
        job = self.job('blender', frames=(1, 30), seconds_per_frame=0.3)
        self.manager.add_job(job)
        self.manager.start_processing()
        deadline = time.time() + 15
        while time.time() < deadline and self.manager.get_job(job.id).status != JobStatus.RENDERING:
            time.sleep(0.05)
        self.manager.stop_processing()
        current = self.manager.get_job(job.id)
        self.assertEqual(JobStatus.PENDING, current.status,
                         'a stopped job was left claiming to be rendering')
        self.assertFalse(self.manager.is_processing)
        self.assertLess(len(self.files(job.name)), 30)

    def test_09_queue_stats_count_what_is_in_the_queue(self):
        first = self.job('blender', frames=(1, 2))
        second = self.job('blender', frames=(1, 2))
        self.manager.add_job(first)
        self.manager.add_job(second)
        stats = self.manager.get_queue_stats()
        self.assertEqual(2, stats['total'])
        self.assertEqual(2, stats['pending'])
        self.assertEqual(2, self.manager.pending_count)

    def test_10_a_configured_path_that_cannot_run_fails_cleanly(self):
        """A folder typed into Settings is the likeliest mistake on an untested machine.

        `MayaEngine.is_available()` can only ask whether the path exists - real
        Maya has no version flag to probe - so a directory can reach the launch.
        The job has to land on FAILED with a message naming the engine, and the
        queue has to carry on with the next job instead of dying with it.
        """
        # Only Maya's entry is wrong; Blender keeps a real shim, so a queue that
        # gives up after one bad path shows up as this next job failing too.
        broken_dir = os.path.join(self.out, 'bin')
        os.makedirs(broken_dir, exist_ok=True)
        self.write_config({**self.executables, 'maya': broken_dir})
        self.manager.refresh_software_cache()
        broken = self.job('maya')
        working = self.job('blender', frames=(1, 2))
        self.manager.add_job(broken)
        self.manager.add_job(working)
        self.manager.start_processing()

        failed = self.wait_for_status(broken.id, {JobStatus.FAILED})
        self.assertIn('maya', (failed.error_message or '').lower(),
                      'the failure was reported without naming the engine: '
                      f'{failed.error_message}')
        done = self.wait_for_status(working.id, {JobStatus.COMPLETED, JobStatus.FAILED})
        self.assertEqual(JobStatus.COMPLETED, done.status,
                         f'the queue stopped working after one bad path: {done.error_message}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
