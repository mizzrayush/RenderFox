"""
The render queue itself, end to end, against the mock DCC harness.

`tests/test_mock_dcc.py` proves an engine can launch a renderer. This file proves
the thing a user actually clicks: that `JobManager` finds the software the
Settings tab configured, hands the job to the right engine, moves the job's
progress, and reaches a true status. Before Phase 4 the queue could only ever
run Blender, because `detect_available_software()` asked config.json for a
Blender path and nobody asked for the other three.

Nothing is monkeypatched: the manager runs in its own thread, the renderers are
real child processes, and `config.json` beside the app - the mechanism
`src/utils/app_paths.py` answers, here pointed at the sandbox by
`RENDERFOX_APP_ROOT` - is the app's own configuration mechanism.

Run: python -X utf8 tests/test_job_manager.py
"""

import glob
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

import psutil

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from PyQt6.QtWidgets import QApplication

from mock_dcc import harness
from src.core.job_manager import JobManager, system_name
from src.core.models import JobStatus, Priority, RenderJob, SoftwareType

ALL_PACKAGES = ['blender', 'maya', 'cinema4d', 'unreal']


class JobManagerCase(unittest.TestCase):
    """A sandbox with the shims installed, config.json as the app's own file, and one JobManager."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.work = tempfile.mkdtemp(prefix='renderfox_queue_')
        cls.previous_cwd = os.getcwd()
        cls.previous_root = os.environ.get('RENDERFOX_APP_ROOT')
        cls.executables = harness.install(cls.work)
        cls.out = os.path.join(cls.work, 'out')
        os.makedirs(cls.out, exist_ok=True)
        os.chdir(cls.work)
        # config.json is read from the app's own folder, and `src/utils/app_paths.py`
        # takes that folder from this variable - so the sandbox is the app here.
        os.environ['RENDERFOX_APP_ROOT'] = cls.work

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.previous_cwd)
        if cls.previous_root is None:
            del os.environ['RENDERFOX_APP_ROOT']
        else:
            os.environ['RENDERFOX_APP_ROOT'] = cls.previous_root
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

    def write_config(self, software, performance=None):
        """Replace config.json the way the Settings tab's Save button does."""
        config = {'software': {key: path for key, path in software.items()}}
        if performance is not None:
            config['performance'] = performance
        with open(os.path.join(self.work, 'config.json'), 'w', encoding='utf-8') as handle:
            json.dump(config, handle, indent=2)

    def job(self, key='maya', frames=(1, 3), name=None, **scene):
        scene.setdefault('seconds_per_frame', 0.02)
        scene.setdefault('output_dir', self.out)
        name = name or f'{key}-queue'
        scene.setdefault('prefix', name)
        launches = os.path.join(self.work, f'.{name}.launches')
        if os.path.exists(launches):
            os.remove(launches)
        scene.setdefault('launch_log', launches)
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
            # `job_updated` is emitted on the queue thread, so the slot that
            # records the events only runs while this loop lets Qt work.
            self.app.processEvents()
            job = self.manager.get_job(job_id)
            if job and job.status in expected:
                return job
            time.sleep(0.05)
        job = self.manager.get_job(job_id)
        self.fail(f'job {job_id} never reached {expected}; it is '
                  f'{job.status if job else "gone"}: {job.error_message if job else ""}')

    def wait_for_running(self, count, timeout=20):
        """Wait until exactly `count` jobs hold a render slot."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.processEvents()
            if len(self.manager.running_jobs()) == count:
                return True
            time.sleep(0.05)
        return False

    def peak_running_within(self, seconds):
        """The most slots the queue ever filled inside the window."""
        deadline = time.time() + seconds
        peak = 0
        while time.time() < deadline:
            self.app.processEvents()
            peak = max(peak, len(self.manager.running_jobs()))
            time.sleep(0.05)
        return peak

    def files(self, prefix):
        return sorted(os.path.basename(path) for path in
                      glob.glob(os.path.join(self.out, f'{prefix}_0*')))

    def attempts(self, job):
        """How many renderer processes the queue launched for this job.

        Counted from the launches the mock recorded, not from `job_updated`:
        those signals are queued onto the test thread and carry the same mutable
        job, so a retry that finished between two processEvents reads as one.
        """
        try:
            with open(os.path.join(self.work, f'.{job.name}.launches'),
                      encoding='utf-8') as handle:
                return sum(1 for _ in handle)
        except OSError:
            return 0

    def live_renderers(self, name=None):
        """Mock renderer processes still alive under this test process.

        With a `name`, only the renderer launched for that job's project file, so
        one job's process can be told apart from another's.
        """
        live = []
        for child in psutil.Process().children(recursive=True):
            try:
                line = ' '.join(child.cmdline())
            except (psutil.Error, OSError):
                continue  # it exited while its command line was being read
            if 'mock_dcc.py' not in line:
                continue
            if name and name not in line:
                continue
            live.append(child.pid)
        return live

    def wait_for_renderers_gone(self, timeout=10):
        """Wait for the queue's child processes to die, and report any left."""
        deadline = time.time() + timeout
        while time.time() < deadline and self.live_renderers():
            time.sleep(0.05)
        return self.live_renderers()

    def wait_for_renderer_gone(self, name, timeout=10):
        """Wait for one job's renderer to die, and report whether it did."""
        deadline = time.time() + timeout
        while time.time() < deadline and self.live_renderers(name):
            time.sleep(0.05)
        return self.live_renderers(name)

    def wait_for_launches(self, *jobs, timeout=20):
        """Wait until every one of these jobs has a renderer process running.

        A slot is claimed before the engine is resolved, so `running_jobs()` alone
        cannot tell a test that pausing the process is possible yet.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.processEvents()
            if all(self.attempts(job) >= 1 for job in jobs):
                return True
            time.sleep(0.05)
        return False

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
        """Stopping must not silently discard queued work, or leave a renderer running."""
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
        self.assertEqual([], self.wait_for_renderers_gone(),
                         'the queue stopped but left its render process running')
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


class TestQueuePolicy(JobManagerCase):
    """What the queue-side Settings controls are supposed to do.

    `max_concurrent`, `auto_retry` and `max_retries` were written to config.json
    by the Settings tab and read by nothing; `job.priority` was settable from the
    Batch menu and the queue took `pending_jobs[0]`, i.e. insertion order.
    """

    def test_11_the_queue_runs_the_most_urgent_job_first(self):
        """Set Priority has to change what renders next, not just what is stored."""
        low = self.job('blender', frames=(1, 1), name='policy-low')
        urgent = self.job('blender', frames=(1, 1), name='policy-urgent')
        normal = self.job('blender', frames=(1, 1), name='policy-normal')
        low.priority = Priority.LOW
        urgent.priority = Priority.URGENT
        for job in (low, urgent, normal):
            self.manager.add_job(job)
        self.manager.start_processing()
        for job in (urgent, normal, low):
            self.assertEqual(JobStatus.COMPLETED,
                             self.wait_for_status(job.id, {JobStatus.COMPLETED,
                                                            JobStatus.FAILED}).status)
        order = [job.name for job in sorted((low, urgent, normal),
                                           key=lambda job: job.start_time)]
        self.assertEqual(['policy-urgent', 'policy-normal', 'policy-low'], order,
                         'the queue picked jobs in the order they were added')

    def test_12_a_failed_job_is_retried_up_to_the_configured_limit(self):
        self.write_config(self.executables, {'auto_retry': True, 'max_retries': 2})
        self.manager.refresh_software_cache()
        job = self.job('blender', frames=(1, 2), name='policy-retry', fail_after=1)
        self.manager.add_job(job)
        self.manager.start_processing()
        done = self.wait_for_status(job.id, {JobStatus.COMPLETED, JobStatus.FAILED})
        self.assertEqual(JobStatus.FAILED, done.status)
        self.assertEqual(3, self.attempts(job),
                         'auto_retry / max_retries reached nothing in the queue')
        self.assertEqual(2, done.retry_count)

    def test_13_one_attempt_is_all_a_failure_gets_when_retry_is_off(self):
        """The default is a single attempt - a failing job must not loop forever."""
        job = self.job('blender', frames=(1, 2), name='policy-noretry', fail_after=1)
        self.manager.add_job(job)
        self.manager.start_processing()
        done = self.wait_for_status(job.id, {JobStatus.COMPLETED, JobStatus.FAILED})
        self.assertEqual(JobStatus.FAILED, done.status)
        self.assertEqual(1, self.attempts(job))
        self.assertEqual(0, done.retry_count)

    def test_14_two_jobs_render_at_once_when_the_settings_allow_it(self):
        self.write_config(self.executables, {'max_concurrent': 2})
        self.manager.refresh_software_cache()
        first = self.job('blender', name='policy-live-a', hang=True, hang_seconds=20)
        second = self.job('blender', name='policy-live-b', hang=True, hang_seconds=20)
        self.manager.add_job(first)
        self.manager.add_job(second)
        self.manager.start_processing()
        self.assertTrue(self.wait_for_running(2),
                        'the second job never started while the first was still rendering')
        self.assertEqual(2, len(self.manager.running_jobs()))

    def test_15_one_job_at_a_time_is_the_default(self):
        first = self.job('blender', name='policy-serial-a', hang=True, hang_seconds=20)
        second = self.job('blender', name='policy-serial-b', hang=True, hang_seconds=20)
        self.manager.add_job(first)
        self.manager.add_job(second)
        self.manager.start_processing()
        self.wait_for_running(1)
        self.assertEqual(1, self.peak_running_within(4),
                         'the queue filled two slots with max_concurrent left at 1')
        self.assertEqual(JobStatus.PENDING, self.manager.get_job(second.id).status)

    def test_16_a_fast_job_closing_at_100_does_not_close_a_slow_one(self):
        """The progress callback used to write to "the current job", one per queue."""
        self.write_config(self.executables, {'max_concurrent': 2})
        self.manager.refresh_software_cache()
        short = self.job('blender', frames=(1, 2), name='policy-fast',
                         seconds_per_frame=0.05)
        long = self.job('blender', frames=(1, 8), name='policy-slow',
                        seconds_per_frame=0.4)
        self.manager.add_job(short)
        self.manager.add_job(long)
        self.manager.start_processing()
        done = self.wait_for_status(short.id, {JobStatus.COMPLETED, JobStatus.FAILED})
        self.assertEqual(JobStatus.COMPLETED, done.status, done.error_message)
        still = self.manager.get_job(long.id)
        self.assertEqual(JobStatus.RENDERING, still.status,
                         'the longer job was cut short by the shorter one finishing')
        self.assertLess(still.progress, 100,
                        'the finished job reported its 100% onto the running one')
        self.assertEqual(100, self.wait_for_status(long.id, {JobStatus.COMPLETED}).progress)

    def test_17_pausing_one_job_leaves_the_other_rendering(self):
        self.write_config(self.executables, {'max_concurrent': 2})
        self.manager.refresh_software_cache()
        paused = self.job('blender', frames=(1, 20), name='policy-pause',
                          seconds_per_frame=0.25)
        other = self.job('blender', frames=(1, 3), name='policy-other',
                         seconds_per_frame=0.1)
        self.manager.add_job(paused)
        self.manager.add_job(other)
        self.manager.start_processing()
        self.assertTrue(self.wait_for_running(2), 'both jobs never reached RENDERING')
        self.assertTrue(self.wait_for_launches(paused, other),
                        'a renderer never started, so there was nothing to pause')
        self.assertTrue(self.manager.pause_job(paused.id))
        self.assertEqual(JobStatus.PAUSED, self.manager.get_job(paused.id).status)
        self.assertEqual(JobStatus.COMPLETED,
                         self.wait_for_status(other.id, {JobStatus.COMPLETED,
                                                         JobStatus.FAILED}).status,
                         'pausing one render stopped the other one too')
        self.assertLess(len(self.files(paused.name)), 20,
                        'the suspended renderer kept writing frames')
        self.assertTrue(self.manager.resume_job(paused.id))
        self.assertEqual(JobStatus.COMPLETED,
                         self.wait_for_status(paused.id, {JobStatus.COMPLETED,
                                                          JobStatus.FAILED}).status)

    def test_18_removing_a_rendering_job_leaves_the_queue_running(self):
        """The removed job's renderer dies; the one still in the queue does not."""
        self.write_config(self.executables, {'max_concurrent': 2})
        self.manager.refresh_software_cache()
        doomed = self.job('blender', name='policy-remove', hang=True, hang_seconds=20)
        other = self.job('blender', frames=(1, 6), name='policy-keep',
                         seconds_per_frame=0.25)
        self.manager.add_job(doomed)
        self.manager.add_job(other)
        self.manager.start_processing()
        self.assertTrue(self.wait_for_running(2), 'both jobs never reached RENDERING')
        self.assertTrue(self.wait_for_launches(doomed, other),
                        'a renderer never started, so removal had nothing to cancel')
        self.assertTrue(self.manager.remove_job(doomed.id))
        self.assertIsNone(self.manager.get_job(doomed.id))
        self.assertEqual([], self.wait_for_renderer_gone(doomed.name),
                         'the removed job kept rendering after it left the queue')
        self.assertEqual(JobStatus.COMPLETED,
                         self.wait_for_status(other.id, {JobStatus.COMPLETED,
                                                         JobStatus.FAILED}).status,
                         'removing one job took the whole queue down with it')
        self.assertTrue(self.manager.is_processing)

    def test_21_stopping_while_a_job_is_paused_kills_it_too(self):
        """A suspended renderer is still Blender holding a core and a window open."""
        self.write_config(self.executables, {'max_concurrent': 2})
        self.manager.refresh_software_cache()
        paused = self.job('blender', frames=(1, 40), name='policy-pause-stop',
                          seconds_per_frame=0.2)
        other = self.job('blender', name='policy-other-stop', hang=True, hang_seconds=20)
        self.manager.add_job(paused)
        self.manager.add_job(other)
        self.manager.start_processing()
        self.assertTrue(self.wait_for_running(2), 'both jobs never reached RENDERING')
        self.assertTrue(self.wait_for_launches(paused, other), 'a renderer never started')
        self.assertTrue(self.manager.pause_job(paused.id))
        self.assertEqual(JobStatus.PAUSED, self.manager.get_job(paused.id).status)
        self.manager.stop_processing()
        self.assertEqual([], self.wait_for_renderers_gone(),
                         'a paused render was left suspended with nothing to wake it')
        for job in (paused, other):
            self.assertEqual(JobStatus.PENDING, self.manager.get_job(job.id).status,
                             'closing the queue left a job claiming to be rendering')

    def test_22_a_junk_queue_setting_still_runs_the_queue(self):
        """config.json is hand-editable, and 0 there means "no slot ever fills".

        The Start button would look dead forever. A value Python cannot even turn
        into a number - a string left over from a template - must not take the
        queue down either.
        """
        for value in (0, -5, 999, 'abc', None):
            with self.subTest(max_concurrent=value):
                self.write_config(self.executables, {'max_concurrent': value})
                self.manager.refresh_software_cache()
                job = self.job('blender', frames=(1, 2), name=f'policy-clamp-{value}')
                self.manager.add_job(job)
                self.manager.start_processing()
                done = self.wait_for_status(job.id, {JobStatus.COMPLETED,
                                                     JobStatus.FAILED}, timeout=25)
                self.assertEqual(JobStatus.COMPLETED, done.status,
                                 f'max_concurrent={value!r} broke the queue: '
                                 f'{done.error_message}')

    def test_19_stop_returns_every_running_job_to_pending(self):
        """A Stop click that lands mid-launch must still leave nothing rendering.

        The queue fills both slots before either worker has resolved an engine, so
        this is the window where a renderer can be started by a thread whose job
        the stop had already counted as finished.
        """
        self.write_config(self.executables, {'max_concurrent': 2})
        self.manager.refresh_software_cache()
        first = self.job('blender', name='policy-stop-a', hang=True, hang_seconds=20)
        second = self.job('blender', name='policy-stop-b', hang=True, hang_seconds=20)
        self.manager.add_job(first)
        self.manager.add_job(second)
        self.manager.start_processing()
        self.assertTrue(self.wait_for_running(2))
        self.manager.stop_processing()
        self.assertEqual([], self.manager.running_jobs())
        self.assertFalse(self.manager.is_processing)
        self.assertEqual([], self.wait_for_renderers_gone(),
                         'a renderer launched after Stop kept the machine busy')
        for job in (first, second):
            current = self.manager.get_job(job.id)
            self.assertEqual(JobStatus.PENDING, current.status,
                             'a running job was left claiming to be rendering')
            self.assertEqual(0, current.progress)
            self.assertLessEqual(self.attempts(current), 1,
                                 'the stopped job was launched again after Stop')

    def test_20_pause_on_error_stops_the_queue_from_going_further(self):
        self.write_config(self.executables, {'pause_on_error': True})
        self.manager.refresh_software_cache()
        broken = self.job('blender', frames=(1, 2), name='policy-error', fail_after=1)
        waiting = self.job('blender', frames=(1, 2), name='policy-after-error')
        self.manager.add_job(broken)
        self.manager.add_job(waiting)
        self.manager.start_processing()
        self.assertEqual(JobStatus.FAILED, self.wait_for_status(broken.id,
                                                                {JobStatus.FAILED}).status)
        deadline = time.time() + 10
        while time.time() < deadline and self.manager.is_processing:
            self.app.processEvents()
            time.sleep(0.05)
        self.assertFalse(self.manager.is_processing,
                         'the queue carried on past a failure it was told to pause on')
        self.assertEqual(JobStatus.PENDING, self.manager.get_job(waiting.id).status)


    def test_23_the_policy_the_queue_reads_is_clamped_and_typed(self):
        """What a hand-edited config.json turns into, read straight off the queue.

        The Settings tab's own range is 1-16, and the renderer cost of ignoring it
        is one Blender per line of the file. Values that are not numbers at all -
        a template left as text - have to land on the default rather than raising
        inside the queue thread, which would stop the Start button dead.
        """
        for value, expected in ((0, 1), (-5, 1), (16, 16), (999, 16), ('3', 3),
                                ('abc', 1), (None, 1), (2.7, 2)):
            with self.subTest(max_concurrent=value):
                self.write_config(self.executables, {'max_concurrent': value})
                self.assertEqual(expected,
                                 self.manager._queue_policy()['max_concurrent'])

        for value, expected in ((0, 0), (-3, 0), (5, 5), (999, 100), ('2', 2),
                                ('x', 3), (None, 3)):
            with self.subTest(max_retries=value):
                self.write_config(self.executables, {'max_retries': value})
                self.assertEqual(expected, self.manager._queue_policy()['max_retries'])

        self.write_config(self.executables, {})
        default = self.manager._queue_policy()
        self.assertEqual(1, default['max_concurrent'])
        self.assertFalse(default['auto_retry'])
        self.assertFalse(default['pause_on_error'])

        self.write_config(self.executables, {'auto_retry': True, 'pause_on_error': 1})
        both = self.manager._queue_policy()
        self.assertTrue(both['auto_retry'])
        self.assertTrue(both['pause_on_error'])


    def test_24_a_paused_renderer_is_woken_before_it_is_killed(self):
        """`terminate` on a suspended process is a request it will never hear.

        On Windows TerminateProcess overrides the suspension, so this ordering
        cannot be shown through a real render on this machine - it is a POSIX
        fact (SIGTERM to a SIGSTOPped process stays queued forever). So the
        contract is pinned on the calls the queue makes, in order.
        """
        calls = []

        class Tracked:
            def resume(self):
                calls.append('resume')

            def stop(self):
                calls.append('stop')

        job = self.job('blender', frames=(1, 2), name='policy-wake')
        job.status = JobStatus.PAUSED
        JobManager._kill_renderer(job, Tracked())
        self.assertEqual(['resume', 'stop'], calls,
                         'a paused render was killed without being woken first')

        calls.clear()
        job.status = JobStatus.RENDERING
        JobManager._kill_renderer(job, Tracked())
        self.assertEqual(['stop'], calls,
                         'a job that was never paused was resumed on the way out')

        calls.clear()
        JobManager._kill_renderer(job, None)
        self.assertEqual([], calls, 'a slot with no engine behind it was reported as killed')

    def test_25_a_job_holding_a_slot_is_never_picked_again(self):
        """A retried job is back to PENDING before its worker frees the slot.

        The gap is real and short: `_retry_pending` runs first, the slot is
        released in the worker's `finally`. Picking the job inside that gap would
        hand one job two renderers at once and overwrite the slot it still holds.
        """
        job = self.job('blender', frames=(1, 2), name='policy-slot')
        self.manager.add_job(job)
        with self.manager._lock:
            self.manager._running[job.id] = (job, None)
            job.status = JobStatus.PENDING

        self.assertIsNone(self.manager._next_pending(),
                          'the queue picked a job whose renderer slot was still held')

        with self.manager._lock:
            self.manager._running.clear()
        self.assertEqual(job.id, self.manager._next_pending().id,
                         'refreeing the slot did not make the job pickable again')

    def test_26_the_settings_tab_writes_the_keys_the_queue_reads(self):
        """A key spelled differently on the two sides of config.json is a silent no-op.

        The Settings tab builds the `performance` block in `_collect_all_settings`,
        the queue reads it in `_queue_policy`. This phase wired those two together,
        so the spelling is pinned from both ends: the names the queue looks up in
        the file have to be the names Save writes, and have to be the names the
        queue hands back. A rename on either side saves fine and changes nothing.
        """
        with open(os.path.join(ROOT, 'src', 'ui', 'settings_tab.py'),
                  encoding='utf-8') as handle:
            written = set(re.findall(r'perf\[["\'](\w+)["\']\]\s*=', handle.read()))

        with open(os.path.join(ROOT, 'src', 'core', 'job_manager.py'),
                  encoding='utf-8') as handle:
            source = handle.read()
        start = source.index('def _queue_policy')
        body = source[start:source.index('\n    def ', start + 1)]
        looked_up = set(re.findall(r"(?:perf\.get\(|whole\()['\"](\w+)['\"]", body))

        read = set(self.manager._queue_policy())
        self.assertEqual({'max_concurrent', 'auto_retry', 'max_retries',
                          'pause_on_error'}, read)
        self.assertEqual(read, looked_up,
                         'the queue reads config.json under names other than the ones it returns')
        self.assertTrue(looked_up <= written,
                        f'the queue reads {sorted(looked_up - written)}, which the Settings '
                        f'tab never writes')


if __name__ == '__main__':
    unittest.main(verbosity=2)
