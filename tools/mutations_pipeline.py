"""Mutations for the Pipeline contract suite - tests/test_pipeline_contract.py.

Each entry breaks one sentence the pane or the engine tells a person, and names the test
that has to go red for it. Two families are here on purpose: the engine's verdicts (a row
that claims a file, a count, or a refusal the code did not produce), and the pane's promise
that everything on the screen came from a run rather than from the pane's own imagination.

Run:
    python -X utf8 tools/mutation_check.py tests/test_pipeline_contract.py \
        tools/mutations_pipeline.py
"""

MUTATIONS = [
    # ---- the graph: what may be wired, and what is said when it may not -------------
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '            if definition.category != NodeCategory.INPUT and '
                'not self.incoming(node.id):',
        'replace': '            if False:',
        'expect': 'test_18',
        'note': 'a node with nothing on its wire is no longer a problem anyone is told about',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '        return self._incoming(node_id)',
        'replace': '        return []',
        'expect': 'test_29b',
        'note': 'a node that refused empties the wire, so the next row blames itself',
    },
    # ---- the run: what a row is allowed to claim ------------------------------------
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '                row[\'files\'] = [item.path for item in stream]',
        'replace': '                row[\'files\'] = []',
        'expect': 'test_04',
        'note': 'a done row reports no files, so the run\'s file count is decoration',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '        if not keep_staging and result[\'status\'] == \'done\':',
        'replace': '        if True:',
        'expect': 'test_29_staging',
        'note': 'the staging folder is deleted while the rows still point into it',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '        if len(sentences) > 3:',
        'replace': '        if False:',
        'expect': 'test_22',
        'note': 'a batch row prints one sentence per file until nobody can read it',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '    reads = sorted(CLOUD_VERB_KNOBS.get(verb) or {})',
        'replace': '    reads = []',
        'expect': 'test_23',
        'note': 'the cloud node stops saying which knobs the verb it ran reads',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '    unused -= taken',
        'replace': '    unused = set()',
        'expect': 'test_23',
        'note': 'the cloud node hides the knobs the chosen verb never reaches',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '        if text in named:',
        'replace': '        if True:',
        'expect': 'test_60_the_pane',
        'note': 'a value outside an enum\'s list is accepted instead of refused by name',
    },
    # ---- a file the engine says it wrote --------------------------------------------
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '                                   \'label\': item.label, \'measured\': '
                'dict(item.facts)}',
        'replace': '                                   \'label\': item.label, \'measured\': {}}',
        'expect': 'test_28',
        'note': 'the stats JSON is written without the numbers it was supposed to carry',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '        if geometry:',
        'replace': '        if False:',
        'expect': 'test_28',
        'note': 'Export Stats ignores its own Include Geometry box',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '            facts[\'faces\'] = int(len(mesh.faces))',
        'replace': '            facts[\'faces\'] = 4',
        'expect': 'test_04',
        'note': 'the mesh counter says four faces whatever the file holds',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '    seen: List[str] = []',
        'replace': '    seen: List[str] = [] if open(absolute, \'a\', encoding=\'utf-8\')'
                   '.write(\'\\n\') is None else []',
        'expect': 'test_32',
        'note': 'loading a pipeline file edits it, so the person\'s file is not theirs',
    },
    # ---- the pane: a control for every knob, and nothing of its own ------------------
    {
        'file': 'src/ui/pipeline_editor_tab.py',
        'find': '        self.widgets[name] = widget',
        'replace': '        return widget if False else widget',
        'expect': 'test_40',
        'note': 'the panel builds a control and forgets which knob it belongs to',
    },
    {
        'file': 'src/ui/pipeline_editor_tab.py',
        'find': '            self.node.position = (self.pos().x(), self.pos().y())',
        'replace': '            pass',
        'expect': 'test_57',
        'note': 'a dragged node never reaches the model, so a saved layout reopens as a pile',
    },
    {
        'file': 'src/ui/pipeline_editor_tab.py',
        'find': '        unknown = status not in STATUSES and status != \'running\'',
        'replace': '        unknown = False',
        'expect': 'test_56',
        'note': 'the table prints any status word handed to it, including one the engine lacks',
    },
    {
        'file': 'src/ui/pipeline_editor_tab.py',
        'find': '        if self._active_thread is not None:',
        'replace': '        if False:',
        'expect': 'test_53',
        'note': 'a second Run starts over the first and two threads write one table',
    },
    {
        'file': 'src/ui/pipeline_editor_tab.py',
        'find': '        self._workers.append(thread)',
        'replace': '        pass',
        'expect': 'test_55',
        'note': 'the running thread is dropped, which is how a QThread kills the process',
    },
    {
        'file': 'src/ui/pipeline_editor_tab.py',
        'find': '        if counts.get(\'failed\'):',
        'replace': '        if counts.get(\'failed\') or counts.get(\'refused\'):',
        'expect': 'test_51',
        'note': 'a node that said no is presented as a crash',
    },
    {
        'file': 'src/ui/pipeline_editor_tab.py',
        'find': '        self.engine = PipelineEngine(staging_root=get_temp_directory())',
        'replace': '        self.engine = PipelineEngine()',
        'expect': 'test_59',
        'note': 'the worker stages in the current working directory instead of the app\'s temp',
    },
    {
        'file': 'src/processing/pipeline_engine.py',
        'find': '                       f"{\', \'.join(named) if named else \'nothing\'}")',
        'replace': '                       "the node has a list of its own.")',
        'expect': 'test_60_the_pane',
        'note': 'the refusal names the value that is wrong and not the values that would have '
                'worked, so the reader has to open the node to find out what to type',
    },
]
