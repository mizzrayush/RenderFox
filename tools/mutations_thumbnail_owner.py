"""Defects to plant in the one picture maker, one line at a time.

The app had three ways to draw a model into a small image and two of them opened an Open3D
window to do it. Phase 6m measured what that shape costs in a worker: 392 s with the progress
bar still spinning, and a `cancel()` flag a thread blocked inside a native call never reads.
The Versions pane's Commit button ran one on the interface thread, so the whole window waited
on a GL context there, and its `destroy_window` sat after the capture - any raise in between
left the window alive. Both are now the QPainter raster the Library, the Automation and the
tagger already use, and the grid module that started the first is deleted.

So the defects worth planting are these: a version that records a picture it never drew, or a
picture of the wrong snapshot, or one whose refusal it does not honour; a badge file left in
the thumbnails folder for a row to pick up; a refusal that reaches the log at the wrong level,
so the pane's own reason never arrives; the Versions pane painting a row other than the
selected one, keeping the previous picture, or telling the three kinds of nothing apart; the
picture built but never put in the pane, or not beside the numbers it belongs to; a model file
that is not on disk answered by an exception instead of by that fact; and the four structural
claims - the deleted pair staying deleted, every picture maker still asking the raster, no
maker opening a window, and no window in the layers the app runs its workers in.

The structural ones are planted by rewriting a real caller's own line, because a window added
to a module the suite imports would be opened while the suite ran - which is exactly the hang
this phase removed, and a runner cannot report one. Each entry names the test that has to fail
for it; a defect no test catches is a hole in the suite, so it gets a test rather than a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_thumbnail_owner_contract.py \
        tools/mutations_thumbnail_owner.py
( twenty-three entries )
"""

MUTATIONS = [
    {
        'file': 'src/features/version_control.py',
        'find': '            thumbnail_path = self._generate_thumbnail(snapshot_path)',
        'replace': '            thumbnail_path = None',
        'expect': 'test_04',
        'note': 'the commit stops recording a picture at all, so the timeline is rows and '
                'numbers with nothing to look at',
    },
    {
        'file': 'src/features/version_control.py',
        'find': "        thumb_path = self.thumbnails_dir / (Path(snapshot_path).stem + '.png')",
        'replace': "        thumb_path = self.thumbnails_dir / (Path(snapshot_path).name + '.png')",
        'expect': 'test_04',
        'note': 'the picture is named for the model file instead of for the snapshot its row '
                'points at, which is how two `chair.obj` used to overwrite one another',
    },
    {
        'file': 'src/features/version_control.py',
        'find': '        outcome = generate_3d_thumbnail(str(snapshot_path), str(thumb_path), size=256) or {}',
        'replace': '        outcome = generate_3d_thumbnail(str(snapshot_path), str(thumb_path), size=64) or {}',
        'expect': 'test_04',
        'note': 'the version writes a picture at a size nothing else in the app uses, so the '
                'row\'s file is not the frame the rest of the Library draws',
    },
    {
        'file': 'src/features/version_control.py',
        'find': "        if not outcome.get('rendered'):",
        'replace': '        if False:',
        'expect': 'test_05',
        'note': 'the raster\'s own refusal is ignored, so a model that was never drawn records '
                'a wireframe crate as its picture',
    },
    {
        'file': 'src/features/version_control.py',
        'find': '            thumb_path.unlink(missing_ok=True)',
        'replace': '            pass',
        'expect': 'test_05',
        'note': 'the badge a refused draw leaves behind stays in the thumbnails folder, where '
                'another row can find it',
    },
    {
        'file': 'src/features/version_control.py',
        'find': '            logger.warning(f"No picture for {thumb_path.name}: "',
        'replace': '            logger.debug(f"No picture for {thumb_path.name}: "',
        'expect': 'test_05',
        'note': 'the refusal is logged below the level the app reports at, so the reason the '
                'raster gave never reaches a log file',
    },
    {
        'file': 'src/features/version_control.py',
        'find': '        return str(thumb_path)',
        'replace': '        return None',
        'expect': 'test_04',
        'note': 'a picture that was drawn is answered as if it had not been, and the row keeps '
                'an empty column',
    },
    {
        'file': 'src/features/version_control.py',
        'find': '            if not model_path.exists():',
        'replace': '            if False:',
        'expect': 'test_07',
        'note': 'a model that is not on disk is committed anyway and the pane swallows the '
                'loader\'s exception instead of stating the fact',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': "            self.version_picture.setText('This version has no picture')",
        'replace': "            self.version_picture.setText('')",
        'expect': 'test_06',
        'note': 'the refusal says nothing, and since a sentence is what withdraws the label\'s '
                'picture, the newest row stays on screen over a row that has none',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': "        path = version.get('thumbnail_path')",
        'replace': '        path = None',
        'expect': 'test_06',
        'note': 'the pane stops reading the column every row carries, and the timeline goes '
                'back to numbers only',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': "            self.version_picture.setText('This version has no picture')",
        'replace': "            self.version_picture.setText('Its picture file could not be read')",
        'expect': 'test_06',
        'note': 'a version that never had a picture is blamed on a file that is missing, which '
                'is a different fact and sends the user looking for a deleted PNG',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': "            self.version_picture.setText('Its picture file could not be read')",
        'replace': "            self.version_picture.setText('This version has no picture')",
        'expect': 'test_06',
        'note': 'the other direction of the same swap: a picture that went missing is reported '
                'as a version that never had one',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': "            self.version_picture.setText('No version selected')",
        'replace': "            self.version_picture.setText('This version has no picture')",
        'expect': 'test_06',
        'note': 'an empty selection speaks about a version that was not selected',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': '            148, 148, Qt.AspectRatioMode.KeepAspectRatio,',
        'replace': '            150, 150, Qt.AspectRatioMode.KeepAspectRatio,',
        'expect': 'test_06',
        'note': 'the picture is scaled past the frame it sits in, so its border is cropped by '
                'the label that holds it',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': '        self._show_version_picture(version)',
        'replace': '        pass',
        'expect': 'test_06',
        'note': 'selecting a row updates the numbers and leaves the picture wherever it was',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': '            self._show_version_picture(None)',
        'replace': '            pass',
        'expect': 'test_06',
        'note': 'clearing the selection keeps the last version\'s picture on screen',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': '        details_row.addWidget(self.version_picture)',
        'replace': '        pass',
        'expect': 'test_06',
        'note': 'the label is built, painted and put nowhere in the pane, so nothing a test '
                'can see about its contents is something a user could see',
    },
    {
        'file': 'src/ui/version_control_ui.py',
        'find': '        details_row.addWidget(self.details_text, 1)',
        'replace': '        pass',
        'expect': 'test_06',
        'note': 'the numbers move out of the row the picture is in, and the pane is a picture '
                'and a block of text that no longer belong to each other',
    },
    {
        'file': 'src/core/library_manager.py',
        'find': '                    outcome = generate_3d_thumbnail(model_path, thumb_path, size=256) or {}',
        'replace': '                    outcome = o3d.visualization.Visualizer().capture_screen_float_buffer()',
        'expect': 'test_03',
        'note': 'a window is back in the layer the app runs its workers in, which is the shape '
                'that answered a cancel with 392 s',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': '        from ..utils.thumbnail_renderer import generate_3d_thumbnail',
        'replace': '        from src.ui.library_grid import LibraryGridWidget',
        'expect': 'test_01',
        'note': 'the deleted grid widget is imported again from inside a function, so the '
                'per-file Open3D thumbnail thread is one call away from running',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': '        from ..utils.thumbnail_renderer import generate_3d_thumbnail',
        'replace': '        from ..utils.thumbnail_renderer import generate_3d_thumbnail  # was src/core/thumbnail_generator.py',
        'expect': 'test_01',
        'note': 'a file that ships inside the app names the deleted module, which is how a '
                'lazy `importlib` or a string entry point would arrive',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': '            outcome = generate_3d_thumbnail(model_path, out_path, size=side) or {}',
        'replace': "            outcome = {'rendered': True}",
        'expect': 'test_02',
        'note': 'a picture maker asks the raster and then reports what it hoped for, so the '
                'category the tagger judged is a judgement about nothing drawn',
    },
    {
        'file': 'src/features/automation_engine.py',
        'find': '            outcome = generate_3d_thumbnail(input_file, destination, size=size) or {}',
        'replace': '            outcome = generate_3d_thumbnail(input_file, destination, size=size) or o3d.visualization.Visualizer().capture_screen_float_buffer()',
        'expect': 'test_02',
        'note': 'the raster stays and a window comes back as its fallback, which is the half '
                'the picture maker\'s own check guards and the file-level scan cannot see',
    },
]
