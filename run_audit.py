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
        "description": "Validates database integrity, translation matrices, process handles, and engine bindings"
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
        "description": "Draws real frames with the app's own raster and requires the picture on disk to be the picture reported: every lamp knob monotone in the pixels, every camera knob visible, fit holding a 0.06-unit and an 8-unit model in one frame, the window floor and ceiling resampled and admitted in the note, transparency accounting for every pixel, and the four Open3D traps this machine punishes (engine head light on, fresh PinholeCameraIntrinsic, plain look-at extrinsic, window left open) pinned from the source as well as the frame",
        "timeout_seconds": 180
    },
    {
        "id": "headless_gui_15_tabs",
        "name": "15-Tab Headless GUI & Synthetic Asset Suite",
        "command": [sys.executable, "-X", "utf8", os.path.join(ROOT_DIR, "tests", "test_all_tabs_headless.py")],
        "description": "Runs full Qt offscreen driver across all 15 tabs using procedural edge-case 3D meshes"
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
