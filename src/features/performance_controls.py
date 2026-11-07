"""What every control on the Performance pane is allowed to change, and what it cannot.

The pane used to hold thirty-odd controls and speak to the machine with about eight of them.
`Max Threads` was a 1-64 box defaulting to 8 while the Post-Processing pane held the same
name as a 1-16 box defaulting to 4 and the post-processor read that one; `Apply Profile`
moved three spin boxes and wrote nothing; six buttons had no receiver at all; and the GPU,
cache, memory-pool and precision rows described switches this app never built. Nothing said
which of them did anything, so a user could not tell a setting from a decoration.

This file is the answer to that question, in one table. Every control the pane shows is one
row here, and each row either names the code that reads the value - with the file and the
symbol, so a change here has to be true of that code - or names why nothing in this app can
honour it. A control that is in neither list is a defect, and
`tests/test_performance_backend_contract.py` fails the pane that carries one.

The second half of the file is the machinery those readers need: the profile store, the
Windows priority class, the process core mask, the working-set trim, the stack size Python
answers for a thread, and the garbage-collection pass. Each one reports what the operating
system or the interpreter answered, because a setting that cannot be read back is a wish.
"""

import gc
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import psutil

from PyQt6.QtCore import QObject, QTimer

from ..utils import app_settings

PERFORMANCE = 'Performance'
THREADING_GROUP = 'PostProcessing'

# The three modes the Garbage Collection box offers, as the interval each one runs a
# collection on. `None` is not "never collected": it is "collected when a button is
# pressed", which is the only honest meaning available, so the row says that in words.
GC_INTERVALS: Dict[str, Optional[int]] = {'Automatic': 60000, 'Aggressive': 15000,
                                          'Manual': None}

# Windows' own priority classes, spelled the way the combo box spells them.
PRIORITY_CLASSES = {'Low': 0x00000040, 'Normal': 0x00000020, 'High': 0x00000080}
PRIORITY_NAMES = {value: name for name, value in PRIORITY_CLASSES.items()}
PRIORITY_REFUSALS = {
    'Real-time': 'REALTIME_PRIORITY_CLASS puts this app above the services that keep '
                 'Windows running, so it is not offered here: the app would rather be '
                 'slow than to take the machine'}


@dataclass(frozen=True)
class Control:
    """One row of the table: a widget on the pane and the code that reads it, or the reason.

    `key` is the settings key the value is persisted under, in the same group the code that
    reads it looks in. It is empty for a control whose reader is a call rather than a stored
    value - the profile name box - and for a refused control, which has neither.
    """
    widget: str
    label: str
    kind: str                       # 'spin' | 'combo' | 'check' | 'text'
    group: str = ''
    key: str = ''
    default: Any = None
    bounds: Optional[Tuple[Any, ...]] = None
    variable: bool = False          # a combo whose items come off the machine
    reader: str = ''
    refusal: str = ''

    @property
    def wired(self) -> bool:
        """Whether something in this app reads what this control changes."""
        return bool(self.reader)

    @property
    def qualified(self) -> str:
        return f'{self.group}/{self.key}' if self.key else ''

    @property
    def settings_type(self):
        """The type the store is asked to answer in, so an ini file does not hand back '16'."""
        return {'spin': int, 'check': bool}.get(self.kind, str)

    def in_bounds(self, value) -> Tuple[bool, str]:
        """Whether the control offers this value, in the control's own words."""
        if self.bounds is None or self.variable or value is None:
            return True, ''
        if self.kind == 'spin':
            low, high = self.bounds
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False, f'{value!r} is not a number'
            return (True, '') if low <= value <= high else (
                False, f'{value} is outside the {low} to {high} this control offers')
        if self.kind == 'combo':
            return (True, '') if value in self.bounds else (
                False, f'{value!r} is not one of {", ".join(map(str, self.bounds))}')
        return True, ''


@dataclass(frozen=True)
class Verb:
    """A button on the pane, the method that answers it, and the artefact it produces.

    Kept beside the controls because the defect is the same: a button with no receiver looks
    exactly like a button with one.
    """
    widget: str
    label: str
    method: str
    produces: str


CONTROLS: Dict[str, Control] = {
    # ---- GPU Acceleration -------------------------------------------------------------
    'enable_gpu_cb': Control(
        'enable_gpu_cb', 'Enable GPU Acceleration', 'check', PERFORMANCE,
        'ask_adapter_every_sample', False,
        reader='PerformanceAnalyzer.set_adapter_reader() hands PerformanceMonitor the '
               'adapter reader (SystemInfo.live_gpu_sample), so every sample carries load, '
               'memory and temperature instead of only the Detect button answer'),
    'gpu_device_combo': Control(
        'gpu_device_combo', 'GPU Device', 'combo', PERFORMANCE, 'adapter_to_report',
        'Auto Select', variable=True,
        reader='SystemInfo.live_gpu_sample(adapter_name=...) reports the figures of the '
               'adapter this names; the items are the ones Windows listed when Detect ran, '
               'and a name it does not recognise answers with a sentence naming both lists'),
    'gpu_memory_spin': Control(
        'gpu_memory_spin', 'Memory Allocation', 'spin', PERFORMANCE,
        'adapter_memory_alert_mb', 4096, (512, 24576),
        reader='BottleneckDetector compares the adapter memory the reader answered with '
               'against this figure and produces the Adapter memory finding'),
    'compute_capability_combo': Control('compute_capability_combo', 'Compute API', 'combo'),
    'precision_combo': Control('precision_combo', 'Precision', 'combo'),
    'gpu_rendering_cb': Control('gpu_rendering_cb', 'GPU Rendering', 'check'),
    'gpu_denoising_cb': Control('gpu_denoising_cb', 'GPU Image Denoising', 'check'),
    'gpu_mesh_processing_cb': Control('gpu_mesh_processing_cb', 'GPU Mesh Processing', 'check'),
    'gpu_format_conversion_cb': Control('gpu_format_conversion_cb', 'GPU Format Conversion',
                                        'check'),
    'gpu_lod_generation_cb': Control('gpu_lod_generation_cb', 'GPU LOD Generation', 'check'),

    # ---- Optimization: profiles and threading ----------------------------------------
    'profile_combo': Control(
        'profile_combo', 'Profile', 'combo', PERFORMANCE, 'applied_profile', 'Balanced',
        variable=True,
        reader='PerformanceProfiles.names() lists the built-in profiles and the custom ones '
               'stored in profiles.json, and PerformanceProfiles.apply() writes the knobs the '
               'chosen profile names'),
    'profile_name_edit': Control(
        'profile_name_edit', 'Custom profile name', 'text',
        reader='PerformanceProfiles.save() takes this as the name it stores the values on '
               'screen under; the saved name appears in the list above next time it is read'),
    'max_threads_spin': Control(
        'max_threads_spin', 'Max Threads', 'spin', THREADING_GROUP, 'max_threads', 4, (1, 16),
        reader='src/processing/postprocessor.py `_denoise_files` and `_watermark_files` hand '
               'this number to ThreadPoolExecutor(max_workers=...); the Post-Processing pane '
               'reads and writes the same key, so the two boxes are one setting'),
    'thread_priority_combo': Control(
        'thread_priority_combo', 'Thread Priority', 'combo', PERFORMANCE, 'process_priority',
        'Normal', ('Low', 'Normal', 'High', 'Real-time'),
        reader='set_process_priority() sets this process Windows priority class and '
               'GetPriorityClass reads it back; the row beside the box is that read-back'),
    'multiprocessing_cb': Control(
        'multiprocessing_cb', 'Enable Multiprocessing', 'check'),
    'affinity_cb': Control(
        'affinity_cb', 'Set CPU Affinity', 'check', PERFORMANCE, 'pin_to_first_cores', False,
        reader='apply_cpu_affinity() asks Windows to run this process on the first Max Threads '
               'logical processors and reports the list it answers with; unchecked it asks for '
               'every processor the machine has'),

    # ---- Optimization: memory ---------------------------------------------------------
    'memory_limit_spin': Control(
        'memory_limit_spin', 'Memory Limit', 'spin', PERFORMANCE, 'process_memory_budget_mb',
        8192, (512, 32768),
        reader='BottleneckDetector compares the resident size this process reports against '
               'this figure and produces the Process memory finding'),
    'garbage_collection_combo': Control(
        'garbage_collection_combo', 'Garbage Collection', 'combo', PERFORMANCE, 'gc_mode',
        'Automatic', ('Automatic', 'Manual', 'Aggressive'),
        reader='GarbageCollectionRunner calls gc.collect() on the interval this mode picks - '
               'Automatic every 60 s, Aggressive every 15 s, Manual only when a button asks - '
               'and keeps what each pass answered'),
    'memory_mapping_cb': Control(
        'memory_mapping_cb', 'Use Memory Mapping', 'check', PERFORMANCE,
        'storage_read_with_memory_map', True,
        reader='BenchmarkRunner.storage_benchmark reads its probe file back through a memory '
               'map while this is on and with a plain read while it is off, and the row says '
               'which verb answered'),
    'swap_usage_cb': Control('swap_usage_cb', 'Allow Swap Usage', 'check'),

    # ---- Optimization: cache ----------------------------------------------------------
    'cache_size_spin': Control('cache_size_spin', 'Cache Size', 'spin'),
    'cache_policy_combo': Control('cache_policy_combo', 'Cache Policy', 'combo'),
    'preload_cache_cb': Control('preload_cache_cb', 'Preload Common Assets', 'check'),
    'compress_cache_cb': Control('compress_cache_cb', 'Compress Cache Data', 'check'),

    # ---- Optimization: I/O ------------------------------------------------------------
    'buffer_size_spin': Control(
        'buffer_size_spin', 'Buffer Size', 'spin', PERFORMANCE, 'storage_probe_buffer_kb', 64,
        (4, 1024),
        reader='BenchmarkRunner.storage_benchmark writes and reads its probe file in chunks '
               'of this size and the row counts the writes it made'),
    'async_io_cb': Control('async_io_cb', 'Enable Async I/O', 'check'),
    'batch_operations_cb': Control('batch_operations_cb', 'Batch File Operations', 'check'),

    # ---- Memory allocation ------------------------------------------------------------
    'heap_size_spin': Control('heap_size_spin', 'Heap Size', 'spin'),
    'stack_size_spin': Control(
        'stack_size_spin', 'Stack Size', 'spin', PERFORMANCE, 'thread_stack_size_mb', 8,
        (1, 64),
        reader='apply_stack_size() asks Python for this per-thread stack and reports the bytes '
               'threading.stack_size() answers; a thread already started keeps the stack it '
               'was given'),
    'pool_size_spin': Control('pool_size_spin', 'Memory Pool', 'spin'),
}

# The sentences the refused rows carry. They are written here rather than in the pane so the
# refusal is a claim about this codebase, and a claim about this codebase has to be true of
# this codebase in one place.
REFUSALS = {
    'compute_capability_combo':
        'the only adapter work this app does is the OpenGL context the 3D view asks Qt for; '
        'no CUDA, OpenCL or Vulkan kernel is compiled here, so there is no API for this box '
        'to choose',
    'precision_combo':
        'FP32, FP16 and INT8 describe arithmetic on the adapter, and this app performs none: '
        'its arithmetic is numpy float64 on the CPU',
    'gpu_rendering_cb':
        'the 3D view is a QOpenGLWidget and Qt picks the adapter its context lands on; this '
        'app has no switch to hand it, so the box changes nothing',
    'gpu_denoising_cb':
        'denoising runs through ImageDenoiser in src/processing/postprocessor.py, whose '
        'OpenCV filters are CPU calls; its OpenImageDenoise path asks oidn.Device() for a '
        'device and this app does not choose it',
    'gpu_mesh_processing_cb':
        'the mesh operations are trimesh and pymeshlab calls in src/processing/mesh_processor.py, '
        'which run on the CPU',
    'gpu_format_conversion_cb':
        'format conversion is pyassimp and trimesh in src/processing/format_converter.py, '
        'which run on the CPU',
    'gpu_lod_generation_cb':
        'the LOD levels are the simplification routes in src/processing/lod_generator.py '
        '(_quadric_simplify, _hybrid_simplify, _cluster_simplify), which run on the CPU',
    'multiprocessing_cb':
        "this app's parallel work is ThreadPoolExecutor in the post-processor and QThreadPool "
        'for the panes readers, which are threads; it starts no processes, so there is no '
        'multiprocessing for this to enable',
    'swap_usage_cb':
        'what Windows pages out is the memory managers decision for the whole machine, and a '
        'single process cannot allow or forbid it',
    'cache_size_spin':
        'the app keeps two caches and neither is measured in megabytes: the adapter sample '
        'PerformanceMonitor holds for gpu_cache_seconds, and the detected-software table in '
        'src/core/job_manager.py. A size limit has nothing to bound',
    'cache_policy_combo':
        'the two caches this app keeps hold one value each and are replaced or rebuilt whole '
        '(SystemInfo.live_gpu_sample, refresh_software_cache), so there is no eviction order '
        'for LRU, LFU, FIFO or Random to choose',
    'preload_cache_cb':
        'thumbnails are generated when a folder is opened and a model is read when it is '
        'asked for; nothing in this app preloads a set of assets ahead of that',
    'compress_cache_cb':
        'the reports, logs and benchmark history this app writes are plain JSON so a reader '
        'can open them without the app, and nothing it caches is compressed',
    'async_io_cb':
        'every timed or machine-asking run in this pane already leaves the thread that paints, '
        'through Worker and QThreadPool; there is no synchronous path left for this to make '
        'asynchronous',
    'batch_operations_cb':
        'file operations go through the job queue in src/core/job_manager.py, which batches by '
        'design; no code path in this app reads a batching switch',
    'heap_size_spin':
        'the heap belongs to Windows and to CPythons allocator, neither of which takes a cap '
        'from Python code at runtime; the ceiling this app does compare itself against is the '
        'Memory Limit in the Optimization tab',
    'pool_size_spin':
        "the app's workers run on QThreadPool, whose size is a thread count, and nothing here "
        'allocates a fixed memory pool for this box to size',
}

for _name, _sentence in REFUSALS.items():
    CONTROLS[_name] = replace(CONTROLS[_name], refusal=_sentence)

VERBS: Dict[str, Verb] = {
    'detect_gpu_btn': Verb(
        'detect_gpu_btn', 'Detect GPU Hardware', 'detect_gpu_hardware',
        'SystemInfo.get_gpu_report() on a worker: the adapter text, the four status rows, '
        'and the device list the GPU Device box is filled from'),
    'benchmark_cpu_btn': Verb(
        'benchmark_cpu_btn', 'CPU Benchmark', 'run_cpu_benchmark',
        'a row of matrix multiplies per second, measured, on the machine note'),
    'benchmark_geometry_btn': Verb(
        'benchmark_geometry_btn', 'Geometry Benchmark', 'run_geometry_benchmark',
        'a row of point-cloud normal rounds per second and the device that ran them'),
    'benchmark_memory_btn': Verb(
        'benchmark_memory_btn', 'Memory Benchmark', 'run_memory_benchmark',
        'a row of megabytes moved per second and what this process grew by'),
    'benchmark_storage_btn': Verb(
        'benchmark_storage_btn', 'Storage Benchmark', 'run_storage_benchmark',
        'a row of write and read throughput for the volume the app writes to'),
    'benchmark_full_btn': Verb(
        'benchmark_full_btn', 'Full System Benchmark', 'run_full_benchmark',
        'every kind the engine performs, each with its answer or its refusal'),
    'export_results_btn': Verb(
        'export_results_btn', 'Export Results', 'export_results',
        'a JSON file in the app data folder holding these rows, the stored runs and the '
        'machine note, which the pane reads back and counts'),
    'clear_results_btn': Verb(
        'clear_results_btn', 'Clear Results', 'clear_results',
        'an empty table, plus the number of runs on disk it deliberately did not touch'),
    'apply_profile_btn': Verb(
        'apply_profile_btn', 'Apply Profile', 'apply_performance_profile',
        'the settings the profile names, written and read back, and the knobs it could not '
        'write named one by one'),
    'save_profile_btn': Verb(
        'save_profile_btn', 'Save Custom Profile', 'save_performance_profile',
        'a profile file the list above is read from, or the reason the name or a value was '
        'refused'),
    'refresh_analysis_btn': Verb(
        'refresh_analysis_btn', 'Analyse This Sample', 'refresh_analysis',
        'get_current_analysis() on a worker: figures, findings, the score with the basis it '
        'was computed from, the advice with the control to change, and what was not measured'),
    'export_report_btn': Verb(
        'export_report_btn', 'Export Analysis Report', 'export_analysis_report',
        'export_performance_report(): the analysis, the trend over the samples kept and the '
        'profiled timings, as a file the pane names and reads back'),
    'clear_cache_btn': Verb(
        'clear_cache_btn', 'Clear Cache', 'clear_memory_cache',
        'the resident size measured before and after a collection and a cleared history'),
    'force_gc_btn': Verb(
        'force_gc_btn', 'Force Garbage Collection', 'force_garbage_collection',
        "gc.collect()'s own answer: how many objects it found unreachable and how long it took"),
    'trim_memory_btn': Verb(
        'trim_memory_btn', 'Trim Working Set', 'trim_working_set',
        'the resident size Windows reports before and after K32EmptyWorkingSet, and what the '
        'call answered'),
    'analyze_memory_btn': Verb(
        'analyze_memory_btn', 'Analyze Memory Usage', 'analyze_memory_usage',
        'the rows the engine words from psutil, gc and the samples kept'),
}


def control(widget: str) -> Optional[Control]:
    """The table row for one widget name, or None when the table does not speak for it."""
    return CONTROLS.get(widget)


def uncovered(widgets) -> List[str]:
    """The controls on screen that the table says nothing about - the defect this exists for."""
    return [name for name in widgets if name not in CONTROLS and name not in VERBS]


def sentence_for(item: Control) -> str:
    """What the pane prints beside a control: the reader it has, or the reason it does not."""
    return item.reader if item.wired else item.refusal


def read_control(item: Control) -> Dict[str, Any]:
    """The value the store holds for one control, or its default, with the bounds verdict.

    A stored value the control does not offer is reported, not clamped: the pane shows the
    number that is really in the store beside the range that store was written by, because a
    silently corrected setting is a setting nobody chose.
    """
    row: Dict[str, Any] = {'widget': item.widget, 'key': item.qualified,
                           'stored': False, 'value': item.default, 'note': '',
                           'wired': item.wired}
    if not item.key:
        row['note'] = sentence_for(item)
        return row
    raw = app_settings.read(item.group, item.key, None)
    if raw is None:
        row['note'] = ('nothing has written this key yet, so the default above is what '
                       'the reader gets')
        return row
    try:
        value = item.settings_type(raw)
    except (TypeError, ValueError):
        row['note'] = f'the store holds {raw!r}, which is not a {item.kind} value'
        return row
    row['stored'] = True
    row['value'] = value
    fits, why = item.in_bounds(value)
    if not fits:
        row['note'] = why
    return row


def write_control(item: Control, value) -> Dict[str, Any]:
    """Persist one control value and read it back, or refuse to write it.

    The read-back is the claim: `sync()` is what makes the value visible to the other
    QSettings readers in this process, and comparing the stored answer with the value asked
    for is the only way to know the store did not coerce it into something else.
    """
    if not item.key:
        return {'written': False, 'widget': item.widget,
                'reason': sentence_for(item) or 'this control changes no stored setting'}
    if not item.wired:
        return {'written': False, 'widget': item.widget, 'reason': item.refusal}
    fits, why = item.in_bounds(value)
    if not fits:
        return {'written': False, 'widget': item.widget, 'value': value, 'reason': why}
    app_settings.write(item.group, item.key, value)
    read_back = app_settings.read(item.group, item.key, None, item.settings_type)
    if read_back != value:
        return {'written': True, 'widget': item.widget, 'value': value,
                'read_back': read_back,
                'reason': f'the store answered {read_back!r} after being given {value!r}'}
    return {'written': True, 'widget': item.widget, 'key': item.qualified, 'value': value,
            'read_back': read_back, 'reason': ''}


class PerformanceProfiles:
    """The named knob sets, and the ones the user saved, read off one file.

    A profile is a set of this app's own settings. It is not a claim about the machine: it
    cannot make the adapter faster, and applying it says which knobs it wrote, which it
    refused because the control they belong to reads nothing, and which it refused because
    the value the file holds is outside the range the reader offers.
    """

    BUILT_IN: Dict[str, Dict[str, Any]] = {
        'Balanced': {'max_threads_spin': 4, 'memory_limit_spin': 8192,
                     'gpu_memory_spin': 4096, 'buffer_size_spin': 64,
                     'garbage_collection_combo': 'Automatic',
                     'thread_priority_combo': 'Normal', 'memory_mapping_cb': True,
                     'affinity_cb': False},
        'Performance': {'max_threads_spin': 16, 'memory_limit_spin': 16384,
                        'gpu_memory_spin': 8192, 'buffer_size_spin': 256,
                        'garbage_collection_combo': 'Manual',
                        'thread_priority_combo': 'High', 'memory_mapping_cb': True,
                        'affinity_cb': False},
        'Quality': {'max_threads_spin': 8, 'memory_limit_spin': 12288,
                    'gpu_memory_spin': 8192, 'buffer_size_spin': 128,
                    'garbage_collection_combo': 'Automatic',
                    'thread_priority_combo': 'Normal', 'memory_mapping_cb': True,
                    'affinity_cb': False},
        'Power Saving': {'max_threads_spin': 2, 'memory_limit_spin': 4096,
                         'gpu_memory_spin': 2048, 'buffer_size_spin': 32,
                         'garbage_collection_combo': 'Aggressive',
                         'thread_priority_combo': 'Low', 'memory_mapping_cb': False,
                         'affinity_cb': True},
    }

    NAME_LIMIT = 64

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.path.join(self._data_dir(), 'profiles.json')

    @staticmethod
    def _data_dir() -> str:
        """The folder `performance_analyzer.data_dir()` names, reached without a cycle.

        The analyzer imports this module, so importing back from it at load time would be a
        circle; the folder is read when a profile is actually stored.
        """
        from .performance_analyzer import data_dir
        return data_dir()

    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {'custom': {}, 'reason': ''}
        try:
            with open(self.path, encoding='utf-8') as handle:
                loaded = json.load(handle)
        except (OSError, ValueError) as failed:
            return {'custom': {},
                    'reason': f'the stored profiles could not be read '
                              f'({type(failed).__name__}: {failed}); the file was left on '
                              f'disk untouched'}
        custom = loaded.get('custom') if isinstance(loaded, dict) else None
        if not isinstance(custom, dict):
            return {'custom': {}, 'reason': 'the stored profile file is not a profile list; '
                                            'it was left on disk untouched'}
        return {'custom': custom, 'reason': ''}

    def names(self) -> List[str]:
        """Built-in names first, then the custom ones the file holds - the pane lists off here."""
        return list(self.BUILT_IN) + [name for name in self._read()['custom']
                                      if name not in self.BUILT_IN]

    def load_reason(self) -> str:
        return self._read()['reason']

    def knobs(self, name: str) -> Dict[str, Any]:
        """The widget values one profile stands for, or an empty dict for an unknown name."""
        if name in self.BUILT_IN:
            return dict(self.BUILT_IN[name])
        entry = self._read()['custom'].get(name)
        values = entry.get('knobs') if isinstance(entry, dict) else None
        return dict(values) if isinstance(values, dict) else {}

    def live_knob_names(self) -> List[str]:
        """Every knob a profile is allowed to name: the controls with a reader and a key.

        The refused controls are left out on purpose. A profile that could set them would be
        a way to write a number nothing reads, which is the defect this table exists to end.
        """
        return [item.widget for item in CONTROLS.values() if item.wired and item.key]

    def apply(self, name: str, live_values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Write the knobs this profile names and report every knob it could not write.

        `live_values` is what the pane holds on screen. It is only consulted for the profile
        called Custom, which means "the settings I have on screen are the profile": there is
        nothing to write, because each control writes its own value as it changes, and the
        answer says that instead of pretending to apply a set.
        """
        outcome: Dict[str, Any] = {'profile': name, 'known': False, 'written': [],
                                   'refused': [], 'reason': ''}
        if name == 'Custom':
            outcome['known'] = True
            outcome['reason'] = ('Custom is the set of values on screen, and each control '
                                 'writes its own as you change it, so there was nothing to '
                                 'apply - press Save Custom Profile to store these values '
                                 'under a name')
            return outcome
        knobs = self.knobs(name)
        if not knobs:
            outcome['reason'] = (f'"{name}" is not a profile this engine holds; it knows '
                                 f'{", ".join(self.names())}')
            return outcome
        outcome['known'] = True
        for widget, value in knobs.items():
            item = CONTROLS.get(widget)
            if item is None:
                outcome['refused'].append(f'{widget}: no control of this name is on the pane')
                continue
            if not item.wired or not item.key:
                outcome['refused'].append(f'{item.label} ({widget}): {sentence_for(item)}')
                continue
            wrote = write_control(item, value)
            if wrote.get('written'):
                outcome['written'].append({'widget': widget, 'label': item.label,
                                           'key': item.qualified, 'value': value,
                                           'read_back': wrote['read_back'],
                                           'reader': item.reader})
            else:
                outcome['refused'].append(f'{item.label} ({widget}): {wrote["reason"]}')
        if not outcome['written']:
            outcome['reason'] = 'this profile named no knob this app can write'
        return outcome

    def save(self, name: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """Store the given control values under `name`, atomically, or refuse the name."""
        cleaned = (name or '').strip()
        if not cleaned:
            return {'saved': False,
                    'reason': 'a profile needs a name, and the name box is empty'}
        if len(cleaned) > self.NAME_LIMIT:
            return {'saved': False,
                    'reason': f'"{cleaned[:20]}..." is {len(cleaned)} characters; a profile '
                              f'name is kept to {self.NAME_LIMIT}'}
        if cleaned in self.BUILT_IN:
            return {'saved': False,
                    'reason': f'"{cleaned}" is a built-in profile; saving would hide the '
                              f'values this app ships for it, so choose another name'}
        if not re.fullmatch(r'[\w \-+.]+', cleaned, re.UNICODE):
            return {'saved': False,
                    'reason': 'a profile name holds letters, digits, spaces, dash, plus, dot '
                              'or underscore; the name you gave would not survive as a key'}
        stored = self._read()
        knobs: Dict[str, Any] = {}
        refused: List[str] = []
        for widget, value in values.items():
            item = CONTROLS.get(widget)
            if item is None:
                refused.append(f'{widget}: no control of this name is on the pane')
                continue
            if not item.wired or not item.key:
                refused.append(f'{item.label} ({widget}): nothing in this app reads it, so '
                               f'it is not a profile knob')
                continue
            fits, why = item.in_bounds(value)
            if not fits:
                refused.append(f'{item.label} ({widget}): {why}')
                continue
            knobs[widget] = value
        if not knobs:
            return {'saved': False, 'reason': 'the pane handed no value this app can store',
                    'refused': refused}
        custom = dict(stored['custom'])
        custom[cleaned] = {'knobs': knobs, 'saved_at': datetime.now().isoformat(
            timespec='seconds')}
        temp = f'{self.path}.writing'
        try:
            folder = os.path.dirname(self.path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(temp, 'w', encoding='utf-8') as handle:
                json.dump({'custom': custom}, handle, indent=1)
            os.replace(temp, self.path)
        except OSError as failed:
            try:
                os.remove(temp)
            except OSError:
                pass
            return {'saved': False,
                    'reason': f'the profile was named and refused by the disk: '
                              f'{type(failed).__name__}: {failed}',
                    'refused': refused}
        return {'saved': True, 'name': cleaned, 'path': self.path, 'knobs': knobs,
                'refused': refused,
                'reason': stored['reason'] or ''}

    def read_back(self, name: str) -> Dict[str, Any]:
        """Proof that a save happened: the file's own entry for that name."""
        entry = self._read()['custom'].get(name)
        return {'found': isinstance(entry, dict), 'entry': entry or {},
                'reason': '' if isinstance(entry, dict) else
                          f'"{name}" is not in {self.path}'}


# ---- the machine itself: priority, cores, working set, stack ---------------------------

def _kernel32():
    """The loaded `kernel32`, with the signatures these calls need.

    The types are not decoration. `GetCurrentProcess()` hands back the pseudohandle
    `-1`, and without `restype` ctypes truncates it to 32 bits, so every call made with it
    fails with `ERROR_INVALID_HANDLE` - measured here: `GetPriorityClass` answered 0 and
    `K32EmptyWorkingSet` answered 0 with error 6 until the signatures were set, and then
    both answered with the truth.
    """
    if sys.platform != 'win32':
        return None
    import ctypes
    from ctypes import wintypes
    library = ctypes.windll.kernel32
    library.GetCurrentProcess.restype = wintypes.HANDLE
    library.GetPriorityClass.restype = wintypes.DWORD
    library.GetPriorityClass.argtypes = [wintypes.HANDLE]
    library.SetPriorityClass.restype = wintypes.BOOL
    library.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    library.GetLastError.restype = wintypes.DWORD
    empty = getattr(library, 'K32EmptyWorkingSet', None)
    if empty is not None:
        empty.restype = wintypes.BOOL
        empty.argtypes = [wintypes.HANDLE]
    return library


def priority_now() -> Dict[str, Any]:
    """What Windows says this process's priority class is right now."""
    library = _kernel32()
    if library is None:
        return {'read': False, 'name': None, 'raw': None,
                'reason': 'this reader asks Windows, and the process is not on Windows'}
    raw = int(library.GetPriorityClass(library.GetCurrentProcess()))
    if raw == 0:
        return {'read': False, 'name': None, 'raw': None,
                'reason': f'GetPriorityClass failed (last error '
                          f'{library.GetLastError()})'}
    return {'read': True, 'name': PRIORITY_NAMES.get(raw), 'raw': raw,
            'reason': '' if raw in PRIORITY_NAMES else
                      'the class Windows reports is not one this app offers'}


def set_process_priority(name: str) -> Dict[str, Any]:
    """Set the priority class and return what Windows then reports, not what was asked."""
    asked = {'asked_for': name}
    if name in PRIORITY_REFUSALS:
        return {**asked, 'set': False, 'reported': None,
                'reason': PRIORITY_REFUSALS[name]}
    if name not in PRIORITY_CLASSES:
        return {**asked, 'set': False, 'reported': None,
                'reason': f'"{name}" is not a priority this app knows; it offers '
                          f'{", ".join(list(PRIORITY_CLASSES) + list(PRIORITY_REFUSALS))}'}
    library = _kernel32()
    if library is None:
        return {**asked, 'set': False, 'reported': None,
                'reason': 'this reader sets the priority through Windows, and the process is '
                          'not on Windows'}
    ok = bool(library.SetPriorityClass(library.GetCurrentProcess(), PRIORITY_CLASSES[name]))
    seen = priority_now()
    if not ok:
        return {**asked, 'set': False, 'reported': seen['name'],
                'reason': f'SetPriorityClass failed (last error {library.GetLastError()}); '
                          f'Windows still reports {seen["name"] or seen["raw"]}'}
    return {**asked, 'set': True, 'reported': seen['name'],
            'reported_raw': seen['raw'],
            'reason': seen['reason'] if seen['read'] else
                      'the class was set but Windows would not report it back'}


def cpu_affinity_now() -> Dict[str, Any]:
    """The logical processors Windows will run this process on, as psutil reads them."""
    process = psutil.Process(os.getpid())
    getter = getattr(process, 'cpu_affinity', None)
    if getter is None:
        return {'read': False, 'cores': [], 'logical': psutil.cpu_count(logical=True),
                'reason': 'this platform does not let a process ask which cores it runs on'}
    try:
        cores = list(getter())
    except Exception as failed:
        return {'read': False, 'cores': [], 'logical': psutil.cpu_count(logical=True),
                'reason': f'psutil raised {type(failed).__name__}: {failed}'}
    return {'read': True, 'cores': cores, 'logical': psutil.cpu_count(logical=True),
            'reason': ''}


def apply_cpu_affinity(pin: bool, threads: Optional[int] = None) -> Dict[str, Any]:
    """Pin this process to the first N logical cores, or hand every core back.

    N comes from the app's own thread count, because that is the sentence the pane puts the
    box beside: cores chosen so the worker threads have one each, not cores chosen for a
    reason the user cannot see.
    """
    before = cpu_affinity_now()
    if not before['read']:
        return {'attempted': False, 'pinned': pin, 'asked_for': [],
                'reported': before['cores'], 'reason': before['reason']}
    logical = before['logical'] or len(before['cores']) or 1
    if pin:
        count = int(threads) if threads else logical
        wanted = list(range(min(max(1, count), logical)))
    else:
        wanted = list(range(logical))
    process = psutil.Process(os.getpid())
    try:
        process.cpu_affinity(wanted)
    except Exception as failed:
        return {'attempted': True, 'pinned': pin, 'asked_for': wanted,
                'reported': before['cores'],
                'reason': f'Windows refused the core list: {type(failed).__name__}: '
                          f'{failed}'}
    after = cpu_affinity_now()
    return {'attempted': True, 'pinned': pin, 'asked_for': wanted,
            'reported': after['cores'], 'reported_count': len(after['cores']),
            'logical': logical,
            'reason': ('' if after['cores'] == wanted else
                       f'Windows answered {after["cores"]} for the list {wanted}')}


def trim_working_set() -> Dict[str, Any]:
    """Ask Windows to page this process's working set out, and measure what it said.

    `K32EmptyWorkingSet` is the verb Task Manager's End task neighbours use; it does not
    free anything, it makes the pages evictable and lets the manager take them back. The
    figures are the resident size on either side of the call, so a trim that Windows
    declined to do is visible as one, rather than as a promise kept.
    """
    process = psutil.Process(os.getpid())
    try:
        before = process.memory_info().rss
    except Exception as failed:
        return {'attempted': False, 'trimmed': False,
                'reason': f'this process resident size could not be read: '
                          f'{type(failed).__name__}: {failed}'}
    library = _kernel32()
    if library is None:
        return {'attempted': False, 'trimmed': False,
                'rss_before_mb': round(before / 1048576, 1),
                'reason': 'this app trims the working set through Windows, and the process is '
                          'not on Windows'}
    empty = getattr(library, 'K32EmptyWorkingSet', None)
    if empty is None:
        return {'attempted': False, 'trimmed': False,
                'rss_before_mb': round(before / 1048576, 1),
                'reason': 'kernel32 has no K32EmptyWorkingSet on this version of Windows'}
    ok = bool(empty(library.GetCurrentProcess()))
    try:
        after = process.memory_info().rss
    except Exception as failed:
        return {'attempted': True, 'trimmed': ok, 'rss_before_mb': round(before / 1048576, 1),
                'reason': f'the call ran but the size after it could not be read: '
                          f'{type(failed).__name__}: {failed}'}
    return {'attempted': True, 'trimmed': ok,
            'rss_before_mb': round(before / 1048576, 1),
            'rss_after_mb': round(after / 1048576, 1),
            'freed_mb': round((before - after) / 1048576, 1),
            'how': 'K32EmptyWorkingSet(GetCurrentProcess())',
            'reason': ('' if ok else
                       f'K32EmptyWorkingSet failed (last error {library.GetLastError()})')}


def apply_stack_size(megabytes) -> Dict[str, Any]:
    """Ask Python for this stack size on the threads it starts from now on.

    One read, taken immediately after the call, is the whole report. Measured here:
    `threading.stack_size(4194304)` is accepted and the next read in the same thread answers
    4194304, but a read taken after a thread has been started answers 0 - so a second read
    would either be a lie or a zero, and neither belongs beside a figure. A thread that is
    already running keeps the stack it was started with; this changes the next one.
    """
    try:
        wanted = int(float(megabytes) * 1024 * 1024)
    except (TypeError, ValueError):
        return {'set': False, 'requested_mb': megabytes, 'reported_bytes': None,
                'reason': f'{megabytes!r} is not a size in megabytes'}
    if wanted <= 0:
        return {'set': False, 'requested_mb': megabytes,
                'reported_bytes': None,
                'reason': f'{megabytes} MB is {wanted} bytes, and no thread can be started '
                          f'with that stack'}
    try:
        threading.stack_size(wanted)
    except (ValueError, RuntimeError) as failed:
        return {'set': False, 'requested_mb': megabytes,
                'reported_bytes': None,
                'reason': f'Python refused the stack size: {failed}'}
    reported = threading.stack_size()
    return {'set': True, 'requested_mb': megabytes,
            'reported_bytes': reported,
            'reported_mb': round(reported / 1048576, 2) if reported else None,
            'reason': ''}


class GarbageCollectionRunner(QObject):
    """When this app asks Python to collect, and what each collection answered.

    The mode box used to sit above a sentence in the UI and nothing else. Here it picks the
    interval a real `gc.collect()` runs on, and every pass keeps what the call returned -
    the number of unreachable objects - and how long it took, so the pane can say which
    collections happened rather than that collection is aggressive.

    A thread that is running a benchmark keeps its objects; a pass never touches another
    thread's frames, so the passes stay the app's own pauses and the timings stay honest.
    """

    def __init__(self, mode: str = 'Automatic', profiler=None,
                 history_limit: int = 200) -> None:
        super().__init__()
        self.profiler = profiler
        self.passes: List[Dict[str, Any]] = []
        self.history_limit = history_limit
        self.timer = QTimer()
        self.timer.timeout.connect(self.collect_now)
        self.mode = ''
        self.running = False
        self.set_mode(mode)

    def start(self) -> Dict[str, Any]:
        """Run the timer this mode names, if the mode names one.

        Construction never starts it: a `QTimer` started before a window exists is a timer
        nobody can stop, and the analyzer is built on a thread that may have no event loop.
        """
        self.running = True
        return self.set_mode(self.mode)

    def set_mode(self, mode: str) -> Dict[str, Any]:
        """Move to one of the three modes and answer with the interval it means."""
        if mode not in GC_INTERVALS:
            return {'mode': self.mode, 'changed': False,
                    'reason': f'"{mode}" is not a mode this runner has; it knows '
                              f'{", ".join(GC_INTERVALS)}'}
        interval = GC_INTERVALS[mode]
        self.timer.stop()
        if interval and self.running:
            self.timer.start(interval)
        self.mode = mode
        return {'mode': mode, 'changed': True, 'interval_ms': interval,
                'running': self.timer.isActive(),
                'started': self.running,
                'reason': ('' if interval and self.running else
                           ('no timer runs in this mode: gc.collect() is called only when '
                            'the Clear Cache or Force Garbage Collection button is pressed'
                            if not interval else
                            'this mode has an interval but the runner was not started'))}

    def collect_now(self, trigger: str = 'timer') -> Dict[str, Any]:
        """One collection, timed, with the interpreter's own answer kept beside it."""
        if self.profiler is not None:
            self.profiler.start_profile('gc.collect')
        started = time.perf_counter()
        try:
            unreachable = gc.collect()
            error = ''
        except Exception as failed:  # pragma: no cover - gc does not raise in practice
            unreachable = None
            error = f'{type(failed).__name__}: {failed}'
        seconds = time.perf_counter() - started
        if self.profiler is not None:
            self.profiler.end_profile('gc.collect')
        row = {'at': datetime.now().isoformat(timespec='seconds'), 'trigger': trigger,
               'unreachable': unreachable, 'seconds': round(seconds, 4), 'error': error}
        self.passes.append(row)
        if len(self.passes) > self.history_limit:
            del self.passes[:len(self.passes) - self.history_limit]
        return row

    def summary(self) -> Dict[str, Any]:
        """What the passes add up to, counted over the passes that answered.

        `running` is what the pane asked for and `timer_active` is what the timer says, and
        both are reported because in Manual mode they are meant to differ.
        """
        counted = [row for row in self.passes if row['unreachable'] is not None]
        return {'mode': self.mode, 'interval_ms': GC_INTERVALS.get(self.mode),
                'running': self.running, 'timer_active': self.timer.isActive(),
                'passes': len(self.passes),
                'answered': len(counted),
                'total_unreachable': sum(row['unreachable'] for row in counted),
                'total_seconds': round(sum(row['seconds'] for row in counted), 4),
                'last': self.passes[-1] if self.passes else None,
                'reason': '' if self.passes else 'no collection has run in this mode yet'}

    def stop(self) -> None:
        self.running = False
        self.timer.stop()
