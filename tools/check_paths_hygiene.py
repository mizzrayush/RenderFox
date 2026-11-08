"""Who is allowed to answer "where does this file go?".

``src/utils/app_paths.py`` is the answer this app settled on in Phase 38, and a reader is only
worth having while nothing else re-types the question. Every rule below is a shape that used to
exist in the shipped tree, measured on the tree this checker is run against:

**Rule 1 refuses a path built from the folder the app was started in.** ``os.getcwd()`` appeared
in five files - the library index, the queue settings, the script store, the crash records and
the user guide - so starting RenderFox by double-clicking a model in Explorer pointed the app at
an empty library, and installing it per ``installer.nsi:20`` pointed it at
``C:\\Program Files\\RenderFox``, which ``C:\\Program Files`` grants ``BUILTIN\\Users`` read and
execute only.

**Rule 2 refuses the profile folder spelled by hand.** ``'.renderfox'`` was written out in four
files, which is how one thumbnail folder ended up in ``~/.renderfox`` and its sibling in
``<app>/output``: two folders holding thumbnails for the same 237 models, and a Clear Thumbnails
button that emptied one of them.

**Rule 3 refuses an ``output`` folder joined together by hand**, because the folder the app makes
its files in is the one thing that has to move when the program folder refuses - a caller that
builds the path itself cannot ask.

**Rule 4 refuses a settings file opened by a bare name.** ``open('config.json')`` resolves
against the working directory, and the three readers plus the Settings pane's Save button each
did exactly that, so the file the person saved to was not the file the queue read.

**Rule 5 refuses the app folder re-derived by a caller.** ``dirname`` of ``__file__``, ``dirname``
of ``sys.executable`` and a ``getattr(sys, '_MEIPASS', ...)`` are the three ways the reader's own
answer gets typed out a second time, and Phase 38 measured six files that had done exactly that -
``src/ui/styles.py``, ``src/core/video_exporter.py``, ``src/processing/format_converter.py``,
``main.py``, ``src/ui/main_window.py`` and ``src/features/ai_asset_tagger.py`` twice. The rule is
blind to two things on purpose: ``sys.executable`` on its own, which is the interpreter
``src/ui/automation_tab.py:1734`` hands to the user's own script and not a folder, and an
``if __name__ == '__main__':`` demo, which has to name the project folder on ``sys.path`` before
it can import the module that would answer the question.

Docstrings are excluded on purpose: rule 2 and rule 3 read string constants, and the prose that
explains these defects *is* a string constant. Measured: without the exclusion this checker
reports three violations in the file that documents them.

    python -X utf8 tools/check_paths_hygiene.py                 # report on this tree
    python -X utf8 tools/check_paths_hygiene.py --strict        # exit 1 unless clean
    python -X utf8 tools/check_paths_hygiene.py --root DIR      # ask of another tree
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
SKIP = {'__pycache__', '.git', '.venv', 'build', 'dist', 'patch_script', 'visualizations',
        'node_modules'}

# The one module allowed to spell these answers: it is the reader, not a caller.
HOME = 'app_paths.py'

RULES = (
    ('a path built from the folder the app was started in', 'getcwd'),
    ('the profile folder spelled by hand', 'profile-literal'),
    ('an output folder joined together by hand', 'output-join'),
    ('a settings file opened by a bare name', 'config-open'),
    ('the app folder re-derived by a caller', 'second-reader'),
)


def app_files(root: Path = ROOT) -> List[Path]:
    """Every source file the packaged app ships: ``src/`` and the entry point."""
    src = [p for p in (root / 'src').rglob('*.py') if not SKIP.intersection(p.parts)]
    entry = root / 'main.py'
    return sorted(src + ([entry] if entry.exists() else []))


def _docstring_nodes(tree: ast.AST) -> set:
    """The constants that are a module's, class's or function's docstring.

    They carry the words this file itself quotes, so a rule that reads string constants has to
    know which strings are prose; ``ast.get_docstring`` names them per node rather than leaving
    a caller to guess by line number.
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, 'body', None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def _names_profile(value: str) -> bool:
    """Whether this string carries ``.renderfox`` as a folder of its own.

    Measured on this tree: one string holds ``.renderfox_backups``, the folder the Automation
    pane copies a file into *beside the file it backed up*. That is a name that happens to start
    like the profile folder, not the profile folder, so the rule reads components rather than
    substrings - otherwise the checker refuses a folder it has no complaint about.
    """
    return any(part == '.renderfox' for part in re.split(r'[\\/]', value))


def _is_path_join(node: ast.Call) -> bool:
    """``os.path.join(...)`` or a ``Path`` division, as one test."""
    name = node.func
    return isinstance(name, ast.Attribute) and name.attr == 'join'


def _demo_block_lines(tree: ast.AST) -> set:
    """The lines inside an ``if __name__ == '__main__':`` block.

    A hand-run demo cannot import the reader before it has put the project folder on
    ``sys.path``, so naming that folder is the one thing such a block has to do itself.
    """
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and '__main__' in ast.dump(node.test):
            for child in ast.walk(node):
                lineno = getattr(child, 'lineno', None)
                if lineno:
                    lines.add(lineno)
    return lines


def _re_derives_folder(node: ast.Call) -> str:
    """Why this call is the reader's answer typed out again, or ``''`` when it is not.

    Only ``dirname``/``abspath`` of ``__file__`` or of the executable count. ``sys.executable``
    by itself is a interpreter, not a folder, and a caller that runs the user's script with it is
    asking a different question.
    """
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in ('dirname', 'abspath')):
        return ''
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id == '__file__':
            return f'os.path.{func.attr}() of `__file__`'
        if isinstance(inner, ast.Attribute) and inner.attr == 'executable' \
                and isinstance(inner.value, ast.Name) and inner.value.id == 'sys':
            return f'os.path.{func.attr}() of the executable'
    return ''


def _violations(path: Path, text: str) -> Iterable[Tuple[str, int, str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as failed:
        yield ('unparsable', failed.lineno or 0, f'{path.name}: {failed.msg}')
        return
    prose = _docstring_nodes(tree)
    demo = _demo_block_lines(tree)
    spells_home = path.name == HOME
    derived = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            callee = (func.attr if isinstance(func, ast.Attribute)
                      else getattr(func, 'id', ''))
            # Rule 1: getcwd() is a read of the folder the process was started in, wherever it
            # is used - the app has no answer for what that folder should hold.
            if callee == 'getcwd':
                yield ('getcwd', node.lineno, f'{_relative(path)}:{node.lineno} os.getcwd()')
            if _is_path_join(node) and not spells_home:
                for arg in node.args:
                    # Rule 3: <anything>/output, which is the folder that has to be able to move.
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                            and arg.value.strip('\\/') == 'output' and id(arg) not in prose:
                        yield ('output-join', node.lineno,
                               f'{_relative(path)}:{node.lineno} os.path.join(..., {arg.value!r})')
            if isinstance(func, ast.Name) and func.id == 'open' and not spells_home:
                first = node.args[0] if node.args else None
                # Rule 4: a bare 'config.json' is resolved against the working directory.
                if isinstance(first, ast.Constant) and isinstance(first.value, str) \
                        and 'config.json' in first.value:
                    yield ('config-open', node.lineno,
                           f'{_relative(path)}:{node.lineno} open({first.value!r})')
            # Rule 5: the app folder, re-derived. One report per line, because a nested
            # dirname(abspath(__file__)) is two calls answering one question.
            if not spells_home and node.lineno not in demo and node.lineno not in derived:
                reason = _re_derives_folder(node)
                if reason:
                    derived.add(node.lineno)
                    yield ('second-reader', node.lineno,
                           f'{_relative(path)}:{node.lineno} {reason}')
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and not spells_home \
                and node.lineno not in demo:
            right = node.right
            if isinstance(right, ast.Constant) and isinstance(right.value, str) \
                    and right.value.strip('\\/') == 'output':
                yield ('output-join', node.lineno,
                       f'{_relative(path)}:{node.lineno} ... / {right.value!r}')
        if isinstance(node, ast.Constant) and not spells_home and node.value == '_MEIPASS' \
                and node.lineno not in demo:
            # Rule 5 again: the unpack folder, read by a caller instead of asked of bundled().
            yield ('second-reader', node.lineno,
                   f'{_relative(path)}:{node.lineno} `sys._MEIPASS` read by a caller')
        if isinstance(node, ast.Constant) and not spells_home and isinstance(node.value, str) \
                and id(node) not in prose and _names_profile(node.value):
            # Rule 2: the profile folder, spelled by a caller instead of asked of the reader.
            yield ('profile-literal', node.lineno,
                   f'{_relative(path)}:{node.lineno} {node.value!r}')


def _relative(path: Path) -> str:
    """The file as a reader finds it: from ``src`` down, or the name when it is not under it."""
    parts = path.parts
    if 'src' in parts:
        return Path(*parts[parts.index('src'):]).as_posix()
    return path.name


def scan(root: Path = ROOT) -> Tuple[int, List[Tuple[str, int, str]]]:
    """The files asked and every violation, as (rule id, line, where)."""
    found: List[Tuple[str, int, str]] = []
    files = app_files(root)
    for path in files:
        found.extend(_violations(path, path.read_text(encoding='utf-8', errors='replace')))
    return len(files), sorted(found, key=lambda row: (row[0], row[2]))


def report(root: Path = ROOT) -> str:
    count, found = scan(root)
    by_rule = {rule: 0 for _, rule in RULES}
    for rule, _line, where in found:
        by_rule[rule] = by_rule.get(rule, 0) + 1
    lines = [f'{count} files in app scope, {len(RULES)} rules, {len(found)} violations']
    for label, rule in RULES:
        lines.append(f'  {by_rule.get(rule, 0):>3}  {label}')
    for rule, line, where in found:
        lines.append(f'  {rule}: {where}')
    return '\n'.join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', default=str(ROOT), help='tree to ask, for a fixture run')
    parser.add_argument('--strict', action='store_true', help='exit 1 unless the tree is clean')
    args = parser.parse_args(argv)
    print(report(Path(args.root)))
    _count, found = scan(Path(args.root))
    return 1 if (args.strict and found) else 0


if __name__ == '__main__':
    sys.exit(main())
