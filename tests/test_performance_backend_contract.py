"""
Performance backend contract - the frame clock, the monitor, the score and the one engine.

This suite exists because the two files it covers used to answer questions nothing measured.
`PerformanceMonitor` divided one monitoring sample by the next - a gap of about one second,
whatever the screen did - and called it `fps`, with a `0.016` fallback under it that the
line above made unreachable. None of those numbers reached a screen: no pane read `fps` or
`frame_time_ms`, and the one function that turned them into a verdict had no caller.
`gpu_percent` was `0.0` both when
the adapter was idle and when nothing read it, which on this machine is every second.
`BottleneckDetector.score` handed back 100 when its inputs were missing.
`OptimizationSuggester` promised "30-50%" and "double or triple FPS". A benchmark summed a
million square roots, beat its own threshold and printed "Top 1%" against a field of results
RenderFox has never collected from anyone, and two engines in one process gave the same
machine two different answers two tabs apart.

What is pinned here, in order:

* `src/utils/frame_clock.py` is the only source of frame timing: a rate is arithmetic over
  stamps the app's own views made, and every case with no gaps to take says which kind of
  nothing it is;
* a sample carries the window it covers, and a field no reader answered is None with its
  reason in `not_read` - never 0.0, never the previous answer;
* the detector compares only measured fields, quotes the limit and the window in every
  finding, and the score refuses when the two fields it most depends on were never read;
* advice names the reading that caused it and the control in this app that changes it, and
  promises no percentage;
* the benchmark engine performs four kinds of bounded work, records what it did on this
  machine, and compares a run only with the app's own earlier runs; a fifth kind is refused
  by name;
* the words a table cell and a paragraph show come from the engine, so two panes cannot
  grade one machine differently;
* the Performance pane paints those words and computes nothing of its own.

Run: python -X utf8 tests/test_performance_backend_contract.py
"""

import ast
import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

# Before anything reads it: a benchmark history and a performance log belong in the app's
# data folder, and a test suite must not be the thing that fills the real one on this
# machine - or leave a folder behind in it.
DATA_DIR = tempfile.mkdtemp(prefix='rf-perf-data-')
os.environ['RENDERFOX_DATA_DIR'] = DATA_DIR

from src.features.performance_analyzer import (
    LIMITS, SCORE_WEIGHTS, BenchmarkHistory, BenchmarkRunner, BottleneckDetector,
    FunctionProfiler, OptimizationSuggester, PerformanceAnalyzer, PerformanceLogger,
    PerformanceMetrics, PerformanceMonitor, ProfileResult, benchmark_engine, data_dir)
from src.features import performance_analyzer as ANALYZER
from src.utils.frame_clock import FrameClock, shared_clock

PANE = os.path.join(ROOT, 'src', 'ui', 'performance_tab.py')
ENGINE_FILE = os.path.join(ROOT, 'src', 'features', 'performance_analyzer.py')
VIEWER_FILE = os.path.join(ROOT, 'src', 'ui', 'model_viewer.py')
DIAG_FILE = os.path.join(ROOT, 'src', 'ui', 'diagnostics_tab.py')
BACKEND_FILE = os.path.join(ROOT, 'src', 'features', 'diagnostic_engine.py')

RATINGS = ('Top 1%', 'Top 10%', 'Top 25%', 'Excellent', 'Outstanding')


def source(path):
    with open(path, encoding='utf-8') as handle:
        return handle.read()


def code_of(path):
    """The file as code only: comments go with `ast.unparse`, docstrings are blanked here.

    Every phase of this app documents the claim it deleted - "this used to print
    Top 1%" - so a ban on a word has to read what the code says, not the sentence
    explaining why the word is gone. A claim that survives only in prose is not a claim.
    """
    tree = ast.parse(source(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            first = node.body and node.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                first.value.value = ''
    return ast.unparse(tree)


def metrics(**over):
    """One sample with every field measured, unless the test says otherwise."""
    row = {'timestamp': time.time(), 'window_seconds': 1.0, 'cpu_percent': 10.0,
           'process_cpu_percent': 5.0, 'memory_percent': 20.0, 'memory_used_mb': 4096.0,
           'memory_available_mb': 8192.0, 'process_rss_mb': 300.0,
           'gpu_load_percent': 30.0, 'gpu_memory_percent': 25.0, 'gpu_temperature_c': 50.0,
           'gpu_reader': 'test reader', 'fps': 60.0, 'frame_time_ms': 16.0,
           'slowest_frame_ms': 20.0, 'frames': 60, 'not_read': {}}
    row.update(over)
    return PerformanceMetrics(**row)


def unmeasured(*names):
    """A sample whose named fields no reader answered for, each with its reason."""
    row = {name: None for name in names}
    row['not_read'] = {name: 'the reader said no' for name in names}
    return metrics(**row)


class Test01LiveSample(unittest.TestCase):
    """The monitor on this machine, which is the only machine it can be tested against."""

    def setUp(self):
        self.clock = FrameClock()
        self.monitor = PerformanceMonitor(clock=self.clock)

    def tearDown(self):
        self.monitor.stop_monitoring()

    def test_01_an_unprimed_sample_refuses_the_cpu_figure_it_cannot_take(self):
        """`cpu_percent(interval=None)` before a first call answers 0.0 about nothing."""
        sample = self.monitor.sample()
        self.assertIsNone(sample.cpu_percent, 'the first call answered 0.0, which is a number')
        self.assertIsNone(sample.process_cpu_percent)
        self.assertIn('cpu_percent', sample.not_read)
        self.assertIn('prime', sample.not_read['cpu_percent'])
        self.assertIsNone(sample.window_seconds, 'a sample with no window claims one')

    def test_02_the_figure_covers_the_window_between_two_samples(self):
        self.monitor.start_monitoring(interval_ms=1000)
        time.sleep(0.12)
        sample = self.monitor.sample()
        self.assertIsInstance(sample.cpu_percent, float)
        self.assertGreaterEqual(sample.window_seconds, 0.1,
                                'the window printed beside the figure is not the window taken')
        self.assertLess(sample.window_seconds, 5.0)

    def test_03_a_sample_does_not_sit_on_the_thread_that_paints(self):
        """The version this replaced called `cpu_percent(interval=0.1)` once a second."""
        self.monitor.start_monitoring()
        self.monitor.sample()
        started = time.perf_counter()
        self.monitor.sample()
        self.assertLess(time.perf_counter() - started, 0.05,
                        'a sample blocked for the length of its own window')

    def test_04_the_machine_and_this_process_are_read_every_sample(self):
        sample = self.monitor.sample()
        self.assertGreater(sample.memory_percent, 0.0)
        self.assertGreater(sample.memory_used_mb, 0.0)
        self.assertGreater(sample.process_rss_mb, 0.0)
        self.assertEqual([], [line for line in sample.unmeasured()
                              if line.startswith(('memory_percent', 'process_rss_mb'))])

    def test_05_an_adapter_nothing_reads_is_a_reason_and_not_an_idle_chip(self):
        sample = self.monitor.sample()
        self.assertIsNone(sample.gpu_load_percent)
        self.assertIsNone(sample.gpu_memory_percent)
        self.assertIn('GPU reader', sample.not_read['gpu_load_percent'])
        # The sentence has to name the absence. A monitor that reached for a reader it was
        # never given gets a `TypeError` from the call, and that reads as a broken adapter.
        for field in ('gpu_load_percent', 'gpu_memory_percent'):
            reason = sample.not_read[field]
            self.assertIn('not given a GPU reader', reason,
                          f'{field} was explained as {reason!r}')
            self.assertNotIn('raised', reason,
                             'no reader was reported as a reader that failed')
        self.assertNotIn(0.0, (sample.gpu_load_percent, sample.gpu_memory_percent),
                         'an unread adapter was reported as an idle one')

    def test_06_a_field_the_clock_has_no_stamps_for_is_not_a_frame_rate(self):
        sample = self.monitor.sample()
        self.assertIsNone(sample.fps)
        self.assertEqual(0, sample.frames)
        self.assertIn('no 3D view has drawn a frame', sample.not_read['fps'])

    def test_07_the_averages_count_the_samples_that_hold_a_number(self):
        self.monitor.metrics_history.extend([
            metrics(cpu_percent=10.0, gpu_load_percent=None, fps=None, frame_time_ms=None,
                    not_read={'gpu_load_percent': 'nothing reads the adapter',
                              'fps': 'no 3D view has drawn a frame'}),
            metrics(cpu_percent=30.0, gpu_load_percent=10.0, fps=None, frame_time_ms=None,
                    not_read={'fps': 'one frame is not a rate'})])
        averages = self.monitor.get_average_metrics()
        self.assertEqual(2, averages['samples'])
        self.assertEqual(20.0, averages['cpu_percent'])
        self.assertEqual(2, averages['cpu_percent_of'])
        self.assertEqual(1, averages['gpu_load_percent_of'],
                         'an average of one reading was reported as two')
        self.assertEqual(10.0, averages['gpu_load_percent'],
                         'the missing reading was averaged in as a zero')
        self.assertIsNone(averages['fps'], 'a field with no values answered 0.0')
        self.assertEqual(0, averages['fps_of'])
        self.assertEqual(0, averages['frame_time_ms_of'])

    def test_08_the_peaks_are_the_highest_value_seen_and_say_how_many_that_was(self):
        self.monitor.metrics_history.extend([
            metrics(cpu_percent=11.0, memory_percent=40.0),
            metrics(cpu_percent=71.0, memory_percent=41.0),
            metrics(cpu_percent=None, memory_percent=None,
                    not_read={'cpu_percent': 'no window'})])
        peaks = self.monitor.get_peak_metrics()
        self.assertEqual(3, peaks['samples'])
        self.assertEqual(71.0, peaks['cpu_percent'])
        self.assertEqual(2, peaks['cpu_percent_of'])
        self.assertEqual(41.0, peaks['memory_percent'])

    def test_09_the_history_is_bounded(self):
        small = PerformanceMonitor(history_size=3, clock=self.clock)
        for _ in range(7):
            small.metrics_history.append(metrics())
        self.assertEqual(3, len(small.metrics_history))
        self.assertEqual(3, small.get_average_metrics()['samples'])

    def test_10_a_sample_the_timer_takes_lands_in_the_history_and_in_the_signal(self):
        seen = []
        self.monitor.metrics_updated.connect(seen.append)
        self.monitor._update_metrics()
        self.assertEqual(1, len(self.monitor.metrics_history))
        self.assertEqual(1, len(seen), 'the pane is never told a sample happened')
        self.assertIn('not_read', seen[0], 'the dictionary painted has no room for reasons')


class Test10bCpuPriming(unittest.TestCase):
    """The prime is one call nobody can see in the figure it protects.

    `psutil.cpu_percent(interval=None)` answers 0.0 on the very first call in a process and
    the share of the time since its previous call on every one after. So a monitor that
    forgets to prime reports "0.0 % busy" for a machine it measured for no time at all, and
    the number is a float, in range, and wrong. This class hands the module a psutil that
    behaves exactly as its own documentation says - silence first, a figure afterwards - so
    the prime is proved by the reading it makes possible rather than by grepping the call.
    """

    class _Psutil:
        def __init__(self):
            self.system_reads = 0
            self.process_reads = 0

        def cpu_percent(self, interval=None):
            self.system_reads += 1
            return 0.0 if self.system_reads == 1 else 42.0

        def virtual_memory(self):
            return SimpleNamespace(percent=20.0, used=4 * 1024 ** 3, available=8 * 1024 ** 3)

        def Process(self, pid):
            outer = self

            class _Process:
                def cpu_percent(self, interval=None):
                    outer.process_reads += 1
                    return 0.0 if outer.process_reads == 1 else 17.0

                def memory_info(self):
                    return SimpleNamespace(rss=300 * 1024 ** 2)

            return _Process()

    def setUp(self):
        self.fake = Test10bCpuPriming._Psutil()
        self.real = ANALYZER.psutil
        ANALYZER.psutil = self.fake
        self.monitor = PerformanceMonitor(clock=FrameClock())

    def tearDown(self):
        self.monitor.stop_monitoring()
        ANALYZER.psutil = self.real

    def test_10b_starting_the_monitor_primes_the_machine_reader(self):
        self.monitor.start_monitoring(interval_ms=1000)
        time.sleep(0.02)
        sample = self.monitor.sample()
        self.assertGreaterEqual(self.fake.system_reads, 2,
                                'the sample was the first call, so it covered nothing')
        self.assertEqual(42.0, sample.cpu_percent,
                         'the figure reported was psutil\'s meaningless first answer')

    def test_10c_starting_the_monitor_primes_this_process_reader(self):
        self.monitor.start_monitoring(interval_ms=1000)
        time.sleep(0.02)
        sample = self.monitor.sample()
        self.assertGreaterEqual(self.fake.process_reads, 2,
                                'this process was never primed before it was read')
        self.assertEqual(17.0, sample.process_cpu_percent)


class Test11GpuReader(unittest.TestCase):
    """What one adapter reading does to a sample, including when it is wrong."""

    def monitor(self, reader, cache=2.0):
        return PerformanceMonitor(clock=FrameClock(), gpu_reader=reader,
                                  gpu_cache_seconds=cache)

    def test_11_the_readers_own_figures_reach_the_sample(self):
        row = self.monitor(lambda: {'load_percent': 42.5, 'memory_percent': 61.0,
                                    'temperature_c': 55.0, 'reader': 'GPUtil'}).sample()
        self.assertEqual(42.5, row.gpu_load_percent)
        self.assertEqual(61.0, row.gpu_memory_percent)
        self.assertEqual(55.0, row.gpu_temperature_c)
        self.assertEqual('GPUtil', row.gpu_reader)
        self.assertEqual([], [line for line in row.unmeasured() if line.startswith('gpu')],
                         'an adapter that answered every field still left a hole in it')

    def test_12_a_reader_that_raises_is_kept_as_the_failure_it_is(self):
        def explode():
            raise OSError('the helper program did not start')

        row = self.monitor(explode).sample()
        self.assertIsNone(row.gpu_load_percent)
        self.assertIn('OSError', row.not_read['gpu_load_percent'])
        self.assertIn('the helper program did not start', row.not_read['gpu_load_percent'])

    def test_13_a_reader_that_answers_with_nothing_says_that(self):
        row = self.monitor(lambda: {}).sample()
        self.assertIsNone(row.gpu_load_percent)
        self.assertIn('answered nothing', row.not_read['gpu_load_percent'])

    def test_14_a_reader_that_starts_a_program_is_not_asked_every_second(self):
        calls = []
        monitor = self.monitor(lambda: calls.append(1) or {'load_percent': 5.0}, cache=30.0)
        first = monitor.sample()
        second = monitor.sample()
        self.assertEqual(1, len(calls), 'every sample paid for a new helper program')
        self.assertEqual(first.gpu_load_percent, second.gpu_load_percent)

    def test_15_a_partial_reading_keeps_its_hole_visible(self):
        row = self.monitor(lambda: {'load_percent': 20.0, 'reader': 'GPUtil'}).sample()
        self.assertEqual(20.0, row.gpu_load_percent)
        self.assertIsNone(row.gpu_memory_percent)
        self.assertIn('gpu_memory_percent', row.not_read)
        self.assertIn('gpu_memory_percent', ' '.join(row.unmeasured()))


class Test16FunctionProfiler(unittest.TestCase):
    """Timings around the app's own operations, including the ones that never finish."""

    def setUp(self):
        self.profiler = FunctionProfiler()

    def test_16_an_end_with_no_start_is_counted_and_says_so(self):
        self.assertIsNone(self.profiler.end_profile('never.started'))
        self.assertEqual(1, self.profiler.unmatched_ends)
        self.assertIsNone(self.profiler.get_profile_result('never.started'))

    def test_17_a_start_with_no_end_never_reaches_the_table(self):
        self.profiler.start_profile('still.running')
        self.assertEqual([], self.profiler.get_all_results())

    def test_18_a_double_start_is_counted_rather_than_stacking_a_timing(self):
        self.profiler.start_profile('job')
        time.sleep(0.01)
        self.profiler.start_profile('job')
        elapsed = self.profiler.end_profile('job')
        self.assertEqual(1, self.profiler.double_starts)
        self.assertEqual(1, self.profiler.get_profile_result('job').call_count)
        self.assertLess(elapsed, 0.5, 'the first start was kept as well as the second')

    def test_19_the_arithmetic_over_several_calls_holds(self):
        for _ in range(3):
            self.profiler.start_profile('job')
            time.sleep(0.005)
            self.profiler.end_profile('job')
        result = self.profiler.get_profile_result('job')
        self.assertIsInstance(result, ProfileResult)
        self.assertEqual(3, result.call_count)
        self.assertAlmostEqual(result.total_time / 3, result.average_time, places=9)
        self.assertLessEqual(result.min_time, result.average_time)
        self.assertLessEqual(result.average_time, result.max_time)
        self.assertGreater(result.min_time, 0.0, 'a call was timed at zero')

    def test_20_results_are_sorted_and_clearing_one_leaves_the_others(self):
        for name in ('beta', 'alpha'):
            self.profiler.start_profile(name)
            self.profiler.end_profile(name)
        self.assertEqual(['alpha', 'beta'],
                         [r.function_name for r in self.profiler.get_all_results()])
        self.profiler.clear_profile('alpha')
        self.assertEqual(['beta'], [r.function_name
                                    for r in self.profiler.get_all_results()])

    def test_21_clearing_everything_clears_the_complaints_too(self):
        self.profiler.end_profile('nothing')
        self.profiler.start_profile('job')
        self.profiler.clear_all()
        self.assertEqual(0, self.profiler.unmatched_ends)
        self.assertEqual(0, self.profiler.double_starts)
        self.assertIsNone(self.profiler.end_profile('job'),
                          'an operation started before the clear still timed itself')


def stamp_calls(node, name):
    """Every `frame_clock.<name>(...)` call inside a parsed node."""
    return [call for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == name]


class Test22FrameClock(unittest.TestCase):
    """Frames only when a view said it drew one, and the right sentence when it did not."""

    def setUp(self):
        self.clock = FrameClock()

    def now(self):
        return time.perf_counter()

    def test_22_no_stamps_is_not_a_frame_rate(self):
        stats = self.clock.stats()
        self.assertIsNone(stats['fps'])
        self.assertIsNone(stats['frame_time_ms'])
        self.assertEqual(0, stats['frames'])
        self.assertIn('no 3D view has drawn a frame', stats['reason'])
        self.assertIn('nothing was reported as blocking it', stats['reason'])

    def test_23_a_view_that_said_why_it_cannot_draw_says_so_in_the_rate_row(self):
        self.clock.note_blocked('PyOpenGL could not be imported')
        stats = self.clock.stats()
        self.assertIsNone(stats['fps'])
        self.assertIn('PyOpenGL could not be imported', stats['reason'])

    def test_24_one_frame_is_not_a_rate(self):
        self.clock.note_frame('viewA', at=self.now() - 0.05)
        stats = self.clock.stats(window_seconds=1.0)
        self.assertIsNone(stats['fps'], 'one frame became a rate')
        self.assertEqual(1, stats['frames'])
        self.assertIn('one frame is not a rate', stats['reason'])

    def test_25_a_rate_is_arithmetic_over_the_gaps_between_stamps(self):
        now = self.now()
        for offset, name in ((0.30, 'viewA'), (0.20, 'viewA'),
                             (0.175, 'viewA'), (0.15, 'viewB')):
            self.clock.note_frame(name, at=now - offset)
        stats = self.clock.stats(window_seconds=1.0)
        self.assertEqual(4, stats['frames'])
        self.assertAlmostEqual(20.0, stats['fps'], places=0)
        self.assertAlmostEqual(50.0, stats['frame_time_ms'], places=0)
        self.assertAlmostEqual(100.0, stats['slowest_frame_ms'], places=0)
        self.assertEqual(['viewA', 'viewB'], stats['sources'])
        self.assertEqual('', stats['reason'])

    def test_26_the_window_is_measured_from_now_not_from_the_newest_frame(self):
        """The mistake the replaced code made: a burst that ended keeps being reported."""
        now = self.now()
        for index in range(6):
            self.clock.note_frame('viewA', at=now - 5.0 + index * 0.01)
        stats = self.clock.stats(window_seconds=1.0)
        self.assertIsNone(stats['fps'], "a burst from five seconds ago is this second's rate")
        self.assertIn('nothing drew in the last 1 s', stats['reason'])
        self.assertAlmostEqual(5.0, stats['last_frame_seconds_ago'], delta=0.5)
        self.assertEqual(6, stats['total_frames'], 'the frames that ran were forgotten')

    def test_27_stamps_that_carry_the_same_instant_produce_no_rate(self):
        now = self.now()
        self.clock.note_frame('viewA', at=now - 0.1)
        self.clock.note_frame('viewA', at=now - 0.1)
        stats = self.clock.stats(window_seconds=1.0)
        self.assertIsNone(stats['fps'])
        self.assertIn('same timestamp', stats['reason'])

    def test_28_a_paint_that_raised_is_a_failure_not_a_frame(self):
        self.clock.note_failure(ValueError('framebuffer incomplete'))
        stats = self.clock.stats()
        self.assertEqual(1, stats['failures'])
        self.assertIn('ValueError: framebuffer incomplete', stats['last_failure'])
        self.assertEqual(0, stats['total_frames'], 'a failed paint counted as a frame')

    def test_29_the_clock_keeps_a_bounded_number_of_stamps(self):
        small = FrameClock(keep=4)
        now = self.now()
        for index in range(10):
            small.note_frame('viewA', at=now - index * 0.01)
        wide = small.stats(window_seconds=1000.0)
        self.assertEqual(4, wide['frames'], 'the stamps grew without a ceiling')
        self.assertEqual(10, wide['total_frames'])

    def test_30_clearing_leaves_no_frame_behind_to_be_counted_again(self):
        self.clock.note_frame('viewA', at=self.now())
        self.clock.note_blocked('blocked')
        self.clock.clear()
        stats = self.clock.stats()
        self.assertEqual(0, stats['frames'])
        self.assertEqual(0, stats['total_frames'])
        self.assertIsNone(stats['last_frame_seconds_ago'])
        self.assertIsNone(stats['blocked'])
        self.assertIn('nothing was reported as blocking it', stats['reason'])

    def test_31_the_shared_clock_is_the_one_the_views_stamp(self):
        from src.utils import frame_clock
        before = shared_clock().total_frames
        frame_clock.note_frame('test.shared.view')
        self.assertGreaterEqual(shared_clock().total_frames, before + 1)
        self.assertIs(shared_clock(), frame_clock.SHARED)
        stats = shared_clock().stats()
        self.assertEqual(['test.shared.view'], stats['sources'],
                         'the stamp did not reach the clock every pane reads')
        frame_clock.note_blocked('the view said it cannot draw')
        stats = shared_clock().stats()
        self.assertEqual('the view said it cannot draw', stats['blocked'])
        self.assertIn('one frame is not a rate', stats['reason'])
        shared_clock().clear()
        self.assertEqual(0, shared_clock().total_frames)
        self.assertIsNone(shared_clock().stats()['blocked'])

    def test_32_the_refusal_a_sample_carries_is_the_clocks_own_words(self):
        clock = FrameClock()
        clock.note_blocked('no context')
        row = PerformanceMonitor(clock=clock).sample()
        self.assertIsNone(row.fps)
        self.assertIn('no context', row.not_read['fps'])

    def test_33_the_viewer_is_the_thing_that_stamps(self):
        """A rate has to come from the widget that draws, or it is not a rate.

        Where the call sits matters as much as that it is there: a stamp outside the
        `try` counts a frame the drawing never finished, and a failure report in the
        body rather than the handler would stamp failures as frames.
        """
        paints = [node for node in ast.walk(ast.parse(source(VIEWER_FILE)))
                  if isinstance(node, ast.FunctionDef) and node.name == 'paintGL']
        self.assertTrue(paints, 'the 3D view has no paint to stamp')
        for paint in paints:
            self.assertTrue(stamp_calls(paint, 'note_blocked'),
                            'the viewer that cannot draw never says why')
            frames = stamp_calls(paint, 'note_frame')
            failures = stamp_calls(paint, 'note_failure')
            self.assertTrue(frames, 'a finished frame is not stamped by this viewer')
            self.assertTrue(failures, 'a paint that raised is reported to nobody')
            tried = [node for node in ast.walk(paint) if isinstance(node, ast.Try)]
            self.assertTrue(tried, 'the paint has no failure path at all')
            in_body = [call for call in frames for try_node in tried
                       for stmt in try_node.body if call in ast.walk(stmt)]
            self.assertEqual(len(frames), len(in_body),
                             'a frame is stamped even when the drawing raised')
            in_handler = [call for call in failures for try_node in tried
                          for handler in try_node.handlers if call in ast.walk(handler)]
            self.assertEqual(len(failures), len(in_handler),
                             'the failure is reported from outside the except')


class Test34BottleneckDetector(unittest.TestCase):
    """Only a measured field can be a finding, and every finding quotes its limit."""

    def setUp(self):
        self.detector = BottleneckDetector()

    def test_34_a_sample_of_nothings_produces_no_findings(self):
        row = unmeasured('cpu_percent', 'memory_percent', 'gpu_load_percent', 'fps')
        self.assertEqual([], self.detector.analyze(row))
        self.assertEqual(4, len(self.detector.not_measured(row)))

    def test_35_a_reading_past_its_limit_names_the_number_and_the_window(self):
        finding = self.detector.analyze(metrics(cpu_percent=95.0, window_seconds=2.0))[0]
        self.assertEqual('CPU', finding['kind'])
        self.assertIn('95.0% busy', finding['observed'])
        self.assertIn('2.00 s', finding['because'])
        self.assertIn(f"{LIMITS['cpu_percent']:g}", finding['limit'])
        self.assertIn('19% past the', finding['because'])

    def test_36_the_severity_is_how_far_past_the_limit_the_reading_went(self):
        medium = self.detector.analyze(metrics(cpu_percent=85.0))[0]
        high = self.detector.analyze(metrics(cpu_percent=100.0))[0]
        self.assertEqual('Medium', medium['severity'])
        self.assertEqual('High', high['severity'])

    def test_37_an_unread_adapter_is_never_a_finding_about_an_idle_adapter(self):
        row = unmeasured('gpu_load_percent')
        self.assertEqual([], [f for f in self.detector.analyze(row) if f['kind'] == 'GPU'])

    def test_38_the_adapter_finding_names_the_reader_that_produced_it(self):
        finding = self.detector.analyze(metrics(gpu_load_percent=99.0,
                                                gpu_reader='GPUtil'))[0]
        self.assertIn('99.0% load reported by GPUtil', finding['observed'])

    def test_39_slow_frames_and_slow_frame_time_are_two_different_findings(self):
        findings = self.detector.analyze(metrics(fps=12.0, frame_time_ms=80.0))
        self.assertEqual(['Frames', 'Frame time'], [f['kind'] for f in findings])
        self.assertIn('12.0 fps from 60 frames the app itself drew', findings[0]['observed'])
        self.assertIn('80.0 ms between finished frames', findings[1]['observed'])

    def test_40_a_reading_exactly_at_its_limit_is_not_over_it(self):
        self.assertEqual([], self.detector.analyze(metrics(cpu_percent=LIMITS['cpu_percent'])))
        self.assertEqual([], self.detector.analyze(metrics(fps=LIMITS['fps'])))

    def test_41_the_score_is_arithmetic_over_the_deductions_it_lists(self):
        row = metrics(cpu_percent=100.0, memory_percent=50.0, gpu_load_percent=None,
                      fps=60.0, not_read={'gpu_load_percent': 'nothing reads the adapter'})
        score = self.detector.score(row)
        self.assertEqual(90, score['value'])
        self.assertEqual(3, len(score['basis']))
        self.assertIn('cpu_percent 100.0% is 20.0 points above the CPU limit (-10.0)',
                      score['basis'][0])
        self.assertIn('memory_percent 50.0% is within its 85 limit', score['basis'][1])
        self.assertIn('gpu_load_percent', score['missing'][0])

    def test_42_the_score_refuses_when_the_fields_it_needs_were_never_read(self):
        score = self.detector.score(unmeasured('cpu_percent', 'fps'))
        self.assertIsNone(score['value'], 'a score of 100 from no readings is an all-clear')
        self.assertIn('refused', score['reason'])
        self.assertIn('cpu_percent', score['reason'])

    def test_43_every_deduction_the_score_makes_is_one_it_lists(self):
        row = metrics(cpu_percent=100.0, memory_percent=100.0, gpu_load_percent=100.0,
                      fps=1.0)
        expected = (100
                    - (100 - LIMITS['cpu_percent']) * SCORE_WEIGHTS['cpu_percent']
                    - (100 - LIMITS['memory_percent']) * SCORE_WEIGHTS['memory_percent']
                    - (100 - LIMITS['gpu_load_percent']) * SCORE_WEIGHTS['gpu_load_percent']
                    - (LIMITS['fps'] - 1.0) * SCORE_WEIGHTS['fps'])
        score = self.detector.score(row)
        self.assertEqual(int(round(expected)), score['value'])
        self.assertEqual(4, len(score['basis']))
        self.assertEqual([], score['missing'])

    def test_44_a_score_never_leaves_the_band_it_claims_to_be_in(self):
        row = metrics(cpu_percent=100.0, memory_percent=100.0, gpu_load_percent=100.0,
                      fps=0.1, frame_time_ms=9000.0, frames=1)
        self.assertGreaterEqual(self.detector.score(row)['value'], 0)
        self.assertLessEqual(self.detector.score(metrics())['value'], 100)

    def test_45_the_weights_and_limits_are_written_down_once(self):
        text = source(ENGINE_FILE)
        self.assertEqual(1, text.count("'cpu_percent': 80.0"),
                         'a limit was repeated in the code instead of read from LIMITS')
        scored = ('cpu_percent', 'memory_percent', 'gpu_load_percent', 'fps')
        self.assertEqual(set(scored), set(SCORE_WEIGHTS),
                         'a weight exists for a field the score does not read')
        for name in scored:
            self.assertIn(name, LIMITS, f'{name} is weighted against no limit')


class Test46Suggester(unittest.TestCase):
    """Advice that points at a reading and at a control, and promises nothing else."""

    def setUp(self):
        self.detector = BottleneckDetector()
        self.suggester = OptimizationSuggester()

    def test_46_every_suggestion_belongs_to_a_reading_that_is_over_a_limit(self):
        row = metrics(cpu_percent=99.0, memory_percent=99.0)
        findings = self.detector.analyze(row)
        suggestions = self.suggester.get_suggestions(row, findings)
        kinds = {f['kind'] for f in findings}
        self.assertEqual(3, len(suggestions), 'advice arrived for a category nothing exceeded')
        for suggestion in suggestions:
            self.assertIn(suggestion['category'], kinds)
            self.assertIn('99', suggestion['because'],
                          'advice appeared with no reading quoted in it')
            self.assertTrue(suggestion['where_to_change'])

    def test_47_a_suggestion_names_the_control_in_this_app_that_changes_the_number(self):
        row = metrics(cpu_percent=99.0)
        suggestion = self.suggester.get_suggestions(row, self.detector.analyze(row))[0]
        self.assertIn('Max Concurrent Jobs', suggestion['where_to_change'])
        self.assertIn('Settings pane', suggestion['where_to_change'])

    def test_48_no_percentage_of_an_unmeasured_benefit_survives_anywhere(self):
        text = code_of(ENGINE_FILE)
        for promise in ('30-50', 'double or triple', 'improve FPS by', "'impact'"):
            self.assertNotIn(promise, text, f'the backend still promises {promise!r}')
        for row in (metrics(cpu_percent=99.0, memory_percent=99.0, gpu_load_percent=99.0,
                            fps=1.0, frame_time_ms=99.0), metrics()):
            body = json.dumps(self.suggester.get_suggestions(row, self.detector.analyze(row)))
            for promise in ('30-50', 'double or triple', 'impact'):
                self.assertNotIn(promise, body)

    def test_49_the_memory_advice_admits_the_app_may_not_be_the_one_holding_it(self):
        row = metrics(memory_percent=97.0, cpu_percent=10.0)
        text = json.dumps(self.suggester.get_suggestions(row, self.detector.analyze(row)))
        self.assertIn('cannot promise that clearing its own cache is enough', text)

    def test_50_nothing_past_a_limit_says_that_instead_of_giving_advice(self):
        row = metrics()
        suggestions = self.suggester.get_suggestions(row, self.detector.analyze(row))
        self.assertEqual(1, len(suggestions))
        self.assertIn('nothing that was measured is past a limit',
                      suggestions[0]['suggestion'])
        self.assertIn('cpu 10.0', suggestions[0]['because'])
        self.assertEqual('', suggestions[0]['where_to_change'])

    def test_51_an_incomplete_sample_says_it_was_incomplete(self):
        row = unmeasured('gpu_load_percent')
        suggestion = self.suggester.get_suggestions(row, self.detector.analyze(row))[0]
        self.assertIn('this sample was incomplete', suggestion['suggestion'])
        self.assertIn('gpu_load_percent: the reader said no', suggestion['because'])


class Test52PerformanceLogger(unittest.TestCase):
    """One line per sample, when asked - not a folder at import time."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='rf-perf-log-')

    def test_52_making_a_logger_makes_no_directory(self):
        target = os.path.join(self.dir, 'not-yet')
        PerformanceLogger(log_dir=target)
        self.assertFalse(os.path.exists(target),
                         "importing the pane made a folder appear on the user's disk")

    def test_53_one_call_appends_one_line(self):
        logger = PerformanceLogger(log_dir=os.path.join(self.dir, 'logs'))
        first = logger.log_metrics(metrics(cpu_percent=11.0))
        second = logger.log_metrics(metrics(cpu_percent=12.0))
        self.assertEqual(first, second)
        with open(first, encoding='utf-8') as handle:
            rows = [json.loads(line) for line in handle]
        self.assertEqual(2, len(rows), 'the second sample rewrote the first')
        self.assertEqual([11.0, 12.0], [r['cpu_percent'] for r in rows])
        self.assertEqual(12.0, logger.get_session_logs()[1]['cpu_percent'])

    def test_54_a_line_that_is_not_json_is_skipped_rather_than_losing_the_session(self):
        logger = PerformanceLogger(log_dir=os.path.join(self.dir, 'logs'))
        path = logger.log_metrics(metrics())
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write('half a line written by a crash\n')
        logger.log_metrics(metrics(cpu_percent=44.0))
        rows = logger.get_session_logs()
        self.assertEqual(2, len(rows), 'one damaged line hid the whole day')
        self.assertEqual(44.0, rows[-1]['cpu_percent'])

    def test_55_a_session_name_cannot_walk_out_of_the_log_folder(self):
        logger = PerformanceLogger(log_dir=os.path.join(self.dir, 'logs'))
        path = logger.log_metrics(metrics(), session_name='..\\..\\escape:me')
        self.assertEqual(os.path.join(self.dir, 'logs'), os.path.dirname(path))
        for bad in (':', '\\', '/', '..'):
            self.assertNotIn(bad, os.path.basename(path),
                             f'{bad!r} survived in {os.path.basename(path)}')
        self.assertIn('escape', os.path.basename(path))
        self.assertTrue(os.path.exists(path),
                        'the name was sanitised but no file was written where it points')

    def test_56_no_file_means_no_rows_and_no_claim(self):
        self.assertEqual([], PerformanceLogger(
            log_dir=os.path.join(self.dir, 'empty')).get_session_logs())

    def test_57_profile_results_are_written_when_asked_for(self):
        profiler = FunctionProfiler()
        profiler.start_profile('render.one')
        profiler.end_profile('render.one')
        logger = PerformanceLogger(log_dir=os.path.join(self.dir, 'logs'))
        path = logger.log_profile_results(profiler.get_all_results(), 'a session')
        with open(path, encoding='utf-8') as handle:
            rows = [json.loads(line) for line in handle]
        self.assertEqual('render.one', rows[0]['function_name'])
        self.assertGreater(rows[0]['call_count'], 0)
        self.assertNotIn('/', os.path.basename(path))
        self.assertNotIn('\\', os.path.basename(path))
        self.assertNotIn(' ', os.path.basename(path),
                         'a session name with a space became a path with a space in it')


class Test58BenchmarkHistory(unittest.TestCase):
    """The only series a benchmark here can be compared against is this app's own."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='rf-perf-bench-')
        self.path = os.path.join(self.dir, 'benchmarks.json')
        self.history = BenchmarkHistory(path=self.path)

    def test_58_the_first_run_says_it_is_the_first(self):
        got = self.history.comparison('cpu', 12.0)
        self.assertEqual(0, got['runs_stored'])
        self.assertIsNone(got['best'])
        self.assertIn('first run of this work', got['reason'])
        self.assertFalse(os.path.exists(self.path))

    def test_59_a_recorded_run_is_compared_with_the_earlier_ones(self):
        for value in (10.0, 20.0):
            self.history.record({'kind': 'cpu', 'value': value,
                                 'unit': 'multiplies/s', 'at': '2026-11-06T00:00:00'})
        best = self.history.comparison('cpu', 25.0)
        self.assertEqual(2, best['previous_runs'])
        self.assertEqual(20.0, best['best'])
        self.assertEqual(10.0, best['worst'])
        self.assertTrue(best['this_is_best'])
        self.assertEqual(25.0, best['delta_vs_best_percent'])
        self.assertIn('faster than every earlier run', best['reason'])
        behind = self.history.comparison('cpu', 15.0)
        self.assertFalse(behind['this_is_best'])
        self.assertIn('25.0% short of the best run the app stored', behind['reason'])

    def test_60_a_run_of_another_kind_is_not_part_of_the_series(self):
        self.history.record({'kind': 'memory', 'value': 5.0, 'unit': 'MB/s', 'at': 'x'})
        self.assertEqual(0, self.history.comparison('cpu', 1.0)['previous_runs'])
        self.assertEqual(1, len(self.history.recent_runs('memory')['runs']))
        self.assertEqual([], self.history.recent_runs('cpu')['runs'])
        self.assertEqual(['memory'], self.history.recent_runs('cpu')['all_kinds'])

    def test_61_a_lower_is_better_kind_compares_the_other_way(self):
        for value in (30.0, 20.0):
            self.history.record({'kind': 'geometry', 'value': value, 'unit': 'ms', 'at': 'x'})
        got = self.history.comparison('geometry', 25.0, higher_is_better=False)
        self.assertEqual(20.0, got['best'])
        self.assertEqual(30.0, got['worst'])
        self.assertFalse(got['this_is_best'])

    def test_62_a_damaged_history_is_read_as_a_failure_and_left_on_disk(self):
        with open(self.path, 'w', encoding='utf-8') as handle:
            handle.write('{"runs": [')
        untouched = open(self.path, 'rb').read()
        got = self.history.comparison('cpu', 1.0)
        self.assertIn('could not be read', got['reason'])
        self.assertEqual(0, got['runs_stored'])
        self.assertIn('could not be read', self.history.recent_runs('cpu')['reason'])
        self.assertEqual(untouched, open(self.path, 'rb').read(),
                         'the app rewrote a file it could not read')

    def test_63_a_history_that_is_not_a_run_list_is_refused_not_replaced(self):
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump({'scores': [1, 2, 3]}, handle)
        self.assertIn('not a run list', self.history.recent_runs('cpu')['reason'])
        self.assertIn('not a run list', self.history.comparison('cpu', 1.0)['reason'])

    def test_64_a_write_leaves_no_temporary_file_and_keeps_the_recent_runs(self):
        for index in range(BenchmarkHistory.LIMIT + 5):
            self.history.record({'kind': 'cpu', 'value': float(index), 'unit': 'x', 'at': 'x'})
        self.assertFalse(os.path.exists(self.path + '.writing'))
        with open(self.path, encoding='utf-8') as handle:
            stored = json.load(handle)['runs']
        self.assertEqual(BenchmarkHistory.LIMIT, len(stored), 'the history grew forever')
        self.assertEqual(204.0, stored[-1]['value'], 'the runs kept were the oldest ones')

    def test_65_a_history_that_cannot_be_written_says_the_run_was_not_stored(self):
        blocked = os.path.join(self.dir, 'blocked')
        with open(blocked, 'w', encoding='utf-8') as handle:
            handle.write('a file where a folder is needed')
        got = BenchmarkHistory(path=os.path.join(blocked, 'benchmarks.json')).record(
            {'kind': 'cpu', 'value': 1.0, 'unit': 'x', 'at': 'x'})
        self.assertFalse(got['recorded'])
        self.assertIn('measured but not stored', got['reason'])

    def test_65b_a_folder_that_does_not_exist_yet_is_made_and_the_run_is_kept(self):
        """The folder is created inside the same promise, or a first run cannot be stored."""
        nested = os.path.join(self.dir, 'first', 'benchmarks.json')
        got = BenchmarkHistory(path=nested).record(
            {'kind': 'cpu', 'value': 12.0, 'unit': 'x', 'at': '2026-11-06T00:00:00'})
        self.assertTrue(got['recorded'], got['reason'])
        self.assertEqual(nested, got['path'])
        with open(nested, encoding='utf-8') as handle:
            self.assertEqual([12.0], [row['value'] for row in json.load(handle)['runs']])

    def test_65c_a_bare_filename_is_written_where_the_caller_is_standing(self):
        """`dirname` of a bare name is empty, and asking to make no folder is not a failure."""
        original = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, original)
        got = BenchmarkHistory(path='benchmarks.json').record(
            {'kind': 'cpu', 'value': 7.0, 'unit': 'x', 'at': '2026-11-06T00:00:00'})
        self.assertTrue(got['recorded'], got['reason'])
        self.assertTrue(os.path.isfile(os.path.join(self.dir, 'benchmarks.json')))


class Test66BenchmarkRunner(unittest.TestCase):
    """Four kinds of bounded work, each reported with the machine it ran on."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='rf-perf-run-')
        self.path = os.path.join(self.dir, 'benchmarks.json')
        self.engine = BenchmarkRunner(history=BenchmarkHistory(path=self.path))

    def test_66_a_fifth_kind_is_refused_by_name(self):
        got = self.engine.run('gpu')
        self.assertIsNone(got['ran'])
        self.assertIn('"gpu" is not work this engine performs', got['reason'])
        for kind in BenchmarkRunner.KINDS:
            self.assertIn(kind, got['reason'], 'the refusal did not offer what does run')
        self.assertEqual({}, got['machine'], 'a refusal claimed a machine it never used')

    def test_67_the_cpu_kind_multiplies_matrices_and_says_how_gigaflops_was_got(self):
        got = self.engine.run('cpu', duration=0.05, matrix=16)
        self.assertIn('16x16 float64 matrix multiplies for', got['ran'])
        self.assertGreaterEqual(got['work']['multiplies'], 1)
        self.assertGreater(got['result']['gigaflops'], 0.0)
        self.assertEqual('derived: 2 x size^3 x multiplies / elapsed',
                         got['result']['how_gigaflops_was_got'])
        self.assertEqual(16, got['work']['matrix_size'])
        self.assertIsInstance(got['comparison_value'], float)
        self.assertEqual('multiplies/s', got['comparison_unit'])
        self.assertIn('first run of this work', got['against']['reason'])

    def test_68_a_matrix_too_small_to_be_work_is_refused(self):
        for size in (1, 0, -4):
            got = self.engine.run('cpu', matrix=size)
            self.assertIsNone(got['ran'])
            self.assertIn('is not work', got['reason'])

    def test_69_a_stop_ends_the_work_and_reports_where_it_stopped(self):
        got = self.engine.run('cpu', duration=5.0, matrix=8, should_stop=lambda: True)
        self.assertIsNone(got['ran'])
        self.assertIn('stopped after 0 multiplies', got['reason'])

    def test_70_the_progress_callback_is_the_ones_and_zeros_the_worker_offers(self):
        seen = []
        self.engine.run('cpu', duration=0.06, matrix=8, progress_callback=seen.append)
        self.assertTrue(seen, 'the bar was given nothing to move on')
        self.assertLessEqual(max(seen), 100)
        self.assertGreaterEqual(seen[-1], 50, 'the work stopped reporting before it finished')

    def test_71_the_memory_kind_moves_a_real_array_and_reports_the_grown_process(self):
        got = self.engine.run('memory', duration=0.05, footprint_mb=8.0)
        self.assertIn('float64 array in', got['ran'])
        self.assertGreater(got['result']['mb_per_second'], 0.0)
        self.assertIn('rss_delta_mb', got['result'])
        self.assertIn('freed again before this figure is reported', got['result']['note'])
        self.assertEqual('MB/s', got['comparison_unit'])

    def test_72_an_array_of_nothing_moves_nothing(self):
        for size in (0, -1):
            got = self.engine.run('memory', footprint_mb=size)
            self.assertIsNone(got['ran'])
            self.assertIn('moves nothing', got['reason'])

    def test_73_the_storage_kind_writes_a_file_it_can_prove_is_gone_again(self):
        got = self.engine.run('storage', size_mb=2.0, directory=self.dir)
        self.assertIn('wrote and read back 2 MB on', got['ran'])
        self.assertTrue(got['result']['read_back_identical'])
        self.assertTrue(got['work']['verified_gone'])
        self.assertFalse(os.path.exists(got['work']['path']))
        self.assertEqual('probe file removed', got['result']['cleanup'])
        self.assertGreater(got['result']['write_mb_per_second'], 0.0)
        self.assertIn('fsync', got['result']['cache_note'])
        self.assertNotIn(os.path.basename(got['work']['path']), os.listdir(self.dir))

    def test_74_the_storage_figures_are_for_the_volume_the_app_writes_to(self):
        """The one shared helper picks the drive, here and in the health check."""
        from src.features.diagnostic_engine import SystemInfo
        from src.utils.file_utils import get_temp_directory
        folder = get_temp_directory()
        got = self.engine.run('storage', size_mb=1.0)
        self.assertEqual(os.path.abspath(folder).upper(),
                         os.path.dirname(got['work']['path']).upper(),
                         'the benchmark wrote somewhere the app does not write')
        volume = SystemInfo.working_volume(SystemInfo.get_storage_info(), folder)
        self.assertIsNotNone(volume, 'the helper could not name a volume for the app folder')
        self.assertEqual(os.path.splitdrive(got['work']['path'])[0].upper(),
                         os.path.splitdrive(volume['mountpoint'])[0].upper(),
                         'the drive this benchmark measured is not the drive the health '
                         'check names')

    def test_75_a_folder_that_is_not_there_refuses_and_names_the_volume_it_needed(self):
        got = self.engine.run('storage', size_mb=1.0,
                              directory=os.path.join(self.dir, 'no-such-folder'))
        self.assertIsNone(got['ran'])
        self.assertIn('is not a folder on this disk', got['reason'])
        self.assertEqual({}, got['result'], 'a refusal still printed a throughput figure')

    def test_75b_a_write_the_disk_refuses_is_the_failure_and_no_figure_is_claimed(self):
        probe = os.path.join(self.dir, f'rf_storage_probe_{os.getpid()}.bin')
        os.makedirs(probe)
        self.addCleanup(os.rmdir, probe)
        got = self.engine.run('storage', size_mb=1.0, directory=self.dir)
        self.assertIsNone(got['ran'])
        self.assertIn('writing', got['reason'])
        self.assertEqual({}, got['result'], 'a failed write was reported as a measured one')

    def test_76_a_file_of_nothing_holds_nothing(self):
        got = self.engine.run('storage', size_mb=0)
        self.assertIsNone(got['ran'])
        self.assertIn('holds nothing', got['reason'])

    def test_77_the_geometry_kind_names_the_device_that_answered(self):
        try:
            import open3d  # noqa: F401 - the question is only whether it is importable
            have_open3d = True
        except Exception:
            have_open3d = False
        got = self.engine.run('geometry', duration=0.05, points=2000)
        if have_open3d:
            self.assertIn('normal-estimation rounds over 2000 points', str(got['ran']))
            device = got['result']['device']
            self.assertTrue('CPU' in device or 'CUDA' in device,
                            f'the row does not say what ran: {device!r}')
            self.assertTrue(got['result']['open3d_version'])
        else:
            self.assertIsNone(got['ran'])
            self.assertIn('Open3D could not be imported', got['reason'])

    def test_78_too_few_points_is_not_something_to_time(self):
        got = self.engine.run('geometry', points=10)
        self.assertIsNone(got['ran'])
        self.assertIn('not enough to time', got['reason'])

    def test_79_the_gpu_verb_refuses_and_sends_the_user_to_the_work_that_exists(self):
        got = self.engine.run_gpu_benchmark()
        self.assertIsNone(got['ran'])
        self.assertIn('there is no GPU benchmark to run', got['reason'])
        self.assertIn('press Geometry instead', got['reason'])
        self.assertEqual('gpu', got['kind'])

    def test_80_run_all_reports_four_answers_and_keeps_its_refusals(self):
        summary = self.engine.run_all(duration=0.05)
        self.assertEqual(set(BenchmarkRunner.KINDS), set(summary['kinds']))
        self.assertEqual(4, len(summary['performed']) + len(summary['refused']))
        for line in summary['refused']:
            self.assertIn(': ', line)
        self.assertEqual('cpu', summary['kinds']['cpu']['kind'])
        self.assertIn('measured_at', summary)

    def test_81_recording_a_run_puts_it_in_the_history_the_next_run_reads(self):
        first = self.engine.run('cpu', duration=0.05, matrix=8, record=True)
        self.assertTrue(first['stored']['recorded'], first.get('stored'))
        self.assertIn('first run of this work', first['against']['reason'])
        second = self.engine.run('cpu', duration=0.05, matrix=8, record=True)
        self.assertEqual(1, second['against']['previous_runs'])
        self.assertTrue(second['stored']['recorded'])
        with open(self.path, encoding='utf-8') as handle:
            runs = json.load(handle)['runs']
        self.assertEqual(2, len(runs))
        self.assertEqual('cpu', runs[0]['kind'])

    def test_82_a_run_that_could_not_be_stored_says_so_in_its_own_row(self):
        blocked = os.path.join(self.dir, 'blocked')
        with open(blocked, 'w', encoding='utf-8') as handle:
            handle.write('not a folder')
        engine = BenchmarkRunner(history=BenchmarkHistory(
            path=os.path.join(blocked, 'benchmarks.json')))
        got = engine.run('cpu', duration=0.05, matrix=8, record=True)
        self.assertIsNotNone(got['ran'], 'the work still ran, and that part is true')
        self.assertFalse(got['stored']['recorded'])
        self.assertIn('not stored', BenchmarkRunner.row_cells(got)[3])

    def test_83_every_run_carries_the_machine_the_number_came_from(self):
        got = self.engine.run('cpu', duration=0.05, matrix=8)
        machine = got['machine']
        self.assertIn(' physical / ', machine['cores'])
        self.assertTrue(machine['clock'])
        self.assertTrue(machine['numpy'])
        self.assertIn('thread', machine['blas_threads'])

    def test_84_the_default_history_is_the_app_data_folder_the_tests_redirected(self):
        self.assertEqual(DATA_DIR, data_dir())
        self.assertEqual(os.path.join(DATA_DIR, 'benchmarks.json'), BenchmarkHistory().path)
        self.assertEqual(os.path.join(DATA_DIR, 'performance_logs'),
                         PerformanceLogger().log_dir)


class Test85TheWords(unittest.TestCase):
    """Cells and sentences come from the engine, so two panes cannot disagree."""

    def refusal(self):
        return BenchmarkRunner._refusal('gpu', 'nothing here times the adapter')

    def run_result(self):
        return {'kind': 'cpu', 'ran': '8x8 float64 matrix multiplies for 0.050 s',
                'reason': '', 'measured_at': '2026-11-06T00:00:00',
                'work': {'matrix_size': 8, 'multiplies': 12},
                'result': {'multiplies_per_second': 240.0, 'gigaflops': 0.001,
                           'how_gigaflops_was_got':
                               'derived: 2 x size^3 x multiplies / elapsed'},
                'comparison_value': 240.0, 'comparison_unit': 'multiplies/s',
                'against': {'reason': 'faster than every earlier run of this work',
                            'previous_runs': 2},
                'machine': {'cores': '10 physical / 12 logical', 'clock': '1300 MHz',
                            'numpy': '1.26.4', 'python': '3.11.8',
                            'blas_threads': 'openblas with 12 thread(s)'}}

    def test_85_a_refusal_is_a_row_that_says_it_did_not_run(self):
        cells = BenchmarkRunner.row_cells(self.refusal())
        self.assertEqual(4, len(cells))
        self.assertEqual('gpu', cells[0])
        self.assertEqual('did not run', cells[1])
        self.assertIn('nothing here times the adapter', cells[2])
        for claim in RATINGS:
            self.assertNotIn(claim, ' '.join(cells), f'the refusal printed {claim!r}')

    def test_86_a_run_shows_only_figures_the_work_produced(self):
        cells = BenchmarkRunner.row_cells(self.run_result())
        self.assertIn('8x8 float64 matrix multiplies', cells[1])
        self.assertIn('multiplies per second 240.0', cells[2])
        self.assertIn('gigaflops 0.001', cells[2])
        self.assertNotIn('derived', cells[2], 'a sentence about method was painted as a figure')
        self.assertIn('faster than every earlier run', cells[3])
        self.assertNotIn('run number', cells[3], 'a cell claimed a storage that did not happen')
        for claim in RATINGS:
            self.assertNotIn(claim, ' '.join(cells), f'the row graded the work as {claim!r}')

    def test_87_a_run_that_was_stored_says_which_number_it_is(self):
        result = dict(self.run_result(), stored={'recorded': True, 'path': 'x'})
        self.assertIn('stored as run number 3', BenchmarkRunner.row_cells(result)[3])
        failed = BenchmarkRunner.row_cells(
            dict(self.run_result(), stored={'recorded': False, 'reason': 'the disk was full'}))
        self.assertIn('the disk was full', failed[3],
                      'a run that was measured but not kept read as a kept one')

    def test_88_work_with_no_figure_in_it_does_not_become_a_zero(self):
        result = dict(self.run_result(), result={'how_gigaflops_was_got': 'derived'})
        self.assertEqual('no figure came out of this work',
                         BenchmarkRunner.row_cells(result)[2])

    def test_89_the_prose_and_the_cells_come_from_the_same_reading(self):
        described = BenchmarkRunner.describe(self.run_result())
        self.assertIn('8x8 float64 matrix multiplies', described)
        self.assertIn('multiplies per second: 240.0', described)
        self.assertIn("against this app's own earlier runs", described)
        self.assertIn('openblas with 12 thread(s)', described)
        self.assertEqual('gpu: did not run - nothing here times the adapter',
                         BenchmarkRunner.describe(self.refusal()))

    def test_90_there_is_exactly_one_engine_in_the_process(self):
        self.assertIs(benchmark_engine(), benchmark_engine())
        self.assertIsInstance(benchmark_engine(), BenchmarkRunner)
        self.assertIs(benchmark_engine(), PerformanceAnalyzer().benchmark,
                      "the pane's analyzer keeps its own engine, so two tabs time one machine twice")
        self.assertIs(benchmark_engine().history, PerformanceAnalyzer().benchmark.history,
                      'a second history would be a second idea of what this app has measured')

    def test_91_the_second_ratings_engine_is_gone_from_the_app(self):
        for path in (BACKEND_FILE, DIAG_FILE, PANE):
            text = code_of(path)
            self.assertNotIn('class PerformanceBenchmark', text)
            self.assertNotIn('math.sqrt', text, 'the square-root benchmark is still reachable')
            for claim in RATINGS:
                self.assertNotIn(claim, text, f'{os.path.basename(path)} still ranks a machine')
        self.assertIn('benchmark_engine()', source(DIAG_FILE))
        self.assertIn('engine.run(', source(PANE))
        self.assertIn('BenchmarkRunner.describe(', source(DIAG_FILE),
                      'the Diagnostics pane is wording a benchmark sentence itself')

    def test_91b_the_alias_verb_that_no_pane_could_call_is_gone(self):
        """`run(kind)` is the only door to the work; an alias beside it is a second name.

        The runner used to hold `run_cpu_benchmark`, whose name matched the pane button's
        own method, which is how it looked used. Every call site in the app resolves to
        `engine.run(` or `engine.run_all(`, and the CPU button reaches the same work
        through `start_benchmark('cpu')`, so the alias only offered a second way to time
        one machine - and the second way had no progress argument, no record flag and no
        test.
        """
        self.assertNotIn('def run_cpu_benchmark', code_of(ENGINE_FILE),
                         'a second name for the cpu work is back, and nothing calls it')
        self.assertNotIn('benchmark.run_cpu', source(PANE),
                         'the pane reached around the engine again')
        for call in ('engine.run(', 'engine.run_all('):
            self.assertIn(call, source(PANE), f'{call} is how the pane times work')
        self.assertIn('def run_gpu_benchmark', code_of(ENGINE_FILE),
                      'the gpu verb answers the label the Geometry button used to carry; '
                      'test_79 is what keeps it honest')


class Test92PerformanceAnalyzer(unittest.TestCase):
    """The object the pane asks, which must never invent a field it was not given."""

    def setUp(self):
        self.analyzer = PerformanceAnalyzer()

    def tearDown(self):
        self.analyzer.stop_monitoring()

    def test_92_the_analysis_is_serialisable_and_carries_its_own_refusals(self):
        row = self.analyzer.get_current_analysis()
        for key in ('metrics', 'findings', 'not_measured', 'score', 'suggestions',
                    'frames', 'average_metrics', 'peak_metrics'):
            self.assertIn(key, row)
        self.assertIsNone(row['metrics']['fps'],
                          'a monitor that never started cannot know a frame rate')
        self.assertTrue(row['not_measured'], 'an incomplete sample looked complete')
        json.dumps(row)

    def test_93_no_samples_is_no_trend(self):
        got = self.analyzer.get_historical_analysis()
        self.assertEqual(0, got['data_points'])
        self.assertIn('no sample has been kept yet', got['reason'])

    def test_94_a_trend_counts_the_samples_that_hold_the_number(self):
        self.analyzer.monitor.metrics_history.extend([
            metrics(cpu_percent=10.0, gpu_load_percent=None,
                    not_read={'gpu_load_percent': 'nothing reads the adapter'}),
            metrics(cpu_percent=30.0, gpu_load_percent=None,
                    not_read={'gpu_load_percent': 'nothing reads the adapter'})])
        trends = self.analyzer.get_historical_analysis()['trends']
        self.assertEqual(20.0, trends['cpu_percent']['average'])
        self.assertEqual(30.0, trends['cpu_percent']['peak'])
        self.assertEqual(2, trends['cpu_percent']['samples'])
        self.assertIsNone(trends['gpu_load_percent']['average'])
        self.assertEqual(0, trends['gpu_load_percent']['samples'])
        self.assertIn('nothing reads the adapter', trends['gpu_load_percent']['reason'])

    def test_95_a_report_is_a_file_with_the_refusals_inside_it(self):
        path = os.path.join(tempfile.mkdtemp(prefix='rf-perf-report-'), 'report.json')
        self.assertEqual(path, self.analyzer.export_performance_report(path))
        with open(path, encoding='utf-8') as handle:
            loaded = json.load(handle)
        self.assertIn('analysis', loaded)
        self.assertIn('historical', loaded)
        self.assertIn('profiling', loaded)
        self.assertTrue(loaded['analysis']['not_measured'])

    def test_96_profiling_and_clearing_reach_the_objects_that_hold_them(self):
        self.analyzer.start_profiling('render.one')
        self.assertGreater(self.analyzer.end_profiling('render.one'), 0.0)
        self.assertEqual(['render.one'],
                         [r.function_name for r in self.analyzer.get_profiling_results()])
        self.analyzer.clear_all_data()
        self.assertEqual([], self.analyzer.get_profiling_results())
        self.assertEqual(0, len(self.analyzer.monitor.metrics_history))


class Test97PerformancePane(unittest.TestCase):
    """The pane paints the engine's words, on a worker, and adds no claim of its own."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.QtCore import QThreadPool
        from src.ui.performance_tab import PerformanceTab
        self.pool = QThreadPool.globalInstance()
        self.pool.waitForDone(15000)
        self.tab = PerformanceTab()
        self.tab.performance_analyzer.stop_monitoring()
        self.history_path = os.path.join(tempfile.mkdtemp(prefix='rf-perf-pane-'),
                                         'benchmarks.json')
        self.tab.performance_analyzer.benchmark.history = BenchmarkHistory(
            path=self.history_path)

    def tearDown(self):
        """Hand the pane back the way the other GUI suites do, timers first.

        A timer left running on a widget whose C++ object goes at interpreter exit is
        how a green suite ends up exiting 127 instead of 0, and the audit reads that as
        a suite that never reported.
        """
        from PyQt6.QtCore import QThreadPool
        self.tab.performance_analyzer.stop_monitoring()
        self.tab.update_timer.stop()
        self.tab.system_monitor.timer.stop()
        QThreadPool.globalInstance().waitForDone(15000)
        self.tab.close()
        self.app.processEvents()

    def pump(self, seconds=30.0, until=None):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.02)
            if until and until():
                return True
        return until() if until else False

    def fake_engine(self, result=None, raises=None):
        """Replace only the work, so the pane still reads the real history object."""
        engine = self.tab.performance_analyzer.benchmark
        engine.run_calls = []
        engine.gave_a_progress_callback = []

        def run(kind, duration=2.0, record=False, should_stop=None,
                progress_callback=None, **work):
            engine.run_calls.append(kind)
            engine.gave_a_progress_callback.append(callable(progress_callback))
            if progress_callback:
                progress_callback(37)
            if raises:
                raise raises
            return dict(result, kind=kind)

        def run_all(duration=2.0, record=False, should_stop=None, progress_callback=None):
            engine.run_calls.append('all')
            engine.gave_a_progress_callback.append(callable(progress_callback))
            # The real run_all forwards the callback into each kind; silence here would
            # let a bar wired to nothing look like a bar wired to the engine.
            kinds = {}
            for kind in BenchmarkRunner.KINDS:
                kinds[kind] = BenchmarkRunner._refusal(kind, 'fake engine')
                if progress_callback:
                    progress_callback(37)
            return {'kinds': kinds, 'performed': [],
                    'refused': [f'{kind}: fake engine' for kind in BenchmarkRunner.KINDS],
                    'measured_at': '2026-11-06T00:00:00'}

        engine.run = run
        engine.run_all = run_all
        return engine

    def spy_progress_bar(self):
        """Record every value the pane delivers to the bar, and the range it landed in.

        The bar is read at the end of a run, by which time `finish_benchmark` has stamped
        it full - so what the engine reported mid-run, and the range that report arrived
        in, can only be proved by watching the calls as they come in. Qt throws away the
        number while minimum equals maximum, and the bar keeps looking exactly as it did.
        """
        class Painted(list):
            """The values in order, and beside each one the maximum the bar had then."""

        painted = Painted()
        painted.ranges = []
        bar = self.tab.benchmark_progress
        real = bar.setValue

        def record(value):
            painted.append(value)
            painted.ranges.append(bar.maximum())
            real(value)

        bar.setValue = record
        self.addCleanup(setattr, bar, 'setValue', real)
        return painted

    def cells(self, row):
        return [self.tab.results_table.item(row, column).text()
                for column in range(self.tab.results_table.columnCount())]

    def test_97_no_button_in_the_pane_promises_a_gpu_it_cannot_time(self):
        from PyQt6.QtWidgets import QPushButton
        text = source(PANE)
        self.assertNotIn('QPushButton("GPU Benchmark")', text)
        self.assertIn('Geometry Benchmark', text)
        labels = [button.text() for button in self.tab.findChildren(QPushButton)]
        self.assertIn('Geometry Benchmark', labels)
        for label in labels:
            self.assertNotRegex(label, r'GPU\s*Benchmark', f'{label!r} still claims the adapter')
        self.assertFalse(hasattr(self.tab, 'benchmark_gpu_btn'),
                         'the old button is still on screen with nothing behind it')
        self.assertIn('benchmark_geometry_btn.clicked.connect', source(PANE))

    def test_98_the_result_columns_are_measurements(self):
        headers = [self.tab.results_table.horizontalHeaderItem(column).text()
                   for column in range(4)]
        self.assertEqual(['Kind', 'What ran', 'Measured',
                          "Against this app's own earlier runs"], headers)
        for claim in RATINGS:
            self.assertNotIn(claim, ' '.join(headers))

    def test_99_a_finished_benchmark_paints_the_engines_cells(self):
        engine = self.fake_engine({'ran': '8x8 float64 matrix multiplies for 0.050 s',
                                   'reason': '', 'work': {}, 'comparison_value': 240.0,
                                   'comparison_unit': 'multiplies/s', 'result': {
                                       'multiplies_per_second': 240.0},
                                   'against': {}, 'machine': {}})
        self.tab.run_cpu_benchmark()
        self.assertTrue(self.pump(
            until=lambda: (self.tab.results_table.rowCount() == 1
                           and self.tab.benchmark_cpu_btn.isEnabled())))
        self.assertEqual(['cpu', '8x8 float64 matrix multiplies for 0.050 s',
                          'multiplies per second 240.0',
                          'this run was not compared with anything'], self.cells(0))
        self.assertIn('cpu benchmark finished', self.tab.benchmark_status.text())
        self.assertEqual(['cpu'], engine.run_calls)

    def test_100_a_refusal_is_painted_as_a_refusal(self):
        self.fake_engine({'ran': None, 'reason': 'the fake engine declines', 'result': {},
                          'against': {}, 'machine': {}, 'work': {}})
        self.tab.run_geometry_benchmark()
        self.assertTrue(self.pump(until=lambda: self.tab.results_table.rowCount() == 1))
        self.assertEqual('did not run', self.cells(0)[1])
        self.assertIn('the fake engine declines', self.cells(0)[2])
        self.assertIn('did not run', self.tab.benchmark_status.text())
        self.assertEqual('nothing to compare - this work did not run',
                         self.tab.comparison_chart.text())

    def test_101_the_work_runs_off_the_thread_that_paints(self):
        """`Worker` supplies `progress_callback`; the pane's old workers could not take it."""
        self.fake_engine({'ran': 'x', 'reason': '', 'result': {}, 'against': {},
                          'machine': {}, 'work': {}})
        painted = self.spy_progress_bar()
        self.tab.run_cpu_benchmark()
        self.assertTrue(self.pump(
            until=lambda: (self.tab.results_table.rowCount() == 1
                           and self.tab.benchmark_cpu_btn.isEnabled())))
        self.assertEqual([True],
                         self.tab.performance_analyzer.benchmark.gave_a_progress_callback,
                         'the engine was given no way to report progress')
        self.assertIn(37, painted, 'what the engine reported never reached the bar')
        self.assertEqual([100] * len(painted), painted.ranges,
                         'a percentage was reported into a bar whose maximum was 0, and Qt '
                         'throws those away while `finish_benchmark` fixes the range later')
        self.assertEqual(0, painted[0], 'the bar was not emptied before the work started')
        self.assertEqual(100, painted[-1], 'the run did not end with a full bar')
        self.assertEqual((0, 100), (self.tab.benchmark_progress.minimum(),
                                    self.tab.benchmark_progress.maximum()),
                         'a bar whose range is 0 to 0 throws every figure away')
        self.assertEqual(1, len(self.tab._workers), 'the worker could have been collected')
        self.assertTrue(all(button.isEnabled() for button in (
            self.tab.benchmark_cpu_btn, self.tab.benchmark_geometry_btn,
            self.tab.benchmark_memory_btn, self.tab.benchmark_storage_btn,
            self.tab.benchmark_full_btn)), 'the buttons stayed locked after the run')

    def test_102_a_benchmark_that_raises_is_said_out_loud(self):
        self.fake_engine({'ran': None}, raises=RuntimeError('the fake engine died'))
        self.tab.run_cpu_benchmark()
        self.assertTrue(self.pump(
            until=lambda: ('benchmark failed' in self.tab.benchmark_status.text()
                           and self.tab.benchmark_cpu_btn.isEnabled())))
        self.assertIn('the fake engine died', self.tab.benchmark_status.text())
        self.assertEqual(0, self.tab.results_table.rowCount())

    def test_103_the_series_shown_is_the_apps_own_runs_and_says_so(self):
        BenchmarkHistory(path=self.history_path).record(
            {'kind': 'cpu', 'value': 111.0, 'unit': 'multiplies/s',
             'at': '2026-11-05T22:00:00'})
        self.fake_engine({'ran': 'cpu work', 'reason': '', 'result': {},
                          'comparison_unit': 'multiplies/s', 'against': {},
                          'machine': {}, 'work': {}})
        self.tab.run_cpu_benchmark()
        self.assertTrue(self.pump(
            until=lambda: 'own runs' in self.tab.comparison_chart.text()))
        text = self.tab.comparison_chart.text()
        self.assertIn('2026-11-05T22:00:00 - 111.0 multiplies/s', text)
        self.assertIn('No other machine is in this list', text)
        self.assertEqual('cpu work', self.tab.benchmark_results[0]['ran'])

    def test_104_a_history_that_cannot_be_read_says_that(self):
        with open(self.history_path, 'w', encoding='utf-8') as handle:
            handle.write('{ not json')
        self.fake_engine({'ran': 'cpu work', 'reason': '', 'result': {}, 'against': {},
                          'machine': {}, 'work': {}})
        self.tab.run_cpu_benchmark()
        self.assertTrue(self.pump(
            until=lambda: 'could not be read' in self.tab.comparison_chart.text()))

    def test_105_the_full_benchmark_keeps_every_refusal_visible(self):
        self.fake_engine()
        painted = self.spy_progress_bar()
        self.tab.run_full_benchmark()
        self.assertTrue(self.pump(
            until=lambda: (self.tab.results_table.rowCount() == 4
                           and self.tab.benchmark_full_btn.isEnabled())))
        self.assertEqual(list(BenchmarkRunner.KINDS),
                         [self.cells(row)[0] for row in range(4)])
        for row in range(4):
            self.assertEqual('did not run', self.cells(row)[1])
        status = self.tab.benchmark_status.text()
        self.assertIn('measured nothing', status)
        self.assertIn('refused 4', status)
        self.assertEqual([True],
                         self.tab.performance_analyzer.benchmark.gave_a_progress_callback,
                         'the four kinds were started with no way to report progress')
        self.assertEqual(0, painted[0], 'the bar was not emptied before the four kinds')
        self.assertIn(37, painted, 'what the run reported never reached the bar')
        self.assertEqual([100] * len(painted), painted.ranges,
                         'the four kinds reported progress into a bar that discarded it')

    def test_106_the_pane_holds_no_number_and_no_verdict_of_its_own(self):
        """The engine owns the figures and the words; the pane only paints them."""
        tree = ast.parse(source(PANE))
        wanted = ('start_benchmark', 'show_benchmark_result', 'show_full_benchmark',
                  'paint_comparison', 'finish_benchmark', 'on_benchmark_failed')
        bodies = {node.name: node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name in wanted}
        self.assertEqual(sorted(wanted), sorted(bodies), 'a step of the run is missing')
        painted = ast.unparse(bodies['show_benchmark_result'])
        self.assertIn('row_cells(', painted, 'the pane is wording a benchmark cell itself')
        # The two methods left out hold a progress bar's ends, which are a widget bound
        # and not a measurement: 0 and 100 belong to QProgressBar, not to the work.
        for name in ('show_benchmark_result', 'show_full_benchmark', 'paint_comparison',
                     'on_benchmark_failed'):
            for node in ast.walk(bodies[name]):
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                    self.fail(f'{name} holds the literal {node.value!r} at line '
                              f'{node.lineno}; a figure belongs to the engine')
        for name, body in bodies.items():
            for claim in RATINGS:
                self.assertNotIn(claim, ast.unparse(body),
                                 f'{name} grades this machine as {claim!r}')

    def test_106b_the_detect_button_works_on_a_thread_that_can_take_the_callback(self):
        """The house `Worker` always passes `progress_callback`; this button's function takes it.

        Two of the pane's four worker functions had no test reaching them at all, and the
        sweep found it by mutating the wrong one. Pressing Detect is the only way the
        adapter row is ever filled, so a signature it cannot honour has to show up here as
        a failed test rather than as a panel that says nothing.
        """
        self.tab.detect_gpu_btn.setEnabled(True)
        self.tab.gpu_info_display.setPlainText('')
        self.tab.detect_gpu_hardware()
        self.assertFalse(self.tab.detect_gpu_btn.isEnabled(),
                         'the button was left clickable during its own run')
        self.assertTrue(self.pump(
            until=lambda: (self.tab.gpu_info_display.toPlainText() != ''
                           and self.tab.detect_gpu_btn.isEnabled())))
        text = self.tab.gpu_info_display.toPlainText()
        self.assertNotIn('Machine reader failed', text,
                         f'the adapter worker died instead of answering: {text}')
        self.assertNotIn('Asking Windows', text, 'the placeholder never left the panel')
        self.assertTrue(text.strip(), 'an empty panel is not an adapter report')

    def test_106c_the_storage_rows_are_filled_on_a_thread_that_can_take_the_callback(self):
        """The same signature rule on the volume reader, whose answer the Storage rows show."""
        self.tab.storage_total_label.setText('-')
        self.tab.refresh_storage_info()
        self.assertTrue(self.pump(
            until=lambda: isinstance(self.tab.storage_info, dict)
                          and self.tab.storage_total_label.text() != '-'))
        shown = ' | '.join(label.text() for label in (
            self.tab.storage_total_label, self.tab.storage_used_label,
            self.tab.storage_free_label, self.tab.storage_type_label))
        self.assertNotIn('reader failed', shown,
                         f'the volume worker died instead of answering: {shown}')
        self.assertIn('GB', self.tab.storage_total_label.text())


class Test107MetricsShape(unittest.TestCase):
    """The row a sample returns, so a pane cannot quietly invent a column."""

    def test_107_every_field_that_can_be_measured_can_also_be_refused(self):
        measured = metrics()
        self.assertEqual([], measured.unmeasured())
        row = measured.to_dict()
        self.assertEqual(17, len(row), 'a field was added to one place only')
        for name in ('cpu_percent', 'memory_percent', 'gpu_load_percent', 'fps',
                     'frame_time_ms', 'not_read'):
            self.assertIn(name, row)
        self.assertEqual({}, PerformanceMetrics(timestamp=time.time()).not_read)
        refused = unmeasured('fps', 'cpu_percent', 'gpu_load_percent', 'memory_percent')
        self.assertEqual(['cpu_percent: the reader said no', 'fps: the reader said no',
                          'gpu_load_percent: the reader said no',
                          'memory_percent: the reader said no'], refused.unmeasured())

    def test_108_a_profile_result_carries_its_own_count(self):
        result = ProfileResult('render.one', 3, 0.9, 0.3, 0.1, 0.5, time.time())
        self.assertEqual('render.one', result.to_dict()['function_name'])
        self.assertAlmostEqual(result.total_time / result.call_count, result.average_time)

    def test_109_the_limits_are_this_apps_policy_and_say_so_in_words(self):
        self.assertEqual({'cpu_percent', 'memory_percent', 'gpu_load_percent', 'fps',
                          'frame_time_ms'}, set(LIMITS))
        for name, value in LIMITS.items():
            self.assertIsInstance(value, float, f'{name} is not a stated policy figure')
        detector = BottleneckDetector()
        finding = detector.analyze(metrics(memory_percent=LIMITS['memory_percent'] + 20))[0]
        self.assertIn('this app checks itself against', finding['because'])
        self.assertIn('24% past the', finding['because'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
