"""Defects to plant in the report channels, one line at a time.

Phase 34 moved nothing but strings and one latch, which is exactly the kind of change a suite
passes over: a file with no new behaviour is a file no test notices being wrong. So the list
below puts each defect back and demands the named test fail. Half of it is planted in the
product - the paint writing to a stream the build closes, the latch that stops repeating, the
failure answering as a success, the sentence sending a user to a console, the log line that
reaches the Diagnostics table with its level, its component or its text missing. The other half
is planted in `tools/check_stdout_quiet.py`, because an instrument nobody can break is not
evidence: a rule whose label constant was retargeted, whose name set no longer names a repaint,
whose print test always answers no, whose comment scan lost the pattern, whose scope walk forgot
that a method cannot see a class body, and the one line that reports a finding at all.

Two of them exist because this phase moved code rather than deleting it. `_report_paint_failure`
is a new function, so an entry writes the deleted `print` into it - which only catches if the
guard reads the helper as part of the paint, and a second entry takes the helper back out of the
guarded name set to prove that is what makes the first one fail.

Three more exist because the sweep found a second copy of a defect this phase had already fixed.
The viewer has two export methods and the two panes call different ones, so `Export failed:` was
written twice and corrected once; the entries put the line back in the one that was missed, and
put back the two refusals that answered `False` while the pane's copy promised a row.

Run:
    python -X utf8 tools/mutation_check.py tests/test_stdout_quiet_contract.py \
        tools/mutations_stdout_quiet.py
( twenty-six entries )
"""

MV = 'src/ui/model_viewer.py'
PT = 'src/ui/painting_tab.py'
RT = 'src/ui/rendering_tab.py'
MP = 'main.py'
MW = 'src/ui/main_window.py'
DG = 'src/ui/diagnostics_tab.py'
CK = 'tools/check_stdout_quiet.py'

MUTATIONS = [
    # ---- the paint path: the defect this phase was about --------------------------------------
    {
        'file': MV,
        'find': '        logger.warning("paintGL failed: %s", reason)',
        'replace': '        print(f"paintGL failed: {reason}")',
        'expect': 'test_01_the_tree_the_app_ships_is_clean',
        'note': 'the failure report goes back to the stream the packaged build closes, from a '
                'function that runs once per frame',
    },
    {
        'file': MV,
        'find': '    def paintGL(self):',
        'replace': '    def paintGL(self):  # print("DEBUG: frame start")',
        'expect': 'test_01_the_tree_the_app_ships_is_clean',
        'note': 'the parked trace comes back on the paint header, where one un-comment away it '
                'would run 60 times a second',
    },
    {
        'file': MV,
        'find': '        if reason == self._last_paint_failure:',
        'replace': '        if False and reason == self._last_paint_failure:',
        'expect': 'test_21_a_failing_repaint_is_reported_once_per_reason_not_once_per_frame',
        'note': 'the latch never fires, so a paint that raises every frame writes a row every '
                'frame and fills the table with the same line',
    },
    {
        'file': MV,
        'find': '        self._last_paint_failure = reason',
        'replace': '        self._last_paint_failure = None',
        'expect': 'test_21_a_failing_repaint_is_reported_once_per_reason_not_once_per_frame',
        'note': 'the latch forgets what it just said, which is the same flood by another route',
    },
    {
        'file': MV,
        'find': '    _last_paint_failure = None',
        'replace': '    # _last_paint_failure = None',
        'expect': 'test_21_a_failing_repaint_is_reported_once_per_reason_not_once_per_frame',
        'note': 'the default moves back into `__init__`, which returns before its attribute '
                'block when PyOpenGL is missing, and the first paint raises AttributeError',
    },
    {
        'file': MV,
        'find': '            logger.warning("Model export to %s failed: %s", file_path, e)',
        'replace': '            print(f"Export failed: {e}")',
        'expect': 'test_24_a_failed_export_names_the_file_and_still_answers',
        'note': 'the export failure is silent in the build and drops the file it failed on, '
                'which is the half a user could act on',
    },
    {
        'file': MV,
        'find': '            logger.warning("Scene export to %s failed: %s", output_path, e)',
        'replace': '            print(f"Export failed: {e}")',
        'expect': 'test_28_a_failed_scene_export_names_the_file_and_still_answers',
        'note': 'the second export route, the Rendering pane one, back to the stream nobody reads',
    },
    {
        'file': MV,
        'find': '            logger.warning("Scene export to %s refused: nothing is loaded", output_path)',
        'replace': '            pass',
        'expect': 'test_29_an_export_refused_for_want_of_a_model_says_that_is_why',
        'note': 'the pane promises the reason is in the log while this branch writes no row at all',
    },
    {
        'file': MV,
        'find': '            logger.warning("Model export to %s refused: nothing is loaded", file_path)',
        'replace': '            pass',
        'expect': 'test_29_an_export_refused_for_want_of_a_model_says_that_is_why',
        'note': 'the same unanswered `False` on the other method, so two rows become one',
    },

    # ---- the sentence the user reads -----------------------------------------------------------
    {
        'file': PT,
        'find': '                    "Failed to export model. The reason is in the Diagnostics log.")',
        'replace': '                    "Failed to export model. Check console for details.")',
        'expect': 'test_26_the_export_failure_copy_points_at_the_log',
        'note': 'the pane sends the user to a console this build does not have, for a reason it '
                'did write down somewhere they can open',
    },
    {
        'file': RT,
        'find': '            self.status_message.emit("Scene export failed. The reason is in the Diagnostics log.")',
        'replace': '            self.status_message.emit("Export failed. Check console for details.")',
        'expect': 'test_26_the_export_failure_copy_points_at_the_log',
        'note': 'the Rendering pane given the same two words the Painting pane was corrected for',
    },
    {
        'file': MP,
        'find': '        logger.warning("Window icon not found at %s", icon_path)',
        'replace': '        print(f"Window icon not found at {icon_path}")',
        'expect': 'test_27_a_missing_window_icon_is_logged_without_a_write',
        'note': 'the entry point reports a missing file only to a stream nobody reads',
    },
    {
        'file': MW,
        'find': '            logger.warning("Window icon not found at %s", icon_path)',
        'replace': '            print(f"Window icon not found at {icon_path}")',
        'expect': 'test_27_a_missing_window_icon_is_logged_without_a_write',
        'note': 'the window repeats it, so the same invisible line is written twice per start',
    },

    # ---- the channel the reports travel on -----------------------------------------------------
    {
        'file': DG,
        'find': '        self.log_record.connect(self.add_log_entry)',
        'replace': '        pass',
        'expect': 'test_22_the_warning_lands_in_the_diagnostics_table',
        'note': 'the table is built and never wired, so every log call in the app reports to '
                'nobody while the pane looks populated',
    },
    {
        'file': DG,
        'find': '        logging.getLogger().addHandler(self._log_handler)',
        'replace': '        pass',
        'expect': 'test_22_the_warning_lands_in_the_diagnostics_table',
        'note': 'the handler is made but never put on the root logger, so a module writing '
                'anywhere in `src/` reaches no row',
    },
    {
        'file': DG,
        'find': '            pane.log_record.emit(record.levelname, record.name, record.getMessage())',
        'replace': '            pane.log_record.emit(record.levelname, record.name, \'\')',
        'expect': 'test_22_the_warning_lands_in_the_diagnostics_table',
        'note': 'a row appears with its text thrown away, which reads as a working log',
    },
    {
        'file': DG,
        'find': '            pane.log_record.emit(record.levelname, record.name, record.getMessage())',
        'replace': '            pane.log_record.emit(\'INFO\', record.name, record.getMessage())',
        'expect': 'test_22_the_warning_lands_in_the_diagnostics_table',
        'note': 'every record arrives labelled INFO, so the failure a reader filters for is gone '
                'from the counts and the table',
    },
    {
        'file': DG,
        'find': '            pane.log_record.emit(record.levelname, record.name, record.getMessage())',
        'replace': '            pane.log_record.emit(record.levelname, \'renderfox\', record.getMessage())',
        'expect': 'test_23_a_record_written_on_another_thread_arrives_through_the_loop',
        'note': 'the row loses which module wrote it, which is the only clue that points at the '
                'pane to fix',
    },

    # ---- the instrument itself -----------------------------------------------------------------
    {
        'file': CK,
        'find': "DEBUG_LABEL = 'DEBUG'",
        'replace': "DEBUG_LABEL = 'NOTICE'",
        'expect': 'test_04_a_debug_trace_planted_in_a_pane_is_reported',
        'note': 'rule 1 reads for another word and reports a clean tree full of traces',
    },
    {
        'file': CK,
        'find': "            if text.strip().startswith(DEBUG_LABEL)]",
        'replace': "            if False and text.strip().startswith(DEBUG_LABEL)]",
        'expect': 'test_04_a_debug_trace_planted_in_a_pane_is_reported',
        'note': 'rule 1 is bypassed at its own filter, which no constant edit would reveal',
    },
    {
        'file': CK,
        'find': '        return func.id in PRINT_NAMES',
        'replace': '        return False',
        'expect': 'test_08_a_write_from_the_repaint_is_reported',
        'note': 'nothing counts as a stream write any more, so all three rules go quiet at once',
    },
    {
        'file': CK,
        'find': "PAINT_FUNCTIONS = {'paintGL', '_report_paint_failure'}",
        'replace': "PAINT_FUNCTIONS = {'paintGL'}",
        'expect': 'test_18_the_real_repaint_is_the_one_being_guarded',
        'note': 'the report moved out of `paintGL` into a method it calls, and a guard that '
                'reads only the old name would pass the print back in',
    },
    {
        'file': CK,
        'find': "COMMENTED_PRINT = re.compile(r'\\b(?:print|print_exc|print_last)\\s*\\(')",
        'replace': "COMMENTED_PRINT = re.compile(r'\\b(?:nothing_this_matches)\\s*\\(')",
        'expect': 'test_09_a_parked_write_in_the_repaint_is_reported',
        'note': 'the comment scan asks for a hash it has already stripped, which is the exact '
                'mistake this entry was written for',
    },
    {
        'file': CK,
        'find': '        if node.name not in PAINT_FUNCTIONS:',
        'replace': '        if node.name in PAINT_FUNCTIONS:',
        'expect': 'test_10_the_same_line_outside_a_repaint_is_not_a_paint_defect',
        'note': 'the rule reads every function except the paints, so it reports the world and '
                'misses the defect',
    },
    {
        'file': CK,
        'find': '        inherit = entrance if isinstance(node, ast.ClassDef) else outer',
        'replace': '        inherit = outer',
        'expect': 'test_13_a_logger_bound_in_a_class_body_does_not_reach_the_method',
        'note': 'a class body starts lending its names to its methods, which is what Python '
                'does not do, and the NameError passes',
    },
    {
        'file': CK,
        'find': '                missing.append(child.lineno)',
        'replace': '                pass',
        'expect': 'test_11_a_logger_that_was_never_bound_is_reported',
        'note': 'rule 3 walks the whole tree, finds everything and reports nothing',
    },
]
