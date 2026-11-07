"""Who reads what the app writes, and does the name it uses exist?

The shipped build is packaged with ``console=False`` (`RenderFox.spec:29`), so the process
has no console: a write to stdout or stderr goes where nobody can read it. Six questions follow
from that sentence, and this checker asks one of each, over the 71 files the app ships.

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

**Rule 4 is the same defect everywhere else.** Ninety-three stream writes sat outside a module's
own ``if __name__ == "__main__":`` block at the start of this phase - a failure caught, described,
and written into the closed stream, or a shader that did not compile, or a milestone in a batch.
Eighty-eight of them had no reader at all. Each one is a record now: the tree writes 238 of them,
from 33 of the 71 app files where it wrote 151 from 16, and what this rule reports is none. A rule
scoped only to `except` handlers would have let the shader and texture lines stay invisible, and
would not have stopped the backlog growing in a branch that has no handler.

An exemption is matched by the text of the line, not by its number, because edits above it
move numbers and a rule keyed to numbers silently stops covering anything. An exemption that
matches no line is itself reported (`stale-exemption`): a guard whose exception no longer
applies is the widest blind spot it can have.

**Rule 5 asks whether a record that reaches the channel can reach a row.** Two answers are
readable from the source. A call whose literal message and its arguments disagree -
``logger.info("wrote %d files")`` with nothing to fill the slot, or one argument too many -
raises inside `logging` at emit time, and `Handler.handleError` writes the complaint to stderr:
the report is gone and the only thing left is the part that cannot be read. And
``logging.warning(...)`` on the module *is* the root logger, so the record it makes is named
`root` and the component column tells a reader nothing about which module failed.

**Rule 6 reads the sentence itself.** A row of the table is text next to a level and a component:
it has no colour for a warning and no icon for a success, so a status glyph written into the
message is the interface leaking into the log. Fourteen of them were - ``"✅ CLIP model loaded
successfully!"`` and its siblings, in the AI tagger alone - and the word that means the same thing
costs the same to type, so a record whose own text needs a non-ASCII character is a finding.

**What this checker cannot see is written down so it is not mistaken for clean.**

* A record with no handler on the root logger is not dropped quietly: Python's `lastResort`
  writes it to stderr, which `console=False` discards like any other write. Five reports in
  `main.py` are written before `MainWindow()` builds the pane whose `setup_logging` attaches the
  handler, and `src/features/ai_asset_tagger.py` writes one while it is being imported.
  `src/utils/early_log.py` is the queue that holds those until the pane plays them back; a
  record logged before `install()` runs is still lost, which is why it is the first statement
  in `main()`.
* The level a record carries is decided in `main.py`, not here. It sets INFO on the app's own
  namespaces and leaves the root logger at WARNING, so a dependency cannot fill the table. The
  split the app uses: `warning` for a failure it caught and still answered (102 sites), `error`
  for one that left its own records or state wrong (68), `info` for progress (60), `debug` for
  per-item chatter, which stays below the floor on purpose (6), and `logger.exception` where a
  traceback is the report (2).
* Whether the row the record becomes is *readable* is the pane's contract, and
  `tests/test_stdout_quiet_contract.py` executes it: the level filter is a floor rather than an
  equality, and the component list is built from what arrived rather than a fixed list of names
  no emitter has ever had.

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
# record on the channel the Diagnostics pane owns, whatever becomes of its level - and its level
# is decided by `main.py`, which opens the app's own namespaces to INFO and leaves the root logger
# at WARNING, so a DEBUG record is dropped before it reaches any handler today. Six sites are
# written at that level on purpose; `tests/test_stdout_quiet_contract.py` pins the two levels.
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

# Rule 4. A stream write that has a reader, matched by (file, a fragment of the line's own text).
# Numbers would move under any edit above them and take the coverage with them.
VISIBLE_WRITES = (
    ('main.py', 'CRITICAL ERROR',
     'the last-resort reporter, which cannot depend on the logging machinery it may be '
     'reporting on; the same handler shows the traceback in a dialog'),
    ('main.py', 'Models downloaded successfully',
     "the installer's headless mode (installer.nsi:133 runs the console-less exe with "
     "--download-models and never builds a window), where the dialog and the exit code are "
     'the answer'),
    ('main.py', 'Model download cancelled or failed',
     'the same headless mode, the other way it ends'),
    ('main.py', 'Error launching downloader',
     'the same headless mode, and the one branch whose whole answer is the `sys.exit` below it: '
     '`installer.nsi:133` waits for the process and reads no code from it, so this line is '
     'narration beside a contract rather than the report itself'),
    ('src/processing/script_engine.py', '[{level}] {message}',
     "the scripting console's own line: ScriptExecutor.run swaps sys.stdout for a StringIO "
     'and emits what the script wrote (script_engine.py:332), so this write is read back by '
     'the Scripting pane'),
)


# Rule 5. The two ways a record reaches no row once it is on the channel.
LEVEL_CALLS = frozenset({'debug', 'info', 'warning', 'error', 'critical', 'exception', 'log'})

# One slot of a `%`-style format string. `%%` is matched as its own alternative so a literal
# percent in the text is never counted as a slot - which is the difference between "the message
# has two slots" and "the message has four", in a line that ends `(%.1f%% reduction)` twice.
# `%*d` and `%(key)s` are not matched at all, and a format string holding either is left alone
# because its arity is not a number this can read.
FORMAT_SLOT = re.compile(
    r'(?P<escape>%%)|(?P<type>%[-+ #0]*[0-9]*(?:\.[0-9]+)?[diouxXeEfFgGcrsa])')


# Rule 6. A row of the Diagnostics table is text, in a monospace list, next to a level and a
# component: it has no colour for a warning and no icon for a success, so a status glyph smuggled
# into the sentence is the app's UI leaking into its log. Fourteen of them were written this way
# by the AI tagger alone ("✅ CLIP model loaded successfully!"), which is why the rule reads the
# whole message rather than the first character. A sentence that needs the glyph needs a word.
NON_ASCII = re.compile(r'[^\x00-\x7f]')


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


def _main_string(node) -> bool:
    return isinstance(node, ast.Constant) and node.value == '__main__'


def _main_guard_spans(tree) -> list:
    """Line ranges held by a module's own ``if __name__ == "__main__":`` block.

    The packaged app never reaches one: PyInstaller runs `main.py`, and a library module's
    guard only fires when a developer runs that file by hand - in a console that exists. Those
    six writes are the app's smoke tests, so they are exempt by their position in the tree
    rather than by their text. Only a direct child of the module counts: a guard written
    inside a function is not a hand-run block, and the exemption must not reach that far.
    """
    spans = []
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Compare) and len(test.comparators) == 1
                and isinstance(test.left, ast.Name) and test.left.id == '__name__'
                and _main_string(test.comparators[0])):
            continue
        start = min([getattr(c, 'lineno', node.lineno) for c in ast.walk(node)] or [node.lineno])
        end = max([getattr(c, 'end_lineno', getattr(c, 'lineno', node.lineno))
                   for c in ast.walk(node)] or [node.end_lineno])
        spans.append((start, end))
    return spans


def stream_writes_with_source(path: Path):
    """The same calls, each with the line of source it is written on.

    Rule 4 exempts by text rather than by number, so it needs the text the parse tree throws
    away. A multi-line call is keyed to the line holding its ``print(``, which is the line an
    exemption fragment has to appear on.
    """
    lines = _source(path).splitlines()
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    guards = _main_guard_spans(tree)
    out = []
    for node in ast.walk(tree):
        if _is_print_like(node):
            text = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ''
            in_guard = any(start <= node.lineno <= end for start, end in guards)
            out.append((node.lineno, text, in_guard))
    return out


def _relative(path: Path) -> str:
    return (path.relative_to(ROOT).as_posix()
            if path.is_absolute() and ROOT in path.parents else path.as_posix())


def invisible_writes(path: Path):
    """Rule 4: ``(line, detail)`` for every stream write in an app file that has no reader.

    Returns the findings *and* the exemptions this file used, so an exemption that matches
    nothing is reported instead of quietly becoming a gap in the rule.
    """
    rel = _relative(path)
    used = set()
    findings = []
    for line, text, in_main_guard in stream_writes_with_source(path):
        if in_main_guard:
            continue
        holder = next((key for key in VISIBLE_WRITES
                       if key[0] == rel and key[1] in text), None)
        if holder:
            used.add(holder)
            continue
        findings.append((line, 'writes to the stream the packaged build has no reader for'))
    return findings, used


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


def _logger_call(node) -> tuple:
    """``(level, is_root_call)`` for a log call, or None when this is not one.

    Two shapes reach the channel: ``logger.warning(...)`` on a name that rule 3 has already
    checked exists, and ``logging.warning(...)`` on the module, which is the root logger itself.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    if func.attr not in LEVEL_CALLS:
        return None
    if func.value.id == 'logging':
        return func.attr, True
    if func.value.id.endswith('logger'):
        return func.attr, False
    return None


def unformattable_records(path: Path):
    """Rule 5a: ``(lineno, detail)`` where a literal format string and its arguments disagree.

    `logging` interpolates at emit time, and when that raises it hands the failure to
    `Handler.handleError`, which writes to stderr - the stream this checker already refuses. So a
    call with the wrong number of arguments is worse than the `print` it replaced: it reports
    nothing, and the one thing it does write is the part that cannot be read.
    """
    found = []
    tree = ast.parse(_source(path), filename=str(path))
    for node in ast.walk(tree):
        call = _logger_call(node)
        if call is None or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        text = first.value
        if '%(' in text or '%*' in text:
            continue
        want = len([m for m in FORMAT_SLOT.finditer(text) if m.group('type')])
        have = len(node.args) - 1
        if want != have:
            found.append((node.lineno,
                          f'a {want}-slot message handed {have} argument(s): the record is '
                          'dropped when it is formatted'))
    return found


def root_logger_calls(path: Path):
    """Rule 5b: ``(lineno, detail)`` for a record written on the root logger by name.

    `logging.warning(...)` is the root logger, so the record it makes is named `root`, and the
    component the Diagnostics table shows for it is `root` - which tells a reader nothing about
    which module failed. `logging.getLogger(__name__)` costs one line and the row keeps its name.
    """
    found = []
    tree = ast.parse(_source(path), filename=str(path))
    for node in ast.walk(tree):
        call = _logger_call(node)
        if call and call[1]:
            found.append((node.lineno,
                          f'`logging.{call[0]}` writes a record named `root`, so the row has no '
                          'component to filter or read'))
    return found


def _message_literals(call: ast.Call) -> list:
    """The literal text a log message is built from, f-string parts included."""
    if not call.args:
        return []
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return [first.value]
    if isinstance(first, ast.JoinedStr):
        return [v.value for v in first.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return []


def glyph_in_record(path: Path):
    """Rule 6: ``(lineno, detail)`` for a record whose own sentence carries a glyph."""
    found = []
    tree = ast.parse(_source(path), filename=str(path))
    for node in ast.walk(tree):
        if _logger_call(node) is None:
            continue
        for text in _message_literals(node):
            hit = NON_ASCII.search(text)
            if hit:
                found.append((node.lineno,
                              f'the sentence needs {hit.group(0)!r}; a row is text and the word '
                              'that means it costs the same to type'))
    return found


def scan(paths):
    """Every rule, over the given files: ``[(file, rule, lineno, detail), ...]``."""
    found = []
    used = set()
    walked = set()
    for path in paths:
        rel = _relative(path)
        walked.add(rel)
        for line, _text in debug_traces(path):
            found.append((rel, 'debug-trace', line, 'a DEBUG trace written to a stream the build discards'))
        for line, detail in paint_path_writes(path):
            found.append((rel, 'paint-path', line, detail))
        for line in unresolved_logger_uses(path):
            found.append((rel, 'logger-name', line,
                          '`logger` is used but bound in neither the module nor the function'))
        invisible, exemptions = invisible_writes(path)
        used |= exemptions
        for line, detail in invisible:
            found.append((rel, 'stream-write', line, detail))
        for line, detail in unformattable_records(path):
            found.append((rel, 'unformattable', line, detail))
        for line, detail in root_logger_calls(path):
            found.append((rel, 'root-logger', line, detail))
        for line, detail in glyph_in_record(path):
            found.append((rel, 'glyph-in-record', line, detail))
    for entry in VISIBLE_WRITES:
        if entry[0] in walked and entry not in used:
            found.append((entry[0], 'stale-exemption', 0,
                          f'no stream write matches {entry[1]!r} any more, so this exemption '
                          f'covers nothing ({entry[2]})'))
    return found


def total_stream_writes(paths):
    """``(total, in_a_hand_run_block, named_exempt, unreadable)`` over the given files."""
    total = guard = named = unreadable = 0
    for path in paths:
        rows = stream_writes_with_source(path)
        total += len(rows)
        rel = _relative(path)
        for _line, text, in_guard in rows:
            if in_guard:
                guard += 1
            elif any(key[0] == rel and key[1] in text for key in VISIBLE_WRITES):
                named += 1
            else:
                unreadable += 1
    return total, guard, named, unreadable


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
    counts = {'debug-trace': 0, 'paint-path': 0, 'logger-name': 0,
              'stream-write': 0, 'stale-exemption': 0,
              'unformattable': 0, 'root-logger': 0, 'glyph-in-record': 0}
    for _rel, rule, _line, _detail in found:
        counts[rule] += 1
    total, guard, named, unreadable = total_stream_writes(paths)
    print(f'files checked: {len(paths)}; debug traces: {counts["debug-trace"]}; '
          f'writes from a repaint: {counts["paint-path"]}; unresolved `logger`: {counts["logger-name"]}; '
          f'writes with no reader: {counts["stream-write"]}; records that cannot be formatted: '
          f'{counts["unformattable"]}; records named `root`: {counts["root-logger"]}; '
          f'sentences that need a glyph: {counts["glyph-in-record"]}')
    print(f'stream writes in app scope: {total} = {unreadable} with no reader + {named} named '
          f'exempt + {guard} inside a hand-run `__main__` block')
    for rel, rule, line, detail in found:
        print(f'{rule}: {rel}:{line} {detail}')
    if not found:
        print('nothing is written to a stream from the paint path, no DEBUG trace remains, every '
              'log call names a logger that exists, every record on it can be formatted and '
              'carries a component, and every other stream write is one of the exempt lines that '
              'has a reader')
    return 1 if (args.strict and found) else 0


if __name__ == '__main__':
    sys.exit(main())
