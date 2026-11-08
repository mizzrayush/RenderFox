"""Format converter mutation spec: one real defect at a time, each one due a named test.

Run it with:
    python -X utf8 tools/mutation_check.py tests/test_format_converter_contract.py tools/mutations_format_converter.py

Every entry rewrites one line of the converter - the set of formats a scene can be written
as, the call the material switch chooses, the fields a written file is asked about, or the
sentence its bytes answer with - and the named test must fail because of it. The switch is
worth pinning this hard because both third-party readers under-report what they wrote: a
merged mesh holds one visual, assimp names no material in a .fbx, and pymeshlab accepts no
material parameter, so a suite that trusted the reader would pass while the file said
something else.
"""

CONVERTER = 'src/processing/format_converter.py'

MUTATIONS = [
    # --- the switch has to be a question the converter answers ------------------
    {
        'file': CONVERTER,
        'find': "    if 'preserve_materials' in options:",
        'replace': '    if False:',
        'expect': 'test_28_a_library_that_cannot_be_told_says_which_one_it_was',
        'note': 'the switch is never counted as asked, so a library that ignored it says nothing',
    },
    {
        'file': CONVERTER,
        'find': "    _SCENE_EXPORT_FORMATS = {'obj', 'ply', 'stl', 'gltf', 'glb', '3mf'}",
        'replace': "    _SCENE_EXPORT_FORMATS = {'obj', 'ply', 'stl', 'gltf', '3mf'}",
        'expect': 'test_24_the_switch_changes_which_call_runs',
        'note': 'a .glb cannot be written as a scene, so both answers fall back to the merged route',
    },
    {
        'file': CONVERTER,
        'find': "    _SCENE_EXPORT_FORMATS = {'obj', 'ply', 'stl', 'gltf', 'glb', '3mf'}",
        'replace': "    _SCENE_EXPORT_FORMATS = {'obj', 'ply', 'stl', 'gltf', 'glb', '3mf', 'off'}",
        'expect': 'test_27_a_format_with_no_room_says_that_instead_of_counting_zero',
        'note': 'a .off is asked for a scene export, which the library on this machine refuses',
    },
    {
        'file': CONVERTER,
        'find': '            if keep is not None and (_extension(Path(output_file).suffix)',
        'replace': '            if keep and (_extension(Path(output_file).suffix)',
        'expect': 'test_24_the_switch_changes_which_call_runs',
        'note': 'the answer "off" is not a call of its own; it merges the parts like nobody asked',
    },
    {
        'file': CONVERTER,
        'find': '                    ok, reason = self.write_scene(scene if keep else self.without_materials(scene),',
        'replace': '                    ok, reason = self.write_scene(scene if not keep else self.without_materials(scene),',
        'expect': 'test_24_the_switch_changes_which_call_runs',
        'note': 'the two answers are swapped, so on strips the file and off keeps it',
    },
    {
        'file': CONVERTER,
        'find': '                kept = np.array(visual.vertex_colors)',
        'replace': '                kept = None',
        'expect': 'test_26_the_switch_is_about_the_texture_not_the_painted_vertices',
        'note': 'stripping the material also takes the colours painted on the vertices, which were never asked about',
    },
    # --- the sentence is read off the bytes the file is made of -----------------
    {
        'file': CONVERTER,
        'find': "                    if 'preserve_materials' in (options or {}):",
        'replace': '                    if False:',
        'expect': 'test_27_a_format_with_no_room_says_that_instead_of_counting_zero',
        'note': 'the conversion reports the file it wrote and never says what the file still holds',
    },
    {
        'file': CONVERTER,
        'find': "    'stl': (),",
        'replace': "    'stl': ('materials',),",
        'expect': 'test_27_a_format_with_no_room_says_that_instead_of_counting_zero',
        'note': 'a triangle list is counted as if it had a material field, and answers "no materials"',
    },
    {
        'file': CONVERTER,
        'find': '    if not places:',
        'replace': '    if False:',
        'expect': 'test_27_a_format_with_no_room_says_that_instead_of_counting_zero',
        'note': 'the formats with no field for anything are read like the ones that have one',
    },
    {
        'file': CONVERTER,
        'find': "        length = int.from_bytes(raw[12:16], 'little')",
        'replace': "        length = int.from_bytes(raw[12:16], 'big')",
        'expect': 'test_29_the_answer_is_read_off_the_bytes_not_out_of_the_reader',
        'note': 'the JSON chunk of a .glb is cut at the wrong length, so nothing in it is read',
    },
    {
        'file': CONVERTER,
        'find': "        found['textures'] = len(document.get('images') or [])",
        'replace': "        found['textures'] = 0",
        'expect': 'test_29_the_answer_is_read_off_the_bytes_not_out_of_the_reader',
        'note': 'the images a container names are left out of the answer it gives',
    },
    {
        'file': CONVERTER,
        'find': r"            textures += len(re.findall(r'(?m)^\s*map_\w+', sidecar))",
        'replace': '            textures += 0',
        'expect': 'test_32_an_obj_answers_with_the_materials_its_own_sidecar_names',
        'note': 'the .mtl the file points at is opened and nothing in it is counted',
    },
    {
        'file': CONVERTER,
        'find': r"        found['uvs'] = bool(re.findall(r'(?m)^\s*vt\s', text))",
        'replace': "        found['uvs'] = True",
        'expect': 'test_32_an_obj_answers_with_the_materials_its_own_sidecar_names',
        'note': 'every .obj is answered as if it carried texture coordinates, stripped or not',
    },
    {
        'file': CONVERTER,
        'find': '        names = {line.split()[-1] for line in header.splitlines()',
        'replace': '        names = {line.split()[1] for line in header.splitlines()',
        'expect': 'test_31_a_ply_names_its_own_coordinate_columns',
        'note': 'the .ply header is read for the property type instead of the column name beside it',
    },
    {
        'file': CONVERTER,
        'find': '    if len(words) > 1 and not isinstance(value, bool) and value == 1:',
        'replace': '    if len(words) > 1 and value == 1:',
        'expect': 'test_28_a_library_that_cannot_be_told_says_which_one_it_was',
        'note': 'a yes/no field reading True is treated as a count of one, so the noun stops matching the number',
    },
    # --- a reader that cannot make sense of a file is not a failed conversion ---
    {
        'file': CONVERTER,
        'find': '                        except Exception as error:',
        'replace': '                        except ValueError as error:',
        'expect': 'test_30_a_file_that_cannot_be_read_back_leaves_the_conversion_won',
        'note': 'the sentence failing turns a written, verified file into a reported failure',
    },
]
