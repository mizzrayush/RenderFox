"""Who ends a Qt event loop, and does anything still own a window when the process leaves?

A PyQt6 process dies two ways. One is a traceback: a raise nobody caught, a test that fails, a
dialog that refuses. The other is `0xc0000409` - Windows' `STATUS_FAIL_FAST_EXCEPTION` - which
arrives with **no output at all**, because PyQt6 answers a fault at the edge of a C++ frame by
calling `__fastfail` instead of raising. `run_audit.py` reads a suite by its return code, so the
second death turns a run that printed `Ran 6 tests in 20.1s / OK` into
`Core Backend & Regression Suite [FAIL]`, which is exactly how `#50` was recorded: 3 times in 6
subprocess runs of one tree and 1 in 6 of another.

This checker reads the one decision that separates the two deaths - **who holds the last Python
reference to a top-level widget when the interpreter starts tearing itself down**. Dropping that
reference during finalization, after `QApplication` has gone, is the shape the app used to ship:
`sys.exit(app.exec())` written in the frame that owns the window keeps that frame alive to carry
the `SystemExit`, and the window with it. The fix is to end the loop, hand the windows to
`src/utils/run_teardown.shutdown` while `app` can still run its delete queue, and only then
leave.

**Rule 1 refuses the shipped shape.** A Qt event loop must not be the argument of `sys.exit`,
`exit` or `raise SystemExit`: the exit is what carries the calling frame - and every widget local
in it - into finalization.

**Rule 2 asks the same question of every file that owns a `QApplication`.** Five do, in app scope:
`main.py` and four panes with a hand-run `__main__` block. A loop that ends is only half an exit;
the other half is a `shutdown` call on the same object, in the same file, between the loop and the
leaving. An exit code is part of the contract too - `run_audit.py:312` reads one - so the entry
point that returns the loop's code must still hand it to `sys.exit`.

**Rule 3 checks the drain itself, not just that its name was called.** A `shutdown` that stops
deleting - the `deleteLater` or the `processEvents` taken out, the loop that stops closing - reads
identical from the call site and returns the process to the shape rule 1 refuses. So the function
body is required to close what is on screen, schedule every top-level for deletion, run the queue,
and report what stayed.

**Rule 4 covers the process that cannot call `sys.exit` at all.** A test suite ends when
`unittest.main()` returns, so its windows are carried out by the frame that built them; the
guarantee there is a `tearDownClass` that drains, because teardown runs whatever a test did in
between - including a test that failed halfway and never reached its own cleanup.

**Rule 5 keeps the exit quiet in the one way that is still loud.** Nothing in app scope may
register an `atexit` hook: a callback Qt objects reach from is the same finalization the other
four rules avoid, one step later, with less context. (Measured: zero sites in `main.py` and
`src/` today.)

What this checker cannot see is written down so it is not mistaken for a proof.

* It reads *shapes*, not outcomes. Whether a given process actually returns 0 is a fact about a
  run, and `tests/test_clean_exit_contract.py` measures that instead of asserting it.
* A window held only by C++ - a parent Qt keeps for itself, a singleton a pane stores on a module -
  is not a Python reference and is not this rule's to find. That class is what
  `src/utils/run_teardown.py`'s walk of `topLevelWidgets()` is for, which is broader than any
  name-based scan can be.
* A `closeEvent` that refuses the close (`event.ignore()`) leaves a visible window no drain can
  remove. `shutdown` returns those names rather than hiding the fact, and `main.py` logs them.

    python -X utf8 tools/check_clean_exit.py             # report
    python -X utf8 tools/check_clean_exit.py --strict    # exit 1 unless the tree is clean

``--strict`` is what the contract suite runs, and what a future change has to pass.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP = {'__pycache__', '.git', '.venv', 'build', 'dist', 'patch_script', 'visualizations',
        'node_modules'}

TEARDOWN = ROOT / 'src' / 'utils' / 'run_teardown.py'
SUITE = ROOT / 'tests' / 'verify_all_fixes.py'

# The verbs that leave the process, and the loop call that must not be their argument.
EXIT_FUNCS = {'exit', 'quit'}
EXIT_MODULES = {'sys'}
SYSTEM_EXIT = {'SystemExit', 'QuitException'}

# `exec` is the modern spelling; `exec_` is the one PyQt kept for the Python 2 name clash.
LOOP_METHODS = {'exec', 'exec_'}

# What `shutdown` has to do to be a drain rather than a name. Each entry is
# (a human name, the attribute call the body must contain).
DRAIN_STEPS = (('close a window still on screen', 'close'),
               ('schedule the C++ object for deletion', 'deleteLater'),
               ('run the delete queue while the app is alive', 'processEvents'))


def app_files(root: Path = ROOT):
    """Every source file the packaged app ships: ``src/`` and the entry point."""
    src = [p for p in (root / 'src').rglob('*.py') if not SKIP.intersection(p.parts)]
    entry = root / 'main.py'
    return sorted(src + ([entry] if entry.exists() else []))


def _source(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace')


def _relative(path: Path) -> str:
    return (path.relative_to(ROOT).as_posix()
            if path.is_absolute() and ROOT in path.parents else path.as_posix())


def _callee_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ''


def _is_qapplication_construction(node) -> bool:
    """``QApplication(...)`` - not ``QApplication.instance()``, which builds nothing."""
    return isinstance(node, ast.Call) and _callee_name(node.func) == 'QApplication'


def app_names(tree) -> set:
    """Names this file binds to a freshly constructed `QApplication`.

    The right-hand side is searched rather than matched, because the shape every suite and the
    entry point uses is `QApplication.instance() or QApplication(sys.argv)`: the construction is
    the second operand of a boolean, and a name bound from it is still the object whose `.exec()`
    ends the process.
    """
    names = set()
    for node in ast.walk(tree):
        value = None
        targets = []
        if isinstance(node, ast.Assign):
            value, targets = node.value, node.targets
        elif isinstance(node, ast.AnnAssign):
            value, targets = node.value, [node.target]
        if value is None:
            continue
        if any(_is_qapplication_construction(child) for child in ast.walk(value)):
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def loop_calls(tree, owners: set):
    """``(lineno, receiver)`` for every call that runs an application event loop."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in LOOP_METHODS:
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id in owners:
            found.append((node.lineno, node.func.value.id))
    return found


def _is_exit_call(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in EXIT_FUNCS
    if isinstance(func, ast.Attribute):
        return isinstance(func.value, ast.Name) and func.value.id in EXIT_MODULES \
            and func.attr in EXIT_FUNCS
    return False


def _is_system_exit_raise(node) -> bool:
    return (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
            and _callee_name(node.exc.func) in SYSTEM_EXIT)


def loops_used_as_exit(path: Path):
    """Rule 1: ``(lineno, detail)`` where ending the loop *is* the exit statement."""
    tree = ast.parse(_source(path), filename=str(path))
    owners = app_names(tree)
    if not owners:
        return []
    loops = {lineno for lineno, _recv in loop_calls(tree, owners)}
    found = []
    for node in ast.walk(tree):
        carrier = node if _is_exit_call(node) else (
            node.exc if _is_system_exit_raise(node) and isinstance(node.exc, ast.Call) else None)
        if carrier is None:
            continue
        for arg in carrier.args:
            hit = [c.lineno for c in ast.walk(arg)
                   if isinstance(c, ast.Call) and c.lineno in loops]
            for line in hit:
                found.append((node.lineno,
                              'the event loop at line %d is the argument of the exit, so this '
                              'frame - and the widgets local to it - is carried into interpreter '
                              'finalization' % line))
    return found


def drained_names(tree) -> set:
    """The receivers `run_teardown.shutdown` is handed anywhere in this file."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee_name(node.func) == 'shutdown' and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name):
                out.add(first.id)
    return out


def undrained_loops(path: Path):
    """Rule 2: ``(lineno, detail)`` for a loop this file ends but never drains.

    Per-file rather than per-call: a module may run its loop inside a function and drain it in the
    `__main__` block below, and both are the same exit. The two spellings of the call -
    `run_teardown.shutdown(app)` and a bare `shutdown(app)` from a `from ... import` - are the
    same answer, which is why only the callee's last name and its argument are read.
    """
    tree = ast.parse(_source(path), filename=str(path))
    owners = app_names(tree)
    if not owners:
        return []
    drained = drained_names(tree)
    return [(line,
             '`%s.exec()` ends the loop and nothing in this file hands `%s` to `shutdown`, so the '
             'windows Qt still owns reach finalization with no delete queue left to run'
             % (recv, recv))
            for line, recv in loop_calls(tree, owners) if recv not in drained]


def entry_keeps_the_loop_code(path: Path):
    """Rule 2b: the file that *is* the entry point must still leave with the loop's code.

    `run_audit.py:312` scores a suite by `proc.returncode == 0`, and a `main()` that returns
    `None` after a fix this careful would report a clean exit for a loop that ended in failure.
    """
    tree = ast.parse(_source(path), filename=str(path))
    text = _source(path)
    found = []
    if not text.rstrip().endswith('sys.exit(main())'):
        last = text.rstrip().splitlines()[-1] if text.strip() else ''
        found.append((len(text.splitlines()),
                      'the hand-off is %r, not `sys.exit(main())`: whatever `main()` returns for '
                      'the loop is thrown away and the process always leaves with 0' % last))
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)
               if isinstance(n.value, ast.Name)]
    if not any(r.value.id in {'code', 'exit_code', 'status'} for r in returns):
        found.append((0, '`main()` never returns the value the event loop ended with, so a '
                         'non-zero quit cannot reach an exit code'))
    return found


def _calls_a_name(node, name: str) -> bool:
    """Whether `name(...)` is called anywhere inside this node."""
    return any(isinstance(c, ast.Call) and _callee_name(c.func) == name
               for c in ast.walk(node))


def drain_steps_missing(path: Path = TEARDOWN):
    """Rule 3: ``(lineno, detail)`` for a `shutdown` that no longer drains."""
    tree = ast.parse(_source(path), filename=str(path))
    func = next((n for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == 'shutdown'), None)
    if func is None:
        return [(0, '`src/utils/run_teardown.py` has no module-level `shutdown`, so every call '
                    'site reads as a drain and raises at the first quit')]
    calls = {_callee_name(c.func) for c in ast.walk(func) if isinstance(c, ast.Call)}
    found = [(func.lineno, '`shutdown` no longer performs the step the exit path depends on: %s'
              % label)
             for label, verb in DRAIN_STEPS if verb not in calls]
    # Structural rather than by name: the second loop reads `isVisible` for its own reasons, so a
    # `close()` that lost its guard still leaves the word in the function and a name test passes
    # the defect. What the exit path needs is the *shape* - close only inside a visibility test.
    if not any(isinstance(node, ast.If) and _calls_a_name(node.test, 'isVisible')
               and _calls_a_name(node, 'close') for node in ast.walk(func)):
        found.append((func.lineno, '`shutdown` no longer closes only what is on screen, so a '
                                   'window that already went through its `closeEvent` is asked '
                                   'again from inside a quit that is already under way'))
    returned = [n for n in ast.walk(func) if isinstance(n, ast.Return) and n.value is not None]
    if not returned:
        found.append((func.lineno, '`shutdown` returns nothing, so a window that refused the '
                                   'close is invisible to the caller and to the log line that '
                                   'names it'))
    return found


def suite_drains_in_teardown(path: Path = SUITE):
    """Rule 4: ``(lineno, detail)`` for a suite that cannot be trusted to have drained.

    The drain belongs in `tearDownClass` rather than in the last test, because the failure mode
    is a test that died halfway: it never reaches its own cleanup, and the process it leaves
    behind is the one #50 recorded.
    """
    tree = ast.parse(_source(path), filename=str(path))
    if not any(isinstance(n, ast.Call) and _callee_name(n.func) in {'QApplication'}
               for n in ast.walk(tree)):
        return []
    holders = {_callee_name(n.func) for n in ast.walk(tree)
               if isinstance(n, ast.Call) and _callee_name(n.func) == 'MainWindow'}
    if not holders:
        return []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        teardown = next((f for f in cls.body
                         if isinstance(f, ast.FunctionDef) and f.name == 'tearDownClass'), None)
        if teardown is None:
            continue
        if any(isinstance(c, ast.Call) and _callee_name(c.func) == 'shutdown'
               for c in ast.walk(teardown)):
            return []
    return [(0, 'this suite builds %s and has no `tearDownClass` that calls `shutdown`, so the '
               'window is carried out by whichever frame happened to build it'
               % ('a `MainWindow`'))]


def atexit_hooks(path: Path):
    """Rule 5: ``(lineno, detail)`` for a callback scheduled to run during finalization."""
    tree = ast.parse(_source(path), filename=str(path))
    return [(node.lineno, 'an `atexit` callback touches the process after `QApplication` has gone, '
                          'which is the finalization the other four rules avoid')
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _callee_name(node.func) == 'register'
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'atexit']


def scan(paths, entry=None):
    """Every rule, over the given files: ``[(file, rule, lineno, detail), ...]``.

    `entry` is the file whose exit code somebody outside the process reads - `run_audit.py:312`
    for the app, and a planted file for `tests/test_clean_exit_contract.py`, which has to be able
    to ask whether rule 2b is applied at all without rewriting the shipped entry point to find out.
    """
    found = []
    entry = entry if entry is not None else ROOT / 'main.py'
    for path in paths:
        rel = _relative(path)
        for line, detail in loops_used_as_exit(path):
            found.append((rel, 'loop-as-exit', line, detail))
        for line, detail in undrained_loops(path):
            found.append((rel, 'loop-undrained', line, detail))
        if path == entry:
            for line, detail in entry_keeps_the_loop_code(path):
                found.append((rel, 'exit-code-lost', line, detail))
        for line, detail in atexit_hooks(path):
            found.append((rel, 'atexit-hook', line, detail))
    for line, detail in drain_steps_missing():
        found.append((_relative(TEARDOWN), 'drain-hollowed', line, detail))
    for line, detail in suite_drains_in_teardown():
        found.append((_relative(SUITE), 'suite-undrained', line, detail))
    return found


def loop_owners(paths):
    """``(files owning a QApplication, application loops, loops that reach a shutdown)``."""
    owning = looping = drained = 0
    for path in paths:
        tree = ast.parse(_source(path), filename=str(path))
        owners = app_names(tree)
        if not owners:
            continue
        owning += 1
        used = drained_names(tree)
        for _line, recv in loop_calls(tree, owners):
            looping += 1
            if recv in used:
                drained += 1
    return owning, looping, drained


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--strict', action='store_true', help='exit 1 when any rule is broken')
    parser.add_argument('--file', action='append', default=None,
                        help='check only these paths, relative to the repository root')
    args = parser.parse_args(argv)

    paths = [ROOT / f for f in args.file] if args.file else app_files()
    missing = [_relative(p) for p in paths if not p.exists()]
    if missing:
        print(f'file not found: {", ".join(missing)}')
        return 2

    found = scan(paths)
    counts = {'loop-as-exit': 0, 'loop-undrained': 0, 'exit-code-lost': 0, 'atexit-hook': 0,
              'drain-hollowed': 0, 'suite-undrained': 0}
    for _rel, rule, _line, _detail in found:
        counts[rule] += 1
    owning, looping, drained = loop_owners(paths)
    print(f'files checked: {len(paths)}; files owning a QApplication: {owning}; application event '
          f'loops: {looping} = {drained} drained + {looping - drained} not; loops used as the '
          f'exit: {counts["loop-as-exit"]}; drains missing a step: {counts["drain-hollowed"]}; '
          f'suites with no drain: {counts["suite-undrained"]}; atexit hooks: '
          f'{counts["atexit-hook"]}; exit code thrown away: {counts["exit-code-lost"]}')
    for rel, rule, line, detail in found:
        print(f'{rule}: {rel}:{line} {detail}')
    if not found:
        print('every Qt event loop in the app is ended by a statement that does not carry its '
              'frame into finalization, every one of them reaches the shared drain, the drain '
              'still closes, deletes, runs the queue and reports what stayed, the suite that '
              'built the window that flaked drains in teardown, and nothing registers a callback '
              'for the interpreter to run after the app is gone')
    return 1 if (args.strict and found) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
