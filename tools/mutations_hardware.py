"""Mutations for the hardware report suite.

Each entry breaks one sentence the panes tell about this machine - a volume picked the wrong
way, a reason replaced by a number, a second measurement of the same drive, a health word
copied from the wrong check, a library looked up by the wrong name - and names the test that
has to fail for it. A defect the suite does not notice is a hole in the suite, so it gets a
test rather than a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_hardware_report.py \
        tools/mutations_hardware.py
"""

MUTATIONS = [
    # ---- the reading itself: a window, a volume, a disk -------------------------------
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '        per_core = psutil.cpu_percent(interval=0.2, percpu=True)',
        'replace': '        per_core = psutil.cpu_percent(interval=None, percpu=True)',
        'expect': 'test_07',
        'note': 'the CPU figure is read over no window, so it means nothing',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '        target = os.path.abspath(path or get_temp_directory()).upper()',
        'replace': '        target = os.path.abspath(path or os.getcwd()).upper()',
        'expect': 'test_15',
        'note': 'the write volume is guessed from where the process started',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '            if target.startswith(mount) and (best is None',
        'replace': '            if mount in target and (best is None',
        'expect': 'test_14',
        'note': 'a path that only begins with a drive letter counts as that drive',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "                                             or len(mount) > len(best['mountpoint'])):",
        'replace': "                                             or False):",
        'expect': 'test_11',
        'note': 'the first mount that matches wins instead of the most specific one',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '                volume[\'media_type\'] = name or f\'disk kind {raw}\'',
        'replace': '                volume[\'media_type\'] = name',
        'expect': 'test_141',
        'note': 'a drive kind this app has no name for is left blank',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '                if device is None:',
        'replace': '                if False:',
        'expect': 'test_142',
        'note': 'a drive letter no partition carries is matched to a disk anyway',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '                entry = by_device.get(device)',
        'replace': "                entry = by_device.get(device) or disks['rows'][0]",
        'expect': 'test_143',
        'note': 'a disk Windows never listed is answered with the first one it did',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "            if partitions['reason']:",
        'replace': '            if False:',
        'expect': 'test_146',
        'note': 'the second question to Windows failing is swallowed, not said',
    },

    # ---- the adapter: identity, current figures, and the words around them -----------
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '        if not live:',
        'replace': '        if False:',
        'expect': 'test_51',
        'note': 'a reader that answered nothing stops explaining why it answered nothing',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '        if len(live) != len(adapters):',
        'replace': '        if False:',
        'expect': 'test_52',
        'note': 'figures matched in order across disagreeing lists go unstated',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "            adapter['live'] = {'load_percent': round(gpu.load * 100, 1),",
        'replace': "            adapter['live'] = {'load_percent': round(gpu.load, 1),",
        'expect': 'test_50',
        'note': 'a fraction of 1 is printed as a percentage',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "        return {'adapters': adapters, 'reasons': reasons, 'load_reason': load_reason,",
        'replace': "        return {'adapters': adapters, 'reasons': reasons, 'load_reason': None,",
        'expect': 'test_53',
        'note': "the reason no figures arrived stops being a field a pane can read",
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '            lines.append(f"   Vendor: {adapter[\'vendor\'] or \'not reported\'}")',
        'replace': '            lines.append(f"   Vendor: {adapter[\'vendor\']}")',
        'expect': 'test_60',
        'note': 'a field nobody read prints the word None to the user',
    },

    # ---- the health words ------------------------------------------------------------
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '        volume = SystemInfo.working_volume(storage, path)',
        'replace': "        volume = storage['volumes'][0] if storage['volumes'] else None",
        'expect': 'test_23',
        'note': 'the verdict is printed for whichever volume was listed first',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "        if volume['used_percent'] > 95:",
        'replace': "        if volume['used_percent'] > 99:",
        'expect': 'test_20',
        'note': 'a volume nearly full is called healthy',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "        status = 'critical' if usage > 95 else 'warning' if usage > 85 else 'healthy'",
        'replace': "        status = 'healthy'",
        'expect': 'test_80',
        'note': 'the CPU check passes whatever the cores are doing',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "        plural = '' if count == 1 else 's'",
        'replace': "        plural = ''",
        'expect': 'test_72',
        'note': 'two adapters are reported as one adapter',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "        if report.get('load_reason'):",
        'replace': '        if False:',
        'expect': 'test_71',
        'note': 'an adapter nobody can read stops saying so in its verdict',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "            'cpu': cls.check_cpu_usage(cpu),",
        'replace': "            'cpu': cls.check_cpu_usage(),",
        'expect': 'test_90',
        'note': 'a handed reading is ignored and the machine measured twice',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "            'disk': cls.check_disk_space(storage),",
        'replace': "            'disk': cls.check_disk_space(),",
        'expect': 'test_90',
        'note': 'the volume verdict comes from its own second look',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "            'health_checks': HealthChecker.run_all_checks(storage, gpu, cpu),",
        'replace': "            'health_checks': HealthChecker.run_all_checks(),",
        'expect': 'test_93',
        'note': 'a row and its verdict come from two looks a second apart',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '                recommendations.append(f"Warning: {check[\'message\']}")',
        'replace': '                recommendations.append(f"Warning: {name} looked {check[\'status\']}")',
        'expect': 'test_91',
        'note': 'advice is invented from the status word instead of the measured message',
    },

    # ---- the dependency answer -------------------------------------------------------
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "        'pillow': 'PIL',",
        'replace': "        'pillow': 'pillow',",
        'expect': 'test_100',
        'note': 'an installed library is looked up by a name it does not answer to',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "            package_name, package_name.replace('-', '_'))",
        'replace': '            package_name, package_name)',
        'expect': 'test_100',
        'note': 'a hyphenated distribution is searched for with its hyphen',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': '            present = importlib.util.find_spec(module_name) is not None',
        'replace': '            present = importlib.import_module(module_name) is not None',
        'expect': 'test_103',
        'note': 'asking which libraries exist loads every one of them again',
    },
    {
        'file': 'src/features/diagnostic_engine.py',
        'find': "            'installed': present or version is not None,",
        'replace': "            'installed': present,",
        'expect': 'test_105',
        'note': 'a library the installer recorded is called missing',
    },

    # ---- the performance pane --------------------------------------------------------
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        self.gpu_utilization_label = QLabel(GPU_NOT_READ_NOTE)',
        'replace': "        self.gpu_utilization_label = QLabel('45% busy')",
        'expect': 'test_110',
        'note': 'a figure with no measurement behind it is on screen before the button',
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        self.gpu_power_label = QLabel(GPU_POWER_NOTE)',
        'replace': "        self.gpu_power_label = QLabel('285W')",
        'expect': 'test_110',
        'note': 'the pane claims to measure the power the chip draws',
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        volume = SystemInfo.working_volume(self.storage_info)',
        'replace': "        volume = self.storage_info['volumes'][0]",
        'expect': 'test_111',
        'note': 'the storage rows show whichever volume arrived first',
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        if kind:',
        'replace': '        if True:',
        'expect': 'test_112',
        'note': 'an unreadable drive kind prints None instead of the reason',
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': "            reason = report.get('load_reason') or (",
        'replace': "            reason = '0% busy' or (",
        'expect': 'test_114',
        'note': 'an adapter nothing reads is shown as idle',
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        def worker_func(progress_callback=None):',
        'replace': '        def worker_func():',
        'expect': 'test_119',
        'note': 'the adapter question is handed an argument it cannot accept',
        'which': 1,
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        def worker_func(progress_callback=None):',
        'replace': '        def worker_func():',
        'expect': 'test_119',
        'note': 'the volume question is handed an argument it cannot accept',
        'which': 2,
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        worker.signals.error.connect(self.on_machine_reader_failed)',
        'replace': '        pass',
        'expect': 'test_119',
        'note': 'the adapter reader can die with nobody told',
        'which': 1,
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        worker.signals.error.connect(self.on_machine_reader_failed)',
        'replace': '        pass',
        'expect': 'test_119',
        'note': 'the volume reader can die with nobody told',
        'which': 2,
    },

    # ---- the diagnostics pane --------------------------------------------------------
    {
        'file': 'src/ui/diagnostics_tab.py',
        'find': "                return words.get(health.get(name, {}).get('status'), '[Not checked]')",
        'replace': "                return words.get(health.get(name, {}).get('status'), '[OK]')",
        'expect': 'test_136',
        'note': 'a check that never ran is printed as a pass',
    },
    {
        'file': 'src/ui/diagnostics_tab.py',
        'find': "            words = {'healthy': '[OK]', 'warning': '[Warning]', 'critical': '[Critical]'}",
        'replace': "            words = {'healthy': '[OK]', 'warning': '[Warning]', 'critical': '[Warning]'}",
        'expect': 'test_132',
        'note': 'a critical volume is filed with the same word as a warning',
    },
    {
        'file': 'src/ui/diagnostics_tab.py',
        'find': "        badges = ((self.cpu_health, 'cpu'), (self.memory_health, 'memory'),",
        'replace': "        badges = ((self.cpu_health, 'memory'), (self.memory_health, 'memory'),",
        'expect': 'test_130',
        'note': 'the CPU badge is painted from the memory check again',
    },
    {
        'file': 'src/ui/diagnostics_tab.py',
        'find': '            results += "=== STORAGE ===\\n"',
        'replace': '            results += ""',
        'expect': 'test_133',
        'note': 'the full report stops printing the volumes it was handed',
    },
    {
        'file': 'src/ui/diagnostics_tab.py',
        'find': "            checked = ('cpu', 'memory', 'disk', 'gpu', 'dependencies')",
        'replace': '            checked = tuple(health)',
        'expect': 'test_136',
        'note': 'the overall line counts only the checks that happened to answer',
    },
    {
        'file': 'src/ui/diagnostics_tab.py',
        'find': "                indicator, verdicts.get(status, 'Not checked'))",
        'replace': "                indicator, verdicts.get(status, 'Good'))",
        'expect': 'test_131',
        'note': 'a badge with no reading behind it is painted as a pass',
    },
]
