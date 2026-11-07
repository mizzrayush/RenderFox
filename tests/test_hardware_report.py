"""
Hardware report contract - the machine's own numbers, or the reason there are none.

This suite exists because the Performance and Diagnostics panes used to answer questions this
machine was never asked. `SystemInfo.get_gpu_info()` returned the row
`{'name': 'Unknown GPU', 'details': 'Install GPUtil package for GPU monitoring'}` while GPUtil
was already installed, `HealthChecker.check_gpu_availability()` called that row
"1 GPU(s) available", and the Performance pane wrote "45%", "6,847 MB", "72 degC" and "285W"
into its GPU rows from its own timer every two seconds. Storage was measured with
`psutil.disk_usage('/')`, which on Windows is the drive the process started on - here D: at
25.8% full - while the directory the app stages renders into sits on C: at 90.8%. The pane
printed the start-up drive's figure and called the machine healthy. The dependency check
imported every package it was asked about, which costs 7.6 seconds on this machine, and
looked up `pillow` and `scikit-learn` by their distribution names, so it reported two
installed libraries as missing.

What is pinned here, in order:

* a reading that did not happen is a reason, never a number: no adapter, no load figure, no
  media type and no volume leaves the field blank-and-explained rather than 0, `None` or the
  previous answer;
* the volume every storage figure describes is the volume the app writes to, chosen by one
  helper the panes and the health check share, and the mount point travels with the number;
* the vocabulary is the backend's: `working_volume`, `load_reason`, `media_type`, and the
  status words `healthy` / `warning` / `critical`;
* a question to Windows that fails is reported as that failure with the message Windows
  sent, and a pane never treats "unknown" as "all right";
* the figures beside a verdict and the verdict itself come from one measurement, so a row
  cannot show last second's number with this second's word;
* the panes paint what they are handed and compute nothing of their own.

Run: python -X utf8 tests/test_hardware_report.py
"""

import ast
import collections
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

import psutil

from src.features.diagnostic_engine import (DependencyChecker, DiagnosticEngine,
                                            HealthChecker, SystemInfo)

VOLUME_KEYS = {'mountpoint', 'device', 'filesystem', 'total_bytes', 'used_bytes',
               'free_bytes', 'used_percent', 'media_type', 'disk'}
ADAPTER_KEYS = {'name', 'vendor', 'driver', 'adapter_ram_mb', 'resolution', 'live', 'source'}
STATUSES = ('healthy', 'warning', 'critical')


def volume(mount='C:\\', used_percent=40.0, total=200 * 1024 ** 3, media='SSD',
           disk='TestDisk', **extra):
    row = {'mountpoint': mount, 'device': mount, 'filesystem': 'NTFS',
           'total_bytes': int(total),
           'used_bytes': int(total * used_percent / 100.0),
           'free_bytes': int(total * (100.0 - used_percent) / 100.0),
           'used_percent': used_percent, 'media_type': media, 'disk': disk}
    row.update(extra)
    return row


def storage(*rows, reasons=None):
    return {'volumes': list(rows), 'reasons': list(reasons or [])}


def working_drive():
    """The drive letter the app stages its files on, as `C:\\`."""
    from src.utils.file_utils import get_temp_directory
    return os.path.abspath(get_temp_directory())[:2].upper() + '\\'


def adapter(name='Fake Adapter', live=None, **extra):
    row = {'name': name, 'vendor': 'FakeVendor', 'driver': '1.2.3', 'adapter_ram_mb': 1024,
           'resolution': '1920x1080', 'live': live, 'source': 'unit test'}
    row.update(extra)
    return row


def gpu_report(adapters=(), reasons=(), load_reason=None):
    return {'adapters': list(adapters), 'reasons': list(reasons),
            'load_reason': load_reason,
            'text': SystemInfo._gpu_text(list(adapters), list(reasons)),
            'identity_source': adapters[0]['source'] if adapters else None}




def body_of(path, class_name, function_name):
    """The statements of one method as text, without its docstring.

    Several pins here are "this call is gone from the code", and the explanation of why it
    went mentions it, so the docstring has to come out or the pin fails on its own prose.
    """
    path = os.path.join(ROOT, path)
    with open(path, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    klass = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.ClassDef) and node.name == class_name)
    fn = next(node for node in klass.body
              if isinstance(node, ast.FunctionDef) and node.name == function_name)
    return '\n'.join(ast.unparse(statement) for statement in fn.body
                     if not (isinstance(statement, ast.Expr)
                             and isinstance(statement.value, ast.Constant)))


class Test01LiveMachineReading(unittest.TestCase):
    """The real machine, asked honestly: whatever it answers, the shape must hold."""

    @classmethod
    def setUpClass(cls):
        cls.gpu = SystemInfo.get_gpu_report()
        cls.st = SystemInfo.get_storage_info()
        cls.cpu = SystemInfo.get_cpu_info()

    def test_01_gpu_report_has_every_field_the_panes_read(self):
        for key in ('adapters', 'reasons', 'text', 'load_reason', 'identity_source'):
            self.assertIn(key, self.gpu, f'get_gpu_report() lost {key}')
        for row in self.gpu['adapters']:
            self.assertEqual(ADAPTER_KEYS, set(row.keys()),
                             f'adapter row carries {sorted(row)} not the agreed fields')
            self.assertTrue(str(row['source']).strip(), 'an adapter with no source is a guess')
        self.assertIsInstance(self.gpu['text'], str)
        self.assertTrue(self.gpu['text'].strip())

    def test_02_get_gpu_info_is_the_same_rows_not_a_second_copy(self):
        self.assertEqual(self.gpu['adapters'], SystemInfo.get_gpu_info(),
                         'two GPU answers again: the panes and the check disagree by design')

    def test_03_no_adapter_becomes_a_zero(self):
        if self.gpu['load_reason']:
            self.assertTrue(all(row['live'] is None for row in self.gpu['adapters']),
                            'a machine that could not answer left a 0.0 behind anyway')
            self.assertTrue(any('current load' in reason for reason in self.gpu['reasons']),
                            'the reason is missing from the notes the report prints')
        else:
            self.assertTrue(any(row['live'] for row in self.gpu['adapters']),
                            'load_reason said nothing was read, yet a row carries figures')

    def test_04_storage_volumes_are_whole_rows_or_no_row(self):
        for row in self.st['volumes']:
            self.assertEqual(VOLUME_KEYS, set(row.keys()), f'volume row {sorted(row)}')
            for key in ('total_bytes', 'used_bytes', 'free_bytes'):
                self.assertIsInstance(row[key], int, f'{key} is not a byte count')
                self.assertGreater(row[key], 0, f'{key} came back {row[key]}')
            self.assertTrue(row['mountpoint'], 'a volume with no name cannot be shown')
        self.assertIsInstance(self.st['reasons'], list)

    def test_05_a_blank_media_type_is_explained(self):
        for row in self.st['volumes']:
            if row['media_type'] is None:
                self.assertTrue(self.st['reasons'],
                                f"{row['mountpoint']} has no disk kind and no reason either")

    def test_06_cpu_figure_comes_from_a_watched_window(self):
        self.assertEqual(len(self.cpu['per_core_usage']), self.cpu['logical_cores'],
                         'per-core list does not match the core count')
        expected = round(sum(self.cpu['per_core_usage']) / len(self.cpu['per_core_usage']), 1)
        self.assertLessEqual(abs(self.cpu['usage_percent'] - expected), 0.2,
                             'the overall figure is not the mean of the same window')
        self.assertLessEqual(0.0, self.cpu['usage_percent'])
        self.assertGreaterEqual(100.0, self.cpu['usage_percent'])

    def test_07_measuring_the_cpu_takes_the_window_it_claims(self):
        start = time.time()
        SystemInfo.get_cpu_info()
        self.assertGreaterEqual(time.time() - start, 0.15,
                                'get_cpu_info returned instantly, so it read no window')

    def test_08_storage_answer_names_the_volume_the_app_writes_to(self):
        from src.utils.file_utils import get_temp_directory
        picked = SystemInfo.working_volume(self.st)
        self.assertIsNotNone(picked,
                             'no mounted volume carries the directory the app writes into')
        self.assertTrue(os.path.abspath(get_temp_directory()).upper()
                        .startswith(picked['mountpoint'].upper()))


class Test02WorkingVolume(unittest.TestCase):
    """One helper decides which drive a number belongs to; the panes do not each guess."""

    def test_10_exact_drive_letter(self):
        st = storage(volume('C:\\'), volume('D:\\'))
        self.assertEqual('D:\\', SystemInfo.working_volume(st, 'D:\\renders\\out.obj')
                         ['mountpoint'])

    def test_11_longest_mount_wins(self):
        st = storage(volume('C:\\'), volume('R:\\'))
        st['volumes'].append(volume('R:\\renders'))
        self.assertEqual('R:\\renders',
                         SystemInfo.working_volume(st, 'R:\\renders\\a\\b.obj')['mountpoint'])

    def test_12_letter_case_and_trailing_separator(self):
        st = storage(volume('e:\\'))
        self.assertIsNotNone(SystemInfo.working_volume(st, 'E:\\mixed\\case'))
        self.assertIsNotNone(SystemInfo.working_volume(st, 'e:\\'))

    def test_13_nothing_carries_the_path(self):
        st = storage(volume('C:\\'))
        self.assertIsNone(SystemInfo.working_volume(st, 'Z:\\somewhere'))
        self.assertIsNone(SystemInfo.working_volume(storage()), 'no volumes, yet a pick')

    def test_14_prefix_must_be_a_whole_drive(self):
        st = storage(volume('C:\\'))
        self.assertIsNone(SystemInfo.working_volume(st, 'CC:\\fake'),
                          'a path starting with the letters of a drive counts as that drive')

    def test_15_default_path_is_where_the_app_writes(self):
        """The no-path answer is the scratch folder's drive, named by the fixture.

        Reading the real `get_temp_directory()` and hoping it sits on another drive than the
        process started on pinned this on one machine and left it unpinnable on any machine
        where the two agree, which is the same assertion written twice. Both sides are
        therefore set here: the scratch folder is put on a drive the cwd is not on, and the
        fixture carries both, so the answer can only be right for the reason the code gives.
        """
        cwd_drive = os.path.abspath(os.getcwd())[:2].upper()
        drives = [letter + ':' for letter in 'CDEF']
        scratch_drive = next(drive for drive in drives if drive != cwd_drive)
        st = storage(*[volume(drive + '\\') for drive in drives])
        with mock.patch('src.utils.file_utils.get_temp_directory',
                        return_value=os.path.join(scratch_drive + '\\', 'renders', 'scratch')):
            picked = SystemInfo.working_volume(st)
        self.assertIsNotNone(picked, 'every drive in the fixture is mounted, yet no pick')
        self.assertEqual(scratch_drive, picked['mountpoint'][:2].upper(),
                         f'the default write volume is not the drive the app writes into '
                         f'({scratch_drive})')
        self.assertNotEqual(cwd_drive, picked['mountpoint'][:2].upper(),
                            'the answer is the drive the process happened to start on, which '
                            'is where the exe lives, not where a render lands')


class Test03DiskVerdict(unittest.TestCase):
    """`psutil.disk_usage('/')` measured a drive the app never writes to."""

    def test_20_thresholds_come_from_the_picked_volume(self):
        for percent, expected in ((96.0, 'critical'), (90.0, 'warning'), (40.0, 'healthy')):
            got = HealthChecker.check_disk_space(storage(volume('C:\\', percent)))
            self.assertEqual(expected, got['status'], f'{percent}% read as {got["status"]}')

    def test_21_the_message_names_the_volume_it_measured(self):
        got = HealthChecker.check_disk_space(storage(volume('D:\\', 50.0)), 'D:\\work\\x.obj')
        self.assertIn('D:\\', got['message'])
        self.assertIn('TestDisk', got['message'])
        self.assertEqual('D:\\', got['mountpoint'])
        self.assertAlmostEqual(100.0, got['free_gb'], places=1)
        self.assertEqual(50.0, got['used_percent'])

    def test_22_a_verdict_without_a_volume_says_so(self):
        got = HealthChecker.check_disk_space(storage(volume('C:\\')), 'Z:\\gone.obj')
        self.assertEqual('warning', got['status'])
        self.assertIsNone(got['free_gb'], 'no volume was measured, yet a figure appeared')
        self.assertIsNone(got['used_percent'])
        self.assertIn('Z:\\gone.obj', got['message'])
        self.assertNotIn('%', got['message'].replace('percent', ''),
                         'a percentage was printed with nothing measured')

    def test_23_the_start_up_drive_is_not_the_answer(self):
        """A volume holding the app's writes must win over whichever drive the process began on."""
        startup = os.path.abspath(os.sep)[:2].upper()
        other = 'E:\\' if startup != 'E:' else 'F:\\'
        st = storage(volume(startup + '\\', 12.0), volume(other, 99.0))
        got = HealthChecker.check_disk_space(st, other + 'renders')
        self.assertEqual(other.rstrip('\\') + '\\', got['mountpoint'])
        self.assertEqual('critical', got['status'],
                         'the start-up drive\'s quiet figure overrode the full write volume')

    def test_24_the_start_up_drive_is_never_asked_about(self):
        body = body_of(os.path.join('src', 'features', 'diagnostic_engine.py'),
                       'HealthChecker', 'check_disk_space')
        self.assertNotIn("disk_usage('/')", body, 'the old question came back')
        self.assertIn('working_volume', body, 'the check stopped using the shared pick')

    def test_25_the_report_ships_one_volume_answer(self):
        report = DiagnosticEngine().get_full_system_report()
        self.assertNotIn('disk', report,
                         'a second volume reader crept back beside get_storage_info')
        self.assertEqual(VOLUME_KEYS, set(report['storage']['volumes'][0].keys()))
        self.assertEqual(report['health_checks']['disk']['mountpoint'],
                         SystemInfo.working_volume(report['storage'])['mountpoint'])


class Test04CimFailures(unittest.TestCase):
    """Every way a question to Windows can fail arrives as that failure, with its message."""

    class Completed:
        def __init__(self, rc=0, out='[]', err=''):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def test_30_off_windows(self):
        with mock.patch('src.features.diagnostic_engine.platform.system',
                        return_value='Linux'):
            got = SystemInfo._cim_rows('anything')
        self.assertEqual([], got['rows'])
        self.assertIn('Linux', got['reason'])

    def test_31_no_shell_on_path(self):
        with mock.patch('src.features.diagnostic_engine.platform.system',
                        return_value='Windows'), \
             mock.patch('src.features.diagnostic_engine.shutil.which', return_value=None):
            got = SystemInfo._cim_rows('anything')
        self.assertIn('PATH', got['reason'])

    def test_32_shell_never_answers(self):
        def hang(*a, **k):
            raise subprocess.TimeoutExpired(cmd='powershell', timeout=20)
        with mock.patch('src.features.diagnostic_engine.platform.system',
                        return_value='Windows'), \
             mock.patch('src.features.diagnostic_engine.shutil.which',
                        return_value='powershell'), \
             mock.patch('src.features.diagnostic_engine.subprocess.run', side_effect=hang):
            got = SystemInfo._cim_rows('anything')
        self.assertIn('20', got['reason'])

    def test_33_shell_could_not_start(self):
        with mock.patch('src.features.diagnostic_engine.platform.system',
                        return_value='Windows'), \
             mock.patch('src.features.diagnostic_engine.shutil.which',
                        return_value='powershell'), \
             mock.patch('src.features.diagnostic_engine.subprocess.run',
                        side_effect=OSError('access denied')):
            got = SystemInfo._cim_rows('anything')
        self.assertIn('access denied', got['reason'])

    def test_34_nonzero_exit_carries_the_first_error_line(self):
        with mock.patch('src.features.diagnostic_engine.platform.system',
                        return_value='Windows'), \
             mock.patch('src.features.diagnostic_engine.shutil.which',
                        return_value='powershell'), \
             mock.patch('src.features.diagnostic_engine.subprocess.run',
                        return_value=self.Completed(1, '', 'boom line\nsecond line')):
            got = SystemInfo._cim_rows('anything')
        self.assertIn('boom line', got['reason'])
        self.assertNotIn('second line', got['reason'], 'the whole error dump went to the pane')

    def test_35_silence_and_nonsense(self):
        for out, needle in (('', 'no rows'), ('not json at all', 'not JSON')):
            with mock.patch('src.features.diagnostic_engine.platform.system',
                            return_value='Windows'), \
                 mock.patch('src.features.diagnostic_engine.shutil.which',
                            return_value='powershell'), \
                 mock.patch('src.features.diagnostic_engine.subprocess.run',
                            return_value=self.Completed(0, out)):
                got = SystemInfo._cim_rows('anything')
            self.assertIn(needle, got['reason'])

    def test_36_one_row_arrives_as_a_list(self):
        with mock.patch('src.features.diagnostic_engine.platform.system',
                        return_value='Windows'), \
             mock.patch('src.features.diagnostic_engine.shutil.which',
                        return_value='powershell'), \
             mock.patch('src.features.diagnostic_engine.subprocess.run',
                        return_value=self.Completed(0, '{"Name": "Only One"}')):
            got = SystemInfo._cim_rows('anything')
        self.assertEqual([{'Name': 'Only One'}], got['rows'])
        self.assertEqual('', got['reason'])


class Test05AdapterIdentity(unittest.TestCase):
    """Who is in this machine, according to whichever check could say."""

    def _report(self, cim=None, live=None, live_reason='', opengl=None):
        rows = {'rows': [], 'reason': ''} if cim is None else cim
        with mock.patch.object(SystemInfo, '_cim_rows', return_value=rows), \
             mock.patch.object(SystemInfo, '_gputil_adapters',
                               return_value=(live or [], live_reason)), \
             mock.patch.object(SystemInfo, '_attach_live',
                               side_effect=lambda a: None), \
             mock.patch('src.features.diagnostic_engine.OPENGL_AVAILABLE',
                        bool(opengl is not None)), \
             mock.patch('src.features.diagnostic_engine.OpenGLInfo.get_opengl_info',
                        return_value=opengl or {}):
            return SystemInfo.get_gpu_report()

    def test_40_windows_fields_are_mapped(self):
        cim = {'rows': [{'Name': 'Intel X', 'AdapterCompatibility': 'Intel',
                         'DriverVersion': '31.0', 'AdapterRAM': 4 * 1024 ** 3,
                         'VideoProcessor': None,
                         'CurrentHorizontalResolution': 2560,
                         'CurrentVerticalResolution': 1440}], 'reason': ''}
        row = self._report(cim=cim)['adapters'][0]
        self.assertEqual({'Intel X', 'Intel', '31.0', 4096, '2560x1440'},
                         {row['name'], row['vendor'], row['driver'], row['adapter_ram_mb'],
                          row['resolution']})

    def test_41_missing_fields_stay_missing(self):
        cim = {'rows': [{'Name': None, 'AdapterCompatibility': None, 'DriverVersion': None,
                         'AdapterRAM': None, 'CurrentHorizontalResolution': None,
                         'CurrentVerticalResolution': None}], 'reason': ''}
        row = self._report(cim=cim)['adapters'][0]
        self.assertEqual('unnamed adapter', row['name'])
        self.assertIsNone(row['adapter_ram_mb'], 'no figure became 0')
        self.assertIsNone(row['resolution'])
        self.assertEqual('unknown', row['vendor'])

    def test_42_the_32_bit_memory_caveat_is_said_once(self):
        cim = {'rows': [{'Name': 'A', 'AdapterRAM': 2 * 1024 ** 3},
                        {'Name': 'B', 'AdapterRAM': 2 * 1024 ** 3}], 'reason': ''}
        report = self._report(cim=cim)
        notes = [r for r in report['reasons'] if r.startswith('adapter memory')]
        self.assertEqual(1, len(notes), str(report['reasons']))
        self.assertIn('capacity', notes[0])

    def test_43_query_failing_is_a_reason_not_an_empty_pane(self):
        report = self._report(cim={'rows': [], 'reason': 'PowerShell answered no rows'},
                              live_reason='GPUtil is not installed')
        self.assertEqual([], report['adapters'])
        self.assertIn('adapter identity: PowerShell answered no rows', report['reasons'])
        self.assertIn('adapter identity: GPUtil is not installed', report['reasons'])
        self.assertIn('No display adapter', report['text'])

    def test_44_gputil_names_the_adapter_when_windows_cannot(self):
        class G:
            name, driver, memoryTotal = 'NVIDIA T', '550.1', 8192.0

        report = self._report(live=[G()])
        self.assertEqual('NVIDIA T', report['adapters'][0]['name'])
        self.assertEqual('GPUtil', report['adapters'][0]['source'])
        self.assertEqual(8192, report['adapters'][0]['adapter_ram_mb'])

    def test_45_opengl_says_only_what_it_knows(self):
        report = self._report(opengl={'renderer': 'llvmpipe', 'vendor': 'Mesa'})
        row = report['adapters'][0]
        self.assertEqual('llvmpipe', row['name'])
        self.assertIn('OpenGL context', row['source'])
        self.assertIsNone(row['adapter_ram_mb'],
                          'a renderer name was promoted into a memory figure')

    def test_46_opengl_that_cannot_start_is_admitted(self):
        report = self._report(opengl={'error': 'no GL context'})
        self.assertEqual([], report['adapters'])
        self.assertTrue(any('no reader answered' in r for r in report['reasons']),
                        str(report['reasons']))

    def test_47_report_is_json_serialisable(self):
        """The Diagnostics pane writes this whole thing to a file; a live object breaks it."""
        text = json.dumps(self._report(cim={'rows': [{'Name': 'A'}], 'reason': ''}),
                          default=None)
        self.assertIn('"A"', text)


class Test06CurrentLoad(unittest.TestCase):
    """The load figures arrive together or not at all, and say which happened."""

    class G:
        def __init__(self, load=0.5, util=0.25, temp=61.23, used=123.4):
            self.load, self.memoryUtil, self.temperature, self.memoryUsed = load, util, temp, used

    def test_50_figures_are_rounded_onto_the_right_row(self):
        rows = [adapter('A'), adapter('B')]
        with mock.patch.object(SystemInfo, '_gputil_adapters',
                               return_value=([self.G(), self.G(0.1, 0.9, 20.0, 7.0)], '')):
            reason = SystemInfo._attach_live(rows)
        self.assertIsNone(reason)
        self.assertEqual({'load_percent': 50.0, 'memory_percent': 25.0,
                          'temperature_c': 61.2, 'memory_used_mb': 123,
                          'reader': 'GPUtil'}, rows[0]['live'])
        self.assertEqual(10.0, rows[1]['live']['load_percent'])

    def test_51_nothing_answered_is_a_sentence(self):
        rows = [adapter('A')]
        with mock.patch.object(SystemInfo, '_gputil_adapters', return_value=([], 'GPUtil is not installed')):
            self.assertEqual('GPUtil is not installed', SystemInfo._attach_live(rows))
        self.assertIsNone(rows[0]['live'])

    def test_52_counts_that_disagree_are_reported(self):
        rows = [adapter('A'), adapter('B')]
        with mock.patch.object(SystemInfo, '_gputil_adapters', return_value=([self.G()], '')):
            reason = SystemInfo._attach_live(rows)
        self.assertIn('matched in order', reason)
        self.assertIn('live_unmatched', rows[1])
        self.assertIsNone(rows[1]['live'], 'the second adapter inherited the first one\'s load')

    def test_53_report_puts_the_reason_in_its_own_field(self):
        with mock.patch.object(SystemInfo, '_cim_rows',
                               return_value={'rows': [{'Name': 'A'}], 'reason': ''}), \
             mock.patch.object(SystemInfo, '_gputil_adapters', return_value=([], 'nothing here')):
            report = SystemInfo.get_gpu_report()
        self.assertEqual('nothing here', report['load_reason'])
        self.assertIn('current load: nothing here', report['reasons'])
        for row in report['adapters']:
            self.assertIsNone(row['live'])


class Test07AdapterText(unittest.TestCase):
    """One block of words, printed by both panes, that never says `None`.

    The OpenGL answer can leave the vendor blank, and the line printed `Vendor: None`, so the
    report claimed to have read a value that was never there.
    """

    def test_60_no_field_leaks_the_word_none(self):
        rows = [adapter('Only', vendor=None, driver=None, adapter_ram_mb=None,
                        resolution=None, live=None)]
        text = SystemInfo._gpu_text(rows, [])
        self.assertNotIn('None', text, text)
        self.assertIn('Vendor: not reported', text)
        self.assertNotIn('Driver:', text)
        self.assertIn("no reader reports this adapter's load", text)

    def test_61_figures_print_with_their_units(self):
        rows = [adapter(live={'load_percent': 12.5, 'memory_percent': 40.0,
                              'temperature_c': 55.0, 'memory_used_mb': 900,
                              'reader': 'GPUtil'})]
        text = SystemInfo._gpu_text(rows, ['note one'])
        self.assertIn('12.5% busy', text)
        self.assertIn('40.0% of its memory in use', text)
        self.assertIn('55.0 degC', text)
        self.assertIn('read from GPUtil', text)
        self.assertIn('Note: note one', text)

    def test_62_unmatched_row_is_shown(self):
        rows = [adapter(live_unmatched='GPUtil answered 1 adapter(s) and Windows records 2')]
        self.assertIn('GPUtil answered 1', SystemInfo._gpu_text(rows, []))


class Test08GpuVerdict(unittest.TestCase):
    """The word beside the GPU line, including when only half the question was answerable."""

    def test_70_nothing_identified_is_a_warning(self):
        got = HealthChecker.check_gpu_availability(gpu_report())
        self.assertEqual('warning', got['status'],
                         'an unidentified adapter was called available, as before the repair')

    def test_71_adapter_without_load_is_healthy_and_explains(self):
        got = HealthChecker.check_gpu_availability(
            gpu_report([adapter()], ['current load: nothing here'], 'nothing here'))
        self.assertEqual('healthy', got['status'])
        self.assertIn('Fake Adapter', got['message'])
        self.assertIn('what it is doing right now', got['message'])
        self.assertIn('nothing here', got['message'])

    def test_72_two_adapters_use_the_plural(self):
        report = gpu_report([adapter('A'), adapter('B')], [], 'nothing here')
        report['adapters'][0]['name'] = report['adapters'][1]['name'] = 'B'
        message = HealthChecker.check_gpu_availability(report)['message']
        self.assertIn('2 display adapters', message)
        self.assertIn('what they are doing', message)

    def test_73_hot_adapter_warns_and_names_itself(self):
        report = gpu_report([adapter('Hot', live={'load_percent': 99.0, 'memory_percent': 90.0,
                                                  'temperature_c': 91.0,
                                                  'memory_used_mb': 8000, 'reader': 'GPUtil'})])
        got = HealthChecker.check_gpu_availability(report)
        self.assertEqual('warning', got['status'])
        self.assertIn('Hot', got['message'])
        self.assertIn('91 degC', got['message'])

    def test_74_partial_figures_name_which_rows_have_them(self):
        report = gpu_report([adapter('Read', live={'load_percent': 1.0, 'memory_percent': 2.0,
                                                   'temperature_c': 30.0,
                                                   'memory_used_mb': 10, 'reader': 'GPUtil'}),
                             adapter('Blind')])
        report['adapters'][0]['name'] = 'Read'
        report['adapters'][1]['name'] = 'Blind'
        message = HealthChecker.check_gpu_availability(report)['message']
        self.assertIn('Current figures only for: Read', message)
        self.assertNotIn('each with its current figures', message)

    def test_75_all_rows_read_is_stated(self):
        live = {'load_percent': 1.0, 'memory_percent': 2.0, 'temperature_c': 30.0,
                'memory_used_mb': 10, 'reader': 'GPUtil'}
        message = HealthChecker.check_gpu_availability(
            gpu_report([adapter(live=live)]))['message']
        self.assertIn('each with its current figures', message)


class Test09OtherChecks(unittest.TestCase):
    def test_80_cpu_verdict_follows_the_sample(self):
        for usage, expected in ((97.0, 'critical'), (88.0, 'warning'), (30.0, 'healthy')):
            cpu = {'usage_percent': usage, 'logical_cores': 12}
            got = HealthChecker.check_cpu_usage(cpu)
            self.assertEqual(expected, got['status'], f'{usage}% read as {got["status"]}')
            self.assertIn('12 logical cores', got['message'])
            self.assertEqual(usage, got['usage_percent'])

    def test_81_dependencies_missing_required_is_critical(self):
        with mock.patch.object(DependencyChecker, 'check_all_dependencies',
                               return_value={'required': {'trimesh': {'installed': False}},
                                             'optional': {}}):
            self.assertEqual('critical', HealthChecker.check_dependencies()['status'])

    def test_82_memory_verdict_words(self):
        class Mem:
            percent, available = 95.0, 1024 ** 3
        with mock.patch('src.features.diagnostic_engine.psutil.virtual_memory',
                        return_value=Mem()):
            self.assertEqual('critical', HealthChecker.check_memory_usage()['status'])

    def test_83_every_check_answers_in_the_vocabulary(self):
        health = HealthChecker.run_all_checks()
        self.assertEqual({'cpu', 'memory', 'disk', 'gpu', 'dependencies'}, set(health))
        for name, check in health.items():
            self.assertIn(check['status'], STATUSES, f'{name} invented {check["status"]!r}')
            self.assertTrue(check['message'].strip(), f'{name} had nothing to say')


class Test10OneMeasurementPerReport(unittest.TestCase):
    """Handing the readings down must stop a second question, not just look tidier."""

    def test_90_shared_readings_ask_nothing(self):
        def boom(*a, **k):
            raise AssertionError('a check measured this machine a second time')
        storage_read = storage(volume('C:\\', 10.0))
        adapters = gpu_report([adapter()], ['current load: n/a'], 'n/a')
        cpu = {'usage_percent': 5.0, 'logical_cores': 4}
        with mock.patch.object(SystemInfo, 'get_storage_info', side_effect=boom), \
             mock.patch.object(SystemInfo, 'get_gpu_report', side_effect=boom), \
             mock.patch.object(SystemInfo, 'get_cpu_info', side_effect=boom):
            health = HealthChecker.run_all_checks(storage_read, adapters, cpu)
        self.assertEqual('healthy', health['disk']['status'])
        self.assertEqual('healthy', health['cpu']['status'])
        self.assertIn('n/a', health['gpu']['message'])

    def test_91_report_and_advice_are_the_same_measurement(self):
        engine = DiagnosticEngine()
        report = engine.get_full_system_report()
        advice = engine.get_recommendations(report['health_checks'])
        for line in advice:
            self.assertTrue(line.startswith('Warning: ') or line.startswith('Good: '), line)
            self.assertFalse(any(ord(ch) > 0x2190 for ch in line),
                             f'a picture character went back into {line!r}')
        for line in [a for a in advice if a.startswith('Warning: ')]:
            body = line[len('Warning: '):]
            self.assertTrue(any(body == check['message']
                                for check in report['health_checks'].values()),
                            f'{body!r} is advice no check gave')

    def test_92_healthy_machine_says_one_plain_thing(self):
        clean = {name: {'status': 'healthy', 'message': 'fine'} for name in
                 ('cpu', 'memory', 'disk', 'gpu', 'dependencies')}
        lines = DiagnosticEngine().get_recommendations(clean)
        self.assertEqual(1, len(lines), str(lines))
        self.assertTrue(lines[0].startswith('Good: '), lines[0])

    def test_93_the_report_hands_its_own_readings_to_its_verdicts(self):
        """The look the report takes is the look the checks judge, not a second one.

        test_90 proves `run_all_checks` uses what it is handed; this proves the caller
        actually hands it. The reading is answered once and a second question raises, so a
        report that measures the machine twice cannot pass - which is the defect a pane shows
        as a full drive beside a "all right" word.
        """
        def once(fixture):
            asked = []

            def answer(*a, **k):
                asked.append(1)
                if len(asked) > 1:
                    raise AssertionError('the machine was measured a second time')
                return fixture
            return answer

        read = storage(volume(working_drive(), 90.0))
        adapters = gpu_report([adapter()], ['current load: n/a'], 'n/a')
        cpu = {'usage_percent': 3.0, 'logical_cores': 4, 'physical_cores': 2,
               'current_frequency': '100 MHz'}
        with mock.patch.object(SystemInfo, 'get_storage_info', side_effect=once(read)), \
             mock.patch.object(SystemInfo, 'get_gpu_report', side_effect=once(adapters)), \
             mock.patch.object(SystemInfo, 'get_cpu_info', side_effect=once(cpu)):
            report = DiagnosticEngine().get_full_system_report()
        self.assertIs(read, report['storage'])
        self.assertIn('90.0% used', report['health_checks']['disk']['message'])
        self.assertIn('n/a', report['health_checks']['gpu']['message'])
        self.assertEqual(3.0, report['health_checks']['cpu']['usage_percent'])


class Test11DependencyLookup(unittest.TestCase):
    """Presence and version, without importing a single library."""

    def test_100_distribution_names_are_translated(self):
        seen = []

        class Spec:
            pass

        def fake_find_spec(name):
            seen.append(name)
            return Spec()

        with mock.patch('importlib.util.find_spec', side_effect=fake_find_spec), \
             mock.patch('importlib.metadata.version', return_value='9.9'):
            DependencyChecker.check_package('pillow')
            DependencyChecker.check_package('scikit-learn')
            DependencyChecker.check_package('some-thing')
        self.assertEqual(['PIL', 'sklearn', 'some_thing'], seen,
                         'a library was looked up by the wrong name again')

    def test_101_absent_library_is_absent_both_ways(self):
        with mock.patch('importlib.util.find_spec', return_value=None), \
             mock.patch('importlib.metadata.version',
                        side_effect=importlib.metadata.PackageNotFoundError('nope')):
            got = DependencyChecker.check_package('never-published-xyz')
        self.assertFalse(got['installed'])
        self.assertIsNone(got['version'])
        self.assertEqual('Not Installed', got['status'])

    def test_102_a_broken_name_does_not_raise(self):
        with mock.patch('importlib.util.find_spec', side_effect=ValueError('empty name')), \
             mock.patch('importlib.metadata.version', return_value=None):
            self.assertFalse(DependencyChecker.check_package('pillow')['installed'])

    def test_103_the_check_loads_no_library_just_to_ask(self):
        body = body_of(os.path.join('src', 'features', 'diagnostic_engine.py'),
                       'DependencyChecker', 'check_package')
        self.assertIn('find_spec', body, 'the check stopped asking the package records')
        self.assertNotIn('__import__', body, 'the seven-second check came back')
        for name in DependencyChecker.REQUIRED_PACKAGES + DependencyChecker.OPTIONAL_PACKAGES:
            self.assertNotIn(name, body,
                             f'{name} is loaded by the check that only asks if it exists')

    def test_104_the_whole_dependency_answer_is_fast(self):
        start = time.time()
        deps = DependencyChecker.check_all_dependencies()
        took = time.time() - start
        self.assertLess(took, 2.0, f'asking which libraries exist took {took:.1f}s')
        for group in ('required', 'optional'):
            for name, info in deps[group].items():
                self.assertEqual({'installed', 'version', 'status'}, set(info), name)
                if info['installed']:
                    self.assertNotEqual('Unknown', info['version'],
                                        f'{name} is here and its version was not looked up')

    def test_105_a_library_the_installer_records_is_not_called_missing(self):
        """Some distributions install files without a module of that name.

        The version record is the evidence that counts there: `pillow` without `PIL` is a
        broken install, not an absent library, and telling a user to install what they have
        already installed costs the trust the whole pane runs on.
        """
        with mock.patch('importlib.util.find_spec', return_value=None), \
             mock.patch('importlib.metadata.version', return_value='2.1'):
            got = DependencyChecker.check_package('meta-thing')
        self.assertTrue(got['installed'], 'a library with a version record was called missing')
        self.assertEqual('2.1', got['version'])
        self.assertEqual('OK', got['status'])


class Test12PerformancePane(unittest.TestCase):
    """The pane paints what it is handed, and says nothing before it is asked."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from src.ui.performance_tab import PerformanceTab
        self.tab = PerformanceTab()

    def pump(self, seconds=25.0, until=None):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.02)
            if until and until():
                return True
        return until() if until else False

    def test_110_nothing_is_on_screen_before_a_reading(self):
        for label in (self.tab.gpu_utilization_label, self.tab.gpu_memory_used_label,
                      self.tab.gpu_temperature_label):
            self.assertIn('not measured', label.text().lower(), label.text())
            self.assertNotRegex(label.text(), r'\b\d+% ', 'a figure with no measurement')
        self.assertNotRegex(self.tab.gpu_power_label.text(), r'\d', self.tab.gpu_power_label.text())
        for label in (self.tab.storage_total_label, self.tab.storage_used_label,
                      self.tab.storage_free_label, self.tab.storage_type_label):
            self.assertEqual('-', label.text(), 'a storage row was seeded with an answer')

    def test_111_storage_rows_show_the_write_volume_not_the_first_row(self):
        working = working_drive()
        decoy = 'E:\\' if working[:1].upper() != 'E' else 'F:\\'
        self.tab.show_storage_info(storage(volume(decoy, 3.0),
                                           volume(working, 97.0, media='HDD', disk='Slow')))
        self.assertIn(working, self.tab.storage_total_label.text())
        self.assertNotIn(decoy, self.tab.storage_total_label.text(),
                         'the pane showed whichever volume was handed to it first')
        self.assertIn('97.0% full', self.tab.storage_used_label.text())
        self.assertEqual('HDD - Slow', self.tab.storage_type_label.text(),
                         'the pane printed the drive kind without the disk it belongs to')

    def test_112_an_unknown_drive_kind_shows_the_reason(self):
        self.tab.show_storage_info(storage(volume(working_drive(), 40.0, media=None,
                                                  disk=None),
                                           reasons=['which kind of disk: Windows said no']))
        self.assertEqual('which kind of disk: Windows said no',
                         self.tab.storage_type_label.text())
        self.assertNotIn('None', self.tab.storage_type_label.text())

    def test_113_no_write_volume_is_said_loudly(self):
        from src.features.diagnostic_engine import SystemInfo as SI
        real = SI.working_volume
        try:
            SI.working_volume = lambda st, path=None: None
            self.tab.show_storage_info(storage(volume('C:\\')))
            self.assertIn('no mounted volume', self.tab.storage_free_label.text())
            self.assertEqual('unknown - no volume was listed', self.tab.storage_type_label.text())
        finally:
            SI.working_volume = real

    def test_114_adapter_without_load_never_shows_zero(self):
        self.tab.show_gpu_report(gpu_report([adapter()], ['current load: nope'], 'nope'))
        for label in (self.tab.gpu_utilization_label, self.tab.gpu_memory_used_label,
                      self.tab.gpu_temperature_label):
            self.assertEqual('nope', label.text())
        self.assertEqual('nope', self.tab.gpu_report['load_reason'])

    def test_115_load_figures_are_printed_as_read(self):
        live = {'load_percent': 33.3, 'memory_percent': 44.4, 'temperature_c': 55.5,
                'memory_used_mb': 666, 'reader': 'GPUtil'}
        self.tab.show_gpu_report(gpu_report([adapter(live=live)]))
        self.assertEqual('33.3% busy', self.tab.gpu_utilization_label.text())
        self.assertIn('666 MB', self.tab.gpu_memory_used_label.text())
        self.assertEqual('55.5 degC', self.tab.gpu_temperature_label.text())

    def test_116_the_timer_cannot_stamp_gpu_numbers(self):
        self.tab.show_gpu_report(gpu_report([adapter()], ['x'], 'nothing here reports'))
        kept = self.tab.gpu_utilization_label.text()
        metrics = {'cpu_percent': 1.0, 'memory_percent': 2.0, 'memory_used_mb': 3.0,
                   'gpu_percent': 0.0, 'gpu_memory_percent': 0.0, 'fps': 0.0,
                   'frame_time_ms': 0.0, 'timestamp': time.time()}
        self.tab.on_metrics_updated(metrics)
        self.assertEqual(kept, self.tab.gpu_utilization_label.text(),
                         'the two-second timer wrote its zero back over the answer')

    def test_117_a_failed_reader_is_named_not_zeroed(self):
        self.tab.on_machine_reader_failed((RuntimeError, RuntimeError('windows is closed'), None))
        self.assertIn('RuntimeError', self.tab.gpu_info_display.toPlainText())
        self.assertIn('windows is closed', self.tab.storage_used_label.text())
        self.assertNotRegex(self.tab.storage_used_label.text(), r'^\s*0')

    def test_118_detect_button_answers_off_the_interface_thread(self):
        self.tab.detect_gpu_hardware()
        self.assertFalse(self.tab.detect_gpu_btn.isEnabled(), 'the button stayed clickable')
        self.assertTrue(self.pump(until=lambda: self.tab.gpu_report is not None),
                        'the adapter question never answered')
        self.assertTrue(self.pump(3.0, until=lambda: self.tab.detect_gpu_btn.isEnabled()),
                        'the button never came back')
        for key in ('adapters', 'text', 'load_reason', 'reasons'):
            self.assertIn(key, self.tab.gpu_report)
        self.assertEqual(self.tab.gpu_report['text'],
                         self.tab.gpu_info_display.toPlainText(),
                         'the pane printed its own words instead of the reading')
        if not self.tab.gpu_report['adapters']:
            for label in (self.tab.gpu_utilization_label, self.tab.gpu_memory_used_label,
                          self.tab.gpu_temperature_label):
                self.assertNotRegex(label.text(), r'\b0(\.0)?\s*[%°]', label.text())

    def test_119_the_two_machine_readers_report_their_failures(self):
        """`Worker` always passes a progress argument, and always has somewhere to send a fault.

        The two buttons in this pane that do real work in the background are the adapter
        question and the volume question. The benchmark buttons join this pin in 6j-3, where
        their results stop being invented.
        """
        path = os.path.join(ROOT, 'src', 'ui', 'performance_tab.py')
        with open(path, encoding='utf-8') as handle:
            tree = ast.parse(handle.read())
        wanted = ('detect_gpu_hardware', 'refresh_storage_info')
        seen = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in wanted:
                continue
            seen.append(node.name)
            body = ast.unparse(node)
            self.assertIn('progress_callback=None', body,
                          f'{node.name} hides the argument the house worker always passes')
            self.assertIn('signals.error.connect', body,
                          f'{node.name} runs a task that can die silently')
        self.assertEqual(sorted(wanted), sorted(seen), 'a machine reader lost its function')

    def tearDown(self):
        """Hand the pane back the way the rest of the GUI suites do.

        `deleteLater` with no event loop left running puts the widget's death in the queue
        the interpreter reaches on its way out, and PyQt6 answers that with a process abort -
        a green run that exits 127 and reads, to the audit, as a suite that never reported.
        """
        from PyQt6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(10000)
        self.tab.update_timer.stop()
        self.tab.close()
        self.app.processEvents()


class Test13DiagnosticsPane(unittest.TestCase):
    """Badges and lines, each standing for exactly one check."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from src.ui.diagnostics_tab import DiagnosticsTab
        cls.tab = DiagnosticsTab()
        cls.real_engine = cls.tab.diagnostic_engine

    def setUp(self):
        self.tab.diagnostic_engine = self.real_engine

    def badge(self, name):
        frame = getattr(self.tab, name)
        return frame.layout().itemAt(1).widget()

    def test_130_each_badge_is_painted_by_its_own_check(self):
        health = {'cpu': {'status': 'healthy'}, 'memory': {'status': 'critical'},
                  'disk': {'status': 'warning'}, 'gpu': {'status': 'healthy'},
                  'dependencies': {'status': 'critical'}}
        self.tab.update_health_indicators(health)
        self.assertEqual('Good', self.badge('cpu_health').text())
        self.assertEqual('Critical', self.badge('memory_health').text())
        self.assertEqual('Warning', self.badge('storage_health').text())
        self.assertEqual('Good', self.badge('gpu_health').text())
        self.assertNotEqual(self.badge('cpu_health').text(),
                            self.badge('memory_health').text(),
                            'the CPU badge is still copying the memory one')

    def test_131_a_missing_check_is_not_a_pass(self):
        self.tab.update_health_indicators({'memory': {'status': 'healthy'}})
        for name in ('cpu_health', 'storage_health', 'gpu_health'):
            self.assertEqual('Not checked', self.badge(name).text(), name)
        self.assertIn('#7f8c8d', self.badge('cpu_health').styleSheet())

    def fake_engine(self, health, volumes):
        class Stub:
            def get_full_system_report(self_inner):
                return {'cpu': {'physical_cores': 4, 'logical_cores': 8,
                                'current_frequency': '100 MHz', 'usage_percent': 7.5,
                                'max_frequency': '200 MHz'},
                        'memory': {'used': '1 GB', 'total': '2 GB', 'percent': 50.0,
                                   'available': '1 GB', 'swap_used': '0 GB',
                                   'swap_total': '2 GB'},
                        'os': {'os': 'Windows', 'os_release': '11', 'os_version': '10',
                               'architecture': 'x64', 'processor': 'Intel64',
                               'python_version': '3.11'},
                        'storage': {'volumes': volumes, 'reasons': []},
                        'gpu': [adapter('MARKER-GPU')],
                        'gpu_text': 'MARKER-GPU TEXT',
                        'gpu_reasons': ['current load: MARKER'],
                        'opengl': {'vendor': 'V', 'renderer': 'R', 'version': '1'},
                        'dependencies': {'required': {}, 'optional': {}},
                        'health_checks': health,
                        'recent_errors': [], 'timestamp': 'now'}

            def get_recommendations(self_inner, health_arg=None):
                return ['Warning: MARKER-ADVICE']
        self.tab.diagnostic_engine = Stub()

    def test_132_quick_check_prints_the_backends_sentence(self):
        health = {'cpu': {'status': 'healthy', 'message': 'm'},
                  'memory': {'status': 'healthy', 'message': 'm'},
                  'disk': {'status': 'critical', 'message': '9.9 GB free on Q:\\ (MARKERDISK)'},
                  'gpu': {'status': 'healthy', 'message': 'm'},
                  'dependencies': {'status': 'healthy', 'message': 'm'}}
        self.fake_engine(health, [volume('C:\\')])
        self.tab.run_quick_check()
        text = self.tab.diagnostic_results.toPlainText()
        self.assertIn('[Critical] Storage: 9.9 GB free on Q:\\ (MARKERDISK)', text, text)
        self.assertIn('MARKER-GPU', text)
        self.assertIn('Issues detected', text)
        self.assertEqual('Critical', self.badge('storage_health').text(),
                         'the badge and the line were given the same check and disagreed')

    def test_133_full_diagnostic_prints_the_volumes_it_was_given(self):
        health = {name: {'status': 'healthy', 'message': 'all quiet on ' + name}
                  for name in ('cpu', 'memory', 'disk', 'gpu', 'dependencies')}
        self.fake_engine(health, [volume('C:\\', 90.0),
                                 volume('D:\\', 10.0, media=None, disk=None)])
        self.tab.run_full_diagnostic()
        text = self.tab.diagnostic_results.toPlainText()
        self.assertIn('=== STORAGE ===', text)
        self.assertIn('C:\\ [NTFS]: 180.0 GB used of 200.0 GB (90.0%) - SSD, TestDisk', text)
        self.assertIn('disk kind unknown', text, 'an unknown drive kind printed nothing')
        self.assertIn('MARKER-ADVICE', self.tab.issues_table.item(0, 0).text())
        self.assertEqual('Warning', self.tab.issues_table.item(0, 1).text())

    def test_134_dependency_table_is_the_engines_rows(self):
        deps = {'required': {'trimesh': {'installed': True, 'version': '4.7.4', 'status': 'OK'}},
                'optional': {'gone': {'installed': False, 'version': None,
                                      'status': 'Not Installed'}}}
        with mock.patch.object(DependencyChecker, 'check_all_dependencies',
                               return_value=deps):
            self.tab.run_dependency_check()
        text = self.tab.diagnostic_results.toPlainText()
        self.assertIn('[Installed] trimesh: 4.7.4', text)
        self.assertIn('[Not Installed] gone', text)

    def test_135_no_fabricated_number_survives_in_the_pane(self):
        """The four invented telemetry figures are gone from the code, not only from the screen.

        The comment that records their deletion repeats them, so this reads the parsed file:
        a comment cannot paint anything, and a string constant in here is a string some code
        hands to a widget.
        """
        with open(os.path.join(ROOT, 'src', 'ui', 'performance_tab.py'),
                  encoding='utf-8') as handle:
            tree = ast.parse(handle.read())
        literals = [node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        for invented in ('45%', '6,847', '72°C', '285W'):
            self.assertEqual([], [text for text in literals if invented in text],
                              f'the invented figure {invented} is painted again')
        calls = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertEqual([], [call for call in calls
                              if 'disk_usage' in call and "'/'" in call],
                         'the pane asked the start-up drive again')

    def test_136_a_check_that_never_ran_is_not_counted_as_healthy(self):
        """The five lines are the five checks, and a missing one is visible in both.

        The overall line counted `health.values()`, so a report whose storage check never
        ran printed "All systems operational" beside a CPU row that said otherwise - and
        the per-line mark fell back to `[OK]`, the word a passing check earns.
        """
        health = {'memory': {'status': 'healthy', 'message': 'm'},
                  'gpu': {'status': 'healthy', 'message': 'm'},
                  'dependencies': {'status': 'healthy', 'message': 'm'}}
        self.fake_engine(health, [volume('C:\\')])
        self.tab.run_quick_check()
        text = self.tab.diagnostic_results.toPlainText()
        self.assertIn('[Not checked] CPU:', text, text)
        self.assertIn('[Not checked] Storage: no storage check ran', text, text)
        self.assertIn('Issues detected', text, 'the overall line counted only what answered')


class Test14VolumeDiskJoin(unittest.TestCase):
    """Which disk a drive letter sits on, and what gets said when Windows cannot tell.

    Nine partitions can sit on one physical disk, so "is this an SSD" is answered per drive
    letter by a two-step join: letter to disk number, disk number to disk record. Every way
    that join can come up short is a reason the user reads, and the byte sizes - which always
    come from a different question - keep arriving regardless.
    """

    Partition = collections.namedtuple('Partition', 'device mountpoint fstype opts')
    Usage = collections.namedtuple('Usage', 'total used free percent')

    def read(self, letters='CD', disks=None, disks_reason='', partitions=None,
             partitions_reason='', usage=None):
        seen = []
        rows = {SystemInfo.CIM_DISK: {'rows': disks or [], 'reason': disks_reason},
                SystemInfo.CIM_PARTITIONS: {'rows': partitions or [],
                                            'reason': partitions_reason}}

        def answer(command, *args):
            seen.append(command)
            return rows[command]

        parts = [self.Partition(letter + ':\\', letter + ':\\', 'NTFS', 'rw')
                 for letter in letters]
        sizes = usage or self.Usage(200 * 1024 ** 3, 50 * 1024 ** 3,
                                    150 * 1024 ** 3, 25.0)
        with mock.patch.object(psutil, 'disk_partitions', return_value=parts), \
             mock.patch.object(psutil, 'disk_usage', return_value=sizes), \
             mock.patch.object(SystemInfo, '_cim_rows', side_effect=answer):
            got = SystemInfo.get_storage_info()
        got['asked'] = seen
        return got

    def row(self, got, letter):
        return next(one for one in got['volumes'] if one['mountpoint'] == letter + ':\\')

    def test_140_each_letter_gets_the_disk_it_sits_on(self):
        got = self.read(disks=[{'DeviceId': '0', 'FriendlyName': 'Fast A', 'MediaType': 4},
                               {'DeviceId': '1', 'FriendlyName': 'Slow B', 'MediaType': 3}],
                       partitions=[{'DiskNumber': 0, 'DriveLetter': 'C', 'Type': 'Basic'},
                                   {'DiskNumber': 1, 'DriveLetter': 'D', 'Type': 'Basic'}])
        self.assertEqual(('SSD', 'Fast A'),
                         (self.row(got, 'C')['media_type'], self.row(got, 'C')['disk']))
        self.assertEqual(('HDD', 'Slow B'),
                         (self.row(got, 'D')['media_type'], self.row(got, 'D')['disk']),
                         'both letters were answered with one disk')
        self.assertEqual([], got['reasons'])

    def test_141_an_unknown_media_type_keeps_its_number(self):
        got = self.read(disks=[{'DeviceId': '0', 'FriendlyName': 'Fast A', 'MediaType': 7},
                               {'DeviceId': '1', 'FriendlyName': 'Slow B', 'MediaType': 3}],
                       partitions=[{'DiskNumber': 0, 'DriveLetter': 'C', 'Type': 'Basic'},
                                   {'DiskNumber': 1, 'DriveLetter': 'D', 'Type': 'Basic'}])
        self.assertEqual('disk kind 7', self.row(got, 'C')['media_type'],
                         'a kind this app has no name for was left blank')
        self.assertTrue(any('kind 7' in reason and 'Fast A' in reason
                            for reason in got['reasons']), str(got['reasons']))
        self.assertEqual('HDD', self.row(got, 'D')['media_type'],
                         'one unknown kind silenced the letter that did have an answer')

    def test_142_a_letter_with_no_partition_is_left_unlabelled(self):
        got = self.read(partitions=[], disks=[{'DeviceId': '0', 'FriendlyName': 'Fast A',
                                               'MediaType': 4}])
        for letter in 'CD':
            self.assertIsNone(self.row(got, letter)['media_type'])
            self.assertIsNone(self.row(got, letter)['disk'])
            self.assertEqual(150 * 1024 ** 3, self.row(got, letter)['free_bytes'],
                             'the disk join failing lost the sizes that came from psutil')
        self.assertEqual(2, len(got['reasons']), str(got['reasons']))
        self.assertTrue(all('no partition carries the drive letter' in reason
                            for reason in got['reasons']), str(got['reasons']))

    def test_143_a_partition_on_an_unlisted_disk_is_explained(self):
        got = self.read(disks=[{'DeviceId': '0', 'FriendlyName': 'Fast A', 'MediaType': 4}],
                        partitions=[{'DiskNumber': 5, 'DriveLetter': 'D', 'Type': 'Basic'}])
        self.assertIsNone(self.row(got, 'D')['media_type'])
        self.assertTrue(any('disk 5' in reason and 'did not list' in reason
                            for reason in got['reasons']), str(got['reasons']))
        self.assertTrue(any('C' in reason for reason in got['reasons']),
                        'the letter with no partition at all went unexplained')

    def test_144_the_disk_query_failing_is_one_reason_not_two(self):
        got = self.read(disks_reason='Windows said no')
        self.assertEqual(['which kind of disk: Windows said no'], got['reasons'])
        self.assertEqual([SystemInfo.CIM_DISK], got['asked'],
                         'a second question was asked after the first was refused')
        for letter in 'CD':
            self.assertIsNone(self.row(got, letter)['media_type'])

    def test_145_a_disk_with_no_name_still_reports_its_kind(self):
        got = self.read(letters='C', disks=[{'DeviceId': '0', 'MediaType': 4}],
                        partitions=[{'DiskNumber': 0, 'DriveLetter': 'C', 'Type': 'Basic'}])
        self.assertEqual('SSD', self.row(got, 'C')['media_type'])
        self.assertIsNone(self.row(got, 'C')['disk'],
                          'a missing name was filled with something')

    def test_146_the_second_query_refusing_is_its_own_reason(self):
        got = self.read(disks=[{'DeviceId': '0', 'FriendlyName': 'Fast A', 'MediaType': 4}],
                        partitions_reason='shell access denied')
        self.assertIn('which disk a drive letter sits on: shell access denied', got['reasons'])
        self.assertEqual(3, len(got['reasons']),
                         f'only some of the letters went unlabelled: {got["reasons"]}')
        self.assertIsNone(self.row(got, 'C')['media_type'],
                          'a letter was matched to no disk and labelled anyway')


def log_row(level='ERROR', message='the mesh has no faces',
            component='src.features.mesh', at=None):
    """One record in the exact shape the Diagnostics pane keeps."""
    stamp = (at if isinstance(at, str)
             else (at or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'))
    return {'timestamp': stamp, 'level': level, 'component': component,
            'message': message,
            'full_text': f'[{stamp}] {level}: [{component}] {message}'}


def proc(**over):
    """A process reading, with the fields the panes read and nothing else."""
    row = {'pid': 4242, 'started_at': '2026-11-06T09:00:00', 'uptime_seconds': 12.5,
           'rss_mb': 512.25, 'vms_mb': 1024.0, 'peak_rss_mb': 600.5, 'threads': 9,
           'open_files': 4, 'gc_objects': 54321, 'failures': []}
    row.update(over)
    return row


def machine_mem(**over):
    row = {'total': '16.00 GB', 'used': '12.00 GB', 'available': '4.00 GB',
           'percent': 75.0, 'swap_total': '18.00 GB', 'swap_used': '1.00 GB',
           'swap_percent': 5.5}
    row.update(over)
    return row


def frames(**over):
    """A frame-clock answer: nothing measured, unless a test says frames were drawn."""
    row = {'frames': 0, 'window_seconds': 1.0, 'fps': None, 'frame_time_ms': None,
           'slowest_frame_ms': None, 'sources': [], 'total_frames': 0,
           'last_frame_seconds_ago': None, 'failures': 0, 'last_failure': None,
           'blocked': False, 'reason': 'no 3D view has drawn a frame since the app started',
           'measured_at': time.time()}
    row.update(over)
    return row


class Test15LogArithmetic(unittest.TestCase):
    """Windows and counts over the records the pane holds, and the files it writes.

    Everything here is arithmetic on rows the app itself produced. The analysis this
    replaces printed 1,247 records, a 2.3% error rate, a 156 ms response time and three
    named issues with a fix each, and none of those figures came from a measurement.
    """

    def setUp(self):
        self.engine = DiagnosticEngine()
        self.dir = tempfile.mkdtemp(prefix='rf6j2-')

    def tearDown(self):
        for name in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, name))
        os.rmdir(self.dir)

    def test_150_a_window_keeps_only_the_records_its_own_time_places_inside(self):
        now = datetime.now()
        rows = [log_row(at=now - timedelta(seconds=10)),
                log_row(at=now - timedelta(hours=2)),
                log_row(at=now - timedelta(hours=25)),
                log_row(at='not a time at all')]
        for window, expected in (('Last Hour', 1), ('Last 6 Hours', 2), ('Last Month', 3)):
            got = self.engine.rows_in_window(rows, window)
            self.assertEqual(expected, len(got['rows']),
                             f'{window} kept {len(got["rows"])} of {len(rows)} rows')
            self.assertEqual(1, got['unparsed'],
                             f'{window} dropped the unreadable row silently')
            self.assertIsNone(got['reason'])
            self.assertAlmostEqual(got['cutoff'],
                                   time.time() - DiagnosticEngine.LOG_WINDOWS[window],
                                   delta=5.0)

    def test_151_custom_range_refuses_by_name_instead_of_becoming_the_whole_log(self):
        got = self.engine.rows_in_window([log_row()], 'Custom Range')
        self.assertEqual([], got['rows'])
        self.assertIsNone(got['cutoff'])
        self.assertIn('Custom Range', got['reason'])
        for window in DiagnosticEngine.LOG_WINDOWS:
            self.assertIn(window, got['reason'], f'{window} was not offered as an answer')

    def test_152_the_summary_is_a_count_of_the_rows_it_was_given(self):
        rows = ([log_row(message='the mesh has no faces') for _ in range(4)]
                + [log_row(level='WARNING', message='cache is full', at=datetime.now()
                           - timedelta(seconds=30)),
                   log_row(level='INFO', message='loaded 12 files',
                           at=datetime.now() - timedelta(seconds=90))])
        got = self.engine.summarise_log_rows(rows)
        self.assertEqual(6, got['total'])
        self.assertEqual(4, got['errors'])
        self.assertEqual(66.7, got['error_rate_percent'])
        self.assertEqual([('ERROR', 4), ('WARNING', 1), ('INFO', 1)],
                         sorted(got['by_level'], key=lambda pair: -pair[1]))
        self.assertEqual(0, got['rows_without_a_readable_time'])
        self.assertEqual(1, len(got['repeated']))
        self.assertEqual(4, got['repeated'][0]['count'])
        self.assertEqual('the mesh has no faces', got['repeated'][0]['message'])
        self.assertEqual('src.features.mesh', got['repeated'][0]['component'])
        self.assertLessEqual(got['repeated'][0]['first_at'], got['repeated'][0]['last_at'])
        self.assertGreater(got['span_seconds'], 0)

    def test_153_no_rows_is_not_a_zero_percent_of_nothing(self):
        got = self.engine.summarise_log_rows([])
        self.assertEqual(0, got['total'])
        self.assertIsNone(got['error_rate_percent'])
        self.assertIsNone(got['first_at'])
        self.assertIsNone(got['span_seconds'])
        self.assertEqual([], got['repeated'])

    def test_154_each_kind_of_report_writes_the_file_its_name_promises(self):
        rows = [log_row(), log_row(level='WARNING')]
        expected = {'Crash Report': ('error_log', 'records_the_pane_saw', 'process'),
                    'Error Summary': ('error_log', 'records_the_pane_saw'),
                    'Performance Report': ('cpu', 'frames', 'gpu'),
                    'Memory Report': ('objects', 'memory'),
                    'System Report': ('system',)}
        for kind, keys in expected.items():
            path = os.path.join(self.dir, f'{kind.replace(" ", "_")}.json')
            got = self.engine.export_error_report(kind, rows, output_path=path)
            self.assertEqual(path, got['path'], got)
            with open(path, encoding='utf-8') as handle:
                payload = json.load(handle)
            self.assertEqual(kind, payload['report_type'])
            for key in keys:
                self.assertIn(key, payload, f'{kind} is missing its {key} reading')
            self.assertIn('build', payload, f'{kind} forgot which interpreter it describes')

    def test_155_a_kind_the_engine_cannot_fill_writes_nothing(self):
        before = os.listdir(self.dir)
        got = self.engine.export_error_report('Custom Report', [log_row()])
        self.assertIsNone(got['path'])
        self.assertIn('Custom Report', got['reason'])
        for kind in DiagnosticEngine.REPORT_KINDS:
            self.assertIn(kind, got['reason'], f'{kind} was not offered instead')
        self.assertEqual(before, os.listdir(self.dir), 'a refusal still wrote a file')

    def test_156_the_object_walk_asks_no_object_for_anything(self):
        """A count must not probe attributes: some attributes load a library to answer.

        `getattr(obj, 'nbytes')` over every live object asked a `ctypes` lazy library for
        a DLL called 'nbytes' and raised FileNotFoundError out of the middle of the
        memory snapshot. The size lookup is a type test now, and this pins it.
        """
        class Exploding:
            def __getattr__(self, name):
                raise RuntimeError(f'asking for {name} would load something')

        keep = Exploding()
        payload = SystemInfo.live_object_counts(limit=100000)
        self.assertIn('Exploding', [name for name, _count in payload['classes']],
                      'the walk died before it counted the test object')
        self.assertGreaterEqual(payload['scanned'], 1000)
        self.assertGreaterEqual(payload['distinct_classes'], 10)
        self.assertIn('ndarray', payload['sized_types'])
        self.assertIn('rss_mb', payload['process'])

    def test_157_this_processes_peak_is_a_reading_not_a_default(self):
        got = SystemInfo.get_process_info()
        self.assertEqual([], got['failures'], str(got['failures']))
        self.assertGreater(got['peak_rss_mb'], 0.0)
        self.assertGreater(got['rss_mb'], 0.0)
        self.assertLessEqual(got['rss_mb'], 10 * got['peak_rss_mb'])

    def test_158_the_peak_is_read_under_the_name_the_records_of_either_platform_use(self):
        """The second name in the fallback is proved with a shaped record, not on this machine.

        `peak_wset` only exists on Windows and `peak_rss` only exists on Linux and macOS, so
        whichever way this box answers, one of the two branches has never been watched. A
        memory record built to the other shape is what watches them.
        """
        import collections
        import psutil

        Windows = collections.namedtuple('Windows', 'rss vms peak_wset')
        Other = collections.namedtuple('Other', 'rss vms peak_rss')
        Both = collections.namedtuple('Both', 'rss vms peak_wset peak_rss')
        Neither = collections.namedtuple('Neither', 'rss vms')

        class Recorded:
            def __init__(self, info):
                self.pid = 4242
                self._info = info

            def memory_info(self):
                return self._info

            def create_time(self):
                return time.time() - 60.0

            def num_threads(self):
                return 3

            def open_files(self):
                return []

        meg = 1024 * 1024
        for info, peak, failures in (
                (Windows(20 * meg, 100 * meg, 40 * meg), 40.0, []),
                (Other(20 * meg, 100 * meg, 30 * meg), 30.0, []),
                (Both(20 * meg, 100 * meg, 40 * meg, 90 * meg), 40.0, []),
                (Neither(20 * meg, 100 * meg), None, ['no peak field'])):
            with mock.patch.object(psutil, 'Process', lambda pid, info=info: Recorded(info)):
                got = SystemInfo.get_process_info()
            self.assertEqual(peak, got['peak_rss_mb'],
                             f'{info._fields}: the peak read was {got["peak_rss_mb"]}')
            self.assertEqual(20.0, got['rss_mb'])
            for wanted in failures:
                self.assertIn(wanted, ' '.join(got['failures']))
            if not failures:
                self.assertEqual([], got['failures'], str(got['failures']))
        with mock.patch.object(psutil, 'Process',
                               lambda pid: Recorded(Neither(20 * meg, 100 * meg))):
            named = SystemInfo.get_process_info()
        self.assertIn('rss, vms', ' '.join(named['failures']),
                      'the refusal does not say which fields the record actually had')


class Test16DiagnosticsStatePane(unittest.TestCase):
    """The six buttons under Debug / Reports / Analysis, painting only what was measured."""

    BUILD = {'os': 'TestOS 1.2 (build 9)', 'architecture': 'TESTARCH',
             'processor': 'TestChip 3.0', 'python': '9.9.9',
             'python_implementation': 'TestPython', 'packaged': False,
             'qt_runtime': '9.8.7', 'pyqt': '6.6.6'}

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from src.ui.diagnostics_tab import DiagnosticsTab
        from src.features.diagnostic_engine import ErrorLogger
        self.dir = tempfile.mkdtemp(prefix='rf6j2-pane-')
        self.tab = DiagnosticsTab()
        self.tab.show()
        self.tab.diagnostic_engine.error_logger = ErrorLogger(self.dir)

    def tearDown(self):
        for name in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, name))
        os.rmdir(self.dir)
        self.tab.close()

    def pump(self, seconds=60.0, until=None):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.02)
            if until and until():
                return True
        return bool(until and until())

    def painted(self, widget, marker, seconds=60.0):
        self.assertTrue(self.pump(seconds, lambda: marker in widget.toPlainText()),
                        f'the pane never painted {marker!r}')
        return widget.toPlainText()

    class FakeClock:
        def __init__(self, stats):
            self._stats = stats

        def stats(self, window_seconds=1.0):
            return self._stats

    def patches(self, **over):
        """Every reading the dump takes, held still so a painted line can be matched."""
        from src.ui import diagnostics_tab as pane
        build = dict(Test16DiagnosticsStatePane.BUILD)
        build.update(over.pop('build', {}))
        stack = [
            mock.patch.object(SystemInfo, 'get_build_info', return_value=build),
            mock.patch.object(SystemInfo, 'get_process_info',
                              return_value=over.get('process', proc())),
            mock.patch.object(SystemInfo, 'get_memory_info',
                              return_value=over.get('memory', machine_mem())),
            mock.patch.object(pane, 'shared_clock',
                              lambda: self.FakeClock(over.get('frames', frames()))),
        ]
        return stack

    def apply_patches(self, stack):
        for patcher in stack:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_160_the_dump_names_the_interpreter_this_process_really_runs(self):
        self.tab.dump_application_state()
        text = self.painted(self.tab.debug_output, 'Application State Dump')
        self.assertIn(sys.version.split()[0], text)
        self.assertIn('CPython', text)
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        self.assertIn(PYQT_VERSION_STR, text)
        self.assertIn(QT_VERSION_STR, text)
        for invented in ('Windows 11', 'Python Version: 3.11.5', 'PyQt Version: 6.5.2',
                         'Loaded Models: 3', 'Active Processes: 12',
                         'GPU Acceleration: Enabled', 'Active Objects: 45,232',
                         'building.obj', 'Total Allocated: 1.2 GB', 'Peak Usage: 1.8 GB',
                         'Cache cleared (150MB freed)'):
            self.assertNotIn(invented, text, f'the dump printed {invented!r} again')

    def test_161_the_dump_paints_the_readings_it_was_handed(self):
        stack = self.patches()
        self.apply_patches(stack)
        self.tab.dump_application_state()
        text = self.painted(self.tab.debug_output, 'Application State Dump')
        self.assertIn('TestOS 1.2 (build 9) on TESTARCH', text)
        self.assertIn('Python: 9.9.9 (TestPython), a source tree', text)
        self.assertIn('Qt runtime: 9.8.7, PyQt: 6.6.6', text)
        self.assertIn('512.25 MB now, 600.5 MB at its peak; virtual 1024.0 MB', text)
        self.assertIn('Threads: 9, open files: 4, live objects: 54321', text)
        self.assertIn('12.00 GB used of 16.00 GB (75.0%)', text)
        self.assertIn('Frames: nothing measured - '
                      'no 3D view has drawn a frame since the app started', text)

    def test_162_a_missing_peak_is_said_whole_not_spelled_into_a_number(self):
        stack = self.patches(process=proc(peak_rss_mb=None,
                                         failures=['peak resident size: no field here']))
        self.apply_patches(stack)
        self.tab.dump_application_state()
        text = self.painted(self.tab.debug_output, 'Application State Dump')
        self.assertIn('peak not reported', text)
        self.assertIn('not reported: peak resident size: no field here', text)
        self.assertIn('Resident memory: 512.25 MB now, peak not reported; '
                      'virtual 1024.0 MB', text)
        self.assertNotIn('None MB', text)

    def test_163_a_frozen_build_says_so(self):
        stack = self.patches(build={'packaged': True})
        self.apply_patches(stack)
        self.tab.dump_application_state()
        text = self.painted(self.tab.debug_output, 'Application State Dump')
        self.assertIn('a frozen build', text)

    def test_164_frames_are_printed_even_when_no_view_is_in_reach(self):
        stack = self.patches(frames=frames(frames=5, fps=48.0, frame_time_ms=20.8,
                                          slowest_frame_ms=31.2, sources=['ViewerA'],
                                          total_frames=5, window_seconds=1.0))
        self.apply_patches(stack)
        self.tab.dump_application_state()
        text = self.painted(self.tab.debug_output, 'Application State Dump')
        self.assertIn('48.0 fps from 5 frame(s) drawn by ViewerA, 20.8 ms average, '
                      '31.2 ms slowest', text)

    def test_165_a_standalone_pane_names_what_it_cannot_reach(self):
        self.tab.dump_application_state()
        text = self.painted(self.tab.debug_output, 'Application State Dump')
        self.assertIn('not inside the main window', text)
        self.assertIn('which holds no job queue', text)

    def test_166_inside_the_window_the_dump_reaches_the_views_and_the_queue(self):
        from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout

        class Job:
            def __init__(self, start, end):
                self.start_time, self.end_time = start, end

        class Manager:
            def get_queue_stats(self):
                return {'total': 3, 'pending': 1, 'rendering': 0, 'completed': 2,
                        'failed': 0, 'paused': 0}

            def get_all_jobs(self):
                now = time.time()
                return [Job(now - 30.0, now), Job(now - 10.0, now), Job(None, None)]

        window = QMainWindow()
        holder = QWidget()
        holder.current_file_path = os.path.join(self.dir, 'MARKER-model.obj')
        quiet = QWidget()
        quiet.current_file_path = None
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.tab)
        layout.addWidget(holder)
        layout.addWidget(quiet)
        window.setCentralWidget(central)
        window.job_manager = Manager()
        self.addCleanup(window.close)

        self.tab.dump_application_state()
        text = self.painted(self.tab.debug_output, 'Application State Dump')
        self.assertIn('2 view(s) found, 1 holding a file', text)
        self.assertIn('MARKER-model.obj', text)
        self.assertIn('3 job(s): 1 waiting, 0 running, 0 paused, 2 finished, 0 failed', text)
        self.assertIn('20.0 s on average, 30.0 s at the slowest', text)
        self.assertNotIn('which holds no job queue', text)

    def test_167_the_snapshot_counts_objects_and_refuses_the_price_list(self):
        payload = {'scanned': 54321, 'classes': [('tuple', 1000), ('dict', 900),
                                                 ('list', 800), ('function', 700),
                                                 ('type', 600)],
                   'distinct_classes': 777, 'array_like_count': 3, 'array_bytes': 4096,
                   'array_mb': 0.0, 'sized_types': 'ndarray, bytes',
                   'process': proc(), 'machine_memory': machine_mem()}
        with mock.patch.object(SystemInfo, 'live_object_counts', return_value=payload):
            self.tab.take_memory_snapshot()
            text = self.painted(self.tab.debug_output, 'Memory Snapshot')
        self.assertIn('(54321 objects of 777 classes)', text)
        self.assertIn('1000  tuple', text)
        self.assertIn('3 object(s) of these types: ndarray, bytes', text)
        self.assertIn('4096 bytes (0.0 MB)', text)
        self.assertIn('12.00 GB used of 16.00 GB', text)
        self.assertIn('tracemalloc', text, 'the refusal stopped naming what is missing')
        for invented in ('3D Viewer: 245 MB', 'Model Data: 156 MB', 'Textures: 89 MB',
                         'Cache: 67 MB', 'UI Framework: 34 MB', 'Cached Models: 8',
                         'Memory Pools: 12', 'Total: 619 MB'):
            self.assertNotIn(invented, text, f'the snapshot printed {invented!r} again')

    def test_168_a_report_row_carries_the_file_it_was_written_to(self):
        from PyQt6.QtCore import Qt
        self.tab.generate_debug_report()
        text = self.painted(self.tab.debug_output, 'Wrote the full system reading')
        self.assertEqual(1, self.tab.reports_list.count())
        row = self.tab.reports_list.item(0)
        path = row.data(Qt.ItemDataRole.UserRole)
        self.assertIn(path, text)
        self.assertTrue(os.path.exists(path), f'the row points at nothing: {path}')
        preview = self.painted(self.tab.report_preview, 'Read from:')
        self.assertIn(path, preview)
        self.assertIn('"cpu"', preview, 'the preview is not showing the file')
        self.assertEqual(os.path.getsize(path),
                         int(preview.splitlines()[2].split(' bytes')[0]))

    def test_169_a_type_the_engine_cannot_fill_adds_no_row(self):
        self.tab.generate_report_combo.setCurrentText('Custom Report')
        self.tab.generate_error_report()
        text = self.painted(self.tab.debug_output, 'No file was written')
        self.assertIn('Custom Report', text)
        self.assertEqual(0, self.tab.reports_list.count(), 'a refusal still added a row')
        self.assertEqual([], [name for name in os.listdir(self.dir) if name.endswith('.json')])

    def test_170_generated_reports_are_readable_after_the_worker_answers(self):
        self.tab.generate_report_combo.setCurrentText('Memory Report')
        self.tab.generate_error_report()
        self.painted(self.tab.debug_output, 'bytes to:')
        row = self.tab.reports_list.item(self.tab.reports_list.count() - 1)
        self.assertTrue(row.text().startswith('Memory Report - '), row.text())
        preview = self.painted(self.tab.report_preview, 'Read from:')
        self.assertIn('"objects"', preview)
        self.assertNotIn('"scanned": null', preview)

    def test_171_the_preview_shows_no_crash_that_never_happened(self):
        from PyQt6.QtCore import Qt
        self.tab.preview_report()
        self.assertIn('Nothing selected', self.tab.report_preview.toPlainText())

        self.tab.reports_list.addItem('Old Report - 2024-08-29 14:30:15')
        self.tab.reports_list.setCurrentRow(0)
        self.tab.preview_report()
        self.assertIn('no file behind it', self.tab.report_preview.toPlainText())

        path = os.path.join(self.dir, 'gone.json')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('{"built": true}')
        item = self.tab.reports_list.item(0)
        item.setData(Qt.ItemDataRole.UserRole, path)
        self.tab.preview_report()
        self.assertIn('"built": true', self.tab.report_preview.toPlainText())
        os.remove(path)
        self.tab.preview_report()
        text = self.tab.report_preview.toPlainText()
        self.assertIn('file this row points at is gone', text)
        for canned in ('mesh_processor.cpp', 'segmentation fault', 'process_vertices',
                       'GPU Memory: 89% used', 'Update graphics drivers'):
            self.assertNotIn(canned, text, f'the canned crash printed {canned!r} again')

    def test_172_the_analysis_counts_the_rows_the_pane_holds(self):
        self.tab.log_entries = ([log_row(message='the mesh has no faces') for _ in range(4)]
                                + [log_row(level='WARNING', message='cache is full')])
        self.tab.analysis_period_combo.setCurrentText('Last Hour')
        self.tab.analyze_logs()
        text = self.painted(self.tab.trends_display, 'Log Analysis - the Last Hour window')
        self.assertEqual('5 of 5 seen', self.tab.total_logs_label.text())
        self.assertEqual('80.0%', self.tab.error_rate_label.text())
        self.assertIn('MB in this process', self.tab.peak_memory_label.text())
        self.assertEqual('nothing recorded', self.tab.crash_count_label.text())
        self.assertIn('80.0% - 4 ERROR of 5 records', text)
        self.assertIn('the mesh has no faces - 4 time(s)', text)
        self.assertEqual(1, self.tab.frequent_issues_table.rowCount())
        cells = [self.tab.frequent_issues_table.item(0, col).text() for col in range(4)]
        self.assertEqual('4 times', cells[1])
        self.assertEqual('src.features.mesh', cells[3])
        self.assertEqual('Logged By',
                         self.tab.frequent_issues_table.horizontalHeaderItem(3).text())

    def test_173_no_invented_statistics_survive_the_analysis(self):
        self.tab.log_entries = [log_row()]
        self.tab.analysis_period_combo.setCurrentText('Last Hour')
        self.tab.analyze_logs()
        self.painted(self.tab.trends_display, 'Log Analysis')
        for label in (self.tab.total_logs_label, self.tab.error_rate_label,
                      self.tab.avg_response_label, self.tab.peak_memory_label,
                      self.tab.crash_count_label):
            self.assertNotIn(label.text(), ('1,247', '2.3%', '156ms', '1.8GB', '0'))
        text = self.tab.trends_display.toPlainText()
        for invented in ('Performance degrades after 2+ hours', 'GPU driver timeouts',
                         'Unusual memory allocation pattern at 14:30-15:00',
                         'Implement automatic GPU memory management'):
            self.assertNotIn(invented, text, f'the trends printed {invented!r} again')

    def test_174_a_window_no_control_can_give_leaves_no_stale_figure(self):
        self.tab.log_entries = [log_row() for _ in range(3)]
        self.tab.analysis_period_combo.setCurrentText('Last Hour')
        self.tab.analyze_logs()
        self.painted(self.tab.trends_display, 'Log Analysis')
        self.tab.analysis_period_combo.setCurrentText('Custom Range')
        self.tab.analyze_logs()
        self.painted(self.tab.trends_display, 'Nothing was counted')
        for label in (self.tab.total_logs_label, self.tab.error_rate_label,
                      self.tab.avg_response_label, self.tab.peak_memory_label,
                      self.tab.crash_count_label):
            self.assertEqual('not measured', label.text(), label.text())
        self.assertEqual(0, self.tab.frequent_issues_table.rowCount())

    def test_175_crash_records_are_counted_from_the_file_they_live_in(self):
        from src.features.diagnostic_engine import ErrorLogger
        logger = ErrorLogger(self.dir)
        logger.log_error('ValueError', 'first crash')
        logger.log_error('OSError', 'second crash')
        self.tab.diagnostic_engine.error_logger = logger
        self.tab.analysis_period_combo.setCurrentText('Last Hour')
        self.tab.analyze_logs()
        text = self.painted(self.tab.trends_display, 'Log Analysis')
        self.assertEqual('2 record(s)', self.tab.crash_count_label.text())
        self.assertIn('2 record(s)', text)

        os.remove(logger.log_file)
        self.tab.analyze_logs()
        self.painted(self.tab.trends_display, 'Log Analysis')
        self.assertEqual('nothing recorded', self.tab.crash_count_label.text())
        self.assertIn('does not exist yet', self.tab.trends_display.toPlainText())

    def test_176_no_measurement_runs_on_the_interface_thread(self):
        """Every button that reads the machine hands the reading to a worker.

        `run_quick_check` and its neighbours used to call psutil, WMI and the drive scan
        from the click handler, which is how the pane stopped painting while it claimed to
        be working. A measuring call is allowed only inside something the worker runs, so
        this walks each entry point's tree and flags any call at the handler's own depth.
        """
        import ast
        import inspect
        import textwrap
        from src.ui.diagnostics_tab import DiagnosticsTab

        forbidden = ('get_process_info', 'live_object_counts', 'get_cpu_info',
                     'export_report', 'export_error_report', 'rows_in_window',
                     'summarise_log_rows')

        def depth_of_calls(node, depth):
            found = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Call):
                    name = ast.unparse(child.func).rsplit('.', 1)[-1]
                    if name in forbidden:
                        found.append((depth, ast.unparse(child)))
                    found.extend(depth_of_calls(child, depth))
                elif isinstance(child, (ast.FunctionDef, ast.Lambda)):
                    found.extend(depth_of_calls(child, depth + 1))
                else:
                    found.extend(depth_of_calls(child, depth))
            return found

        for name in ('dump_application_state', 'take_memory_snapshot',
                     'generate_debug_report', 'generate_error_report', 'analyze_logs'):
            source = textwrap.dedent(inspect.getsource(getattr(DiagnosticsTab, name)))
            body = ast.parse(source).body[0]
            self.assertIn('run_off_thread', ast.unparse(body),
                          f'{name} measures on the UI thread')
            offenders = [text for depth, text in depth_of_calls(body, 0) if depth == 0]
            self.assertEqual([], offenders, f'{name} measures where the window waits')

    def test_177_a_measurement_that_raises_is_reported_not_swallowed(self):
        def explode():
            raise RuntimeError('the probe raised')

        self.tab.run_off_thread(explode, lambda payload: None, 'Working...')
        text = self.painted(self.tab.debug_output, 'RuntimeError')
        self.assertIn('the probe raised', text)
        self.assertIn('raised before it answered', text)

    def test_177b_the_hardware_test_button_hands_the_engine_a_worker_it_can_answer(self):
        """The house `Worker` always passes `progress_callback`, so this one has to take it.

        `run_engine_kinds` is the path behind the Diagnostics pane's hardware test, and until
        now nothing drove it: the pane's answer was only ever read by the person clicking the
        button. A `worker_func` that cannot take the argument is a TypeError painted where a
        benchmark belongs, so both channels are read here and the engine is asked whether it
        was given the callback at all.
        """
        import src.ui.diagnostics_tab as pane
        asked = []

        class FakeEngine:
            def run(self, kind, duration=2.0, record=False, should_stop=None,
                    progress_callback=None, **work):
                asked.append((kind, callable(progress_callback)))
                return {'kind': kind, 'ran': f'{kind} work on this machine', 'reason': '',
                        'result': {'multiplies_per_second': 1000.0}, 'against': {'reason': ''},
                        'machine': {}, 'work': {},
                        'stored': {'recorded': False, 'reason': 'the test engine'}}

        real = pane.benchmark_engine
        pane.benchmark_engine = lambda: FakeEngine()
        self.addCleanup(setattr, pane, 'benchmark_engine', real)
        self.tab.run_hardware_test()
        answered = self.pump(20, lambda: (
            'Hardware Performance Test Results' in self.tab.diagnostic_results.toPlainText()
            or 'Benchmark failed' in self.tab.diagnostic_results.toPlainText()))
        text = self.tab.diagnostic_results.toPlainText()
        self.assertTrue(answered, 'the hardware test never answered at all')
        self.assertNotIn('Benchmark failed', text,
                        f'the pane took the failure channel instead of the result: {text}')
        self.assertIn('cpu work on this machine', text)
        self.assertIn('memory work on this machine', text)
        self.assertIn('multiplies per second', text)
        self.assertEqual([('cpu', True), ('memory', True)], asked,
                         'the engine was run without the way to report its own progress')
        self.assertEqual('Status: Hardware test completed', self.tab.health_status.text())

    def test_177c_a_hardware_test_that_raises_is_said_out_loud(self):
        """The engine's failure channel is connected, or the pane just stops answering.

        177b proves the success path reaches the screen; it cannot see the error connect
        being deleted, because nothing raises. This runs an engine that dies mid-kind and
        requires the pane to print the exception it was handed, on the same widget the
        benchmark writes to and with the status the person clicking is watching.
        """
        import src.ui.diagnostics_tab as pane

        class DeadEngine:
            def run(self, kind, duration=2.0, record=False, should_stop=None,
                    progress_callback=None, **work):
                raise RuntimeError('the engine died mid-run')

        real = pane.benchmark_engine
        pane.benchmark_engine = lambda: DeadEngine()
        self.addCleanup(setattr, pane, 'benchmark_engine', real)
        self.tab.run_hardware_test()
        text = self.painted(self.tab.diagnostic_results, 'Benchmark failed')
        self.assertIn('RuntimeError', text)
        self.assertIn('the engine died mid-run', text)
        self.assertEqual('Status: Test failed', self.tab.health_status.text())

    def test_178_a_closed_pane_holds_no_log_handler_over_the_app(self):
        """Every pane gets the app's records, and none of them outlives its pane.

        The handler used to be attached once per process, so a second pane attached
        nothing and its table stayed empty; and it stored a *bound signal*, which kept a
        reference into the closed pane's Qt memory - memory the next widget then reused.
        A record logged after that crashed the process, which is what the test run hit
        before the handler was made to hold the pane weakly and detach on `destroyed`.
        """
        import logging
        from PyQt6.QtWidgets import QWidget
        from src.ui.diagnostics_tab import DiagnosticsTab, PaneLogHandler

        def live_handlers():
            return [handler for handler in logging.getLogger().handlers
                    if isinstance(handler, PaneLogHandler) and handler.pane_alive()]

        before = len(live_handlers())
        second = DiagnosticsTab()
        marker = 'the second pane must see this'
        logging.getLogger('probe.component').error(marker)
        end = time.time() + 10
        while time.time() < end:
            self.app.processEvents()
            if (any(marker in row['message'] for row in self.tab.log_entries)
                    and any(marker in row['message'] for row in second.log_entries)):
                break
            time.sleep(0.02)
        self.assertTrue(any(marker in row['message'] for row in self.tab.log_entries),
                        'the first pane stopped receiving records')
        self.assertTrue(any(marker in row['message'] for row in second.log_entries),
                        'a second pane attached nothing: the root logger was claimed by '
                        'whichever pane was built first')
        self.assertEqual(before + 1, len(live_handlers()),
                         'the second pane logged nothing, or double')

        died = []
        second.destroyed.connect(lambda _=None: died.append(True))
        second.deleteLater()
        from PyQt6.QtCore import QEvent
        end = time.time() + 15
        while time.time() < end and not died:
            self.app.processEvents()
            # Deferred deletes only reach a widget once the loop really flushes them,
            # which is what returning to the event loop does in a running app.
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertTrue(died, 'the pane was never destroyed, so the test proved nothing')
        self.assertEqual(before, len(live_handlers()),
                         'a destroyed pane still had a handler on the root logger')

        # A record now must reach the surviving pane and crash nothing, and the memory
        # the closed pane held must be in use by something else first.
        spare = QWidget()
        spare.setObjectName('recycled')
        self.app.processEvents()
        logging.getLogger('probe.component').error('logged after the pane died')
        self.app.processEvents()
        self.assertTrue(any('logged after the pane died' in row['message']
                            for row in self.tab.log_entries),
                        'the surviving pane stopped hearing the app')
        spare.deleteLater()


class Test17CrashRecord(unittest.TestCase):
    """The handler that decides whether the crash count can ever be more than a claim."""

    def test_179_the_unhandled_exception_writes_the_record_the_pane_counts(self):
        import main as app_main
        written = []

        class FakeLogger:
            def log_error(self, error_type, message, traceback_str=None):
                written.append((error_type, message, traceback_str))

        with mock.patch('src.features.diagnostic_engine.ErrorLogger', FakeLogger), \
                mock.patch.object(app_main, 'get_telemetry') as telemetry, \
                mock.patch.object(app_main, 'QMessageBox'):
            try:
                raise ValueError('the probe crashed')
            except ValueError:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                app_main.global_exception_handler(exc_type, exc_value, exc_traceback)

        self.assertEqual(1, len(written), 'the crash reached no file at all')
        self.assertEqual('ValueError', written[0][0])
        self.assertEqual('the probe crashed', written[0][1])
        self.assertIn('ValueError: the probe crashed', written[0][2])
        telemetry.return_value.track_error.assert_called_once()

    def test_180_the_crash_path_swallows_nothing(self):
        with open(os.path.join(ROOT, 'main.py'), encoding='utf-8') as handle:
            source = handle.read()
        tree = ast.parse(source)
        bare = [node for node in ast.walk(tree)
                if isinstance(node, ast.ExceptHandler) and node.type is None]
        self.assertEqual([], [ast.unparse(node) for node in bare],
                         'a bare except is again hiding the failure it should report')
        for name in ('log_error', 'track_error'):
            self.assertIn(name, source, f'the handler stopped using {name}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
