"""The records written before the Diagnostics pane exists.

`main.py` reports a missing window icon, a missing splash image and a failed action
registration, and all three happen before `MainWindow` builds the pane whose `setup_logging`
attaches the handler. A log call with no handler on the root logger does not vanish quietly:
Python's `logging.lastResort` writes it to stderr, and `RenderFox.spec` builds the app with
`console=False`, so that stream is discarded exactly like a `print`. The startup reports need a
queue that survives the pane's absence and a pane that plays it back when it appears.

Nothing here installs itself. `main.py` calls `install()` as the first thing it does, and only
the running app does that - a test that builds a pane without installing the buffer gets the
empty table it has always got, so this cannot add rows to a suite it was not written for.
"""

import logging

# A startup that fails hard can reach this queue from a loop; the cap is what stops a buffer that
# nobody will ever read from turning into the memory the app does not have.
EARLY_LIMIT = 200

_records = []


class EarlyLogHandler(logging.Handler):
    """Hold records instead of dropping them, until a pane exists to show them."""

    def emit(self, record) -> None:
        if len(_records) < EARLY_LIMIT:
            _records.append(record)


def install() -> bool:
    """Put the buffer on the root logger; answer whether this call is the one that did.

    The answer is not cosmetic: a second `main()` in the same process - a test that drives the
    entry point, a rebuilt window - must not stack a second queue in front of the first.
    """
    root = logging.getLogger()
    if any(isinstance(handler, EarlyLogHandler) for handler in root.handlers):
        return False
    root.addHandler(EarlyLogHandler())
    return True


def take() -> list:
    """The records held so far, oldest first, leaving the buffer empty.

    Draining rather than peeking is the point: a second pane must not show the same startup row
    twice, and a row that has been read has nowhere else to come from.
    """
    held = list(_records)
    del _records[:]
    return held
