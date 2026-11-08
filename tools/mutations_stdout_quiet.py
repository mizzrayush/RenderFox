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

The 51 entries below are of three kinds, because the phase ended up being three things. One group
puts a report back into the closed stream, or takes one out of the channel. Another breaks the
*instrument* - `tools/check_stdout_quiet.py` - since a rule nobody can break is not evidence:
rules 5 and 6 are each bypassed at their own filter, at their constant, and at the line that
reports a finding, rule 4's hand-run exemption is widened until it reaches a function body, one of
its exemptions is left matching nothing, and the summary line is made to count two rules into keys
it never builds. Thirteen land on the sweep's own judgement rather than on its arithmetic: they
change the *level* a record carries, drop one of its arguments, put a glyph back in a sentence,
hide a row behind the table's level filter or a component name no module has ever emitted, or move
`early_log.install()`, its drain and the two `setLevel` calls in `main.py` - and every one of those
is caught by a test that reads the level, the formatted row or the startup order, not by the checker.

Run:
    python -X utf8 tools/mutation_check.py tests/test_stdout_quiet_contract.py \
        tools/mutations_stdout_quiet.py
( 51 entries )
"""

MV = 'src/ui/model_viewer.py'
PT = 'src/ui/painting_tab.py'
RT = 'src/ui/rendering_tab.py'
MP = 'main.py'
MW = 'src/ui/main_window.py'
DG = 'src/ui/diagnostics_tab.py'
EL = 'src/utils/early_log.py'
WK = 'src/utils/worker.py'
TB = 'src/processing/texture_baker.py'
AE = 'src/features/automation_engine.py'
AT = 'src/features/ai_asset_tagger.py'
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

    # ---- the sweep: a record at the wrong level is a different sentence ------------------------
    {
        'file': WK,
        'find': '            logger.error("%s failed: %s", getattr(self.fn, \'__name__\', repr(self.fn)), text)',
        'replace': '            logger.warning("%s failed: %s", getattr(self.fn, \'__name__\', repr(self.fn)), text)',
        'expect': 'test_56_a_report_is_written_at_the_level_its_sentence_claims',
        'note': 'a task that ended in its except arm is reported as one the app answered; the '
                'tree stays clean, so only the level pin can see this',
    },
    {
        'file': TB,
        'find': '            logger.error("Baking failed: %s", e)',
        'replace': '            logger.warning("Baking failed: %s", e)',
        'expect': 'test_56_a_report_is_written_at_the_level_its_sentence_claims',
        'note': 'the batch records a map it did not write and calls that a refusal',
    },
    {
        'file': AE,
        'find': '        logger.debug("Registered action: %s", action_id)',
        'replace': '        logger.info("Registered action: %s", action_id)',
        'expect': 'test_56_a_report_is_written_at_the_level_its_sentence_claims',
        'note': 'per-item chatter moves above the floor, so every action the start registers '
                'becomes a row in the table a failure is meant to stand out in',
    },
    {
        'file': MV,
        'find': '            logger.warning("Model export to %s failed: %s", file_path, e)',
        'replace': '            logger.warning("Model export to %s failed: %s", file_path)',
        'expect': 'test_24_a_failed_export_names_the_file_and_still_answers',
        'note': 'one slot left empty: `logging` raises while formatting the record and the row '
                'never arrives, which is the failure the checker\'s rule 5a reads for',
    },
    {
        'file': AT,
        'find': '                    logger.info("Local CLIP model loaded successfully!")',
        'replace': '                    logger.info("\u2705 Local CLIP model loaded successfully!")',
        'expect': 'test_43_the_counts_are_measured_against_emitters_the_tree_has',
        'note': 'the status glyph the sweep took out of fourteen sentences goes back into one, '
                'and the report line that counts them stops being zero',
    },

    # ---- the table a record arrives at ---------------------------------------------------------
    {
        'file': DG,
        'find': '            if arrived is not None and arrived < floor:',
        'replace': '            if arrived is not None and arrived != floor:',
        'expect': 'test_45_a_warning_is_visible_under_the_default_level',
        'note': 'the floor becomes an equality again against its own INFO default, so every '
                'WARNING and ERROR row is stored and displayed as nothing',
    },
    {
        'file': DG,
        'find': '        self.component_filter_combo.addItem("All Components")',
        'replace': '        self.component_filter_combo.addItems(["All Components", "Renderer"])',
        'expect': 'test_47_the_component_list_offers_only_emitters_that_wrote',
        'note': 'one of the nine names no module has ever emits is back on the list, where '
                'choosing it is one click away from an empty table',
    },
    {
        'file': DG,
        'find': '        for record in early_log.take():',
        'replace': '        for record in []:',
        'expect': 'test_52_a_pane_shows_what_was_held_before_it_existed',
        'note': 'the queue is filled at startup and never read, which is a quieter way of '
                'losing the same five reports than writing them to stderr',
    },

    # ---- the records written before the pane exists ---------------------------------------------
    {
        'file': EL,
        'find': '        if len(_records) < EARLY_LIMIT:',
        'replace': '        if True:',
        'expect': 'test_51_the_buffer_stops_at_its_cap_and_keeps_the_earliest',
        'note': 'a startup that fails in a loop grows a list nothing will ever read',
    },
    {
        'file': EL,
        'find': '    del _records[:]',
        'replace': '    pass',
        'expect': 'test_50_the_held_records_come_back_oldest_first_and_only_once',
        'note': 'the buffer is peeked at instead of drained, so the second pane shows the first '
                'pane\'s startup and every pane after it shows it again',
    },
    {
        'file': EL,
        'find': '    if any(isinstance(handler, EarlyLogHandler) for handler in root.handlers):',
        'replace': '    if False:',
        'expect': 'test_49_a_second_install_adds_no_second_queue',
        'note': 'a second main() in one process stacks a queue in front of the first, and each '
                'record is now held twice',
    },
    {
        'file': MP,
        'find': '    early_log.install()',
        'replace': '    pass  # early_log.install()',
        'expect': 'test_59_the_queue_is_installed_before_main_reports_or_levels_anything',
        'note': 'the entry point opens with something else, so the icon, splash and registration '
                'reports go back to the stream the package closes',
    },
    {
        'file': MP,
        'find': "    logging.getLogger('src').setLevel(logging.INFO)",
        'replace': '    logging.getLogger().setLevel(logging.INFO)',
        'expect': 'test_58_main_opens_its_own_two_namespaces_and_nobody_elses',
        'note': 'the floor moves onto the root logger, so every dependency in the process can '
                'write rows into a table capped at 10,000',
    },

    # ---- the instrument, part two: rules 4, 5 and 6 --------------------------------------------
    {
        'file': CK,
        'find': '        if want != have:',
        'replace': '        if False and want != have:',
        'expect': 'test_35_a_message_and_its_arguments_that_disagree_are_reported',
        'note': 'rule 5a compares the two numbers and then refuses to say anything about it',
    },
    {
        'file': CK,
        'find': "        want = len([m for m in FORMAT_SLOT.finditer(text) if m.group('type')])",
        'replace': '        want = len(list(FORMAT_SLOT.finditer(text)))',
        'expect': 'test_37_a_literal_percent_is_not_counted_as_a_slot',
        'note': 'the escape stops being an escape, so `(%.1f%% reduction)` counts three slots where '
                'it has two and the correct LOD row is reported as a broken one',
    },
    {
        'file': CK,
        'find': '        if call and call[1]:',
        'replace': '        if False and call[1]:',
        'expect': 'test_39_a_record_written_on_the_root_logger_is_reported',
        'note': 'rule 5b finds the root call and drops it, so every row those three sites write '
                'is named `root` and cannot be filtered',
    },
    {
        'file': CK,
        'find': '        return func.attr, False',
        'replace': '        return func.attr, True',
        'expect': 'test_40_the_same_call_through_a_module_logger_keeps_its_name',
        'note': 'a module logger becomes the root logger, so every emitter in the app is reported '
                'as a defect - which is how a rule that cries wolf ends up switched off',
    },
    {
        'file': CK,
        'find': '        for text in _message_literals(node):',
        'replace': '        for text in []:',
        'expect': 'test_41_a_glyph_written_into_a_record_is_reported',
        'note': 'rule 6 walks the tree, asks for a message it never reads and finds none',
    },
    {
        'file': CK,
        'find': "NON_ASCII = re.compile(r'[^\\x00-\\x7f]')",
        'replace': "NON_ASCII = re.compile(r'^\\s*[^\\x00-\\x7f]')",
        'expect': 'test_41_a_glyph_written_into_a_record_is_reported',
        'note': 'the rule reads the first character of the sentence, which is where none of the '
                'fourteen real ones were',
    },
    {
        'file': CK,
        'find': '        if in_main_guard:',
        'replace': '        if False and in_main_guard:',
        'expect': 'test_31_a_write_inside_a_hand_run_block_is_not_reported',
        'note': 'the exemption stops applying, and a rule that reports a developer\'s own smoke '
                'test is a rule somebody turns off',
    },
    {
        'file': CK,
        'find': '    for node in tree.body:',
        'replace': '    for node in ast.walk(tree):',
        'expect': 'test_32_a_guard_written_inside_a_function_is_not_a_hand_run_block',
        'note': 'the hand-run block is found anywhere in the file, so a guard in a function body '
                'exempts a write the packaged app can reach',
    },
    {
        'file': CK,
        'find': '        if entry[0] in walked and entry not in used:',
        'replace': '        if False and entry not in used:',
        'expect': 'test_33_an_exemption_that_matches_no_write_is_itself_reported',
        'note': 'an exemption nobody needs any more is never noticed, and the rule it covers is '
                'silently gone',
    },
    {
        'file': CK,
        'find': "              'unformattable': 0, 'root-logger': 0, 'glyph-in-record': 0}",
        'replace': "              'unformattable': 0}",
        'expect': 'test_02_the_strict_run_exits_zero_and_says_so',
        'note': 'the report counts two of its six rules into a key it never makes, so the run '
                'dies before it prints a single number',
    },
    {
        'file': CK,
        'find': "LEVEL_CALLS = frozenset({'debug', 'info', 'warning', 'error', 'critical', 'exception', 'log'})",
        'replace': "LEVEL_CALLS = frozenset({'debug', 'info', 'error', 'critical', 'exception', 'log'})",
        'expect': 'test_39_a_record_written_on_the_root_logger_is_reported',
        'note': 'the busiest level in the app is not a log call, so rules 5 and 6 read 104 of '
                'the 241 records as ordinary code',
    },
    {
        'file': CK,
        'find': '            elif any(key[0] == rel and key[1] in text for key in VISIBLE_WRITES):',
        'replace': '            elif False:',
        'expect': 'test_34_the_writes_the_report_splits_add_up_to_the_writes_it_walked',
        'note': 'the arithmetic line the report prints stops reconciling, which is how a summary '
                'figure drifts from the rows under it',
    },
]
