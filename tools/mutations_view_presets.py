"""Defects to plant in the four claims this phase moved, one line at a time.

The Model pane's Settings tab carried a **Presets** group written inside a triple-quoted string
expression - valid Python that builds nothing - and its three handlers set `render_mode_combo`,
a widget nowhere in the tree, so a click would have raised out of a Qt slot even if the buttons
had existed. The Scripting pane listed nineteen hand-typed names, fifteen of which the engine
never answers to and none of which carried the `rfx.` prefix the executor injects, so the line
*Insert Code* put into the editor could not run. `load_model_file` - the path the Library's
double-click and the shell's "Open with" take - handed the file path to a slot typed
`pyqtSignal(dict)`, so a model that loaded was reported as `Failed to load model: 'str' object
has no attribute 'get'`. And the integrity dialog answered a category report with
`"\n".join(a_dict)`, which lists the key names and no paths.

So each entry below breaks one of the four in the way the shipped code used to be broken, or in
the way it would go back to being broken if one line slipped: a preset that moves a checkbox and
nothing else, a row list that no longer matches a mode the paint branches on, a surface read off
the engine replaced by a typed list, the engine's own surface emptied, a success box that arrives
whatever the viewer answered, and a dialog that names categories without counting them.

`expect` is a substring of a test name in tests/test_view_preset_contract.py; each one resolves
to exactly one test, so a defect that a different test happens to notice is reported as the hole
it is rather than as a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_view_preset_contract.py \
        tools/mutations_view_presets.py
( thirty-eight entries )
"""

MUTATIONS = [
    {
        'file': 'src/ui/model_tab.py',
        'find': '        presets_group.setLayout(presets_layout)',
        'replace': '        pass',
        'expect': 'test_01',
        'note': 'the group is built and never given its widgets, which is the shape the parked '
                'string left behind - a titled box with no buttons in the tree',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        layout.addWidget(presets_group)',
        'replace': '        pass',
        'expect': 'test_01',
        'note': 'the buttons exist but are put nowhere, so the pane has a preset it cannot show',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        preset_wireframe_btn.clicked.connect(self.apply_wireframe_preset)',
        'replace': '        pass',
        'expect': 'test_01',
        'note': 'a button nothing listens to',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        preset_solid_btn.clicked.connect(self.apply_solid_preset)',
        'replace': '        pass',
        'expect': 'test_03',
        'note': 'the Solid row stays a picture of a preset',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        preset_debug_btn.clicked.connect(self.apply_debug_preset)',
        'replace': '        pass',
        'expect': 'test_04',
        'note': 'the overlay mode keeps its button and loses its only caller',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.shader_list.addItems(["Wireframe", "Shaded", "Visualized", "Point Cloud", "Overlay"])',
        'replace': '        self.shader_list.addItems(["Wireframe", "Shaded", "Visualized", "Point Cloud"])',
        'expect': 'test_06',
        'note': 'the fourth row is dropped, so the paint branch that ships for overlay cannot be '
                'selected and the Debug preset selects nothing',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '            self.model_viewer.set_render_mode("wireframe")',
        'replace': '            self.model_viewer.set_render_mode("fill")',
        'expect': 'test_02',
        'note': 'row 0 tells the viewer to shade',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '            self.model_viewer.set_render_mode("point_cloud")',
        'replace': '            self.model_viewer.set_render_mode("fill")',
        'expect': 'test_06',
        'note': 'the Point Cloud row draws a surface',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '            self.model_viewer.set_render_mode("overlay")',
        'replace': '            self.model_viewer.set_render_mode("fill")',
        'expect': 'test_04',
        'note': 'the new row selects the mode the paint already has and never reached',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.viz_details_widget.setVisible(row == 2)',
        'replace': '        pass',
        'expect': 'test_07',
        'note': 'the Visualized controls stop following their own row',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.shader_list.setCurrentRow(0)',
        'replace': '        self.shader_list.setCurrentRow(1)',
        'expect': 'test_02',
        'note': 'the Wireframe preset leaves the pane showing Shaded',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.lighting_enable_cb.setChecked(False)',
        'replace': '        pass',
        'expect': 'test_02',
        'note': 'edges only, still lit - the checkbox the preset is supposed to move',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.line_width_spin.setValue(1.5)',
        'replace': '        pass',
        'expect': 'test_02',
        'note': 'the line width the preset claims to set is left wherever it was',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.shader_list.setCurrentRow(1)',
        'replace': '        self.shader_list.setCurrentRow(0)',
        'expect': 'test_03',
        'note': 'Solid selects the wireframe row',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.textures_cb.setChecked(True)',
        'replace': '        pass',
        'which': 2,
        'expect': 'test_03',
        'note': 'the Solid preset forgets textures, so the shader is told none while the pane '
                'advertises the surface one',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.vcolors_cb.setChecked(True)',
        'replace': '        pass',
        'which': 2,
        'expect': 'test_03',
        'note': 'the third data switch of the same preset, and the one whose value goes straight '
                'into the uniform that picks vertex colours over the base colour',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.shader_list.setCurrentRow(4)',
        'replace': '        self.shader_list.setCurrentRow(1)',
        'expect': 'test_04',
        'note': 'Debug View asks for shaded and calls it an overlay',
    },
    {
        'file': 'src/ui/model_viewer.py',
        'find': '        self.render_mode = mode',
        'replace': '        pass',
        'expect': 'test_06',
        'note': 'the one live setter behind every row - the deleted copy sat above it and was '
                'never bound, so this line is all the mode change the viewer ever had',
    },
    {
        'file': 'src/ui/model_viewer.py',
        'find': '        self.use_vertex_colors = enabled',
        'replace': '        self.use_vertex_colors = False',
        'expect': 'test_03',
        'note': 'the survivor of the same shadow pair ignores what the pane handed it, which is '
                'what a second binding of a name silently does to the one that runs',
    },
    {
        'file': 'src/ui/scripting_tab.py',
        'find': '        for call in self.script_engine.api_surface():',
        'replace': "        for call in ['get_loaded_models()', 'save_model(model, file_path)', 'convert_model(model, format)']:",
        'expect': 'test_08',
        'note': 'the pane goes back to typing its own list, and the first row it offers is a name '
                'nothing in the engine answers to',
    },
    {
        'file': 'src/ui/scripting_tab.py',
        'find': '                      for call in self.script_engine.api_surface())',
        'replace': "                      for call in ['rfx.legacy_helper(model)'])",
        'expect': 'test_11',
        'note': 'the documentation panel and the list the user clicks are built from different '
                'words, so the page explaining a call describes a call that is not there',
    },
    {
        'file': 'src/processing/script_engine.py',
        'find': '        for name, method in inspect.getmembers(self.api, predicate=inspect.ismethod):',
        'replace': '        for name, method in []:',
        'expect': 'test_19',
        'note': 'a surface read off the object answers an empty list when the reading is dropped, '
                'and every test that compares the pane to it then compares nothing to nothing',
    },
    {
        'file': 'src/processing/script_engine.py',
        'find': "            if name.startswith('_'):",
        'replace': '            if False:',
        'expect': 'test_19',
        'note': "the private helpers a script must not call are offered as API, including "
                "QObject's own",
    },
    {
        'file': 'src/processing/script_engine.py',
        'find': "                    parts.append(f'{parameter.name}={parameter.default!r}')",
        'replace': '                    parts.append(parameter.name)',
        'expect': 'test_19',
        'note': 'a parameter that has a default is shown without it, so the inserted line calls '
                'the method with fewer arguments than it takes',
    },
    {
        'file': 'src/processing/script_engine.py',
        'find': "                    parts.append('**' + parameter.name)",
        'replace': '                    parts.append(parameter.name)',
        'expect': 'test_19',
        'note': 'the keyword-splat is printed as a positional, which is not a call that runs',
    },
    {
        'file': 'src/processing/script_engine.py',
        'find': '            calls.append(f\'rfx.{name}({", ".join(parts)})\')',
        'replace': '            calls.append(f\'{name}({", ".join(parts)})\')',
        'expect': 'test_08',
        'note': 'the name is right and the spelling is wrong: without the object the executor '
                "injects, the line the pane inserts is a NameError in the user's script",
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        if not os.path.exists(file_path):',
        'replace': '        if False:',
        'which': 2,
        'expect': 'test_12',
        'note': 'a path that is not on disk is claimed as a load attempt instead of refused for '
                'the reason it cannot be one',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '                if self.load_model_in_viewer(file_path):',
        'replace': '                if True:',
        'expect': 'test_14',
        'note': 'the success box arrives whatever the viewer answered',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        success = self.model_viewer.load_model(file_path)',
        'replace': '        success = True',
        'expect': 'test_14',
        'note': 'the pane reports its own hope rather than the reader\'s verdict, and the Load '
                'Error box it also writes never appears',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '                        f"Model loaded successfully!\\n\\nFile: {file_name}"',
        'replace': '                        "Model loaded successfully!"',
        'expect': 'test_13',
        'note': 'the verdict stops naming the file it was handed, which is the only part of it a '
                'user can check',
    },
    {
        'file': 'src/ui/model_viewer.py',
        'find': '    model_loaded = pyqtSignal(dict)  # Add missing signal',
        'replace': '    model_loaded = pyqtSignal(str)  # Add missing signal',
        'expect': 'test_15',
        'note': 'the signal retyped to a path is how the load came to report `\'str\' object has '
                'no attribute \'get\'`: the measurements are what the labels read',
    },
    {
        'file': 'src/ui/library_tab.py',
        'find': '            report = self.library.check_integrity()',
        'replace': '            report = {}',
        'expect': 'test_16',
        'note': 'the dialog stops reading the backend and has nothing to say about the database',
    },
    {
        'file': 'src/ui/library_tab.py',
        'find': '            if not report:',
        'replace': '            if False:',
        'expect': 'test_18',
        'note': 'an empty answer - what the backend returns after an exception - is then read for '
                'its counts and reported as a clean library',
    },
    {
        'file': 'src/ui/library_tab.py',
        'find': '            detail = "\\n".join(lines)',
        'replace': '            detail = "\\n".join(report)',
        'expect': 'test_16',
        'note': 'the shipped bug: joining a dict yields its key names, so the dialog lists '
                'category labels and calls that a result',
    },
    {
        'file': 'src/ui/library_tab.py',
        'find': '                lines.append(f"{key}: {len(found)}")',
        'replace': '                lines.append(key)',
        'expect': 'test_16',
        'note': 'the count is what makes a category worth reading; without it the sentence is a '
                'label',
    },
    {
        'file': 'src/ui/library_tab.py',
        'find': '                lines.extend(f"  {item}" for item in found[:5])',
        'replace': '                lines.extend(f"  {item}" for item in found[:0])',
        'expect': 'test_16',
        'note': 'the paths are dropped and only the numbers are left, so nothing names the file '
                'the user has to go and look for',
    },
    {
        'file': 'src/ui/library_tab.py',
        'find': '                if len(found) > 5:',
        'replace': '                if False:',
        'expect': 'test_20',
        'note': 'a list cut to five is shown as if it were the whole list, which is how a silent '
                'truncation becomes a wrong count',
    },
    {
        'file': 'src/ui/library_tab.py',
        'find': '                    lines.append(f"  and {len(found) - 5} more")',
        'replace': '                    lines.append(f"  and {len(found)} more")',
        'expect': 'test_20',
        'note': 'the remainder is counted from the whole list instead of from what was left out',
    },
]
