"""Ask the built package the questions the app asks of it, with the reader the package ships.

``RenderFox.spec`` decides what lands in ``dist\\RenderFox``, and ``src\\utils\\app_paths.py``
decides where the app looks. Nothing in the tree checks that those two answers are the same
answer, which is how ``USER_GUIDE.md`` came to be missing from the build: the Help pane asked
``bundled('USER_GUIDE.md')``, the spec shipped ``src``, ``resources`` and the assimp build, and
every test that could see the mismatch ran from the checkout, where ``bundled()`` answers beside
``app_root()`` and the guide happens to be there.

So this tool fakes a packaged start - ``sys.frozen`` and ``sys._MEIPASS`` for the bundled folder,
``RENDERFOX_APP_ROOT`` for the executable's folder - and asks the shipped ``app_paths.py`` the
names the shipped callers pass it. The reader is loaded out of the package, so the answer is the
one the person who installs this build gets, not the one this checkout gets.

Run it after the build: ``python -X utf8 tools/check_package_layout.py dist/RenderFox``.
"""

import argparse
import ast
import importlib.util
import os
import sys
from pathlib import Path

INTERNAL = '_internal'

# The name each shipped caller passes, with the file and line that passes it. Read from the tree
# by hand and kept short on purpose: a rule that derives these from the callers would need to
# run the callers, and `src/ui/main_window.py` cannot be imported without a QApplication.
ASKED = [
    ('main.py:121,124 and src/ui/main_window.py:68,70', os.path.join('resources', 'icon.ico'), 'file'),
    ('main.py:132', os.path.join('resources', 'splash.png'), 'file'),
    ('src/ui/styles.py:13', os.path.join('resources', 'icons'), 'dir'),
    ('src/ui/main_window.py:365', 'USER_GUIDE.md', 'file'),
]

# One file in a folder, because the assimp build is named by its toolchain version.
LIBRARY = ('src/processing/format_converter.py:29', 'lib', 'assimp')


def load_reader(package: Path):
    """The ``app_paths`` the package shipped, answering as a packaged start answers."""
    module_file = package / INTERNAL / 'src' / 'utils' / 'app_paths.py'
    if not module_file.is_file():
        raise SystemExit(f'{module_file} is not there: the package does not ship the reader, '
                         'so nothing below this line can be asked of it.')
    spec = importlib.util.spec_from_file_location('shipped_app_paths', module_file)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    sys.frozen = True                                  # the branch no source run reaches
    sys._MEIPASS = str(package / INTERNAL)
    os.environ['RENDERFOX_APP_ROOT'] = str(package)
    return reader


def ffmpeg_build(path: Path) -> str:
    """The build folder name ``src/core/video_exporter.py:20`` writes down, read off its source."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'FFMPEG_BUILD':
                    return node.value.value
    raise SystemExit(f'{path} no longer binds FFMPEG_BUILD, so the transcoder search moved')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('package', help='the folder PyInstaller wrote (dist/RenderFox)')
    args = parser.parse_args()

    package = Path(args.package).resolve()
    if not package.is_dir():
        print(f'no package at {package}')
        return 1

    failures = []
    exe = package / 'RenderFox.exe'
    print(f'{"ok" if exe.is_file() else "MISSING"}  {exe}  <- the shortcut installer.nsi:97 starts')
    if not exe.is_file():
        failures.append('RenderFox.exe')

    try:
        reader = load_reader(package)
    except SystemExit as refused:
        print(f'MISSING  {refused}')
        return 1

    for caller, name, kind in ASKED:
        answer = reader.bundled(name)
        there = os.path.isdir(answer) if kind == 'dir' else os.path.isfile(answer)
        print(f'{"ok" if there else "MISSING"}  {answer}  <- {caller}')
        if not there:
            failures.append(name)

    folder, lib_folder, needle = LIBRARY
    library = reader.bundled(lib_folder)
    found = [p.name for p in Path(library).glob(f'{needle}*.dll')] if os.path.isdir(library) else []
    print(f'{"ok" if found else "MISSING"}  {library} holds {found or "no assimp build"}  <- {folder}')
    if not found:
        failures.append(f'{lib_folder}/{needle}*.dll')

    build = ffmpeg_build(package / INTERNAL / 'src' / 'core' / 'video_exporter.py')
    shipped = reader.bundled(os.path.join('resources', build, 'bin', 'ffmpeg.exe'))
    installed = os.path.join(reader.app_root(), 'ffmpeg', 'bin', 'ffmpeg.exe')
    if os.path.isfile(shipped):
        print(f'ok      {shipped}  <- src/core/video_exporter.py:42 (the build ships it)')
    else:
        print(f'note    {shipped} is not in the package; the app then relies on '
              f'{installed}, which installer.nsi:107 writes - and on PATH')

    # The two answers that decide whether an installed app can write anything at all. Printed
    # because they are the machine's answer, not the package's: this folder is writable, so
    # output_dir() keeps the candidate, and a Program Files install gets the profile instead.
    print(f'note    app_root()   -> {reader.app_root()}')
    print(f'note    data_dir()   -> {reader.data_dir()}')
    print(f'note    output_dir() -> {reader.output_dir()}')

    print(f'{len(ASKED) + 2} questions the shipped callers ask, {len(failures)} unanswered')
    for name in failures:
        print(f'  unanswered: {name}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
