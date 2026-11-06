"""Who drew a frame, and when: the app's only source of frame timing.

A frame rate can only come from frames. Nothing outside a 3D view knows whether that
view drew: a view that has never been shown, a view sitting behind another tab, a
driver that refused a context and a paint that raised all look the same from the
performance pane. The code this replaced answered them with the gap between two
monitoring samples - the timer fires once a second whatever the screen does, so a view
that drew nothing reported about one frame per second and about a second per frame, and
the 0.016 s written under it as the empty-history case could not be reached. None of it
reached a screen either: no pane read those two fields.

So each view stamps its own finished frames here, and a rate is only ever arithmetic
on the gaps between stamps. Where there are no gaps to take, the answer says which
kind of nothing it is instead of producing a number.
"""

import time
from collections import deque
from datetime import datetime

WINDOW_SECONDS = 1.0


class FrameClock:
    """The stamps of the frames the app's own views finished drawing."""

    def __init__(self, keep: int = 240) -> None:
        self._stamps = deque(maxlen=keep)
        self._failures = deque(maxlen=20)
        self._blocked = None
        self._monotonic = time.perf_counter
        self._wall = time.time
        self.total_frames = 0
        self.started_at = self._wall()

    def note_frame(self, source, at=None) -> None:
        """Record one frame that finished. Called by the widget that drew it."""
        stamp = self._monotonic() if at is None else float(at)
        self._stamps.append((stamp, str(source)))
        self.total_frames += 1

    def note_failure(self, reason) -> None:
        """Record a paint that raised. It is not a frame, and saying so is the point."""
        self._failures.append(f'{type(reason).__name__}: {reason}')

    def note_blocked(self, reason) -> None:
        """Record a view that says it cannot draw at all on this machine."""
        self._blocked = str(reason)

    def clear(self) -> None:
        self._stamps.clear()
        self._failures.clear()
        self._blocked = None
        self.total_frames = 0
        self.started_at = self._wall()

    def stats(self, window_seconds: float = WINDOW_SECONDS) -> dict:
        """Rate over the last `window_seconds`, or the reason there is no rate.

        The window is measured from now, not from the newest stamp. Anchoring it on
        the newest stamp would let a burst that stopped five seconds ago keep being
        reported as the current frame rate, which is the same mistake as the sample
        interval it replaced.
        """
        now = self._monotonic()
        window = float(window_seconds)
        recent = [s for s in self._stamps if s[0] >= now - window]
        gaps = [later[0] - earlier[0]
                for earlier, later in zip(recent, recent[1:])]
        gaps = [g for g in gaps if g > 0.0]
        span = (recent[-1][0] - recent[0][0]) if len(recent) > 1 else 0.0

        answer = {
            'frames': len(recent),
            'window_seconds': window,
            'fps': None,
            'frame_time_ms': None,
            'slowest_frame_ms': None,
            'sources': sorted({name for _, name in recent}),
            'total_frames': self.total_frames,
            'last_frame_seconds_ago': ((now - self._stamps[-1][0])
                                       if self._stamps else None),
            'failures': len(self._failures),
            'last_failure': (self._failures[-1] if self._failures else None),
            'blocked': self._blocked,
            'reason': '',
            'measured_at': datetime.fromtimestamp(self._wall()).isoformat(
                timespec='seconds'),
        }

        if len(recent) > 1 and span > 0.0:
            answer['fps'] = round((len(recent) - 1) / span, 1)
            answer['frame_time_ms'] = round(1000.0 * sum(gaps) / len(gaps), 2)
            answer['slowest_frame_ms'] = round(1000.0 * max(gaps), 2)
        elif not self._stamps:
            answer['reason'] = (
                'no 3D view has drawn a frame since the app started'
                + (f' - the view itself said: {self._blocked}' if self._blocked
                   else '; nothing was reported as blocking it'))
        elif not recent:
            answer['reason'] = (
                f'nothing drew in the last {window:g} s'
                + (f' - the view itself said: {self._blocked}' if self._blocked
                   else f'; the last frame was drawn '
                        f'{answer["last_frame_seconds_ago"]:.3f} s ago'))
        elif len(recent) == 1:
            answer['reason'] = (
                f'one frame inside the {window:g} s window, and one frame is not '
                'a rate')
        else:
            answer['reason'] = (
                f'{len(recent)} frames carry the same timestamp, so no gap between '
                'them can be taken')
        return answer


SHARED = FrameClock()


def shared_clock() -> FrameClock:
    """The one clock the views stamp and the performance backend reads."""
    return SHARED


def note_frame(source, at=None) -> None:
    shared_clock().note_frame(source, at)


def note_failure(reason) -> None:
    shared_clock().note_failure(reason)


def note_blocked(reason) -> None:
    shared_clock().note_blocked(reason)
