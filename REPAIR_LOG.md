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
python run_audit.py                       # 5-suite health audit (~95s)
python -X utf8 tests/test_renderfox.py    # LOD/QEM/format/queue
QT_QPA_PLATFORM=offscreen python -X utf8 tests/test_all_tabs_headless.py
```

Understood limitation: `run_audit.py` reported 100% while ten Mesh Tools buttons threw `TypeError`, because the suites call the backend API with correct kwargs and `test_all_tabs_headless.py` wraps nearly every action in `if hasattr(...)` with no assertion and monkeypatches `QMessageBox`/`QFileDialog` to auto-accept. **A passing audit does not mean a working button.** Adding UI-contract tests is part of this repair.

## Phases

| # | Area | Status |
|---|---|---|
| 0 | Baseline push + this file | DONE |
| 1 | Mesh Tools UI-to-backend contract | not started |
| 2 | Invalid pymeshlab 2025.7 filter names | not started |
| 3 | Mock DCC harness | not started |
| 4 | Job manager: progress, pause, stop, retry, concurrency, valid CLI per engine, dead Render buttons | not started |
| 5 | FBX/DAE claims + requirements gaps | not started |
| 6 | Fabricated results presented as real | not started |
| 7 | 22s startup | not started |
| 8 | Dead module deletion + stale wiring + thumbnail keys | not started |

## Bug inventory (file:line, from the audit pass)

**Confirmed by live reproduction**

- `src/ui/mesh_tools_tab.py:1421` sends `repair(..., method='close_holes')`; `src/processing/mesh_processor.py:757` accepts `operation=`. Every one of ten repair handlers passes `method=` → `TypeError`. Also the value names do not match: backend accepts only `auto`, `fill_holes`, `remove_duplicates`, `remove_degenerate`, `fix_normals`.
- `src/ui/mesh_tools_tab.py:1437` sends `method='make_manifold'` — no such operation exists on either side.
- `src/ui/mesh_tools_tab.py:1389` sends `simplify(method='quadric')`, `:1454` `'clustering'`, `:1746` `'planar'`; `mesh_processor.py:734-744` accepts only `ratio`/`faces` → `Unknown method`.
- `mesh_processor.py:750` `smooth` and `:775` `remesh` read `iterations`/`edge_length`, UI sends `steps=`/`target_len=` → spinboxes silently ignored, hardcoded 5 / 0.1 used.
- `src/ui/mesh_tools_tab.py:1596` `save_mesh` is `shutil.copy2(original, dest)` — Export discards all edits.
- `src/ui/dashboard_tab.py:572` and `:579` read `job_table.item(row, 0)` for the job id, but column 0 is a `QCheckBox` cellWidget (`:854`) and the id lives in column 1 (`:858`) → `AttributeError` on Pause/Resume.
- `src/processing/render_engines.py:81-84` `get_progress()` returns a constant `0.0`; `job_manager.py:240` uses blocking `communicate()` so Blender's `Fra:` output is discarded → progress sits at 0% then jumps to 100.
- `max_concurrent` appears **zero** times in `job_manager.py`; `pending_jobs[0]` (`:222`) plus one engine = strictly serial. Settings checkbox is write-only.
- `auto_retry` / `max_retries` exist only in `settings_tab.py:288-295`; no consumer in `job_manager.py` or `render_engines.py`.
- `src/ui/rendering_tab.py`: `render_btn` "Render Image" (`:624`) and `btn_render` "Render Frame" (`:764`) have **no `.clicked.connect`** — the Rendering tab cannot render. Toolbar view modes (`:720-751`) likewise unwired; only `action_export` is connected.
- `src/ui/dashboard_tab.py:95` format dropdown offers `jpg`; `render_engines.py:199` sends `--render-format JPG` — Blender requires `JPEG`.
- `src/core/library_manager.py:978` thumbnail keyed on basename only in one shared dir → different models named `char.fbx` in different folders serve each other's picture; no mtime in key → stale thumbs after edits.
- `src/ui/main_window.py:244`/`:249`/`:254` View menu → `switch_to_tab(0/1/2)`, but tab order (`:106-120`) is 0=Library, 1=Batch Render, 2=Models. All three entries land on the wrong tab.
- Measured startup: 22.2 s to construct MainWindow; `library_tab` import alone 14.2 s (eager torch/transformers/open3d/CLIP).
- pymeshlab 2025.7: `meshing_tri_to_quad` (`mesh_processor.py:504`) does not exist; `compute_ambient_occlusion_per_vertex` (`texture_baker.py:135`) does not exist; `pymeshlab.AbsoluteValue` (`mesh_processor.py:480`) is not a class; `colorize_by_vertex_quality` (`texture_baker.py:143`) fails.
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
- `mesh_processor.py:225-226` passes a fraction positionally into trimesh `simplify_quadric_decimation(face_count=...)` → measured non-monotonic (0.5→640, 0.25→960 faces on identical input).
- `verify_software` written/read only inside `settings_tab.py`; never consulted by the queue.
- `painting_tab.py:299-304` `update_brush_settings` is a no-op "(to be implemented)".
- Missing from `requirements.txt` but imported: `cv2` (`postprocessor.py:15`, top level), `sklearn` (`model_extractor.py:10`, top level), `psutil`, `schedule`, `GPUtil`, `pyqtgraph`, `pyassimp`, `pycollada`, PyOpenGL. Declared but unused: `scipy`, `networkx`, `matplotlib`, `tensorflow`, `accelerate`, `safetensors`.
- `node_graph.py:229-232` material graph parser reads three Principled sockets, ignores the rest.

**Dead files (10, 6,081 raw / 4,624 code)** — `src/ui/model_tab_open3d.py` (1871), `src/ui/model_viewer_open3d.py` (1065), `src/utils/system_utils.py` (1059), `src/ui/library_grid.py` (821, orphans `src/core/thumbnail_generator.py` 488), `src/utils/file_utils.py` (367), `src/ui/weight_painting_tab.py` (264), plus 6-line shims `src/features/mesh_processor.py`, `src/features/point_cloud_processor.py`. `src/ui/feedback_dialog.py` (134) is imported but its only entry point `main_window.py:553 open_feedback` is connected to nothing.

## Fix log

_Format: Phase — file — what changed — how it was proven._

_(empty — starts at Phase 1)_

## Known-deferred

Nothing deferred yet. Anything deliberately left broken gets moved here with a reason.
