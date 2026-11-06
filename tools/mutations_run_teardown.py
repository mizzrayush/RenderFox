"""Defects to plant in the way a run is stopped, one line at a time.

Closing the window while a pane's worker is still running posts that worker's result into
widgets Qt has destroyed - measured here as a heap fault (0xc0000374) inside the Point Clouds
verdict handler, which is not an exception anything can catch - and dropping the last
reference of a worker that is still running is answered with an abort. The stop now lives in
one helper, `src/utils/run_teardown.py`, and every holder of a run calls it, so the defects
worth planting are the helper's own steps and the places a pane can stop feeding it: silence
skipped, the verb never asked, a pool answered as if it named one run, a finished run's
reference dropped or a live one's kept, an attribute cleared while its run is still working,
a holder the close never reaches, and a `keep` that forgets to hold.

Each entry names the suite it breaks and the test that has to fail for it. Most of them are
read by `tests/test_all_tabs_headless.py`, which drives the real window; the four whose defect
ends a process before any suite can report - an unconnected signal raising out of a slot, and
three ways a started run ends up referenced by nothing - are read by
`tests/test_run_teardown_contract.py`, which asks the same questions without starting a run,
so the answer arrives as a named test instead of an access violation. A defect no test catches
is a hole in the suites, so it gets a test rather than a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_all_tabs_headless.py \
        tools/mutations_run_teardown.py
( twelve entries; four carry their own `suite` and run against the other file )
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
]
