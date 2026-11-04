"""
Installer for the mock DCC harness.

`JobManager` and `detect_available_software` resolve an engine from
`config.json` in the current working directory (`software.blender` and friends).
That is the app's own configuration path, so the harness writes a real
`config.json` next to real executables and lets the app find them the way it
would find Blender - no patching, no fake detector, no test-only branch in
production code.

Each executable is a two-line shim that forwards to `mock_dcc.py` with the
package name it is emulating, which is what makes `BlenderEngine.is_available`
("Blender" must appear in stdout of `--version`) pass honestly.

Used by tests/test_mock_dcc.py and, from Phase 4 on, by the job manager tests.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOCK = os.path.join(HERE, 'mock_dcc.py')

# software_type value -> (emulated package, executable name, project extension)
PACKAGES = {
    'blender': ('blender', 'blender', '.blend'),
    'maya': ('maya', 'maya', '.ma'),
    'cinema4d': ('cinema4d', 'cinema4d', '.c4d'),
    'unreal': ('unreal', 'UnrealEditor', '.uproject'),
}

IS_WINDOWS = os.name == 'nt'


def _shim_body(package):
    """A batch/posix wrapper that behaves like the real executable."""
    quoted = '"{}" "{}" {}'.format(sys.executable, MOCK, package)
    if IS_WINDOWS:
        return '@echo off\r\n' + quoted + ' %*\r\n'
    return '#!/bin/sh\nexec ' + quoted + ' "$@"\n'


def install(root):
    """Create shims + config.json under `root` and return {software: path}."""
    executables = {}
    for key, (package, name, _extension) in PACKAGES.items():
        filename = name + ('.cmd' if IS_WINDOWS else '')
        path = os.path.join(root, filename)
        with open(path, 'w', encoding='utf-8', newline='') as handle:
            handle.write(_shim_body(package))
        if not IS_WINDOWS:
            os.chmod(path, 0o755)
        executables[key] = path

    with open(os.path.join(root, 'config.json'), 'w', encoding='utf-8') as handle:
        json.dump({'software': executables}, handle, indent=2)
    return executables


def write_scene(root, software_key, name='scene', **scene):
    """Write a project file whose contents are the render's behaviour."""
    extension = PACKAGES[software_key][2]
    path = os.path.join(root, name + extension)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(scene, handle, indent=2)
    return path


def run(software_key, *arguments):
    """Invoke the shim directly, for the tests that assert on the CLI itself."""
    package = PACKAGES[software_key][0]
    command = [sys.executable, MOCK, package] + [str(argument) for argument in arguments]
    return subprocess.run(command, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
