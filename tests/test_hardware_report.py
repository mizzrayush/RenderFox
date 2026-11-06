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
import time
import unittest
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
        from src.utils.file_utils import get_temp_directory
        st = storage(volume('C:\\'), volume('D:\\'), volume('E:\\'))
        picked = SystemInfo.working_volume(st)
        self.assertEqual(os.path.abspath(get_temp_directory())[:2].upper(),
                         picked['mountpoint'][:2].upper())


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
