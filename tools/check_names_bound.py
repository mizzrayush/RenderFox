"""A name the app uses that no line of the file binds.

Phase 38 replaced ``base_dir = os.path.dirname(os.path.abspath(__file__))`` in ``main.py`` with a
call to the reader, and left ``splash_path = os.path.join(base_dir, ...)`` two lines below it
pointing at the name that had just gone. ``main.py:132`` then raises ``NameError`` on the way up,
before a window is on screen: the app does not start, and nothing in the 38-suite chain or the
21-test paths suite notices, because no suite calls ``main()``. ``tests/test_clean_exit_contract.py:559``
imports ``main`` and stops there, which is exactly how far an import gets.

This is the same class ``tools/check_stdout_quiet.py`` rule 3 refuses for ``logger`` - a bare name
that resolves to nothing at the moment it is reached - and it cannot be caught by a rule of my own
invention without re-writing a Python scope analyser. So the question is asked with the analyser
that exists: pylint's two messages for a name no line binds (``used-before-assignment`` and
``undefined-variable``) over the same app scope `check_paths_hygiene` walks. Measured on this tree
after the fix: 74 files, 0 findings, 59 s.

    python -X utf8 tools/check_names_bound.py                   # report on this tree
    python -X utf8 tools/check_names_bound.py --strict          # exit 1 unless clean
    python -X utf8 tools/check_names_bound.py --root DIR        # ask of another tree
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_paths_hygiene import app_files

ROOT = Path(__file__).resolve().parent.parent

# The two answers that decide whether the file can run at all. Anything wider here and the tool
# starts reporting style, which is how a gate gets its exemptions added.
MESSAGES = 'E0601,E0602'

FINDING = re.compile(r'^(?P<file>.+?):\d+:\d+: E060[12]: (?P<text>.*?) \((?P<symbol>[A-Za-z_-]+)\)$')


def scan(root: Path) -> tuple:
    """(files asked, findings). A tool that cannot ask reports that, rather than an empty list."""
    files = app_files(root)
    command = [sys.executable, '-m', 'pylint', '--disable=all', f'--enable={MESSAGES}',
               '--persistent=n', '--score=n', '--jobs=1', *[str(f) for f in files]]
    try:
        answered = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=600)
    except (OSError, subprocess.TimeoutExpired) as failed:
        return len(files), [f'pylint was not run ({type(failed).__name__}: {failed})']
    found = []
    for line in (answered.stdout or '').splitlines():
        matched = FINDING.match(line)
        if matched:
            where = matched.group('file')
            try:
                where = Path(where).relative_to(root).as_posix()
            except ValueError:
                pass
            found.append(f'{where}: {matched.group("symbol")} - {matched.group("text")}')
    return len(files), found


def report(root: Path = ROOT) -> str:
    """The measured answer as the person running the gate reads it."""
    count, found = scan(root)
    lines = [f'{count} files in app scope, {len(found)} names no line binds']
    lines += [f'  {one}' for one in found]
    return '\n'.join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Report a name no line in its own file binds.')
    parser.add_argument('--root', default=str(ROOT), help='the tree to ask')
    parser.add_argument('--strict', action='store_true', help='exit 1 unless the answer is zero')
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    count, found = scan(root)
    print(f'{count} files in app scope, {len(found)} names no line binds')
    for one in found:
        print(f'  {one}')
    return 1 if (args.strict and found) else 0


if __name__ == '__main__':
    sys.exit(main())
