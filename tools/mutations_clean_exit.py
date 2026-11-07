"""Defects to plant in how the app leaves a process, one line at a time.

An exit path is worth a mutation list for the same reason a renderer is: the wrong answer costs
a run rather than a pixel. `#50` is the recorded cost - a `QApplication` event loop used as the
argument of the exit keeps the frame that owns the window alive into interpreter finalization, and
PyQt6 answers a fault there with `0xc0000409`, which has no traceback, no stdout, and no line for
`run_audit.py` to read. That suite printed `OK` and was scored FAIL, three times in six runs.

This phase found the shape in four more files than the entry point, and pinned all five with
`tools/check_clean_exit.py`. So the defects below come in two groups, and they are two different
questions:

* **the product** (entries 1-11): put the shipped shape back in one file - the loop as the exit,
  the drain call taken out, the visibility guard around the close dropped, the return value
  silenced, the crash reporter's platform guard removed - and show a test names it.
* **the instrument** (entries 12-27): leave the product alone and break one rule's ability to see
  it. An instrument that reports nothing and an instrument that is blind read identically from the
  outside, which is why every rule here has a planted file it is required to answer about, and
  each of these entries takes one of those answers away.

Two of them cost the sweep real seconds: entry 3 (no platform guard) and the guard-removal it
protects are caught by `test_32`'s own 25 s child timeout, because the defect *is* a hang. Nothing
here plants a hang the suite cannot end: `tools/mutation_check.py` runs each suite with no
timeout of its own, so an entry that outlives its test would take the whole sweep with it.

Run:
    python -X utf8 tools/mutation_check.py tests/test_clean_exit_contract.py \\
        tools/mutations_clean_exit.py
"""

MUTATIONS = [
    # ------------------------------------------------------------------ the product
    {
        'file': 'main.py',
        'find': '    code = app.exec()',
        'replace': '    sys.exit(app.exec())',
        'expect': 'test_02',
        'note': 'the entry point back to the shape #50 blames: the exit carries the frame that '
                'owns `main_window`, and the strict run passes a tree holding it',
    },
    {
        'file': 'main.py',
        'find': '    owed = run_teardown.shutdown(app)',
        'replace': '    owed = []',
        'expect': 'test_01',
        'note': 'the quit ends its loop and hands nothing to the drain, so the window Qt owns '
                'reaches finalization with the delete queue never run',
    },
    {
        'file': 'main.py',
        'find': "    if app and app.platformName() != 'offscreen':",
        'replace': '    if app:',
        'expect': 'test_32',
        'note': 'the crash reporter waits on a modal button nobody can press in a headless run, '
                'so a failure arrives as a timeout with no code and no line',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        widget.deleteLater()',
        'replace': '        pass',
        'expect': 'test_15',
        'note': 'the drain hides windows and never schedules the C++ object for deletion, which '
                'is the half the exit path exists for',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '    app.processEvents()',
        'replace': '    pass  # app.processEvents()',
        'expect': 'test_11',
        'note': 'the delete queue is filled and never run, because the app dies before it gets a '
                'turn - and the call site reads this exactly the same as the real drain',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '        if widget.isVisible():',
        'replace': '        if True:',
        'which': 1,
        'expect': 'test_12',
        'note': 'the close stops being guarded, so a window that already answered its own '
                '`closeEvent` is asked again from inside a quit already under way',
    },
    {
        'file': 'src/utils/run_teardown.py',
        'find': '    return owed',
        'replace': '    return',
        'expect': 'test_21',
        'note': 'the drain stops naming what stayed on screen, so a window that refused the close '
                'is invisible to `main.py`\'s warning and to the suite\'s failure',
    },
    {
        'file': 'tests/verify_all_fixes.py',
        'find': '        owed = run_teardown.shutdown(cls.app)',
        'replace': '        owed = []',
        'expect': 'test_15',
        'note': 'the suite that #50 was recorded on stops draining in teardown, so whichever '
                'frame happened to build the `MainWindow` carries it out',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '    shutdown(app)',
        'replace': '    pass  # shutdown(app)',
        'expect': 'test_03',
        'note': 'a developer\'s own `python -m` run ends its loop with no drain, and the summary '
                'that claims every loop reaches one has to say so',
    },
    {
        'file': 'src/ui/feedback_dialog.py',
        'find': '    shutdown(app)',
        'replace': '    pass  # shutdown(app)',
        'expect': 'test_02',
        'note': 'the same for the fourth pane: the rule is per-file, so one file losing its drain '
                'must not read as a clean tree',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '    code = app.exec()',
        'replace': '    sys.exit(app.exec())',
        'expect': 'test_01',
        'note': 'rule 1 asked only of the shipped app before this phase; this is the defect in a '
                'pane\'s hand-run block, which is the same frame and the same window',
    },

    # ------------------------------------------------------------------ the instrument
    {
        'file': 'tools/check_clean_exit.py',
        'find': "EXIT_FUNCS = {'exit', 'quit'}",
        'replace': 'EXIT_FUNCS = set()',
        'expect': 'test_04',
        'note': 'the bare and the dotted exit stop counting, so rule 1 sees the shipped shape and '
                'calls it a statement like any other',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "EXIT_MODULES = {'sys'}",
        'replace': 'EXIT_MODULES = set()',
        'expect': 'test_04',
        'note': '`sys.exit` is the spelling every file in the app actually uses, and dropping the '
                'module check drops the rule with it',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "SYSTEM_EXIT = {'SystemExit', 'QuitException'}",
        'replace': 'SYSTEM_EXIT = set()',
        'expect': 'test_06',
        'note': '`raise SystemExit(app.exec())` is the same defect in a spelling the rule has to '
                'know, and this makes it invisible',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "LOOP_METHODS = {'exec', 'exec_'}",
        'replace': "LOOP_METHODS = {'exec_'}",
        'expect': 'test_03',
        'note': 'the modern spelling of the loop call is what all five files use; keeping only the '
                'Python 2 name leaves the instrument counting zero loops',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "    return isinstance(node, ast.Call) and _callee_name(node.func) == 'QApplication'",
        'replace': '    return False',
        'expect': 'test_03',
        'note': 'no file owns an application any more, so rules 1, 2 and 5 pass the whole tree '
                'without reading it - which is what the reach line in the report is for',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': '        if any(_is_qapplication_construction(child) for child in ast.walk(value)):',
        'replace': '        if _is_qapplication_construction(value):',
        'expect': 'test_07',
        'note': 'a direct call only, so `app = QApplication.instance() or QApplication(sys.argv)` '
                'binds no name and the loop it owns is nobody\'s - the shape every suite is '
                'written in',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "               ('run the delete queue while the app is alive', 'processEvents'))",
        'replace': "               ('run the delete queue while the app is alive', 'processEverything'))",
        'expect': 'test_15',
        'note': 'rule 3 asks for a verb nobody calls, so the shipped drain reads as hollow - and '
                'a rule that cries wolf on a clean tree is a rule somebody switches off',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "               and _calls_a_name(node, 'close') for node in ast.walk(func)):",
        'replace': '               for node in ast.walk(func)):',
        'expect': 'test_12',
        'note': 'the structural read degrades into the word `isVisible` appearing somewhere, so a '
                'close that lost its guard passes because the second loop still mentions it',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': '    if not returned:',
        'replace': '    if False:',
        'expect': 'test_16',
        'note': 'rule 3 stops reading the return statement, so a drain that answers None and '
                'names nothing passes as a drain',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': '    holders = {_callee_name(n.func) for n in ast.walk(tree)',
        'replace': '    holders = {n for n in ast.walk(tree) if False',
        'expect': 'test_13',
        'note': 'rule 4 never finds the `MainWindow`, so it passes the one suite that is the '
                'reason #50 was ever seen',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': '    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:',
        'replace': '    for cls in []:',
        'expect': 'test_15',
        'note': 'the teardown walk looks at no class, so a suite that does drain in teardown is '
                'reported as one that does not',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': '        if path == entry:',
        'replace': '        if False:',
        'expect': 'test_17',
        'note': 'rule 2b is keyed to the entry point and stops being applied to it, so a quit '
                'that throws the loop\'s code away leaves the audit chain reading 0',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "    print(f'files checked: {len(paths)}; files owning a QApplication: {owning}; application event '",
        'replace': "    print(f'files checked: {len(paths)}; files owning a QApplication: 0; application event '",
        'expect': 'test_03',
        'note': 'the reach line reports five files owning a loop while walking nothing that does, '
                'which is the claim an empty instrument would make',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': '            if recv in used:',
        'replace': '            if recv not in used:',
        'expect': 'test_04',
        'note': 'the drained column counts the loops that were never handed to the drain, so the '
                'summary says a broken tree is the fixed one',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "TEARDOWN = ROOT / 'src' / 'utils' / 'run_teardown.py'",
        'replace': "TEARDOWN = ROOT / 'src' / 'utils' / 'run_teardown_unused.py'",
        'expect': 'test_15',
        'note': 'rule 3 reads the drain by path, so a path that names nothing silently stops '
                'checking the function every call site depends on',
    },
    {
        'file': 'tools/check_clean_exit.py',
        'find': "            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'atexit']",
        'replace': "            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'sys']",
        'expect': 'test_10',
        'note': 'rule 5 watches the wrong module, so a callback scheduled to touch Qt objects '
                'after `QApplication` is gone reads as ordinary code',
    },
]
