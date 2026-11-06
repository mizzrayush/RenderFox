"""Mutations for the Quality pane suite.

Each entry re-breaks one claim this area makes - a fix name dispatched to a verb that
does not do it, an error channel left unhooked so a dead thread reads as a spinning bar,
a `progress_callback` the house Worker always injects and a closure that never accepts
it, an analysis failure painted as a grade, a Fix All that marks rows it never touched,
an output path built by splitting on the wrong dot, a confirmation sentence that names
fewer filters than the engine runs, an export called with the shape the report does not
read - and names the test that has to fail for it. A defect the suite does not notice is
a hole in the suite, so it gets a test rather than a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_quality_analyzer_contract.py \
        tools/mutations_quality_analyzer.py
"""

MUTATIONS = [
    # ---- the dispatch table: does each name reach the verb it claims ----------------
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "    'repair_mesh': ('repair', {'operation': 'auto'}),",
        'replace': "    'repair_mesh': ('repair', {'operation': 'fill_holes'}),",
        'expect': 'test_30',
        'note': 'the catch-all row runs one filter instead of the auto-repair it says',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "    'merge_vertices': ('repair', {'operation': 'remove_duplicates'}),",
        'replace': "    'merge_vertices': ('repair', {'operation': 'remove_degenerate'}),",
        'expect': 'test_30',
        'note': 'welding vertices is answered by dropping faces',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "    'remove_degenerate_faces': ('repair', {'operation': 'remove_degenerate'}),",
        'replace': "    'remove_degenerate_faces': ('repair', {'operation': 'remove_unreferenced'}),",
        'expect': 'test_30',
        'note': 'the zero-area faces stay, and the vertices nobody uses go',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "    'fix_normals': ('repair', {'operation': 'fix_normals'}),",
        'replace': "    'fix_normals': ('repair', {'operation': 'invert_normals'}),",
        'expect': 'test_30',
        'note': 'orienting a mesh and flipping it inside out are different verbs',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "    'remesh': ('remesh', {'method': 'uniform'}),",
        'replace': "    'remesh': ('remesh', {'method': 'quad'}),",
        'expect': 'test_30',
        'note': 'the triangle quality fix pairs quads instead, on meshes that refuse it',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "    'generate_uvs': ('uv', {'method': 'trivial', 'layout': 'Basic'}),",
        'replace': "    'generate_uvs': ('uv', {'method': 'trivial', 'layout': 'Space-optimizing'}),",
        'expect': 'test_30',
        'note': 'both UV rows become the same verb',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "    'pack_uvs': ('uv', {'method': 'trivial', 'layout': 'Space-optimizing'}),",
        'replace': "    'pack_uvs': ('uv', {'method': 'trivial', 'layout': 'Basic'}),",
        'expect': 'test_30',
        'note': 'packing is offered and the basic layout runs',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '    verb = FIX_VERBS.get(fix_action)',
        'replace': "    verb = FIX_VERBS.get(fix_action) or ('repair', {'operation': 'auto'})",
        'expect': 'test_12',
        'note': 'an unknown fix name silently auto-repairs the model',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '    if fix_action in QualityAnalyzer.OWNED_ELSEWHERE:',
        'replace': '    if False:',
        'expect': 'test_11',
        'note': 'the two routed names fall through to "no backend", which sends the user '
                'nowhere',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        return MeshUV.parametrize(model_path, target, **kwargs)',
        'replace': "        return MeshUV.parametrize(model_path, target, method='flat_plane')",
        'expect': 'test_09',
        'note': 'the knobs the pane chose are thrown away before the filter is called',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '    root, ext = os.path.splitext(model_path)',
        'replace': "    root, ext = model_path.split('.')[0], '.' + model_path.split('.')[-1]",
        'expect': 'test_13',
        'note': 'a folder whose name contains a dot is cut in half',
    },
    # ---- the worker contract --------------------------------------------------------
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        def worker_func(processor, path, action, progress_callback=None):',
        'replace': '        def worker_func(processor, path, action):',
        'expect': 'test_24',
        'note': 'the house Worker injects progress_callback into every callback, so the '
                'single-fix path dies on the way in',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        def worker_func(processor, path, progress_callback=None):',
        'replace': '        def worker_func(processor, path):',
        'expect': 'test_24',
        'note': 'the same defect on the Fix All path',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        worker.signals.error.connect(self.on_fix_failed)',
        'replace': '        worker.signals.error.connect(lambda _e: None)',
        'which': 1,
        'expect': 'test_25',
        'note': 'the single fix swallows its own failure: the bar stops, nothing is said',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        worker.signals.error.connect(self.on_fix_failed)',
        'replace': '        worker.signals.error.connect(lambda _e: None)',
        'which': 2,
        'expect': 'test_25',
        'note': 'Fix All swallows its own failure',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        self.worker.error_occurred.connect(self.on_analysis_error)',
        'replace': '        pass',
        'expect': 'test_21',
        'note': 'the SafeWorker channel that actually fires has no listener, so Analyze '
                'stays disabled and the bar spins',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        self.worker.analysis_done.connect(self.on_analysis_complete)',
        'replace': '        pass',
        'expect': 'test_23',
        'note': 'the analysis comes back to nobody',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '    analysis_done = pyqtSignal(dict)',
        'replace': '    finished = pyqtSignal(dict)',
        'expect': 'test_23',
        'note': 'the subclass signal shadows the QThread built-in Qt itself emits',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "        if result.get('error'):",
        'replace': '        if False:',
        'expect': 'test_22',
        'note': 'a file the app never opened is scored 0 and graded F as if it had been '
                'measured',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        if not fix_action:',
        'replace': '        if False:',
        'expect': 'test_20',
        'note': 'an advice row starts a thread for a verb that does not exist',
    },
    # ---- what the pane says about a run ---------------------------------------------
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "                    if suggestion.get('fix_action') not in QualityAnalyzer.FIX_ALL_COVERS:",
        'replace': '                    if False:',
        'expect': 'test_17',
        'note': 'every row is marked (Applied) after one auto-repair, UV suggestions too',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '                                        + (f"\\n\\n{steps}" if steps else ""))',
        'replace': '                                        + "")',
        'expect': 'test_18',
        'note': "the engine's own sentences are dropped from the success message",
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '               "drop unreferenced vertices. The result is written to a new file beside "',
        'replace': '               "drop nothing else. The result is written to a new file beside "',
        'expect': 'test_14',
        'note': 'the sentence the user confirms no longer names the filters that run',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '        QMessageBox.information(self, "Report Exported",',
        'replace': '        QMessageBox.information(self, "Nothing Exported",',
        'expect': 'test_26',
        'note': 'the pane stops telling the user which file it wrote',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '                {self.current_model_path: self.analysis_result}, str(output_path))',
        'replace': '                self.analysis_result, str(output_path))',
        'expect': 'test_26',
        'note': 'the flat analysis has no .items(), so the report raises and writes '
                'nothing - the defect this pass was written for',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "        if analysis.get('error'):",
        'replace': '        if False:',
        'expect': 'test_28',
        'note': 'the compare dialog reads metrics off a result that has none',
    },
    # ---- the analyzer owns the vocabulary -------------------------------------------
    {
        'file': 'src/features/quality_analyzer.py',
        'find': "                    'one_click': fix_type in self.ONE_CLICK_FIXES,",
        'replace': "                    'one_click': True,",
        'expect': 'test_03',
        'note': 'every suggestion claims a one-click fix the pane may not be able to do',
    },
    {
        'file': 'src/features/quality_analyzer.py',
        'find': "                    'other_pane': self.OWNED_ELSEWHERE.get(fix_type),",
        'replace': "                    'other_pane': None,",
        'expect': 'test_03',
        'note': 'the two fixes another pane owns lose their route',
    },
    {
        'file': 'src/features/quality_analyzer.py',
        'find': "                       'fix_normals', 'remesh', 'generate_uvs', 'pack_uvs')",
        'replace': "                       'fix_normals', 'remesh', 'generate_uvs')",
        'expect': 'test_01',
        'note': 'a name is promised by a check with nothing that applies or routes it',
    },
    {
        'file': 'src/features/quality_analyzer.py',
        'find': "        'generate_lods': 'LOD levels are written by the Pre-Processing pane, which owns '",
        'replace': "        'generate_lods': 'LOD levels are not supported automatically, '",
        'expect': 'test_04',
        'note': 'the route names no pane, so the user cannot find the control that does',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': "            fields = issue if hasattr(issue, 'get') else {'type': 'issue', 'message': str(issue)}",
        'replace': "            fields = issue",
        'expect': 'test_38',
        'note': 'the issue painter asks a bare sentence for its keys, inside a Qt slot',
    },
    {
        'file': 'src/features/quality_analyzer.py',
        'find': '        self.issue_fixes = self._load_fix_mappings()',
        'replace': '        self.issue_fixes = {}',
        'expect': 'test_02',
        'note': 'the descriptions fall back to "Manual fix required" for all nine names',
    },
    # ---- the report's own text: does the file say what the button promised ----------
    {
        'file': 'src/features/quality_analyzer.py',
        'find': '        html = head + f"""',
        'replace': '        html = head + """',
        'expect': 'test_26',
        'note': 'the model count stops being substituted, so the header of the report is '
                'a literal brace expression',
    },
    # ---- the one reader: what a scene-shaped file is counted as ---------------------
    {
        'file': 'src/processing/mesh_processor.py',
        'find': '            meshes = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]',
        'replace': '            meshes = []',
        'expect': 'test_35',
        'note': 'a multi-material .obj is read as a file with no mesh in it',
    },
    {
        'file': 'src/processing/mesh_processor.py',
        'find': '            mesh = MeshUV.read_unprocessed(mesh_path)',
        'replace': '            mesh = trimesh.load(mesh_path, process=False)',
        'expect': 'test_35',
        'which': 2,
        'note': 'strip goes back to asking the scene wrapper for its texture coordinates',
    },
    # ---- the weld: does the verdict count the positions it joined -------------------
    {
        'file': 'src/processing/mesh_processor.py',
        'find': "                'removed': original_vertices - final_vertices,",
        'replace': "                'removed': 0,",
        'expect': 'test_33',
        'which': 1,
        'note': 'the fix says it welded nothing on a file that doubles two corners',
    },
    # ---- the reload prompt: a Yes that leaves the pane on the old file --------------
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '                if reply == QMessageBox.StandardButton.Yes:',
        'replace': '                if False:',
        'expect': 'test_31',
        'which': 1,
        'note': 'the single Fix says "Load the fixed model?" and keeps the old one',
    },
    {
        'file': 'src/ui/quality_analyzer_ui.py',
        'find': '                if reply == QMessageBox.StandardButton.Yes:',
        'replace': '                if False:',
        'expect': 'test_37',
        'which': 2,
        'note': 'Fix All asks the same question and ignores the same answer',
    },
]
