"""Defects to plant in the Diagnostics pane's one machine-check step.

Phase 7c took the pane's three machine readings - the quick check, the comprehensive check and
the dependency lookups - off the thread that paints, and did it through one verb (`run_step`)
and one table (`CHECK_STEPS`) rather than three handlers that each spelled their own sentences.
The table is where a second regression crept in while that was written: with one shared failure
handler the pane printed `Error running diagnostics` for a drive scan and for a package read,
and `Status: Check failed` where the comprehensive check used to say `Status: Diagnostic
failed`. Three buttons, one set of words - a loss of the person's own wording, caught here
before it was committed.

Four defects, one line each. Every one is read by `tests/test_check_threading_contract.py`,
which parses the pane instead of pressing its buttons: the two entries that plant a reading
back inside a click could previously be answered only by the live pane, whose verdict on them
was a process that aborted in two runs of nine.

Run:
    python -X utf8 tools/mutation_check.py tests/test_check_threading_contract.py \
        tools/mutations_check_threading.py
( four entries; every one is caught by a named test, and none by killing the suite )
"""

PANE = 'src/ui/diagnostics_tab.py'

MUTATIONS = [
    # ---- who presses the reading -----------------------------------------------------------
    {
        'file': PANE,
        'find': '        measure = self.system_report_measure()',
        'replace': '        measure = None',
        'expect': 'test_01',
        'note': 'the quick check hands the pool nothing to measure with, so the box keeps its '
                'busy words and the one reading that may only be taken on the paint thread is '
                'never taken at all',
        'which': 1,
    },
    {
        'file': PANE,
        'find': '        busy, lead, status = self.CHECK_STEPS[name]',
        'replace': "        busy, lead, status = self.CHECK_STEPS['quick check']",
        'expect': 'test_02',
        'note': 'the table is looked up by whichever row the first button owns, so the '
                'comprehensive check reports itself as a quick check while still answering',
    },

    # ---- whose words each button speaks ----------------------------------------------------
    {
        'file': PANE,
        'find': "                            'Error running full diagnostic', 'Status: Diagnostic failed'),",
        'replace': "                            'Error running diagnostics', 'Status: Diagnostic failed'),",
        'expect': 'test_02',
        'note': 'two rows share one failure sentence, which is the shape that made three '
                'buttons speak as one - and a person cannot tell which check to press again',
    },
    {
        'file': PANE,
        'find': '            self.diagnostic_results.setPlainText(f"{lead}: {kind.__name__}: {value}")',
        'replace': '            self.diagnostic_results.setPlainText('
                   'f"Error running diagnostics: {kind.__name__}: {value}")',
        'expect': 'test_02',
        'note': 'the handler goes back to spelling one sentence and the table\'s `lead` becomes '
                'a value nothing reads, so the rows may collide again with nothing to notice',
    },
]
