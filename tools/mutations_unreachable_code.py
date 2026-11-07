"""Defects to plant in the three questions the checker asks, one line at a time.

Two defect classes reached this app and no runtime check could see them. The Model pane's
Presets group was a string statement below the first line of a builder - valid Python, no
widgets - and the viewer carried two `set_render_mode` methods, two `set_use_vertex_colors`
and a `check_integrity` that scanned the database under an alias that answered it, because a
`def` whose name the same scope already bound is a function that never exists. Neither makes
the file stop compiling, so `tools/check_unreachable_code.py` reads the syntax tree for them
alongside the dead tail it already knew about.

A checker is only a claim until something breaks it, so each entry below is one line of the
checker or one shape in a real product file: a detector emptied so that the answer is always
"clean", the position rule dropped so that a docstring is an offence, the decorator rule
dropped so that a property and its setter are, the scope kinds narrowed so that a rebinded
class is invisible, the roots narrowed so that half the app goes unread, and each of the
three messages reworded out of the sentence the reader is meant to act on. The last three
entries plant the shapes themselves in `src/ui/model_tab.py`, because the whole-tree answer of
"nothing" is only worth anything if the reading would have said otherwise. The one entry that
plants the command's own handoff is a defect the checker had before this suite read it: a target
named on the command line was discarded and the app answered for it.

`expect` is a substring of a test name in tests/test_unreachable_code_checker.py; each resolves
to exactly one test. The suite parses files and never imports them, so a planted product defect
is reported rather than run.

Run:
    python -X utf8 tools/mutation_check.py tests/test_unreachable_code_checker.py \
        tools/mutations_unreachable_code.py
( twenty-four entries )
"""

MUTATIONS = [
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '        for index, statement in enumerate(node.body[:-1]):',
        'replace': '        for index, statement in enumerate([]):',
        'expect': 'test_01',
        'note': 'the dead-tail question emptied: a body that continues past its exit is the '
                'shape the checker was written for, and it now answers it never happens',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '            if not isinstance(statement, EXITS):',
        'replace': '            if False:',
        'expect': 'test_02',
        'note': 'every statement becomes an exit, so a function that returns in one branch and '
                'after the if in another is reported as dead code',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '        for index, statement in enumerate(node.body):',
        'replace': '        for index, statement in enumerate([]):',
        'expect': 'test_03',
        'note': 'the parked-string question emptied, which is the question that would have '
                'found the Presets group before it shipped',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': "    if isinstance(value, ast.Constant) and isinstance(value.value, str):",
        'replace': '    if False:',
        'expect': 'test_03',
        'note': 'plain strings no longer count, so only an f-string block is still seen and the '
                'shape that actually occurred is invisible',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '        if index == 0:',
        'replace': '        if False:',
        'expect': 'test_04',
        'note': 'the docstring slot stops being a slot: every documented module, class and '
                'function in the app is suddenly an offence',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '    if isinstance(value, ast.JoinedStr):',
        'replace': '    if False:',
        'expect': 'test_06',
        'note': 'a parked f-string is the same no-op with an expression in it, and dropping the '
                'branch lets the one the docstring slot cannot hold slip through',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '    if not isinstance(statement, ast.Expr):',
        'replace': '    if False:',
        'expect': 'test_05',
        'note': 'a returned or assigned string is not a statement, and without that test the '
                'checker reports honest code as dead',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '        for statement in node.body:',
        'replace': '        for statement in []:',
        'expect': 'test_07',
        'note': 'the shadow question emptied: the two `set_render_mode` methods were the answer '
                'it exists to give',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '            if earlier is not None and not statement.decorator_list:',
        'replace': '            if False:',
        'expect': 'test_07',
        'note': 'nothing is ever a shadow, so the duplicate binding goes back into the tree',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '            if earlier is not None and not statement.decorator_list:',
        'replace': '            if earlier is not None:',
        'expect': 'test_08',
        'note': 'the decorator rule is what keeps `@property` and `@x.setter` out of the report; '
                'without it the checker buries the real answer under a dozen legitimate pairs',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': 'DEF_LIKE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)',
        'replace': 'DEF_LIKE = (ast.FunctionDef, ast.AsyncFunctionDef)',
        'expect': 'test_07',
        'note': 'a rebinded class stops being a shadow, which is the shape two pane copies of '
                'the same widget take',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': 'SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)',
        'replace': 'SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)',
        'expect': 'test_07',
        'note': 'class bodies go unread, and both the parked block and the duplicate method the '
                'app actually had sit inside one',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': "DEFAULT_ROOTS = ('src', 'tools', 'tests')",
        'replace': "DEFAULT_ROOTS = ('src', 'tools')",
        'expect': 'test_10',
        'note': 'the reading silently loses a root, and a checker that reads less still prints '
                'the same confident sentence',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': "            paths.extend(sorted(target.rglob('*.py')))",
        'replace': '            paths.extend([])',
        'expect': 'test_10',
        'note': 'a directory target contributes no files, so the whole-tree answer is computed '
                'over nothing',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': "                              f'{name} continues after its exit with a {kind}'))",
        'replace': "                              f'{name} has a {kind} in it'))",
        'expect': 'test_13',
        'note': 'the line stops naming the exit, so a reader cannot tell an unreachable tail '
                'from any other statement',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': "            offenders.append((str(path), line, f'parked string, not a docstring: \"{words}\"'))",
        'replace': "            offenders.append((str(path), line, f'string: \"{words}\"'))",
        'expect': 'test_13',
        'note': 'the report stops saying which of the two a string statement is, and the reader '
                'has to re-derive the docstring rule from the line number',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': "                              f'{kind} {name}() rebinds :{earlier} with no decorators, '",
        'replace': "                              f'{kind} {name}() appears, '",
        'expect': 'test_13',
        'note': 'the earlier binding is the half that tells you which copy is dead',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '        return 1',
        'replace': '        return 0',
        'expect': 'test_13',
        'note': 'the command prints the offences and exits as if it had found none, so a chain '
                'that reads the exit code calls it clean',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': "        print(f'\\n{len(offenders)} statement(s) build nothing: a tail past an exit, a string '",
        'replace': "        print(f'\\n{len(offenders)} offenders: '",
        'expect': 'test_13',
        'note': 'the summary stops naming the three shapes, which is what makes one line of '
                'output enough to act on',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': "    print('No body continues past its exit, no string is parked below the docstring slot, '",
        'replace': "    print('The reading found nothing worth reporting, '",
        'expect': 'test_13',
        'note': 'the clean answer stops saying which three questions were asked, so a narrowed '
                'reading is indistinguishable from a clean app',
    },
    {
        'file': 'tools/check_unreachable_code.py',
        'find': '    sys.exit(main(sys.argv[1:]))',
        'replace': '    sys.exit(main(sys.argv))',
        'expect': 'test_14',
        'note': 'the handoff bug the suite found in the checker itself: with the program name in '
                'the list, the one target a caller named is dropped and the app is read instead',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '    def apply_debug_preset(self):',
        'replace': '    def apply_wireframe_preset(self):',
        'expect': 'test_11',
        'note': 'the duplicate-method shape put back into the pane that had it: two bindings of '
                'one name, the first never reachable',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.shader_list.setCurrentRow(1) # Default to Shaded',
        'replace': '        "Default to Shaded"',
        'expect': 'test_11',
        'note': 'the parked-string shape put back where the Presets group was parked: a line of '
                'the builder replaced by prose about it',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        presets_group.setLayout(presets_layout)',
        'replace': '        return widget',
        'expect': 'test_11',
        'note': 'the dead-tail shape put back where an edit once inserted a method beside the '
                'builder: the rest of the pane stops being built',
    },
]
