"""Defects to plant in how the AI tagger gets its picture, one line at a time.

CLIP decides the tagger's category from an image, so the two things worth breaking here are
the image and the claim built on it. The image: this app used to make it with an OpenGL
context inside the tagger's worker thread, and a second GL window in one process was measured
never answering - the thread sat in `poll_events` for over three minutes. The claim:
`ai_powered` says CLIP judged this asset, and a preview the raster refused is not a judgement.

Each entry names the test that has to fail for it.

Run:
    python -X utf8 tools/mutation_check.py tests/test_ai_tagger_contract.py \
        tools/mutations_ai_tagger.py
"""

MUTATIONS = [
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': "            if not outcome.get('rendered'):",
        'replace': '            if False:',
        'expect': 'test_03',
        'note': 'the raster\'s own verdict is ignored, so whatever the file happens to be is '
                'called a picture of the model',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': "                return picture.convert('RGB').copy()",
        'replace': '                return picture',
        'expect': 'test_01',
        'note': 'the lazy reader keeps the preview file open, so the next export over it '
                'cannot write and the temp folder never empties',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': "                    analysis['ai_powered'] = True",
        'replace': '                    pass',
        'expect': 'test_02',
        'note': 'CLIP judged a real frame and the verdict no longer says it did',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': "                'ai_powered': False",
        'replace': "                'ai_powered': self.use_clip",
        'expect': 'test_03',
        'note': 'the claim is made from what is installed rather than from the frame that '
                'was drawn, which is the shape the refused draw exposes',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': '            outcome = generate_3d_thumbnail(model_path, out_path, size=side) or {}',
        'replace': '            import open3d as o3d; o3d.visualization.Visualizer(); outcome = {}',
        'expect': 'test_02',
        'note': 'the GL window comes back for the preview, which is the call that never '
                'returns once another context has been opened',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': '        import tempfile',
        'replace': '        import open3d as o3d',
        'expect': 'test_04',
        'note': 'a second renderer re-enters the file as an import, which is how it started',
    },
]
