"""Whether the sweep can be stopped by a run that never answers - read off the runner.

`tools/mutation_check.py` plants one line, runs one suite, restores the line, and calls the
answer caught, CRASHED or SURVIVED. It had a fourth case it could not answer: a planted defect
that leaves a test *waiting*. Measured while closing the Diagnostics checks, entry 74 of
`tools/mutations_hardware.py` - the one that disconnects a measurement's error channel - costs
119.4 s against the 34-38 s that same suite costs clean, because the tests that name the defect
spend their whole `pump` budget first. The same entry then held a sweep for fourteen minutes on a
process whose CPU time had stopped moving, with nothing in the runner to end it: a sweep with no
deadline is not a slow measurement, it is a measurement that may never be reported.

So the runner now bounds each planted run and calls the unanswered one HUNG, kills the child and
restores the file. Three questions, and all three are about text in a file rather than about a
process - which is why this suite starts no subprocess, builds no widget and costs no minute:
the answer to "does the runner have a deadline" must not itself depend on waiting for one.

Run: python -X utf8 tests/test_mutation_harness_contract.py
"""

import ast
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
RUNNER = os.path.join(ROOT, 'tools', 'mutation_check.py')


def tree():
    with open(RUNNER, encoding='utf-8') as handle:
        return ast.parse(handle.read())


def function(name):
    for node in ast.walk(tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'{name} is not in the runner')


def keyword(call, name):
    for one in call.keywords:
        if one.arg == name:
            return one.value
    return None


def run_calls():
    """The `subprocess.run` calls in `main`, where every planted suite is started."""
    return [one for one in ast.walk(function('main'))
            if isinstance(one, ast.Call)
            and ast.unparse(one.func) == 'subprocess.run']


def module_constant(name):
    for node in tree().body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == name for t in node.targets):
            return node.value
    raise AssertionError(f'{name} is not bound at module level, so the budget is a guess')


class TestSweepDeadline(unittest.TestCase):
    """The runner answers a run that never ends, instead of joining it."""

    def test_01_every_planted_run_is_given_a_deadline_and_the_default_is_a_number(self):
        runs = run_calls()
        self.assertEqual(1, len(runs),
                         f'the runner starts planted suites in {len(runs)} places; a sweep is '
                         f'only bounded if every one of them is')
        for call in runs:
            limit = keyword(call, 'timeout')
            self.assertIsNotNone(limit,
                                 'a planted suite run is started with no timeout at all, which '
                                 'is the shape that held a sweep for fourteen minutes')
            self.assertEqual('budget', ast.unparse(limit),
                             'the deadline is not the per-entry budget, so a list can no longer '
                             'say that one suite legitimately needs longer')

        source = ast.unparse(function('main'))
        self.assertIn("item.get('timeout', args.timeout)", source,
                      'the budget no longer falls back to the command line, so the default '
                      'stops being the answer for the suites that do not name one')
        self.assertIn('default=SUITE_TIMEOUT', source,
                      "the --timeout default no longer names the constant, so the number a "
                      "sweep uses is typed in two places and can disagree with itself")

        value = module_constant('SUITE_TIMEOUT')
        self.assertTrue(isinstance(value, ast.Constant) and isinstance(value.value, int),
                        'SUITE_TIMEOUT is not a plain number, so a sweep cannot be asked for how '
                        'long it may wait')
        self.assertGreaterEqual(value.value, 300,
                                'the shipped budget is below four times the slowest entry '
                                'measured here (119.4 s), so a machine under load would read as '
                                'a sweep full of hangs')

    def test_02_a_run_that_gave_no_answer_is_a_verdict_and_refuses_the_sweep(self):
        source = ast.unparse(function('main'))
        self.assertIn('except subprocess.TimeoutExpired:', source,
                      'the timeout is no longer caught where the run happens, so the runner '
                      'dies mid-sweep and leaves the product holding a planted line')
        self.assertIn('proc, names, caught = (None, [], [])', source,
                      'a hung run is given a result object, which the verdict chain below reads '
                      'as a suite that reported something')
        self.assertIn('if proc is None:', source,
                      'the hung case is no longer separated from the caught case, so waiting '
                      'and passing wear the same face')
        self.assertIn('hung.append(label)', source,
                      'the entry is printed as hung and then dropped, which lets the summary '
                      'below claim every defect was caught')
        self.assertIn('if survived or crashed or hung:', source,
                      'a sweep with a hung entry exits as though nothing was unanswered')

    def test_03_the_advice_a_hung_entry_prints_names_the_way_out(self):
        source = ast.unparse(function('main'))
        self.assertIn('HUNG', source,
                      'the verdict no longer says what it was, so a reader cannot tell a killed '
                      'child from a crashing one')
        self.assertIn("--only {index}", source,
                      'the advice no longer names the entry it just refused to answer for')
        self.assertIn('longer --timeout', source,
                      'the advice names the deadline that was exceeded without saying it may be '
                      'raised, which sends the reader to the tests rather than to the budget')
        self.assertIn('file restored', source,
                      'the advice does not say the product was put back, so a reader has no way '
                      'to know the tree is clean for the next entry')
        doc = ast.get_docstring(tree()) or ''
        self.assertIn('HUNG', doc,
                      "the runner's own docstring lists the verdicts a sweep prints and does not "
                      "list this one")


if __name__ == '__main__':
    unittest.main()
