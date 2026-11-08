"""Where this process may write, answered once and by asking the disk.

``installer.nsi:20`` installs RenderFox into ``$PROGRAMFILES64\\RenderFox`` and ``:24`` asks for
administration only to *install* it. The shortcut ``:101`` then starts the app as the signed-in
person, and ``C:\\Program Files`` grants ``BUILTIN\\Users`` read and execute - measured here with
``icacls``. So every path the app built from its own folder or from ``os.getcwd()``: the library
index, the thumbnails beside it, the generated textures, the script store, the crash records and
the version snapshots - resolved inside the program folder, where the person who installed
RenderFox cannot write. ``src/core/library_manager.py:122`` answered that with a
``PermissionError`` out of ``os.makedirs`` on the first launch, before any pane was on screen to
say why.

Five other subsystems had already settled the same question the other way - tasks and workflows
in ``src/features/automation_engine.py``, benchmark history and performance logs in
``src/features/performance_analyzer.py``, telemetry in ``src/utils/telemetry.py``, saved searches
and one thumbnail path in ``src/ui/library_tab.py`` - all of them in ``~/.renderfox``, which is
outside the program folder and always writable. That is why the answer is written once here
rather than nine more times in nine more files, and why the two questions are kept apart rather
than merged:

``data_dir()`` is for state that has to be found again however the app was started, so it lives
in the profile and never beside the executable. ``output_dir()`` is for the files the app makes
for the person to keep using - the library index on this machine holds 237 models, and it has
lived in ``<app>/output`` since it was created - so it stays where it has always been while the
disk allows it and moves under ``data_dir()`` only when the disk says no. No folder is migrated,
because on a machine that can write, nothing needs moving, and on one that cannot, there is
nothing to migrate.

``RENDERFOX_DATA_DIR``, ``RENDERFOX_OUTPUT_DIR`` and ``RENDERFOX_APP_ROOT`` point those answers
elsewhere. The first two are the same convention ``src/utils/app_settings.py:34`` already uses
for the settings store, and the reason is the same: a suite that builds a pane should not be the
thing that appends to the history of the machine it runs on. The third is here because the
question it asks - what does the app do when its own folder is read-only - cannot be asked of
this machine at all, so a suite fakes the program folder and reads both branches.

Two more questions are answered here rather than in the files that ask them, for the same reason
as the first two: ``config_path()`` is the queue- and engine-settings file, which three files
used to build from ``os.getcwd()`` - ``src/core/job_manager.py`` twice, ``src/processing/render_engines.py``
and ``src/ui/settings_tab.py``, whose Save button opened a *relative* ``config.json`` - and
``bundled()`` is a file the build ships, which ``src/ui/main_window.py`` also read from
``os.getcwd()`` and therefore did not find in the installed build at all.

``state_file()`` is that precedence on its own, for any file the app both reads and writes, and
the folder question turned out to have six more readers: ``src/ui/styles.py``,
``src/core/video_exporter.py``, ``src/processing/format_converter.py``, ``main.py``,
``src/ui/main_window.py`` and two inside ``src/features/ai_asset_tagger.py``, each re-typing the
``getattr(sys, 'frozen')`` / ``_MEIPASS`` / ``dirname``-of-``__file__`` shape. Five of the six
answer a folder the measured package does contain - ``_internal/resources`` holds ``icon.ico``,
``icons/``, ``splash.png`` and the FFmpeg build - so their values are the reader's values with the
branches retyped by hand, which is how a future fix misses them; the sixth was a write, the
tagger's own ``config/asset_tags.json`` (the tags a person assigned), which lands in ``_internal``
and is refused by the read-and-execute grant. Two more files hold the shape legitimately and stay:
``src/ui/automation_tab.py`` passes ``sys.executable`` to the user's own script, and a hand-run
``__main__`` demo has to name the path before it can import anything.
``tools/check_paths_hygiene.py`` refuses the shape on those terms now, so six readers stay one.
"""

import os
import sys

DATA_OVERRIDE = 'RENDERFOX_DATA_DIR'
OUTPUT_OVERRIDE = 'RENDERFOX_OUTPUT_DIR'
# The program folder, faked. It is the only way to ask this module what it would do on a
# machine where the app is installed read-only, which is the machine `installer.nsi` builds
# for and the one nobody developing here is sitting at.
APP_ROOT_OVERRIDE = 'RENDERFOX_APP_ROOT'

CONFIG_NAME = 'config.json'

# Why the output folder moved, kept from the one `OSError` that asked for it. A fallback nobody
# can read is a folder that silently changed, which is how an installed build would report
# "0 models" for a library the person cannot see rather than "this folder is read-only".
_reason = ''


def app_root() -> str:
    """The folder the app itself lives in, not the folder it was started from.

    ``os.getcwd()`` is what these paths used, so starting RenderFox by double-clicking a model
    in Explorer, or from any other directory, pointed the app at an empty library in the wrong
    place - the defect `src/features/automation_engine.py:62` documents for its own files.
    """
    override = os.environ.get(APP_ROOT_OVERRIDE)
    if override:
        return override
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def data_dir() -> str:
    """The profile folder this app keeps its own state in, created if it is not there yet."""
    return _make(os.environ.get(DATA_OVERRIDE)
                 or os.path.join(os.path.expanduser('~'), '.renderfox'))


def output_dir() -> str:
    """The folder for the files the app makes, beside itself while that is allowed.

    The candidate is tried rather than judged: a writability probe on a path is the only answer
    that is true on the machine asking it, and the fallback has to be reachable without anybody
    installing the app first. The reason the first attempt failed is kept, because the pane that
    shows the folder is the person's only chance to read it.
    """
    override = os.environ.get(OUTPUT_OVERRIDE)
    if override:
        return _make(override)
    global _reason
    candidate = os.path.join(app_root(), 'output')
    try:
        _make(candidate)
    except OSError as failed:
        problem = f'{type(failed).__name__}: {failed}'
    else:
        if _takes_files(candidate):
            return candidate
        problem = 'it is there but takes no files from this account'
    _reason = (f'{candidate} cannot be used ({problem}), '
               f'so the app\'s files go under {data_dir()} instead')
    return _make(os.path.join(data_dir(), 'output'))


def config_path() -> str:
    """The queue- and engine-settings file, in the one place both reader and writer can reach."""
    return state_file(CONFIG_NAME)


def state_file(name: str) -> str:
    """A file the app both reads and writes, from where it already is or from the profile.

    ``config_path()`` is one instance and the AI tagger's ``config/asset_tags.json`` is another:
    both used to be built from ``os.getcwd()`` or from ``__file__``, so the Settings pane's Save
    button opened a *relative* ``config.json`` and a person's own tags were written into the
    program folder. A copy that already sits beside the app keeps being read, because that is
    where every source-tree run has kept one and where the tags on this machine are; a machine
    that cannot write there gets the profile answer instead, and the folder is made by whoever
    saves.
    """
    beside = os.path.join(app_root(), name)
    return beside if os.path.isfile(beside) else os.path.join(data_dir(), name)


def bundled(name: str) -> str:
    """The path to a file the build ships, in whichever folder this start keeps those.

    ``PyInstaller`` puts ``--add-data`` under ``sys._MEIPASS``, which is ``_internal`` beside the
    executable, while a source tree keeps the same file at its root. Two answers, one caller:
    ``USER_GUIDE.md`` was read from ``os.getcwd()`` and so was missing from the installed build
    entirely - the Help pane reported the file not found on the only machine the person buying
    RenderFox uses it on.
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(getattr(sys, '_MEIPASS', app_root()), name)
    return os.path.join(app_root(), name)


def reason() -> str:
    """What the disk said when the app was not allowed to keep its files beside itself."""
    return _reason


def reset() -> None:
    """Forget the recorded reason, so a suite asks the question again instead of inheriting one."""
    global _reason
    _reason = ''


def _make(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _takes_files(path: str) -> bool:
    """Whether this account can actually put a file in ``path``, not whether the folder exists.

    ``os.makedirs(..., exist_ok=True)`` answers "made" for a read-only folder that is already
    there, which is what an install looks like once anybody has run the app as administrator:
    ``output`` sits inside ``C:\\Program Files\\RenderFox`` with the folder's own
    ``BUILTIN\\Users`` read-and-execute grant, and every thumbnail after that fails.
    """
    probe = os.path.join(path, f'.writable-{os.getpid()}')
    try:
        with open(probe, 'wb'):
            pass
    except OSError:
        return False
    try:
        os.remove(probe)
    except OSError:
        pass
    return True
