"""Who reads what the app writes, and does the name it uses exist?

The shipped build is packaged with ``console=False`` (`RenderFox.spec:29`), so the process
has no console: a write to stdout or stderr goes where nobody can read it. That makes the
app's reports one of three things, and this checker asks a question about each.

**A debug trace has no destination.** Twenty ``print("DEBUG: ...")`` calls sat in the load,
pick and paint paths, and the ones in ``paintGL`` ran at the frame rate. They are gone; rule
1 keeps them gone by refusing any stdout write whose text starts with ``DEBUG``, in every
app file. A commented-out trace in the paint path is refused by rule 2 as well, because the
one that was deleted here read "useful if needed", which is an invitation to put a 60 fps
write back into the function that must never have one.

**A failure needs a channel the user can open.** The only one the app has is the root
logger: `src/ui/diagnostics_tab.py:733` puts a `PaneLogHandler` on it, and the Diagnostics
pane turns each record into a row. Rule 3 checks the other half of that path - that every
bare ``logger.`` call resolves to a name the module or the enclosing function actually
bound. A ``logger.warning`` with no ``logger`` is a ``NameError`` raised inside an
``except`` block, which is worse than the silent line it replaced: it hides the failure and
adds one of its own.

Rule 2 is narrower than "no printing while painting" on purpose. The information that a
paint failed is worth keeping, and `frame_clock.note_failure` already collects it; what
cannot stay is the write to a stream the package closes.

What this file does **not** yet ask is the widest question, because the tree would not pass
it: 101 ``print`` calls remain in `src/` and `main.py` and most of them sit in `except`
handlers, so the failures they describe are written into the same closed stream. That is
#52, and when it lands rule 2 grows a fourth rule over exactly these lines.

    python -X utf8 tools/check_stdout_quiet.py            # report
    python -X utf8 tools/check_stdout_quiet.py --strict    # exit 1 unless the tree is clean

``--strict`` is what the contract suite runs, and what a future change has to pass.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP = {'__pycache__', '.git', '.venv', 'build', 'dist', 'patch_script', 'visualizations', 'node_modules'}

# A trace is a stdout write that begins with this word. `logger.debug` is not a trace: it is a
# record on the channel the Diagnostics pane owns, whatever becomes of its level - and nothing in
# the app calls `setLevel` or `basicConfig`, so the root logger sits at WARNING and a DEBUG record
# is dropped before it reaches any handler today. Measured, not assumed; #52 owns that half.
DEBUG_LABEL = 'DEBUG'

# The functions that run once per repaint: the one Qt calls, and the report it hands the
# failure to. Anything written here is written at the frame rate, which is why the second name
# is in the list - moving the write out of `paintGL` and into the method it calls would other-
# wise step around this rule while changing nothing a user sees.
PAINT_FUNCTIONS = {'paintGL', '_report_paint_failure'}

# What counts as a write to a stream: `print`, and traceback's own console helpers.
# `traceback.format_exc` is not in this list - it returns a string, and a string handed to a
# signal or a dialog is exactly the visible report this checker wants more of.
PRINT_NAMES = {'print', 'pprint'}
TRACEBACK_WRITERS = {'print_exc', 'print_last', 'print_file', 'print_stack'}

# A comment whose whole text is a call that was parked rather than deleted. Matched against the
# text after the `#`, so the pattern must not ask for the hash again.
COMMENTED_PRINT = re.compile(r'\b(?:print|print_exc|print_last)\s*\(')


def app_files(root: Path = ROOT):
    """Every source file the packaged app ships: ``src/`` and the entry point."""
    src = [p for p in (root / 'src').rglob('*.py') if not SKIP.intersection(p.parts)]
    entry = root / 'main.py'
    return sorted(src + ([entry] if entry.exists() else []))


def _source(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace')


def _label_of(call: ast.Call):
    """The text a stdout write begins with, when it begins with a plain word."""
    if not call.args:
        return ''
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    if isinstance(first, ast.JoinedStr) and first.values:
        head = first.values[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value
    return ''


def _is_print_like(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in PRINT_NAMES
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id == 'traceback' and func.attr in TRACEBACK_WRITERS
    return False


def stdout_writes(path: Path):
    """Every ``(lineno, text)`` pair where this file writes to a stream."""
    tree = ast.parse(_source(path), filename=str(path))
    return [(node.lineno, _label_of(node))
            for node in ast.walk(tree) if _is_print_like(node)]


def debug_traces(path: Path):
    """Rule 1: a stream write whose text starts with ``DEBUG``."""
    return [(line, text) for line, text in stdout_writes(path)
            if text.strip().startswith(DEBUG_LABEL)]


def paint_path_writes(path: Path):
    """Rule 2: nothing at all may be written from inside a repaint.

    Comments are read too, by line range: the defect this rule replaces was a parked trace,
    invisible to the parse tree and one un-comment away from running on every frame.
    """
    source = _source(path)
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in PAINT_FUNCTIONS:
            continue
        start = min(getattr(child, 'lineno', node.lineno) for child in ast.walk(node))
        end = max(getattr(child, 'end_lineno', getattr(child, 'lineno', node.lineno))
                  for child in ast.walk(node))
        for child in ast.walk(node):
            if _is_print_like(child):
                found.append((child.lineno, 'writes to stdout while painting'))
        for number in range(start, min(end, len(lines)) + 1):
            text = lines[number - 1]
            if '#' not in text:
                continue
            if COMMENTED_PRINT.search(text.split('#', 1)[1]):
                found.append((number, 'holds a parked stdout write'))
    return found


def _bound_names(scope_node):
    """Names one scope binds, without entering the scopes nested inside it.

    Python resolves a bare name through the function it is written in, then the module. A
    name assigned inside a nested function or class body belongs to that body, so the walk
    stops at those nodes and does not lend the name outward.
    """
    out = set()

    def targets(node):
        names = set()
        stack = [node]
        while stack:
            cur = stack.pop()
            if isinstance(cur, ast.Name):
                names.add(cur.id)
            elif isinstance(cur, (ast.Tuple, ast.List)):
                stack.extend(cur.elts)
            elif isinstance(cur, ast.Starred):
                stack.append(cur.value)
        return names

    stack = [scope_node]
    while stack:
        cur = stack.pop()
        if cur is not scope_node and isinstance(
                cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(cur, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            nodes = cur.targets if isinstance(cur, ast.Assign) else [cur.target]
            for node in nodes:
                out |= targets(node)
        elif isinstance(cur, (ast.Import, ast.ImportFrom)):
            out |= {a.asname or a.name.split('.')[0] for a in cur.names}
        elif isinstance(cur, ast.ExceptHandler) and cur.name:
            out.add(cur.name)
        elif isinstance(cur, (ast.With, ast.AsyncWith)):
            for item in cur.items:
                if item.optional_vars:
                    out |= targets(item.optional_vars)
        elif isinstance(cur, (ast.For, ast.AsyncFor)):
            out |= targets(cur.target)
        elif isinstance(cur, ast.NamedExpr):
            out |= targets(cur.target)
        elif isinstance(cur, (ast.Global, ast.Nonlocal)):
            out |= set(cur.names)
        elif isinstance(cur, ast.comprehension):
            out |= targets(cur.target)
        stack.extend(ast.iter_child_nodes(cur))
    return out


def unresolved_logger_uses(path: Path, name: str = 'logger'):
    """Rule 3: line numbers where ``name`` is called but bound nowhere it can be found.

    ``entrance`` is what a statement written directly in the scope being walked can see from
    outside it. A scope adds its own bindings to that for its own statements, and hands what
    it computed to a nested function - except a class body, whose names a method cannot reach
    by bare name at all. That one distinction is why a ``logger`` moved from module level into
    a class header is reported instead of passed: the method would raise on the first call.
    """
    tree = ast.parse(_source(path), filename=str(path))
    missing = []

    def visit(node, entrance):
        binds = _bound_names(node) if not isinstance(node, ast.Lambda) else set()
        outer = entrance | binds
        inherit = entrance if isinstance(node, ast.ClassDef) else outer
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                visit(child, inherit)
                continue
            if (isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name)
                    and child.value.id == name and name not in outer):
                missing.append(child.lineno)
            visit(child, outer)

    visit(tree, set())
    return sorted(set(missing))


def scan(paths):
    """Every rule, over the given files: ``[(file, rule, lineno, detail), ...]``."""
    found = []
    for path in paths:
        rel = path.relative_to(ROOT).as_posix() if path.is_absolute() and ROOT in path.parents else path.as_posix()
        for line, _text in debug_traces(path):
            found.append((rel, 'debug-trace', line, 'a DEBUG trace written to a stream the build discards'))
        for line, detail in paint_path_writes(path):
            found.append((rel, 'paint-path', line, detail))
        for line in unresolved_logger_uses(path):
            found.append((rel, 'logger-name', line,
                          '`logger` is used but bound in neither the module nor the function'))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--strict', action='store_true',
                        help='exit 1 when any rule is broken')
    parser.add_argument('--file', action='append', default=None,
                        help='check only these paths, relative to the repository root')
    args = parser.parse_args()

    paths = [ROOT / f for f in args.file] if args.file else app_files()
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f'file not found: {", ".join(missing)}')
        return 2

    found = scan(paths)
    counts = {'debug-trace': 0, 'paint-path': 0, 'logger-name': 0}
    for _rel, rule, _line, _detail in found:
        counts[rule] += 1
    print(f'files checked: {len(paths)}; debug traces: {counts["debug-trace"]}; '
          f'writes from a repaint: {counts["paint-path"]}; unresolved `logger`: {counts["logger-name"]}')
    for rel, rule, line, detail in found:
        print(f'{rule}: {rel}:{line} {detail}')
    if not found:
        print('nothing is written to a stream from the paint path, no DEBUG trace remains, '
              'and every log call names a logger that exists')
    return 1 if (args.strict and found) else 0


if __name__ == '__main__':
    sys.exit(main())
