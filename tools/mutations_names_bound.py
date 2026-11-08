"""Defects to plant in the gate that asks whether a name the app reads is ever bound.

Phase 38 lifted six files' hand-typed folder answers onto ``src/utils/app_paths.py`` calls, and
in ``main.py`` replaced the line that bound ``base_dir`` while leaving the line two below it
reading that name. The app does not start: ``main.py:132`` raises ``NameError`` before a window
exists. Nothing else in the tree could see it - the paths suite reads ``main.py`` as a caller and
its imports and calls were both correct, the 38-suite chain never calls ``main()``, and
``tests/test_clean_exit_contract.py`` imports the module and stops. ``tools/check_names_bound.py``
asks the question with a real scope analyser over the same 74 files
``tools/check_paths_hygiene.py`` walks, and ``tests/test_names_bound_contract.py`` reads it.

Six defects, one line each, in the instrument rather than in the app: the two messages narrowed to
one, the pattern that drops a message, the walk shrunk to a file, the exit code that stops
refusing, and the run that could not start pylint answered as a clean tree twice - the last two
ways being the ones this repo has had to name before, a gate that reports zero because it asked
nothing.

Run:
    python -X utf8 tools/mutation_check.py tests/test_names_bound_contract.py \
        tools/mutations_names_bound.py
( six entries; every one is caught by a named test, and none by killing the suite )
"""

TOOL = 'tools/check_names_bound.py'

MUTATIONS = [
    # ---- what the gate asks ----------------------------------------------------------------
    {
        'file': TOOL,
        'find': "MESSAGES = 'E0601,E0602'",
        'replace': "MESSAGES = 'E0602'",
        'expect': 'test_02_both_shapes_are_reported',
        'note': 'the used-before-assignment half goes, so the name read above the line that binds '
                'it stops being a finding while the gate still prints as though it asked both',
    },
    {
        'file': TOOL,
        'find': r"FINDING = re.compile(r'^(?P<file>.+?):\d+:\d+: E060[12]: (?P<text>.*?) "
                r"\((?P<symbol>[A-Za-z_-]+)\)$')",
        'replace': r"FINDING = re.compile(r'^(?P<file>.+?):\d+:\d+: E0602: (?P<text>.*?) "
                   r"\((?P<symbol>[A-Za-z_-]+)\)$')",
        'expect': 'test_02_both_shapes_are_reported',
        'note': 'the same half lost a different way: pylint is still asked for both messages and '
                'only one kind of answer is read out of its report',
    },

    # ---- what the gate walks ---------------------------------------------------------------
    {
        'file': TOOL,
        'find': '    files = app_files(root)',
        'replace': '    files = app_files(root)[:1]',
        'expect': 'test_01_the_shipped_tree_has_no_name_that_is_not_bound',
        'note': 'the walk shrinks to one file, which is the failure mode a clean answer is most '
                'likely to hide - the count the test pins is what keeps it visible',
    },

    # ---- what the gate answers -------------------------------------------------------------
    {
        'file': TOOL,
        'find': '    return 1 if (args.strict and found) else 0',
        'replace': '    return 0',
        'expect': 'test_03_strict_is_the_exit_code_the_chain_reads',
        'note': 'the gate prints its findings and leaves with success, which is the shape that has '
                'turned a red tree into a passing suite in this repo twice already',
    },
    {
        'file': TOOL,
        'find': "        return len(files), [f'pylint was not run ({type(failed).__name__}: {failed})']",
        'replace': '        return len(files), []',
        'expect': 'test_04_a_gate_that_cannot_ask_says_so_instead_of_reporting_clean',
        'note': 'a run that could not start is reported as a tree with nothing wrong in it, so a '
                'machine without pylint ships an app that may not start',
    },
    {
        'file': TOOL,
        'find': '    except (OSError, subprocess.TimeoutExpired) as failed:',
        'replace': '    except subprocess.TimeoutExpired as failed:',
        'expect': 'test_04_a_gate_that_cannot_ask_says_so_instead_of_reporting_clean',
        'note': 'the missing-interpreter answer is a FileNotFoundError, which is an OSError and so '
                'now leaves the tool as a traceback instead of a verdict',
    },
]
