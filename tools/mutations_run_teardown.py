"""Defects to plant in the way a run is stopped, one line at a time.

Closing the window while a pane's worker is still running posts that worker's result into
widgets Qt has destroyed - measured here as a heap fault (0xc0000374) inside the Point Clouds
verdict handler, which is not an exception anything can catch - and dropping the last
reference of a worker that is still running is answered with an abort. The stop now lives in
one helper, `src/utils/run_teardown.py`, and every holder of a run calls it, so the defects
worth planting are the helper's own steps and the places a pane can stop feeding it: silence
skipped, the verb never asked, a pool answered as if it named one run, a finished run's
reference dropped or a live one's kept, an attribute cleared while its run is still working,
a holder the close never reaches, a `keep` that forgets to hold, a plain thread answered as if
it were pool work, a dialog the tree cannot see, and a step boundary that a stop never reaches.

Each entry names the suite it breaks and the test that has to fail for it. The twelve read by
`tests/test_all_tabs_headless.py` drive the real window; the rest are read by
`tests/test_run_teardown_contract.py`, `tests/test_download_teardown_contract.py` and
`tests/test_automation_tasks_contract.py`, because the defects they plant end a process before
any suite can report - an unconnected signal raising out of a slot, three ways a started run
ends up referenced by nothing, and a download that carries on after the dialog that owned it
has gone - and because the plain-thread and dialog shapes this pass added are not in the
window's tree at all. A defect no test catches is a hole in the suites, so it gets a test
rather than a pass.

The two contract files are split on where the raise is allowed to land. `silence` and the rest
of the helper are called from `closeEvent` and from `QDialog.done()`, both virtuals Qt calls,
and an exception that escapes either ends the process the way one escaping a slot does - so the
helper's own clause is answered only by the file that calls it as plain Python, while the
dialog's `done()` tests live where a defect in their own two lines is what is being planted and
nothing else can raise through the override.

Run:
    python -X utf8 tools/mutation_check.py tests/test_all_tabs_headless.py \
        tools/mutations_run_teardown.py
( thirty-two entries; twenty carry their own `suite` and run against another file )
"""

MUTATIONS = [
    {
        'file': 'src/ui/main_window.py',
        'find': '        for holder in [self] + self.findChildren(QWidget):',
        'replace': '        for holder in self.tab_widget.findChildren(QWidget):',
        'expect': 'test_25',
        'note': 'the close is back to the tab loop, so the holders embedded in a pane or '
                'parented to a dialog are never asked',
    },
    {
        'file': 'src/ui/main_window.py',
        'find': "            if hasattr(holder, 'shutdown_runs'):",
        'replace': '            if False:',
        'expect': 'test_20',
        'note': 'the walk runs and asks nobody, so a verdict in flight is delivered into the '
                'widgets the close has already destroyed',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        silence(runner)',
        'replace': '        pass',
        'which': 1,
        'expect': 'test_20',
        'note': 'the receivers stay wired, and the answer lands after the window is gone',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        ask_to_stop(runner)',
        'replace': '        pass',
        'which': 1,
        'expect': 'test_20',
        'note': 'the run is waited on but never asked to stop, so a long verb only times out',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        except TypeError:',
        'replace': '        except ValueError:',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_01',
        'note': 'a signal with nothing connected raises the error PyQt6 does not give, so the '
                'first clean runner raises inside the close',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '            (ended if pool.waitForDone(timeout_ms) else running).append(runner)',
        'replace': '            (ended if True else running).append(runner)',
        'expect': 'test_22',
        'note': 'pool work is reported ended whether its queue drained or not',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '            running.append(runner)',
        'replace': '            ended.append(runner)',
        'expect': 'test_26',
        'note': 'work handed over with no pool named is called finished, and the close deletes '
                'the widgets it is still going to write',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '    for runner in ended:',
        'replace': '    for runner in workers:',
        'expect': 'test_22',
        'note': 'the release loop lets go of the runs that are still working, which is Qt\'s '
                'other way of ending this process',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '            workers.remove(runner)',
        'replace': '            pass',
        'expect': 'test_22',
        'note': 'a finished run is never released, so every click of a long session keeps a thread',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        if ended:',
        'replace': '        if True:',
        'expect': 'test_27',
        'note': 'the attribute of a run still working is set to None, so the pane\'s own Cancel '
                'guard finds nothing and the reference Qt needs is dropped',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        silence(runner)',
        'replace': '        pass',
        'which': 2,
        'expect': 'test_27',
        'note': 'the attribute holders keep their receivers, which is the half of the job the '
                'list-holder half does not cover',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        ask_to_stop(runner)',
        'replace': '        pass',
        'which': 2,
        'expect': 'test_27',
        'note': 'an attribute-held run is never asked to stop, so it runs to its end behind a '
                'window that has already gone',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '        self._dismiss(self._run_progress)',
        'replace': '        pass',
        'expect': 'test_20',
        'note': 'the progress dialog stays up over a run the close already ended',
    },
    {
        'file': 'src/ui/mesh_tools_tab.py',
        'find': '        self._runs.append(worker)',
        'replace': '        pass',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_02',
        'note': 'a mesh operation is handed to the pool and held by nothing, so no close can '
                'take its handlers off',
    },
    {
        'file': 'src/ui/performance_tab.py',
        'find': '        self._workers.append(worker)',
        'replace': '        pass',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_02',
        'note': 'a machine reader is started and forgotten, which is the shape that faulted',
    },
    {
        'file': 'src/ui/diagnostics_tab.py',
        'find': '        held = self._benchmark_workers + self._measure_workers',
        'replace': '        held = self._benchmark_workers',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_02',
        'note': 'one of the two buckets is left out of the stop, so its run reports nothing to '
                'a pane that is closing',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        elif isinstance(runner, threading.Thread):',
        'replace': '        elif False:',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_03',
        'note': 'a plain thread is answered as if it were pool work, so the one question the '
                'helper can ask of it is never asked',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '            runner.join(timeout_ms / 1000)',
        'replace': '            pass',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_03',
        'note': 'the wait is skipped and the run is classified straight from `is_alive()`, so '
                'the close says it waited on a worker still mid-file-operation',
    },
    {
        'file': 'src/ui/automation_tab.py',
        'find': '        self._action_threads = [one for one in self._action_threads if one.is_alive()]',
        'replace': '        pass',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_03',
        'note': 'every watched file adds a row that no code ever empties',
    },
    {
        'file': 'src/ui/automation_tab.py',
        'find': '        self._action_threads.append(thread)',
        'replace': '        pass',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_03',
        'note': 'the worker is started and filed nowhere, which is the shape the close cannot '
                'reach whatever it does after that',
    },
    {
        'file': 'src/ui/automation_tab.py',
        'find': '        owed = drain(self._action_threads, timeout_ms)',
        'replace': '        owed = []',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_03',
        'note': 'the pane answers the close with "nothing owed" and has waited for nobody',
    },
    {
        'file': 'src/ui/automation_tab.py',
        'find': '        silence(self)',
        'replace': '        pass',
        'suite': 'tests/test_run_teardown_contract.py',
        'expect': 'test_03',
        'note': 'a plain thread has no signal to take off, so the pane\'s own channel is the '
                'half of the job that would go undone',
    },
    {
        'file': 'src/ui/automation_tab.py',
        'find': '        if not self.automation_engine.run_task(task_id):',
        'replace': '        if not self.automation_engine.execute_task(task_id):',
        'suite': 'tests/test_automation_tasks_contract.py',
        'expect': 'test_17b',
        'note': 'the task runs on the click, so the window waits on a thread no list holds',
    },
    {
        'file': 'src/features/automation_engine.py',
        'find': '        self._spawn(self.execute_task, (task_id,))',
        'replace': '        threading.Thread(target=self.execute_task, args=(task_id,), daemon=True).start()',
        'suite': 'tests/test_automation_tasks_contract.py',
        'expect': 'test_17b',
        'note': 'back to the thread beside the list, which is the one thing `stop` joins',
    },
    {
        'file': 'src/features/automation_engine.py',
        'find': '        if task.enabled:',
        'replace': '        if True:',
        'suite': 'tests/test_automation_tasks_contract.py',
        'expect': 'test_20',
        'note': 'a task the engine refused is left claiming it is running, and the next close '
                'asks the user whether to cut it off',
    },
    {
        'file': 'src/features/model_downloader.py',
        'find': '        self.shutdown_runs()',
        'replace': '        pass',
        'suite': 'tests/test_download_teardown_contract.py',
        'expect': 'test_05',
        'note': 'the dialog closes over a download that was never asked to stop',
    },
    {
        'file': 'src/features/model_downloader.py',
        'find': '        self._stop_requested = True',
        'replace': '        pass',
        'suite': 'tests/test_download_teardown_contract.py',
        'expect': 'test_07',
        'note': 'the verb is spelled out and then forgets to remember it',
    },
    {
        'file': 'src/features/model_downloader.py',
        'find': '            if self.download_sd and not self._stop_requested:',
        'replace': '            if self.download_sd:',
        'suite': 'tests/test_download_teardown_contract.py',
        'expect': 'test_07',
        'note': 'the first step ignores a stop asked before the thread had started',
    },
    {
        'file': 'src/features/model_downloader.py',
        'find': '            if self.download_clip and not self._stop_requested:',
        'replace': '            if self.download_clip:',
        'suite': 'tests/test_download_teardown_contract.py',
        'expect': 'test_05',
        'note': 'the second step starts after the close gave up on the download',
    },
    {
        'file': 'src/features/model_downloader.py',
        'find': '            if self._stop_requested:',
        'replace': '            if False:',
        'suite': 'tests/test_download_teardown_contract.py',
        'expect': 'test_07',
        'note': 'a download that ran nothing still reports "All downloads complete!"',
    },
    {
        'file': 'src/ui/settings_tab.py',
        'find': '        self.model_manager = ModelDownloaderDialog(self, auto_start=False)',
        'replace': '        self.model_manager = ModelDownloaderDialog(None, auto_start=False)',
        'suite': 'tests/test_download_teardown_contract.py',
        'expect': 'test_06',
        'note': 'parentless again, so the walk cannot see the dialog and the download inside it',
    },
    {
        'file': 'src/ui/settings_tab.py',
        'find': '        self.model_manager.exec()',
        'replace': '        ModelDownloaderDialog(self, auto_start=False).exec()',
        'suite': 'tests/test_download_teardown_contract.py',
        'expect': 'test_06',
        'note': 'a second dialog for the modal call, and the one the pane could reach is '
                'dropped with a run still inside it',
    },
]
