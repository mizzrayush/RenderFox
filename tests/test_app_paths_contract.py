"""Where this app writes, asked of the one module that answers it.

``src/utils/app_paths.py`` exists because Phase 38 measured what the shipped tree does on an
installed machine: ``installer.nsi:20`` puts RenderFox in ``C:\\Program Files\\RenderFox``, ``:24``
asks for administration only to put it there, and ``icacls`` on that folder answers
``BUILTIN\\Users:(RX)`` - so the nine paths the app built from its own folder or from
``os.getcwd()`` resolved where the person who installed it cannot write. Two of them were proved
rather than assumed: ``output/library.db`` on this machine holds 237 models and lives in
``<app>/output``, which is why the answer is a probe with a fallback and not a move, and
``~/.renderfox`` holds no thumbnails folder at all, which is why the two thumbnail paths in
``src/ui/library_tab.py`` were one bug rather than two folders of history.

The two branches are therefore both read here, against a program folder this suite makes and
unmakes:

* a candidate that takes files wins, and no reason is recorded;
* a candidate that does not - a folder that refuses a file, or a name that is not a folder at
  all - falls back under the profile, and the reason names both folders in the disk's own words,
  because a folder that silently changed is how an installed build reports "0 models" for a
  library the person cannot see.

``tools/check_paths_hygiene.py`` is read as the instrument it is: run over the shipped tree it
must answer five rules and no violations, and run over a fixture it must answer a known count per
rule, so a rule emptied of its patterns cannot pass the shipped tree by looking for nothing.

The fifth rule is the one this phase added last: ``bundled()``/``app_root()`` answers had been
re-typed by hand in six files, one of which used its hand-typed answer to *write* the tags a
person assigns to their models into the read-and-execute install. So rules 1-4 are asked of one
fixture tree and rule 5 of a second tree that holds its three shapes and both of its exemptions,
counted by hand either way. The files the reader now answers for are then asked directly -
``icon.ico``, ``resources/icon.ico``, ``USER_GUIDE.md``, ``resources/splash.png``, the icon
folder, the CLIP folder and the assimp ``lib/`` - because a wrong ``bundled()`` is a blank theme,
not a traceback, and the import wiring is read off the source, because a file that stopped
spelling the path by hand can still forget to import the answer.

Run: python -X utf8 tests/test_app_paths_contract.py
"""

import ast
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.utils import app_paths  # noqa: E402
from src.features import automation_engine  # noqa: E402
from src.features import performance_analyzer  # noqa: E402
from tools import check_paths_hygiene  # noqa: E402

ENV_NAMES = (app_paths.APP_ROOT_OVERRIDE, app_paths.DATA_OVERRIDE, app_paths.OUTPUT_OVERRIDE)

# What the account's own folder is called on each platform. Test 13 moves both, so that the
# reader's fallback is asked of a profile this suite owns rather than of the real one.
PROFILE_NAMES = ('USERPROFILE', 'HOME')

# The four counts the fixture tree must answer: two getcwd calls, one profile literal spelled by
# a caller (a second one sits in a docstring and is not a violation), three hand-built output
# folders and two bare config.json opens, in four files. Counted by hand from the fixture
# written in setUpClass, because a checker that reports a number nobody has worked out is a
# checker nobody can trust.
FIXTURE_COUNTS = {'getcwd': 2, 'profile-literal': 1, 'output-join': 3, 'config-open': 2}

# The reader's answers, and the six files that had been re-typing them. Rule 5 refuses the shapes;
# test 20 asks each of these files whether the names it calls are the names it imports.
ANSWERED = ('app_root', 'data_dir', 'output_dir', 'config_path', 'state_file', 'bundled')
CALLERS = ('main.py', 'src/ui/styles.py', 'src/core/video_exporter.py',
           'src/processing/format_converter.py', 'src/ui/main_window.py',
           'src/features/ai_asset_tagger.py')


class TestAppPathsContract(unittest.TestCase):
    """One reader, both branches, and the instrument that keeps it the only reader."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='renderfox_app_paths_')
        # A program folder that cannot take a folder of its own: `<blocked>/output` is a file,
        # so `makedirs` there is refused by the disk rather than by a policy this suite fakes.
        cls.blocked = os.path.join(cls.work, 'blocked')
        os.makedirs(cls.blocked)
        with open(os.path.join(cls.blocked, 'output'), 'w') as handle:
            handle.write('a name in the way')
        cls.fixture = os.path.join(cls.work, 'fixture')
        os.makedirs(os.path.join(cls.fixture, 'src', 'core'))
        os.makedirs(os.path.join(cls.fixture, 'src', 'ui'))
        with open(os.path.join(cls.fixture, 'src', 'core', 'bad.py'), 'w',
                  encoding='utf-8') as handle:
            handle.write('import os\n'
                         'with open(os.path.join(os.getcwd(), "config.json")) as h:\n'
                         '    p = os.path.join(os.getcwd(), "output")\n'
                         '    d = ".renderfox"\n'
                         '    open("config.json", "w")\n')
        with open(os.path.join(cls.fixture, 'src', 'ui', 'bad2.py'), 'w',
                  encoding='utf-8') as handle:
            handle.write('from pathlib import Path\n'
                         'import os\n'
                         'q = Path("x") / "output"\n'
                         'r = os.path.join("a", "output")\n'
                         'open("config.json")\n')
        # Prose that spells the profile folder the way rule 2 reads it, so the docstring
        # exclusion is a live branch and not a habit nobody can prove: the string has to name
        # `.renderfox` as a component of its own, which ``~/.renderfox/thumbnails`` does.
        with open(os.path.join(cls.fixture, 'src', 'ui', 'notes.py'), 'w',
                  encoding='utf-8') as handle:
            handle.write('"""The thumbnails used to sit in ~/.renderfox/thumbnails, one folder per pane."""\n'
                         'NOTES = 1\n')
        # A file the checker cannot parse. Silence here is the failure mode every instrument in
        # this repo has to answer for: `ast.parse` raises, the file is skipped, and the tree
        # reads clean because nothing was asked of it.
        cls.unreadable = os.path.join(cls.work, 'unreadable')
        os.makedirs(os.path.join(cls.unreadable, 'src', 'core'))
        with open(os.path.join(cls.unreadable, 'src', 'core', 'broken.py'), 'w',
                  encoding='utf-8') as handle:
            handle.write('def cut(\n')
        # Rule 5's three shapes and its two exemptions, asked of a tree this suite owns. The
        # shapes are the ones six shipped files were written in until this phase re-pointed them
        # (`git show HEAD:src/ui/styles.py` answers three findings for that file alone), and the
        # exemptions are the two files the rule has to leave alone: `src/ui/automation_tab.py`
        # hands `sys.executable` to the user's script, and a hand-run demo must put the project
        # folder on `sys.path` before it can import the reader.
        cls.readers = os.path.join(cls.work, 'readers')
        os.makedirs(os.path.join(cls.readers, 'src', 'ui'))
        with open(os.path.join(cls.readers, 'src', 'ui', 'retype.py'), 'w',
                  encoding='utf-8') as handle:
            handle.write('import os\n'
                         'import sys\n'
                         'APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n'
                         'EXE = os.path.dirname(os.path.abspath(sys.executable))\n'
                         'UNPACK = getattr(sys, "_MEIPASS", APP)\n')
        with open(os.path.join(cls.readers, 'src', 'ui', 'legit.py'), 'w',
                  encoding='utf-8') as handle:
            handle.write('import os\n'
                         'import sys\n'
                         'INTERPRETER = sys.executable\n'
                         'FOLDER = os.path.dirname(INTERPRETER) if False else ""\n')
        with open(os.path.join(cls.readers, 'src', 'ui', 'demo.py'), 'w',
                  encoding='utf-8') as handle:
            handle.write('import os\n'
                         'import sys\n'
                         'if __name__ == "__main__":\n'
                         '    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n'
                         '    from src.utils.app_paths import app_root\n'
                         '    print(app_root())\n')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.saved = {name: os.environ.get(name) for name in ENV_NAMES}
        for name in ENV_NAMES:
            os.environ.pop(name, None)
        app_paths.reset()
        self.addCleanup(app_paths.reset)

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def point_at(self, root, data):
        """A program folder and a profile folder this test owns."""
        os.environ[app_paths.APP_ROOT_OVERRIDE] = root
        os.environ[app_paths.DATA_OVERRIDE] = data
        app_paths.reset()

    # ---- the tree this checkout is ------------------------------------------------------

    def test_01_the_reader_answers_this_tree_where_it_already_lives(self):
        """Nothing moved: the source tree's answer is the folder the nine call sites used.

        `os.getcwd()` and `__file__`-three-up both come to this folder when the audit chain runs
        from the checkout, so a reader that answered elsewhere would have moved the 237-model
        library on the first launch after this phase.
        """
        self.assertEqual(ROOT, app_paths.app_root())
        self.assertEqual(os.path.join(ROOT, 'output'), app_paths.output_dir())
        self.assertEqual(os.path.join(os.getcwd(), 'output'), app_paths.output_dir())
        self.assertEqual('', app_paths.reason(), 'a writable folder recorded a reason anyway')
        legacy = os.path.join(ROOT, 'config.json')
        self.assertEqual(legacy if os.path.isfile(legacy)
                         else os.path.join(app_paths.data_dir(), 'config.json'),
                         app_paths.config_path())

    def test_02_a_candidate_that_takes_files_wins_and_says_nothing(self):
        """The probe's success path: the folder beside the app, with no reason attached."""
        root = os.path.join(self.work, 'writable_root')
        data = os.path.join(self.work, 'writable_profile')
        self.point_at(root, data)
        answered = app_paths.output_dir()
        self.assertEqual(os.path.join(root, 'output'), answered)
        self.assertTrue(os.path.isdir(answered), 'the winner was answered without being made')
        self.assertEqual('', app_paths.reason())
        self.assertEqual([], os.listdir(answered),
                         'the probe left a file in the folder it had just tested')

    def test_03_a_folder_that_refuses_a_file_falls_back_and_names_both(self):
        """The case `os.makedirs` cannot see: the folder is there and takes nothing.

        An install that was once run as administrator has a real `<app>\\output` sitting inside
        ``C:\\Program Files`` with that folder's read-and-execute grant, and `makedirs` answers
        "made" for it. The probe is what turns that into the fallback, so this stands a folder
        in the probe's own way rather than trusting an ACL this machine does not have.
        """
        root = os.path.join(self.work, 'readonly_root')
        data = os.path.join(self.work, 'readonly_profile')
        candidate = os.path.join(root, 'output')
        os.makedirs(candidate)
        os.makedirs(os.path.join(candidate, f'.writable-{os.getpid()}'))
        self.point_at(root, data)
        answered = app_paths.output_dir()
        self.assertEqual(os.path.join(data, 'output'), answered)
        reason = app_paths.reason()
        self.assertIn(candidate, reason)
        self.assertIn(data, reason)
        self.assertTrue(reason, 'the folder moved and nothing was left to read')
        app_paths.reset()
        self.assertEqual('', app_paths.reason(), 'reset() left the previous answer readable')

    def test_04_a_name_that_is_not_a_folder_falls_back_too(self):
        """`makedirs` raises `FileExistsError` there, which is not a `PermissionError`.

        Pinning the class the reader catches is the point: a narrower clause turns the first
        launch into a traceback out of `library_manager` instead of a folder that moved.
        """
        data = os.path.join(self.work, 'name_in_the_way_profile')
        self.point_at(self.blocked, data)
        answered = app_paths.output_dir()
        self.assertEqual(os.path.join(data, 'output'), answered)
        self.assertIn('FileExistsError', app_paths.reason())
        self.assertIn(self.blocked, app_paths.reason())

    def test_05_an_explicit_folder_is_used_and_never_probed(self):
        """`RENDERFOX_OUTPUT_DIR` is an instruction, so a refusal there must be loud.

        The probe exists to guess what the machine allows; a caller that already said the folder
        has nothing to guess, and a fallback would hide the one thing that person needs to see.
        """
        target = os.path.join(self.work, 'explicit', 'files')
        os.environ[app_paths.OUTPUT_OVERRIDE] = target
        app_paths.reset()
        self.assertEqual(target, app_paths.output_dir())
        self.assertTrue(os.path.isdir(target))
        self.assertEqual('', app_paths.reason())

    # ---- one answer per question --------------------------------------------------------

    def test_06_the_three_existing_readers_give_this_same_answer(self):
        """The dedupe, measured: three modules asked, and now they say one thing.

        `automation_engine.app_data_dir()` wrote the profile path out itself, as did
        `performance_analyzer.data_dir()` and `src/utils/telemetry.py`; the automation suites
        patch the first of those names, so it stays a function of its own and delegates.
        """
        data = os.path.join(self.work, 'shared_profile')
        os.environ[app_paths.DATA_OVERRIDE] = data
        app_paths.reset()
        self.assertEqual(data, app_paths.data_dir())
        self.assertEqual(data, automation_engine.app_data_dir())
        self.assertEqual(data, performance_analyzer.data_dir())
        self.assertEqual('RENDERFOX_DATA_DIR', app_paths.DATA_OVERRIDE,
                         'the override the suites already set is not the one the reader reads')

    def test_07_the_settings_file_is_where_both_sides_can_reach_it(self):
        """A copy beside the app still wins; with none, the profile answers.

        Every source-tree run since the file was written has kept one at the checkout's root, so
        dropping that branch would have made the app report no configured engine on this machine.
        """
        root = os.path.join(self.work, 'config_root')
        data = os.path.join(self.work, 'config_profile')
        os.makedirs(root, exist_ok=True)
        self.point_at(root, data)
        self.assertEqual(os.path.join(data, 'config.json'), app_paths.config_path(),
                         'a profile answer appeared while the app had its own copy nowhere')
        with open(os.path.join(root, 'config.json'), 'w', encoding='utf-8') as handle:
            handle.write('{}')
        self.assertEqual(os.path.join(root, 'config.json'), app_paths.config_path())
        os.remove(os.path.join(root, 'config.json'))
        self.assertEqual(os.path.join(data, 'config.json'), app_paths.config_path())

    def test_08_a_shipped_document_is_read_from_the_folder_this_start_keeps(self):
        """`USER_GUIDE.md` was opened from `os.getcwd()`, so the install had no guide at all."""
        self.assertEqual(os.path.join(ROOT, 'USER_GUIDE.md'), app_paths.bundled('USER_GUIDE.md'))
        self.assertTrue(os.path.isfile(app_paths.bundled('USER_GUIDE.md')),
                        'the shipped tree does not carry the file the Help pane opens')
        self.point_at(self.work, self.work)
        self.assertEqual(os.path.join(self.work, 'USER_GUIDE.md'),
                         app_paths.bundled('USER_GUIDE.md'),
                         'a faked program folder did not move the answer')

    # ---- the instrument ----------------------------------------------------------------

    def test_09_the_checker_answers_the_shipped_tree_clean(self):
        """Five rules over the files the app ships, with nothing left to find."""
        count, found = check_paths_hygiene.scan()
        self.assertEqual(len(check_paths_hygiene.app_files()), count,
                         'the files asked and the files walked are not the same set')
        self.assertEqual(5, len(check_paths_hygiene.RULES))
        self.assertEqual([], found, f'a path is still spelled by a caller: {found}')
        self.assertGreaterEqual(count, 70, f'app scope walked only {count} files')

    def test_10_the_checker_finds_every_shape_in_a_tree_that_has_them(self):
        """Reach, measured: each rule must fire on its own fixture shape.

        Without this, emptying `RULES` or one pattern would still read the shipped tree as clean,
        which is the failure every checker in this repo has to answer for.
        """
        _count, found = check_paths_hygiene.scan(Path(self.fixture))
        by_rule = {}
        for rule, _line, _where in found:
            by_rule[rule] = by_rule.get(rule, 0) + 1
        self.assertEqual(FIXTURE_COUNTS, by_rule,
                         f'the fixture answers {by_rule}, and {FIXTURE_COUNTS} was counted by hand')
        report = check_paths_hygiene.report(Path(self.fixture))
        self.assertIn('8 violations', report)
        self.assertIn('5 rules', report)

    def test_11_the_profile_prefix_a_caller_may_still_spell_is_not_the_profile(self):
        """`.renderfox_backups` sits beside the file it protects, and is not this rule's.

        Measured on this tree: the Automation pane's backup folder is the only string that starts
        like the profile path, and a component-wise rule is what keeps the checker honest about
        it rather than exempting a file.
        """
        self.assertTrue(check_paths_hygiene._names_profile('~/'.join(['~', '.renderfox'])))
        self.assertFalse(check_paths_hygiene._names_profile('.renderfox_backups'))
        self.assertFalse(check_paths_hygiene._names_profile('renderfox_automation_log.txt'))

    def test_12_the_prose_that_describes_a_defect_is_not_a_second_defect(self):
        """The docstring in the fixture carries the same string as the caller in `bad.py`.

        Only one of the two is a violation, and the exclusion is what makes that true: measured
        here, the fixture answers one `profile-literal` while its files hold two such strings.
        Without the branch the checker refuses the prose that explains the rule, which is the
        reason every checker in this repo has to say how many it read and of what kind.
        """
        _count, found = check_paths_hygiene.scan(Path(self.fixture))
        spelled = [where for rule, _line, where in found if rule == 'profile-literal']
        self.assertEqual(1, len(spelled), f'the docstring was counted as a caller: {spelled}')
        self.assertIn('bad.py', spelled[0])

    # ---- the reader with nothing pointed at it --------------------------------------------

    def test_13_the_profile_is_the_account_s_own_folder_not_the_app_s(self):
        """No override: `data_dir()` is the account's folder, named `.renderfox`.

        Every other test in this file sets `RENDERFOX_DATA_DIR`, so the fallback is the one line
        in the reader no suite had reached. Building it from `os.getcwd()` instead passes all of
        them and writes the library into whatever directory the app happened to be started from,
        which is the defect rule 1 exists to refuse.
        """
        home = os.path.join(self.work, 'fake_account')
        saved = {name: os.environ.get(name) for name in PROFILE_NAMES}
        for name in PROFILE_NAMES:
            os.environ[name] = home
        try:
            answered = app_paths.data_dir()
            self.assertEqual(os.path.join(home, '.renderfox'), answered)
            self.assertTrue(os.path.isdir(answered), 'the reader answered a folder it had not made')
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    # ---- the instrument, again ------------------------------------------------------------

    def test_14_a_file_the_checker_cannot_parse_is_named_not_skipped(self):
        """`ast.parse` raising is a finding, not a reason to say the tree is clean.

        Measured: one file whose `def` never closes answers `('unparsable', 1, …broken.py…)` and
        a scope of one file. Swallowing the `SyntaxError` would report one file and no
        violations, which is the same sentence the checker says about a healthy tree.
        """
        count, found = check_paths_hygiene.scan(Path(self.unreadable))
        self.assertEqual(1, count)
        self.assertEqual(['unparsable'], [rule for rule, _line, _where in found])
        self.assertIn('broken.py', found[0][2])

    def test_15_the_strict_answer_is_the_exit_code_the_chain_reads(self):
        """`--strict` is what turns the report into a gate; report mode keeps it readable.

        Measured on the two trees: the fixture exits 1 under `--strict` and 0 without it, and the
        shipped tree exits 0 either way. A `return 0` planted in `main` makes the first of those
        a clean exit over eight defects, which is the failure this chain has seen before - a
        checker that prints a list and still says success.
        """
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(1, check_paths_hygiene.main(['--root', self.fixture, '--strict']))
            self.assertEqual(0, check_paths_hygiene.main(['--root', self.fixture]))
            self.assertEqual(0, check_paths_hygiene.main(['--strict']))
        self.assertIn('8 violations', out.getvalue())

    def test_16_the_checker_refuses_an_app_folder_re_typed_by_a_caller(self):
        """Rule 5, asked of the shapes six shipped files were written in until this phase.

        Three findings and three files, measured: `dirname` of `__file__`, `dirname` of the
        executable and a `getattr(sys, '_MEIPASS', …)` each name the same folder the reader
        answers, and a caller that types it out cannot ask whether that folder takes files.
        The two exemptions are the reason the rule is not simply a name search:
        `src/ui/automation_tab.py:1734` hands `sys.executable` to the user's own script, which is
        an interpreter and not a folder, and a hand-run `__main__` demo has to put the project
        folder on `sys.path` before it can import the reader at all.
        """
        count, found = check_paths_hygiene.scan(Path(self.readers))
        self.assertEqual(3, count, 'the tree this test wrote is not the tree it asked')
        self.assertEqual(['second-reader'] * 3, [rule for rule, _line, _w in found])
        reasons = ' '.join(where for _rule, _line, where in found)
        for shape in ('`__file__`', 'the executable', '_MEIPASS'):
            self.assertIn(shape, reasons, f'one of the three shapes is not looked for: {reasons}')
        self.assertIn('retype.py', reasons)
        self.assertNotIn('legit.py', reasons, '`sys.executable` on its own is a second reader')
        self.assertNotIn('demo.py', reasons, 'a hand-run demo cannot import what it must name')

    # ---- the callers that used to answer for themselves ------------------------------------

    def test_17_a_file_the_app_both_reads_and_writes_keeps_the_copy_it_has(self):
        """`state_file()` is `config_path()`'s precedence, standing on its own for a second file.

        The AI tagger's `config/asset_tags.json` - the tags a person assigned to their models -
        was built from three levels above `__file__`, which in the packaged build is
        `_internal\\config`, inside the folder the install grants read and execute. This checkout
        holds 287 bytes of real tags at the source-tree answer, so the branch that keeps reading
        an existing copy is the branch that keeps the person their work.
        """
        tags = os.path.join('config', 'asset_tags.json')
        legacy = os.path.join(ROOT, 'config', 'asset_tags.json')
        self.assertTrue(os.path.isfile(legacy), 'this checkout no longer holds the tags file')
        self.assertEqual(legacy, app_paths.state_file(tags), 'the tags that exist were ignored')

        data = os.path.join(self.work, 'state_profile')
        self.point_at(self.blocked, data)
        self.assertEqual(os.path.join(data, 'config', 'asset_tags.json'), app_paths.state_file(tags),
                         'a machine with no copy beside it did not get the profile answer')

        root = os.path.join(self.work, 'state_root', 'config')
        os.makedirs(root)
        with open(os.path.join(root, 'asset_tags.json'), 'w', encoding='utf-8') as handle:
            handle.write('{}')
        self.point_at(os.path.join(self.work, 'state_root'), data)
        self.assertEqual(os.path.join(root, 'asset_tags.json'), app_paths.state_file(tags))
        self.assertEqual(app_paths.state_file(app_paths.CONFIG_NAME), app_paths.config_path(),
                         'config_path() is no longer the same question as state_file()')

    def test_18_the_ffmpeg_search_reaches_both_folders_the_build_ships(self):
        """The transcoder's candidate list is the reader's two roots, measured on a fake install.

        `installer.nsi:107` unpacks FFmpeg into `$INSTDIR\\ffmpeg` while the spec ships the same
        build inside `resources`, which in a package is `_internal`. A list built from either one
        alone answers a bare `ffmpeg` on the machine that installed the component - the
        transcode failing with a name that is not a path and no reason attached.
        """
        from src.core.video_exporter import FFMPEG_BUILD, find_ffmpeg_executable

        root = os.path.join(self.work, 'ffmpeg_install')
        data = os.path.join(self.work, 'ffmpeg_profile')
        self.point_at(root, data)

        installed = os.path.join(root, 'ffmpeg', 'bin')
        os.makedirs(installed)
        exe = os.path.join(installed, 'ffmpeg.exe')
        with open(exe, 'wb') as handle:
            handle.write(b'not ffmpeg, a marker')
        self.assertEqual(exe, find_ffmpeg_executable(),
                         'the folder the installer writes to is not one of the roots asked')

        os.remove(exe)
        shipped = os.path.join(root, 'resources', FFMPEG_BUILD, 'bin')
        os.makedirs(shipped)
        inside = os.path.join(shipped, 'ffmpeg.exe')
        with open(inside, 'wb') as handle:
            handle.write(b'not ffmpeg, a marker')
        self.assertEqual(inside, find_ffmpeg_executable(),
                         'the shipped resources folder is not one of the roots asked')

        os.remove(inside)
        answered = find_ffmpeg_executable()
        self.assertFalse(os.path.isabs(answered) and answered.startswith(root),
                         f'a fake install with nothing in it still answered {answered!r}')

    def test_19_the_shipped_files_are_where_the_reader_says_they_are(self):
        """Seven things the six callers name, asked of this checkout: every one is where it says.

        ``bundled()`` and ``app_root()`` replaced a hand-typed `_MEIPASS`/`dirname` chain in
        `src/ui/styles.py`, `main.py`, `src/ui/main_window.py`, `src/features/ai_asset_tagger.py`
        and `src/processing/format_converter.py`, so one wrong answer is a theme with no icons, a
        taskbar with somebody else's glyph, a Help pane that says the guide is missing, a CLIP
        model that will not load offline and a `.dae` that will not open. The packaged half of
        each answer is the same string on a different root, which is what the built executable is
        asked at the end of this phase.
        """
        for shipped in ('icon.ico', os.path.join('resources', 'icon.ico'), 'USER_GUIDE.md',
                        os.path.join('resources', 'splash.png')):
            self.assertTrue(os.path.isfile(app_paths.bundled(shipped)),
                            f'bundled({shipped!r}) does not name a file this checkout ships')
        self.assertTrue(os.path.isdir(app_paths.bundled(os.path.join('resources', 'icons'))),
                        'the icon folder the theme points at is not where the reader says it is')
        self.assertTrue(os.path.isdir(app_paths.bundled('OPENai Clip')),
                        'the offline CLIP folder the tagger searches is not a shipped folder')

        import src.ui.styles as styles

        self.assertEqual(app_paths.bundled(os.path.join('resources', 'icons')).replace('\\', '/'),
                         styles._ICONS_DIR, 'the theme sheet is not built from the reader')
        self.assertTrue(os.path.isdir(styles._ICONS_DIR))

        from src.processing import format_converter

        self.assertEqual([os.path.join(ROOT, 'lib')], format_converter._ASSIMP_LIB_DIRS,
                         'the assimp search is not the reader\'s source-tree answer')
        with_assimp = [d for d in format_converter._ASSIMP_LIB_DIRS
                       if any('assimp' in f.lower() and f.lower().endswith('.dll')
                              for f in os.listdir(d))]
        self.assertEqual(format_converter._ASSIMP_LIB_DIRS, with_assimp,
                         'the folder put on PATH for pyassimp holds no assimp build')

    def test_20_no_caller_names_an_answer_it_did_not_import(self):
        """The wiring, read off the source: six files ask the reader, and each imports what it calls.

        Measured while re-pointing them: `src/features/ai_asset_tagger.py` imported `data_dir`
        and then called `app_root()`, `bundled()` and `state_file()` - so the AI pane raised
        `NameError` the moment a tag was saved, and no rule of `check_paths_hygiene` can see it,
        because that file had stopped spelling the folder by hand and had only forgotten to ask
        for the answer. Both directions are checked: an import nothing calls is a caller that
        went back to building the path itself.
        """
        for rel in CALLERS:
            tree = ast.parse(Path(ROOT, rel).read_text(encoding='utf-8'))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or '').endswith('app_paths'):
                    imported |= {alias.name for alias in node.names}
            called = {node.func.id for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                      and node.func.id in ANSWERED}
            self.assertEqual(called, imported,
                             f'{rel} imports {sorted(imported)} and calls {sorted(called)}')
            self.assertTrue(called, f'{rel} no longer asks the reader anything')

    def _compiled(self, rel, func_name, namespace):
        """One function lifted out of a file this suite must not import.

        `src/features/ai_asset_tagger.py` pulls torch, transformers and Open3D in at import, so
        its tags path cannot be asked by importing it; `ast` hands the method body over with the
        reader's names bound, which is the same call the pane makes.
        """
        tree = ast.parse(Path(ROOT, rel).read_text(encoding='utf-8'))
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == func_name)
        node.args.args = []
        module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        exec(compile(module, rel, 'exec'), namespace)
        return namespace[func_name]

    def test_21_the_tags_a_person_assigns_are_written_where_the_reader_says(self):
        """The tagger's own answer, run against a program folder that cannot take a write.

        `config/asset_tags.json` holds 287 bytes of real tags on this machine, and until this
        phase it was named by three directories above `__file__` - in the installed build
        ``_internal\\config``, inside the folder that grants read and execute, where
        `_save_tags_db`'s `except` turns the `PermissionError` into a log line and the next scan
        forgets the tag. The first half of this test is the continuity of that work; the second is
        the machine `installer.nsi` builds for, which no test can reach by importing the tagger.
        """
        tags = os.path.join('config', 'asset_tags.json')
        namespace = {'os': os, 'app_root': app_paths.app_root, 'data_dir': app_paths.data_dir,
                     'bundled': app_paths.bundled, 'state_file': app_paths.state_file}
        answer = self._compiled('src/features/ai_asset_tagger.py', '_get_tags_db_path', namespace)

        self.assertEqual(app_paths.state_file(tags), answer(),
                         'the tagger does not give the answer the reader gives')
        self.assertTrue(os.path.isfile(answer()), 'the tags this machine holds are not found')

        data = os.path.join(self.work, 'tags_profile')
        self.point_at(self.blocked, data)
        answered = answer()
        self.assertEqual(os.path.join(data, 'config', 'asset_tags.json'), answered)
        self.assertFalse(answered.startswith(self.blocked),
                         f'a read-only install was offered {answered!r} inside itself')


if __name__ == '__main__':
    unittest.main(verbosity=2)
