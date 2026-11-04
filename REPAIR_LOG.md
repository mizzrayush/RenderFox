# RenderFox Repair Log

**Working document, not documentation.** If context is compressed, read this file first: it holds the plan, the full bug inventory with file:line, the decisions already made, and what has been proven fixed. Update it after every commit.

---

## Ground rules for this pass

- **No 3D software is installed on this machine.** No Blender, Maya, Unreal or C4D anywhere (`C:\Program Files\Blender Foundation` absent, nothing on PATH). Real DCC rendering cannot be verified here — correctness comes from the mock DCC harness plus reading the diff. Never claim a real render works.
- Repo remote: `https://github.com/mizzrayush/RenderFox` (private). Baseline = commit `1727f94` "Baseline: RenderFox pre-repair snapshot", pushed to `origin/main`.
- Binaries, model weights, packaged builds and `patch_script/` are gitignored. GitHub rejects single files over 100 MB; the folder is 4.2 GB.
- One commit per fix area, so any single change is revertable.
- Surgical edits only. No loss: account for every deleted line before calling something removed.
- Backend owns the vocabulary. When UI and backend disagree on a parameter name, fix the **caller**, not by adding a compatibility alias in the backend.

## Code size (for reference)

Counted over `git ls-files "*.py"` - tracked source only, so build output, vendored
binaries and `patch_script/` are not in it. "Raw" is every line; "Code" skips
blank lines and whole-line comments, and is the honest answer to "how many lines
did you write" because a docstring counts as code here.

| Bucket | Files | Raw | Code |
|---|---|---|---|
| `src/` at the pre-repair baseline (`1727f94`) | 73 | 56,111 | 41,523 |
| `src/` now | 73 | 56,990 | 42,360 |
| `tests/` (incl. `tests/mock_dcc/`) at baseline | 22 | 2,257 | 1,620 |
| `tests/` now | 32 | 4,610 | 3,582 |
| entry + tooling scripts at the root | 5 | 581 | ~450 |
| `installer.nsi` + `RenderFox.spec` | 2 | 210 | 158 |
| dead code inside `src/` (to be deleted) | 10 | 6,081 | 4,624 |

Headline for a README or a conversation: **~57k lines of application code in
`src/` (~42k non-blank), plus ~4.6k of tests.** Say "application code" and
"tests" separately - folding them together invites the reply "so half of it was
generated?". The repair pass itself is +879 raw in `src/` and +2,353 in `tests/`
(the mock renderers, the harness, the contract and mutation suites), which is
the honest answer to "what did the AI write": the app, every tab and every
feature are the user's; the harness and the fixes are the difference.

## Verification commands

```bash
python run_audit.py                       # 11-suite health audit (~88s)
python -X utf8 tests/test_mesh_tools_contract.py   # clicks every Mesh Tools control
python -X utf8 tests/test_pymeshlab_calls.py       # every filter/param/enum/method name vs the installed build
python -X utf8 tests/test_texture_bake.py          # bakes 3 maps and reads the pixels back
python -X utf8 tests/test_renderfox.py    # LOD/QEM/format/queue
python -X utf8 tests/test_mock_dcc.py     # every engine command line against a stand-in renderer
python -X utf8 tests/test_job_manager.py  # the real queue thread against those stand-ins
python -X utf8 tests/test_postprocessor_paths.py   # organize/archive/cleanup stay inside the job folder
QT_QPA_PLATFORM=offscreen python -X utf8 tests/test_all_tabs_headless.py
```

`tests/_pymeshlab_probe.py` is the single place that asks the installed library a question, and it does it in a **child process**: probing filters with deliberately bad enum values and then letting the MeshSets go corrupts the parent heap (reproduced as exit 139 in a later, unrelated `load_new_mesh`). It answers one JSON spec and exits via `os._exit(0)` before its destructors can race anything. `test_pymeshlab_calls.py` imports no pymeshlab at all - keep it that way, and keep the two invariants it asserts (literal filter names, no `**kwargs` unpacking) or bad names get a hiding place again.

Understood limitation: `run_audit.py` reported 100% while ten Mesh Tools buttons threw `TypeError`, because the suites call the backend API with correct kwargs and `test_all_tabs_headless.py` wraps nearly every action in `if hasattr(...)` with no assertion and monkeypatches `QMessageBox`/`QFileDialog` to auto-accept. **A passing audit does not mean a working button.** `tests/test_mesh_tools_contract.py` is the guard added for that and now runs inside the audit.

## Phases

| # | Area | Status |
|---|---|---|
| 0 | Baseline push + this file | DONE |
| 1 | Mesh Tools UI-to-backend contract | DONE |
| 2 | Invalid pymeshlab 2025.7 filter names | DONE - 47 call sites, all literal, all read back from the installed build; texture baking now writes real images |
| 3 | Mock DCC harness | DONE - `tests/mock_dcc/` runs every engine's real command line against a real child process; 16 tests |
| 4 | Job manager: progress, pause, stop, retry, concurrency, valid CLI per engine, dead Render buttons | IN PROGRESS - 4a DONE (live progress streaming), 4b DONE (every configured engine reaches the queue), 4c-1 DONE (output path, frame names, post-processing folder), 4c-2 queue (priority, retry, concurrency), 4d dashboard wiring |
| 5 | FBX/DAE claims + requirements gaps | not started |
| 6 | Fabricated results presented as real | not started |
| 7 | 22s startup | not started |
| 8 | Dead module deletion + stale wiring + thumbnail keys | not started |

## Bug inventory (file:line, from the audit pass)

**Confirmed by live reproduction**

- `src/ui/dashboard_tab.py:572` and `:579` read `job_table.item(row, 0)` for the job id, but column 0 is a `QCheckBox` cellWidget (`:854`) and the id lives in column 1 (`:858`) → `AttributeError` on Pause/Resume.
- ~~`src/processing/render_engines.py:81-84` `get_progress()` returns a constant `0.0`; `job_manager.py:240` uses blocking `communicate()` so Blender's `Fra:` output is discarded → progress sits at 0% then jumps to 100.~~ **Engines fixed in Phase 4a** (verified streaming against the mock). `job_manager.py` still polls on a 1 s timer and now gets real values, but the queue loop itself is Phase 4c.
- `max_concurrent` appears **zero** times in `job_manager.py`; `pending_jobs[0]` (`:222`) plus one engine = strictly serial. Settings checkbox is write-only.
- `auto_retry` / `max_retries` exist only in `settings_tab.py:288-295`; no consumer in `job_manager.py` or `render_engines.py`.
- `src/ui/rendering_tab.py`: `render_btn` "Render Image" (`:624`) and `btn_render` "Render Frame" (`:764`) have **no `.clicked.connect`** — the Rendering tab cannot render. Toolbar view modes (`:720-751`) likewise unwired; only `action_export` is connected.
- `src/ui/dashboard_tab.py:95` format dropdown offers `jpg`; `render_engines.py:199` sends `--render-format JPG` — Blender requires `JPEG`.
- `src/core/library_manager.py:978` thumbnail keyed on basename only in one shared dir → different models named `char.fbx` in different folders serve each other's picture; no mtime in key → stale thumbs after edits.
- `src/ui/main_window.py:244`/`:249`/`:254` View menu → `switch_to_tab(0/1/2)`, but tab order (`:106-120`) is 0=Library, 1=Batch Render, 2=Models. All three entries land on the wrong tab.
- Measured startup: 22.2 s to construct MainWindow; `library_tab` import alone 14.2 s (eager torch/transformers/open3d/CLIP).
- pymeshlab 2025.7: `compute_ambient_occlusion_per_vertex` (`texture_baker.py:135`) does not exist and `colorize_by_vertex_quality` (`texture_baker.py:143`) fails.
- trimesh 4.7.4: `.fbx` raises `ValueError: 'fbx' exporter not available`, `.dae` needs absent pycollada — yet `format_converter.py:108-111` advertises OBJ↔FBX and glTF→FBX conversions.

**Confirmed by code reading**

- ~~`job_manager.py:340` uses `sys.platform` but `sys` is never imported (harmless on Windows, `NameError` on mac/linux).~~ **Fixed in Phase 4b** - the read is now `system_name(os.name, sys.platform)` with `sys` imported, and the branch it lived in was rewritten.
- ~~`render_engines.py:229` `os.path.dirname(job.output_path)` while the dialog returns a directory (`dashboard_tab.py:235`).~~ **Worse than the inventory said, and only half fixed:** `browse_output` uses `getExistingDirectory`, so `job.output_path` from both `AddJobDialog` (`:546`) and imported job JSON (`:781`) is a **directory**, and `dirname()` of a directory is its parent - frames land one level up, and Blender is handed `--render-output D:\Renders`, which writes `D:\Renders0001.png`. Phase 4a removed the `makedirs('')` crash and made every path absolute; `output_spec` + `frame_stem` + Blender's `#` run are Phase 4c-1.
- **Found while fixing that, also fixed in Phase 4c-1:** `postprocessor.py` used `os.path.dirname(job.output_path) or job.output_path` for archiving and temp cleanup, i.e. the folder *above* the render folder - `archive_old_files` walks its argument and **deletes** every file older than the threshold, so a UI job whose output was `D:\Renders` archived the old files of `D:\`. Two more in the same shape: the system-temp sweep matched the `renderfox_` prefix with no age check, so it deleted the scratch folder of a render running in another window, and `job.name` (free text) went untreated into a folder *and* a file name, where on Windows `Elsewhere: 1` becomes an alternate data stream on a file named `Elsewhere` and the copy "succeeds" invisibly.
- `render_engines.py:413-442` Unreal writes a 3-key `MoviePipelineConfig.json` its own comment calls "Simplified"; UE does not consume it. `:513-525` C4D flags `-nogui -render -frame a..b` do not exist in C4D's CLI.
- `dashboard_tab.py:909` `update_progress` never connected → the visible queue progress bar never moves. `:669` Set Priority mutates `job.priority` the queue never sorts on.
- `automation_tab.py:1350-1366` `simulate_file_event` logs `random.choice([...])` fake file events as live watching. `automation_engine.py:172-175` `generate_lod` returns "Generated N LODs" without calling `LODGenerator`.
- `pipeline_engine.py:843-845` render node logs "Rendering not fully implemented, skipping" and returns `True`; `:997` transform node "is not yet implemented. Passing data through."
- `animation_tab.py:316-332` fake sine waveform as audio track; `:907` seeds dummy tracks. No skeletal playback at all — `:1143-1183` applies only whole-model translate/rotate/uniform-scale.
- `performance_analyzer.py:127-135` GPU 0.0 without GPUtil; `:541+` "GPU benchmark" is Open3D CPU normal estimation on random points; `performance_tab.py:945` "GPU status (placeholder)".
- `main.py:142-143` starts a second `AutomationEngine` that is never given rules — dead.
- `point_cloud_processor.py:1120-1131` DBSCAN handler loads the cloud, does nothing, emits an excuse — while a working `dbscan_clustering:380` sits uncalled.
- `mesh_tools_tab.py:1876` and `mesh_processor.py:117` label `is_winding_consistent` as "Manifold" — not a manifold test.
- `lod_generator.py:233-234` `_cluster_simplify` delegates to quadric unless `use_vertex_clustering=True` (default False).
- `verify_software` written/read only inside `settings_tab.py`; never consulted by the queue.
- `painting_tab.py:299-304` `update_brush_settings` is a no-op "(to be implemented)".
- Missing from `requirements.txt` but imported: `cv2` (`postprocessor.py:15`, top level), `sklearn` (`model_extractor.py:10`, top level), `psutil`, `schedule`, `GPUtil`, `pyqtgraph`, `pyassimp`, `pycollada`, PyOpenGL. Declared but unused: `scipy`, `networkx`, `matplotlib`, `tensorflow`, `accelerate`, `safetensors`.
- `node_graph.py:229-232` material graph parser reads three Principled sockets, ignores the rest.

**Dead files (10, 6,081 raw / 4,624 code)** — `src/ui/model_tab_open3d.py` (1871), `src/ui/model_viewer_open3d.py` (1065), `src/utils/system_utils.py` (1059), `src/ui/library_grid.py` (821, orphans `src/core/thumbnail_generator.py` 488), `src/utils/file_utils.py` (367), `src/ui/weight_painting_tab.py` (264), plus 6-line shims `src/features/mesh_processor.py`, `src/features/point_cloud_processor.py`. `src/ui/feedback_dialog.py` (134) is imported but its only entry point `main_window.py:553 open_feedback` is connected to nothing.

## Fix log

_Format: Phase — file — what changed — how it was proven._

### Phase 1 — Mesh Tools UI-to-backend contract

**Canonical vocabulary (backend owns it, callers were changed, no aliases added):**

- `MeshProcessor.repair(mesh, out, operation=...)` → `auto`, `fill_holes` (+`max_hole_size`), `remove_duplicates` (+`threshold`), `remove_degenerate`, `remove_unreferenced`, `fix_normals`, `invert_normals`, `repair_non_manifold_edges`, `repair_non_manifold_vertices`, `make_manifold`
- `MeshProcessor.simplify(mesh, out, method=...)` → `faces` (+`target_faces`, `preserve_*`, `quality_threshold`), `ratio`, `clustering` (+`threshold`), `planar` (+`target_faces`, `angle`)
- `MeshProcessor.smooth(mesh, out, method=...)` → `laplacian` (+`iterations`, `boundary`), `taubin` (+`lambda_param`, `mu_param`, `iterations`), `depth` (+`iterations`, `delta`)
- `MeshProcessor.remesh(mesh, out, method=...)` → `uniform` (+`edge_length`, `iterations`, `adaptive`), `quad`, `voronoi` (+`threshold`), `subdivision` (+`sub_method`, `levels`)
- New `MeshProcessor.export(mesh, out, include_normals, include_textures, include_colors)` and `MeshMeasure` (measurements / components / curvature / face_quality / boundary_loops).

Existing callers that must keep working were re-checked, not assumed: `tests/e2e_backend_test.py` (`operation='auto'`, `method='faces'`), `tests/test_e2e_workflow.py` (`operation='scale'`), `verify_all_fixes.py` (`operation='translate'`), `quality_analyzer_ui.py` (already `operation=`).

**`src/processing/mesh_processor.py`**

- Every pymeshlab filter name and parameter in this file now comes from `tools/pymeshlab_filter_params.txt`, generated from the installed 2025.7 build. The two names this build does not have (`compute_vertex_quality_measures`, `generate_texture_bake_to_per_vertex_color`) are not referenced.
- `simplify_quadric` rewritten pymeshlab-first (`meshing_decimation_quadric_edge_collapse`), trimesh fallback corrected to `face_count=<absolute target>` (it was receiving a fraction, which measured non-monotonic), plus `preserve_*`, `planarquadric`/`planarweight` and `qualitythr` forwarding.
- `cluster_simplify` → `meshing_decimation_clustering(threshold=PercentageValue)`; `planar_simplify` + `_angle_to_planar_weight` maps a UI angle onto the filter's coplanarity penalty.
- `MeshRepairer`: `fill_holes(max_hole_size)` clamped 3..1000 → `maxholesize` and reports faces added; `remove_duplicate_vertices(threshold)` picks `meshing_merge_close_vertices` when a tolerance is given (plain duplicate removal only welds exactly-equal vertices, so the UI tolerance spin was inert); `remove_degenerate_faces` = null + folded + duplicate faces; added `remove_unreferenced_vertices`, `repair_non_manifold_edges`, `repair_non_manifold_vertices`, `make_manifold`, `invert_normals`.
- `auto_repair` now stays inside one `MeshSet`. It previously round-tripped PyMeshLab → trimesh → PyMeshLab, which silently discarded UVs, vertex colours and normals between passes.
- `MeshRemesher`: `uniform_remesh` fixed (used `pymeshlab.AbsoluteValue`, which does not exist → `AttributeError`) to `targetlen=PercentageValue`; `quad_remesh` fixed (`meshing_tri_to_quad` does not exist) to poly-to-tri + smart triangle pairing; added `voronoi_filtering` and `subdivide(loop | catmull-clark | butterfly | midpoint)` with an explicit error naming supported methods.
- Four dispatch methods rewritten to the vocabulary above.

**`src/ui/mesh_tools_tab.py`**

- 19 handler call sites moved onto the canonical names (`method='close_holes'` → `operation='fill_holes'`, `steps=` → `iterations=`, `target_len=` → `edge_length=`, `method='quadric'` → `method='faces'`, `threshold=` → `delta=` for depth, `samples=` → `threshold=` for Voronoi, `remove_non_manifold_*` → `repair_non_manifold_*`, etc.).
- **Deleted 277 lines (239 non-blank, 8 method definitions)** that were the second, older generation of the same class: `close_holes`, `remove_duplicate_vertices`, `fix_face_normals`, `center_mesh` were shadowed by the newer async versions in the same class (Python name rebinding — the older bodies were unreachable), and `apply_quadric_simplification`, `apply_laplacian_smoothing`, `apply_taubin_smoothing`, `apply_transformation` were connected to no button. Every one is superseded by a live equivalent; nothing was reachable code.
- 10 dead Analysis buttons wired. 6 of them had no implementation at all (histogram, volume, area, curvature, geometric info, watertight, components, holes) and now call `MeshMeasure`; `compute_mesh_quality` and `check_manifold` existed but were never connected.
- Measurements run on the worker pool through `run_measurement`, so the UI does not freeze on a hero mesh; results land in the Detailed Analysis pane with the honest caveats (volume states it is unreliable when the mesh is not watertight).
- Orphaned controls made live: "Use Target Percentage" checkbox gates face-count vs percentage (and disables the control it is not using), "Quality Threshold" → `qualitythr`, Planar group gained a real Target Faces spin, Voronoi's "Sample Count" became the 0–2000 planarity threshold the filter actually takes, depth "Delta Threshold" became a 1–100 % strength.
- `save_mesh` no longer `shutil.copy2`s the original over the destination (that threw away all edits and wrote OBJ bytes into a `.stl` name); it calls `MeshProcessor.export`, as do the four Export buttons. Export option checkboxes now really strip UVs/materials/vertex colours, and the normals toggle is honoured for OBJ — the only one of the four formats with somewhere to put them.
- `load_mesh_file(..., notify=)` added: internal reloads after an operation no longer pop a "Mesh loaded successfully!" dialog on top of the operation's own result.
- Undo implemented for real: `execute_async` records the input path and operation label, `on_operation_completed` pushes an undo step and a history row, Undo reloads the pre-operation file, Clear History empties both.
- `take_screenshot` fixed (`QPixmap.isEmpty()` does not exist → `isNull()`); it saves the preview image actually on screen.
- `check_manifold` had an unreachable `if len(issues) == 0` inside `if issues:`; the no-issues case now also writes its report.

**`tests/test_mesh_tools_contract.py` (new, registered in `run_audit.py`)**

Clicks every control through the real UI path and requires an artefact: 19 mutating operations must produce a non-empty written mesh and move `current_model_path` onto it; 8 measurements must produce a report; export must write OBJ/PLY/STL/OFF; the colours toggle must be observable in the written PLY and the normals toggle in the written OBJ; Undo must restore the previous file; history must record exactly one row per completed operation; percentage-driven simplify must actually reduce faces. Dialogs are recorded, not auto-accepted, so a warning dialog fails the test instead of hiding it.

**Proof**

- `python -X utf8 tests/test_mesh_tools_contract.py` → `Ran 11 tests ... OK` (13.5 s). Before this phase the same handlers threw `TypeError: MeshProcessor.repair() got an unexpected keyword argument 'method'`.
- `python run_audit.py` → `100% (6/6 suites passed in 97.55s)`, including the new contract suite.
- Live calibration that drove the numbers: open box → 1 hole of 3 vertices; closed two-box scene → 0 holes, 2 bodies, volume 2.0; equilateral vs sliver triangle → quality metric 1.0 vs 5e-05, which is why the histogram range is 0–1 and "good" is >= 0.5.

### Phase 2 — Invalid pymeshlab 2025.7 filter and API names

**The checker first, then the fixes.** `tests/test_pymeshlab_calls.py` (315 raw / 270 code lines, new) parses `src/` with `ast` and checks every literal filter name, every keyword, every string enum value and every method called on a `MeshSet`/`Mesh` against the installed build through `tests/_pymeshlab_probe.py` (91 / 69, new). It resolves module-level constants, so `colormap=AO_COLORMAP` is checked as `'Viridis'` rather than waved through as computed. Mutation-proven, one defect at a time, each caught:

| injected defect | result |
|---|---|
| `meshing_remove_null_faces` → `..._facez` | CAUGHT (1 failure) |
| `maxholesize=` → `maxholezize=` | CAUGHT (1 failure) |
| `AO_COLORMAP = 'Inferno'` (wrong enum in a constant) | CAUGHT (1 failure) |
| `ms.mesh_number()` → `ms.number_of_meshes()` | CAUGHT (2 failures) |
| `apply_filter(FN)` (computed name) | CAUGHT (1 failure) |

47 `apply_filter` sites in `src/`, all literal, all present in this build, all parameters and enum values verified.

**`src/processing/mesh_processor.py` (+32 / -19)** — three dynamic call sites that the checker could not see were rewritten so each `apply_filter` carries a literal name: `fill_holes` (was building a `params` dict and unpacking it) became two explicit calls; `auto_repair`'s loop over `(label, filter)` pairs became seven named calls behind a local `log_removal` helper; `subdivide`'s `filters` alias dict now dispatches to four literal branches. Deleted lines are the dict-building and loop bodies only - every filter it used to reach by variable is still reached, now by name, and `test_pymeshlab_calls.py` proves each one exists. `# Written as two literal calls so the filter schema test can read both.` records why the shape looks redundant.

**`src/processing/texture_baker.py` (+163 / -95)** — the bake had never written a single file. Measured against the library:

- `transfer_attributes_to_texture_per_vertex` raises `Mesh has no associated texture to overwrite` unless a texture is attached to the target first. Nothing attached one. `set_texture_per_mesh` now runs before every transfer.
- `textname` is an in-memory texture name, **not** an output path; the old code passed the destination PNG as `textname` and expected a file. The image only reaches disk through `Mesh.texture(name).save(path)`.
- A texture loaded from a file is keyed by its **basename**; the built-in dummy is always keyed `dummy_texture` and its `textname` argument is ignored. `_transfer` therefore reads the key back from `Mesh.textures()` instead of assuming it.
- `use_dummy_texture=True` writes `checkerboard.png` into the **process working directory** on the first bake of every run - into whatever folder the app was launched from. `_transfer` supplies its own blank raster next to the output file and deletes it, and `test_10` fails if anything is left outside the output directory. Proven in isolation: a variant using the dummy texture with the key lookup corrected passes every content test and is caught by `test_10` alone.
- `attributeenum='Vertex Quality'` writes an all-black image whatever the scalar range, so AO could never have worked. The deleted AO block used `compute_ambient_occlusion_per_vertex` and `colorize_by_vertex_quality`, neither of which exists in 2025.7. `_bake_ao` now runs `compute_scalar_ambient_occlusion` → normalise → `compute_color_from_scalar_per_vertex(colormap='Viridis')` → `apply_color_desaturation_per_vertex(method='Luminosity')` → a levels stretch of the measured band to 0-255, and transfers **Vertex Color**.
- Accounting for the rest of the 95 deleted lines: the `try/except` that swallowed UV-generation failure (now propagates, because a bake without UVs is not a bake); the single outer `except` that returned `{}` and discarded the maps already written (now per-map, so one failure costs one map); `from typing import Dict, Any, Optional, Tuple` trimmed to `Dict`; and the old `meshing_tri_to_quad`-era comments naming filters that do not exist. No reachable behaviour was removed - `_bake_one`/`_bake_ao`/`_transfer`/`_require_image` cover every case the old `bake()` attempted, plus the failure reporting it did not have.
- `bake()`'s public signature and its three signals are unchanged, so no caller needed editing. Partial success reports `success=False` with the maps it did write and a message naming each one that failed.

**`src/processing/format_converter.py` (+3 / -2)** — `ms.number_of_meshes()` → `ms.mesh_number()`. `number_of_meshes()` does not exist in this build (`AttributeError`) and `number_meshes()` is deprecated; the call sat in the second entry of the conversion chain, which only runs when trimesh fails, so it had never executed. Caught by the API-name test, not by reading.

**`tests/test_texture_bake.py` (200 raw / 168 code lines, new, 11 tests)** — proves the maps are real: exactly the requested size (128 and 64), diffuse core pixels within delta 45 of the source vertex colour, AO strictly greyscale with a byte span > 32 (a flat AO means the levels stretch did not run), normal map carrying detail (`std > 10`), a colourless high poly costing the diffuse map and nothing else, progress monotone to 100, nested output directories created, single-map selection honoured, nothing-selected reporting instead of lying, and nothing written outside the output directory.

**`run_audit.py` (+12)** — the two new suites are registered, so the audit is now 8 suites.

**Proof**

- `python -X utf8 tests/test_pymeshlab_calls.py` → `Ran 8 tests ... OK`, exit 0 (no 139).
- `python -X utf8 tests/test_texture_bake.py` → `Ran 11 tests ... OK`.
- `python run_audit.py` → `100% (8/8 suites passed in 82.15s)`.

### Phase 3 — Mock DCC harness

Nothing in `render_engines.py` had ever been executed: `detect_available_software`, the four `get_render_command` builders, `is_available`, `render_job`, `stop`, `pause`, `resume` - all of it unrun, because no 3D package is installed. This phase adds the stand-in that makes the whole launch path testable, and the next phase is written against it.

**`tests/mock_dcc/mock_dcc.py` (333 lines, new)** - one script that emulates all four packages, chosen by its first argument. It is strict on purpose:

- `blender` demands `--background`, exactly one `.blend`, `--render-output`, `--render-format` and either `--render-anim` or `--render-frame`, and rejects any flag it does not know. Unknown or missing flags exit 20.
- `maya` demands `-batch -file <scene> -command "<mel>"` and parses the MEL for `workspace -fr "images"`, `imageFilePrefix`, `startFrame`/`endFrame`; a `-command` that never calls `render` is rejected.
- `cinema4d` demands `-nogui -render <file>` and a `-frame start..end` span it can actually parse.
- `unreal` takes the `.uproject`, requires `-MoviePipelineConfig=` pointing at a file that exists, and reads OutputDirectory / Resolution / StartFrame / EndFrame out of that JSON.
- Success prints the package's own progress syntax then exits 0; failure writes to **stderr** and exits 30 (render stopped), 31 (no output directory) or 32 (unusable frame range). It writes a real file per frame so progress can be observed from disk while the process runs.
- Scene knobs live in the project file, like a real scene: `seconds_per_frame`, `frame_count`, `output_dir`, `prefix`, `fail_after`, `hang`, `write_files`, `format`.

**`tests/mock_dcc/harness.py` (76 lines, new)** - installs `.cmd`/POSIX shims named `blender`, `maya`, `cinema4d`, `UnrealEditor`, each forwarding to `mock_dcc.py` with its package name, and writes a `config.json` of absolute paths. The app reads `config.json` from the working directory as its own "user configured the path" mechanism, so detection and `JobManager._get_executable_path` are exercised through the production code path - there is no test-only branch in `src/` and nothing is monkeypatched.

**`tests/test_mock_dcc.py` (286 lines, new, 16 tests)** - `TestMockPackageBehaviour` checks the stand-in itself: version banners satisfy each engine's probe, `BlenderEngine.get_version()` parses `4.3.0`, each package's progress syntax appears, failures land on stderr and reach `job.error_message`, and six malformed command lines are refused with exit 20 (so the suite cannot pass because the mock is lenient). `TestEngineLaunchPath` drives the real engine classes: all four render their own command end to end, Blender's frame range reaches the command line and produces frames 7-9, a single-frame job produces one frame, Maya's MEL carries resolution/format/frames, Unreal's config file exists with the promised OutputDirectory, the factory maps each `SoftwareType` to the right class, a configured path is discovered, `stop()` terminates a running 40-frame render, and `pause()` freezes frame production (measured: the frame count is unchanged across 0.8 s) while `resume()` finishes the job. `tearDown` stops and resumes every engine the test created, so a failure between pause and resume cannot leave a suspended process on the machine.

**`src/processing/render_engines.py` (+5 / -1)** - the harness found a live bug on its first run: `UnrealEngine` passed no frame range anywhere, so every Unreal animation job - 1 frame or 1000 - rendered exactly one frame. `_create_movie_pipeline_config` now writes `StartFrame`/`EndFrame` from `job.frame_range` into the JSON the app already owns, and the mock refuses a config whose range is unusable (exit 32). Nothing was deleted.

**Proof that the harness bites** - six command-line defects injected one at a time, each caught, then the file restored byte-identical:

| injected defect | failing tests |
|---|---|
| drop `--background` from the Blender command | 7 |
| drop `--render-format` | 7 |
| `--render-output` → `--output` | 7 |
| Maya MEL no longer sets the image workspace | 2 |
| Unreal config loses its frame range | 3 |
| drop `-nogui` from the Cinema 4D command | 2 |

**Measured facts Phase 4 has to work with**

- `test_10_nothing_about_the_render_is_readable_while_it_runs` records the current ceiling deliberately: `get_progress()` returns a constant `0.0`, nothing calls it, and `render_job` uses `communicate()`, so stdout is only available after the render ends. Phase 4 replaces that test with one requiring the `Fra:` lines above to drive the bar - it must not be kept.
- ~~`detect_available_software()` returns only `blender` even when `config.json` names all four correctly (`_get_user_configured_path('maya' / 'cinema4d' / 'unreal')` all return the path, but only `_get_blender_paths` asks for it). `JobManager._process_queue` gates on that dict, so a configured Maya/C4D/Unreal job fails with "No render engine available for maya" before the command is ever built. This is Phase 4's first fix, not a harness limitation.~~ **Fixed in Phase 4b** - all four getters now ask, and `tests/test_job_manager.py` runs a configured Maya job through the real queue to COMPLETED.
- `pause()` and `resume()` do nothing without psutil - they set no state and report no error, so the Pause button would lie. psutil 6.0.0 is installed here but is **not** in `requirements.txt` (Phase 5).

### Phase 4a - render progress streamed while the renderer runs

The queue could not show progress because nothing read the renderer while it was alive: `get_progress()` returned a constant `0.0`, no caller invoked it, and all four `render_job` bodies were the same ~33 lines of `Popen` + `communicate()`, which by design hands you stdout only after the process has exited. One shared `execute()` in the base class replaces all four.

**`src/processing/render_engines.py` (+192 / -143)**

- Base class gained `_progress` state, `get_progress()` (real value now), `parse_progress()` (per-engine hook), `_percent()`, `_drain()`, `_observe()`, `_output_directory()`, `_files_in()`, `execute()`.
- `execute()` runs one reader thread per pipe. `_drain`'s comment records why: a renderer chatty on both streams fills one 4 KB buffer and blocks forever writing the other, which is exactly what `stdout.read()` then `stderr.read()` would do.
- Each engine keeps only its own frame-line grammar: Blender `Fra:7/9 Rendered …`, Maya `// Rendering frame 2 of 3 //`, Cinema 4D `Frame 2 rendered (2/3)`, Unreal `Frame 2 ( 2/3 )` **before** its `[ 100.0%]` bracket, because that bracket is the completion of the current frame, not of the job - taking the percent first makes a 3-frame job report 100% on frame 1.
- `render_job` in all four classes is now `return self.execute(self.get_render_command(job), job)`. The 143 deleted lines are those four duplicated bodies (~33 each), the constant `get_progress()` it replaces, the three imports none of them used (`time`, `dataclasses.dataclass`, `enum.Enum` - all already dead before this change), the function-local `import re` in `Cinema4DEngine.get_version`, and the raw `os.path.dirname(...)` expressions that `_output_directory`/`_mel_string` replaced. No behaviour was dropped: each body's `should_stop` check, return-code check and stderr capture are all in `execute()`, plus the two verdicts they did not have.
- Verdict rules, in order: user stopped → failed; non-zero exit → failed with the renderer's own stderr; **exit 0 with neither a frame line nor a new file** → failed ("exited cleanly without reporting a frame or writing anything to …"); exit 0 with new files but no recognised frame line → **success**, and progress closes at 100.
- That fourth rule is the safety net for the constraint this machine imposes: the parsers are written against syntax the mock records, and a real build of any of these packages could word its lines differently. Size + `st_mtime_ns` per file is evidence that does not depend on matching a string, so a differently-worded renderer costs a still bar, not a false failure. A re-render over the same filenames still shows up, because the mtimes move.
- `_output_directory` (`abspath(dirname(output_path))`) removes the `os.makedirs('')` crash the inventory noted at `render_engines.py:229` for a bare output filename, and hands every engine an **absolute** directory. A relative path is resolved against the *renderer's* cwd, which this app does not control, so Blender's `--render-output` is absolutized too and `test_15` renders a bare `blender_hero.png` through all four packages. *(Kept as the reason the directory is absolute; the method itself became `output_spec` in Phase 4c-1, which is also what fixed its `dirname` reading.)*

**A MEL quoting bug the bare-name test exposed** - `tests/mock_dcc/mock_dcc.py` read Maya's settings with `workspace -fr "images" "(.*)";`, and `.*` is greedy: the captured "directory" was the path plus everything up to the *last* quoted value in the command. That produced `Error: output directory does not exist: C:\Users\AYUSHM~1\..."; setAttr -type "string" defaultRenderGlobals.imageFilePrefix "maya_hero`. Two sides fixed:

- the mock now reads one quoted value at a time (`MEL_VALUE` + `mel_string()`, unescaping `\X` → `X`) and refuses an absent, unquoted or unterminated one with exit 20 - `test_07` drives it with literal MEL, including `D:/say\"hi\"`.
- the app now writes one: `MayaEngine._mel_string()` turns `\` into `/` (valid in every Windows API path, needs no escaping in a MEL literal) and `"` into `\"`.
- Unverifiable here: the app-side `\"` branch, because Windows forbids `"` in a path. The reader half is tested; the writer half is one `str.replace` and is exercised only through the backslash branch. Stated rather than implied.
- Symmetric strictness added to the mock for Unreal's `OutputDirectory` (empty *and* relative are both refused now), which is what caught the original `dirname` bug in a runnable way.

**`tests/mock_dcc/mock_dcc.py` (+63 / -9)** - two new scene knobs. `silent` prints no frame lines at all (simulates a build whose progress wording differs, so the fallback evidence is tested and not just the parsers); `noise` floods both pipes during every frame (the shape a single buffered read cannot survive). `log_error()` writes flushed stderr. A bare output name now falls back to the process working directory, which is what `dirname` of one really means.

**`tests/test_mock_dcc.py` (22 tests, was 16)** - `test_10_nothing_about_the_render_is_readable_while_it_runs` deleted, as its own docstring required; it existed only to record the ceiling. In its place: `test_10` asserts each package's four frame lines arrive at the callback as `[25, 50, 75, 100]`; `test_11` polls `get_progress()` on an 8-frame render and requires a non-zero value **while the worker thread is still alive and the renderer pid still exists** - progress read after exit would pass a weaker test; `test_12` a silent renderer that writes nothing is a failure and its message says so; `test_13` a silent renderer that writes frames is a success; `test_14` 60 lines of output on both pipes for 3 Maya frames completes inside its join timeout; `test_15` a bare output filename renders into the working directory for all four packages; `test_16` rendering the same shot twice is not refused (same frame names, moved mtimes - so filename-only comparison is not the evidence); `test_07` in `TestMockPackageBehaviour` covers the MEL reader. `test_04` now reads Maya's workspace back instead of string-matching it.

**Proof** - control run passed, then nine defects injected one at a time, each caught, file restored byte-identically:

| injected defect | caught by |
|---|---|
| Blender regex `^Fra:` → `^Frame:` | test_10 |
| Maya `Rendering` → `Renderig` | test_10 |
| Cinema 4D `rendered` → `rendrd` | test_10 |
| Unreal percent tried before the tally | test_10 |
| `_observe` stores progress but never calls the callback | test_10 |
| `_observe` calls the callback but never stores progress | test_11 |
| `_drain` reads lines and drops them on the floor | test_10 |
| file evidence removed from the exit-0 verdict | test_13 |
| threaded drain → `stdout.read()` then `stderr.read()` | test_14 (deadlocks, join timeout fires) |

Then five more for the path rules, same method:

| injected defect | caught by |
|---|---|
| `_output_directory` loses `abspath` | test_15 (4 subtests) |
| `_mel_string` returns the path unconverted | test_01, test_04 |
| Blender `--render-output` loses `abspath` | test_15 |
| new-output check compares filenames only, ignoring mtimes | test_16 |
| "nothing reported and nothing written" verdict removed | test_12 |

- `python -X utf8 tests/test_mock_dcc.py` → `Ran 22 tests ... OK` (8.9 s).
- `python run_audit.py` → `100% (9/9 suites passed in 81.52s)`.
- Both scratch mutation runners were deleted after these runs (one-shot probes, not tooling).

### Phase 4b - every configured engine reaches the queue

Phase 4a made a render readable; it did not make one *startable*. Three separate lookups stood between the Settings tab and a Maya job, and all three only ever asked about Blender.

**`src/processing/render_engines.py` (+30 / -17)**

- New `_preferred_paths(config_key, commands)` (`:685`): the path `config.json` names for this exact package first, then one entry per `shutil.which(command)` hit, deduplicated. `_get_blender_paths`, `_get_maya_paths`, `_get_unreal_paths` and `_get_cinema4d_paths` each call it (`blender`/`maya`/`unreal`+`cinema4d` keys, commands `blender`, `maya`, `UnrealEditor`+`UnrealEditor-Cmd`, `cinema4d`+`Cinema 4D`). Previously only the Blender getter asked at all, so `detect_available_software()` could not return Maya even when its path was configured correctly.
- Maya's list is `["maya"]` only, because the lookup has to return a program that accepts the line `MayaEngine.get_render_command` builds - `maya -batch -file scene.ma -command "<mel>"`, which is what `mock_dcc.parse_maya` refuses anything else than. `Render.exe` is a different program with a different call shape, and putting it in this list would hand a job to something that starts and renders nothing. That contrast is a design reason, not something measured on this machine.
- `execute()` now hands `self._observe` to the **stderr** reader as well (`:190`). Which pipe a build reports frames on is not this app's choice, and a `Fra:` line on stderr is still a frame line; stdout-only parsing left the bar at 0 for such a build, where the exit-0 verdict then had to carry the whole job. `tests/mock_dcc/mock_dcc.py` grew a `stderr_progress` scene knob (frame lines to stderr) and `test_17` requires `[25, 50, 75, 100]` from it for all four packages.

**`src/core/job_manager.py` (+52 / -25)**

- `sys` was never imported here while `_get_executable_path` read `sys.platform` at old `:340`. The `NameError` was swallowed by that method's own `except Exception`, which returned `None`, so on mac and Linux the fallback path list was unreachable and the job died with "No executable found". `import sys` is now at `:6` and the branch is gone.
- That read became `system_name(os_name, platform_name)` (`:17`), taking the values as arguments so all three platforms are testable on the one machine this runs on (`test_04`).
- `_get_executable_path` (`:360`) is now two steps instead of three: the configured path via `_get_user_configured_path`, then the same `_get_*_paths(system)` list the detector walks (which carries the PATH lookups). The 12-line duplicated `config.json` reader and the trailing `shutil.which(software_type.value)` are deleted - the first re-read what the helper already reads, the second searched for the enum's own spelling (`unreal`, `cinema4d`) rather than the binary names the surviving list asks for (`UnrealEditor`, `UnrealEditor-Cmd`), so it could only ever hit for Blender and Maya, which `_preferred_paths` already covers. Both deletions are covered by `test_01`/`test_05`/`test_06`.
- The software cache (`:318`) is now keyed on the file it is a view of: `_config_stamp()` (`:347`) hashes `config.json`'s bytes, and a cached answer is reused only when that digest is unchanged *and* the entry is under 5 minutes old. Saving a Maya path in Settings therefore reaches the next job instead of waiting out the window on a stale answer. A digest rather than `st_mtime`: the file is a few hundred bytes, and a one-second mtime is exactly the resolution at which "Save" and "Start Queue" happen.

**`tests/mock_dcc/harness.py` (+9 / -2)** - the shims moved from `<root>` to `<root>/bin`. This was a harness bug hiding an app truth: `shutil.which` searches the current working directory on Windows, so with the shims sitting next to `config.json` the sandbox could not express "this package is not installed anywhere" - `test_02` and `test_07` failed for that reason before the app changed. `path_key()` in the new suite is the second half of the same discovery: `shutil.which` rebuilds the name from `PATHEXT` and returns `maya.CMD` for a file written `maya.cmd`, so paths from PATH have to be compared the way the OS compares them.

**`tests/test_job_manager.py` (new, 308 lines, 12 tests)** - the queue itself, driven through the real `JobManager` thread with real child processes and nothing monkeypatched. `TestSoftwareDiscovery`: `test_01` all four configured packages available *and* resolving to the configured executable; `test_02` a package named in no config is not available; `test_03` the cache is reused for an unchanged `config.json` and rebuilt when it changes; `test_04` platform keys; `test_05` an empty `config.json` with the shims on PATH still finds all four; `test_06` a job found only through PATH renders to COMPLETED. `TestQueueExecution`: `test_05` the flagship case - a configured **Maya** job, which before this phase could not even reach a command line - completes with 3 frames and progress 100; `test_06` a `job_updated` snapshot carrying `RENDERING` and `0 < progress < 100`, i.e. the bar moved *during* the render; `test_07` an unconfigured package fails with a message naming it; `test_08` stop returns the job to PENDING and cuts the render short; `test_09` queue stats; `test_10` a directory typed into Settings (`MayaEngine.is_available()` at `render_engines.py:375` can only ask whether the path exists - real Maya has no version flag to probe, and `_get_user_configured_path` accepts any existing path) lands the job on FAILED naming Maya, and the queue still renders the next job.

- `test_10` was written expecting the second half to pass on the first try. It did not, and the reason was my test's own fault: `write_config({'maya': …})` replaces the whole software map, so Blender stopped being configured and the follow-up job failed honestly. Corrected to override one key. The app never disagreed with the documented behaviour, which is worth stating because the alternative reading - "the queue poisoned itself" - was the hypothesis being tested.
- `job_manager.py:392` `_update_progress` (the 1 s timer that re-reads `get_progress()`) has no test of its own: the engine callback already emits, so nothing observable changes when the timer is deleted. It is kept as the fallback for an engine that updates `_progress` without calling back, and recorded here as covered-by-design rather than covered-by-a-test.
- The versioned-install-folder scans inside `_get_*_paths` (`C:\Program Files\Blender Foundation\…` and friends) are not reachable from a temp directory, so no suite here proves they work; the two routes that are proven are the configured path and PATH.

**Proof** - control run green, then ten defects injected one at a time, each caught by a named test, each file restored byte-identically (sha256 compared), scratch runner `_probe_4b.py` deleted:

| injected defect | caught by |
|---|---|
| `config.json` consulted for Blender only | test_01 (job manager), test_09 (mock) |
| Maya never looked up on PATH | test_05, test_06 |
| Cinema 4D config key misspelled `"cinema 4d"` | test_01 |
| progress read from stdout only | test_17 (mock) |
| `except OSError` around `Popen` widened to `ValueError` | test_10 |
| `system_name` never returns darwin | test_04 |
| Unreal dropped from the executable map | test_01, test_05 |
| `_config_stamp` returns a constant | test_03 |
| cache reuse stops comparing the config digest | test_03 |
| queue failure message stops naming the package | test_07 |

- `python -X utf8 tests/test_job_manager.py` → `Ran 12 tests ... OK` (15.3 s); `tests/test_mock_dcc.py` → `Ran 24 tests ... OK` (9.8 s).
- `run_audit.py` grew a tenth suite (`job_queue`, "Render Queue & Software Discovery") → `100% (10/10 suites passed in 83.33s)`.
- `config/batch_templates.json`, `tests/test_data/repaired.obj` and `tests/test_data/simplified.obj` were `git restore`d again after the audit run (see Known-deferred).

### Phase 4c-1 - one job's output means one thing

`job.output_path` meant two different things depending on who made the job, and every consumer picked a reading by guessing. `browse_output` in the dialog uses `getExistingDirectory`, so UI jobs and imported job JSON carry a **folder**; the scripting API carries a **file name** (`output_path="render.png"`). `dirname()` of a folder is the folder above it, and that single mismatch was three separate bugs: frames landing outside the chosen folder, Blender writing `D:\Renders0001.png`, and post-processing archiving/deleting the chosen folder's *parent*.

**`src/processing/render_engines.py`**

- `frame_stem(value)` (`:40`) and `output_spec(job) -> (absolute directory, frame-name stem)` (`:52`) are module-level functions, not `BaseRenderEngine` classmethods, because `postprocessor.py` has to answer the same question. A path that exists as a directory, or ends in a separator, is a directory and the stem is the job name; otherwise the stem is the file's own name without its extension, and the directory is `dirname` of it - made absolute by `os.path.abspath`, which is also what turns `''` ("right here") into the working directory instead of a crash.
- The stem is always the sanitized one: `_STEM_UNSAFE` (`[\\/:*?"<>|\r\n\t]+` → `_`), trailing spaces/dots stripped (Windows refuses them), empty → `render`. `job.name` is free text from the dialog.
- `BlenderEngine._output_template(job)` (`:350`) returns `<dir>/<stem>_` + `#` * `max(4, len(str(abs(last_frame))))`. Without a `#` run Blender appends the frame number to whatever string `-o` was handed and writes `<dir>0001.png`; the run also fixes the padding, so a 12,000-frame shot does not sort `frame_10.png` before `frame_2.png`.
- Maya's MEL gets the folder in `workspace -fr "images"` and the stem in `defaultRenderGlobals.imageFilePrefix` (`:472-473`); Unreal's generated config gets `OutputDirectory` from the same call (`:563`); `execute()` takes `output_spec(job)[0]` for its `makedirs` and for the before/after file evidence (`:193`).
- **Honest gap, unchanged:** Cinema 4D's command line carries no output path at all, so for C4D the app cannot choose the folder or the frame names. Its renders are proven by progress lines, not by file evidence.

**`src/processing/postprocessor.py` (+23 / -7)** - `organize_files`, `archive_old_files` and `_cleanup_temp_files` now all receive `output_spec(job)[0]` (`:584`, `:608`, `:846`), and `job.name` passes through `frame_stem` at both places it becomes a path (the subfolder at `:384`, the `{job_name}` token at `:413`). Two extra guards found while reading, not from the inventory: `archive_old_files` deletes what it archives, so the folder-above bug was data loss outside the render tree; and the system-temp sweep matched `renderfox_*` with no age check, so it removed the live scratch folder of another RenderFox window - it now skips anything newer than `STALE_TEMP_SECONDS` (`:29`, 24 h).

**`tests/mock_dcc/mock_dcc.py`** - directory precedence flipped to **command line first, scene second**, because the command line is the thing under test and the old order let a scene value mask whatever the app asked for; Cinema 4D, whose line carries nothing, still falls back to its own scene. The Blender parser now refuses a `--render-output` with no `#` run (exit 20), which is how `D:\Renders0001.png` became a test failure instead of a silent wrong folder, and frame names are built from the `#` run's position and length.

**`tests/test_mock_dcc.py` (24 → 27 tests)** - `test_18` a folder `output_path` keeps every frame inside that folder and puts nothing in the process cwd, for Blender/Maya/Unreal; `test_19` the Blender template carries a `#` run whose length follows the last frame (`(1, 3)` → 4, `(1, 12000)` → 5); `test_20` the job name `Hero/Shot: 1` reaches the frame files as `Hero_Shot_ 1` and does not create a folder. `test_05` was rewritten rather than deleted: it used a scene value to express a missing folder, which the new precedence ignores, and now it asks the real question - the raw command line refuses a folder that isn't there *and* does not create it, while `render_job` creates it first and renders, and a file in its way produces "Cannot create output directory" instead of a crash. `test_15` lost its file-name half for the same reason (a folder picker's value is a folder) and keeps the "no directory in it means right here" half.

**`tests/test_postprocessor_paths.py` (new, 6 tests, no renderer needed)** - organizing into a folder-shaped and a file-shaped `output_path`; archiving removing an old frame inside the job folder while a 40-day-old file in the parent survives; temp cleanup removing `<out>/temp` and not a neighbour's; the sweep keeping a fresh `renderfox_` folder and taking a day-old one; the free-text job name pinned in both folder and file position.

**`run_audit.py`** - eleventh suite `postprocessor_paths`.

**Proof** - control run green, then nine defects injected one at a time, each caught by a named test, both files restored byte-identically, scratch runner `_probe_4c.py` deleted:

| injected defect | caught by |
|---|---|
| organize base_dir is the raw `output_path` (a file path) | test_02 (postprocessor) |
| archive walks the folder above the output | test_04 (postprocessor) |
| temp cleanup targets the folder above | test_05 (postprocessor) |
| organised file name keeps the raw job name | test_03 (postprocessor) |
| organised subfolder keeps the raw job name | test_03 (postprocessor) |
| temp sweep deletes every `renderfox_` entry | test_06 (postprocessor) |
| `output_spec` treats a folder as a file name | test_18 (mock), test_15 |
| Blender template drops the `#` run | test_01, test_02, test_19 (mock) |
| frame stem is not sanitized | test_20 (mock) |

- `tests/test_mock_dcc.py` → `Ran 27 tests ... OK` (11.1 s); `tests/test_job_manager.py` → `Ran 12 tests ... OK` (15.3 s); `tests/test_postprocessor_paths.py` → `Ran 6 tests ... OK` (0.03 s); `run_audit.py` → `100% (11/11 suites passed in 88.33s)`.
- Two lessons from the pass itself. The first runner compared a *decoded string* digest to the *raw bytes* on restore, refused to write, and left `postprocessor.py` mutated one step longer than it should have been - repaired by hand and the runner now keeps the original bytes and verifies after writing. And "stayed inside the output folder" was not strong evidence: under the raw-`output_path` defect Windows happily created a **folder named `hero.png`** inside the render folder, so the tests now pin the folder list and the file prefix, not just the ancestor.

## Known-deferred

- `tools/` is gone. Its job - the pymeshlab name/parameter/enum truth - is now `tests/_pymeshlab_probe.py` + `tests/test_pymeshlab_calls.py`, which run inside the audit instead of being remembered by hand. Nothing references `tools/` any more.
- **One string enum is still invisible to the checker**: `_transfer(attribute, ...)` in `texture_baker.py` receives `attributeenum` as a parameter, so it parses as computed. It is covered at runtime instead - `test_02` proves `'Vertex Color'` rasterises colour, `test_04` proves `'Vertex Normal'` rasterises normals - and splitting it into two literal call sites was rejected because the only thing gained would be a second copy of the same eleven lines. Say so rather than let the green checker imply full coverage.
- `MeshAnalyzer.is_manifold` / `mesh_tools_tab.update_mesh_info` still report `is_winding_consistent` under the label "Manifold". Kept open because a correct test needs a real edge-manifold check, which belongs with the quality-scoring work, not silently patched here.
- Running the audit dirties the working tree: tests write into tracked files (`config/batch_templates.json` records a `created_at` timestamp; `tests/test_data/repaired.obj` and `simplified.obj` are regenerated outputs, not inputs - nothing reads them). They were restored with `git restore` before the Phase 2 commit, so every commit here is clean, but the suites need to write to a temp directory. Belongs with the dead-file/phase-8 hygiene pass, not a behaviour fix.
- `format_converter.py` calls `os.makedirs(os.path.dirname(output_file))` at lines 262, 290 and 313, which raises for a bare filename (`dirname` is `''`). Latent - every UI path passes a directory - and not reached by any test yet. Fix with the format-claims phase.
