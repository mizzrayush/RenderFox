"""Render samples mutation spec (Phase 15c-1): one real defect at a time, each due a named test.

Run it with:
    python -X utf8 tools/mutation_check.py tests/test_render_samples_contract.py tools/mutations_render_samples.py

The count has to travel the whole way - the job's default, the flag each engine emits,
the Dashboard box that sets it, the preset that used to write it into a render_settings
object the job never had, and the export/import round trip. Cinema 4D is pinned the other
way: its command line has no sample parameter, so a defect that invents one must fail.
"""

MODELS = 'src/core/models.py'
ENGINES = 'src/processing/render_engines.py'
DASHBOARD = 'src/ui/dashboard_tab.py'

MUTATIONS = [
    {
        'file': MODELS,
        'find': '    samples: int = 128',
        'replace': '    samples: int = 0',
        'which': 1,
        'expect': 'test_01_a_job_carries_a_default_of_128',
        'note': 'the job ships a sample count of zero instead of the baseline 128',
    },
    {
        'file': ENGINES,
        'find': '            f"import bpy; bpy.context.scene.render.resolution_x = {job.resolution[0]}; bpy.context.scene.render.resolution_y = {job.resolution[1]}; bpy.context.scene.cycles.samples = {max(1, int(job.samples))}"',
        'replace': '            f"import bpy; bpy.context.scene.render.resolution_x = {job.resolution[0]}; bpy.context.scene.render.resolution_y = {job.resolution[1]}"',
        'expect': 'test_02_blender_sets_cycles_samples_in_the_python_expr',
        'note': 'Blender is told the resolution but never the sample count',
    },
    {
        'file': ENGINES,
        'find': '            f"setAttr defaultArnoldRenderOptions.AASamples {max(1, int(job.samples))};")',
        'replace': '            f"setAttr defaultArnoldRenderOptions.AASamples {max(1, int(job.samples)) + 1};")',
        'expect': 'test_03_maya_sets_arnold_aa_samples_in_the_mel',
        'note': 'Maya is handed a sample count one higher than the job asked for',
    },
    {
        'file': ENGINES,
        'find': '            "SpatialSampleCount": max(1, int(job.samples)),',
        'replace': '            "SpatialSampleCount": 1,',
        'expect': 'test_04_unreal_writes_the_sample_count_into_the_config',
        'note': 'the Unreal pipeline config always names one sample, whatever the job carries',
    },
    {
        'file': ENGINES,
        'find': '            "-render", job.project_file  # C4D file',
        'replace': '            "-render", job.project_file, "-samples", str(job.samples)  # C4D file',
        'expect': 'test_05_cinema4d_invents_no_samples_flag',
        'note': 'Cinema 4D is handed a -samples flag its command line does not have',
    },
    {
        'file': ENGINES,
        'find': '            f"import bpy; bpy.context.scene.render.resolution_x = {job.resolution[0]}; bpy.context.scene.render.resolution_y = {job.resolution[1]}; bpy.context.scene.cycles.samples = {max(1, int(job.samples))}"',
        'replace': '            f"import bpy; bpy.context.scene.render.resolution_x = {job.resolution[0]}; bpy.context.scene.render.resolution_y = {job.resolution[1]}; bpy.context.scene.cycles.samples = {int(job.samples)}"',
        'expect': 'test_06_a_zero_or_negative_is_made_safe_not_emitted_raw',
        'note': 'a zero or negative sample count reaches Blender raw instead of being made safe',
    },
    {
        'file': DASHBOARD,
        'find': '        self.samples_spin.setRange(1, 4096)',
        'replace': '        self.samples_spin.setRange(1, 256)',
        'expect': 'test_07_the_dialog_offers_a_typable_samples_box_defaulting_to_128',
        'note': 'the Samples box caps at 256 instead of the 4096 the control promises',
    },
    {
        'file': DASHBOARD,
        'find': '        self.samples_spin.setValue(128)',
        'replace': '        self.samples_spin.setValue(64)',
        'expect': 'test_07_the_dialog_offers_a_typable_samples_box_defaulting_to_128',
        'note': 'the Samples box opens at 64 instead of the baseline 128',
    },
    {
        'file': DASHBOARD,
        'find': "            'samples': self.samples_spin.value(),",
        'replace': "            'samples': 128,",
        'expect': 'test_08_the_dialogs_answer_carries_the_samples_it_shows',
        'note': 'the dialog answers with a fixed 128 instead of the count it shows',
    },
    {
        'file': DASHBOARD,
        'find': "                samples=job_data['samples'],",
        'replace': "                samples=128,",
        'expect': 'test_09_add_new_job_builds_a_job_with_the_samples_chosen',
        'note': 'the job is built with a fixed 128, dropping the count the dialog chose',
    },
    {
        'file': DASHBOARD,
        'find': '                    job.samples = config["samples"]',
        'replace': '                    job.samples = 128',
        'expect': 'test_10_the_preset_writes_the_sample_count_onto_the_job',
        'note': 'the preset writes a fixed 128 instead of the sample count it names',
    },
    {
        'file': DASHBOARD,
        'find': '                        "samples": job.samples,',
        'replace': '                        "samples": 128,',
        'expect': 'test_11_export_and_import_round_trip_the_samples',
        'note': 'an exported job always records 128, so the count cannot round trip',
    },
    {
        'file': DASHBOARD,
        'find': '                            samples=job_data.get("samples", 128),',
        'replace': '                            samples=128,',
        'expect': 'test_11_export_and_import_round_trip_the_samples',
        'note': 'an imported job ignores the file\'s sample count and takes 128',
    },
]