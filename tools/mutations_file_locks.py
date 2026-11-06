"""Defects to plant in the file-release path, one line at a time.

Each entry breaks one claim `tests/test_all_tabs_headless.py` makes about files this app
opens - a texture read that leaves the file open while its own error is kept, a read that
hands the GL upload fewer channels than the shader asks for, a texture control on the
wrapper that no longer reaches the viewer it wraps, and the same control reaching it with
the arguments swapped - and names the test that has to fail for it. A defect the suite does
not notice is a hole in the suite, so it gets a test rather than a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_all_tabs_headless.py \
        tools/mutations_file_locks.py
"""

MUTATIONS = [
    # ---- the release: a file this app read has to be free again ---------------------
    {
        'file': 'src/ui/model_viewer.py',
        'find': '            img.close()',
        'replace': '            pass',
        'expect': 'test_19',
        'note': 'the failed texture read leaves the file held by the traceback it kept',
    },
    {
        'file': 'src/ui/model_viewer.py',
        'find': "            return np.array(img.convert('RGBA'), dtype=np.uint8)",
        'replace': '            return np.array(img, dtype=np.uint8)',
        'expect': 'test_18',
        'note': 'a palette or grayscale texture reaches the upload with its own channels',
    },
    # ---- the wrapper: one implementation, reached from the control -----------------
    {
        'file': 'src/ui/model_viewer.py',
        'find': "        if hasattr(self.viewer_3d, 'set_material_texture'):",
        'replace': '        if False:',
        'expect': 'test_17',
        'note': 'the texture control answers the panel and does nothing with it',
    },
    {
        'file': 'src/ui/model_viewer.py',
        'find': '            self.viewer_3d.set_material_texture(texture_type, file_path)',
        'replace': '            self.viewer_3d.set_material_texture(file_path, texture_type)',
        'expect': 'test_17',
        'note': 'the control forwards, but hands the viewer the path where the slot belongs',
    },
]
