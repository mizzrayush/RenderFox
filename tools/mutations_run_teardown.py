"""Defects to plant in the way a run is stopped, one line at a time.

Closing the window while a pane's worker is still running posts that worker's result into
widgets Qt has destroyed - measured here as a heap fault (0xc0000374) inside the Point Clouds
verdict handler, which is not an exception anything can catch. These entries break one part
of the stop at a time - the close no longer asks the panes, the pane no longer takes the
result channels off, no longer asks the verb to stop, forgets which run was in flight, or
leaves its dialog up - and name the test that has to fail for it. A defect the suite does not
notice is a hole in the suite, so it gets a test rather than a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_all_tabs_headless.py \
        tools/mutations_run_teardown.py
"""

MUTATIONS = [
    {
        'file': 'src/ui/main_window.py',
        'find': "            if hasattr(pane, 'shutdown_runs'):",
        'replace': '            if False:',
        'expect': 'test_20',
        'note': 'the close stops the batch and the scheduler but no pane run',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '            for signal in (thread.verdict_ready, thread.finished):',
        'replace': '            for signal in ():',
        'expect': 'test_20',
        'note': 'the stopped run is still wired to the widgets it may no longer touch',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '            thread.request_stop()',
        'replace': '            pass',
        'expect': 'test_20',
        'note': 'the verb is waited on but never asked to stop, so the wait only times out',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '        self._active_thread = None',
        'replace': '        pass',
        'expect': 'test_20',
        'which': 2,
        'note': 'the pane goes into its close still claiming a run that has been stopped',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '        self._dismiss(self._run_progress)',
        'replace': '        pass',
        'expect': 'test_20',
        'note': 'the progress dialog stays open over a run the close already ended',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '        return still_running',
        'replace': '        return 0',
        'expect': 'test_21',
        'note': 'a thread that refused to stop is reported as if it had ended',
    },
]
