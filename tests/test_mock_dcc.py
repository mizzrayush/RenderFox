"""
Mock DCC harness tests.

No 3D package is installed here, so the launch path in `render_engines.py`
(command assembly, availability probes, progress syntax, exit codes, stop and
pause) had never been executed against a process. These tests run it against a
real child process that emulates each package, through the engines' own
`render_job`, with no monkeypatching of the code under test.

Run: python -X utf8 tests/test_mock_dcc.py
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

import psutil

from mock_dcc import harness
from mock_dcc import mock_dcc as dcc
from src.core.models import RenderJob, SoftwareType
from src.processing.render_engines import (BlenderEngine, Cinema4DEngine,
                                           MayaEngine, UnrealEngine,
                                           create_render_engine,
                                           detect_available_software)

# What each package prints per frame, in its own syntax. The parsers in
# `render_engines.py` are written against these lines rather than a guess, and
# test_03 below keeps the mock honest about printing them.
PROGRESS_LINES = {
    'blender': ['Fra:1/3 Rendered', 'Fra:2/3 Rendered', 'Fra:3/3 Rendered', 'Blender quit'],
    'maya': ['// Rendering frame 1 of 3 //', '// Rendering frame 2 of 3 //',
             '// Rendering frame 3 of 3 //'],
    'cinema4d': ['Frame 1 rendered (1/3)', 'Frame 2 rendered (2/3)', 'Frame 3 rendered (3/3)'],
    'unreal': ['[ 100.0%] Frame 1 ( 1/3 )', '[ 100.0%] Frame 2 ( 2/3 )',
               '[ 100.0%] Frame 3 ( 3/3 )'],
}

CLASSES = {'blender': BlenderEngine, 'maya': MayaEngine,
           'cinema4d': Cinema4DEngine, 'unreal': UnrealEngine}


class MockDCCCase(unittest.TestCase):
    """Sandbox with the shims installed, a config.json in cwd, and an out/ directory."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='renderfox_mock_dcc_')
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
        self.live = []
        for name in glob.glob(os.path.join(self.out, '*')):
            os.remove(name)

    def tearDown(self):
        # A test that fails between pause() and resume() would otherwise leave a
        # suspended renderer process on the machine indefinitely.
        for engine in self.live:
            engine.stop()
            engine.resume()

    def engine(self, key):
        engine = CLASSES[key](self.executables[key])
        self.live.append(engine)
        return engine

    def job(self, key, frames=None, name='hero', **scene):
        scene.setdefault('seconds_per_frame', 0.02)
        scene.setdefault('output_dir', self.out)
        scene.setdefault('prefix', name)
        project = harness.write_scene(self.work, key, name=name, **scene)
        return RenderJob(
            id=f'{key}-{name}', name=name, project_file=project,
            software_type=SoftwareType(key),
            output_path=os.path.join(self.out, f'{name}.png'),
            resolution=(960, 540), frame_range=frames, output_format='png')

    def launch(self, key, job):
        """Run the command the engine itself assembles, and keep its output."""
        return subprocess.run(self.engine(key).get_render_command(job),
                              capture_output=True, text=True,
                              encoding='utf-8', errors='replace')

    def frames_written(self, prefix='hero'):
        return sorted(os.path.basename(path) for path in
                      glob.glob(os.path.join(self.out, f'{prefix}_0*')))

    def run_render_in_thread(self, engine, job, results):
        worker = threading.Thread(target=lambda: results.setdefault(
            'ok', engine.render_job(job)), daemon=True)
        worker.start()
        deadline = time.time() + 10
        while engine.current_process is None and time.time() < deadline:
            time.sleep(0.01)
        return worker


class TestMockPackageBehaviour(MockDCCCase):
    """The stand-in has to be as fussy as the real thing, or it proves nothing."""

    def test_01_version_banner_satisfies_each_engines_probe(self):
        for key in CLASSES:
            with self.subTest(package=key):
                engine = self.engine(key)
                self.assertTrue(engine.is_available(),
                                f'{key} was refused at its own executable path')
                self.assertTrue(engine.get_version())

    def test_02_blender_banner_parses_to_a_real_version_number(self):
        self.assertEqual('4.3.0', BlenderEngine(self.executables['blender']).get_version())

    def test_03_progress_lines_use_the_documented_syntax(self):
        for key, expected in PROGRESS_LINES.items():
            with self.subTest(package=key):
                job = self.job(key, frames=(1, 3))
                run = self.launch(key, job)
                self.assertEqual(0, run.returncode, run.stdout + run.stderr)
                for line in expected:
                    self.assertIn(line, run.stdout,
                                  f'{key} did not print its own progress syntax')

    def test_04_failure_exits_nonzero_with_the_reason_on_stderr(self):
        job = self.job('blender', frames=(1, 4), fail_after=2)
        engine = self.engine('blender')
        self.assertFalse(engine.render_job(job))
        self.assertIn('sample limit', job.error_message or '',
                      'the engine discarded the renderer stderr')

    def test_05_missing_output_directory_is_reported(self):
        job = self.job('blender', frame_count=2,
                       output_dir=os.path.join(self.work, 'nope'))
        run = self.launch('blender', job)
        self.assertEqual(31, run.returncode, run.stdout + run.stderr)
        self.assertIn('output directory does not exist', run.stderr)

    def test_06_rejects_command_lines_the_engines_do_not_build(self):
        job = self.job('blender', frame_count=1)
        base = ['--background', job.project_file, '--render-output', job.output_path,
                '--render-format', 'PNG', '--render-frame', '1']
        cases = {
            'no --background': [item for item in base if item != '--background'],
            'no output path': [item for item in base if item not in
                               ('--render-output', job.output_path)],
            'no frame request': [item for item in base if item not in
                                 ('--render-frame', '1')],
            'unknown flag': base + ['--turbo'],
        }
        for label, argv in cases.items():
            with self.subTest(case=label):
                run = harness.run('blender', *argv)
                self.assertEqual(20, run.returncode, run.stdout + run.stderr)

    def test_07_reads_one_mel_quoted_value_and_never_two(self):
        """A MEL value is read up to its closing quote, not to the last one.

        `"(.*)"` runs through the following statement, so the directory the mock
        renders into used to come back as the directory plus half the command -
        which is how a path with no folder in it turned into exit 31 "output
        directory does not exist" for a directory that plainly did.
        """
        command = ('setAttr defaultResolution.width 960; '
                   'workspace -fr "images" "D:/renders/hero"; '
                   'setAttr -type "string" defaultRenderGlobals.imageFilePrefix "shot_01"; '
                   'setAttr defaultRenderGlobals.imageFormat 32; render -batch;')
        self.assertEqual('D:/renders/hero', dcc.mel_string(command, 'workspace -fr "images"'))
        self.assertEqual('shot_01', dcc.mel_string(command, 'defaultRenderGlobals.imageFilePrefix'))
        self.assertEqual('D:/say"hi"',
                         dcc.mel_string(r'workspace -fr "images" "D:/say\"hi\""; render;',
                                        'workspace -fr "images"'))
        for broken in ('setAttr defaultResolution.width 960; render -batch;',
                       'workspace -fr "images" ; render -batch;',
                       'workspace -fr "images" D:/unquoted; render -batch;'):
            with self.subTest(command=broken):
                with self.assertRaises(SystemExit):
                    dcc.mel_string(broken, 'workspace -fr "images"')


class TestEngineLaunchPath(MockDCCCase):
    """The four engine classes assemble commands a real renderer would accept."""

    def test_01_every_engine_renders_its_own_command(self):
        for key in CLASSES:
            with self.subTest(package=key):
                job = self.job(key, frames=(1, 3), name=key)
                engine = self.engine(key)
                self.assertTrue(engine.render_job(job),
                                f'{key} failed: {job.error_message}\n'
                                f'{engine.get_render_command(job)}')
                produced = self.frames_written(prefix=key)
                self.assertEqual(3, len(produced), f'{key} wrote {produced}')

    def test_02_blender_frame_range_reaches_the_command_line(self):
        job = self.job('blender', frames=(7, 9))
        command = ' '.join(self.engine('blender').get_render_command(job))
        for fragment in ('--frame-start 7', '--frame-end 9', '--render-anim'):
            self.assertIn(fragment, command)
        self.assertTrue(self.engine('blender').render_job(job), job.error_message)
        self.assertEqual(['hero_0007.png', 'hero_0008.png', 'hero_0009.png'],
                         self.frames_written())

    def test_03_blender_single_frame_job_renders_one_frame(self):
        job = self.job('blender')
        self.assertTrue(self.engine('blender').render_job(job), job.error_message)
        self.assertEqual(['hero_0001.png'], self.frames_written())

    def test_04_maya_mel_carries_resolution_format_and_frames(self):
        job = self.job('maya', frames=(1, 2))
        command = ' '.join(self.engine('maya').get_render_command(job))
        self.assertIn('defaultResolution.width 960', command)
        self.assertIn('imageFormat 32', command)
        self.assertIn('startFrame 1', command)
        self.assertIn('endFrame 2', command)
        written_to = dcc.mel_string(command.split(' -command ', 1)[1],
                                    'workspace -fr "images"')
        self.assertEqual(os.path.normpath(self.out), os.path.normpath(written_to),
                         'Maya was told to render somewhere other than the job output folder')

    def test_05_unreal_passes_the_pipeline_config_it_writes(self):
        job = self.job('unreal')
        engine = self.engine('unreal')
        tail = [part for part in engine.get_render_command(job)
                if part.startswith('-MoviePipelineConfig=')]
        self.assertEqual(1, len(tail))
        with open(tail[0].split('=', 1)[1], encoding='utf-8') as handle:
            config = json.load(handle)
        self.assertEqual(os.path.dirname(job.output_path), config['OutputDirectory'])
        self.assertEqual(1, config['EndFrame'])
        self.assertTrue(engine.render_job(job), job.error_message)

    def test_06_factory_returns_the_matching_class(self):
        for key, expected in CLASSES.items():
            engine = create_render_engine(SoftwareType(key), self.executables[key])
            self.assertIsInstance(engine, expected)

    def test_07_stop_terminates_the_render_process(self):
        job = self.job('blender', frame_count=40, seconds_per_frame=0.1)
        engine = self.engine('blender')
        results = {}
        worker = self.run_render_in_thread(engine, job, results)
        pid = engine.current_process.pid
        engine.stop()
        worker.join(timeout=20)
        self.assertFalse(results.get('ok', True), 'a stopped render reported success')
        self.assertFalse(pid_is_live(pid), 'the renderer survived stop()')
        self.assertLess(len(self.frames_written()), 40,
                        'stop() arrived after every frame had already landed')

    def test_08_pause_freezes_the_process_and_resume_finishes_it(self):
        job = self.job('blender', frame_count=6, seconds_per_frame=0.2)
        engine = self.engine('blender')
        results = {}
        worker = self.run_render_in_thread(engine, job, results)
        engine.pause()
        frozen = len(self.frames_written())
        time.sleep(0.8)
        self.assertEqual(frozen, len(self.frames_written()),
                         'frames kept landing after pause()')
        engine.resume()
        worker.join(timeout=30)
        self.assertTrue(results.get('ok', False),
                        f'resume did not finish the render: {job.error_message}')
        self.assertEqual(6, len(self.frames_written()))

    def test_09_configured_path_is_discovered_by_the_detector(self):
        """`config.json` in the working directory is how a user points RenderFox at their install.

        Every engine has to be looked up through it, not just Blender: the queue
        refuses a job whose software is missing from this dict, so a configured
        Maya that the detector never asks about fails with "No render engine
        available for maya" before a command line is ever built.
        """
        found = detect_available_software()
        for key in CLASSES:
            with self.subTest(package=key):
                self.assertIn(SoftwareType(key), found,
                              f'{key} is configured in config.json and was still not detected')

    def test_10_progress_lines_move_the_bar_while_the_render_runs(self):
        """Each package's frame lines are read, not discarded.

        Phase 3 recorded the opposite ceiling - `get_progress()` was a constant
        0.0 and `render_job` used `communicate()`, so stdout only existed after
        the render was over. That test had to go; this is the one it promised.
        """
        for key in CLASSES:
            with self.subTest(package=key):
                job = self.job(key, frames=(1, 4), name=key)
                seen = []
                engine = self.engine(key)
                engine.set_progress_callback(seen.append)
                self.assertTrue(engine.render_job(job), job.error_message)
                self.assertEqual([25.0, 50.0, 75.0, 100.0], seen,
                                 f'{key} frame lines did not drive the callback')

    def test_11_progress_is_readable_before_the_renderer_exits(self):
        """The value has to land while the process is still live, or the bar is a lie."""
        job = self.job('blender', frame_count=8, seconds_per_frame=0.15)
        engine = self.engine('blender')
        results = {}
        worker = self.run_render_in_thread(engine, job, results)
        pid = engine.current_process.pid
        deadline = time.time() + 10
        while engine.get_progress() == 0.0 and time.time() < deadline:
            time.sleep(0.01)
        self.assertGreater(engine.get_progress(), 0.0, 'no progress was ever reported')
        self.assertTrue(worker.is_alive(), 'the render had already finished - nothing was live')
        self.assertTrue(pid_is_live(pid), 'progress came from a process that had exited')
        worker.join(timeout=30)
        self.assertTrue(results.get('ok', False), job.error_message)
        self.assertEqual(8, len(self.frames_written()))
        self.assertEqual(100.0, engine.get_progress())

    def test_12_a_silent_renderer_that_writes_nothing_is_reported_as_failed(self):
        job = self.job('blender', frame_count=2, silent=True, write_files=False)
        engine = self.engine('blender')
        self.assertFalse(engine.render_job(job),
                         'exit code 0 with no frame and no file passed as a render')
        self.assertIn('without reporting a frame', job.error_message or '')
        self.assertEqual(0.0, engine.get_progress())

    def test_13_frames_on_disk_succeed_without_any_progress_lines(self):
        """A build that words its frame lines differently is not a false failure.

        The parsers are written against the syntax `PROGRESS_LINES` records here,
        which is the closest thing to a real package this machine can produce.
        Exit code 0 plus files that were not there before is evidence that does
        not depend on matching a string.
        """
        job = self.job('blender', frame_count=3, silent=True)
        engine = self.engine('blender')
        self.assertTrue(engine.render_job(job), job.error_message)
        self.assertEqual(3, len(self.frames_written()))
        self.assertEqual(100.0, engine.get_progress())

    def test_14_a_chatty_renderer_does_not_deadlock_the_pipes(self):
        """Both pipes need their own reader: fill one 4 KB buffer and the renderer
        blocks writing the other while the app waits on the first."""
        job = self.job('maya', frames=(1, 3), noise=60)
        engine = self.engine('maya')
        results = {}
        worker = self.run_render_in_thread(engine, job, results)
        worker.join(timeout=60)
        self.assertFalse(worker.is_alive(), 'reading 3 frames of output never finished')
        self.assertTrue(results.get('ok', False), job.error_message)
        self.assertEqual(100.0, engine.get_progress())

    def test_15_a_bare_output_filename_renders_into_the_working_directory(self):
        """`dirname('hero.png')` is the empty string, and `makedirs('')` is a crash.

        The queue is built from a folder picker *or* a typed name, so an output
        path with no directory in it has to mean "right here" for every engine,
        in the command line as well as in the folder the app creates.
        """
        for key in CLASSES:
            with self.subTest(package=key):
                job = self.job(key, frames=(1, 2), name=f'bare-{key}', output_dir=None)
                job.output_path = f'{key}_hero.png'
                engine = self.engine(key)
                self.assertTrue(engine.render_job(job), f'{key}: {job.error_message}')
                self.assertEqual(100.0, engine.get_progress())
                landed = sorted(os.path.basename(path) for path in
                                glob.glob(os.path.join(self.work, f'bare-{key}_0*.png')))
                self.assertEqual([f'bare-{key}_0001.png', f'bare-{key}_0002.png'], landed,
                                 f'{key} put a bare-name render somewhere unexpected')

    def test_16_a_second_render_over_the_same_filenames_is_not_a_failure(self):
        """Re-rendering a shot keeps the frame names and moves only their mtimes.

        "the output folder is unchanged" is therefore not evidence that nothing
        rendered, and the file comparison has to look at modified times too.
        """
        engine = self.engine('blender')
        first = self.job('blender', frame_count=3, silent=True)
        self.assertTrue(engine.render_job(first), first.error_message)
        again = self.job('blender', frame_count=3, silent=True)
        self.assertTrue(engine.render_job(again),
                        f'the second pass over the same names was refused: {again.error_message}')
        self.assertEqual(3, len(self.frames_written()))

    def test_17_frame_lines_on_stderr_move_the_bar_too(self):
        """Which pipe a build reports frames on is not this app's choice.

        Reading progress from stdout alone would leave the bar stuck at 0 for a
        build that writes its frame lines to stderr, so both streams are
        watched and parsed the same way.
        """
        for key in CLASSES:
            with self.subTest(package=key):
                job = self.job(key, frames=(1, 4), name=key, stderr_progress=True)
                seen = []
                engine = self.engine(key)
                engine.set_progress_callback(seen.append)
                self.assertTrue(engine.render_job(job), job.error_message)
                self.assertEqual([25.0, 50.0, 75.0, 100.0], seen,
                                 f'{key} reported frames on stderr and none reached the bar')


def pid_is_live(pid):
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


if __name__ == '__main__':
    unittest.main(verbosity=2)
