"""The app's one persisted settings store, handed out as one object.

Two panes used to keep their own `QSettings()` and their own idea of a setting's range,
which is how `Max Threads` ended up as a 1-64 box defaulting to 8 in the Performance pane
and a 1-16 box defaulting to 4 in Post-Processing, both claiming to be the thread count
`src/processing/postprocessor.py:662` hands to `ThreadPoolExecutor`. A `QSettings` instance
holds its own in-memory copy of the store, so a value one instance writes is not visible to
another until one of them syncs: two instances are two answers, whatever the file behind
them says. Every pane that persists a setting now asks this module for the object.

`RENDERFOX_SETTINGS_PATH` points the store at an ini file, which is how a suite writes
settings without becoming the thing that changed this machine's real ones. The app never
sets it, so the app keeps the store Qt picks from the organization and application names
`main.py:111` and `main.py:113` give the process.
"""

import os
from typing import Optional

from PyQt6.QtCore import QSettings

STORE: Optional[QSettings] = None


def settings() -> QSettings:
    """The store this process persists through - one object, so one answer per key.

    The path override is read on the first call only, because a store that moved mid-run
    would leave the panes holding the object they were given earlier; a suite that needs a
    different folder gets it before any pane is constructed.
    """
    global STORE
    if STORE is None:
        override = os.environ.get('RENDERFOX_SETTINGS_PATH')
        STORE = (QSettings(override, QSettings.Format.IniFormat) if override
                 else QSettings())
    return STORE


def reset() -> None:
    """Drop the cached object so the next call re-reads the environment.

    Only a suite needs this: it is how one test's settings do not leak into the next test
    in the same process, which is the same reason the data folder is redirected.
    """
    global STORE
    if STORE is not None:
        STORE.sync()
    STORE = None


def write(group: str, key: str, value) -> None:
    """Store one value and push it to the backend now, not whenever Qt gets to it.

    `sync()` is the line that makes a write visible to a pane that reads the same key on
    its next sample, so the thread count Post-Processing reads is the one the Performance
    box just held rather than the one that was on disk when that pane opened.
    """
    store = settings()
    store.setValue(f'{group}/{key}', value)
    store.sync()


def read(group: str, key: str, default, kind=None):
    """One value out of the store, with the type the store was asked to answer in."""
    store = settings()
    return store.value(f'{group}/{key}', default, kind) if kind is not None \
        else store.value(f'{group}/{key}', default)
