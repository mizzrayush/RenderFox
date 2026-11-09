"""
RenderFox Master Solo-Developer Audit & Health Runner
One-click comprehensive test and health audit across all 15 tabs and backend processing engines.
Usage: python run_audit.py
"""

import os
import sys
import time
import subprocess
import json
from datetime import datetime

# Enforce UTF-8 encoding for Windows terminals
if sys.platform.startswith('win'):
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

SUITES = [
    {
        "id": "syntax_compilation",
        "name": "Syntax & Bytecode Compilation",
        "command": [sys.executable, "-m", "compileall", "-q", "src", "tests", "main.py"],
        "description": "Verifies that 100% of Python source files compile without syntax errors"
    },
    {
        "id": "baseline_stability",
        "name": "Core Backend & Regression Suite",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "verify_all_fixes.py")],
        "description": "Validates database integrity, translation matrices, process handles, engine bindings, and that a shut window leaves no file a DCC cannot re-export over",
        "timeout_seconds": 240
    },
    {
        "id": "lod_mesh_pipeline",
        "name": "3D LOD & QEM Decimation Pipeline",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_renderfox.py")],
        "description": "Validates Quadric Error decimation, clustering simplification, format conversions, and job queue"
    },
    {
        "id": "backend_e2e",
        "name": "Mesh Repair & Analysis E2E Workflow",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "e2e_backend_test.py")],
        "description": "Validates hole filling, duplicate vertex removal, topology scoring, and format conversion"
    },
    {
        "id": "mesh_tools_contract",
        "name": "Mesh Tools UI-to-Backend Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_mesh_tools_contract.py")],
        "description": "Clicks every Mesh Tools control and requires a written mesh, a report, an undo step or an export from it"
    },
    {
        "id": "pymeshlab_calls",
        "name": "PyMeshLab Filter & API Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_pymeshlab_calls.py")],
        "description": "Reads every filter name, parameter, enum value and object method out of src/ and checks it against the installed PyMeshLab"
    },
    {
        "id": "texture_bake",
        "name": "Texture Bake Output Verification",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_texture_bake.py")],
        "description": "Bakes normal, diffuse and AO maps and requires real greyscale/colour pixels at the requested resolution"
    },
    {
        "id": "mock_dcc_launch",
        "name": "Mock DCC Launch & Process Control",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_mock_dcc.py")],
        "description": "Runs every engine's real command line against a stand-in renderer process and checks versions, progress syntax, exit codes, pause and stop"
    },
    {
        "id": "job_queue",
        "name": "Render Queue & Software Discovery",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_job_manager.py")],
        "description": "Drives the real JobManager thread against the mock renderers: configured engines are discovered, live progress per job, priority order, retries, concurrency, pause/remove/stop leave no renderer running"
    },
    {
        "id": "dashboard_contract",
        "name": "Dashboard Queue Control Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_dashboard_contract.py")],
        "description": "Clicks every dashboard queue control and requires the queue to be asked, the bar to follow the render and the format list to match the engine"
    },
    {
        "id": "rendering_tab_contract",
        "name": "Rendering Viewport Control Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_rendering_tab_contract.py")],
        "description": "Clicks every Rendering tab toolbar action and Render Image button and requires the viewport to change or a frame of the requested resolution and format to be written"
    },
    {
        "id": "render_samples_contract",
        "name": "Render Samples Command Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_render_samples_contract.py")],
        "description": "Phase 15c-1: the sample count travels from the Dashboard's typable Samples box and the preset onto the RenderJob, and each engine emits its own flag for it - Blender's cycles.samples python-expr, Maya's Arnold AASamples MEL, Unreal's Movie Pipeline config - proven at the command line, never by a render. Cinema 4D, whose -render command has no sample parameter, is pinned to invent no flag, and a zero or negative count is made safe rather than emitted raw"
    },
    {
        "id": "video_export_contract",
        "name": "H.264 MP4 Export Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_video_export_contract.py")],
        "description": "Phase 15c-2: the Animation tab's MP4 export reads its completed file back for an ISO-BMFF ftyp and moov plus an avc1/avc3 H.264 track, instead of trusting a filename or a zero ffmpeg exit code; missing, empty, truncated, non-MP4, and non-H.264 output reaches the user as a refusal"
    },
    {
        "id": "texture_packer_contract",
        "name": "Texture Channel Packing Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_texture_packer_contract.py")],
        "description": "Writes ORM and mask PNGs from explicitly assigned image channels, reads the written RGBA pixels back, refuses mismatched source sizes, and proves the Texture Generator and shared automation registry call the same backend"
    },
    {
        "id": "texture_mipmaps_contract",
        "name": "Texture Mipmap Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_texture_mipmaps_contract.py")],
        "description": "Writes a portable PNG mip chain and manifest from a texture, reads every recorded level back, and refuses a missing source instead of claiming engine-ready KTX/Basis compression"
    },
    {
        "id": "geometry_compression_contract",
        "name": "Geometry Compression Capability Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_geometry_compression_contract.py")],
        "description": "Requires Meshopt compression to use gltfpack and verify EXT_meshopt_compression from the written asset; without that encoder it refuses by name rather than calling an ordinary GLB compressed"
    },
    {
        "id": "ecosystem_contract",
        "name": "Cross-Workspace Ecosystem Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_ecosystem_contract.py")],
        "description": "Protects shared asset selection and icon-only workspace accessibility so cross-pane sends cannot silently return to positional navigation or disconnected selection state"
    },
    {
        "id": "format_converter_contract",
        "name": "Format Conversion Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_format_converter_contract.py")],
        "description": "Converts every claimed format pair for real and reads the result back, opens the picker to check it only offers what the installed libraries can write, and checks the build recipe ships the FBX writer"
    },
    {
        "id": "preprocessing_contract",
        "name": "Pre-Processing Pane Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_preprocessing_contract.py")],
        "description": "Clicks every Pre-Processing control and requires the extraction to keep every face it was given, each method to name the split it actually ran, Preview to measure without writing, Apply to write an optimized file it can read back, and every Cancel to reach a live worker - with no worker startable outside the registry that keeps a running thread alive"
    },
    {
        "id": "automation_contract",
        "name": "Automation File-Watcher Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_automation_contract.py")],
        "description": "Adds a real folder, drops a real file in it and requires the tab's log to name it, checks the filter fields and Watch Events boxes reach the watcher, and makes each Auto Action prove its result on disk or say it failed"
    },
    {
        "id": "automation_tasks_contract",
        "name": "Automation Task Scheduler Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_automation_tasks_contract.py")],
        "description": "Schedules a real task, waits for the polling thread to fire it and requires the run, the saved record, the next-run time, the exit code of a real command and every scheduler button to be true rather than a printed claim"
    },
    {
        "id": "automation_workflows_contract",
        "name": "Automation Workflow Builder Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_automation_workflows_contract.py")],
        "description": "Runs a workflow end to end, requires the copy on disk, the retry count, the tolerated failure, the stop between steps and every builder button - Save, Load, Duplicate, Delete, Move, Test, Stop - to reach the engine or name why not"
    },
    {
        "id": "automation_batch_contract",
        "name": "Automation Batch Operations Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_automation_batch_contract.py")],
        "description": "Repeats one registry action over a real folder of real files, requires a file the action refused to be counted as failed instead of done, checks Preview prints the exact call each file will get, and makes Start, Pause, Stop, Preview and both Browse buttons reach the engine or name why they cannot"
    },
    {
        "id": "automation_monitor_contract",
        "name": "Automation Monitor Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_automation_monitor_contract.py")],
        "description": "Requires the Monitor pane to report only runs the engine says are happening - no invented activity lines, process rows, CPU figures or error counts - and makes Refresh, Kill, Details, Clear Log, Export Log and the close question reach the engine or name why they cannot"
    },
    {
        "id": "postprocessor_paths",
        "name": "Post-Processing Output Folder",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_postprocessor_paths.py")],
        "description": "Requires organizing, archiving and temp cleanup to stay inside the job's output folder and to survive a job name containing slashes or colons"
    },
    {
        "id": "point_clouds_contract",
        "name": "Point Clouds Pane Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_point_clouds_contract.py")],
        "description": "Clicks every Point Clouds control and requires each verb to write the file it names, count the points off that file rather than off memory, chain the next verb onto it, refuse an impossible parameter by repeating the number typed, keep the progress dialog's maximum equal to the files actually written, and make Cancel and a second click reach the run in flight - including the two defects only a live run found: a verdict slot that raised on QProgressDialog.wasClosed and a finished signal from an old thread silencing a newer one"
    },
    {
        "id": "preview_render_contract",
        "name": "Preview Raster Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_preview_render_contract.py")],
        "description": "Draws real frames with the app's own raster and requires the picture on disk to be the picture reported: every lamp knob monotone in the pixels, every camera knob visible, fit holding a 0.06-unit and an 8-unit model in one frame, the window floor and ceiling resampled and admitted in the note, supersample reporting the multiple that actually opened, transparency accounting for every pixel, and the four Open3D traps this machine punishes (engine head light on, fresh PinholeCameraIntrinsic, plain look-at extrinsic, window left open) pinned from the source as well as the frame. Also the suite the 52-defect mutation sweep runs against, including the four defects a live window kills the process over - a mesh painted with the point-cloud channel, an extrinsic that puts the eye behind the model, a fitted eye inside the geometry, a camera standing on the point it looks at - reached through the module's own helpers, and the two verdict rules a real frame never produces by accident: a file that re-reads as nothing but background, and a silhouette one pixel wide",
        "timeout_seconds": 180
    },
    {
        "id": "ai_tagger_contract",
        "name": "AI Asset Tagger Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_ai_tagger_contract.py")],
        "description": "Requires the picture CLIP judges to be a frame the app really drew: the tagger's preview comes back as the file the software raster wrote (the asked size, more than one colour in it, gone again from the temp folder, in seconds rather than minutes), a tagging run is counted to open no OpenGL window at all because a second GL window in one process never answers and the worker blocked inside it takes the pane's bar with it, a draw the raster refuses is reported as refused so the geometry answers alone and `ai_powered` stays false instead of claiming a judgement that never happened, and the syntax tree of the module is read to prove no second renderer is left in it a conditional away",
        "timeout_seconds": 180
    },
    {
        "id": "pipeline_contract",
        "name": "Pipeline Engine and Pane Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_pipeline_contract.py")],
        "description": "Runs the 26 node types on the real backends and requires every verdict on screen to be the engine's own: files that exist and measure back, the four source and three destination refusals named - a refused format quoting the value it was handed and listing the formats that node takes, so the sentence cannot be a bare no - extremes passed to the filter instead of clamped by the widget, a stop that says where it stopped, a pipeline file loaded without being rewritten, and a pane that builds a control for every knob, holds its worker, and never computes a number of its own",
        "timeout_seconds": 180
    },
    {
        "id": "hardware_report_contract",
        "name": "Hardware Report Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_hardware_report.py")],
        "description": "Asks this machine what it is and requires the answer to be the machine's own: the volume every storage figure and storage verdict describes is the one the app writes into (here C: at 90.8%, not the start-up drive's 25.8%) picked by one shared helper, the drive letter to disk number to disk record join says which of its three failures happened, an adapter is named with the check that named it and its current figures arrive together or as the reason they did not, the CPU figure is taken over a real window, one measurement per report so a row and its verdict cannot be two looks, a library is looked up in the package records instead of imported (7.6s to 0.06s, and pillow and scikit-learn stop being called missing), no machine reading happens on the thread that paints - the three Diagnostics checks hold their reading open and the click still returns, the one reading that needs a widget is taken on the paint thread and passed down as an argument, and a check that raises writes the sentence that belongs to the button that was pressed into the box it was filling - and the two panes paint what they are handed: no seeded telemetry, no zero for an unread adapter, one badge per check, and the start-up drive never asked",
        "timeout_seconds": 180
    },
    {
        "id": "check_threading_contract",
        "name": "Machine Checks: Which Thread Asks, In Which Words",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_check_threading_contract.py")],
        "description": "Reads the Diagnostics pane's source, builds no widget and starts no thread, and requires the three machine buttons to be one shape: each handler builds its reading, names its own row of the wording table to run_step, and never presses the closure it built - because a handler that calls the engine in its own body, or calls the measure it made, takes the 2.3 s report - 1.4 s of it the drive scan - back onto the thread that paints, which is the defect this area was opened for and the one whose verdict on the live pane was a process that aborted in two runs of nine; and the table itself is read as three rows of three non-empty texts with no two busy lines and no two failure sentences alike, so the quick check, the comprehensive check and the package read each still say which of them failed, in the box they were filling, with the status word that button used to use",
        "timeout_seconds": 120
    },
    {
        "id": "mutation_harness_contract",
        "name": "Sweep Runner: What a Run That Never Answers Is Called",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_mutation_harness_contract.py")],
        "description": "Reads the mutation runner's source and starts no process, because the question - does the sweep have a deadline - cannot be answered by running a sweep, since a sweep with no deadline is the case being asked about; requires every planted run to carry the per-entry budget, that budget to fall back to the command line, the command line default to name one module constant rather than repeat a number, and that constant to sit above the 119.4 s the slowest real entry answers in, so a loaded machine does not read as a sweep full of hangs; requires an unanswered run to be its own verdict, kept apart from a passing one by the absence of a result object, counted in the summary and to refuse the sweep's exit code; and requires the advice printed under it to name the entry, the way to raise the budget, and the fact that the product was put back - because one entry that disconnects a measurement's error channel held a whole sweep for fourteen minutes on a process whose CPU time had stopped moving, and the sweep is the instrument every other claim in this audit is measured with",
        "timeout_seconds": 120
    },
    {
        "id": "performance_backend_contract",
        "name": "Performance Backend and Frame Clock Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_performance_backend_contract.py")],
        "description": "Requires every figure on the Performance tab to be arithmetic over stamps the app's own views made, or a refusal that says which kind of nothing it is: the rate is taken over a window so a burst that stopped five seconds ago reads as stale rather than current, the four cases with no gaps to take each name themselves, the monitor primes both psutil readers when it starts so no first sample divides an empty window, an unread field stays None with its reason in not_read instead of becoming 0.0 or last run's answer, an adapter the pane was never given a reader for says that rather than reporting a raise, the score refuses when the two fields it leans on were never read, advice names the reading that caused it and the control in this app that changes it and promises no percentage, the four kinds of bounded work record what this machine did and compare only with the app's own earlier runs while a fifth kind is refused by name and no second name for the cpu work survives in the engine, a session or profile log name carrying .. a colon or a slash cannot walk out of the log folder, the storage probe measures the volume the app actually writes into, and the pane keeps the progress bar's range at the moment each percentage arrives rather than only after the run, drives all four of its worker functions through the callback the house Worker always passes, and paints the engine's own cells",
        "timeout_seconds": 180
    },
    {
        "id": "performance_pane_contract",
        "name": "Performance Pane and Control Table Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_performance_pane_contract.py")],
        "description": "Requires the Performance pane to be the two tables painted and nothing else: the boxes on screen are exactly the rows of performance_controls.CONTROLS by name, by object and by widget-tree count, every widget is built in one method off one row, no range or item list or seeded figure belongs to the pane, a box that cannot show the store's number says so instead of hiding it, every control prints the verdict its row carries while refused controls stay visible and enabled, the contract table repeats the tables' wording rather than inventing its own, the sixteen buttons are the sixteen verbs each connected to the method its row names with a dead connection reported as a failure, a stored value lands on the key its reader looks in (the Post-Processing thread box included, read back through a second QSettings object), an out-of-range stored number is shown and refused rather than corrected, a priority this app will not act on is refused by name before the store or Windows sees it, constructing the pane runs no verb and writes no key, a start-up with nothing stored claims no read, a profile is the values on screen - the knobs it may name are the controls an engine honours, applying one writes them and runs their verbs, and the record of which profile was applied last is never re-applied",
        "timeout_seconds": 180
    },
    {
        "id": "quality_analyzer_contract",
        "name": "Quality Pane Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_quality_analyzer_contract.py")],
        "description": "Double-clicks every fix row the Quality tab can produce and requires the file, the verb and the sentence to match: each of the seven one-click names calls the operation its row claims (recorded, not trusted) and leaves a file the app's own analyzer can score again, the two fixes the Pre-Processing pane owns say so by pane name instead of claiming nothing exists, an unknown name is refused by that name, a UV pack writes coordinates an atlas can use, the output file keeps a folder whose name contains a dot, the confirmation sentence names all seven filters auto_repair actually runs, Fix All marks only the rows auto_repair carried out, both reload prompts move the pane onto the file the fix wrote, a file the reader returns as a scene is still counted and stripped by texture rows, a file that lists a position twice is read whole by the engine and welded by the fix that says it welds, the analysis thread's real failure channel is the one wired, a file that cannot be opened says Error instead of grading an unread model F, every closure handed to the house Worker takes the progress_callback it is always given and every start has an error channel attached, and Export writes the HTML its button promises - the call that used to raise a TypeError, then a KeyError over its own CSS, and never wrote a file",
        "timeout_seconds": 240
    },
    {
        "id": "run_teardown_contract",
        "name": "Run Teardown Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_run_teardown_contract.py")],
        "description": "Asks the close-over-a-live-run questions where nothing enters a C++ frame, so a defect Qt otherwise answers with an access violation or a fail-fast arrives as a named test: a runner with nothing connected silences to nothing rather than raising out of closeEvent, every run a pane keeps is filed in the bucket its shutdown_runs drains and emptied by it - both of the Diagnostics lists included - and the Automation pane's plain worker is filed, joined, silenced and pruned by the pane that started it",
        "timeout_seconds": 180
    },
    {
        "id": "worker_holder_contract",
        "name": "Worker Holder Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_worker_holder_contract.py")],
        "description": "The Performance pane's half of the same questions, asked in a file that builds no pane, because that pane starts three runs while it is being built and a defect that takes away their owner then takes away the process too: the keep-helper files the run it is handed and lets it go when that run's own `finished` arrives, and every one of the pane's eight pool starts calls the helper before it starts, which is read off the syntax tree because the only way to ask it by execution is to start a run nobody holds",
        "timeout_seconds": 120
    },
    {
        "id": "download_teardown_contract",
        "name": "AI Model Manager Teardown Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_download_teardown_contract.py")],
        "description": "The two holders the widget-tree walk cannot reach, asked against a fake hub that records instead of downloading: the manager's own QThread is held, silenced and released by the dialog that started it - a stop asked at the step boundary means the second step never starts - the way out of the dialog is done() rather than a caller that remembers to ask, and the Settings pane opens the manager as its own child and keeps it, so the close walk can see a run that lives in a dialog",
        "timeout_seconds": 180
    },
    {
        "id": "thumbnail_owner_contract",
        "name": "One Picture Maker Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_thumbnail_owner_contract.py")],
        "description": "Every picture the app writes comes from its one raster and nowhere else: the dead thumbnail thread and the grid widget that was its only caller stay deleted with nothing naming them, the five callers still own their verdict, a window opener appears only in the four modules that were built around one, a committed version records a picture of its own snapshot and no other model's, a file with nothing to draw is refused with its reason, and the Versions pane paints the file its row names - including the two different sentences for a version that never had a picture and a picture whose file went missing",
        "timeout_seconds": 240
    },
    {
        "id": "version_metrics_contract",
        "name": "Version Metrics Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_version_metrics_contract.py")],
        "description": "The Versions commit reads the file a DCC actually hands it: a mesh, a multi-material Scene and a point cloud each record the counts an oracle read straight off trimesh agrees with, a file with nothing measurable is refused before it is copied, a write that fails after the copy takes the copy and its picture back, a first version claims no delta and every later one equals the two rows printed above it, a number the file does not have is stored as NULL and said in the backend's own words in the column, the details, the statistics, the dialog and the HTML export, and the pane names which of the four facts stopped a commit",
        "timeout_seconds": 240
    },
    {
        "id": "dead_modules_contract",
        "name": "Reachable Modules & Feedback Record Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_dead_modules_contract.py")],
        "description": "Which modules the app can reach is an instrument now rather than a grep: the five files no import arrives at stay deleted with nothing spelling their names, the walk reports a planted unreachable module as dead and its two counts as different numbers, its word search reads the files it claims to, it does not read the build copies, and a module named *after* the word `import` - `from src.utils import early_log` - is reached by the file that names it while a function named the same way invents no edge; the one helper the reduced utils file keeps makes the folder it names; the Painting pane the deleted second copy duplicated is still the live one on screen; and Help -> Send Feedback opens a dialog the window owns, writes a record carrying exactly the fields the user saw, keeps two records saved in the same second apart, and says which failure stopped it",
        "timeout_seconds": 240
    },
    {
        "id": "stdout_quiet_contract",
        "name": "Report Channels: No Console in the Build",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_stdout_quiet_contract.py")],
        "description": "The packaged app has no stream anybody reads, and every report it wrote into one is an instrument now: the checker's six rules run over the real tree and over planted defects (a trace in a pane, one built from an f-string, a write from a repaint and the same line parked in a comment, a `logger` bound in a class body or a sibling function rather than where it is used, a message whose `%`-slots and its arguments disagree, a record written on the root logger, a sentence that needs a glyph, a smoke test inside a hand-run `__main__` block and that same block moved into a function where the build can reach it, an exemption that matches nothing, an unparsable file), and it refuses to call an ordinary message, a `log.debug` record or a correct `%.1f%% reduction` a defect; the counts it prints are the rows it lists and the writes it splits add up to the writes it walked; the channel is proven end to end - a warning on this thread and on a worker both reach the Diagnostics table, a repaint that raises leaves one row per distinct reason and not one per frame, both of the viewer's export methods name the file they could not write and the refusal that has nothing loaded says that is why, a good export writes a file that reloads, neither pane sends the user to a console, the table's level filter is a floor rather than an equality, and its component list holds only emitters that actually wrote; and the records written before the pane exists are held by `src/utils/early_log.py`, whose premise - that an unhandled record goes to the stderr the build discards - is executed in a child process both with and without the queue, with `main.py`'s `early_log.install()`, its two `setLevel` calls and the level each converted report carries pinned at the source",
        "timeout_seconds": 180
    },
    {
        "id": "view_preset_contract",
        "name": "Presets, Scripting Surface & Load Verdict Contract",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_view_preset_contract.py")],
        "description": "Four controls that described a capability instead of reaching it, asked at the control that makes the claim: the Model pane's three Preset buttons are in the widget tree, each connected, and a click moves the Shaders row, the light, the line width and the two data switches through to the state the viewer paints from rather than only the boxes; the fifth Shaders row is the overlay mode the paint already branches on and each row reaches the mode its label names; the Scripting pane's list is the engine's own surface read off the object the executor injects as `rfx`, so all eleven calls carry the prefix, the parameters and the defaults a script needs and none of the fifteen invented names is left, and the documentation panel is built from the same reading; `load_model_file` refuses a path that is not on disk for that reason, opens its success box only when the viewer said yes, names the file it was handed, and never hands the file path to the dict-typed load report the info labels read; and the integrity dialog says the three categories with their counts, five paths and the number left out, and calls an unreadable library unreadable instead of clean",
        "timeout_seconds": 240
    },
    {
        "id": "unreachable_code_checker",
        "name": "Three Questions the Tree Can Answer",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_unreachable_code_checker.py")],
        "description": "The three shapes that compile, import and build nothing are instruments now: a body that continues past the statement that ends it - which is how an edit beside `__init__` can leave a pane with no widgets - a string statement parked below the docstring slot, which is how the Presets group shipped, buttons and all, and a `def` or `class` whose name the same scope already bound, which is how the viewer came to hold two `set_render_mode` methods and the library a `check_integrity` that no caller reached. Each question is answered on a sample that has the shape and on one that only looks like it (an exit that is the body's last line, a docstring in its slot, a property and its setter, the same name in two classes, a string that is an argument or a returned value rather than a statement), the whole reading is then taken over `src`, `tools` and `tests` and has to answer nothing, and the size of the reading is printed beside it: the roots named in the test, the file list compared against an independent `os.walk` count, the eight repaired files shown to be inside what is read. The command's own lines are asked too - the target list handed to `main` rather than `sys.argv`, so one folder is read as one folder and not as the whole app; one message per shape, the earlier binding named by line for a shadow; exit 1 when there is anything to report and the clean sentence naming all three questions so a narrowed reading cannot pass as a clean app - and a file the tree cannot parse is reported rather than skipped",
        "timeout_seconds": 180
    },
    {
        "id": "headless_gui_15_tabs",
        "name": "15-Tab Headless GUI & Synthetic Asset Suite",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_all_tabs_headless.py")],
        "description": "Runs full Qt offscreen driver across all 15 tabs using procedural edge-case 3D meshes, every file reader's release, and a close driven over a run still in flight",
        "timeout_seconds": 240
    },
    {
        "id": "clean_exit_contract",
        "name": "Who Ends the Event Loop, and What Still Owns a Window When It Does",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_clean_exit_contract.py")],
        "description": "#50 was a suite that printed OK and was scored FAIL, because PyQt6 answers a fault at the edge of a C++ frame with `0xc0000409` and this audit reads a run by its return code. The shape that decides it is who holds the last Python reference to a top-level widget when the interpreter starts tearing itself down, so `tools/check_clean_exit.py` is run over the shipped tree - all 74 files in app scope - and five rules are asked: no Qt event loop may be the argument of the exit, every file that owns a `QApplication` must hand it to `src/utils/run_teardown.shutdown` between the loop and the leaving, the drain itself must still close what is on screen, schedule it for deletion, run the queue and report what stayed, `tests/verify_all_fixes.py` must drain in `tearDownClass` rather than in a test that a halfway failure never reaches, and nothing in app scope may register an `atexit` hook. Reach is measured, not assumed: the report has to name the five files that own a loop and count five loops, five drained. Each rule is then shown blind to nothing, by a defect planted in a module written for the run, and the instrument is broken one rule at a time. Two child processes answer what cannot be tested in-process: the shipped `sys.exit(app.exec())` shape with a window in the frame (recorded at exit 0 today, so the abort is not claimed as cured and the tripwire is there if a future Qt turns it back on), and the app's own ending - loop returns 3, the drain names the window that refused the close, the process leaves with 3. The third is the release defect this phase found by hanging on it: the crash reporter shows a modal dialog whenever a QApplication exists, which in an offscreen run is a button nobody can press, so it is guarded on Qt's own `platformName()` and the test requires the handler back in well under a second with its crash record already written",
        "timeout_seconds": 240
    },
    {
        "id": "app_paths_contract",
        "name": "One Writable Home, Asked Of The Disk",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_app_paths_contract.py")],
        "description": "`installer.nsi:20` installs into `C:\\Program Files\\RenderFox`, which grants `BUILTIN\\Users` read and execute, so the nine paths the app built from its own folder or from `os.getcwd()` - the 237-model library index, its thumbnails, textures, tasks, benchmark history, crash records, version snapshots and the queue's `config.json` - resolved where the person who installed the app cannot write. `src/utils/app_paths.py` is now the only file allowed to answer, and both branches of its one hard question are read against a fake program folder (`RENDERFOX_APP_ROOT`): the candidate that takes files wins and records nothing, and a candidate that is there but refuses - which `os.makedirs(..., exist_ok=True)` answers as success for - falls back under the profile with a reason naming both folders. The probe is asked four ways: a folder that refuses a file, a name in the way that raises `FileExistsError` rather than `PermissionError`, a probe that leaves its own file behind in the folder it tested, and an explicit `RENDERFOX_OUTPUT_DIR` that is used without ever being probed. One answer per question is measured rather than claimed: `automation_engine.app_data_dir()`, `performance_analyzer.data_dir()` and the reader all return the same folder, `state_file()` prefers a copy that already sits beside the app and falls to the profile - which is what the AI tagger's `config/asset_tags.json` is asked through, out of the shipped file, against a program folder that refuses a write - `config_path()` is the same question as `state_file('config.json')`, and with no override at all the profile is the account's own folder and not the app's. The six other readers are retired and read as callers instead: `bundled()` must name a real file for the icon, the splash and the guide in this checkout, the FFmpeg search must reach both the folder `installer.nsi:107` writes and the `resources` folder the build ships, every file that asks the reader must import the name it asks (`src/features/ai_asset_tagger.py` imported `data_dir` and called three others, which is a `NameError` the moment a tag is saved), and no caller may re-type the `frozen` / `_MEIPASS` / `dirname`-of-`__file__` shape. `tools/check_paths_hygiene.py` is then read as the instrument it is - five rules over 74 files in app scope with nothing left to find, and over a fixture with the eight violations counted by hand per rule (2 getcwd, 1 profile literal, 3 output joins, 2 bare settings opens) plus the re-derived app folder, a docstring that spells the profile folder not counted as a second defect, a demo block that must name the path before importing exempted, a file that cannot be parsed reported rather than skipped, and `--strict` exiting 1 over the fixture and 0 over the shipped tree. 21 tests, 6.4 s",
        "timeout_seconds": 120
    },
    {
        "id": "names_bound_contract",
        "name": "Names the App Reads That No Line Binds",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_names_bound_contract.py")],
        "description": "Phase 38 moved six files' hand-typed folder answers onto `src/utils/app_paths.py` and, in `main.py`, replaced the line that bound `base_dir` while leaving `main.py:132` two lines below still reading it - so the app raises `NameError` on the way up, before a window exists, and no suite in the tree can see it: the paths suite reads that file as a caller (its imports and its calls were both right), this chain never calls `main()`, and `tests/test_clean_exit_contract.py:559` imports the module and stops. `tools/check_names_bound.py` asks the question with a real scope analyser instead of a rule of mine - pylint's `used-before-assignment` and `undefined-variable`, over the same 74 files `tools/check_paths_hygiene.py` walks - and measures 0 findings on this tree. Four verdicts: the shipped tree is clean and its file count is pinned, because a walk that shrinks to one file also answers zero; both shapes are reported on a two-file fixture, each named by file and by the name itself; `--strict` exits 1 over the fixture, which is the half that makes it a gate rather than a report; and a run that cannot start pylint is reported as a finding rather than as a clean tree, which is the failure mode this repo has had to name twice. 4 tests, 40.1 s - almost all of it pylint over 74 files, one process and no `QApplication`",
        "timeout_seconds": 240
    }
]


def print_banner():
    print("=" * 75)
    print("[RenderFox] Solo-Developer Master Health & Audit Suite")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python: {sys.version.split()[0]} | Platform: {sys.platform}")
    print("=" * 75)


def run_suite(suite_info):
    name = suite_info["name"]
    cmd = suite_info["command"]
    desc = suite_info["description"]
    
    print(f"\n▶ [{name}]")
    print(f"  Purpose: {desc}")
    start = time.time()
    
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONIOENCODING'] = 'utf-8'
    budget = suite_info.get("timeout_seconds", 120)

    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT_DIR,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=budget
        )
        elapsed = time.time() - start
        success = (proc.returncode == 0)
        
        status_badge = "✅ PASS" if success else "❌ FAIL"
        print(f"  Result: {status_badge} ({elapsed:.2f}s)")
        
        if not success:
            print("  --- Stderr snippet ---")
            lines = (proc.stderr or proc.stdout).strip().splitlines()
            for line in lines[-8:]:
                print(f"    {line}")
                
        return {
            "id": suite_info["id"],
            "name": name,
            "status": "PASS" if success else "FAIL",
            "elapsed_seconds": round(elapsed, 2),
            "output_tail": (proc.stdout or "")[-300:]
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"  Result: TIMEOUT after the {budget}s budget ({elapsed:.2f}s). Run the suite by "
              f"hand before reading this as a defect - a busy machine and a real hang look alike "
              f"in this report.")
        return {
            "id": suite_info["id"],
            "name": name,
            "status": "TIMEOUT",
            "elapsed_seconds": round(elapsed, 2),
            "error": f"exceeded its {budget}s budget"
        }
    except Exception as e:
        elapsed = time.time() - start
        print(f"  Result: ❌ ERROR: {e} ({elapsed:.2f}s)")
        return {
            "id": suite_info["id"],
            "name": name,
            "status": "ERROR",
            "elapsed_seconds": round(elapsed, 2),
            "error": str(e)
        }


def main():
    print_banner()
    total_start = time.time()
    results = []
    
    for suite in SUITES:
        res = run_suite(suite)
        results.append(res)
        
    total_elapsed = time.time() - total_start
    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)
    
    print("\n" + "=" * 75)
    print("📋 AUDIT SUMMARY DASHBOARD")
    print("=" * 75)
    for r in results:
        badge = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {badge} {r['name']:<48} [{r['status']}] ({r['elapsed_seconds']}s)")
    print("-" * 75)
    health_score = int((passed / total) * 100)
    print(f"Overall Health Score: {health_score}% ({passed}/{total} suites passed in {total_elapsed:.2f}s)")
    print("=" * 75)
    
    # Save audit report
    report_path = os.path.join(ROOT_DIR, "audit_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"RenderFox Health Audit Report - {datetime.now().isoformat()}\n")
        f.write(f"Health Score: {health_score}% ({passed}/{total})\n\n")
        for r in results:
            f.write(f"[{r['status']}] {r['name']} ({r['elapsed_seconds']}s)\n")
            
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
