"""
RenderFox performance backend: what this app can say about this machine while it runs.

Every figure below is one of four things, and each one carries the word saying which:
a reading taken from the operating system, arithmetic over readings the app made
itself, a limit this app wrote down for itself, or nothing - a field left as None
because no reader answered it, with the reason beside it.

What this file used to do instead was hand back a default. `fps` was one monitoring
sample divided by the next - the timer fires at 1000 ms whatever the screen is doing -
so every reading came out near 1.0 fps and 1000 ms per frame, and the `0.016` written
under it as the empty-history case could not be reached, because the sample was
appended on the line above; none of it even reached a screen, because no pane read
`fps` or `frame_time_ms` and the one function that turned them into a verdict had no
caller. `gpu_percent` was 0.0 both
when the adapter was idle and when no reader answered it, which on this machine is
every second; a benchmark score of `int(ops_per_second * 1000)` was painted as
"Top 1%" against a leaderboard that exists nowhere. Those are not cautious numbers.
They are numbers about a machine that was never asked.
"""

import gc
import json
import os
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import psutil

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..utils.app_paths import data_dir as _app_data_dir
from ..utils.frame_clock import FrameClock, shared_clock
from . import performance_controls
from .diagnostic_engine import SystemInfo

__all__ = ['PerformanceMetrics', 'ProfileResult', 'PerformanceMonitor',
           'FunctionProfiler', 'BottleneckDetector', 'OptimizationSuggester',
           'PerformanceLogger', 'BenchmarkHistory', 'BenchmarkRunner',
           'PerformanceAnalyzer', 'benchmark_engine', 'data_dir', 'BUDGETS']

# The limits this app checks itself against. They are a policy, not a measurement, so
# they live in one place and every finding quotes the number it used.
LIMITS = {
    'cpu_percent': 80.0,          # busy share of all logical cores, over the sample window
    'memory_percent': 85.0,       # share of physical memory in use on the machine
    'gpu_load_percent': 90.0,     # adapter load, only when a reader answers
    'fps': 30.0,                  # frames the app's own 3D view finished drawing
    'frame_time_ms': 33.0,        # the same frames as a duration
}

# The two budgets the Performance panes set for themselves. Unlike LIMITS these are not
# this app's policy: they are numbers a user typed, so both start as None and a finding
# against one only exists once the box that owns it has been filled.
BUDGETS = {'process_memory_budget_mb': None, 'adapter_memory_alert_mb': None}

# How much each limit is allowed to reduce the app's own pressure score. Policy, stated
# plainly, and a score never spends a field that was not read.
SCORE_WEIGHTS = {'cpu_percent': 0.5, 'memory_percent': 0.4,
                 'gpu_load_percent': 0.6, 'fps': 0.3}


def data_dir() -> str:
    """The app's own data folder, where a benchmark history has to outlive a run.

    `RENDERFOX_DATA_DIR` points it elsewhere, which is how the suites keep their test
    runs out of the history of the machine they run on. `src/utils/app_paths.py` answers
    that for the whole app now, so this says the same thing rather than a second time.
    """
    return _app_data_dir()


def _stamp() -> str:
    return datetime.now().isoformat(timespec='seconds')


@dataclass
class PerformanceMetrics:
    """One sample of this machine, with a place to say what could not be read.

    A None here is an answer, not a gap: `not_read` holds the reason beside the name of
    the field that stayed None, and anything that paints these rows shows that reason
    instead of the zero a default would have given.
    """
    timestamp: float
    window_seconds: Optional[float] = None
    cpu_percent: Optional[float] = None
    process_cpu_percent: Optional[float] = None
    cpu_frequency_mhz: Optional[float] = None
    memory_percent: Optional[float] = None
    memory_used_mb: Optional[float] = None
    memory_available_mb: Optional[float] = None
    process_rss_mb: Optional[float] = None
    gpu_load_percent: Optional[float] = None
    gpu_memory_percent: Optional[float] = None
    gpu_memory_used_mb: Optional[float] = None
    gpu_temperature_c: Optional[float] = None
    gpu_reader: Optional[str] = None
    fps: Optional[float] = None
    frame_time_ms: Optional[float] = None
    slowest_frame_ms: Optional[float] = None
    frames: int = 0
    not_read: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def unmeasured(self) -> List[str]:
        """The names of the fields no reader answered for, each with its reason."""
        return [f'{name}: {why}' for name, why in sorted(self.not_read.items())]


@dataclass
class ProfileResult:
    """Timings the app recorded around one of its own operations."""
    function_name: str
    call_count: int
    total_time: float
    average_time: float
    min_time: float
    max_time: float
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PerformanceMonitor(QObject):
    """Reads the machine once a sample and keeps the samples.

    Nothing here blocks. `psutil.cpu_percent(interval=0.1)` used to sit on the interface
    thread for a tenth of a second every second, which is how a monitoring pane ends up
    making the machine slower than the thing it is watching; the window is now the gap
    between two samples, and that gap is reported with the figure it produced.
    """

    metrics_updated = pyqtSignal(dict)

    def __init__(self, history_size: int = 300, clock: Optional[FrameClock] = None,
                 gpu_reader: Optional[Callable[[], Dict[str, Any]]] = None,
                 gpu_cache_seconds: float = 2.0) -> None:
        super().__init__()
        self.history_size = history_size
        self.metrics_history: deque = deque(maxlen=history_size)
        self.is_monitoring = False
        self.update_interval = 1000
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_metrics)

        self.clock = clock if clock is not None else shared_clock()
        self.gpu_reader = gpu_reader
        self.gpu_cache_seconds = float(gpu_cache_seconds)

        self._process = psutil.Process(os.getpid())
        self._last_sample_at: Optional[float] = None
        self._gpu_cache: Optional[Dict[str, Any]] = None
        self._gpu_at = 0.0
        self._primed = False

    def start_monitoring(self, interval_ms: int = 1000) -> None:
        """Begin sampling. The first two calls of each percent reader are the prime."""
        self.update_interval = int(interval_ms)
        psutil.cpu_percent(interval=None)
        self._process.cpu_percent(interval=None)
        self._primed = True
        self._last_sample_at = time.monotonic()
        self.is_monitoring = True
        self.timer.start(self.update_interval)

    def stop_monitoring(self) -> None:
        self.is_monitoring = False
        self.timer.stop()

    def _read_gpu(self) -> Dict[str, Any]:
        """The adapter figures, at most once per `gpu_cache_seconds`.

        GPUtil starts a helper program to answer, so a per-second sample would start one
        per second. A reader that raises is kept as a reason, not as a zero.
        """
        if self.gpu_reader is None:
            return {'reason': 'the monitor was not given a GPU reader; the Detect button '
                              'asks about the adapter, this sample does not'}
        now = time.monotonic()
        if self._gpu_cache is not None and now - self._gpu_at < self.gpu_cache_seconds:
            return self._gpu_cache
        try:
            sample = dict(self.gpu_reader() or {})
        except Exception as failed:
            sample = {'reason': f'the GPU reader raised {type(failed).__name__}: {failed}'}
        self._gpu_cache = sample
        self._gpu_at = now
        return sample

    def set_gpu_reader(self, reader: Optional[Callable[[], Dict[str, Any]]]) -> Dict[str, Any]:
        """Swap the adapter reader and drop the cached answer with the old one.

        The cache belongs to the reader that filled it: leaving it in place would show the
        previous adapter's figures beside a new one for up to `gpu_cache_seconds`.
        """
        self.gpu_reader = reader
        self._gpu_cache = None
        self._gpu_at = 0.0
        return {'reading': reader is not None}

    def sample(self) -> PerformanceMetrics:
        """One look at the machine, as it was at this instant."""
        not_read: Dict[str, str] = {}
        now = time.monotonic()
        window = (now - self._last_sample_at) if self._last_sample_at is not None else None
        self._last_sample_at = now

        if self._primed and window is not None and window > 0.0:
            cpu_percent = round(psutil.cpu_percent(interval=None), 1)
            process_cpu = round(self._process.cpu_percent(interval=None), 1)
        else:
            cpu_percent = process_cpu = None
            not_read['cpu_percent'] = ('no window has been measured yet; start_monitoring '
                                       'primes the reader and the figure covers the gap '
                                       'between two samples')

        try:
            memory = psutil.virtual_memory()
            memory_percent = round(memory.percent, 1)
            memory_used_mb = memory.used / (1024 * 1024)
            memory_available_mb = memory.available / (1024 * 1024)
        except Exception as failed:
            memory_percent = memory_used_mb = memory_available_mb = None
            not_read['memory_percent'] = f'psutil raised {type(failed).__name__}: {failed}'

        try:
            process_rss_mb = self._process.memory_info().rss / (1024 * 1024)
        except Exception as failed:
            process_rss_mb = None
            not_read['process_rss_mb'] = f'psutil raised {type(failed).__name__}: {failed}'

        cpu_frequency_mhz = None
        try:
            frequency = psutil.cpu_freq()
        except Exception as failed:
            frequency = None
            not_read['cpu_frequency_mhz'] = f'psutil raised {type(failed).__name__}: {failed}'
        if frequency is not None:
            if frequency.current:
                cpu_frequency_mhz = round(frequency.current, 1)
            else:
                not_read['cpu_frequency_mhz'] = (
                    'psutil answered the sensor with current=0.0, which is what it returns '
                    'when the firmware gives this machine no live clock reading')
        elif 'cpu_frequency_mhz' not in not_read:
            not_read['cpu_frequency_mhz'] = 'psutil.cpu_freq() answered nothing at all'

        gpu = self._read_gpu()
        gpu_load = gpu.get('load_percent')
        if gpu_load is None:
            not_read['gpu_load_percent'] = gpu.get('reason') or 'the GPU reader answered nothing'
        gpu_memory = gpu.get('memory_percent')
        if gpu_memory is None:
            not_read['gpu_memory_percent'] = gpu.get('reason') or 'the GPU reader answered nothing'
        gpu_memory_used = gpu.get('memory_used_mb')
        if gpu_memory_used is None:
            not_read['gpu_memory_used_mb'] = (
                gpu.get('reason') or 'the GPU reader answered no memory figure')

        frames = self.clock.stats(window_seconds=window or (self.update_interval / 1000.0))
        if frames['fps'] is None:
            not_read['fps'] = frames['reason']

        return PerformanceMetrics(
            timestamp=time.time(),
            window_seconds=round(window, 3) if window is not None else None,
            cpu_percent=cpu_percent,
            process_cpu_percent=process_cpu,
            cpu_frequency_mhz=cpu_frequency_mhz,
            memory_percent=memory_percent,
            memory_used_mb=round(memory_used_mb, 1) if memory_used_mb is not None else None,
            memory_available_mb=(round(memory_available_mb, 1)
                                 if memory_available_mb is not None else None),
            process_rss_mb=round(process_rss_mb, 1) if process_rss_mb is not None else None,
            gpu_load_percent=gpu_load,
            gpu_memory_percent=gpu_memory,
            gpu_memory_used_mb=gpu_memory_used,
            gpu_temperature_c=gpu.get('temperature_c'),
            gpu_reader=gpu.get('reader'),
            fps=frames['fps'],
            frame_time_ms=frames['frame_time_ms'],
            slowest_frame_ms=frames['slowest_frame_ms'],
            frames=frames['frames'],
            not_read=not_read,
        )

    def _update_metrics(self) -> None:
        metrics = self.get_current_metrics()
        self.metrics_history.append(metrics)
        self.metrics_updated.emit(metrics.to_dict())

    def get_current_metrics(self) -> PerformanceMetrics:
        return self.sample()

    def get_metrics_history(self, last_n: Optional[int] = None) -> List[PerformanceMetrics]:
        items = list(self.metrics_history)
        return items[-last_n:] if last_n else items

    def get_average_metrics(self, last_n: int = 60) -> Dict[str, Any]:
        """Means over the samples that hold a number, and how many samples that was.

        The old version answered 0.0 for a field nothing measured, so an average of five
        CPU readings and one GPU reading looked like an idle GPU. Each figure now comes
        with the count of samples behind it, and None when that count is zero.
        """
        fields = ('cpu_percent', 'memory_percent', 'gpu_load_percent', 'fps',
                  'frame_time_ms', 'process_rss_mb', 'gpu_memory_used_mb')
        recent = self.get_metrics_history(last_n)
        out: Dict[str, Any] = {'samples': len(recent)}
        for name in fields:
            values = [getattr(m, name) for m in recent if getattr(m, name) is not None]
            out[name] = round(sum(values) / len(values), 2) if values else None
            out[f'{name}_of'] = len(values)
        return out

    def get_peak_metrics(self) -> Dict[str, Any]:
        """Highest value seen per field, again with the count of samples behind it."""
        fields = ('cpu_percent', 'memory_percent', 'gpu_load_percent',
                  'memory_used_mb', 'process_rss_mb', 'gpu_memory_used_mb')
        out: Dict[str, Any] = {'samples': len(self.metrics_history)}
        for name in fields:
            values = [getattr(m, name) for m in self.metrics_history
                      if getattr(m, name) is not None]
            out[name] = max(values) if values else None
            out[f'{name}_of'] = len(values)
        return out

    def clear_history(self) -> None:
        self.metrics_history.clear()

    def drop_gpu_cache(self) -> None:
        """Forget the adapter sample being held, so the next question really asks."""
        self._gpu_cache = None
        self._gpu_at = 0.0


class FunctionProfiler:
    """Wall-clock timings around the app's own operations.

    A start with no matching end, or an end with no start, is counted rather than
    dropped: both used to vanish quietly, which left a table of timings that looked
    complete and was not.
    """

    def __init__(self) -> None:
        self.profiles: Dict[str, List[float]] = {}
        self._active: Dict[str, float] = {}
        self.unmatched_ends = 0
        self.double_starts = 0

    def start_profile(self, function_name: str) -> None:
        if function_name in self._active:
            self.double_starts += 1
        self._active[function_name] = time.perf_counter()

    def end_profile(self, function_name: str) -> Optional[float]:
        if function_name not in self._active:
            self.unmatched_ends += 1
            return None
        elapsed = time.perf_counter() - self._active.pop(function_name)
        self.profiles.setdefault(function_name, []).append(elapsed)
        return elapsed

    def get_profile_result(self, function_name: str) -> Optional[ProfileResult]:
        times = self.profiles.get(function_name)
        if not times:
            return None
        return ProfileResult(
            function_name=function_name,
            call_count=len(times),
            total_time=sum(times),
            average_time=sum(times) / len(times),
            min_time=min(times),
            max_time=max(times),
            timestamp=time.time(),
        )

    def get_all_results(self) -> List[ProfileResult]:
        results = []
        for name in sorted(self.profiles):
            result = self.get_profile_result(name)
            if result:
                results.append(result)
        return results

    def clear_profile(self, function_name: str) -> None:
        self.profiles.pop(function_name, None)

    def clear_all(self) -> None:
        self.profiles.clear()
        self._active.clear()
        self.unmatched_ends = 0
        self.double_starts = 0


class BottleneckDetector:
    """Compares measured fields to LIMITS and to the user's budgets, and names neither
    reading it does not have.

    The two jobs this class does are different kinds of claim. A limit is this app's own
    policy, so a finding against it always exists once the reading does. A budget is a
    number typed into a box - the process memory ceiling and the adapter memory alert - so
    a finding against it exists only while the box has been filled, and the sample keeps
    its reason in `not_read` when the reader that would answer it never did.
    """

    def __init__(self, limits: Optional[Dict[str, float]] = None,
                 budgets: Optional[Dict[str, Any]] = None) -> None:
        self.limits = dict(limits or LIMITS)
        self.budgets = dict(BUDGETS)
        for name, value in (budgets or {}).items():
            self.set_budgets(**{name: value})

    def set_budgets(self, **values) -> Dict[str, Any]:
        """Type a budget in, or type it out again, and answer with what the check now holds.

        A non-number is refused rather than stored: a budget that compares nothing is how a
        finding disappears without anybody pressing anything.
        """
        refused = []
        for name, value in values.items():
            if name not in BUDGETS:
                refused.append(f'{name}: no budget of this name is checked')
                continue
            if value is None:
                self.budgets[name] = None
                continue
            try:
                amount = float(value)
            except (TypeError, ValueError):
                refused.append(f'{name}: {value!r} is not a number in megabytes')
                continue
            self.budgets[name] = amount if amount > 0 else None
            if amount <= 0:
                refused.append(f'{name}: {value} MB bounds nothing, so the check is off')
        return dict(self.budgets, refused=refused)

    def analyze(self, metrics: PerformanceMetrics) -> List[Dict[str, str]]:
        findings: List[Dict[str, str]] = []

        window = (f'{metrics.window_seconds:.2f} s'
                  if metrics.window_seconds else 'no window')

        def severity_for(over_by):
            """The one rule that turns 'past' into a word, shared by both kinds below."""
            return 'High' if over_by >= 0.2 else 'Medium'

        def add(kind, label, observed, limit, over_by):
            findings.append({
                'kind': kind,
                'observed': f'{label} {observed}',
                'limit': f'{limit:g}',
                'severity': severity_for(over_by),
                'because': (f'{observed} is {over_by * 100:.0f}% past the {limit:g} this '
                            f'app checks itself against, measured over {window}'),
            })

        def add_budget(kind, label, observed, budget, over_by, box, reader):
            """The same shape as `add`, for a number the user typed rather than a policy.

            The sentence has to say which box owns the figure and which reader answered the
            observation, because a budget finding is only actionable if the person who set
            it can find it again.
            """
            findings.append({
                'kind': kind,
                'observed': f'{label} {observed}',
                'limit': f'{budget:g}',
                'severity': severity_for(over_by),
                'because': (f'{observed} is {over_by * 100:.0f}% past the {budget:g} MB set '
                            f'in the {box} box, and {reader}'),
            })

        if metrics.cpu_percent is not None and metrics.cpu_percent > self.limits['cpu_percent']:
            add('CPU', f'CPU', f'{metrics.cpu_percent:.1f}% busy across the logical cores',
                self.limits['cpu_percent'],
                metrics.cpu_percent / self.limits['cpu_percent'] - 1)
        if (metrics.memory_percent is not None
                and metrics.memory_percent > self.limits['memory_percent']):
            add('Memory', 'Memory',
                f'{metrics.memory_percent:.1f}% of physical memory in use',
                self.limits['memory_percent'],
                metrics.memory_percent / self.limits['memory_percent'] - 1)
        if (metrics.gpu_load_percent is not None
                and metrics.gpu_load_percent > self.limits['gpu_load_percent']):
            add('GPU', 'Adapter', f'{metrics.gpu_load_percent:.1f}% load reported by '
                                  f'{metrics.gpu_reader}', self.limits['gpu_load_percent'],
                metrics.gpu_load_percent / self.limits['gpu_load_percent'] - 1)
        if metrics.fps is not None and metrics.fps < self.limits['fps']:
            add('Frames', 'Frames',
                f'{metrics.fps:.1f} fps from {metrics.frames} frames the app itself drew',
                self.limits['fps'], 1 - metrics.fps / self.limits['fps'])
        if (metrics.frame_time_ms is not None
                and metrics.frame_time_ms > self.limits['frame_time_ms']):
            add('Frame time', 'Frame time',
                f'{metrics.frame_time_ms:.1f} ms between finished frames',
                self.limits['frame_time_ms'],
                metrics.frame_time_ms / self.limits['frame_time_ms'] - 1)

        process_budget = self.budgets.get('process_memory_budget_mb')
        if (process_budget and metrics.process_rss_mb is not None
                and metrics.process_rss_mb > process_budget):
            add_budget('Process memory', 'This process',
                       f'{metrics.process_rss_mb:.1f} MB resident', process_budget,
                       metrics.process_rss_mb / process_budget - 1, 'Memory Limit',
                       ('psutil read it from this process at this sample, so it is not an '
                        'average over the window'))
        adapter_budget = self.budgets.get('adapter_memory_alert_mb')
        if (adapter_budget and metrics.gpu_memory_used_mb is not None
                and metrics.gpu_memory_used_mb > adapter_budget):
            add_budget('Adapter memory', 'Adapter memory',
                       f'{metrics.gpu_memory_used_mb:.0f} MB in use', adapter_budget,
                       metrics.gpu_memory_used_mb / adapter_budget - 1, 'GPU Memory Allocation',
                       (f'{metrics.gpu_reader or "the GPU reader"} answered it; this app '
                        f'does not own the adapter\'s memory, only the figure'))
        return findings

    def not_measured(self, metrics: PerformanceMetrics) -> List[str]:
        """What this check could not judge, in the readers' own words."""
        return metrics.unmeasured()

    def budget_notes(self, metrics: PerformanceMetrics) -> List[str]:
        """One line per budget, so a typed-in ceiling is never silent.

        A budget with no finding beside it can mean three different things - under it, over
        it, or unable to be compared because the reading it needs was refused - and only the
        first of those is supposed to be quiet.
        """
        notes: List[str] = []
        for name, field, box in (('process_memory_budget_mb', 'process_rss_mb',
                                  'Memory Limit'),
                                 ('adapter_memory_alert_mb', 'gpu_memory_used_mb',
                                  'GPU Memory Allocation')):
            budget = self.budgets.get(name)
            if not budget:
                notes.append(f'{box}: nothing is typed in it, so no figure is compared')
            elif getattr(metrics, field) is None:
                notes.append(
                    f'{box} {budget:g} MB: no comparison, because no reader answered '
                    f'{field} - {metrics.not_read.get(field, "no reason was recorded")} '
                    f'(the {box} box bounds a figure this machine has not given)')
            else:
                notes.append(f'{box} {budget:g} MB against '
                             f'{getattr(metrics, field):.1f} MB read from the machine')
        return notes

    def score(self, metrics: PerformanceMetrics) -> Dict[str, Any]:
        """This app's own pressure score, from the fields that were actually read.

        The weights are policy (SCORE_WEIGHTS) and the deductions are over-limit
        amounts, so the score means "how far past this app\'s limits the readings went".
        It is not a machine rating and it refuses outright when the two fields it most
        depends on were never read.
        """
        basis: List[str] = []
        missing: List[str] = []
        value = 100.0

        pairs = (('cpu_percent', metrics.cpu_percent, 'above the CPU limit'),
                 ('memory_percent', metrics.memory_percent, 'above the memory limit'),
                 ('gpu_load_percent', metrics.gpu_load_percent, 'above the adapter limit'))
        for name, observed, wording in pairs:
            limit = self.limits[name]
            if observed is None:
                missing.append(f'{name}: {metrics.not_read.get(name, "no reading")}')
                continue
            if observed > limit:
                deduction = (observed - limit) * SCORE_WEIGHTS[name]
                value -= deduction
                basis.append(f'{name} {observed:.1f}% is {observed - limit:.1f} points '
                             f'{wording} (-{deduction:.1f})')
            else:
                basis.append(f'{name} {observed:.1f}% is within its {limit:g} limit')

        if metrics.fps is None:
            missing.append(f'fps: {metrics.not_read.get("fps", "no frames were drawn")}')
        elif metrics.fps < self.limits['fps']:
            deduction = (self.limits['fps'] - metrics.fps) * SCORE_WEIGHTS['fps']
            value -= deduction
            basis.append(f'fps {metrics.fps:.1f} is below the app\'s '
                         f'{self.limits["fps"]:g} (-{deduction:.1f})')
        else:
            basis.append(f'fps {metrics.fps:.1f} is at or above the app\'s '
                         f'{self.limits["fps"]:g}')

        if not basis:
            return {'value': None, 'basis': [], 'missing': missing,
                    'reason': 'nothing was measured, so there is nothing to score'}
        required = [name for name in ('cpu_percent', 'memory_percent')
                    if getattr(metrics, name) is None]
        if required:
            return {'value': None, 'basis': basis, 'missing': missing,
                    'reason': f'refused: {", ".join(required)} was never read, and a '
                              f'score of 100 from the readings that did arrive would be '
                              f'the same all-clear the old default gave'}
        return {'value': max(0, min(100, int(round(value)))), 'basis': basis,
                'missing': missing,
                'reason': ('scored from '
                           f'{len(basis)} measured field(s); '
                           f'{len(missing)} field(s) refused, listed in missing')}


class OptimizationSuggester:
    """Advice tied to a measurement, naming the control in this app that changes it.

    The `impact` strings this replaced promised "30-50%" and "double or triple FPS"
    from no measurement of anything. The app has never benchmarked its own settings
    against each other, so it does not know those numbers and now does not say them:
    each line says which reading brought it up, and what the app can show measured.
    """

    LEVERS = {
        'CPU': ('Run fewer jobs at once',
                'Settings pane - "Max Concurrent Jobs", and the "Max Threads" box, which '
                'the Performance and Post-Processing panes both read from one stored value'),
        'Memory': ('Free what the app is holding',
                   'Memory pane - Clear Cache and Force GC, which report the measured '
                   'resident size before and after'),
        'Process memory': ('Hand the pages back, or raise the ceiling',
                           'Memory pane - Trim Working Set calls K32EmptyWorkingSet and '
                           'prints the resident size before and after it; the Memory Limit '
                           'box is the figure this finding was compared against'),
        'Adapter memory': ('Ask the adapter for less at a time',
                           'GPU Acceleration pane - GPU Memory Allocation holds the number '
                           'this was compared against. This app does not own the adapter\'s '
                           'memory, so the box bounds an alert rather than a reservation'),
        'GPU': ('Ask the adapter for less at a time',
                'the viewer\'s own settings; this app does not drive the adapter, so the '
                'change is in the 3D software that owns it'),
        'Frames': ('Draw fewer or cheaper frames',
                   'the 3D view that is stamping them; the frame clock names which one'),
        'Frame time': ('Draw fewer or cheaper frames',
                       'the 3D view that is stamping them; the frame clock names which one'),
    }

    def get_suggestions(self, metrics: PerformanceMetrics,
                        findings: List[Dict[str, str]]) -> List[Dict[str, str]]:
        suggestions = []
        for finding in findings:
            lever = self.LEVERS.get(finding['kind'])
            if lever is None:
                continue
            suggestions.append({
                'category': finding['kind'],
                'priority': finding['severity'],
                'suggestion': lever[0],
                'because': finding['because'],
                'where_to_change': lever[1],
            })
        if findings:
            memory_high = any(f['kind'] == 'Memory' for f in findings)
            if memory_high:
                suggestions.append({
                    'category': 'Memory',
                    'priority': 'High',
                    'suggestion': 'Close the models the app is not showing',
                    'because': ('the machine itself reported '
                                f'{metrics.memory_percent:.1f}% of its physical memory in '
                                'use, so the app cannot promise that clearing its own '
                                'cache is enough'),
                    'where_to_change': 'Library pane, which holds the loaded assets',
                })
        if not suggestions:
            refused = metrics.unmeasured()
            suggestions.append({
                'category': 'Nothing measured past a limit',
                'priority': 'Info',
                'suggestion': ('no advice: nothing that was measured is past a limit'
                               if not refused else
                               'no advice, and this sample was incomplete - see what was '
                               'not measured'),
                'because': '; '.join(refused) if refused else (
                    f'cpu {metrics.cpu_percent}, memory {metrics.memory_percent}, '
                    f'adapter load {metrics.gpu_load_percent}, fps {metrics.fps}'),
                'where_to_change': '',
            })
        return suggestions


class PerformanceLogger:
    """Append-only JSON lines, written when asked rather than when imported.

    Creating the log directory used to happen in `__init__`, so importing the
    performance pane made a folder appear, and every sample used to re-read and
    re-write one growing JSON array - which loses the whole day's history if a write
    is interrupted. A line per sample costs one append and survives a crash.
    """

    def __init__(self, log_dir: Optional[str] = None) -> None:
        self.log_dir = log_dir or os.path.join(data_dir(), 'performance_logs')

    @staticmethod
    def _safe_name(session_name: str) -> str:
        """A file name out of a session name: nothing that could be a path survives.

        The metrics file has always been sanitised; the profile file used to paste the
        name straight in, so a session called `..\\..\\x` wrote outside the log folder.
        Both ask this now.
        """
        return ''.join(c if (c.isalnum() or c in '-_') else '_' for c in session_name)

    def _session_file(self, session_name: str) -> str:
        return os.path.join(self.log_dir,
                            f'{self._safe_name(session_name) or "default"}_'
                            f'{datetime.now().strftime("%Y%m%d")}.jsonl')

    def _append(self, path: str, rows: List[Dict[str, Any]]) -> None:
        os.makedirs(self.log_dir, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row) + '\n')

    def log_metrics(self, metrics: PerformanceMetrics, session_name: str = 'default') -> str:
        path = self._session_file(session_name)
        self._append(path, [metrics.to_dict()])
        return path

    def log_profile_results(self, results: List[ProfileResult],
                           session_name: str = 'default') -> str:
        path = os.path.join(self.log_dir,
                           f'profiles_{self._safe_name(session_name) or "default"}_'
                           f'{datetime.now().strftime("%Y%m%d_%H%M%S")}.jsonl')
        self._append(path, [r.to_dict() for r in results])
        return path

    def get_session_logs(self, session_name: str = 'default') -> List[Dict[str, Any]]:
        """The lines this session wrote today, or an empty list with nothing claimed."""
        path = self._session_file(session_name)
        if not os.path.exists(path):
            return []
        rows = []
        try:
            with open(path, encoding='utf-8') as handle:
                for line in handle:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return rows
        return rows


class BenchmarkHistory:
    """The app's own past runs on this machine, which is all a benchmark can compare with.

    A percentile needs every other machine's result. RenderFox has never collected one,
    so this file keeps only what this app measured here, and the comparison it can
    actually support: this run against the earlier runs.
    """

    LIMIT = 200

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.path.join(data_dir(), 'benchmarks.json')

    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {'runs': [], 'reason': ''}
        try:
            with open(self.path, encoding='utf-8') as handle:
                loaded = json.load(handle)
        except (OSError, ValueError) as failed:
            return {'runs': [],
                    'reason': f'the stored history could not be read '
                              f'({type(failed).__name__}: {failed}); it was left on disk '
                              f'untouched'}
        runs = loaded.get('runs') if isinstance(loaded, dict) else None
        if not isinstance(runs, list):
            return {'runs': [], 'reason': 'the stored history is not a run list; '
                                          'it was left on disk untouched'}
        return {'runs': runs, 'reason': ''}

    def record(self, run: Dict[str, Any]) -> Dict[str, Any]:
        """Append one finished run, atomically, and say where it went."""
        stored = self._read()
        runs = stored['runs'] + [run]
        temp = f'{self.path}.writing'
        try:
            folder = os.path.dirname(self.path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(temp, 'w', encoding='utf-8') as handle:
                json.dump({'runs': runs[-self.LIMIT:]}, handle, indent=1)
            os.replace(temp, self.path)
        except OSError as failed:
            try:
                os.remove(temp)
            except OSError:
                pass
            return {'recorded': False,
                    'reason': f'the run was measured but not stored: '
                              f'{type(failed).__name__}: {failed}'}
        return {'recorded': True, 'path': self.path,
                'reason': stored['reason'] or ''}

    def count(self) -> Dict[str, Any]:
        """How many runs the file keeps, where it is, and whether it could be read.

        The Clear button on the Benchmarks pane empties a table, not this file. This is the
        answer that lets the button say so, because "cleared" is what a user hears as
        "the measurements are gone".
        """
        stored = self._read()
        return {'count': len(stored['runs']), 'path': self.path, 'reason': stored['reason']}

    def recent_runs(self, kind: str, limit: int = 10) -> Dict[str, Any]:
        """The stored runs of one kind, oldest first, with the read's own reason."""
        stored = self._read()
        rows = [row for row in stored['runs'] if row.get('kind') == kind]
        return {'runs': rows[-limit:], 'reason': stored['reason'],
                'all_kinds': sorted({str(row.get('kind')) for row in stored['runs']})}

    def comparison(self, kind: str, value: float,
                   higher_is_better: bool = True) -> Dict[str, Any]:
        """Where this run sits among the app's own earlier runs of the same work."""
        stored = self._read()
        if stored['reason']:
            return {'runs_stored': 0, 'reason': stored['reason']}
        earlier = [r['value'] for r in stored['runs']
                   if r.get('kind') == kind and isinstance(r.get('value'), (int, float))]
        if not earlier:
            return {'runs_stored': 0, 'best': None, 'worst': None, 'previous_runs': 0,
                    'reason': 'this is the first run of this work the app has stored on '
                              'this machine, so there is nothing to compare it with yet'}
        best = max(earlier) if higher_is_better else min(earlier)
        worst = min(earlier) if higher_is_better else max(earlier)
        delta = ((value - best) / best * 100.0) if best else 0.0
        better = (value > best) if higher_is_better else (value < best)
        return {
            'runs_stored': len(stored['runs']),
            'previous_runs': len(earlier),
            'best': round(best, 3),
            'worst': round(worst, 3),
            'this_is_best': bool(better),
            'delta_vs_best_percent': round(delta, 1),
            'reason': ('faster than every earlier run of this work' if better else
                       f'{abs(delta):.1f}% short of the best run the app stored'),
        }


class BenchmarkRunner:
    """The app's one benchmark engine: bounded work, timed, kept with what ran.

    Two engines used to answer this question - `PerformanceBenchmark` in the
    diagnostic engine, which summed `math.sqrt` over a million integers and called the
    result Excellent/Good/Average on thresholds its own loop always beat, and
    `BenchmarkRunner` here, which multiplied matrices and was then painted as a
    percentile. One engine now, and each kind says which work it performed, how long it
    took, what machine it did it on, and how it sat against the app's own earlier runs.
    """

    KINDS = ('cpu', 'memory', 'storage', 'geometry')

    def __init__(self, history: Optional[BenchmarkHistory] = None) -> None:
        self.history = history if history is not None else BenchmarkHistory()

    @staticmethod
    def _machine_note() -> Dict[str, Any]:
        """The facts about this machine a number needs in order to mean the same twice."""
        cpu = SystemInfo.get_cpu_info()
        return {
            'cores': f"{cpu['physical_cores']} physical / {cpu['logical_cores']} logical",
            'clock': cpu['current_frequency'],
            'numpy': np.__version__,
            'python': sys.version.split()[0],
            'blas_threads': _blas_thread_note(),
        }

    @staticmethod
    def _refusal(kind: str, reason: str) -> Dict[str, Any]:
        return {'kind': kind, 'ran': None, 'reason': reason, 'measured_at': _stamp(),
                'work': {}, 'result': {}, 'machine': {}}

    def run(self, kind: str, duration: float = 2.0, record: bool = False,
            should_stop: Optional[Callable[[], bool]] = None,
            progress_callback: Optional[Callable[..., None]] = None,
            **work) -> Dict[str, Any]:
        """Do one kind of work and report what was measured."""
        if kind not in self.KINDS:
            return self._refusal(
                kind, f'"{kind}" is not work this engine performs; it performs '
                      f'{", ".join(self.KINDS)}')
        result = getattr(self, f'{kind}_benchmark')(
            duration=duration, should_stop=should_stop,
            progress_callback=progress_callback, **work)
        result['machine'] = self._machine_note()
        if result.get('comparison_value') is not None and record:
            outcome = self.history.record({
                'kind': kind, 'value': result['comparison_value'],
                'unit': result['comparison_unit'], 'at': _stamp()})
            result['stored'] = outcome
        return result

    def run_all(self, duration: float = 2.0, record: bool = False,
                should_stop: Optional[Callable[[], bool]] = None,
                progress_callback: Optional[Callable[..., None]] = None,
                **work) -> Dict[str, Any]:
        """Every kind, each with its own answer or its own reason.

        `work` reaches the kinds that take a box - the storage buffer size and the
        memory-map choice - and is ignored by the ones that do not, so the Full System
        Benchmark button runs the same settings the individual buttons would.
        """
        answers = {}
        for index, kind in enumerate(self.KINDS):
            answers[kind] = self.run(kind, duration=duration, record=record,
                                     should_stop=should_stop,
                                     progress_callback=progress_callback, **work)
        refused = [f'{kind}: {a["reason"]}'
                   for kind, a in answers.items() if a['ran'] is None]
        return {'kinds': answers,
                'performed': [k for k, a in answers.items() if a['ran'] is not None],
                'refused': refused,
                'measured_at': _stamp()}

    def cpu_benchmark(self, duration: float = 2.0, matrix: int = 256,
                      should_stop=None, progress_callback=None, **_ignored) -> Dict[str, Any]:
        """Multiply square float64 matrices until the clock says so.

        numpy hands the multiplication to its BLAS, which may use several cores; the
        machine note carries how many threads that was, because a single-core claim
        would be a different number than the one measured.
        """
        if matrix < 2:
            return self._refusal('cpu', f'a {matrix}x{matrix} matrix is not work')
        size = int(matrix)
        duration = max(0.05, float(duration))
        started = time.perf_counter()
        multiplies = 0
        while True:
            if should_stop is not None and should_stop():
                return self._refusal('cpu', f'stopped after {multiplies} multiplies')
            a = np.random.rand(size, size)
            b = np.random.rand(size, size)
            a @ b
            multiplies += 1
            if progress_callback:
                progress_callback(min(100, int((time.perf_counter() - started)
                                               / duration * 100)))
            if time.perf_counter() - started >= duration:
                break
        elapsed = time.perf_counter() - started
        per_second = multiplies / elapsed if elapsed > 0 else None
        flops = 2.0 * (size ** 3) * multiplies
        return {
            'kind': 'cpu',
            'ran': f'{size}x{size} float64 matrix multiplies for {elapsed:.3f} s',
            'reason': '',
            'measured_at': _stamp(),
            'work': {'matrix_size': size, 'multiplies': multiplies},
            'result': {
                'multiplies_per_second': round(per_second, 2) if per_second else None,
                'elapsed_seconds': round(elapsed, 3),
                'gigaflops': round(flops / elapsed / 1e9, 3) if elapsed > 0 else None,
                'how_gigaflops_was_got': 'derived: 2 x size^3 x multiplies / elapsed',
            },
            'comparison_value': round(per_second, 2) if per_second else None,
            'comparison_unit': 'multiplies/s',
            'against': self.history.comparison('cpu', per_second) if per_second else {},
        }

    def memory_benchmark(self, duration: float = 2.0, footprint_mb: float = 256.0,
                         should_stop=None, progress_callback=None, **_ignored) -> Dict[str, Any]:
        """Write and copy arrays the app can see in its own resident size.

        The reported figures are bytes moved over the measured time; the RSS delta is
        what the operating system says this process grew by, which is the part of the
        sentence that is not arithmetic.
        """
        if footprint_mb <= 0:
            return self._refusal('memory', f'a footprint of {footprint_mb} MB moves nothing')
        elements = max(1, int(float(footprint_mb) * 1024 * 1024 / 8))
        duration = max(0.05, float(duration))
        source = np.ones(elements, dtype=np.float64)
        target = np.empty(elements, dtype=np.float64)
        rss_before = psutil.Process(os.getpid()).memory_info().rss

        started = time.perf_counter()
        fills = copies = 0
        while True:
            if should_stop is not None and should_stop():
                return self._refusal('memory', f'stopped after {fills} fills')
            target[:] = source
            copies += 1
            source *= 1.0000001
            fills += 1
            if progress_callback:
                progress_callback(min(100, int((time.perf_counter() - started)
                                               / duration * 100)))
            if time.perf_counter() - started >= duration:
                break
        elapsed = time.perf_counter() - started
        moved_mb = (fills + copies) * elements * 8 / (1024 * 1024)
        rss_after = psutil.Process(os.getpid()).memory_info().rss
        del source, target
        mb_per_second = moved_mb / elapsed if elapsed > 0 else None
        return {
            'kind': 'memory',
            'ran': f'{fills} in-place multiplies and {copies} copies of a '
                   f'{footprint_mb:g} MB float64 array in {elapsed:.3f} s',
            'reason': '',
            'measured_at': _stamp(),
            'work': {'footprint_mb': footprint_mb, 'fills': fills, 'copies': copies},
            'result': {
                'mb_per_second': round(mb_per_second, 1) if mb_per_second else None,
                'elapsed_seconds': round(elapsed, 3),
                'rss_delta_mb': round((rss_after - rss_before) / (1024 * 1024), 1),
                'note': ('the arrays are freed again before this figure is reported, so '
                         'the resident size is measured with them alive'),
            },
            'comparison_value': round(mb_per_second, 1) if mb_per_second else None,
            'comparison_unit': 'MB/s',
            'against': self.history.comparison('memory', mb_per_second)
                       if mb_per_second else {},
        }

    def storage_benchmark(self, duration: float = 2.0, size_mb: float = 128.0,
                          directory: Optional[str] = None, should_stop=None,
                          progress_callback=None, buffer_kb: Optional[float] = None,
                          use_memory_map: Optional[bool] = None,
                          **_ignored) -> Dict[str, Any]:
        """Write and read back a real file on the volume the app writes to anyway.

        Two of the pane's boxes are read here, which is what makes them settings rather
        than decoration:

        `buffer_kb` (Buffer Size) is how many bytes each `write()` is handed. The figure
        is then a figure about a chunked writer, and the number of chunks is reported with
        it, because the same megabytes written in one call is a different measurement.
        `use_memory_map` (Memory Mapped Reads) chooses how the bytes come back: an
        ordinary `read()`, or a mapping the operating system fills a page at a time. Each
        slice taken out of a mapping is still turned into bytes to be compared, so the
        mapped figure is the cost of paging *and* copying, and `cache_note` says so.

        `buffering=0` and one `fsync` are what make the write figure mean "the disk was
        given these bytes". Free space is measured before and after, and the file is
        verified gone - which needs the mapping closed first, because on Windows an open
        map holds the file and the remove would answer `ERROR_ACCESS_DENIED`.
        """
        if size_mb <= 0:
            return self._refusal('storage', f'a file of {size_mb} MB holds nothing')
        from ..utils.file_utils import get_temp_directory
        folder = directory or get_temp_directory()
        if not os.path.isdir(folder):
            return self._refusal('storage', f'{folder} is not a folder on this disk, so there '
                                            f'is no volume here to measure a write against')
        payload = os.urandom(max(1, int(float(size_mb) * 1024 * 1024)))
        size_bytes = len(payload)
        chunk = size_bytes
        if buffer_kb is not None:
            try:
                asked = int(float(buffer_kb) * 1024)
            except (TypeError, ValueError):
                return self._refusal('storage', f'{buffer_kb!r} is not a buffer size in KB')
            if asked <= 0:
                return self._refusal(
                    'storage', f'a buffer of {buffer_kb} KB is {asked} bytes, so nothing '
                               f'would be handed to the writer')
            chunk = min(asked, size_bytes)
        path = os.path.join(folder, f'rf_storage_probe_{os.getpid()}.bin')
        free_before = psutil.disk_usage(folder).free

        write_started = time.perf_counter()
        chunks_written = 0
        stopped = False
        try:
            with open(path, 'wb', buffering=0) as handle:
                for start in range(0, size_bytes, chunk):
                    if should_stop is not None and should_stop():
                        stopped = True
                        break
                    handle.write(payload[start:start + chunk])
                    chunks_written += 1
                    if progress_callback:
                        progress_callback(min(45, int(45 * start / size_bytes)))
                if not stopped:
                    handle.flush()
                    os.fsync(handle.fileno())
        except OSError as failed:
            return self._refusal('storage', f'writing {path} failed: '
                                            f'{type(failed).__name__}: {failed}')
        write_elapsed = time.perf_counter() - write_started
        if stopped:
            try:
                os.remove(path)
            except OSError:
                pass
            left = f'{path} is still on disk' if os.path.exists(path) else (
                'the partial probe file was removed')
            return self._refusal(
                'storage', f'stopped after {chunks_written} chunk(s) of {chunk} bytes; {left}')
        if progress_callback:
            progress_callback(50)

        read_started = time.perf_counter()
        got_bytes = 0
        if use_memory_map:
            import mmap
            read_by = 'memory map'
            try:
                with open(path, 'rb') as handle:
                    with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
                        for start in range(0, size_bytes, chunk):
                            piece = mapping[start:start + chunk]
                            if piece != payload[start:start + chunk]:
                                break
                            got_bytes += len(piece)
            except (OSError, ValueError) as failed:
                return self._refusal('storage', f'mapping {path} failed: '
                                                f'{type(failed).__name__}: {failed}')
        else:
            read_by = 'read()'
            try:
                with open(path, 'rb', buffering=0) as handle:
                    data = handle.read()
            except OSError as failed:
                return self._refusal('storage', f'reading {path} failed: '
                                                f'{type(failed).__name__}: {failed}')
            got_bytes = len(data) if data == payload else 0
        read_elapsed = time.perf_counter() - read_started
        if progress_callback:
            progress_callback(100)

        intact = got_bytes == size_bytes
        try:
            os.remove(path)
            gone = not os.path.exists(path)
            cleanup_reason = '' if gone else f'{path} is still on disk'
        except OSError as failed:
            gone = False
            cleanup_reason = f'the probe file could not be removed: {failed}'
        free_after = psutil.disk_usage(folder).free
        write_mb = size_bytes / (1024 * 1024) / write_elapsed if write_elapsed > 0 else None
        read_mb = size_bytes / (1024 * 1024) / read_elapsed if read_elapsed > 0 else None
        mapped_note = ('; this read went through a memory map, so it is the cost of the '
                       'operating system paging the file in and of this app copying each '
                       'slice out of it - a second run of the same file usually answers '
                       'faster than the disk can')
        return {
            'kind': 'storage',
            'ran': f'wrote and read back {size_bytes / (1024 * 1024):.0f} MB on '
                   f'{os.path.splitdrive(path)[0] or path} in {chunks_written} x '
                   f'{chunk // 1024} KB chunk(s), read by {read_by}',
            'reason': '' if intact else 'the bytes read back were not the bytes written',
            'measured_at': _stamp(),
            'work': {'path': path, 'bytes': size_bytes, 'verified_gone': gone,
                     'buffer_kb': round(chunk / 1024), 'read_by': read_by},
            'result': {
                'write_mb_per_second': round(write_mb, 1) if write_mb else None,
                'read_mb_per_second': round(read_mb, 1) if read_mb else None,
                'write_seconds': round(write_elapsed, 4),
                'read_seconds': round(read_elapsed, 4),
                'chunks_written': chunks_written,
                'chunk_bytes': chunk,
                'read_back_identical': intact,
                'free_bytes_before': free_before,
                'free_bytes_after': free_after,
                'cleanup': cleanup_reason or 'probe file removed',
                'cache_note': ('the write was flushed and fsync-ed; the read still goes '
                               'through whatever the operating system kept, so the read '
                               'figure can be higher than the disk' + mapped_note),
            },
            'comparison_value': round(write_mb, 1) if write_mb else None,
            'comparison_unit': 'write MB/s',
            'against': self.history.comparison('storage', write_mb) if write_mb else {},
        }

    def geometry_benchmark(self, duration: float = 2.0, points: int = 200000,
                           should_stop=None, progress_callback=None,
                           **_ignored) -> Dict[str, Any]:
        """Estimate normals on a point cloud through Open3D, and say what ran it.

        This replaced a button labelled GPU Benchmark. Open3d's normal estimation is
        not a shader: on a CPU build it runs on the CPU, and nothing about it lets this
        app claim the adapter drew a frame. The name of the work is the honest version
        of the claim, and the answer says which Open3D build ran it.
        """
        try:
            import open3d as o3d
        except Exception as failed:
            return self._refusal('geometry', f'Open3D could not be imported, so this work '
                                             f'cannot be run: {type(failed).__name__}: '
                                             f'{failed}')
        if points < 1000:
            return self._refusal('geometry', f'{points} points is not enough to time')
        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector(
            np.random.rand(int(points), 3) * 100.0)
        started = time.perf_counter()
        rounds = 0
        neighbourhood = o3d.geometry.KDTreeSearchParamHybrid(radius=0.1, max_nn=30)
        try:
            while True:
                if should_stop is not None and should_stop():
                    return self._refusal('geometry', f'stopped after {rounds} rounds')
                cloud.estimate_normals(search_param=neighbourhood)
                rounds += 1
                if progress_callback:
                    progress_callback(min(100, int((time.perf_counter() - started)
                                                   / max(0.05, duration) * 100)))
                if time.perf_counter() - started >= duration:
                    break
        except Exception as failed:
            return self._refusal('geometry', f'Open3D raised '
                                             f'{type(failed).__name__}: {failed}')
        elapsed = time.perf_counter() - started
        per_second = rounds / elapsed if elapsed > 0 else None
        return {
            'kind': 'geometry',
            'ran': f'{rounds} normal-estimation rounds over {points} points in '
                   f'{elapsed:.3f} s',
            'reason': '',
            'measured_at': _stamp(),
            'work': {'points': int(points), 'rounds': rounds},
            'result': {
                'rounds_per_second': round(per_second, 3) if per_second else None,
                'elapsed_seconds': round(elapsed, 3),
                'open3d_version': o3d.__version__,
                'device': ('this Open3D build reports a CUDA device'
                           if _open3d_has_cuda(o3d) else
                           'Open3D ran this on the CPU; the display adapter did not '
                           'take part'),
            },
            'comparison_value': round(per_second, 3) if per_second else None,
            'comparison_unit': 'rounds/s',
            'against': self.history.comparison('geometry', per_second)
                       if per_second else {},
        }

    # The one verb that is not a kind, kept because it answers the label the Geometry
    # button used to carry. The kinds themselves are reached only through `run`/`run_all`.
    def run_gpu_benchmark(self) -> Dict[str, Any]:
        return self._refusal(
            'gpu', 'there is no GPU benchmark to run: the work this app can time is '
                   'point-cloud normal estimation through Open3D, which runs on the CPU, '
                   'so press Geometry instead and read which device answered')

    @staticmethod
    def describe(result: Dict[str, Any]) -> str:
        """The same claim as `row_cells`, in prose, for a pane that shows text.

        Both panes' wording comes from here because the Diagnostics pane used to keep
        its own version of the sentence, and the two versions graded the same machine
        differently.
        """
        if result.get('ran') is None:
            return (f"{result.get('kind')}: did not run - "
                    f"{result.get('reason', 'no reason was given')}")
        lines = [f"{result.get('kind')}: {result['ran']}"]
        for name, value in result['result'].items():
            if isinstance(value, (int, float)):
                lines.append(f'  {name.replace("_", " ")}: {value}')
        against = (result.get('against') or {}).get('reason')
        if against:
            lines.append(f"  against this app's own earlier runs: {against}")
        machine = result.get('machine') or {}
        if machine:
            lines.append(f"  on this machine: {machine.get('cores')} at "
                         f"{machine.get('clock')}, {machine.get('blas_threads')}")
        return '\n'.join(lines)

    @staticmethod
    def row_cells(result: Dict[str, Any]) -> List[str]:
        """The four cells one benchmark row is allowed to contain.

        They are worded here rather than in the pane because the pane is where a
        "Top 1%" used to be written: a table column is a claim, and the claim belongs
        next to the measurement that supports it.
        """
        if result.get('ran') is None:
            return [str(result.get('kind', '?')), 'did not run',
                    str(result.get('reason', 'no reason was given')), '']
        figures = [f'{name.replace("_", " ")} {value}'
                   for name, value in result['result'].items()
                   if isinstance(value, (int, float))]
        against = result.get('against') or {}
        stored = result.get('stored')
        note = against.get('reason', 'this run was not compared with anything')
        if stored and not stored.get('recorded'):
            note = f'{note}; {stored["reason"]}'
        elif stored:
            note = f'{note}; stored as run number ' \
                   f'{against.get("previous_runs", 0) + 1}'
        return [str(result.get('kind')), str(result['ran']),
                '; '.join(figures) or 'no figure came out of this work', note]

    EXPORT_HEADERS = ('kind', 'what ran', 'figures', "against this app's own earlier runs")

    def stored_runs(self) -> Dict[str, Any]:
        """What the history file holds - the sentence a cleared table has to be honest about."""
        return self.history.count()

    def export(self, results: List[Dict[str, Any]],
               output_path: Optional[str] = None) -> Dict[str, Any]:
        """Write the table's own cells out, then read the file back to count the lines.

        A pane that builds its own export rows is a pane that can print a second, different
        claim about the same run - which is what `row_cells` exists to prevent, so the
        exporter calls it rather than repeating it. The read-back is the proof: a file that
        was opened and never written would otherwise be reported as an export.
        """
        import csv
        if output_path is None:
            output_path = os.path.join(
                data_dir(),
                f'benchmark_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
        folder = os.path.dirname(output_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        rows = [self.row_cells(result) for result in results]
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as handle:
                writer = csv.writer(handle)
                writer.writerow(self.EXPORT_HEADERS)
                writer.writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as failed:
            return {'written': False, 'path': output_path, 'rows': len(rows),
                    'reason': f'the export could not be written: '
                              f'{type(failed).__name__}: {failed}'}
        try:
            with open(output_path, encoding='utf-8', newline='') as handle:
                lines = len(list(csv.reader(handle)))
            size = os.path.getsize(output_path)
        except OSError as failed:
            return {'written': True, 'path': output_path, 'rows': len(rows),
                    'reason': f'the file was written but not read back: '
                              f'{type(failed).__name__}: {failed}'}
        return {'written': True, 'path': output_path, 'rows': len(rows), 'bytes': size,
                'lines_read_back': lines, 'headers': list(self.EXPORT_HEADERS),
                'reason': ('' if lines == len(rows) + 1 else
                           f'the file answers with {lines} line(s) for {len(rows)} row(s) '
                           f'plus a header')}


def _open3d_has_cuda(o3d_module) -> bool:
    try:
        import open3d.core as o3c  # noqa: F401 - presence only, the call below asks it
        return bool(o3d_module.core.Device.cuda_is_available())
    except Exception:
        return False


def _blas_thread_note() -> str:
    """How many threads numpy's BLAS says it will use, or that it does not say."""
    try:
        import threadpoolctl
        for info in threadpoolctl.threadpool_info():
            limit = info.get('internal_api') and info.get('num_threads')
            if limit:
                return f'{info["internal_api"]} with {limit} thread(s)'
    except Exception:
        pass
    return 'numpy did not report its BLAS thread count on this machine'


class PerformanceAnalyzer:
    """The performance panes' backend: one monitor, one engine, one store, one place per name.

    Every control on those panes reaches the machine through this class, and each of them
    either names the code below that reads it or names why nothing can - the table lives in
    `performance_controls`, and the verbs live here.
    """

    def __init__(self, gpu_reader: Optional[Callable[[], Dict[str, Any]]] = None,
                 clock: Optional[FrameClock] = None) -> None:
        self.monitor = PerformanceMonitor(clock=clock, gpu_reader=gpu_reader)
        self.profiler = FunctionProfiler()
        self.detector = BottleneckDetector()
        self.suggester = OptimizationSuggester()
        self.logger = PerformanceLogger()
        self.benchmark = benchmark_engine()
        self.profiles = performance_controls.PerformanceProfiles()
        self.garbage = performance_controls.GarbageCollectionRunner(profiler=self.profiler)
        self.adapter_name: Optional[str] = None
        self.last_trim: Optional[Dict[str, Any]] = None

    def start_monitoring(self, interval_ms: int = 1000) -> None:
        """Start the sample timer and the collection interval the stored mode names.

        The collector belongs here rather than in the constructor because its timer is a
        real pause in this process: a pane that was only ever built by a test would otherwise
        run `gc.collect()` every sixty seconds on somebody else's behalf.
        """
        self.monitor.start_monitoring(interval_ms)
        self.garbage.start()

    def stop_monitoring(self) -> None:
        self.monitor.stop_monitoring()

    def stop_everything(self) -> None:
        """Take the timers off the machine: the monitor's and the collector's.

        The pane calls this on its way out. A timer left running after the widgets it
        paints are gone is how a closed tab keeps sampling until the process does.
        """
        self.monitor.stop_monitoring()
        self.garbage.stop()

    # ---- the controls: one door in, one table saying what each door opens -------------

    def control_rows(self, widgets: List[str]) -> List[Dict[str, Any]]:
        """One row per widget the pane shows: what it stores, and what reads it.

        The pane prints these rather than writing its own labels beside its own boxes, so a
        control cannot look like a setting while behaving like a decoration.
        """
        rows = []
        for name in widgets:
            item = performance_controls.control(name)
            if item is None:
                rows.append({'widget': name, 'known': False, 'wired': False,
                             'note': 'this control is in neither the table of controls nor '
                                     'the table of buttons, so nothing here says what it '
                                     'does'})
                continue
            row = {'widget': name, 'label': item.label, 'kind': item.kind, 'known': True,
                   'wired': item.wired, 'key': item.qualified,
                   'note': performance_controls.sentence_for(item)}
            if item.key:
                row.update({k: v for k, v in
                            performance_controls.read_control(item).items()
                            if k in ('stored', 'value')})
            rows.append(row)
        return rows

    def uncovered_controls(self, widgets: List[str]) -> List[str]:
        """The widgets the tables say nothing about - the defect, named."""
        return performance_controls.uncovered(widgets)

    def apply_control(self, widget: str, value: Any) -> Dict[str, Any]:
        """Store one control and do whatever this process can do with it now.

        Two different things happen, and the answer keeps them apart: the store is written
        so the next reader of the value sees it, and the live verb runs so this process
        changes now. A control whose only effect is stored says so with `live` empty.
        """
        item = performance_controls.control(widget)
        if item is None:
            return {'widget': widget,
                    'stored': {'written': False,
                               'reason': f'"{widget}" is in no control table, so this app '
                                         f'does not know what it would set'}}
        outcome = {'widget': widget, 'label': item.label,
                   'stored': performance_controls.write_control(item, value)}
        outcome['stored']['label'] = item.label
        outcome['live'] = self._apply_live(widget, value) if outcome['stored']['written'] \
            else None
        return outcome

    def _apply_live(self, widget: str, value: Any) -> Optional[Dict[str, Any]]:
        """The in-process effect of one value already stored, or None when storing is it.

        Each branch names the verb it calls, because the claim this pane makes is that a
        box changes the running app - and a box whose value only lands in a file changes
        nothing until something reads the file.
        """
        if widget == 'thread_priority_combo':
            return performance_controls.set_process_priority(value)
        if widget == 'affinity_cb':
            return performance_controls.apply_cpu_affinity(bool(value))
        if widget == 'stack_size_spin':
            return performance_controls.apply_stack_size(value)
        if widget == 'garbage_collection_combo':
            return self.garbage.set_mode(value)
        if widget in ('memory_limit_spin', 'gpu_memory_spin'):
            name = ('process_memory_budget_mb' if widget == 'memory_limit_spin'
                    else 'adapter_memory_alert_mb')
            return self.detector.set_budgets(**{name: value})
        if widget == 'enable_gpu_cb':
            return self.set_adapter_reader(bool(value), self.adapter_name)
        if widget == 'gpu_device_combo':
            # Choosing which adapter to read is not a decision to start reading it. The
            # helper program runs only while `enable_gpu_cb` holds it on, so the name is
            # remembered and the reader is swapped only if one is already installed.
            asked = self.monitor.gpu_reader is not None
            return self.set_adapter_reader(asked, value)
        if widget == 'profile_combo':
            return self.apply_profile(value)
        return None

    def set_adapter_reader(self, enabled: bool,
                           adapter_name: Optional[str] = None) -> Dict[str, Any]:
        """Put the live adapter reader on the per-second sample, or take it off.

        `SystemInfo.live_gpu_sample` starts a helper program to answer, so the box that
        turns it on is a real decision about cost, not a decoration: while it is off the
        sample leaves the adapter fields None and carries the reason.
        """
        self.adapter_name = (adapter_name or '').strip() or None
        if not enabled:
            answer = self.monitor.set_gpu_reader(None)
            answer.update({'adapter': None,
                           'reader': None,
                           'reason': 'the box is off, so no helper program is started each '
                                     'sample and the adapter fields say why they are empty'})
            return answer
        answer = self.monitor.set_gpu_reader(
            lambda: SystemInfo.live_gpu_sample(adapter_name=self.adapter_name))
        answer.update({
            'adapter': self.adapter_name or 'the first adapter the reader answers',
            'reader': 'SystemInfo.live_gpu_sample',
            'reason': '' if self.adapter_name else
                      'no adapter was chosen, so the reader takes the first one it answers '
                      'for - the device box lists what Windows records here'})
        return answer

    def refresh_from_settings(self) -> Dict[str, Any]:
        """Read every stored control back and apply it, so a restart is not a reset.

        The values are read off the store rather than off the widgets: the widgets are what
        the pane paints from this answer, so applying them would only prove the screen
        agrees with itself.
        """
        applied = []
        for name, item in performance_controls.CONTROLS.items():
            if not (item.wired and item.key):
                continue
            stored = performance_controls.read_control(item)
            if not stored['stored']:
                applied.append({'widget': name, 'value': item.default, 'source': 'default',
                                'live': None,
                                'reason': stored['note']})
                continue
            restart_only = item.key in performance_controls.RESTART_KEYS
            applied.append({'widget': name, 'value': stored['value'], 'source': 'store',
                            'live': None if restart_only
                            else self._apply_live(name, stored['value']),
                            'reason': performance_controls.RESTART_NOTE if restart_only
                            else stored['note']})
        return {'applied': applied, 'count': len(applied),
                'reason': 'a control with nothing stored keeps its default and does not run '
                          'a live verb, so a first run changes nothing on the machine'}

    def apply_profile(self, name: str) -> Dict[str, Any]:
        """Write the knobs a profile names, then run the live verb each one owns."""
        outcome = self.profiles.apply(name)
        for row in outcome.get('written', []):
            row['live'] = self._apply_live(row['widget'], row['value'])
        return outcome

    def save_profile(self, name: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """Store the current values under a new name and read the entry back."""
        saved = self.profiles.save(name, values)
        if saved.get('saved'):
            saved['read_back'] = self.profiles.read_back(saved['name'])
        return saved

    # ---- the machine verbs the Memory and Optimization panes ask for -----------------

    def trim_working_set(self) -> Dict[str, Any]:
        """Hand this process's clean pages back to Windows and keep what it answered."""
        answer = performance_controls.trim_working_set()
        self.last_trim = answer
        return answer

    def collect_garbage(self, trigger: str = 'button') -> Dict[str, Any]:
        """One collection, timed, with the interpreter's own count beside it."""
        return self.garbage.collect_now(trigger)

    def clear_caches(self, clear_software_table: Optional[Callable[[], Any]] = None
                     ) -> Dict[str, Any]:
        """Empty the caches this app really holds, and say which ones those are.

        'Cache Size' on the pane bounds nothing - no structure in this app is measured in
        megabytes - so the only honest reading of a Clear Cache button is the two caches
        that do exist: the adapter sample `PerformanceMonitor` keeps for
        `gpu_cache_seconds`, and the detected-software table the job manager holds. This
        process owns the first; the second is handed in as a callable by whoever holds the
        job manager, because clearing a cache that lives in somebody else's instance is a
        way of emptying the wrong object.
        """
        before = psutil.Process(os.getpid()).memory_info().rss
        samples = len(self.monitor.metrics_history)
        self.monitor.clear_history()
        self.monitor.drop_gpu_cache()
        profiles = len(self.profiler.profiles)
        self.profiler.clear_all()
        if clear_software_table is None:
            software = ('nothing was handed this app\'s job manager, so the '
                        'detected-software table was left alone')
        else:
            try:
                clear_software_table()
            except Exception as failed:
                software = f'the detected-software table was not cleared: ' \
                           f'{type(failed).__name__}: {failed}'
            else:
                software = 'the detected-software table was emptied; the next question ' \
                           'about installed software re-detects it'
        return {'samples_dropped': samples, 'profile_timings_dropped': profiles,
                'adapter_sample_dropped': True, 'software_table': software,
                'rss_before_mb': round(before / 1048576, 1),
                'rss_after_mb': round(
                    psutil.Process(os.getpid()).memory_info().rss / 1048576, 1)}

    def memory_rows(self) -> Dict[str, Any]:
        """Every figure the Memory pane paints, each with the reader that answered it.

        The four cards used to be seeded with 16.0 / 8.5 / 7.5 / 2.3 GB and never
        refreshed. Three of them have a reader; the fourth does not exist on this
        operating system - `psutil.virtual_memory()` on Windows answers total, available,
        percent, used and free and carries no `cached` field at all (measured 2026-11-07),
        so a Cached card can only ever carry the reason it is empty.
        """
        metrics = self.monitor.get_current_metrics()
        rows: Dict[str, Any] = {'machine': [], 'process': [], 'garbage': {},
                                'adapter': [], 'budgets': [], 'last_trim': self.last_trim,
                                'reason': ''}
        try:
            machine = psutil.virtual_memory()
        except Exception as failed:
            rows['reason'] = f'psutil raised {type(failed).__name__}: {failed}'
            machine = None
        if machine is not None:
            for name, value in (('total', machine.total), ('used', machine.used),
                                ('available', machine.available), ('free', machine.free)):
                rows['machine'].append({'card': name, 'value': round(value / 1048576, 1),
                                        'unit': 'MB', 'reader': 'psutil.virtual_memory'})
            rows['machine'].append({'card': 'percent', 'value': machine.percent,
                                    'unit': '%', 'reader': 'psutil.virtual_memory'})
            rows['machine'].append({
                'card': 'cached', 'value': None, 'unit': 'MB', 'reader': None,
                'reason': ('psutil.virtual_memory() answers total, available, percent, used '
                           'and free on Windows and carries no cached field, so no reader '
                           'here can fill this card')})

        process = psutil.Process(os.getpid())
        try:
            info = process.memory_full_info()
        except Exception as failed:
            info = None
            rows['process'] = [{'card': 'this process', 'value': None,
                                'reason': f'psutil raised {type(failed).__name__}: {failed}'}]
        if info is not None:
            for name in ('rss', 'wset', 'peak_wset', 'private', 'pagefile', 'uss'):
                value = getattr(info, name, None)
                if value is None:
                    rows['process'].append(
                        {'card': name, 'value': None,
                         'reason': 'this psutil build did not answer the field'})
                else:
                    rows['process'].append({'card': name, 'value': round(value / 1048576, 1),
                                            'unit': 'MB', 'reader': 'psutil.memory_full_info'})
            rows['process'].append({'card': 'num_page_faults', 'value': info.num_page_faults,
                                    'unit': 'faults', 'reader': 'psutil.memory_full_info'})
            rows['process'].append({'card': 'share of machine',
                                    'value': round(process.memory_percent(), 2),
                                    'unit': '%', 'reader': 'psutil.Process.memory_percent'})

        rows['garbage'] = {'counts': list(gc.get_count()), 'generations': len(gc.get_stats()),
                           'uncollectable': len(gc.garbage),
                           'reader': 'gc.get_count / gc.get_stats / gc.garbage',
                           'passes': self.garbage.summary()}

        adapter_mb = metrics.gpu_memory_used_mb
        rows['adapter'].append(
            {'card': 'adapter memory in use', 'value': adapter_mb, 'unit': 'MB',
             'reader': metrics.gpu_reader if adapter_mb is not None else None,
             'reason': '' if adapter_mb is not None else
                       metrics.not_read.get('gpu_memory_used_mb',
                                            'the adapter reader answered no memory figure')})
        rows['budgets'] = self.detector.budget_notes(metrics)
        return rows

    def benchmark_work_settings(self) -> Dict[str, Any]:
        """The two boxes the storage benchmark reads, straight off the store.

        The engine takes them as arguments rather than reaching for a widget, so a
        benchmark run from anywhere - the Diagnostics pane, a test, this pane - gets the
        same chunking.
        """
        buffer_kb = performance_controls.read_control(
            performance_controls.CONTROLS['buffer_size_spin'])['value']
        mapped = performance_controls.read_control(
            performance_controls.CONTROLS['memory_mapping_cb'])['value']
        return {'buffer_kb': buffer_kb, 'use_memory_map': bool(mapped)}

    def run_benchmark(self, kind: str, duration: float = 2.0, record: bool = False,
                      should_stop=None, progress_callback=None) -> Dict[str, Any]:
        """Time one kind of work with the pane's stored settings handed to the engine."""
        work = self.benchmark_work_settings()
        return self.benchmark.run(kind, duration=duration, record=record,
                                  should_stop=should_stop,
                                  progress_callback=progress_callback, **work)

    def run_all_benchmarks(self, duration: float = 2.0, record: bool = False,
                           should_stop=None, progress_callback=None) -> Dict[str, Any]:
        """Every kind, with the same stored settings a single run would use.

        Without this the Full System Benchmark button would time the storage probe with the
        engine's own chunk size while the Storage button used the number in the box, and the
        two rows in one table would answer two different questions.
        """
        work = self.benchmark_work_settings()
        return self.benchmark.run_all(duration=duration, record=record,
                                      should_stop=should_stop,
                                      progress_callback=progress_callback, **work)

    def export_benchmark_results(self, results: List[Dict[str, Any]],
                                 output_path: Optional[str] = None) -> Dict[str, Any]:
        """Write the table's own cells out - the same words, in a file."""
        return self.benchmark.export(results, output_path)

    def get_current_analysis(self) -> Dict[str, Any]:
        """What one look at the machine supports: figures, findings, score, advice.

        The score and the advice are tied together here on purpose: advice without the
        reading that caused it is what the old version returned, and `not_measured` is
        the list a pane has to show so an empty table is not read as an all-clear.
        """
        metrics = self.monitor.get_current_metrics()
        findings = self.detector.analyze(metrics)
        return {
            'timestamp': metrics.timestamp,
            'metrics': metrics.to_dict(),
            'findings': findings,
            'not_measured': self.detector.not_measured(metrics),
            'budgets': self.detector.budget_notes(metrics),
            'score': self.detector.score(metrics),
            'suggestions': self.suggester.get_suggestions(metrics, findings),
            'frames': self.monitor.clock.stats(),
            'average_metrics': self.monitor.get_average_metrics(),
            'peak_metrics': self.monitor.get_peak_metrics(),
        }

    def get_historical_analysis(self, last_n: int = 300) -> Dict[str, Any]:
        """Trends over the samples kept, counting only the samples that hold a number."""
        history = self.monitor.get_metrics_history(last_n)
        if not history:
            return {'data_points': 0, 'history': [], 'trends': {},
                    'reason': 'no sample has been kept yet, so there is no trend'}
        trends = {}
        for name in ('cpu_percent', 'memory_percent', 'gpu_load_percent', 'fps',
                     'frame_time_ms', 'process_rss_mb', 'gpu_memory_used_mb'):
            values = [getattr(m, name) for m in history if getattr(m, name) is not None]
            if not values:
                trends[name] = {'average': None, 'peak': None, 'current': None,
                                'samples': 0,
                                'reason': history[-1].not_read.get(
                                    name, 'no sample carried this reading')}
                continue
            trends[name] = {
                'average': round(sum(values) / len(values), 2),
                'peak': max(values),
                'current': values[-1],
                'samples': len(values),
                'reason': '',
            }
        return {'data_points': len(history),
                'history': [m.to_dict() for m in history],
                'trends': trends}

    def start_profiling(self, function_name: str) -> None:
        self.profiler.start_profile(function_name)

    def end_profiling(self, function_name: str) -> Optional[float]:
        return self.profiler.end_profile(function_name)

    def get_profiling_results(self) -> List[ProfileResult]:
        return self.profiler.get_all_results()

    def export_performance_report(self, output_path: Optional[str] = None) -> str:
        """Write the current analysis as a report, in the app's own data folder."""
        report = {
            'report_date': _stamp(),
            'analysis': self.get_current_analysis(),
            'historical': self.get_historical_analysis(),
            'profiling': [r.to_dict() for r in self.get_profiling_results()],
        }
        if output_path is None:
            output_path = os.path.join(
                data_dir(),
                f'performance_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, indent=1, default=str)
        return output_path

    def clear_all_data(self) -> None:
        self.monitor.clear_history()
        self.profiler.clear_all()


ENGINE = None


def benchmark_engine() -> BenchmarkRunner:
    """The one benchmark engine in the process.

    The Diagnostics pane and the Performance pane used to keep two engines with two
    ideas of what a benchmark is - one summing square roots, one multiplying matrices -
    and so the same machine was given two different answers two tabs apart. Both panes
    ask for this one.
    """
    global ENGINE
    if ENGINE is None:
        ENGINE = BenchmarkRunner()
    return ENGINE
