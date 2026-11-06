"""Report statements that sit after an unconditional exit in a function body.

An edit that inserts a method beside `__init__` instead of below it leaves the rest of
the constructor as dead code, and nothing in the tree complains: the file compiles, the
class instantiates, and the pane simply has no widgets. This checker reads the syntax
tree, so it answers one question per file - does any function body continue past the
statement that ends it? - and a yes is always a mistake of that shape.

    python tools/check_unreachable_code.py            # src, tools, tests
    python tools/check_unreachable_code.py src/ui     # one subtree
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

EXITS = (ast.Return, ast.Raise)
DEFAULT_ROOTS = ('src', 'tools', 'tests')


def dead_tails(tree: ast.AST) -> list[tuple[int, int, str, str]]:
    """Every (line, column, function, first statement) that follows an exit in a body."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for index, statement in enumerate(node.body[:-1]):
            if not isinstance(statement, EXITS):
                continue
            tail = node.body[index + 1]
            found.append((tail.lineno, tail.col_offset, node.name,
                          type(tail).__name__))
    return found


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    targets = [Path(a) for a in argv[1:]] or [root / name for name in DEFAULT_ROOTS]
    offenders = []
    for target in targets:
        paths = [target] if target.is_file() else sorted(target.rglob('*.py'))
        for path in paths:
            if '__pycache__' in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            except (SyntaxError, UnicodeDecodeError) as problem:
                offenders.append((path, 0, f'unreadable: {problem}'))
                continue
            for line, _col, name, kind in dead_tails(tree):
                offenders.append((path, line, f'{name} continues after its exit with a {kind}'))
    for path, line, message in offenders:
        print(f'{path}:{line}: {message}')
    if offenders:
        print(f'\n{len(offenders)} statement(s) sit after the line that ends their function.')
        return 1
    print('No function body continues past a statement that ends it.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
