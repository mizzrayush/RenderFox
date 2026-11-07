"""Report the three shapes that compile, import and then do nothing.

An edit that inserts a method beside `__init__` instead of below it leaves the rest of
the constructor as dead code, and nothing in the tree complains: the file compiles, the
class instantiates, and the pane simply has no widgets. This checker reads the syntax
tree, so it answers one question per file - does any function body continue past the
statement that ends it? - and a yes is always a mistake of that shape.

Two more questions arrived the same way, from defects no other check could see:

A **parked string** is a string written as its own statement below the first line of a
body. Python evaluates it, throws the value away and builds nothing, so the block it
describes - here the Model pane's Presets group, buttons and all - is gone while the file
still reads like it is there. At index 0 of a module, class or function the same shape is
a docstring, which is what makes this a question about position rather than about text.

A **shadowed binding** is a `def` or `class` whose name the same scope already bound.
Python keeps the last one and the earlier never runs, so the pane calls whichever copy
happens to sit lower in the file. A rebind with decorators is legitimate and is left
alone: `@property` and `@x.setter` share a name on purpose, and flagging those would bury
the real answer under a dozen pairs.

    python tools/check_unreachable_code.py            # src, tools, tests
    python tools/check_unreachable_code.py src/ui     # one subtree
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

EXITS = (ast.Return, ast.Raise)
SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
DEF_LIKE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
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


def parked_text(statement: ast.stmt, index: int) -> str | None:
    """The opening words of a string statement that is not the body's docstring, else None.

    Index 0 of a module, class or function is the docstring slot, so only a plain constant there
    is a description. An f-string is never a docstring - `__doc__` stays None - so it is parked
    whatever its position, and a block of it that reads like a docstring builds nothing either.
    """
    if not isinstance(statement, ast.Expr):
        return None
    value = getattr(statement, 'value', None)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        if index == 0:
            return None
        return ' '.join(value.value.split())[:48]
    if isinstance(value, ast.JoinedStr):
        words = ''.join(part.value if isinstance(part, ast.Constant) else '{...}'
                        for part in value.values)
        return 'f"' + ' '.join(words.split())[:44]
    return None


def parked_strings(tree: ast.AST) -> list[tuple[int, int, str]]:
    """Every (line, column, opening words) string statement that is not a docstring."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, SCOPES):
            continue
        for index, statement in enumerate(node.body):
            words = parked_text(statement, index)
            if words is None:
                continue
            found.append((statement.lineno, statement.col_offset, words))
    return found


def shadowed_bindings(tree: ast.AST) -> list[tuple[int, int, str, str]]:
    """Every (line, earlier line, kind, name) the same scope binds a second time plainly.

    A decorated rebind is a property setter or a registered overload and is left alone; only a
    second binding carrying no decorators is a name Python silently threw away.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, SCOPES):
            continue
        bound: dict[str, ast.AST] = {}
        for statement in node.body:
            if not isinstance(statement, DEF_LIKE):
                continue
            earlier = bound.get(statement.name)
            if earlier is not None and not statement.decorator_list:
                found.append((statement.lineno, earlier.lineno,
                              type(statement).__name__, statement.name))
            bound[statement.name] = statement
    return found


def files_in(targets: list[Path]) -> list[Path]:
    paths = []
    for target in targets:
        if target.is_file():
            paths.append(target)
        else:
            paths.extend(sorted(target.rglob('*.py')))
    return paths


def scan(paths: list[Path]) -> list[tuple[str, int, str]]:
    """Every (file, line, message) the three questions answer yes to."""
    offenders = []
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as problem:
            offenders.append((str(path), 0, f'unreadable: {problem}'))
            continue
        for line, _col, name, kind in dead_tails(tree):
            offenders.append((str(path), line,
                              f'{name} continues after its exit with a {kind}'))
        for line, _col, words in parked_strings(tree):
            offenders.append((str(path), line, f'parked string, not a docstring: "{words}"'))
        for line, earlier, kind, name in shadowed_bindings(tree):
            offenders.append((str(path), line,
                              f'{kind} {name}() rebinds :{earlier} with no decorators, '
                              f'so the earlier one never runs'))
    return offenders


def main(paths: list[str]) -> int:
    """Read the named files or directories and return the exit code the chain should see.

    `paths` is the list of targets themselves, not `sys.argv`: a caller that handed over one
    directory must not have it read as the program name and fall back to the default roots,
    which would report the app instead of the sample it was asked about.
    """
    root = Path(__file__).resolve().parent.parent
    targets = [Path(a) for a in paths] or [root / name for name in DEFAULT_ROOTS]
    offenders = scan(files_in(targets))
    for path, line, message in offenders:
        print(f'{path}:{line}: {message}')
    if offenders:
        print(f'\n{len(offenders)} statement(s) build nothing: a tail past an exit, a string '
              f'parked below the docstring slot, or a name bound twice in one scope.')
        return 1
    print('No body continues past its exit, no string is parked below the docstring slot, '
          'and no name is bound twice in one scope.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
