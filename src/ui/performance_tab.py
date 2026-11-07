"""
Performance pane: the readings the engine takes and the settings the engine reads.

This pane samples nothing. There is no `psutil` and no `GPUtil` import here on purpose: the
one reader of the machine is `PerformanceMonitor`, the one reader of Windows is
`SystemInfo`, and every figure they hand over arrives beside the reason a field was refused.
Every box is built from `performance_controls.CONTROLS` - the pane owns no range, no item
list and no default - every button is named in `performance_controls.VERBS`, and what a box
changed is printed beside it in the engine's own words.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout,
                             QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QProgressBar, QPushButton, QScrollArea, QSpinBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from ..features import performance_controls
from ..features.performance_analyzer import BenchmarkRunner, PerformanceAnalyzer
from ..utils.run_teardown import drain
from ..utils.worker import Worker
from .icon_provider import get_icon

# The packaged build has no console (`RenderFox.spec`: console=False), so the only report
# channel a failure has is the root logger the Diagnostics pane reads.
logger = logging.getLogger(__name__)

GPU_POWER_NOTE = ("Nothing here measures what power the graphics chip draws - the tool that "
                  "reports how busy it is, its memory and its temperature does not report "
                  "power")
GPU_NOT_READ_NOTE = "not measured yet - press Detect GPU Hardware"
MEMORY_NOT_READ_NOTE = 'nothing read yet - press Analyze Memory Usage'
SAMPLE_NOT_READ_NOTE = 'not read yet - the monitor has not sampled'

NOTE_STYLE = 'color: #8c93a8; font-size: 8.5pt;'

# The largest number a figure box will let anybody type. It is deliberately far past every
# offer in the control table: the engine is what refuses a value outside the range it reads,
# and a box that refused first would hide both the number and the reason.
TYPABLE_LIMIT = 2_000_000_000

# How many readings the graphs hold. This is a widget width, not a measurement: it is the
# number of points that fit across the pane at the monitor's own one-second interval.
GRAPH_READINGS = 60

# The three lanes the graphs draw, each named for the field of a sample it reads. They are
# all percentages, which is why the axis is 0 to 100 and why that bound belongs here rather
# than in the engine.
SERIES = (('CPU %', 'cpu_percent'), ('Physical memory %', 'memory_percent'),
          ('Adapter load %', 'gpu_load_percent'))

LANE_COLORS = (QColor(75, 123, 236), QColor(46, 204, 113), QColor(231, 76, 60))

SAMPLE_COLUMNS = ['what the sample reads', 'value', 'the window it covers',
                  'why nothing was read']

# Every field of `PerformanceMetrics`, in the order the table shows them. The labels name
# the reading; the field names are the engine's, and this table has no other column.
SAMPLE_FIELDS = (
    ('CPU busy across the logical cores', 'cpu_percent', '%', 'the gap between two samples'),
    ('This process CPU', 'process_cpu_percent', '%', 'the gap between two samples'),
    ('Physical memory in use', 'memory_percent', '%', 'read at this instant'),
    ('Physical memory used', 'memory_used_mb', 'MB', 'read at this instant'),
    ('Physical memory available', 'memory_available_mb', 'MB', 'read at this instant'),
    ('This process resident', 'process_rss_mb', 'MB', 'read at this instant'),
    ('CPU frequency', 'cpu_frequency_mhz', 'MHz', 'the sensor reading at this instant'),
    ('Adapter load', 'gpu_load_percent', '%', 'the reader answer, cached for its own window'),
    ('Adapter memory share', 'gpu_memory_percent', '%',
     'the reader answer, cached for its own window'),
    ('Adapter memory used', 'gpu_memory_used_mb', 'MB',
     'the reader answer, cached for its own window'),
    ('Adapter temperature', 'gpu_temperature_c', 'degC',
     'the reader answer, cached for its own window'),
    ('Frames per second', 'fps', 'fps', 'the frames the app itself drew'),
    ('Frame time', 'frame_time_ms', 'ms', 'the gaps between finished frames'),
    ('Slowest frame in the window', 'slowest_frame_ms', 'ms', 'the worst gap in the window'),
    ('Frames counted', 'frames', 'frames', 'the stamps the views made in the window'),
)

CONTRACT_COLUMNS = ['on screen', 'what it is', 'does anything read it', 'stored under',
                    'what it changes, or why it cannot']


def note(text: str) -> QLabel:
    """A line of the pane's own explanation, in the style every other pane uses for one."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(NOTE_STYLE)
    return label


def rows_table(columns: List[str]) -> QTableWidget:
    """An empty table with the pane's headers; a row only ever arrives from an engine answer."""
    table = QTableWidget()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(len(columns) - 1, QHeaderView.ResizeMode.Stretch)
    return table


def fill(table: QTableWidget, rows: List[List[str]]) -> None:
    """Replace the whole table with the rows handed over, cell by cell as text."""
    table.setRowCount(0)
    for row in rows:
        position = table.rowCount()
        table.insertRow(position)
        for column, text in enumerate(row):
            table.setItem(position, column, QTableWidgetItem(text))


def cell(value: Any) -> str:
    """One engine value as a table cell: a dash for a reading the engine refused."""
    return '-' if value is None else str(value)


def value_text(entry: Dict[str, Any]) -> str:
    """One card or cell from a `memory_rows()` entry: the figure with its own unit."""
    if entry.get('value') is None:
        return entry.get('reason') or 'no reader answered this'
    return f"{entry['value']} {entry.get('unit', '')}".strip()


def describe_live(live: Optional[Dict[str, Any]]) -> str:
    """The engine's own answer to a value that changes this process right now.

    Nothing is added to it. Each verb returns the fields it wanted the user to see - what
    Windows reported back, what interval the collector took, which budget the check now
    holds - and this prints those, in the order the verb put them in.
    """
    if live is None:
        return 'stored only: nothing in this process reads it differently while it runs'
    if not isinstance(live, dict):
        return str(live)
    parts = []
    for name, value in live.items():
        if value in (None, '', [], {}):
            continue
        if isinstance(value, (list, tuple)):
            value = ', '.join(str(item) for item in value)
        parts.append(f'{name.replace("_", " ")}: {value}')
    return '; '.join(parts) or 'the verb answered nothing at all'


def describe_outcome(outcome: Dict[str, Any]) -> str:
    """One control's verdict: where the value went, and what ran because of it."""
    stored = outcome.get('stored') or {}
    if not stored.get('written'):
        return f'not stored - {stored.get("reason") or "this control stores no setting"}'
    text = f'stored {stored.get("read_back", stored.get("value"))}'
    if stored.get('key'):
        text += f' under {stored["key"]}'
    return text + ' | ' + describe_live(outcome.get('live'))


def describe_stored(item: performance_controls.Control, stored: Dict[str, Any],
                    offered: bool) -> str:
    """What the box holds before anybody touches it, and which code reads that value.

    A refused control says so in its own sentence rather than looking like a setting: this
    is the line that tells the difference between a box the app reads and a box that only
    looks like one.
    """
    if not item.wired:
        return f'this box changes nothing in this app - {item.refusal}'
    if not item.key:
        return f'not a stored setting - {item.reader}'
    text = (f'stored {stored["value"]}' if stored['stored']
            else f'default {item.default}')
    if stored['note']:
        text += f' - {stored["note"]}'
    if not offered:
        text += ' - the store holds a value this list does not offer'
    return text


def describe_profile(answer: Dict[str, Any]) -> str:
    """What applying a profile wrote, and every knob it could not write, named one by one."""
    if not answer:
        return 'the profile never ran: the value did not reach the store'
    written = answer.get('written') or []
    refused = answer.get('refused') or []
    parts = [f'wrote {len(written)} knob(s): '
             + (', '.join(row['label'] for row in written) or 'none')]
    if refused:
        parts.append(f'refused {len(refused)}: ' + '; '.join(refused))
    if answer.get('reason'):
        parts.append(answer['reason'])
    return ' | '.join(parts)


class SampleGraphs(QWidget):
    """Three percentage lanes drawn from the samples the monitor emitted.

    The widget stores no readings of its own: the pane hands it the values it kept from
    `metrics_updated`, so a graph and the table beside it can never disagree, and a lane
    with nothing behind it says which reader refused instead of drawing a flat zero.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.lanes: List[Tuple[str, List[Optional[float]], str]] = []
        self.setMinimumHeight(210)

    def set_lanes(self, lanes) -> None:
        self.lanes = list(lanes)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        base = self.palette().color(self.palette().ColorRole.Base)
        ink = self.palette().color(self.palette().ColorRole.Text)
        painter.fillRect(self.rect(), base)
        if not self.lanes:
            return
        band = self.height() // len(self.lanes)
        for index, lane in enumerate(self.lanes):
            self.draw_lane(painter, lane, index * band, band, ink)

    def draw_lane(self, painter: QPainter, lane, top: int, band: int, ink: QColor) -> None:
        """One lane: its frame, its title, and either its line or the reason it has none."""
        title, values, reason = lane
        painter.setPen(QPen(ink))
        painter.drawRect(0, top, self.width() - 1, band - 1)
        painter.drawText(6, top + 14, title)
        if len(values) < 2:
            painter.drawText(6, top + band // 2 + 4,
                             reason or 'waiting for a second reading - one point is not a '
                                       'line')
            return
        color = LANE_COLORS[LANE_INDEX.get(title, 0) % len(LANE_COLORS)]
        painter.setPen(QPen(color))
        usable = band - 22
        step = (self.width() - 12) / (GRAPH_READINGS - 1)
        first = len(values) - min(len(values), GRAPH_READINGS)
        for offset in range(1, len(values) - first):
            left = values[first + offset - 1]
            right = values[first + offset]
            if left is None or right is None:
                continue
            x1 = 6 + (first + offset - 1) * step
            x2 = 6 + (first + offset) * step
            y1 = top + band - 6 - (min(max(left, 0.0), 100.0) / 100.0) * usable
            y2 = top + band - 6 - (min(max(right, 0.0), 100.0) / 100.0) * usable
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        painter.setPen(QPen(ink))
        painter.drawText(self.width() - 90, top + 14,
                         f'{values[-1]:.1f}%' if values[-1] is not None else 'no reading')


LANE_INDEX = {title: index for index, (title, _) in enumerate(SERIES)}


class PerformanceTab(QWidget):
    """Performance monitoring and GPU acceleration controls."""

    performance_updated = pyqtSignal(dict)

    def __init__(self, parent=None, job_manager=None):
        super().__init__(parent)
        # `clear_caches` empties the caches this process owns and asks for the one it does
        # not - the detected-software table lives on the job manager, so the object that
        # holds it has to be handed in rather than guessed at.
        self.job_manager = job_manager
        self._workers = []
        self._controls: Dict[str, QWidget] = {}
        self._effects: Dict[str, QLabel] = {}
        self._verbs: Dict[str, QPushButton] = {}
        self._cards: Dict[str, QLabel] = {}
        self.benchmark_results: List[Dict[str, Any]] = []
        self.gpu_report: Optional[Dict[str, Any]] = None
        self.storage_info: Optional[Dict[str, Any]] = None
        self.last_sample: Optional[Dict[str, Any]] = None
        self.series: Dict[str, List[Optional[float]]] = {field: [] for _, field in SERIES}
        self.sample_reasons: Dict[str, str] = {}
        self.samples_kept = 0

        self.performance_analyzer = PerformanceAnalyzer()

        self.init_ui()
        self.setup_connections()
        self.start_monitoring()

    # ---- the one way a started run is held and released -------------------------

    def _keep_worker(self, worker):
        """Hold a started run until it says it is done.

        Without the reference this pane has nothing to take the handlers off of when the
        window closes, and a run still queued at that moment writes its measurement into
        labels Qt has already destroyed. The run releases itself through its own
        `finished`, so a long session does not accumulate every measurement it made.
        """
        self._workers.append(worker)
        worker.signals.finished.connect(lambda: self._release_worker(worker))
        return worker

    def _release_worker(self, worker):
        """Let a run go when it says it is done - once, whoever else let go first.

        The removal is guarded because `shutdown_runs` releases the same worker on its way
        out; a second `list.remove` of it raises inside a slot, and PyQt answers an
        exception that escapes a slot by ending the process.
        """
        if worker in self._workers:
            self._workers.remove(worker)

    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Silence every run this pane started and wait for the pool that runs them.

        The measurements arrive through `result`, fail through `error`, and drive the bar
        through `progress` - three channels into widgets that are on their way out. These
        runs are `QRunnable`s on the shared pool rather than threads, so there is no stop
        to ask of one and the wait is the only question a pool answers: did its queue
        drain. What has not drained stays held here.
        Returns the runs still owed to the pool when the wait gave up.
        """
        return len(drain(self._workers, timeout_ms, QThreadPool.globalInstance()))

    def closeEvent(self, event):
        """Take the timers off the machine on the way out.

        The monitor's sample timer, the collector's timer and this pane's repaint timer all
        write into widgets. A closed tab that keeps them running keeps sampling a machine it
        is no longer showing, and keeps a timer alive on a widget whose C++ object is gone.
        """
        self.update_timer.stop()
        self.performance_analyzer.stop_everything()
        self.shutdown_runs()
        super().closeEvent(event)

    # ---- the controls, built off the table --------------------------------------

    def make_control_row(self, name: str):
        """One table row turned into a widget, a report line, and the connection between them."""
        item = performance_controls.control(name)
        widget = self.build_widget(item)
        widget.setObjectName(name)
        self._controls[name] = widget
        setattr(self, name, widget)
        effect = note('')
        self._effects[name] = effect
        self.connect_control(item, widget)
        field = QWidget()
        box = QVBoxLayout(field)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(widget)
        box.addWidget(effect)
        return (None if item.kind == 'check' else f'{item.label}:'), field

    def build_widget(self, item) -> QWidget:
        """Build the widget the table row describes, taking its bounds from the row alone."""
        if item.kind == 'spin':
            widget = QSpinBox()
            # The offer in `item.bounds` is enforced by the engine, which refuses a value
            # outside it and names both numbers; the widget only bounds what can be typed,
            # so an extreme is seen and refused rather than rewritten before the user reads
            # the reason - the same rule the crop box in Point Clouds follows.
            widget.setRange(0, TYPABLE_LIMIT)
            if item.suffix:
                widget.setSuffix(f' {item.suffix}')
            widget.setKeyboardTracking(False)
        elif item.kind == 'combo':
            widget = QComboBox()
            if not item.variable:
                widget.addItems([str(option) for option in item.bounds])
        elif item.kind == 'check':
            widget = QCheckBox(item.label)
        else:
            widget = QLineEdit()
            widget.setPlaceholderText('the name to store these values under')
        return widget

    def connect_control(self, item, widget) -> None:
        """One door per stored value: every change goes through `apply_control`.

        A control with no stored setting is left unconnected on purpose. It has no key, so
        the engine's only answer would be its refusal, and a box that reports a refusal on
        every click reads like a broken box rather than an honest one - the sentence beside
        it already says what nothing reads.
        """
        name = item.widget
        if not item.key:
            return
        if item.kind == 'spin':
            widget.valueChanged.connect(
                lambda value, control=name: self.change_control(control, value))
        elif item.kind == 'combo':
            widget.currentTextChanged.connect(
                lambda value, control=name: self.change_control(control, value))
        elif item.kind == 'check':
            widget.toggled.connect(
                lambda value, control=name: self.change_control(control, value))

    def change_control(self, name: str, value: Any) -> None:
        """Store one control, run the verb it owns, and print the answer beside the box."""
        outcome = self.performance_analyzer.apply_control(name, value)
        self._effects[name].setText(describe_outcome(outcome))
        if name == 'profile_combo':
            self._effects[name].setText(describe_profile(outcome.get('live') or {}))
            self.paint_controls_from_store()
            self._effects[name].setText(describe_profile(outcome.get('live') or {}))
        if name in ('buffer_size_spin', 'memory_mapping_cb'):
            self.paint_benchmark_work()

    def set_stored_value(self, item, widget, value: Any) -> bool:
        """Put the widget at the stored value; answer with whether it can show it at all."""
        if item.kind == 'spin':
            widget.setValue(value if isinstance(value, int) else item.default)
        elif item.kind == 'combo':
            index = widget.findText(str(value))
            if index < 0:
                widget.setCurrentIndex(-1)
                return False
            widget.setCurrentIndex(index)
        elif item.kind == 'check':
            widget.setChecked(bool(value))
        return True

    def paint_control(self, name: str) -> None:
        """Read one control off the store and repaint it and its report line."""
        item = performance_controls.control(name)
        widget = self._controls[name]
        stored = performance_controls.read_control(item)
        widget.blockSignals(True)
        offered = self.set_stored_value(item, widget, stored['value'])
        widget.blockSignals(False)
        self._effects[name].setText(describe_stored(item, stored, offered))

    def paint_controls_from_store(self) -> None:
        """Paint every stored control with its own value and its reader's sentence.

        The signals are blocked while the values land: a pane that wrote `max_threads` back
        into the store because it painted it would make the screen the author of the
        settings, and the next reader would find a number nobody chose.
        """
        for name in list(self._controls):
            self.paint_control(name)

    def refresh_variable_controls(self) -> None:
        """Fill the two lists that come off the machine, not off the table.

        The profiles are `PerformanceProfiles.names()` - the built-ins plus whatever
        `profiles.json` holds - and the devices are the names Windows answered when Detect
        ran. Before Detect has answered, the device box offers the default alone, because
        the pane has no adapter list to invent one from.
        """
        names = self.performance_analyzer.profiles.names()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        self.profile_combo.blockSignals(False)

        adapters = (self.gpu_report or {}).get('adapters') or []
        devices = [performance_controls.CONTROLS['gpu_device_combo'].default]
        devices += [adapter['name'] for adapter in adapters if adapter.get('name')]
        self.gpu_device_combo.blockSignals(True)
        self.gpu_device_combo.clear()
        self.gpu_device_combo.addItems(devices)
        self.gpu_device_combo.blockSignals(False)

    def apply_stored_settings(self) -> Dict[str, Any]:
        """Run the stored values back into this process, once, at start-up.

        The pane does not do this when it is built: a monitoring tab constructed by a test,
        a screenshot run or a second window should not become the thing that changes this
        process's priority class or pins its cores. The main window asks for it, and the
        answer is printed beside the boxes it touched.
        """
        answer = self.performance_analyzer.refresh_from_settings()
        for name in list(self._controls):
            self.paint_control(name)
        from_store = [row for row in answer['applied'] if row['source'] == 'store']
        ran = [row['widget'] for row in from_store if row['live'] is not None]
        for row in answer['applied']:
            line = f'{"stored" if row["source"] == "store" else "default"} {row["value"]}'
            if row.get('live') is not None:
                self._effects[row['widget']].setText(
                    f'{line} | {describe_live(row["live"])}')
            elif row.get('reason') == performance_controls.RESTART_NOTE:
                # Refusing to re-run a knob is a verdict about that box, so it belongs beside
                # the box and not only in the count printed under the block.
                self._effects[row['widget']].setText(f'{line} - {row["reason"]}')
        unreadable = self.performance_analyzer.profiles.load_reason()
        listing = (f'; the profile file was refused, so the list holds only the built-ins: '
                   f'{unreadable}' if unreadable else
                   f'; the profile list holds '
                   f'{", ".join(self.performance_analyzer.profiles.names())}')
        self.store_note.setText(
            f'{len(from_store)} of the {answer["count"]} controls this pane stores were read '
            f'out of the store, and {len(ran)} of those ran a verb on this process: '
            f'{", ".join(ran) or "none"} - {answer["reason"]}' + listing)
        self.paint_benchmark_work()
        return answer

    def control_group(self, title: str, names: List[str],
                      blurb: Optional[str] = None) -> QGroupBox:
        """A titled block of controls, with a line saying which of them the app reads.

        The blurb counts the wired rows off the table rather than repeating a number that
        would go stale the day a row is wired up.
        """
        group = QGroupBox(title)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(16)
        for name in names:
            label, field = self.make_control_row(name)
            if label is None:
                form.addRow(field)
            else:
                form.addRow(label, field)
        if blurb:
            wired = sum(1 for name in names
                        if performance_controls.control(name).wired)
            tail = note(f'{wired} of {len(names)} boxes on this block name a reader; '
                        f'the rest carry the reason nothing reads them, printed beside them. '
                        f'{blurb}')
            form.addRow(tail)
        group.setLayout(form)
        return group

    # ---- the pane ---------------------------------------------------------------

    def init_ui(self) -> None:
        """Six blocks of work, in the order the engine answers them."""
        layout = QVBoxLayout(self)
        self.performance_tabs = QTabWidget()
        self.performance_tabs.addTab(self.create_gpu_tab(), 'GPU Acceleration')
        self.performance_tabs.addTab(self.create_monitor_tab(), 'System Monitor')
        self.performance_tabs.addTab(self.create_analysis_tab(), 'Analysis')
        self.performance_tabs.addTab(self.create_benchmark_tab(), 'Benchmarks')
        self.performance_tabs.addTab(self.create_optimization_tab(), 'Optimization')
        self.performance_tabs.addTab(self.create_memory_tab(), 'Memory')
        layout.addWidget(self.performance_tabs)

    def scrolled(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def create_gpu_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)

        detection_group = QGroupBox('GPU Detection')
        detection_layout = QVBoxLayout()
        self.detect_gpu_btn = QPushButton('Detect GPU Hardware')
        self.detect_gpu_btn.setIcon(get_icon('scan'))
        self.detect_gpu_btn.setProperty('primary', 'true')
        self.gpu_info_display = QTextEdit()
        self.gpu_info_display.setMinimumHeight(180)
        self.gpu_info_display.setMaximumHeight(350)
        self.gpu_info_display.setReadOnly(True)
        self.gpu_info_display.setPlainText(
            "Nothing has been asked yet. 'Detect GPU Hardware' asks Windows which adapters "
            'are fitted here and what can be read off them now.')
        detection_layout.addWidget(self.detect_gpu_btn)
        detection_layout.addWidget(self.gpu_info_display)
        detection_layout.addWidget(note(
            'Each question to Windows costs about a second, so they run on a worker and only '
            'when this button is pressed. The four status rows below are that reading; the '
            'live figures are in the System Monitor table.'))
        detection_group.setLayout(detection_layout)
        layout.addWidget(detection_group)

        layout.addWidget(self.control_group('GPU Acceleration Settings', [
            'enable_gpu_cb', 'gpu_device_combo', 'gpu_memory_spin',
            'compute_capability_combo', 'precision_combo']))

        layout.addWidget(self.control_group('GPU-Accelerated Operations', [
            'gpu_rendering_cb', 'gpu_denoising_cb', 'gpu_mesh_processing_cb',
            'gpu_format_conversion_cb', 'gpu_lod_generation_cb']))

        status_group = QGroupBox('GPU Status')
        status_layout = QFormLayout()

        # Nothing has been read for these four rows at pane start. They used to be filled
        # with "45%", "6,847 MB", "72 degC", "285W" every two seconds, on a machine whose
        # utilisation no installed reader can answer for.
        self.gpu_utilization_label = QLabel(GPU_NOT_READ_NOTE)
        self.gpu_memory_used_label = QLabel(GPU_NOT_READ_NOTE)
        self.gpu_temperature_label = QLabel(GPU_NOT_READ_NOTE)
        self.gpu_power_label = QLabel(GPU_POWER_NOTE)

        status_layout.addRow('GPU Utilization:', self.gpu_utilization_label)
        status_layout.addRow('Memory Used:', self.gpu_memory_used_label)
        status_layout.addRow('Temperature:', self.gpu_temperature_label)
        status_layout.addRow('Power Draw:', self.gpu_power_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        layout.addStretch()
        return self.scrolled(widget)

    def create_monitor_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        graphs_group = QGroupBox('Readings the monitor took')
        graphs_layout = QVBoxLayout()
        self.graphs = SampleGraphs()
        graphs_layout.addWidget(self.graphs)
        graphs_layout.addWidget(note(
            'The axis is 0 to 100 percent and the line is the samples '
            '`PerformanceMonitor` emitted, one per second, each covering the gap between two '
            'of its own reads. This widget measures nothing: it draws the values the pane was '
            'handed, and prints the refusing reader instead of a flat zero.'))
        graphs_group.setLayout(graphs_layout)
        layout.addWidget(graphs_group)

        sample_group = QGroupBox('This sample')
        sample_layout = QVBoxLayout()
        self.sample_table = rows_table(SAMPLE_COLUMNS)
        sample_layout.addWidget(self.sample_table)
        self.sample_status = note('no sample has been handed over yet')
        sample_layout.addWidget(self.sample_status)
        self.window_row = note('')
        sample_layout.addWidget(self.window_row)
        sample_group.setLayout(sample_layout)
        layout.addWidget(sample_group)

        info_layout = QHBoxLayout()

        cpu_group = QGroupBox('CPU Information')
        cpu_layout = QFormLayout()
        self.cpu_model_label = QLabel('-')
        self.cpu_cores_label = QLabel('-')
        self.cpu_threads_label = QLabel('-')
        self.cpu_frequency_label = QLabel('-')
        cpu_layout.addRow('Model:', self.cpu_model_label)
        cpu_layout.addRow('Cores:', self.cpu_cores_label)
        cpu_layout.addRow('Threads:', self.cpu_threads_label)
        cpu_layout.addRow('Frequency:', self.cpu_frequency_label)
        cpu_group.setLayout(cpu_layout)
        info_layout.addWidget(cpu_group)

        memory_group = QGroupBox('Memory Information')
        memory_layout = QFormLayout()
        self.memory_total_label = QLabel('-')
        self.memory_available_label = QLabel('-')
        self.memory_used_label = QLabel('-')
        self.memory_cached_label = QLabel('-')
        memory_layout.addRow('Total:', self.memory_total_label)
        memory_layout.addRow('Available:', self.memory_available_label)
        memory_layout.addRow('Used:', self.memory_used_label)
        memory_layout.addRow('Cached:', self.memory_cached_label)
        memory_group.setLayout(memory_layout)
        info_layout.addWidget(memory_group)

        storage_group = QGroupBox('Storage Information')
        storage_layout = QFormLayout()
        self.storage_total_label = QLabel('-')
        self.storage_used_label = QLabel('-')
        self.storage_free_label = QLabel('-')
        self.storage_type_label = QLabel('-')
        storage_layout.addRow('Total:', self.storage_total_label)
        storage_layout.addRow('Used:', self.storage_used_label)
        storage_layout.addRow('Free:', self.storage_free_label)
        storage_layout.addRow('Type:', self.storage_type_label)
        storage_group.setLayout(storage_layout)
        info_layout.addWidget(storage_group)

        layout.addLayout(info_layout)
        layout.addWidget(note(
            'The CPU and memory rows come from one worker that asks `SystemInfo` and the '
            'analyzer once; the storage rows come from the volume worker. The table above is '
            'the only place that refreshes itself, because the monitor is the only thing that '
            'runs on a timer.'))
        layout.addStretch()
        return self.scrolled(widget)

    def create_analysis_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        tools = QHBoxLayout()
        self.refresh_analysis_btn = QPushButton('Analyse This Sample')
        self.refresh_analysis_btn.setIcon(get_icon('chart'))
        self.refresh_analysis_btn.setProperty('primary', 'true')
        self.export_report_btn = QPushButton('Export Analysis Report')
        self.export_report_btn.setIcon(get_icon('export'))
        tools.addWidget(self.refresh_analysis_btn)
        tools.addWidget(self.export_report_btn)
        tools.addStretch()
        layout.addLayout(tools)

        self.analysis_status = note('nothing has been analysed yet - the tables below are '
                                    'empty because no analysis was asked for')
        layout.addWidget(self.analysis_status)

        display_group = QGroupBox('What this sample supports')
        display_layout = QVBoxLayout()
        self.analysis_display = QTextEdit()
        self.analysis_display.setReadOnly(True)
        self.analysis_display.setMinimumHeight(200)
        display_layout.addWidget(self.analysis_display)
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)

        findings_group = QGroupBox('Findings')
        findings_layout = QVBoxLayout()
        self.findings_table = rows_table(['kind', 'observed', 'limit', 'severity',
                                          'because'])
        findings_layout.addWidget(self.findings_table)
        findings_group.setLayout(findings_layout)
        layout.addWidget(findings_group)

        advice_group = QGroupBox('Advice, and the reading that caused it')
        advice_layout = QVBoxLayout()
        self.suggestions_table = rows_table(['category', 'priority', 'change', 'because',
                                             'where'])
        advice_layout.addWidget(self.suggestions_table)
        advice_group.setLayout(advice_layout)
        layout.addWidget(advice_group)

        trends_group = QGroupBox('Trend over the samples kept')
        trends_layout = QVBoxLayout()
        self.trends_table = rows_table(['field', 'average', 'peak', 'current',
                                        'samples', 'why not'])
        trends_layout.addWidget(self.trends_table)
        trends_group.setLayout(trends_layout)
        layout.addWidget(trends_group)

        profiling_group = QGroupBox('Timings the app recorded around its own operations')
        profiling_layout = QVBoxLayout()
        self.profiling_table = rows_table(['function', 'calls', 'total s', 'average s',
                                           'min s', 'max s'])
        profiling_layout.addWidget(self.profiling_table)
        profiling_layout.addWidget(note(
            'A row only appears for a call the app actually wrapped with '
            '`start_profiling()` / `end_profiling()`. Nothing here guesses at a timing.'))
        profiling_group.setLayout(profiling_layout)
        layout.addWidget(profiling_group)

        contract_group = QGroupBox('What every control on this pane is')
        contract_layout = QVBoxLayout()
        self.contract_table = rows_table(CONTRACT_COLUMNS)
        contract_layout.addWidget(self.contract_table)
        contract_group.setLayout(contract_layout)
        layout.addWidget(contract_group)

        layout.addStretch()
        return self.scrolled(widget)

    def create_benchmark_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls_group = QGroupBox('Benchmark Controls')
        controls_layout = QHBoxLayout()
        self.benchmark_cpu_btn = QPushButton('CPU Benchmark')
        self.benchmark_cpu_btn.setIcon(get_icon('performance'))
        self.benchmark_geometry_btn = QPushButton("Geometry Benchmark")
        self.benchmark_geometry_btn.setIcon(get_icon('rendered'))
        self.benchmark_memory_btn = QPushButton('Memory Benchmark')
        self.benchmark_memory_btn.setIcon(get_icon('diagnostics'))
        self.benchmark_storage_btn = QPushButton('Storage Benchmark')
        self.benchmark_storage_btn.setIcon(get_icon('backup'))
        self.benchmark_full_btn = QPushButton('Full System Benchmark')
        self.benchmark_full_btn.setIcon(get_icon('sparkles'))
        self.benchmark_full_btn.setProperty('primary', 'true')

        controls_layout.addWidget(self.benchmark_cpu_btn)
        controls_layout.addWidget(self.benchmark_geometry_btn)
        controls_layout.addWidget(self.benchmark_memory_btn)
        controls_layout.addWidget(self.benchmark_storage_btn)
        controls_layout.addWidget(self.benchmark_full_btn)
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)

        progress_group = QGroupBox('Benchmark Progress')
        progress_layout = QVBoxLayout()
        self.benchmark_progress = QProgressBar()
        self.benchmark_status = QLabel('Ready to run benchmarks')
        progress_layout.addWidget(self.benchmark_progress)
        progress_layout.addWidget(self.benchmark_status)
        self.benchmark_work = note('')
        progress_layout.addWidget(self.benchmark_work)
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        results_layout = QHBoxLayout()

        results_group = QGroupBox('Benchmark Results')
        results_table_layout = QVBoxLayout()
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        # The columns are the measurement, not a verdict about it. "Performance" and
        # "Rank" used to hold "Excellent" and "Top 1%": the first was a threshold the
        # work always beat, the second a percentile against results RenderFox has never
        # collected from anyone. The engine words these cells (row_cells), because a
        # table column is a claim and the claim belongs beside the number.
        self.results_table.setHorizontalHeaderLabels(
            ["Kind", "What ran", "Measured", "Against this app's own earlier runs"])
        results_table_layout.addWidget(self.results_table)
        results_group.setLayout(results_table_layout)
        results_layout.addWidget(results_group)

        comparison_group = QGroupBox('Performance Comparison')
        comparison_layout = QVBoxLayout()
        self.comparison_chart = QLabel('Run benchmarks to see performance comparison')
        self.comparison_chart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.comparison_chart.setMinimumHeight(200)
        self.comparison_chart.setWordWrap(True)
        self.comparison_chart.setFrameStyle(QFrame.Shape.StyledPanel)
        comparison_layout.addWidget(self.comparison_chart)
        comparison_group.setLayout(comparison_layout)
        results_layout.addWidget(comparison_group)

        layout.addLayout(results_layout)

        export_layout = QHBoxLayout()
        self.export_results_btn = QPushButton('Export Results')
        self.export_results_btn.setIcon(get_icon('export'))
        self.clear_results_btn = QPushButton('Clear Results')
        self.clear_results_btn.setIcon(get_icon('delete'))
        export_layout.addWidget(self.export_results_btn)
        export_layout.addWidget(self.clear_results_btn)
        export_layout.addStretch()
        layout.addLayout(export_layout)
        self.export_status = note('nothing has been exported yet')
        layout.addWidget(self.export_status)

        layout.addStretch()
        return self.scrolled(widget)

    def create_optimization_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        profiles_group = QGroupBox('Performance Profiles')
        profiles_layout = QVBoxLayout()
        selection = QHBoxLayout()
        profile_label, profile_field = self.make_control_row('profile_combo')
        selection.addWidget(QLabel(profile_label))
        selection.addWidget(profile_field)
        self.apply_profile_btn = QPushButton('Apply Profile')
        self.apply_profile_btn.setIcon(get_icon('settings'))
        selection.addWidget(self.apply_profile_btn)
        self.save_profile_btn = QPushButton('Save Custom Profile')
        self.save_profile_btn.setIcon(get_icon('backup'))
        selection.addWidget(self.save_profile_btn)
        name_label, name_field = self.make_control_row('profile_name_edit')
        selection.addWidget(QLabel(name_label))
        selection.addWidget(name_field)
        selection.addStretch()
        profiles_layout.addLayout(selection)
        self.store_note = note('')
        profiles_layout.addWidget(self.store_note)
        profiles_layout.addWidget(note(
            'The list above is `PerformanceProfiles.names()`: the profiles this app ships '
            'and the ones `profiles.json` holds. Applying one writes its knobs through the '
            'same store every box uses and names the ones it could not write.'))
        profiles_group.setLayout(profiles_layout)
        layout.addWidget(profiles_group)

        layout.addWidget(self.control_group('Threading & Parallelization', [
            'max_threads_spin', 'thread_priority_combo', 'multiprocessing_cb',
            'affinity_cb']))
        layout.addWidget(self.control_group('Memory Optimization', [
            'memory_limit_spin', 'garbage_collection_combo', 'memory_mapping_cb',
            'swap_usage_cb']))
        layout.addWidget(self.control_group('Cache Optimization', [
            'cache_size_spin', 'cache_policy_combo', 'preload_cache_cb',
            'compress_cache_cb'],
            blurb='A Clear Cache button is the cache this app really holds, not a size.'))
        layout.addWidget(self.control_group('I/O Optimization', [
            'buffer_size_spin', 'async_io_cb', 'batch_operations_cb'],
            blurb='Buffer Size and Memory Mapping are the two boxes the storage benchmark '
                   'reads; the Benchmarks pane shows what the next run will use.'))

        layout.addStretch()
        return self.scrolled(widget)

    def create_memory_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        overview_group = QGroupBox('Memory Usage Overview')
        overview_layout = QGridLayout()
        for column, (name, title) in enumerate((('total', 'Total Memory'),
                                                ('used', 'Used Memory'),
                                                ('available', 'Available'),
                                                ('cached', 'Cached'))):
            overview_layout.addWidget(self.create_memory_card(title, name), 0, column)
        overview_group.setLayout(overview_layout)
        layout.addWidget(overview_group)

        tools_layout = QHBoxLayout()

        cleanup_group = QGroupBox('Memory Cleanup')
        cleanup_layout = QVBoxLayout()
        self.clear_cache_btn = QPushButton('Clear Cache')
        self.clear_cache_btn.setIcon(get_icon('clean'))
        self.force_gc_btn = QPushButton('Force Garbage Collection')
        self.force_gc_btn.setIcon(get_icon('refresh'))
        self.trim_memory_btn = QPushButton('Trim Working Set')
        self.trim_memory_btn.setIcon(get_icon('cut'))
        self.analyze_memory_btn = QPushButton('Analyze Memory Usage')
        self.analyze_memory_btn.setIcon(get_icon('diagnostics'))
        cleanup_layout.addWidget(self.clear_cache_btn)
        cleanup_layout.addWidget(self.force_gc_btn)
        cleanup_layout.addWidget(self.trim_memory_btn)
        cleanup_layout.addWidget(self.analyze_memory_btn)
        cleanup_layout.addWidget(note(
            'Each of these asks the engine and prints what it answered. The four cards above '
            'are filled by the same rows, and one of them cannot be filled on this operating '
            'system - the reason is printed on the card.'))
        cleanup_group.setLayout(cleanup_layout)
        tools_layout.addWidget(cleanup_group)

        tools_layout.addWidget(self.control_group('Memory Allocation', [
            'heap_size_spin', 'stack_size_spin', 'pool_size_spin']))

        layout.addLayout(tools_layout)

        self.memory_status = note('no memory verb has run yet')
        layout.addWidget(self.memory_status)

        rows_group = QGroupBox('What every memory figure is')
        rows_layout = QVBoxLayout()
        self.memory_rows_table = rows_table(['what it is', 'value', 'the reader that answered',
                                             'why not'])
        rows_layout.addWidget(self.memory_rows_table)
        self.gc_label = note('')
        rows_layout.addWidget(self.gc_label)
        self.trim_label = note('')
        rows_layout.addWidget(self.trim_label)
        rows_group.setLayout(rows_layout)
        layout.addWidget(rows_group)

        layout.addStretch()
        return self.scrolled(widget)

    def create_memory_card(self, title: str, name: str) -> QFrame:
        """One card: a title and a line that stays empty until a reader answers.

        These used to be seeded with 16.0 / 8.5 / 7.5 / 2.3 GB and never refreshed, so the
        pane printed a machine it had never read. A card now holds no value until
        `memory_rows()` hands one over, with the reader that gave it.
        """
        card = QFrame()
        card.setFrameStyle(QFrame.Shape.StyledPanel)
        box = QVBoxLayout(card)
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value = QLabel(MEMORY_NOT_READ_NOTE)
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setWordWrap(True)
        box.addWidget(heading)
        box.addWidget(value)
        self._cards[name] = value
        return card

    def setup_connections(self) -> None:
        """Wire every button to the method the verb table names for it."""
        self.detect_gpu_btn.clicked.connect(self.detect_gpu_hardware)

        self.benchmark_cpu_btn.clicked.connect(self.run_cpu_benchmark)
        self.benchmark_geometry_btn.clicked.connect(self.run_geometry_benchmark)
        self.benchmark_memory_btn.clicked.connect(self.run_memory_benchmark)
        self.benchmark_storage_btn.clicked.connect(self.run_storage_benchmark)
        self.benchmark_full_btn.clicked.connect(self.run_full_benchmark)
        self.export_results_btn.clicked.connect(self.export_results)
        self.clear_results_btn.clicked.connect(self.clear_results)

        self.apply_profile_btn.clicked.connect(self.apply_performance_profile)
        self.save_profile_btn.clicked.connect(self.save_performance_profile)

        self.refresh_analysis_btn.clicked.connect(self.refresh_analysis)
        self.export_report_btn.clicked.connect(self.export_analysis_report)

        self.clear_cache_btn.clicked.connect(self.clear_memory_cache)
        self.force_gc_btn.clicked.connect(self.force_garbage_collection)
        self.trim_memory_btn.clicked.connect(self.trim_working_set)
        self.analyze_memory_btn.clicked.connect(self.analyze_memory_usage)

        self._verbs = {name: getattr(self, name) for name in performance_controls.VERBS}
        self.build_contract_table()

    def start_monitoring(self) -> None:
        """Hand the machine over to the backend and paint from what it already stores."""
        self.performance_analyzer.monitor.metrics_updated.connect(self.on_metrics_updated)
        self.performance_analyzer.start_monitoring(interval_ms=1000)

        self.refresh_variable_controls()
        self.paint_controls_from_store()
        self.paint_benchmark_work()
        self.paint_sample()
        self.refresh_machine_info()
        self.refresh_storage_info()

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.paint_live)
        self.update_timer.start(2000)

    # ---- the sample: one reader, one table, three lanes --------------------------

    @pyqtSlot(dict)
    def on_metrics_updated(self, metrics: dict) -> None:
        """Keep what the monitor measured. The GPU rows are not painted from here.

        This used to write `metrics['gpu_percent']` - a 0.0 the backend defaults when no
        reader answered - into the GPU rows, and the 2-second timer overwrote it with
        invented figures. GPU rows come from the adapter report now, because that is the
        only place that knows whether a reader said anything.
        """
        self.last_sample = metrics
        self.sample_reasons = dict(metrics.get('not_read') or {})
        for _, field in SERIES:
            series = self.series[field]
            series.append(metrics.get(field))
            if len(series) > GRAPH_READINGS:
                del series[:len(series) - GRAPH_READINGS]
        self.paint_sample()

        # Emit signal for other components
        self.performance_updated.emit(metrics)

    def paint_live(self) -> None:
        """Repaint what a timer may repaint at all: the sample table and the stored volumes.

        Nothing here asks the machine anything. A pane whose repaint timer called `psutil`
        would measure on the thread that paints, which is the defect the whole rewrite
        exists to end.
        """
        self.paint_sample()
        self.paint_storage_info()

    def paint_sample(self) -> None:
        """Show each field of the newest sample, or the reason that field was refused."""
        sample = self.last_sample or {}
        reasons = sample.get('not_read') or {}
        window = sample.get('window_seconds')
        rows = []
        for label, field, unit, basis in SAMPLE_FIELDS:
            value = sample.get(field)
            if value is None:
                text = reasons.get(field) or SAMPLE_NOT_READ_NOTE
                rows.append([label, text, basis, reasons.get(field, '')])
                continue
            rows.append([label, f'{value} {unit}'.strip(), basis, ''])
        fill(self.sample_table, rows)

        kept = len(self.performance_analyzer.monitor.metrics_history)
        if window:
            self.window_row.setText(
                f'The sample covers {window:.2f} s between two of the monitor\'s own reads; '
                f'{kept} samples are kept, and the CPU figure is the mean over that window, '
                f'not an instant.')
        else:
            self.window_row.setText(
                f'{kept} samples are kept; the first sample of a run has no window to '
                f'measure, so its CPU figure says so.')
        reader = sample.get('gpu_reader')
        if reader:
            self.sample_status.setText(f'Sample from the monitor; adapter reader: {reader}')
        else:
            self.sample_status.setText(
                'Sample from the monitor - no adapter reader is installed, so every adapter '
                'field below carries its reason')

        lanes = []
        for index, (title, field) in enumerate(SERIES):
            series = self.series[field]
            lanes.append((title, series, self.sample_reasons.get(field, '')))
        self.graphs.set_lanes(lanes)

    def refresh_machine_info(self) -> None:
        """Ask the two identity readers once, on a worker, and paint the rows they answer.

        `SystemInfo.get_cpu_info()` watches the cores for a fifth of a second to produce its
        percentage, so it cannot run on the thread that paints. The answer is kept on the
        pane and the timer only repaints it.
        """
        analyzer = self.performance_analyzer

        def identity_reader(progress_callback=None):
            from ..features.diagnostic_engine import SystemInfo
            return {'cpu': SystemInfo.get_cpu_info(),
                    'os': SystemInfo.get_os_info(),
                    'memory': analyzer.memory_rows()}

        worker = Worker(identity_reader)
        worker.signals.result.connect(self.show_machine_info)
        worker.signals.error.connect(self.on_identity_reader_failed)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_machine_info(self, answer: dict) -> None:
        """Paint the identity rows from the reader's own fields, including the absent ones."""
        cpu, operating, memory = answer['cpu'], answer['os'], answer['memory']
        self.cpu_model_label.setText(operating.get('processor')
                                      or 'the operating system reported no processor')
        physical, logical = cpu.get('physical_cores'), cpu.get('logical_cores')
        self.cpu_cores_label.setText(
            f'{physical} physical core(s)' if physical else
            'unknown - this machine reports no physical core count')
        self.cpu_threads_label.setText(
            f'{logical} logical processor(s)' if logical else
            'unknown - this machine reports no logical processor count')
        self.cpu_frequency_label.setText(f"{cpu.get('current_frequency')} "
                                         f"(max {cpu.get('max_frequency')})")
        for entry in memory['machine']:
            label = {'total': self.memory_total_label, 'available': self.memory_available_label,
                     'used': self.memory_used_label, 'cached': self.memory_cached_label
                     }.get(entry['card'])
            if label is not None:
                label.setText(value_text(entry))

    def on_identity_reader_failed(self, error) -> None:
        """The identity rows say the reader died; they do not fall back to a dash."""
        kind, value, _traceback = error
        text = f'identity reader failed: {kind.__name__}: {value}'
        for label in (self.cpu_model_label, self.cpu_cores_label, self.cpu_threads_label,
                      self.cpu_frequency_label, self.memory_total_label,
                      self.memory_available_label, self.memory_used_label,
                      self.memory_cached_label):
            label.setText(text)
        logger.warning('Performance identity reader failed: %s: %s', kind.__name__, value)

    def detect_gpu_hardware(self):
        """Ask the machine which display adapters it has, and what can be read off them now.

        Each question to Windows costs about a second, so they run on a background thread
        and only when this button is pressed; the answer is kept for the status rows until
        the next press.
        """
        self.detect_gpu_btn.setEnabled(False)
        self.gpu_info_display.setPlainText('Asking Windows which adapters are present...')

        def worker_func(progress_callback=None):
            from ..features.diagnostic_engine import SystemInfo
            return SystemInfo.get_gpu_report()

        worker = Worker(worker_func)
        worker.signals.result.connect(self.show_gpu_report)
        worker.signals.error.connect(self.on_machine_reader_failed)
        worker.signals.finished.connect(lambda: self.detect_gpu_btn.setEnabled(True))
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_gpu_report(self, report: dict) -> None:
        """Paint the adapter answer, and name what could not be read instead of showing zero."""
        self.gpu_report = report
        self.gpu_info_display.setPlainText(report['text'])

        adapters = report['adapters']
        live = adapters[0]['live'] if adapters else None
        if live:
            self.gpu_utilization_label.setText(f"{live['load_percent']}% busy")
            self.gpu_memory_used_label.setText(
                f"{live['memory_used_mb']} MB "
                f"({live['memory_percent']}% of the memory Windows records here)")
            self.gpu_temperature_label.setText(f"{live['temperature_c']} degC")
        else:
            reason = report.get('load_reason') or (
                'no adapter was identified, so there is nothing to measure'
                if not adapters else
                'nothing on this machine reports what this adapter is doing')
            for label in (self.gpu_utilization_label, self.gpu_memory_used_label,
                          self.gpu_temperature_label):
                label.setText(reason)
        self.gpu_power_label.setText(GPU_POWER_NOTE)

        self.refresh_variable_controls()
        self.paint_control('gpu_device_combo')

    def refresh_storage_info(self) -> None:
        """Read the volumes and the disk behind them once, on a background thread."""
        def worker_func(progress_callback=None):
            from ..features.diagnostic_engine import SystemInfo
            return SystemInfo.get_storage_info()

        worker = Worker(worker_func)
        worker.signals.result.connect(self.show_storage_info)
        worker.signals.error.connect(self.on_machine_reader_failed)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_storage_info(self, storage: dict) -> None:
        """Keep the answer; the repaint timer paints it, so nothing blocks on Windows again."""
        self.storage_info = storage
        self.paint_storage_info()

    def paint_storage_info(self) -> None:
        """Fill the Storage rows from the last volume reading.

        This measured the drive the process happened to start on and never said which drive
        that was. It now shows the volume the app's own output directory sits on - the one a
        render can run out of room on - picked by the same helper the storage health check
        uses, with its letter printed beside every figure.
        """
        if self.storage_info is None:
            return
        from ..features.diagnostic_engine import SystemInfo
        volume = SystemInfo.working_volume(self.storage_info)
        if volume is None:
            for label in (self.storage_total_label, self.storage_used_label,
                          self.storage_free_label):
                label.setText('no mounted volume carries the app output directory')
            self.storage_type_label.setText('unknown - no volume was listed')
            return
        self.storage_total_label.setText(
            f"{volume['total_bytes'] / (1024 ** 3):.1f} GB ({volume['mountpoint']})")
        self.storage_used_label.setText(
            f"{volume['used_bytes'] / (1024 ** 3):.1f} GB ({volume['used_percent']}% full)")
        self.storage_free_label.setText(f"{volume['free_bytes'] / (1024 ** 3):.1f} GB")
        kind = volume['media_type']
        if kind:
            self.storage_type_label.setText(
                kind + (f" - {volume['disk']}" if volume['disk'] else ''))
        else:
            self.storage_type_label.setText(
                self.storage_info['reasons'][0] if self.storage_info['reasons']
                else 'nothing reports what kind of disk this is')

    def on_machine_reader_failed(self, error) -> None:
        """A reader that raised is reported as failed, not as a zero."""
        kind, value, _traceback = error
        self.gpu_info_display.setPlainText(
            f'Machine reader failed: {kind.__name__}: {value}')
        for label in (self.storage_total_label, self.storage_used_label,
                      self.storage_free_label, self.storage_type_label):
            label.setText(f'reader failed: {kind.__name__}: {value}')

    # ---- the benchmarks: the engine's work, the engine's words -------------------

    def paint_benchmark_work(self) -> None:
        """What the next storage run will use, read off the store rather than the widgets."""
        work = self.performance_analyzer.benchmark_work_settings()
        self.benchmark_work.setText(
            f'The storage work runs in {work["buffer_kb"]}-chunk writes and reads '
            f'{"through a memory map" if work["use_memory_map"] else "with a plain read"}; '
            f'those two figures are the Buffer Size and Use Memory Mapping boxes, read from '
            f'the store each time a run starts.')

    def run_cpu_benchmark(self):
        """Time square matrix multiplies, which is the work this kind performs."""
        self.start_benchmark('cpu', 'CPU')

    def run_geometry_benchmark(self):
        """Time point-cloud normal estimation through Open3D, and say which device ran it.

        This button was labelled GPU Benchmark while the work behind it was Open3D's
        CPU build. The engine's refusal for a `gpu` kind is what that label deserved, so
        the label names the work now and the row names the device that answered.
        """
        self.start_benchmark('geometry', 'Geometry')

    def run_memory_benchmark(self):
        """Move a bounded footprint until the clock says so; the fifth kind is refused."""
        self.start_benchmark('memory', 'Memory')

    def run_storage_benchmark(self):
        """Write and read a probe file, with the pane's own buffer size and map choice."""
        self.start_benchmark('storage', 'Storage')

    def start_benchmark(self, kind, label):
        """Run one kind in a worker thread; the interface thread times nothing itself.

        The two methods this replaces passed a `worker_func()` that took no
        `progress_callback`, which is the one argument this app's Worker always supplies,
        and never connected `signals.error`, so a failure left the bar indeterminate
        forever. Both are handled here, and the run goes through the analyzer so the two
        boxes the storage kind reads reach the engine with it.
        """
        self.benchmark_status.setText(f'Running {label.lower()} benchmark...')
        # Qt throws away setValue while minimum == maximum, so a busy bar cannot report numbers.
        self.benchmark_progress.setRange(0, 100)
        self.benchmark_progress.setValue(0)
        self.set_benchmark_buttons_enabled(False)
        analyzer = self.performance_analyzer

        def worker_func(progress_callback=None):
            return analyzer.run_benchmark(kind, record=True,
                                          progress_callback=progress_callback)

        worker = Worker(worker_func)
        worker.signals.result.connect(self.show_benchmark_result)
        worker.signals.error.connect(self.on_benchmark_failed)
        worker.signals.progress.connect(self.benchmark_progress.setValue)
        worker.signals.finished.connect(self.finish_benchmark)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def set_benchmark_buttons_enabled(self, enabled):
        for button in (self.benchmark_cpu_btn, self.benchmark_geometry_btn,
                       self.benchmark_memory_btn, self.benchmark_storage_btn,
                       self.benchmark_full_btn):
            button.setEnabled(enabled)

    def show_benchmark_result(self, result):
        """Paint the engine's own cells, including the one that says the work did not run."""
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        for column, text in enumerate(BenchmarkRunner.row_cells(result)):
            self.results_table.setItem(row, column, QTableWidgetItem(text))
        self.benchmark_results.append(result)
        self.paint_comparison(result)
        if result.get('ran') is None:
            self.benchmark_status.setText(
                f"{result.get('kind')} benchmark did not run: {result.get('reason')}")
        else:
            self.benchmark_status.setText(
                f"{result.get('kind')} benchmark finished: {result.get('ran')}")

    def paint_comparison(self, result):
        """The app's own earlier runs of this work, which is the only series it owns."""
        kind = result.get('kind')
        if result.get('ran') is None:
            self.comparison_chart.setText('nothing to compare - this work did not run')
            return
        stored = self.performance_analyzer.benchmark.history.recent_runs(kind)
        if stored['reason']:
            self.comparison_chart.setText(
                f"the stored runs could not be read: {stored['reason']}")
            return
        unit = result.get('comparison_unit', '')
        lines = [f"RenderFox's own runs of the {kind} work on this machine", '']
        if not stored['runs']:
            lines.append('this run was not recorded, so there is no series yet')
        for entry in stored['runs']:
            lines.append(f"{entry.get('at')} - {entry.get('value')} {unit}")
        lines.extend(['',
                      'No other machine is in this list. The app has never collected '
                      "anybody else's result, so it cannot rank this one against a field."])
        self.comparison_chart.setText('\n'.join(lines))

    def on_benchmark_failed(self, error):
        kind, value, _traceback = error
        self.benchmark_status.setText(f'benchmark failed: {kind.__name__}: {value}')

    def finish_benchmark(self):
        self.benchmark_progress.setRange(0, 100)
        self.benchmark_progress.setValue(100)
        self.set_benchmark_buttons_enabled(True)

    def run_full_benchmark(self):
        """Every kind the engine performs, in one worker, with its refusals kept."""
        self.benchmark_status.setText(
            'Running every benchmark this engine performs...')
        # Qt throws away setValue while minimum == maximum, so a busy bar cannot report numbers.
        self.benchmark_progress.setRange(0, 100)
        self.benchmark_progress.setValue(0)
        self.set_benchmark_buttons_enabled(False)
        analyzer = self.performance_analyzer

        def worker_func(progress_callback=None):
            return analyzer.run_all_benchmarks(record=True,
                                               progress_callback=progress_callback)

        worker = Worker(worker_func)
        worker.signals.result.connect(self.show_full_benchmark)
        worker.signals.error.connect(self.on_benchmark_failed)
        worker.signals.progress.connect(self.benchmark_progress.setValue)
        worker.signals.finished.connect(self.finish_benchmark)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_full_benchmark(self, summary):
        for kind in BenchmarkRunner.KINDS:
            self.show_benchmark_result(summary['kinds'][kind])
        refused = summary['refused']
        self.benchmark_status.setText(
            f"measured {', '.join(summary['performed']) or 'nothing'}"
            + (f"; refused {len(refused)}: {'; '.join(refused)}" if refused else ''))

    def export_results(self):
        """Write this table's own cells out, and print the file the engine read back.

        The engine writes and re-reads, so the pane cannot report an export that was only
        an `open()` call; a file whose line count disagrees with the row count says so here.
        """
        answer = self.performance_analyzer.export_benchmark_results(self.benchmark_results)
        if not answer['written']:
            self.export_status.setText(f'nothing was written - {answer["reason"]}')
            return
        text = f'wrote {answer["rows"]} row(s) to {answer["path"]}'
        if 'bytes' in answer:
            text += (f' - the engine read the file back as {answer["lines_read_back"]} '
                     f'lines and {answer["bytes"]} bytes, with the columns '
                     f'{", ".join(answer["headers"])}')
        if answer['reason']:
            text += f' - {answer["reason"]}'
        self.export_status.setText(text)

    def clear_results(self):
        """Empty the table, and say out loud which measurements this did not touch."""
        self.results_table.setRowCount(0)
        self.benchmark_results = []
        history = self.performance_analyzer.benchmark.stored_runs()
        text = (f'the table is empty. The {history["count"]} run(s) the app stored in '
                f'{history["path"]} are still on disk - this button empties a table, not the '
                f'history the comparison reads')
        if history['reason']:
            text += f'; the store itself says: {history["reason"]}'
        self.export_status.setText(text)

    # ---- profiles: the knobs a name stands for -----------------------------------

    def value_of(self, name: str) -> Any:
        """The value one control shows right now, read the way its kind stores it."""
        widget = self._controls[name]
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        return widget.text()

    def apply_performance_profile(self):
        """Ask the engine to apply the named profile, then paint the screen it wrote.

        This used to move three spin boxes and store nothing: the values went to the widget
        that was already on screen and never reached the code that reads them. The engine
        writes the store, runs each knob's own verb and answers with what it refused.
        """
        name = self.profile_combo.currentText()
        outcome = self.performance_analyzer.apply_profile(name)
        self.refresh_variable_controls()
        self.paint_controls_from_store()
        self._effects['profile_combo'].setText(describe_profile(outcome))
        self.paint_benchmark_work()

    def save_performance_profile(self):
        """Store the values on screen under the name the user typed, and read the entry back."""
        name = self.profile_name_edit.text()
        values = {widget: self.value_of(widget)
                  for widget in self.performance_analyzer.profiles.live_knob_names()
                  if widget in self._controls}
        answer = self.performance_analyzer.save_profile(name, values)
        if answer.get('saved'):
            read_back = answer.get('read_back') or {}
            text = (f'saved "{answer["name"]}" with '
                    f'{len(answer.get("knobs") or {})} knob(s) in {answer["path"]}'
                    + (f'; the file answers with {sorted(read_back.get("entry", {}))}'
                       if read_back.get('found') else
                       f'; the file did not answer: {read_back.get("reason")}'))
            if answer.get('refused'):
                text += '; refused ' + '; '.join(answer['refused'])
        else:
            text = f'not saved - {answer.get("reason")}'
            if answer.get('refused'):
                text += '; ' + '; '.join(answer['refused'])
        self._effects['profile_name_edit'].setText(text)
        self.refresh_variable_controls()
        self.paint_control('profile_combo')

    # ---- analysis: the detector, the suggester and the contract ------------------

    def refresh_analysis(self):
        """One look at the machine, the trend over the samples kept, and the timings."""
        analyzer = self.performance_analyzer

        def analysis_reader(progress_callback=None):
            return {'current': analyzer.get_current_analysis(),
                    'historical': analyzer.get_historical_analysis(),
                    'profiling': [row.to_dict()
                                  for row in analyzer.get_profiling_results()]}

        worker = Worker(analysis_reader)
        worker.signals.result.connect(self.show_analysis)
        worker.signals.error.connect(self.on_analysis_reader_failed)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_analysis(self, payload: dict) -> None:
        """Paint the three answers, and name every field the sample could not read."""
        current = payload['current']
        lines = self.sample_paragraph(current)
        lines.extend(['', 'SCORE', self.score_paragraph(current['score'])])
        lines.extend(['', 'BUDGETS THE USER TYPED IN'])
        lines += [f'  {text}' for text in current['budgets']] or ['  none']
        lines.append('')
        lines.append('NOT MEASURED')
        lines += ([f'  {text}' for text in current['not_measured']]
                  or ['  every field this check uses was read'])
        self.analysis_display.setPlainText('\n'.join(lines))

        fill(self.findings_table, [[finding['kind'], finding['observed'],
                                    finding['limit'], finding['severity'],
                                    finding['because']]
                                   for finding in current['findings']])
        fill(self.suggestions_table, [[row['category'], row['priority'], row['suggestion'],
                                       row['because'], row['where_to_change']]
                                      for row in current['suggestions']])

        historical = payload['historical']
        trends = historical['trends']
        fill(self.trends_table, [[name.replace('_', ' '), cell(row['average']),
                                  cell(row['peak']), cell(row['current']),
                                  cell(row['samples']), row['reason'] or '']
                                 for name, row in trends.items()])
        profiling = payload['profiling']
        fill(self.profiling_table, [[row['function_name'], str(row['call_count']),
                                     f"{row['total_time']:.4f}",
                                     f"{row['average_time']:.4f}",
                                     f"{row['min_time']:.4f}", f"{row['max_time']:.4f}"]
                                    for row in profiling])
        self.analysis_status.setText(
            f'{len(current["findings"])} finding(s) and {len(current["suggestions"])} piece '
            f'of advice over {historical["data_points"]} sample(s) kept'
            + (f'; {len(profiling)} profiled function(s)' if profiling else
               '; no function has been profiled in this session')
            + (f' - the trend answer says: {historical["reason"]}'
               if historical.get('reason') else ''))
        self.build_contract_table()

    def sample_paragraph(self, current: dict) -> List[str]:
        """The figures the verdict is built from, each with the window it covers."""
        metrics = current['metrics']
        frames = current['frames']
        refused = metrics.get('not_read') or {}
        lines = ['FIGURES OF THIS SAMPLE']
        for label, field, unit, basis in SAMPLE_FIELDS:
            value = metrics.get(field)
            if value is None:
                lines.append(f'  {label}: no reading - '
                             f'{refused.get(field, "nothing answered")}. Covers {basis}.')
            else:
                lines.append(f'  {label}: {value} {unit}'.rstrip() + '.')
        drawn = ', '.join(frames.get('sources') or [])
        lines.append('')
        lines.append('FRAMES THE APP ITSELF DREW')
        lines.append(f"  {frames.get('frames')} frame(s) in "
                     f"{frames.get('window_seconds')} s from "
                     f"{drawn or 'no view has stamped a frame'}")
        if frames.get('reason'):
            lines.append(f'  {frames["reason"]}')
        average = current['average_metrics']
        peak = current['peak_metrics']
        lines.append('')
        lines.append(f'AVERAGES AND PEAKS OVER THE {average["samples"]} SAMPLE(S) KEPT')
        for name in ('cpu_percent', 'memory_percent', 'gpu_load_percent', 'fps',
                     'frame_time_ms', 'process_rss_mb', 'gpu_memory_used_mb'):
            lines.append(f'  {name.replace("_", " ")}: average '
                         f'{cell(average.get(name))} '
                         f'({average.get(f"{name}_of")} sample(s) carried it), peak '
                         f'{cell(peak.get(name))}')
        return lines

    def score_paragraph(self, score: dict) -> str:
        """The app's own pressure score, or the reason it refuses to give one."""
        if score['value'] is None:
            return f'no score - {score["reason"]}'
        basis = '\n    '.join(score['basis']) or '    nothing was compared'
        missing = '\n    '.join(score['missing']) or '    nothing was refused'
        return (f'{score["value"]} of 100 - {score["reason"]}\n  basis:\n    {basis}\n'
                f'  fields that could not be compared:\n    {missing}')

    def export_analysis_report(self):
        """Write the report the engine assembles, then read the file back before claiming it."""
        analyzer = self.performance_analyzer

        def report_writer(progress_callback=None):
            path = analyzer.export_performance_report()
            with open(path, encoding='utf-8') as handle:
                keys = sorted(json.load(handle))
            return {'path': path, 'bytes': os.path.getsize(path), 'keys': keys}

        worker = Worker(report_writer)
        worker.signals.result.connect(self.show_report_written)
        worker.signals.error.connect(self.on_analysis_reader_failed)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def show_report_written(self, answer: dict) -> None:
        self.analysis_status.setText(
            f'wrote {answer["path"]} ({answer["bytes"]} bytes) and read it back holding '
            f'{", ".join(answer["keys"])}')

    def on_analysis_reader_failed(self, error) -> None:
        kind, value, _traceback = error
        self.analysis_status.setText(
            f'the analysis never answered: {kind.__name__}: {value}')

    def build_contract_table(self) -> None:
        """Print the tables' own verdict on every control and button on this pane.

        The rows are `PerformanceAnalyzer.control_rows()` and the verb table, so this block
        cannot drift from the code it describes: a control nobody wired appears here with
        the sentence that says so, and a button appears with the artefact it produces.
        """
        widgets = sorted(self._controls)
        rows = []
        for row in self.performance_analyzer.control_rows(widgets):
            stored = ('-' if row.get('stored') is None and 'value' not in row
                      else row.get('value'))
            rows.append([row['widget'], row.get('label', 'unknown control'),
                         'yes' if row.get('wired') else 'no',
                         row.get('key') or 'not stored', row.get('note', '')])
        for name, verb in performance_controls.VERBS.items():
            rows.append([name, verb.label, 'button', '-', verb.produces])
        fill(self.contract_table, rows)

    # ---- the memory verbs: the engine's answer, painted ---------------------------

    def run_memory_task(self, label: str, task, paint) -> None:
        """One memory verb on a worker, with its failure channel connected.

        `gc.collect()`, a working-set trim and `memory_full_info()` are all calls that can
        take a moment, and none of them belongs on the thread that paints the pane.
        """
        analyzer = self.performance_analyzer

        def memory_task(progress_callback=None):
            return task(analyzer)

        self.memory_status.setText(f'{label}...')
        worker = Worker(memory_task)
        worker.signals.result.connect(paint)
        worker.signals.error.connect(self.on_memory_task_failed)
        self._keep_worker(worker)
        QThreadPool.globalInstance().start(worker)

    def on_memory_task_failed(self, error) -> None:
        kind, value, _traceback = error
        self.memory_status.setText(
            f'the memory verb failed before it answered: {kind.__name__}: {value}')
        logger.warning('Performance memory verb failed: %s: %s', kind.__name__, value)

    def clear_memory_cache(self):
        """Empty the two caches this app holds, and print what the engine measured."""
        manager = self.job_manager

        def task(analyzer):
            clear = getattr(manager, 'refresh_software_cache', None) if manager else None
            return {'cleared': analyzer.clear_caches(clear), 'rows': analyzer.memory_rows()}

        self.run_memory_task('clearing the caches this app holds', task, self.paint_memory)

    def force_garbage_collection(self):
        """Ask Python to collect once, through the runner that keeps every pass."""
        def task(analyzer):
            return {'pass': analyzer.collect_garbage('button'),
                    'rows': analyzer.memory_rows()}

        self.run_memory_task('collecting', task, self.paint_memory)

    def trim_working_set(self):
        """Hand the clean pages back to Windows and print the size on either side."""
        def task(analyzer):
            return {'trim': analyzer.trim_working_set(), 'rows': analyzer.memory_rows()}

        self.run_memory_task('trimming the working set', task, self.paint_memory)

    def analyze_memory_usage(self):
        """Read every figure on this block once, each with the reader that answered it."""
        def task(analyzer):
            return {'rows': analyzer.memory_rows()}

        self.run_memory_task('reading the memory figures', task, self.paint_memory)

    def paint_memory(self, payload: dict) -> None:
        """Paint the engine's rows: the cards, the table, the collector and the last trim."""
        rows = payload['rows']
        for entry in rows['machine']:
            card = self._cards.get(entry['card'])
            if card is not None:
                card.setText(value_text(entry))

        table_rows = []
        for group in ('machine', 'process', 'adapter'):
            for entry in rows[group]:
                table_rows.append([entry['card'], value_text(entry),
                                   entry.get('reader') or '', entry.get('reason') or ''])
        for text in rows['budgets']:
            table_rows.append(['budget', text, '', ''])
        fill(self.memory_rows_table, table_rows)

        garbage = rows['garbage']
        passes = garbage['passes']
        self.gc_label.setText(
            f'gc keeps {garbage["generations"]} generation(s), counts '
            f'{", ".join(str(count) for count in garbage["counts"])}, uncollectable '
            f'{garbage["uncollectable"]}; {passes["passes"]} pass(es) this session, '
            f'{passes["total_unreachable"]} object(s) found unreachable in '
            f'{passes["total_seconds"]} s in mode "{passes["mode"]}"'
            + (f' (interval {passes["interval_ms"]} ms, timer '
               f'{"running" if passes["timer_active"] else "not running"})'
               if passes['interval_ms'] else ' (no interval: only a button collects)')
            + (f'; {passes["reason"]}' if passes['reason'] else ''))

        if rows.get('last_trim'):
            trim = rows['last_trim']
            self.trim_label.setText(
                f'last trim: {trim.get("how", "the call did not run")} - resident '
                f'{trim.get("rss_before_mb", "?")} MB before, '
                f'{trim.get("rss_after_mb", "?")} MB after'
                + (f', {trim["freed_mb"]} MB returned' if 'freed_mb' in trim else '')
                + (f'; {trim["reason"]}' if trim['reason'] else ''))

        lines = []
        if 'cleared' in payload:
            answer = payload['cleared']
            lines.append(
                f'cleared {answer["samples_dropped"]} sample(s) and '
                f'{answer["profile_timings_dropped"]} profiled timing(s), dropped the held '
                f'adapter sample; resident {answer["rss_before_mb"]} MB before and '
                f'{answer["rss_after_mb"]} MB after; {answer["software_table"]}')
        if 'pass' in payload:
            one = payload['pass']
            lines.append(
                f'gc.collect() at {one["at"]} (triggered by {one["trigger"]}) found '
                f'{one["unreachable"]} unreachable object(s) in {one["seconds"]} s'
                + (f'; it raised {one["error"]}' if one['error'] else ''))
        if 'trim' in payload:
            trim = payload['trim']
            if not trim['attempted']:
                detail = trim['reason']
            elif 'freed_mb' in trim:
                detail = (f'resident {trim["rss_before_mb"]} MB before, '
                          f'{trim["rss_after_mb"]} MB after, {trim["freed_mb"]} MB returned')
            else:
                detail = trim['reason']
            verb = 'ran' if trim['attempted'] else 'did not run'
            answer = 'was accepted' if trim.get('trimmed') else 'was refused'
            lines.append(f'the trim {verb} and {answer} - {detail}')
        if lines:
            self.memory_status.setText('; '.join(lines))
        else:
            figures = sum(1 for group in ('machine', 'process', 'adapter')
                          for entry in rows[group] if entry.get('value') is not None)
            refused = sum(1 for group in ('machine', 'process', 'adapter')
                          for entry in rows[group] if entry.get('value') is None)
            self.memory_status.setText(
                f'the readers answered {figures} figure(s) and refused {refused}; every row '
                f'below carries the reader that answered or the reason that did not'
                + (f' - {rows["reason"]}' if rows['reason'] else ''))
