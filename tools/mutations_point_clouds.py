"""Mutations for the Point Clouds contract suite.

Each entry breaks one real sentence the pane tells the user, one of the two signal-ordering
defects the first live run found, or one of the three naming rules the backend owes a scheduled
task. Every entry names the test that has to fail for it; a defect the suite does not notice is
a hole in the suite.

Run:
    python -X utf8 tools/mutation_check.py tests/test_point_clouds_contract.py \
        tools/mutations_point_clouds.py
"""

MUTATIONS = [
    # ---- the dialog: what it promises and when it goes away --------------------
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '        if progress.isVisible():',
        'replace': '        if False:',
        'expect': 'test_26',
        'note': 'a verdict that arrives leaves the progress dialog standing',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '        expected = VERB_OUTPUT_FILES.get(operation, 1)',
        'replace': '        expected = 100',
        'expect': 'test_23',
        'note': 'the dialog counts percent-of-hope instead of the files the verb writes',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '            progress.canceled.connect(thread.request_stop)',
        'replace': '            pass',
        'expect': 'test_24',
        'note': 'Cancel closes the dialog but never asks the running verb to stop',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '        if self._active_thread is not thread:',
        'replace': '        if self._active_thread is thread:',
        'expect': 'test_27',
        'note': 'the back stop reports the newer run as silent when the older one ends',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '            if not silent:',
        'replace': '            if True:',
        'expect': 'test_27',
        'note': 'the follow-up measure of a verb logs a second operation for one click',
    },
    # ---- the verdict reaching the pane ----------------------------------------
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '            self.load_model(files[0], keep_history=True, announce=False)',
        'replace': '            pass',
        'expect': 'test_05',
        'note': 'a cloud verb writes its file and the next verb reads the old one',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': "        replaced = os.path.normcase(file_path) != os.path.normcase("
                "self.current_model_path or '')",
        'replace': '        replaced = True',
        'expect': 'test_18',
        'note': 'reloading the same cloud forgets the surface built from it',
    },
    # ---- the numbers the pane shows -------------------------------------------
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': "        self.info_bounds.setText(self._measure_text(stats['bounding_box'], 4))",
        'replace': "        self.info_bounds.setText(' '.join(str(v) for v in "
                   "stats['bounding_box']))",
        'expect': 'test_03',
        'note': 'the Info field no longer matches the Statistics block it is copied from',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': '            return (f"voxel {measure.get(\'voxel_size\', 0):.6g}: kept '
                '{self._count(after)} of "',
        'replace': '            return (f"voxel {measure.get(\'voxel_size\', 0):.6g}: kept '
                   '{self._count(before)} of "',
        'expect': 'test_06',
        'note': 'the sentence reports the cloud it was given, not the cloud it wrote',
    },
    {
        'file': 'src/ui/point_clouds_tab.py',
        'find': "            self.surface_format_combo.setCurrentText('.ply')",
        'replace': '            pass',
        'expect': 'test_38',
        'note': 'the surface list opens on .3mf, the one format this app cannot read back',
    },
    # ---- the refusals the backend owes the user -------------------------------
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '        if voxel <= 0.0:',
        'replace': '        if False:',
        'which': 2,
        'expect': 'test_08',
        'note': 'a voxel edge of 0 is sent to open3d instead of being refused by name',
    },
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '        if knn > before:',
        'replace': '        if False:',
        'expect': 'test_08',
        'note': 'a neighbourhood larger than the cloud is quietly answered with fewer '
                'neighbours than the user typed',
    },
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '        if len(mesh.triangles) == 0:',
        'replace': '        if False:',
        'expect': 'test_08',
        'note': 'a surface with no faces is written and reported as a reconstruction',
    },
    # ---- the name a scheduled verb gives its output ---------------------------
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '        output_path = params.get(\'output_path\')',
        'replace': '        output_path = None',
        'expect': 'test_20',
        'note': 'the file name the user typed in the Save dialog is ignored and a derived '
                'one written instead',
    },
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '        return os.path.join(folder, os.path.basename(path)) if folder '
                'else path',
        'replace': '        return path',
        'expect': 'test_39',
        'note': 'the folder a task names is ignored and every result lands beside the scan '
                'it read',
    },
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '        return os.path.join(folder, os.path.basename(path)) if folder '
                'else path',
        'replace': '        return os.path.join(folder, os.path.basename(source_path)) '
                   'if folder else source_path',
        'expect': 'test_40',
        'note': 'the original defect: the output is named after the input, so a task over '
                'D:\\scans replaces the scans and two verbs overwrite each other',
    },
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '        plane_path = self.target_path(params, path, \'plane\')',
        'replace': '        plane_path = self.target_path(params, path, \'off_plane\')',
        'expect': 'test_12',
        'note': 'both halves of a plane split get the same name, so the second write '
                'replaces the first',
    },
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '            offset = [float(params.get(axis, 0.0)) for axis in '
                '(\'dx\', \'dy\', \'dz\')]',
        'replace': '            offset = [float(params[axis]) for axis in '
                   '(\'dx\', \'dy\', \'dz\')]',
        'expect': 'test_39',
        'note': 'a task that moves a cloud along one axis is refused for not naming the '
                'other two, which its own parameter spec says are optional',
    },
    {
        'file': 'src/processing/point_cloud_processor.py',
        'find': '            angles = [float(params.get(axis, 0.0)) for axis in '
                '(\'rx\', \'ry\', \'rz\')]',
        'replace': '            angles = [float(params[axis]) for axis in '
                   '(\'rx\', \'ry\', \'rz\')]',
        'expect': 'test_39',
        'note': 'the same for a turn: naming one axis is not a refusal, it is a rotation '
                'about that axis',
    },
    # ---- the shared viewer ----------------------------------------------------
    {
        'file': 'src/ui/unified_viewer.py',
        'find': '        self.preview_worker.error_occurred.connect(self._on_preview_failed)',
        'replace': '        pass',
        'expect': 'test_31',
        'note': 'a failed render is swallowed and the panel reads "Rendering Preview..." '
                'forever',
    },
]
