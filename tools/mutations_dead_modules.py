"""Defects to plant in the code this phase touched, one line at a time.

This log's **Dead files** paragraph carried a dead-file list with line counts next to nine names, which added up to
the header's own 6,075; two of those nine had already been deleted by 6p, and **two of the seven left
on disk are live and always were** - `src/utils/file_utils.py` and `src/ui/feedback_dialog.py` are
each imported only by a *relative* import, which holds neither module's dotted name, so the grep the
list was made with answered "nothing imports it" about files the app calls on every run - and the
five the walk really cannot reach are the five this phase deleted. The list is now an instrument:
`tools/check_dead_modules.py` parses every import in the tree and walks the edges out of `main.py`,
and `tests/test_dead_modules_contract.py` runs it, plants an unreachable module of its own to
prove the report says so, and asks the second question (does the word appear anywhere) prove it
reads files.

So the defects worth planting are these: the one live helper of the reduced utility file naming a
folder it does not create, or creating it the way that makes a second caller fail; the feedback
dialog answering with a name it then opens in overwrite mode, a retry that tries one name, a
refusal announced as a save, a reason dropped on the way to the dialog, a log that goes quiet at
the level a reader looks at, and a checkbox that decides nothing in either direction; a menu entry
that builds a dialog and never shows it, or shows one the window does not own; and inside the
checker itself, a walk that starts from no entry point, ignores the edges it parsed, forgets that a
package is as live as the module inside it, skips a build folder it no longer skips, counts
reachable modules as the total it walked, or says the all-clear over a tree it just reported dead.

The last ten entries are in this list because the checker is now load-bearing: `test_03` asks
it a question in a subprocess and `test_04` asks it one in this process, and both pass on an
instrument that silently reaches nothing without the probe and count tests to notice. A checker
nobody can break is not evidence.

One line was measured and left out because no defect could be written for it. `save_feedback` used
to build its name with `%f`, on the theory that two records saved in the same second would
otherwise collide. Measured on this machine: two `datetime.now()` calls in a row answered the same
microseconds, so `%f` bought nothing, and what keeps the second record is the exclusive create plus
the retry - which is why five entries below plant that pair and the stamp line itself has none.

Each entry names the test that has to fail for it; a defect no test catches is a hole in the
suite, so it gets a test rather than a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_dead_modules_contract.py \
        tools/mutations_dead_modules.py
( thirty-three entries )
"""

FU = 'src/utils/file_utils.py'
FB = 'src/ui/feedback_dialog.py'
MW = 'src/ui/main_window.py'
CK = 'tools/check_dead_modules.py'

MUTATIONS = [
    # ---- the one helper the reduced utility file still answers -------------------------------
    {
        'file': FU,
        'find': "    temp_dir = os.path.join(tempfile.gettempdir(), 'renderfox')",
        'replace': '    temp_dir = tempfile.gettempdir()',
        'expect': 'test_06',
        'note': 'the app\'s working files go into the system temp folder itself, where the tagger, '
                'the pipeline and the performance report mix them with each other',
    },
    {
        'file': FU,
        'find': '    os.makedirs(temp_dir, exist_ok=True)',
        'replace': '    pass',
        'expect': 'test_06',
        'note': 'the helper answers a folder that is not there, so the first scratch write fails',
    },
    {
        'file': FU,
        'find': '    os.makedirs(temp_dir, exist_ok=True)',
        'replace': '    os.makedirs(temp_dir, exist_ok=False)',
        'expect': 'test_07',
        'note': 'the check-then-create habit comes back: two panes asking in the same moment make '
                'one of them raise on a directory that exists',
    },

    # ---- where the record goes, and what it is written over ----------------------------------
    {
        'file': FB,
        'find': '            feedback_dir = os.path.join(home_dir, ".renderfox", "feedback")',
        'replace': '            feedback_dir = os.path.join(home_dir, ".renderfox")',
        'expect': 'test_11',
        'note': 'reports land loose in the app folder instead of the folder the pane names to the '
                'user, so nobody finds the file they were told the path of',
    },
    {
        'file': FB,
        'find': '            os.makedirs(feedback_dir, exist_ok=True)',
        'replace': '            os.makedirs(feedback_dir, exist_ok=False)',
        'expect': 'test_13',
        'note': 'the second report of the session is refused because the folder was already made '
                'by the first, which is the check-then-create habit `get_temp_directory` exists '
                'to stop',
    },
    {
        'file': FB,
        'find': "                    with open(file_path, 'x', encoding='utf-8') as f:",
        'replace': "                    with open(file_path, 'w', encoding='utf-8') as f:",
        'expect': 'test_13',
        'note': 'a name already taken is truncated instead of refused, which is how the second '
                'report in a second deletes the first one',
    },
    {
        'file': FB,
        'find': '                except FileExistsError:',
        'replace': '                except ValueError:',
        'expect': 'test_13',
        'note': 'a collision is no longer retried but reported as a broken write, so the second '
                'record is refused for being second',
    },
    {
        'file': FB,
        'find': '            for attempt in range(1, 100):',
        'replace': '            for attempt in range(1, 2):',
        'expect': 'test_13',
        'note': 'only one name is ever tried, so a second save inside the same stamp gives up',
    },
    {
        'file': FB,
        'find': '                name = f"feedback_{stamp}.json" if attempt == 1 else '
                'f"feedback_{stamp}_{attempt}.json"',
        'replace': '                name = f"feedback_{stamp}.json"',
        'expect': 'test_13',
        'note': 'the retry counts attempts but the name never changes, so ninety-nine opens all '
                'want the one file and the record is finally refused',
    },

    # ---- what the dialog puts in the record, and what it says about it -----------------------
    {
        'file': FB,
        'find': '        if not description:',
        'replace': '        if False:',
        'expect': 'test_16',
        'note': 'an empty report is written as a record, which the reader then has to open to '
                'find there is nothing in it',
    },
    {
        'file': FB,
        'find': '            QMessageBox.warning(self, "Missing Information", "Please provide a '
                'description.")',
        'replace': '            QMessageBox.information(self, "Missing Information", "Please '
                'provide a description.")',
        'expect': 'test_16',
        'note': 'the refusal is dressed as a confirmation, the same mistake the old "Feedback '
                'Sent" made from the other side',
    },
    {
        'file': FB,
        'find': '        if self.sys_info_cb.isChecked():',
        'replace': '        if False:',
        'expect': 'test_12',
        'note': 'the checkbox stops deciding anything, so a report that said to include the '
                'machine says nothing about it',
    },
    {
        'file': FB,
        'find': '        if self.sys_info_cb.isChecked():',
        'replace': '        if True:',
        'expect': 'test_11',
        'note': 'the machine details go into a record whose writer ticked the box off, which is '
                'the privacy half of the same switch',
    },
    {
        'file': FB,
        'find': '        if saved is None:',
        'replace': '        if False:',
        'expect': 'test_14',
        'note': 'the failed write is announced as a save, which is exactly the claim this phase '
                'was opened to take out',
    },
    {
        'file': FB,
        'find': '            QMessageBox.critical(self, "Feedback Not Saved", reason)',
        'replace': '            QMessageBox.information(self, "Feedback Not Saved", reason)',
        'expect': 'test_14',
        'note': 'the one sentence that tells the user nothing was kept is shown in the same tone '
                'as the one that tells them it was',
    },
    {
        'file': FB,
        'find': '            return None, f"Feedback could not be saved: {e}"',
        'replace': '            return None, None',
        'expect': 'test_14',
        'note': 'the reason is dropped on the way to the dialog, so the user is told it failed '
                'and never told why',
    },
    {
        'file': FB,
        'find': '            logger.error(f"Failed to save feedback: {e}")',
        'replace': '            logger.warning(f"Failed to save feedback: {e}")',
        'expect': 'test_14',
        'note': 'a lost report reaches the log below the level the app is read at',
    },
    {
        'file': FB,
        'find': '            logger.info(f"Feedback saved to {file_path}")',
        'replace': '            logger.debug(f"Feedback saved to {file_path}")',
        'expect': 'test_11',
        'note': 'the path stops being in the log, so a support answer to "where did it go" has '
                'only the screen that already closed',
    },
    {
        'file': FB,
        'find': '        self.accept()',
        'replace': '        pass',
        'expect': 'test_11',
        'note': 'a save that worked leaves the dialog open, so a second click writes a second '
                'record of the same report',
    },

    # ---- the menu entry that has never had a control reaching its method ---------------------
    {
        'file': MW,
        'find': '        help_menu.addAction(feedback_action)',
        'replace': '        pass',
        'expect': 'test_10',
        'note': 'the dialog is built and wired but never offered, which is how `open_feedback` '
                'stayed unreachable from the first commit',
    },
    {
        'file': MW,
        'find': '        feedback_action.triggered.connect(self.open_feedback)',
        'replace': '        feedback_action.triggered.connect(lambda checked=False: None)',
        'expect': 'test_10',
        'note': 'the entry is there and does nothing, which a reader can only discover by '
                'clicking it',
    },
    {
        'file': MW,
        'find': '        dialog = FeedbackDialog(self)',
        'replace': '        dialog = FeedbackDialog()',
        'expect': 'test_10',
        'note': 'the dialog has no owner, so it can be closed and collected while the window '
                'still thinks it is open',
    },
    {
        'file': MW,
        'find': '        dialog.exec()',
        'replace': '        pass',
        'which': 3,
        'expect': 'test_10',
        'note': 'the dialog is constructed and never shown, so the menu entry appears to work '
                'and the record is never written',
    },

    # ---- the instrument the claims are now made with -----------------------------------------
    {
        'file': CK,
        'find': "SKIP = {'__pycache__', '.git', '.venv', 'build', 'dist', 'patch_script', "
                "'visualizations', 'node_modules'}",
        'replace': "SKIP = {'__pycache__', '.git', '.venv'}",
        'expect': 'test_18',
        'note': 'the walk reads `dist/` and `patch_script/`, which hold 3,726 more copies of these '
                'files, so every module looks named and none of them is the one the app runs',
    },
    {
        'file': CK,
        'find': '    queue = [module_of(root) for root in roots]',
        'replace': '    queue = []',
        'expect': 'test_04',
        'note': 'the walk starts nowhere, reports every module unreachable and agrees with itself',
    },
    {
        'file': CK,
        'find': '                queue.append(dep)',
        'replace': '                pass',
        'expect': 'test_04',
        'note': 'the edges are parsed and then ignored, so the report is a file listing with the '
                'word reachable in it',
    },
    {
        'file': CK,
        'find': '            head = dep',
        'replace': "            head = ''",
        'expect': 'test_03',
        'note': 'a package is no longer credited as live because a module inside it is, and four '
                'of the five under `src/` are reached no other way',
    },
    {
        'file': CK,
        'find': '        if path.resolve() == here:',
        'replace': '        if False:',
        'expect': 'test_17',
        'note': 'a module is credited with naming itself, which is the difference between the two '
                'lines this report prints',
    },
    {
        'file': CK,
        'find': "        hits = mentions(name.rpartition('.')[2], path)",
        'replace': '        hits = []',
        'expect': 'test_15',
        'note': 'the second question is never asked, so anything the import graph misses is '
                'reported as dead',
    },
    {
        'file': CK,
        'find': "    return 1 if (args.strict and (dead or named)) else 0",
        'replace': '    return 0',
        'expect': 'test_15',
        'note': '`--strict` reports a planted dead module as a clean run, which is the only job '
                'the flag has',
    },
    {
        'file': CK,
        'find': '    for name, path, _ in dead:',
        'replace': '    for name, path, _ in ():',
        'expect': 'test_15',
        'note': 'the dead list is computed and never printed',
    },
    {
        'file': CK,
        'find': '    if not named and not dead:',
        'replace': '    if True:',
        'expect': 'test_15',
        'note': 'the all-clear sentence prints over a tree the same run reported dead',
    },
    {
        'file': CK,
        'find': "          f'{len([n for n in reachable if n in src_modules])} of them')",
        'replace': "          f'{len(src_modules)} of them')",
        'expect': 'test_15',
        'note': 'the report prints the total twice, so "reachable" is a word about the number of '
                'files rather than about the import graph',
    },
]
