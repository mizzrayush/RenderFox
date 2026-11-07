"""Which modules under ``src/`` can the app actually reach?

A file that no import statement names is maintained, packaged and re-read by every audit
forever, so this answers the question with the import graph instead of with a grep: it parses
every source file, resolves relative imports to the module they really mean, and walks the
edges out of the entry points. The grep is the thing that got this wrong - `from ..utils.file_utils
import get_temp_directory` and `from .feedback_dialog import FeedbackDialog` hold neither module's
dotted name, so a search for `src.utils.file_utils` in `src/` answers "nothing imports it" about a
file four modules call on every run. Anything under ``src/`` the walk never arrives at is printed
as dead.

A name can also be reached without an import node - ``importlib.import_module('...')``, a
``QPluginLoader`` path, a string in a spec file - so every unreachable module gets a second
question: does its name appear as a string literal anywhere in the tree, or outside ``src/`` at
all? If it does, it is printed as *named*, not dead, because this checker refuses to call a file
unreachable on evidence it cannot see.

    python -X utf8 tools/check_dead_modules.py            # report
    python -X utf8 tools/check_dead_modules.py --strict   # exit 1 unless every module is live
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Build output and packaged copies of the source are not the tree this checker is asked about;
# reading them would report a module as "named elsewhere" because a frozen exe mentions it.
SKIP = {'__pycache__', '.git', '.venv', 'build', 'dist', 'patch_script', 'visualizations', 'node_modules'}


def module_of(path: Path) -> str:
    """The dotted name a source file answers to, as ``import`` would spell it."""
    rel = path.relative_to(ROOT).with_suffix('')
    parts = list(rel.parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def resolve(name: str, package: str, level: int) -> str:
    """Turn an ``ImportFrom`` into the module it points at.

    ``package`` is the dotted name of the importing file's package and ``level`` is the number
    of leading dots, so ``from ..ui import x`` inside ``src.features.m`` resolves on the same
    rule the interpreter uses.
    """
    if level == 0:
        return name
    base = package.split('.')[:len(package.split('.')) - (level - 1)]
    return '.'.join(base + ([name] if name else []))


def imports_of(path: Path) -> set:
    """Every module name a file's import statements name."""
    tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'), filename=str(path))
    package = module_of(path)
    if path.name != '__init__.py':
        package = package.rpartition('.')[0]
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(resolve(node.module or '', package, node.level))
    return found


def collect(roots):
    """Every module under `src/`, and the subset an import chain from the roots arrives at."""
    all_files = _walked_files()
    paths = {module_of(p): p for p in all_files}
    depth = len(ROOT.parts)
    src_modules = {name: p for name, p in sorted(paths.items()) if p.parts[depth] == 'src'}
    edges = {name: imports_of(path) for name, path in paths.items()}

    reachable = set()
    queue = [module_of(root) for root in roots]
    while queue:
        name = queue.pop()
        if name in reachable:
            continue
        reachable.add(name)
        for dep in edges.get(name, ()):
            if dep in paths:
                queue.append(dep)
            # Importing `src.ui.styles` runs `src/ui/__init__.py` first, so every package on the
            # way is as live as the module inside it. Four of the five packages under `src/` are
            # reached by this loop and by nothing else.
            head = dep
            while '.' in head:
                head = head.rpartition('.')[0]
                if head in paths:
                    queue.append(head)
    return src_modules, reachable, all_files


def _walked_files():
    return [p for p in ROOT.rglob('*.py') if not SKIP.intersection(p.parts)]


def mentions(tail: str, self_path: Path):
    """Files other than the module itself that spell its name as a word.

    A module can be reached without an import node - `importlib.import_module`, a spec-file
    path, a plugin directory - and the graph cannot see any of that, so this is the second
    question the report asks about every unreachable file. It is a hint, not a verdict.
    """
    pattern = re.compile(r'\b' + re.escape(tail) + r'\b')
    here = self_path.resolve()
    hits = []
    for path in _walked_files():
        if path.resolve() == here:
            continue
        if pattern.search(path.read_text(encoding='utf-8', errors='replace')):
            hits.append(path.relative_to(ROOT).as_posix())
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict', action='store_true',
                        help='exit 1 when a module under src/ is unreachable from the roots')
    parser.add_argument('--root', action='append', default=None,
                        help='extra entry-point file, relative to the repository root')
    args = parser.parse_args()

    roots = [ROOT / 'main.py']
    roots += [ROOT / r for r in (args.root or [])]
    missing = [str(r.relative_to(ROOT)) for r in roots if not r.exists()]
    if missing:
        print(f'root not found: {", ".join(missing)}')
        return 2

    src_modules, reachable, all_files = collect(roots)
    dead, named = [], []
    for name, path in src_modules.items():
        if name in reachable:
            continue
        hits = mentions(name.rpartition('.')[2], path)
        (named if hits else dead).append((name, path, hits))

    print(f'files walked: {len(all_files)}; modules under src/: {len(src_modules)}; '
          f'reachable from {len(roots)} root(s): '
          f'{len([n for n in reachable if n in src_modules])} of them')
    for name, path, hits in named:
        print(f'unreached but named elsewhere: {path.relative_to(ROOT).as_posix()} ({name}) '
              f'-> {", ".join(hits[:6])}{" ..." if len(hits) > 6 else ""}')
    for name, path, _ in dead:
        lines = len(path.read_text(encoding='utf-8', errors='replace').splitlines())
        print(f'dead: {path.relative_to(ROOT).as_posix()} ({lines} lines)')
    if not named and not dead:
        print('every module under src/ is reachable by an import from the entry point')
    return 1 if (args.strict and (dead or named)) else 0


if __name__ == '__main__':
    sys.exit(main())
