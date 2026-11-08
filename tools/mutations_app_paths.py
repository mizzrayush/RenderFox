"""Defects to plant in the one module that answers "where does this file go?", one line at a time.

Phase 38 measured the shipped tree against an installed machine: ``installer.nsi:20`` puts
RenderFox in ``C:\\Program Files\\RenderFox`` and that folder grants ``BUILTIN\\Users`` read and
execute, so the nine paths built from the app's own folder or from ``os.getcwd()`` - the
237-model library index, its thumbnails, generated textures, the script store, crash records,
version snapshots and the queue's ``config.json`` - resolved where the person who installed the
app cannot write. ``src/utils/app_paths.py`` is now the only file allowed to answer, and
``tools/check_paths_hygiene.py`` is what keeps it that way.

Both are instruments, so both get defects planted in them. A reader nobody can break is not
evidence: the probe that distinguishes "the folder is there" from "the folder takes a file" is
one ``if`` deep inside ``output_dir``, the reason a folder moved is a string a pane may or may
not read, and each of the checker's five rules is a pattern list that can be emptied without
changing a single test's green answer - which is exactly why
``tests/test_app_paths_contract.py`` counts the fixture's violations per rule by hand.

Two lines are deliberately absent from this list. ``app_root``'s and ``bundled``'s
``getattr(sys, 'frozen', False)`` branches both answer the same folder in a source tree, and
faking the flag in-process would need a test-only branch in the reader - so they are checked by
running the packaged executable, which is the rest of this phase.

Run:
    python -X utf8 tools/mutation_check.py tests/test_app_paths_contract.py \
        tools/mutations_app_paths.py
( fifty-three entries; every one is caught by a named test, and none by killing the suite )
"""

AP = 'src/utils/app_paths.py'
CHECKER = 'tools/check_paths_hygiene.py'

MUTATIONS = [
    # ---- app_root(): whose folder is the app's ----------------------------------------------
    {
        'file': AP,
        'find': '    if override:',
        'which': 1,
        'replace': '    if False:',
        'expect': 'test_02',
        'note': 'RENDERFOX_APP_ROOT is ignored, so no suite can ask what the app does when its '
                'own folder is read-only and both branches collapse into one',
    },
    {
        'file': AP,
        'find': '    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))',
        'replace': '    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))',
        'expect': 'test_01',
        'note': 'the project folder is two levels up instead of three, which is the exact value '
                'the Settings pane used to default to - src, not the checkout or the install',
    },

    # ---- data_dir(): the profile, and only the profile --------------------------------------
    {
        'file': AP,
        'find': "DATA_OVERRIDE = 'RENDERFOX_DATA_DIR'",
        'replace': "DATA_OVERRIDE = 'RENDERFOX_PROFILE_DIR'",
        'expect': 'test_06',
        'note': "the override is renamed, so every suite that already sets RENDERFOX_DATA_DIR "
                'writes into the real profile of the machine it runs on',
    },
    {
        'file': AP,
        'find': "                 or os.path.join(os.path.expanduser('~'), '.renderfox'))",
        'replace': "                 or os.path.join(app_root(), '.renderfox'))",
        'expect': 'test_13',
        'note': 'with nothing pointed at it, state lands inside the program folder - which is '
                'the one thing this phase exists to stop',
    },

    # ---- output_dir(): the candidate, the probe, the fallback, the reason -------------------
    {
        'file': AP,
        'find': '    if override:',
        'which': 2,
        'replace': '    if False:',
        'expect': 'test_05',
        'note': 'RENDERFOX_OUTPUT_DIR is dropped on the floor, so an explicit instruction is '
                'answered with a guessed folder instead',
    },
    {
        'file': AP,
        'find': '        return _make(override)',
        'replace': '        return override',
        'expect': 'test_05',
        'note': 'the explicit folder is answered without being made, so the first write into it '
                'fails with a FileNotFoundError naming a path the person was told to use',
    },
    {
        'file': AP,
        'find': '        if _takes_files(candidate):',
        'replace': '        if os.path.isdir(candidate):',
        'expect': 'test_03',
        'note': 'existence read as writability - the install that once ran as administrator '
                'keeps its read-only output folder and every thumbnail after that fails',
    },
    {
        'file': AP,
        'find': '    except OSError as failed:',
        'replace': '    except PermissionError as failed:',
        'expect': 'test_04',
        'note': 'the clause narrows to the error anybody thought of: a name in the way raises '
                'FileExistsError, which is not a PermissionError, and it escapes out of the pane',
    },
    {
        'file': AP,
        'find': "               f'so the app\\'s files go under {data_dir()} instead')",
        'replace': "               'so the app\\'s files go somewhere else instead')",
        'expect': 'test_03',
        'note': 'the reason names the folder that refused and not the one that took over, so a '
                'person reading it still cannot find their library',
    },
    {
        'file': AP,
        'find': "    return _make(os.path.join(data_dir(), 'output'))",
        'replace': "    return _make(os.path.join(app_root(), 'output'))",
        'expect': 'test_04',
        'note': 'the fallback is the folder that just refused, so the second launch fails the '
                'same way the first one did and the reason printed above it is a lie',
    },
    {
        'file': AP,
        'find': '    return _reason',
        'replace': "    return ''",
        'expect': 'test_03',
        'note': 'the folder moves and nothing is left to read, which is how an installed build '
                'reports 0 models for a library the person cannot see',
    },

    # ---- _takes_files(): the probe itself ---------------------------------------------------
    {
        'file': AP,
        'find': '        os.remove(probe)',
        'replace': '        pass',
        'expect': 'test_02',
        'note': 'the probe leaves its own file in the folder it just tested, where the library '
                'pane indexes it as a model and the next Clear Thumbnails has to delete it',
    },
    {
        'file': AP,
        'find': "        return False",
        'replace': "        pass",
        'expect': 'test_03',
        'note': 'a refused open answers yes, because the fall-through is the success path - '
                'the whole point of the probe, gone in one word',
    },
    {
        'file': AP,
        'find': "    probe = os.path.join(path, f'.writable-{os.getpid()}')",
        'replace': "    probe = os.path.join(path, '.writable')",
        'expect': 'test_03',
        'note': "the probe's name drifts off the pid, so a refusal planted at the name the "
                'reader actually writes to stops being a refusal it can see',
    },
    {
        'file': AP,
        'find': '    _reason = \x27\x27',
        'replace': '    pass',
        'expect': 'test_03',
        'note': 'reset() forgets nothing, so the reason an earlier question left behind is '
                'read as this run\'s answer - and a suite can never ask again',
    },

    # ---- state_file(): a file both sides have to be able to reach ----------------------------
    {
        'file': AP,
        'find': '    beside = os.path.join(app_root(), name)',
        'replace': '    beside = os.path.join(os.getcwd(), name)',
        'expect': 'test_07',
        'note': 'the copy beside the app is looked for in whatever directory the app was started '
                'from, which is the defect rule 1 exists to refuse and this file is exempt from',
    },
    {
        'file': AP,
        'find': '    return beside if os.path.isfile(beside) else os.path.join(data_dir(), name)',
        'replace': '    return os.path.join(data_dir(), name)',
        'expect': 'test_07',
        'note': 'a copy that already exists is ignored, so this machine loses its configured '
                'engine and, through the same line, the tags in config/asset_tags.json',
    },
    {
        'file': AP,
        'find': '    return beside if os.path.isfile(beside) else os.path.join(data_dir(), name)',
        'replace': '    return beside',
        'expect': 'test_07',
        'note': 'the profile branch goes away, so an install that cannot write in its own folder '
                'is told to write there anyway - the PermissionError this phase started from',
    },
    {
        'file': AP,
        'find': '    return beside if os.path.isfile(beside) else os.path.join(data_dir(), name)',
        'replace': '    return beside if os.path.isfile(beside) else os.path.join(data_dir(), CONFIG_NAME)',
        'expect': 'test_17',
        'note': "the fallback forgets the caller's own name and saves config.json under the "
                'profile, so the tags file and the settings file become the same file',
    },
    {
        'file': AP,
        'find': '    return state_file(CONFIG_NAME)',
        'replace': '    return os.path.join(data_dir(), CONFIG_NAME)',
        'expect': 'test_07',
        'note': 'config_path() stops asking the general question, so the settings copy beside the '
                'checkout is no longer the one the queue reads after the first launch',
    },

    # ---- bundled(): the file the build ships ------------------------------------------------
    {
        'file': AP,
        'find': '    return os.path.join(app_root(), name)',
        'replace': '    return os.path.join(os.getcwd(), name)',
        'expect': 'test_08',
        'note': 'USER_GUIDE.md is looked for in whatever directory the app was started from, '
                'which is how the installed Help pane came up with nothing',
    },

    # ---- the modules that used to answer for themselves -------------------------------------
    {
        'file': 'src/features/automation_engine.py',
        'find': '    return data_dir()',
        'replace': "    return os.path.join(os.path.expanduser('~'), '.renderfox')",
        'expect': 'test_06',
        'note': 'the delegation goes back to a hand-spelled profile, so RENDERFOX_DATA_DIR stops '
                'reaching tasks and workflows and a suite appends to this machine',
    },
    {
        'file': 'src/features/performance_analyzer.py',
        'find': '    return _app_data_dir()',
        'replace': "    return os.path.expanduser('~')",
        'expect': 'test_06',
        'note': 'the benchmark history loses the app folder of its own name and is written '
                'beside every other file the account owns',
    },
    {
        'file': 'src/ui/settings_tab.py',
        'find': "                with open(location, 'r', encoding='utf-8') as f:",
        'replace': "                with open('config.json', 'r', encoding='utf-8') as f:",
        'expect': 'test_09',
        'note': 'a caller opens the settings file by a bare name again, which is the shape rule '
                '4 refuses - the checker is the only test that can see it from a pane',
    },
    {
        'file': 'src/ui/model_tab.py',
        'find': '        self.library_path = library_path or output_dir()',
        'replace': '        self.library_path = library_path or os.path.join(os.getcwd(), \'output\')',
        'expect': 'test_09',
        'note': 'the library pane builds the output folder by hand again, so it cannot ask the '
                'question the reader asks and the Versions pane writes where the index is not',
    },

    # ---- the checker: scope -----------------------------------------------------------------
    {
        'file': CHECKER,
        'find': '    return sorted(src + ([entry] if entry.exists() else []))',
        'replace': '    return sorted([entry] if entry.exists() else [])',
        'expect': 'test_09',
        'note': 'the walk drops src/ and keeps only the entry point: one file, no violations, '
                'and a clean answer over 200,000 lines nobody read',
    },
    {
        'file': CHECKER,
        'find': "HOME = 'app_paths.py'",
        'replace': "HOME = 'run_teardown.py'",
        'expect': 'test_09',
        'note': 'the exemption names a different module, so the reader is reported for the '
                'answers it exists to give and the tree is never clean',
    },

    # ---- the checker: one rule at a time ----------------------------------------------------
    {
        'file': CHECKER,
        'find': "            if callee == 'getcwd':",
        'replace': "            if callee == 'getcwd' and False:",
        'expect': 'test_10',
        'note': 'rule 1 is emptied of its pattern - the shipped tree still reads clean because '
                'nothing is being looked for',
    },
    {
        'file': CHECKER,
        'find': '                and id(node) not in prose and _names_profile(node.value):',
        'replace': '                and id(node) not in prose and False:',
        'expect': 'test_10',
        'note': 'rule 2 is emptied the same way, so a caller spelling the profile folder is '
                'not reported and the two thumbnail folders come back',
    },
    {
        'file': CHECKER,
        'find': '                and id(node) not in prose and _names_profile(node.value):',
        'replace': '                and id(node) not in prose:',
        'expect': 'test_09',
        'note': 'rule 2 reads every string constant in the app instead of the profile name, so '
                'the checker reports hundreds of violations and stops being usable as a gate',
    },
    {
        'file': CHECKER,
        'find': r"    return any(part == '.renderfox' for part in re.split(r'[\\/]', value))",
        'replace': "    return '.renderfox' in value",
        'expect': 'test_11',
        'note': 'the component-wise read goes back to a substring, and the Automation pane\'s '
                '.renderfox_backups - beside the file it protects - becomes a violation',
    },
    {
        'file': CHECKER,
        'find': r"                            and arg.value.strip('\\/') == 'output' and id(arg) not in prose:",
        'replace': r"                            and arg.value.strip('\\/') == 'textures' and id(arg) not in prose:",
        'expect': 'test_10',
        'note': "rule 3's join half is pointed at a name nothing uses, so the hand-built output "
                'folders stop counting while the rule still prints as a finding',
    },
    {
        'file': CHECKER,
        'find': r"                    and right.value.strip('\\/') == 'output':",
        'replace': r"                    and right.value.strip('\\/') == 'textures':",
        'expect': 'test_10',
        'note': "rule 3's Path-division half goes the same way, which is the half a pathlib "
                'caller writes and a os.path-only checker misses',
    },
    {
        'file': CHECKER,
        'find': "                        and 'config.json' in first.value:",
        'replace': "                        and 'settings.json' in first.value:",
        'expect': 'test_10',
        'note': 'rule 4 waits for a file the app never had, so a bare relative settings name '
                'passes and the Save button lands in the working directory again',
    },
    {
        'file': CHECKER,
        'find': '                and id(node) not in prose and _names_profile(node.value):',
        'replace': '                and _names_profile(node.value):',
        'expect': 'test_12',
        'note': 'the docstring exclusion goes, and the prose that explains the rule is reported '
                'as a second defect - which is how a checker gets its exemptions removed',
    },

    # ---- the checker: what it says, and what it exits with ----------------------------------
    {
        'file': CHECKER,
        'find': "        yield ('unparsable', failed.lineno or 0, f'{path.name}: {failed.msg}')",
        'replace': '        pass',
        'expect': 'test_14',
        'note': 'a file that cannot be parsed is skipped, and the tree reads clean because the '
                'one file with a defect in it was never asked',
    },
    {
        'file': CHECKER,
        'find': "        return Path(*parts[parts.index('src'):]).as_posix()",
        'replace': "        return ''",
        'expect': 'test_12',
        'note': 'a finding stops naming the file it came from, so the person reading the report '
                'has a rule and a line number and nothing to open',
    },
    {
        'file': CHECKER,
        'find': "    lines = [f'{count} files in app scope, {len(RULES)} rules, {len(found)} violations']",
        'replace': "    lines = ['app scope checked, every rule applied']",
        'expect': 'test_10',
        'note': 'the summary line is a claim about the checker instead of a measurement of the '
                'tree, so the numbers that make a rule emptied visible disappear',
    },
    {
        'file': CHECKER,
        'find': '    return 1 if (args.strict and found) else 0',
        'replace': '    return 0',
        'expect': 'test_15',
        'note': 'the gate prints eight violations and exits 0, which the audit chain reads as a '
                'pass - the failure mode this repo has had to name twice already',
    },

    # ---- the checker: rule 5, the one that keeps six readers from coming back ----------------
    {
        'file': CHECKER,
        'find': '            if not spells_home and node.lineno not in demo and node.lineno not in derived:',
        'replace': '            if False:',
        'expect': 'test_16',
        'note': 'the whole of rule 5 stops looking: the shipped tree still reads clean while the '
                'six callers re-type the answer and the packaged half of each one goes unseen',
    },
    {
        'file': CHECKER,
        'find': "    if not (isinstance(func, ast.Attribute) and func.attr in ('dirname', 'abspath')):",
        'replace': '    if True:',
        'expect': 'test_16',
        'note': 'the dirname/abspath half answers "not a second reader" for every call, which is '
                'the shape all six files were actually written in',
    },
    {
        'file': CHECKER,
        'find': "        if isinstance(inner, ast.Name) and inner.id == '__file__':",
        'replace': "        if isinstance(inner, ast.Name) and inner.id == '__compiled__':",
        'expect': 'test_16',
        'note': 'the source-tree shape waits for a name no file carries, so three-levels-above-'
                '__file__ stops being a finding while the rule still prints in the report',
    },
    {
        'file': CHECKER,
        'find': "                and isinstance(inner.value, ast.Name) and inner.value.id == 'sys':",
        'replace': "                and isinstance(inner.value, ast.Name) and inner.value.id == 'system':",
        'expect': 'test_16',
        'note': 'the executable shape goes the same way - it is the half only a packaged build '
                'shows, so losing it makes rule 5 blind exactly where the install lives',
    },
    {
        'file': CHECKER,
        'find': "        if isinstance(node, ast.Constant) and not spells_home and node.value == '_MEIPASS' \\",
        'replace': "        if isinstance(node, ast.Constant) and not spells_home and node.value == '_MEIPAS' \\",
        'expect': 'test_16',
        'note': 'the unpack folder is read for a string nobody spells, so a caller that reaches '
                'for sys._MEIPASS instead of asking bundled() is no longer reported',
    },
    {
        'file': CHECKER,
        'find': "        if isinstance(node, ast.If) and '__main__' in ast.dump(node.test):",
        'replace': '        if False:',
        'expect': 'test_16',
        'note': 'the demo exemption goes, and the hand-run block that has to name the project '
                'folder before it can import anything becomes a violation',
    },
    {
        'file': CHECKER,
        'find': '            if not spells_home and node.lineno not in demo and node.lineno not in derived:',
        'replace': '            if not spells_home and node.lineno not in demo:',
        'expect': 'test_16',
        'note': 'one report per line goes, so a nested dirname(dirname(abspath(__file__))) is '
                'three findings for one question and the per-rule counts stop meaning anything',
    },

    # ---- the six callers that now ask instead of answering ----------------------------------
    {
        'file': 'src/ui/styles.py',
        'find': r'_ICONS_DIR = bundled(os.path.join("resources", "icons")).replace("\\", "/")',
        'replace': r'_ICONS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/resources/icons"',
        'expect': 'test_19',
        'note': 'the theme sheet is back to a hand-typed folder: the source tree still finds the '
                'icons, so only the reader\'s answer and rule 5 can see the packaged build losing them',
    },
    {
        'file': 'src/core/video_exporter.py',
        'find': '    app_dir = app_root()',
        'replace': '    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))',
        'expect': 'test_09',
        'note': 'the transcoder\'s first root stops coming from the reader - src/, not the app. '
                'The exe is still found here because bundled() covers the same root, so rule 5 is '
                'the only test that can refuse an answer a caller typed out for itself',
    },
    {
        'file': 'src/core/video_exporter.py',
        'find': '    installed = os.path.join("ffmpeg", "bin", "ffmpeg.exe")',
        'replace': '    installed = os.path.join("ffmpeg", "ffmpeg.exe")',
        'expect': 'test_18',
        'note': 'the folder the installer unpacks FFmpeg into is spelled without its bin/, which '
                'is the half a person who installed the component has and nobody testing here does',
    },
    {
        'file': 'src/processing/format_converter.py',
        'find': '        if os.path.isdir(candidate) and candidate not in dirs:',
        'replace': '        if os.path.isdir(candidate):',
        'expect': 'test_19',
        'note': 'the two roots stop being deduced, so a source tree hands pyassimp the same '
                'folder twice and the order the search prefers becomes arbitrary',
    },
    {
        'file': 'src/ui/main_window.py',
        'find': '        guide_path = bundled("USER_GUIDE.md")',
        'replace': '        guide_path = os.path.join(os.getcwd(), "USER_GUIDE.md")',
        'expect': 'test_09',
        'note': 'the Help pane opens the guide from the working directory again, which is the '
                'original defect and the exact shape rule 1 refuses in a caller',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': 'from src.utils.app_paths import app_root, bundled, data_dir, state_file',
        'replace': 'from src.utils.app_paths import app_root, bundled, data_dir',
        'expect': 'test_20',
        'note': 'the name the tags path uses is missing from the import, which is the defect '
                'measured while re-pointing this file - a NameError the moment a tag is saved',
    },
    {
        'file': 'src/features/ai_asset_tagger.py',
        'find': '        return state_file(os.path.join("config", "asset_tags.json"))',
        'replace': '        return os.path.join(app_root(), "config", "asset_tags.json")',
        'expect': 'test_21',
        'note': 'the precedence goes and the program folder is the answer on its own, so an '
                'install that cannot write there logs the refusal and forgets the tag',
    },
]
