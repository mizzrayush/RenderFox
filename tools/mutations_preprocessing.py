"""Pre-Processing mutation spec: one real defect at a time, each one due a named test.

Run it with:
    python -X utf8 tools/mutation_check.py tests/test_preprocessing_contract.py tools/mutations_preprocessing.py

Every entry rewrites one line of the product - a reader's face test, a clustering
parameter, the sentence a fallback writes, the pane's dialog wiring, a worker's reference,
the typable box's echo - and the named test has to fail because of it. A defect nobody
names is a claim this suite does not actually make.
"""

EXTRACT = 'src/processing/model_extractor.py'
READER = 'src/processing/format_converter.py'
TEXTURES = 'src/processing/texture_optimizer.py'
SCENE = 'src/processing/scene_optimizer.py'
BAKER = 'src/processing/texture_baker.py'
LODS = 'src/processing/lod_generator.py'
PANE = 'src/ui/preprocessing_tab.py'

MUTATIONS = [
    # --- the reader: a mesh means faces ---------------------------------------
    {
        'file': READER,
        'find': '            if mesh is not None and len(mesh.faces):',
        'replace': '            if mesh is not None:',
        'expect': 'test_no_reader_branch_calls_a_faceless_read_a_mesh',
        'note': 'the trimesh branch accepts a result with no faces and reports a read',
    },
    {
        'file': READER,
        'find': '                    if current.face_number():',
        'replace': '                    if True:',
        'expect': 'test_one_reader_and_a_named_refusal_for_the_rest',
        'note': "PyMeshLab's one-vertex read of a text file becomes a model again",
    },
    {
        'file': READER,
        'find': '                if mesh is not None and len(mesh.faces):',
        'replace': '                if mesh is not None:',
        'expect': 'test_no_reader_branch_calls_a_faceless_read_a_mesh',
        'note': 'the assimp branch accepts an empty scene and reports a read',
    },

    # --- extraction: a partition, and a fallback that says so -----------------
    {
        'file': EXTRACT,
        'find': '        eps = float(np.mean(mesh.edges_unique_length)) * 2.0',
        'replace': '        eps = float(np.mean(mesh.extents)) * 0.1',
        'expect': 'test_a_group_of_faces_is_a_group_and_not_a_fragment',
        'note': 'a tenth of the bounding box is smaller than the gap across a solid, so one '
                'tetrahedron becomes four models',
    },
    {
        'file': EXTRACT,
        'find': '            if notes is not None:',
        'replace': '            if False:',
        'which': 3,
        'expect': 'test_a_method_that_could_not_run_names_the_one_that_did',
        'note': 'geometric analysis silently becomes connectivity on a build with no vhacdx',
    },

    # --- the texture group: the number typed is the number applied ------------
    {
        'file': TEXTURES,
        'find': '        applied = min(max(int(quality), 1), 100)',
        'replace': '        applied = int(quality)',
        'expect': 'test_a_quality_the_encoders_reject_is_applied_and_said',
        'note': 'a quality outside the encoders band is passed to them and never reported',
    },
    {
        'file': SCENE,
        'find': "            'parts': len(instances),",
        'replace': "            'parts': 0,",
        'expect': 'test_preview_counts_both_groups_and_writes_nothing',
        'note': 'the preview prints a scene it counted as empty',
    },

    # --- baking: every early return still ends in a verdict --------------------
    {
        'file': BAKER,
        'find': '            self.baking_complete.emit(False, {})',
        'replace': '            pass',
        'which': 1,
        'expect': 'test_every_refusal_still_ends_in_a_verdict',
        'note': 'a refusal with no verdict leaves the pane waiting behind a modal dialog',
    },

    # --- the pane: workers, dialogs, and the typable box ----------------------
    {
        'file': PANE,
        'find': '        self.extraction_thread = self._keep_worker(ModelExtractionThread(',
        'replace': '        self.extraction_thread = (ModelExtractionThread(',
        'expect': 'test_no_worker_can_be_dropped_while_it_still_runs',
        'note': 'a running thread loses its last reference and Qt terminates the process',
    },
    {
        'file': PANE,
        'find': '        progress.setValue(done)',
        'replace': '        self.lod_progress.setValue(done)',
        'expect': 'test_a_stage_handler_never_asks_the_dialog_from_the_attribute',
        'note': 'the handler re-reads the attribute after the pump inside setValue finished '
                'the run, and raises on None',
    },
    {
        'file': PANE,
        'find': '        self.extraction_progress.canceled.connect(self.extraction_thread.request_stop)',
        'replace': "        self.extraction_progress.setWindowTitle('Extracting models...')",
        'expect': 'test_every_progress_dialog_cancel_reaches_its_worker',
        'note': "Cancel on the extraction dialog becomes a button that stops nothing",
    },
    {
        'file': PANE,
        'find': "            'quality': self.texture_quality_value.value(),",
        'replace': "            'quality': self.texture_quality.value(),",
        'expect': 'test_quality_has_a_typable_box_that_outlives_the_slider',
        'note': 'the box is decorative: the run reads the slider, which cannot leave 1..100',
    },
    {
        'file': PANE,
        'find': '            lambda v: _sync_quietly(self.texture_quality, min(max(v, 1), 100)))',
        'replace': '            lambda v: self.texture_quality.setValue(min(max(v, 1), 100)))',
        'expect': 'test_quality_has_a_typable_box_that_outlives_the_slider',
        'note': 'the slider echoes its clamped value back into the box and erases what was typed',
    },
    {
        'file': PANE,
        'find': "            'max_size': self.texture_max_size.value() or None,",
        'replace': "            'max_size': self.texture_max_size.value(),",
        'expect': 'test_quality_has_a_typable_box_that_outlives_the_slider',
        'note': '"No cap" becomes a cap of zero pixels, which no encoder can honour',
    },

    # --- the LOD chain preview: one row per level, only numbers the file gives ---
    {
        'file': LODS,
        'find': '            for i, ratio in enumerate(lod_ratios):',
        'replace': '            for i, ratio in enumerate(list(lod_ratios) + list(lod_ratios[-1:])):',
        'expect': 'test_the_lod_preview_shows_one_row_per_level_asked',
        'note': 'the last level is previewed twice, which is what HEAD did after the loop '
                'with the leaked i and ratio',
    },
    {
        'file': LODS,
        'find': '                target_faces = int(original_faces * ratio)',
        'replace': '                target_faces = original_faces',
        'expect': 'test_the_lod_preview_prints_faces_the_file_has_and_no_guesses',
        'note': 'every level shows the original face count, so the chain promises a '
                'reduction it never applies',
    },
    {
        'file': PANE,
        'find': '                f"{ratio_text} of original, {reduction_text} reduction)\\n"',
        'replace': "                f\"{ratio_text} of original, "
                   "{data.get('estimated_file_size_mb', 0):.2f} MB)\\n\"",
        'expect': 'test_the_lod_preview_prints_faces_the_file_has_and_no_guesses',
        'note': 'the row quotes a size guessed as (vertices*30 + faces*15) bytes instead '
                'of the reduction the level was measured at',
    },

    # --- the pane: a new file forgets the reports of the file before it --------
    {
        'file': PANE,
        'find': '        self.extracted_models = []',
        'replace': '        pass',
        'which': 2,
        'expect': 'test_loading_a_file_forgets_the_one_it_replaced',
        'note': 'Export writes the previous files parts into the folder of the new one',
    },
    {
        'file': PANE,
        'find': "        self.opt_results.setPlainText('')",
        'replace': '        pass',
        'expect': 'test_loading_a_file_forgets_the_one_it_replaced',
        'note': 'the Advanced pane keeps showing the byte counts of the file it replaced',
    },
]
