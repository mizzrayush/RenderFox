"""The one way this app takes a background run off the interface it writes to.

Two ways a run ends this process, and both were measured here rather than read off a
list: a result that is already queued when its widgets are gone is delivered into
freed memory, and Qt answers that with a heap fault (0xc0000374) instead of a
traceback anybody could catch; dropping the last Python reference of a worker that is
still running is answered with an abort. So a pane that is being shut down has to
disconnect first, ask second, and keep holding whatever refused to stop.

The channels are read from the worker's own meta-object rather than from a list typed
next to the pane, because a hand-written list silently forgets the signal somebody
adds later - and a forgotten one is exactly the one that arrives after the window has
gone.
"""

import threading

from PyQt6.QtCore import QObject, QThread

# Qt's own housekeeping. `finished` is deliberately NOT here: a pane connects its own
# cleanup to it, and that cleanup writes to the widgets this module exists to protect.
_PRIVATE = ('destroyed', 'objectNameChanged')

# The spellings a cancellation request takes in this app, counted by reading every run
# class rather than by guessing: `request_stop` in the Point Clouds, Pipeline,
# Pre-Processing and automation runs, `request_cancel` in Post-Processing, `cancel` in
# the thumbnail, video and texture-engine runs, and `stop` on the ScriptExecutor - which
# the pane's own Stop button already reaches through `ScriptEngine.stop_execution`.
# `terminate` is deliberately absent: killing a thread mid-call is not a stop this app
# asks for anywhere else, and a close is not the place to start. A test reads the source
# and fails if a fifth spelling appears, because a run whose verb this list misses is
# stopped by nothing and the close only waits for it.
_STOP_VERBS = ('request_stop', 'request_cancel', 'cancel', 'stop')


def _signal_names(owner: QObject):
    """Every signal `owner` can emit, named by Qt rather than by this app's memory."""
    meta = owner.metaObject()
    names = []
    for index in range(meta.methodCount()):
        method = meta.method(index)
        if method.methodType() != method.MethodType.Signal:
            continue
        name = bytes(method.name()).decode()
        if name not in _PRIVATE and name not in names:
            names.append(name)
    return names


def channels(runner):
    """`(name, bound signal)` for everything this runner can push into the interface.

    A `QThread` subclass carries its signals on itself; the house `Worker` is a
    `QRunnable` - not a `QObject`, so it has no signals of its own - and carries them
    on its `signals` object. Only the `QObject` half of a runner is asked.
    """
    attached = getattr(runner, 'signals', None)
    owners = [owner for owner in (runner, attached) if isinstance(owner, QObject)]
    found = []
    for owner in owners:
        for name in _signal_names(owner):
            signal = getattr(owner, name, None)
            if signal is None or any(name == known for known, _ in found):
                continue
            found.append((name, signal))
    return found


def silence(runner):
    """Take every receiver off this runner and answer with the names that came off.

    A signal with nothing connected raises `TypeError` for `disconnect()` with no
    arguments; that is the same fact as "this runner cannot reach the interface", so it
    is reported as not taken off rather than as a failure.
    """
    removed = []
    for name, signal in channels(runner):
        try:
            signal.disconnect()
        except TypeError:
            continue
        removed.append(name)
    return removed


def ask_to_stop(runner) -> bool:
    """Ask the run to stop if it can be asked, and say whether it could.

    A worker with no cancellation path runs to its end whatever this returns; the pane
    still has to wait for it or keep holding it, and it must not pretend the close
    stopped it.
    """
    for verb in _STOP_VERBS:
        request = getattr(runner, verb, None)
        if callable(request):
            request()
            return True
    return False


def wait_for_runs(runners, timeout_ms: int = 5000, pool=None):
    """Split the runners into the ones that ended and the ones that did not.

    Threads are waited on one at a time, and both kinds are asked: a `QThread` answers
    `wait`, and a plain `threading.Thread` - which is what the Automation pane's Auto
    Actions worker is - answers `join`, in seconds rather than milliseconds. A pool is
    waited on as a pool, because that is the question `QThreadPool` answers - and a caller
    that hands over pool work with no pool cannot be told it finished, so that work comes
    back as still running.
    """
    ended, running = [], []
    for runner in list(runners):
        if isinstance(runner, QThread):
            (ended if runner.wait(timeout_ms) else running).append(runner)
        elif isinstance(runner, threading.Thread):
            runner.join(timeout_ms / 1000)
            (running if runner.is_alive() else ended).append(runner)
        elif pool is not None:
            (ended if pool.waitForDone(timeout_ms) else running).append(runner)
        else:
            running.append(runner)
    return ended, running


def release_from(workers, ended) -> int:
    """Let go of the workers that finished, and return how many that was.

    Only the finished ones: the reference of a running worker is the only thing between
    this process and Qt's abort.
    """
    released = 0
    for runner in ended:
        if runner in workers:
            workers.remove(runner)
            released += 1
    return released


def drain(workers, timeout_ms: int = 5000, pool=None):
    """Silence, ask, wait and let go of one list of runs; answer the ones still running.

    The order is the point. A handler still connected when the wait begins delivers its
    verdict into the widgets this exists to protect, and a stop request that makes a
    worker emit `finished` to a pane already on its way out does the same - so the
    receivers come off before the asking, and the asking before the waiting.

    `workers` keeps whatever outlasts the wait, because the reference of a running worker
    is the only thing between this process and Qt's abort.
    """
    for runner in list(workers):
        silence(runner)
        ask_to_stop(runner)
    ended, running = wait_for_runs(workers, timeout_ms, pool)
    release_from(workers, ended)
    return running


def drain_attributes(owner, names, timeout_ms: int = 5000, pool=None):
    """Silence, ask and wait the runs a pane keeps in the named attributes.

    Most panes hold one run in one attribute instead of a list, and the attribute is what
    its own Cancel button reads. A run that ended has its attribute set to None so the
    next Cancel finds nothing to cancel; a run that outlasted the wait keeps its
    attribute holding it, because that reference is the only thing between this process
    and Qt's abort - which is also what the pane's `isRunning()` guards lean on.
    Returns the runs still owed to the pane.
    """
    running = []
    for name in names:
        runner = getattr(owner, name, None)
        if runner is None:
            continue
        silence(runner)
        ask_to_stop(runner)
        ended, still = wait_for_runs([runner], timeout_ms, pool)
        if ended:
            setattr(owner, name, None)
        else:
            running.extend(still)
    return running


def shutdown(app):
    """Take every window down while `app` is still alive to run the delete queue.

    Who holds the last reference to a top-level widget decides how a PyQt6 process leaves. Held
    by a frame that raises `SystemExit` - `sys.exit(app.exec())`, the shape this app's entry point
    shipped with - it survives to interpreter finalization, after `QApplication` is gone, and the
    C++ delete that follows is what `#50` recorded as `0xc0000409`: a fast fail, no traceback,
    nothing on stdout. `#50` recorded precisely that from `tests/verify_all_fixes.py`, a run that
    printed `Ran 6 tests in 20.1s / OK` and left with a fail code - 3 times in 6 subprocess runs of
    one tree and 1 in 6 of another.

    This is the shape that cannot lose that race, because the windows go while `app` is still
    there to run the queue. It is not claimed as a crash this phase cured: measured since, the
    abort does not reproduce, twenty-two child processes over six shapes - the frame that raises
    `SystemExit`, the drained quit, a module global, a module global with an `atexit` report of
    its 73 surviving widgets, and `verify_all_fixes.py` on both the committed file and this one -
    returned 0 twenty-two times. `tools/check_clean_exit.py` is what keeps it gone; run over the
    tree as `#50` left it, it named ten findings in the five files that ended a loop that way -
    `main.py` and the four panes with a hand-run `__main__` block, each one both the exit and no
    drain - which is the before this change is measured against.

    Only what is on screen is closed. A window that has already answered its own `closeEvent` -
    the normal quit, and every pane's drain-every-holder walk - is not asked twice, because
    `MainWindow.closeEvent` is where a running render refuses the exit. Returns the class names of
    anything still visible afterwards, which is what a `closeEvent` calling `event.ignore()`
    produces on purpose; `main.py` writes them rather than quitting quiet.
    """
    owed = []
    for widget in list(app.topLevelWidgets()):
        if widget.isVisible():
            widget.close()
        widget.deleteLater()
    app.processEvents()
    for widget in app.topLevelWidgets():
        if widget.isVisible():
            owed.append(type(widget).__name__)
    return owed
