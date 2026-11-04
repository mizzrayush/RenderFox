"""Automation mutation spec: one real defect at a time, each one due a named test.

Run it with:
    python -X utf8 tools/mutation_check.py tests/test_automation_workflows_contract.py tools/mutations_automation.py

The watcher defects name their own suite, so one command checks all three automation
contract files (workflows, watcher). Each entry rewrites one line of the product, and the
named test must fail because of it. A defect nobody names is a claim the suite does not
actually support.
"""

ENGINE = 'src/features/automation_engine.py'
PANE = 'src/ui/automation_tab.py'
WATCHER_SUITE = 'tests/test_automation_contract.py'

MUTATIONS = [
    # --- the registry owns the parameter vocabulary -------------------------------
    {
        'file': ENGINE,
        'find': "        unknown = sorted(key for key in params if key not in spec)",
        'replace': "        unknown = []",
        'expect': 'test_02_a_parameter',
        'note': 'an invented parameter name is passed to the action instead of being named',
    },
    {
        'file': ENGINE,
        'find': "            if rule.get('required') and name not in params:",
        'replace': "            if False:",
        'expect': 'test_01_a_missing_value',
        'note': 'a step missing a required value would run and fail inside the action',
    },
    {
        'file': ENGINE,
        'find': "        complaints = cls.validate(action_id, kwargs)",
        'replace': "        complaints = []",
        'expect': 'test_04_execute_refuses',
        'note': 'execute calls the action before reading the reasons it should not',
    },

    # --- the executor honours the policy each step was given ----------------------
    {
        'file': ENGINE,
        'find': "                if step.on_error == 'retry' and attempts <= step.max_retries:",
        'replace': "                if step.on_error == 'retry' and attempts <= 0:",
        'expect': 'test_10_on_error_retry',
        'note': 'retry quietly becomes no retry at all',
    },
    {
        'file': ENGINE,
        'find': "            if step.on_error == 'continue':",
        'replace': "            if False:",
        'expect': 'test_09_on_error_continue',
        'note': 'the continue policy is ignored and the run stops on a tolerated failure',
    },
    {
        'file': ENGINE,
        'find': "        if total == 0:",
        'replace': "        if total < 0:",
        'expect': 'test_06_an_empty_workflow',
        'note': 'a workflow with no steps reports success having done nothing',
    },
    {
        'file': ENGINE,
        'find': "                os.makedirs(folder, exist_ok=True)  # a pipeline stages into a folder it creates",
        'replace': "                pass  # mutation: the destination folder is somebody else's problem",
        'which': 1,
        'expect': 'test_07_the_steps_run',
        'note': 'file.copy cannot stage into a folder the pipeline creates on the way',
    },

    # --- the engine stores, duplicates, deletes and stops what the pane shows -----
    {
        'file': ENGINE,
        'find': "        for step in copy.steps:",
        'replace': "        for step in []:",
        'expect': 'test_17_duplicate_makes_a_new_id',
        'note': 'the copy shares its step ids with the original',
    },
    {
        'file': ENGINE,
        'find': "        self._stopped.add(workflow_id)",
        'replace': "        pass  # mutation: the stop request is dropped on the floor",
        'expect': 'test_23_stop_asks_the_worker',
        'note': 'stop_workflow answers yes and tells the worker nothing',
    },
    {
        'file': ENGINE,
        'find': "                self.workflow_completed.emit(workflow_id, result)",
        'replace': "                self.workflow_completed.emit(workflow_id, {})",
        'expect': 'test_21_the_signals_carry',
        'note': 'the pane is told a run finished but not what it did',
    },
    {
        'file': ENGINE,
        'find': "                    self.workflow_failed.emit(workflow_id, reason)",
        'replace': "                    self.workflow_completed.emit(workflow_id, result)",
        'expect': 'test_22_a_failing_run_reaches',
        'note': 'a failed run is announced as a completed one',
    },
    {
        'file': ENGINE,
        'find': "        workflow.steps = []",
        'replace': "        pass  # mutation: the steps the editor holds are never written",
        'expect': 'test_16_update_changes_only',
        'note': 'update_workflow reports success while keeping the old step list',
    },
    {
        'file': ENGINE,
        'find': "        if not (name or '').strip():",
        'replace': "        if False:",
        'expect': 'test_19_problems_names_every',
        'note': 'a nameless workflow is no longer a reason to refuse',
    },

    # --- the polling watcher, against its own suite -------------------------------
    {
        'file': ENGINE,
        'suite': WATCHER_SUITE,
        'find': "        for old in list(holds):",
        'replace': "        for old in ():",
        'expect': 'test_15_a_rename_split',
        'note': 'a held vanishing is never answered, so half a rename is a loss',
    },
    {
        'file': ENGINE,
        'suite': WATCHER_SUITE,
        'find': "            match = next((p for p in appeared if current[p] == known[old]), None)",
        'replace': "            match = None",
        'expect': 'test_07_a_rename_is_one_move',
        'note': 'a rename seen in one pass is reported as a delete plus a create',
    },
    {
        'file': ENGINE,
        'suite': WATCHER_SUITE,
        'find': "        info['pending_gone'] = {}",
        'replace': "        pass  # mutation: stale losses survive a re-baseline",
        'expect': 'test_16_re_registering',
        'note': 're-adding a folder keeps deletions it should have forgotten',
    },
    {
        'file': ENGINE,
        'suite': WATCHER_SUITE,
        'find': "        info['last_modified'] = self._snapshot(path, info)",
        'replace': "        info['last_modified'] = {}",
        'expect': 'test_04_what_was_already_on_disk',
        'note': 'the baseline is not written at registration, so 500 old files arrive as new',
    },
    {
        'file': ENGINE,
        'suite': WATCHER_SUITE,
        'find': "        if info is None or event not in info['events']:",
        'replace': "        if info is None:",
        'expect': 'test_09_a_folder_only_reports',
        'note': 'a folder reports events its user left unchecked',
    },
    {
        'file': ENGINE,
        'suite': WATCHER_SUITE,
        'find': "            self.file_moved.emit(other_path or '', file_path)",
        'replace': "            self.file_moved.emit(file_path, file_path)",
        'expect': 'test_07_a_rename_is_one_move',
        'note': 'the move signal names the new path twice and loses the old one',
    },

    # --- the pane: every control reaches the engine or says why -------------------
    {
        'file': PANE,
        'find': "            complaints = self.automation_engine.workflow_problems(name, records)",
        'replace': "            complaints = []",
        'expect': 'test_32_a_workflow_with_no_step',
        'note': 'Save stores a workflow the engine would refuse to run',
    },
    {
        'file': PANE,
        'find': "        if not self.automation_engine.execute_workflow(workflow_id):",
        'replace': "        if False:",
        'expect': 'test_38_run_stores_then_executes',
        'note': 'Run Workflow draws a button that runs nothing',
    },
    {
        'file': PANE,
        'find': '        """Say what would happen, without running any of it."""',
        'replace': "        self.run_workflow()  # mutation: Test really runs the steps",
        'expect': 'test_36_test_workflow_proves_the_order',
        'note': 'Test Workflow performs the work it only promised to describe',
    },
    {
        'file': PANE,
        'find': "        self.current_workflow_id = copy_id",
        'replace': "        pass  # mutation: the pane stays on the workflow it copied from",
        'expect': 'test_47_duplicate_copies_the_stored_workflow',
        'note': 'Duplicate makes a copy but leaves the editor on the original',
    },
    {
        'file': PANE,
        'find': "        records[row], records[target] = records[target], records[row]",
        'replace': "        pass  # mutation: the order on screen never changes",
        'expect': 'test_44_moving_a_step_changes_the_order',
        'note': 'Move Up and Move Down are decoration',
    },
    {
        'file': PANE,
        'find': "                item.setText(str(row + 1))",
        'replace': "                item.setText(str(row))",
        'expect': 'test_46_removing_a_step_drops_it_and_renumbers',
        'note': 'the step numbers the table shows are one behind the rows',
    },
    {
        'file': PANE,
        'find': "        if self._rebuilding_list:",
        'replace': "        if False:",
        'expect': 'test_30_new_clears_the_editor',
        'note': 'rebuilding the list reloads a stale row and re-attaches the id',
    },
    {
        'file': PANE,
        'find': "            self.steps_table.setRowCount(0)",
        'replace': "            pass  # mutation: the previous workflow's steps stay on screen",
        'expect': 'test_30_new_clears_the_editor',
        'note': 'New leaves the old steps in the editor of a brand new workflow',
    },
    {
        'file': PANE,
        'find': "            complaints = self.automation_engine.workflow_problems(name, steps)",
        'replace': "            complaints = []",
        'expect': 'test_50_load_reads_a_file_into_the_engine',
        'note': 'Load stores whatever a file contains, runnable or not',
    },
    {
        'file': PANE,
        'find': "                 'on_error': error_combo.currentData() if error_combo else 'stop'}, None)",
        'replace': "                 'on_error': 'stop'}, None)",
        'expect': 'test_31_saving_writes_a_record',
        'note': 'the On error column is read but thrown away before the engine sees it',
    },
    {
        'file': PANE,
        'find': "        self._running_workflow = workflow_id",
        'replace': "        pass  # mutation: the pane forgets which run is live",
        'expect': 'test_41_stop_is_asked_of_the_engine',
        'note': 'Stop cannot name the workflow it was asked to halt',
    },
]
