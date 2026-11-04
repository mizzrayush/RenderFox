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

| Bucket | Files | Raw | Code |
|---|---|---|---|
| `src/` | 73 | 56,111 | 41,523 |
| entry + tooling scripts | 5 | 545 | 421 |
| `installer.nsi` + `RenderFox.spec` | 2 | 210 | 158 |
| `tests/` | 22 | 2,257 | 1,620 |
| dead code inside `src/` (to be deleted) | 10 | 6,081 | 4,624 |

Claimable: ~56k raw / ~42k code lines. After dead-code removal: ~50k / ~37k.

## Verification commands

```bash
python run_audit.py                       # 6-suite health audit (~98s)
python -X utf8 tests/test_mesh_tools_contract.py   # clicks every Mesh Tools control
python -X utf8 tests/test_renderfox.py    # LOD/QEM/format/queue
QT_QPA_PLATFORM=offscreen python -X utf8 tests/test_all_tabs_headless.py
python tools/check_mesh_filters.py        # regenerate the pymeshlab filter/parameter truth
```

`tools/` is deliberately **untracked** (the user asked to keep tooling out for now). `tools/pymeshlab_filter_params.txt` is generated, not hand-edited: a wrong filter or parameter name only surfaces as an exception at call time, and nothing here can be tested against a GPU or a DCC.

Understood limitation: `run_audit.py` reported 100% while ten Mesh Tools buttons threw `TypeError`, because the suites call the backend API with correct kwargs and `test_all_tabs_headless.py` wraps nearly every action in `if hasattr(...)` with no assertion and monkeypatches `QMessageBox`/`QFileDialog` to auto-accept. **A passing audit does not mean a working button.** `tests/test_mesh_tools_contract.py` is the guard added for that and now runs inside the audit.

## Phases

| # | Area | Status |
|---|---|---|
| 0 | Baseline push + this file | DONE |
| 1 | Mesh Tools UI-to-backend contract | DONE |
| 2 | Invalid pymeshlab 2025.7 filter names | `mesh_processor.py` done — every filter and parameter name was read back from the installed library; `texture_baker.py` AO/quality names still open |
| 3 | Mock DCC harness | not started |
| 4 | Job manager: progress, pause, stop, retry, concurrency, valid CLI per engine, dead Render buttons | not started |
| 5 | FBX/DAE claims + requirements gaps | not started |
| 6 | Fabricated results presented as real | not started |
| 7 | 22s startup | not started |
| 8 | Dead module deletion + stale wiring + thumbnail keys | not started |

## Bug inventory (file:line, from the audit pass)

**Confirmed by live reproduction**

- `src/ui/dashboard_tab.py:572` and `:579` read `job_table.item(row, 0)` for the job id, but column 0 is a `QCheckBox` cellWidget (`:854`) and the id lives in column 1 (`:858`) → `AttributeError` on Pause/Resume.
- `src/processing/render_engines.py:81-84` `get_progress()` returns a constant `0.0`; `job_manager.py:240` uses blocking `communicate()` so Blender's `Fra:` output is discarded → progress sits at 0% then jumps to 100.
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

- `job_manager.py:340` uses `sys.platform` but `sys` is never imported (harmless on Windows, `NameError` on mac/linux).
- `render_engines.py:229` `os.path.dirname(job.output_path)` while the dialog returns a directory (`dashboard_tab.py:235`).
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

## Known-deferred

- `tools/` stays untracked at the user's request; regenerate `tools/pymeshlab_filter_params.txt` with `python tools/check_mesh_filters.py` rather than editing it.
- `MeshAnalyzer.is_manifold` / `mesh_tools_tab.update_mesh_info` still report `is_winding_consistent` under the label "Manifold". Kept open because a correct test needs a real edge-manifold check, which belongs with the quality-scoring work, not silently patched here.
