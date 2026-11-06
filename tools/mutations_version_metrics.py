"""Defects to plant in the Versions commit path, one line at a time.

`save_version` read `len(mesh.faces)` off whatever `trimesh.load` answered and assumed one
shape. Measured on this machine before any of this phase's code: an `.obj` carrying
`mtllib`/`usemtl` - what the app's own `MeshRepairer.auto_repair` writes, with
`repaired_model.obj.mtl` beside it - answers `Scene`; a file whose faces were deleted answers
`PointCloud`; an empty or garbled `.obj` answers a `Scene` with no geometries. The first two
raised `AttributeError`, the method's own `except Exception` logged it and returned None, the
pane said "No changes detected", and the snapshot copied two statements earlier stayed on disk
with no row naming it. `tests/test_full_flow.py` printed `Committed version: None` and exited 0.

So the defects worth planting are these: a row that records a face count read off the wrong
attribute, or the wrong shape's numbers, or a number for a file that has none; a refusal that
arrives after the copy instead of before it, at the wrong log level, or with a reason the pane
then rewrites; a write that failed after the copy leaving its snapshot or its picture behind; a
delta invented against a parent that has no such number, or claimed against a parent the
version does not have; a volume read off a surface trimesh says is not closed; the comparison
reaching straight for `.faces` and handing the dialog a raw `AttributeError`; and the words for
an absent number - `no faces`, `no faces to close`, `not comparable` - replaced by a bare 0 or
a blank cell in each of the five places that prints one.

The `format_converter` entries are in this list because the normaliser is what the commit now
depends on: `as_trimesh` answering a Scene's first group instead of all of them, or refusing a
plain mesh, is the same defect as the row printing the wrong count, one level down.

Three entries guard a `None` test that is load-bearing rather than defensive, so they were kept
and planted instead of dropped: the two `is_volume` halves of the volume delta, and the pane's
two places that read a delta which is NULL on every first version and every cloud row. Each one
was written after its absence was measured - an open parent, a box over a point cloud, a cloud on
top of a box - so the guard is a documented dependency and not a habit.

Each entry names the test that has to fail for it; a defect no test catches is a hole in the
suite, so it gets a test rather than a pass.

Run:
    python -X utf8 tools/mutation_check.py tests/test_version_metrics_contract.py \
        tools/mutations_version_metrics.py
( forty-nine entries )
"""

VC = 'src/features/version_control.py'
UI = 'src/ui/version_control_ui.py'
FC = 'src/processing/format_converter.py'

MUTATIONS = [
    # ---- what one commit records about the file in front of it -------------------------------
    {
        'file': VC,
        'find': "                'polygon_count': len(mesh.faces),",
        'replace': "                'polygon_count': len(mesh.vertices),",
        'expect': 'test_01',
        'note': 'the face count comes from the vertex list, so every row in the timeline '
                'reports the wrong model and the deltas below it inherit the error',
    },
    {
        'file': VC,
        'find': "                'is_watertight': bool(mesh.is_watertight)}",
        'replace': "                'is_watertight': True}",
        'expect': 'test_01',
        'note': 'every committed model is recorded as sealed, which is the claim a repairer '
                'is asked to act on',
    },
    {
        'file': VC,
        'find': '    if isinstance(loaded, trimesh.PointCloud):',
        'replace': '    if False:',
        'expect': 'test_01',
        'note': 'a point cloud is no longer a shape this backend can commit, so the scan a DCC '
                'hands over is refused as a file with nothing in it',
    },
    {
        'file': VC,
        'find': "                'polygon_count': None,",
        'replace': "                'polygon_count': 0,",
        'expect': 'test_01',
        'note': 'a file with no faces is recorded as a file with zero of them, which is a flat '
                'model rather than a cloud',
    },
    {
        'file': VC,
        'find': "                'vertex_count': len(loaded.vertices),",
        'replace': "                'vertex_count': len(loaded.faces),",
        'expect': 'test_01',
        'note': 'the cloud is measured the way the mesh is, which is the exact AttributeError '
                'this phase was written because of',
    },
    {
        'file': VC,
        'find': "                'is_watertight': None}",
        'replace': "                'is_watertight': True}",
        'expect': 'test_01',
        'note': 'the row claims a point cloud is a sealed volume, a fact trimesh refuses to '
                'answer for it',
    },
    {
        'file': VC,
        'find': '    return as_trimesh(loaded)',
        'replace': '    return loaded',
        'expect': 'test_01',
        'note': 'the commit goes back to reading whatever shape trimesh happened to return, so '
                'a Scene and a mesh are no longer the same read',
    },
    {
        'file': VC,
        'find': '                shutil.copy2(model_path, snapshot_path)',
        'replace': '                pass',
        'expect': 'test_01',
        'note': 'the row records a snapshot that was never written, which rollback then reads '
                'as a missing file',
    },
    {
        'file': FC,
        'find': '    if isinstance(obj, trimesh.Trimesh):',
        'replace': '    if False:',
        'expect': 'test_01',
        'note': 'the app\'s one normaliser stops recognising a plain mesh, so the simplest file '
                'a DCC exports is refused',
    },
    {
        'file': FC,
        'find': '                return trimesh.util.concatenate(dumped) if dumped else None',
        'replace': '                return dumped[0] if dumped else None',
        'expect': 'test_02',
        'note': 'a multi-material scene is measured as its first group, so the counts are a '
                'part of the file presented as the whole of it',
    },

    # ---- refusing on a fact, before the file is copied ---------------------------------------
    {
        'file': VC,
        'find': '            if metrics is None:',
        'replace': '            if False:',
        'expect': 'test_03',
        'note': 'the refusal that nothing was measured is skipped, so an empty file is logged '
                'as a crash instead of as itself',
    },
    {
        'file': VC,
        'find': '                logger.error(f"Refusing to commit {model_path.name}: '
                '{NO_GEOMETRY}")',
        'replace': '                logger.warning(f"Refusing to commit {model_path.name}: '
                   '{NO_GEOMETRY}")',
        'expect': 'test_03',
        'note': 'the reason reaches the log below error, so a caller that collects refusals at '
                'the level the app uses never sees it',
    },
    {
        'file': VC,
        'find': '                logger.error(f"Could not read {model_path.name} to measure '
                'it: {e}")',
        'replace': '                logger.error(f"Error saving version: {e}")',
        'expect': 'test_03',
        'note': 'a file trimesh will not open is reported as a save failure, which is the '
                'message that used to make the pane blame the commit',
    },
    {
        'file': VC,
        'find': '        if not path.exists():',
        'replace': '        if False:',
        'expect': 'test_03',
        'note': 'the pane is told a file that is not on disk was unreadable, which is a '
                'different fact about a different thing',
    },
    {
        'file': VC,
        'find': "            return {'kind': 'no_file', 'reason': f'There is no file at {path} "
                "to commit.'}",
        'replace': "            return {'kind': 'no_file', 'reason': 'No changes detected.'}",
        'expect': 'test_03',
        'note': 'the missing file is explained with the sentence the pane used for every case, '
                'which is the guess this method exists to stop',
    },
    {
        'file': VC,
        'find': '        if metrics is None:',
        'replace': '        if False:',
        'expect': 'test_03',
        'note': 'a file with no geometry is explained as a commit that did not finish, sending '
                'the reader to a log that says nothing',
    },

    # ---- a write that failed takes its own files back ----------------------------------------
    {
        'file': VC,
        'find': '                if thumbnail_path:',
        'replace': '                if False:',
        'expect': 'test_04',
        'note': 'the picture of a row that was never written stays in the thumbnails folder, '
                'where the Library grid picks it up',
    },
    {
        'file': VC,
        'find': '                snapshot_path.unlink(missing_ok=True)',
        'replace': '                pass',
        'expect': 'test_04',
        'note': 'the orphan comes back: a snapshot no row names, invisible to rollback and '
                'never deleted, which is what this phase was reported for',
    },

    # ---- deltas between rows that are actually there ----------------------------------------
    {
        'file': VC,
        'find': "            'volume_delta': None,",
        'replace': "            'volume_delta': 0,",
        'expect': 'test_05',
        'note': 'a commit reports that its volume did not change when nothing was measured, '
                'which is the difference between a fact and a guess',
    },
    {
        'file': VC,
        'find': '    return None if now is None or then is None else now - then',
        'replace': '    return 0 if now is None or then is None else now - then',
        'expect': 'test_05',
        'note': 'an absent number is turned into a zero, so a mesh committed after a cloud '
                'reports twelve faces gained over a file that had none',
    },
    {
        'file': VC,
        'find': "                                     parent_version.get('polygon_count')),",
        'replace': "                                     parent_version.get('polygon_count') "
                   "or 0),",
        'expect': 'test_05',
        'note': 'the parent row\'s absence is read as a zero, which makes the delta disagree '
                'with the two numbers printed above it',
    },
    {
        'file': VC,
        'find': '        if mesh is None or not mesh.is_volume:',
        'replace': '        if mesh is None:',
        'expect': 'test_05',
        'note': 'the winding check goes, so an open surface is subtracted from a closed one and '
                'the row prints a volume change trimesh refuses to support',
    },
    {
        'file': VC,
        'find': '        if parent_mesh is None or not parent_mesh.is_volume:',
        'replace': '        if parent_mesh is None:',
        'expect': 'test_05',
        'note': 'the same check on the other side: a box committed over an open parent is given '
                'a volume gain measured against a volume the parent never had',
    },
    {
        'file': VC,
        'find': "            diff_metrics.get('volume_delta')",
        'replace': "            diff_metrics.get('volume_delta') or 0",
        'expect': 'test_05',
        'note': 'a first version claims its volume is unchanged from a parent it does not have',
    },
    {
        'file': VC,
        'find': '                           f"not measured: its snapshot could not be read '
                '({e})")',
        'replace': '                           f"not measured: the parent had no volume")',
        'expect': 'test_06',
        'note': 'the warning names a cause it did not check, so a reader hunts for a bad parent '
                'row while the snapshot file is the thing that is missing',
    },
    {
        'file': VC,
        'find': '            logger.warning(f"Volume change against v{parent_version['
                '\'version_number\']} "',
        'replace': '            logger.info(f"Volume change against v{parent_version['
                  '\'version_number\']} "',
        'expect': 'test_06',
        'note': 'a measurement that could not be made reaches the log as routine news, which is '
                'how a silently missing number becomes normal',
    },
    {
        'file': VC,
        'find': "            metrics.get('polygon_count'),",
        'replace': "            metrics.get('polygon_count') or 0,",
        'expect': 'test_01',
        'note': 'the column itself invents the number the measurement refused to give, so the '
                'NULL that means "no faces" is gone',
    },

    # ---- comparing two versions --------------------------------------------------------------
    {
        'file': VC,
        'find': "            mesh1 = _normalise(trimesh.load(v1['snapshot_path']))",
        'replace': "            mesh1 = trimesh.load(v1['snapshot_path'])",
        'expect': 'test_09',
        'note': 'one side of the comparison is no longer normalised, so the dialog is handed a '
                'raw trimesh error string for a scene or a cloud',
    },
    {
        'file': VC,
        'find': "            no_mesh = [v['version_number'] for v, m in ((v1, mesh1), "
                "(v2, mesh2)) if m is None]",
        'replace': '            no_mesh = []',
        'expect': 'test_09',
        'note': 'the answer that one of the two files has no triangle mesh is dropped and the '
                'exception that follows becomes the message',
    },
    {
        'file': VC,
        'find': "                        'v1': float(mesh1.volume) if mesh1.is_volume else None,",
        'replace': "                        'v1': float(mesh1.volume) if mesh1.is_volume else 0,",
        'expect': 'test_09',
        'note': 'an open surface is given a volume of nothing, which is a number the reader '
                'subtracts from the other side',
    },
    {
        'file': VC,
        'find': '                                  if mesh1.is_volume and mesh2.is_volume '
                'else None)',
        'replace': '                                  if mesh1.is_volume and mesh2.is_volume '
                   'else 0.0)',
        'expect': 'test_09',
        'note': 'the comparison reports two unclosed surfaces as holding each other\'s volume',
    },

    # ---- the words an absent number is printed with ------------------------------------------
    {
        'file': VC,
        'find': '    return NO_FACES if count is None else f"{count:,}"',
        'replace': '    return f"{count or 0:,}"',
        'expect': 'test_07',
        'note': 'the one helper that says "no faces" is bypassed, so every surface that uses it '
                'shows a zero instead',
    },
    {
        'file': VC,
        'find': '        return NO_WATERTIGHT',
        'replace': "        return 'No'",
        'expect': 'test_07',
        'which': 1,
        'note': 'a file with nothing to close is answered as a surface that failed to close, '
                'which is a repair the app could then be asked to run',
    },
    {
        'file': VC,
        'find': '        return NO_WATERTIGHT',
        'replace': "        return ''",
        'expect': 'test_10',
        'which': 2,
        'note': 'the comparison cell goes blank rather than saying the surface is open, and a '
                'blank cell reads as a measurement of zero',
    },
    {
        'file': VC,
        'find': '    return f"{value:+.4f}" if signed else f"{value:.4f}"',
        'replace': '    return f"{value:.4f}"',
        'expect': 'test_07',
        'note': 'a volume change loses its sign, so a model that shrank is printed as one that '
                'grew',
    },
    {
        'file': VC,
        'find': '        text = f"V: {vertices:,}, {NO_FACES}"',
        'replace': '        text = f"V: {vertices:,}"',
        'expect': 'test_07',
        'note': 'the timeline column drops the one word telling a cloud row from a mesh row',
    },
    {
        'file': VC,
        'find': "               'to measure')",
        'replace': "               'to compare')",
        'expect': 'test_08',
        'note': 'the refusal that reaches the pane is rewritten to speak about a comparison, so '
                'the reason the user reads is not the reason the commit stopped',
    },
    {
        'file': VC,
        'find': "NOT_COMPARABLE = 'not comparable - one version of this file has no faces'",
        'replace': "NOT_COMPARABLE = 'polygon evolution is not available'",
        'expect': 'test_07',
        'note': 'the statistics line no longer says which of its own rows is the reason',
    },
    {
        'file': VC,
        'find': '                        <strong>Polygons:</strong> {describe_polygon_count('
                'version)}',
        'replace': "                        <strong>Polygons:</strong> {version['polygon_count'] "
                   "or 0}",
        'expect': 'test_11',
        'note': 'the HTML a user hands over shows a point cloud as a model with no faces, which '
                'is the opposite of what the pane says',
    },

    # ---- the pane and the dialog -------------------------------------------------------------
    {
        'file': UI,
        'find': '            metrics = describe_metrics(version)',
        'replace': '            metrics = f"V: {version[\'vertex_count\']:,}"',
        'expect': 'test_07',
        'note': 'the timeline column formats the row itself again and loses the face count, so '
                'the backend\'s one wording is unused',
    },
    {
        'file': UI,
        'find': '            if polygons_delta is not None and polygons_delta < 0:',
        'replace': '            if polygons_delta < 0:',
        'expect': 'test_07',
        'note': 'the row is coloured by comparing its delta to zero, and a NULL delta - which '
                'is what every first version and every cloud row now is - is not a number',
    },
    {
        'file': UI,
        'find': '                if first_polygons is None or latest_polygons is None:',
        'replace': '                if False:',
        'expect': 'test_07',
        'note': 'the statistics line subtracts the two counts it just refused to compare, so a '
                'cloud at the top of a timeline takes the pane down with it',
    },
    {
        'file': UI,
        'find': '                    stats_text += f"<b>Polygon Evolution:</b> '
                '{NOT_COMPARABLE}"',
        'replace': '                    stats_text += "<b>Polygon Evolution:</b> 0 (0.0%)"',
        'expect': 'test_07',
        'note': 'the statistics line reports no change across a version that has no faces to '
                'count, which is a measured result it never measured',
    },
    {
        'file': UI,
        'find': '            watertight = describe_watertight(version)',
        'replace': '            watertight = \'Yes\' if version[\'is_watertight\'] else \'No\'',
        'expect': 'test_07',
        'note': 'the details pane answers the third kind of nothing with No, which is the two-'
                'way reading the backend moved away from',
    },
    {
        'file': UI,
        'find': '            details += f"<p>\u2022 Polygons: {describe_polygon_count(version)}"',
        'replace': '            details += f"<p>\u2022 Polygons: {version[\'polygon_count\'] '
                   'if version[\'polygon_count\'] is not None else 0}"',
        'expect': 'test_07',
        'note': 'the selected row prints Polygons: 0 for a file whose faces were deleted, and '
                'the reader is told to look for a flat model',
    },
    {
        'file': UI,
        'find': '        changes_table.setItem(2, 1, '
                'QTableWidgetItem(describe_volume(changes[\'volume\'][\'v1\'])))',
        'replace': '        changes_table.setItem(2, 1, QTableWidgetItem('
                   'f"{changes[\'volume\'][\'v1\'] or 0:.4f}"))',
        'expect': 'test_10',
        'note': 'the comparison dialog shows 0.0000 for the side that has no volume, which is '
                'the number that gets subtracted',
    },
    {
        'file': UI,
        'find': '                    verdict = self.version_control.explain_no_commit('
                'self.current_model)',
        'replace': "                    verdict = {'kind': 'duplicate', 'reason': 'No changes "
                   "detected.'}",
        'expect': 'test_08',
        'note': 'the pane guesses again: every silent commit is announced as an unchanged file, '
                'including the ones that were refused for having no geometry',
    },

    # ---- the two places that ask whether these bytes are already committed -------------------
    {
        'file': VC,
        'find': '        if self._is_duplicate_version(str(path), '
                'self._calculate_file_hash(path), branch):',
        'replace': '        if False:',
        'expect': 'test_08',
        'note': 'the one case in which "no changes detected" is a true sentence stops being '
                'asked about, and the pane blames the file',
    },
    {
        'file': VC,
        'find': '            if self._is_duplicate_version(str(model_path), file_hash, branch):',
        'replace': '            if False:',
        'expect': 'test_08',
        'note': 'committing the same bytes twice writes a second row, so the timeline reports a '
                'change that did not happen',
    },
]
