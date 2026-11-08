"""Which thread asks, and in whose words - read off the file, in a process that asks nothing.

Two entries in `tools/mutations_hardware.py` (43 and 44) plant the defect this area was opened
for: a Diagnostics machine button that measures the machine inside its own click instead of
handing the reading to `run_step`. Read by the live pane, that defect is a coin. With the
reading moved back into the click, `test_137`'s stub is held open on the thread that paints -
twelve seconds of a blocked event loop, in which the verdict depends on which earlier test's
worker happened to finish and into what - and the process answered `0xc0000005` in two of the
nine planted runs measured while writing this, and reported `test_137` in the other seven. An
aborted suite prints no summary, so a named failure two classes earlier is invisible to the
sweep and the entry reads CRASHED: an unclosed hole wearing a verdict.

So the shape of the defect is asked here, where nothing is constructed and no thread starts.
The rule is one statement long and has nothing to do with timing: a handler that presses the
closure it built, rather than handing it over, measures on the thread that paints. The wording
half is asked in the same breath, because the three checks each own a sentence and a status
word of their own, and a table that has let two of them collide is a table no live click will
always notice.

Entry 73 of `tools/mutations_hardware.py` moved here for the opposite reason: it is answered,
just not at a price a sweep can pay. Taking `progress_callback` out of the closure
`run_off_thread` builds makes `Worker.run` raise before the measurement starts, so only `error`
ever fires and every live test that presses a machine button waits its whole `pump` budget for a
`result` that cannot arrive. Measured on the finished tree it runs past the sweep's 900 s
deadline and names `test_177` inside 1800 s. Whether a function can be called with a given
keyword is a fact about its signature, so the third test reads it off the file in 0.2 s and the
live suite keeps proving what a pane does when a worker raises - entry 71 plants the same shape
in the other closure and answers in the time a clean run costs.

Run: python -X utf8 tests/test_check_threading_contract.py
"""

import ast
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

PANE = os.path.join(ROOT, 'src', 'ui', 'diagnostics_tab.py')
WORKER = os.path.join(ROOT, 'src', 'utils', 'worker.py')

# The three buttons that read this machine, each with the row of CHECK_STEPS it owns and the
# expression `run_step` has to be handed as its reading. A name in this table is a question the
# click may not answer itself.
CHECKS = {
    'run_quick_check': ('quick check', 'measure'),
    'run_full_diagnostic': ('full diagnostic', 'measure'),
    'run_dependency_check': ('dependency check',
                             'DependencyChecker.check_all_dependencies'),
}

# Called from inside a click, these run on the thread that paints: the engine entry the two
# reports go through, and the package reader the dependency button goes through.
ENGINE_CALLS = ('get_full_system_report', 'check_all_dependencies')


def method(name):
    """The `DiagnosticsTab` method with this name, as written."""
    with open(PANE, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'DiagnosticsTab':
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == name:
                    return item
    raise AssertionError(f'DiagnosticsTab.{name} is not in the pane')


def calls_written_in(function):
    """Every call typed in this function's own body, nested definitions left out.

    A nested `def` is what the pane hands to the worker, so a call inside one is a call the
    worker makes - the thing this rule allows. Only the handler's own depth is evidence of a
    click that waits.
    """
    found = []
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return found


def table_rows():
    """CHECK_STEPS as the class wrote it: {row name: (busy, failure lead, status)}."""
    with open(PANE, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'DiagnosticsTab':
            for item in node.body:
                if (isinstance(item, ast.Assign)
                        and any(getattr(target, 'id', '') == 'CHECK_STEPS'
                                for target in item.targets)):
                    return ast.literal_eval(item.value)
    raise AssertionError('CHECK_STEPS is no longer a table the pane can be read from')


def worker_closures():
    """The functions the pane builds and hands to the house `Worker`, with where each was built.

    Resolved by name, because the rule that reads them is about a signature: a `Worker(x)` whose
    `x` is not a function written in the same method has no signature this file can look at, and
    saying so is better than skipping it quietly.
    """
    with open(PANE, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'DiagnosticsTab':
            found = []
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                for call in ast.walk(item):
                    if (isinstance(call, ast.Call)
                            and ast.unparse(call.func) == 'Worker'):
                        if not (call.args and isinstance(call.args[0], ast.Name)):
                            raise AssertionError(
                                f'DiagnosticsTab.{item.name} hands Worker a '
                                f'{ast.unparse(call.args[0]) if call.args else "nothing"}, '
                                f'which is not a closure this rule can read a signature from')
                        name = call.args[0].id
                        built = [inner for inner in ast.walk(item)
                                 if isinstance(inner, ast.FunctionDef)
                                 and inner is not item and inner.name == name]
                        if not built:
                            raise AssertionError(
                                f'DiagnosticsTab.{item.name} hands Worker {name}, which no '
                                f'line of that method writes')
                        found.append((f'DiagnosticsTab.{item.name}.{name}', built[0]))
            return found
    raise AssertionError('DiagnosticsTab is not in the pane')


class TestCheckThreadingContract(unittest.TestCase):
    def test_01_a_machine_check_hands_its_reading_over_and_never_presses_it(self):
        """The three handlers build a reading, name it to `run_step`, and stop there.

        `run_step` is the only place this pane starts a machine reading, so a handler that
        calls the engine - or calls the closure it built itself - has taken the 2.3 s back onto
        the thread that paints. Both shapes are refused here by name, and the second is the one
        the live suite can only answer by racing itself.
        """
        rows = table_rows()
        for name, (row, reading) in CHECKS.items():
            self.assertIn(row, rows, f'{name} has no row of CHECK_STEPS to speak from')
            handler = method(name)
            calls = calls_written_in(handler)
            steps = [call for call in calls if ast.unparse(call.func) == 'self.run_step']
            self.assertEqual(1, len(steps),
                             f'{name} no longer reaches the pool through exactly one run_step '
                             f'call; it makes {len(steps)}')
            self.assertEqual(row, ast.literal_eval(steps[0].args[0]),
                             f'{name} no longer names {row} to run_step, so it is painted with '
                             f'some other check\'s words')
            self.assertEqual(reading, ast.unparse(steps[0].args[1]),
                             f'{name} hands run_step {ast.unparse(steps[0].args[1])}, not the '
                             f'{reading} this pane reads the machine through')
            self.assertEqual(row, ast.unparse(steps[0].args[2]).removeprefix('self.show_')
                             .replace('_', ' '),
                             f'{name} does not paint into its own receiver')
            pressed = [ast.unparse(call) for call in calls
                       if (isinstance(call.func, ast.Attribute)
                           and call.func.attr in ENGINE_CALLS)
                       or isinstance(call.func, ast.Name)]
            self.assertEqual([], pressed,
                              f'{name} measures in its own body instead of handing the reading '
                              f'over: {pressed}')
            if reading == 'measure':
                built = [call for call in calls
                         if ast.unparse(call.func) == 'self.system_report_measure']
                self.assertEqual(1, len(built),
                                 f'{name} no longer builds its reading with '
                                 f'system_report_measure, so what it hands over is not the '
                                 f'reading that takes the widget question on this thread')

    def test_02_each_check_owns_its_own_words_and_the_box_they_arrive_in(self):
        """The table is the only place the pane spells a check's sentences, and no two share.

        Before this area, three handlers each wrote their own failure line, and the pass that
        moved the work left one shared handler behind: `Error running diagnostics` for a drive
        scan and for a package read, and `Status: Check failed` where the comprehensive check
        used to say `Status: Diagnostic failed`. A table is only an improvement if each row
        still says which button it belongs to, so the three busy texts and the three failure
        sentences are read as values that must not collide.
        """
        rows = table_rows()
        self.assertEqual(sorted(one[0] for one in CHECKS.values()), sorted(rows),
                         'the table no longer has exactly the three checks that read this '
                         'machine')
        for index, label in ((0, 'busy'), (1, 'failure lead')):
            values = [row[index] for row in rows.values()]
            self.assertEqual(len(values), len(set(values)),
                             f'two checks share one {label} text: {values}')
        for name, row in rows.items():
            self.assertEqual(3, len(row), f'{name} is not a (busy, lead, status) row')
            for index, field in enumerate(('busy text', 'failure lead', 'status word')):
                self.assertTrue(isinstance(row[index], str) and row[index].strip(),
                                f'{name} has no {field} of its own')

        source = ast.unparse(method('run_step'))
        self.assertIn('self.CHECK_STEPS[name]', source,
                      'run_step no longer looks the clicked check up by name')
        self.assertIn('sink=self.diagnostic_results', source,
                      'a check that failed would write into the box no one was watching')
        self.assertIn('failure=self.check_failure(lead, status)', source,
                      'run_step stopped giving this check its own failure words')

        # The two statements the failure handler is allowed to be: one sentence that starts
        # with the clicked check's own lead-in, and one status word taken from the row. Read as
        # arguments rather than as substrings of the method, because `lead` and `status` are
        # also this handler's parameter names and a signature says nothing about what it prints.
        failure = method('check_failure')
        box = [call for call in ast.walk(failure) if isinstance(call, ast.Call)
               and ast.unparse(call.func) == 'self.diagnostic_results.setPlainText']
        self.assertEqual(1, len(box),
                         'the failure handler no longer writes one sentence into the box the '
                         'check was filling')
        sentence = [ast.unparse(node) for node in ast.walk(box[0])
                    if isinstance(node, ast.JoinedStr)]
        self.assertEqual(1, len(sentence),
                         'what the failure handler prints is no longer one assembled sentence')
        self.assertTrue(sentence[0].startswith("f'{lead"),
                        f'the failure sentence is spelled in the handler again rather than '
                        f'begun with the clicked check\'s own lead-in: {sentence[0]}')
        for fragment in ('kind.__name__', 'value'):
            self.assertIn(fragment, sentence[0],
                          f'the failure sentence no longer carries {fragment}, so what raised '
                          f'is dropped rather than said')
        word = [call for call in ast.walk(failure) if isinstance(call, ast.Call)
                and ast.unparse(call.func) == 'self.health_status.setText']
        self.assertEqual([{'status'}], [{ast.unparse(call.args[0])} for call in word],
                         'the status beside a failed check is no longer the row\'s own word')


    def test_03_every_closure_handed_to_the_house_worker_accepts_its_argument(self):
        """`Worker` adds `progress_callback` to the call it makes, so the closure must take it.

        Entry 73 of `tools/mutations_hardware.py` takes the `=None` parameter out of
        `run_off_thread`'s closure. `Worker.run` then raises `TypeError` before the measurement
        starts, its bare `except` emits `error` instead of `result`, and every test in the live
        suite that presses a machine button waits its whole `pump` budget for an answer that
        cannot arrive. Measured on the finished tree: that one entry costs more than the sweep's
        900 s budget and answers inside 1800 s, naming `test_177` - so the defect is caught, and
        the price of asking is a third of an hour. Whether a closure can be called with a given
        keyword is a fact about the text, so the same question is answered here in a fifth of a
        second, and the live suite keeps the behavioural half it already proves.

        The rule is read off the worker too, not just assumed: if `Worker.__init__` stopped
        injecting the keyword, a closure that demanded one would be the pane's own invention and
        this test would be pinning a convention that had already gone.
        """
        with open(WORKER, encoding='utf-8') as handle:
            worker_source = ast.unparse(ast.parse(handle.read()))
        self.assertIn("self.kwargs['progress_callback'] =", worker_source,
                      "the house worker no longer injects `progress_callback`, so the shape "
                      "this test demands of the pane is a convention nothing enforces")

        closures = worker_closures()
        self.assertEqual(2, len(closures),
                         f'the pane hands the worker {len(closures)} closures; this rule was '
                         f'written against the two the machine checks go through, so a third '
                         f'place needs saying rather than assuming')
        for where, node in closures:
            names = [one.arg for one in node.args.posonlyargs + node.args.args
                     + node.args.kwonlyargs]
            self.assertIn('progress_callback', names,
                          f'{where} is built to run on the worker but its signature is '
                          f'({", ".join(names)}); the worker calls it with '
                          f'`progress_callback=` and would raise TypeError first')

if __name__ == '__main__':
    unittest.main()
