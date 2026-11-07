"""
Pipeline Editor Tab - build a node pipeline, run it, and read what every node answered.

Nothing in this file performs work. It edits a `Pipeline`, hands that pipeline to
`PipelineEngine.execute_pipeline` on a worker thread, and prints the dict the call
answered with: one row per node, its status, and the numbers it measured off the files it
wrote. A node's border colour here and its row in the results table are the same fact,
taken from the same run, so nothing on screen can claim a step ran that did not.
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QLabel, QLineEdit,
    QTextEdit, QScrollArea, QGroupBox, QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsPathItem, QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
    QFormLayout, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QColorDialog,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QThread
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath
)

from ..processing.pipeline_engine import (
    NODE_DEFINITIONS, ParameterType, STATUSES, NodeCategory, NodeDefinition,
    Pipeline, PipelineConnection, PipelineEngine, PipelineNode, definition_not_backed,
    get_nodes_by_category
)
from ..utils.file_utils import get_temp_directory
from ..utils.run_teardown import drain
from .icon_provider import get_icon


# ============================================================================
# THE ONE SET OF COLOURS, KEYED BY THE ENGINE'S OWN STATUS WORDS
# ============================================================================

STATUS_COLORS = {
    'done': '#27AE60',
    'refused': '#E67E22',
    'invalid': '#F1C40F',
    'failed': '#E74C3C',
    'stopped': '#95A5A6',
    'skipped': '#7F8C8D',
    'running': '#3498DB',
}
NOT_RUN_COLOR = '#5D6D7E'
WIRE_COLOR = '#3498DB'
BODY_COLOR = '#252830'
EDGE_COLOR = '#4A4F5C'
TEXT_COLOR = '#D5D8DF'
DETAIL_COLOR = '#9AA3B2'

# A definition's min/max seeds these boxes, it does not gate the backend: `coerce()` keeps
# the full range and the handler answers what it does with an extreme. Clamping here would
# hide the difference between "not supported" and "not allowed to ask".
NUMBER_LIMIT = 1e12
INT_LIMIT = 2 ** 31 - 1

# `.ply` is left out on purpose: it holds either kind, and the Library only ever indexes
# meshes, so a handed-over .ply is opened by Load Model and the person moves it to a cloud
# node if they meant otherwise.
CLOUD_SUFFIXES = ('.pcd', '.xyz', '.xyzn', '.xyzrgb', '.pts', '.las')


def _as_float(value: Any) -> Tuple[float, str]:
    """The number a stored knob means, or 0.0 plus the sentence saying it is a guess."""
    try:
        return float(str(value).strip()), ''
    except (TypeError, ValueError):
        return 0.0, (f"this node carries {value!r} where a number belongs. The box shows 0 "
                     f"so you can type the number you meant; the run will not happen until "
                     f"you do.")


def _as_int(value: Any) -> Tuple[int, str]:
    try:
        return int(str(value).strip()), ''
    except (TypeError, ValueError):
        return 0, (f"this node carries {value!r} where a whole number belongs. The box shows "
                   f"0 so you can type the number you meant.")


# ============================================================================
# GRAPHICS ITEMS
# ============================================================================

class NodeGraphicsItem(QGraphicsItem):
    """One node on the canvas. Its border and status word are the run's answer, or say
    that no run has answered it yet."""

    WIDTH = 210
    HEIGHT = 92
    HEADER_HEIGHT = 26
    RADIUS = 6

    def __init__(self, node: PipelineNode, definition: NodeDefinition):
        super().__init__()
        self.node = node
        self.definition = definition
        self.status = ''
        self.detail = ''
        self.wires: List[QGraphicsPathItem] = []

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setToolTip(definition.description)
        self.is_hovered = False
        self.port_in = QPointF(0, self.HEADER_HEIGHT + (self.HEIGHT - self.HEADER_HEIGHT) / 2)
        self.port_out = QPointF(self.WIDTH, self.HEADER_HEIGHT + (self.HEIGHT - self.HEADER_HEIGHT) / 2)
        try:
            self.setPos(float(node.position[0]), float(node.position[1]))
        except (TypeError, ValueError, IndexError):
            self.setPos(0, 0)

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, self.WIDTH + 4, self.HEIGHT + 4)

    def set_result(self, status: str, detail: str) -> None:
        """Take the verdict the engine just sent for this node."""
        self.status = status
        self.detail = detail or ''
        self.update()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(self.definition.color)
        if not accent.isValid():
            accent = QColor(WIRE_COLOR)

        if self.status:
            border = QColor(STATUS_COLORS.get(self.status, NOT_RUN_COLOR))
            border_width = 3
        elif self.isSelected():
            border, border_width = accent, 3
        elif self.is_hovered:
            border, border_width = accent, 2
        else:
            border, border_width = QColor(EDGE_COLOR), 1

        body = QRectF(0, 0, self.WIDTH, self.HEIGHT)
        painter.setBrush(QBrush(QColor(BODY_COLOR)))
        painter.setPen(QPen(border, border_width))
        painter.drawRoundedRect(body, self.RADIUS, self.RADIUS)

        header = QPainterPath()
        header.addRoundedRect(QRectF(0, 0, self.WIDTH, self.HEADER_HEIGHT + self.RADIUS),
                              self.RADIUS, self.RADIUS)
        header.addRect(QRectF(0, self.HEADER_HEIGHT, self.WIDTH, self.RADIUS))
        painter.setBrush(QBrush(accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(header)

        icon = get_icon(self.definition.icon, color='#FFFFFF', size=14)
        pix = icon.pixmap(14, 14)
        if pix is not None and not pix.isNull():
            painter.drawPixmap(8, int((self.HEADER_HEIGHT - 14) / 2), pix)

        painter.setPen(QPen(QColor('#FFFFFF')))
        painter.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        name = QFontMetrics(QFont('Segoe UI', 9, QFont.Weight.Bold)).elidedText(
            self.definition.name, Qt.TextElideMode.ElideRight, self.WIDTH - 32)
        painter.drawText(QRectF(28, 0, self.WIDTH - 32, self.HEADER_HEIGHT),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)

        status_word = self.status if self.status else 'not run'
        painter.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        painter.setPen(QPen(QColor(STATUS_COLORS.get(self.status, NOT_RUN_COLOR))))
        painter.drawText(QRectF(9, self.HEADER_HEIGHT + 3, self.WIDTH - 18, 14),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         status_word)

        detail = self.detail or 'Double-click a node in the palette, then press Run.'
        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QPen(QColor(DETAIL_COLOR)))
        painter.drawText(QRectF(9, self.HEADER_HEIGHT + 19, self.WIDTH - 18, 42),
                         Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, detail)

        painter.setFont(QFont('Segoe UI', 7))
        painter.setPen(QPen(QColor(EDGE_COLOR)))
        painter.drawText(QRectF(9, self.HEIGHT - 14, self.WIDTH - 18, 12),
                         Qt.AlignmentFlag.AlignLeft,
                         f"{self.definition.category.value.upper()} - "
                         f"{len(self.node.parameters)} knob(s) set")

        for port in (self.port_in, self.port_out):
            painter.setBrush(QBrush(QColor(BODY_COLOR)))
            painter.setPen(QPen(QColor(WIRE_COLOR), 2))
            painter.drawEllipse(port, 6, 6)

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # The model, not the widget, is where a node's position is kept: a saved file
            # that lost the layout would reopen as a pile in one corner.
            self.node.position = (self.pos().x(), self.pos().y())
            for wire in self.wires:
                wire.update_path()
        return super().itemChange(change, value)

    def port_in_scene(self) -> QPointF:
        return self.mapToScene(self.port_in)

    def port_out_scene(self) -> QPointF:
        return self.mapToScene(self.port_out)


class ConnectionGraphicsItem(QGraphicsPathItem):
    """A wire. It registers itself with both node items so dragging either one redraws it."""

    def __init__(self, connection: PipelineConnection,
                 from_item: NodeGraphicsItem, to_item: NodeGraphicsItem):
        super().__init__()
        self.connection = connection
        self.from_item = from_item
        self.to_item = to_item
        pen = QPen(QColor(WIRE_COLOR))
        pen.setWidth(2)
        self.setPen(pen)
        self.setZValue(-1)
        from_item.wires.append(self)
        to_item.wires.append(self)
        self.update_path()

    def detach(self) -> None:
        for item in (self.from_item, self.to_item):
            if self in item.wires:
                item.wires.remove(self)

    def update_path(self) -> None:
        start = self.from_item.port_out_scene()
        end = self.to_item.port_in_scene()
        reach = max(abs(end.x() - start.x()) * 0.5, 50.0)
        if abs(end.x() - start.x()) < 100 and abs(end.y() - start.y()) > 50:
            reach = max(reach, 100.0)
        path = QPainterPath()
        path.moveTo(start)
        path.cubicTo(QPointF(start.x() + reach, start.y()),
                     QPointF(end.x() - reach, end.y()), end)
        self.setPath(path)


class PendingWireItem(QGraphicsPathItem):
    """The dashed line followed by the port while a wire is being dragged."""

    def __init__(self, start: QPointF):
        super().__init__()
        self.start = start
        pen = QPen(QColor(WIRE_COLOR))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(1)
        self.update_to(start)

    def update_to(self, point: QPointF) -> None:
        reach = max(abs(point.x() - self.start.x()) * 0.5, 40.0)
        path = QPainterPath()
        path.moveTo(self.start)
        path.cubicTo(QPointF(self.start.x() + reach, self.start.y()),
                     QPointF(point.x() - reach, point.y()), point)
        self.setPath(path)


# ============================================================================
# CANVAS
# ============================================================================

class PipelineGraphicsView(QGraphicsView):
    """The canvas: drag nodes, wheel-zoom, middle-drag pan, port to port for a wire."""

    node_selected = pyqtSignal(str)
    nodes_deleted = pyqtSignal(list)
    wires_deleted = pyqtSignal(list)
    connection_created = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.graph = QGraphicsScene(self)
        self.graph.setSceneRect(-4000, -4000, 8000, 8000)
        self.setScene(self.graph)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor('#1E2126')))

        self.node_items: Dict[str, NodeGraphicsItem] = {}
        self.wire_items: List[ConnectionGraphicsItem] = []
        self._pending: Optional[PendingWireItem] = None
        self._pending_from: Optional[str] = None

    # ---- the model on screen ----

    def add_node_item(self, node: PipelineNode, definition: NodeDefinition) -> None:
        item = NodeGraphicsItem(node, definition)
        self.graph.addItem(item)
        self.node_items[node.id] = item

    def add_wire_item(self, connection: PipelineConnection) -> bool:
        source = self.node_items.get(connection.from_node)
        target = self.node_items.get(connection.to_node)
        if source is None or target is None:
            return False
        item = ConnectionGraphicsItem(connection, source, target)
        self.graph.addItem(item)
        self.wire_items.append(item)
        return True

    def set_node_result(self, node_id: str, status: str, detail: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.set_result(status, detail)

    def clear_all(self) -> None:
        for wire in self.wire_items:
            wire.detach()
        self.wire_items.clear()
        self.node_items.clear()
        self._pending = None
        self._pending_from = None
        self.graph.clear()

    # ---- zoom ----

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if 0.2 <= self.transformer().m11() * factor <= 4.0:
            self.scale(factor, factor)
        event.accept()

    def fit_all(self) -> None:
        bounds = self.graph.itemsBoundingRect()
        if not bounds.isEmpty():
            self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    # ---- port to port ----

    def _port_hit(self, viewport_pos, item: NodeGraphicsItem, port: QPointF) -> bool:
        scene_pos = self.mapToScene(viewport_pos)
        return (scene_pos - item.mapToScene(port)).manhattanLength() < 24

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, NodeGraphicsItem) and self._port_hit(event.pos(), item,
                                                                    item.port_out):
                self._pending_from = item.node.id
                self._pending = PendingWireItem(item.port_out_scene())
                self._pending.update_to(self.mapToScene(event.pos()))
                self.graph.addItem(self._pending)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pending is not None:
            self._pending.update_to(self.mapToScene(event.pos()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.viewport().unsetCursor()
            super().mouseReleaseEvent(event)
            return
        if self._pending is not None:
            target_id = None
            for item in self.graph.items(self.mapToScene(event.pos())):
                if (isinstance(item, NodeGraphicsItem)
                        and self._port_hit(event.pos(), item, item.port_in)):
                    target_id = item.node.id
                    break
            if target_id and target_id != self._pending_from:
                self.connection_created.emit(self._pending_from, target_id)
            self.graph.removeItem(self._pending)
            self._pending = None
            self._pending_from = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            node_ids, wire_pairs = [], []
            for item in self.graph.selectedItems():
                if isinstance(item, NodeGraphicsItem):
                    node_ids.append(item.node.id)
                elif isinstance(item, ConnectionGraphicsItem):
                    wire_pairs.append((item.connection.from_node, item.connection.to_node))
            if wire_pairs:
                self.wires_deleted.emit(wire_pairs)
            if node_ids:
                self.nodes_deleted.emit(node_ids)
            if node_ids or wire_pairs:
                event.accept()
                return
        super().keyPressEvent(event)


# ============================================================================
# PALETTE
# ============================================================================

class NodePaletteWidget(QWidget):
    """Every node type this build has, grouped, searchable, double-click to add."""

    node_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText('Search nodes')
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.filter_nodes)
        layout.addWidget(self.search_box)

        self.groups: List[Tuple[QGroupBox, QListWidget]] = []
        for category in NodeCategory:
            group = QGroupBox(f'{category.value.title()} nodes')
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(4, 4, 4, 4)
            listing = QListWidget()
            listing.setAlternatingRowColors(True)
            listing.itemDoubleClicked.connect(
                lambda item: self.node_requested.emit(item.data(Qt.ItemDataRole.UserRole)))
            for definition in get_nodes_by_category(category):
                entry = QListWidgetItem(definition.name)
                entry.setIcon(get_icon(definition.icon, color='#8C93A8', size=14))
                entry.setData(Qt.ItemDataRole.UserRole, definition.id)
                entry.setToolTip(f'{definition.description}\n\nid: {definition.id}')
                entry.setTextAlignment(Qt.AlignmentFlag.AlignLeft
                                       | Qt.AlignmentFlag.AlignVCenter)
                listing.addItem(entry)
            group.setLayout(group_layout)
            layout.addWidget(group)
            self.groups.append((group, listing))

        layout.addStretch(1)

    def filter_nodes(self, text: str) -> None:
        wanted = text.lower().strip()
        for group, listing in self.groups:
            shown = 0
            for row in range(listing.count()):
                item = listing.item(row)
                hit = not wanted or wanted in item.text().lower() or wanted in str(
                    item.data(Qt.ItemDataRole.UserRole)).lower()
                item.setHidden(not hit)
                if hit:
                    shown += 1
            group.setVisible(shown > 0)

    def select_definition(self, definition_id: str) -> None:
        """Highlight a node type in the list, so a refusal says which row was meant."""
        for group, listing in self.groups:
            for row in range(listing.count()):
                item = listing.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == definition_id:
                    listing.setCurrentRow(row)
                    group.show()
                    return


# ============================================================================
# PROPERTIES PANEL
# ============================================================================

class PropertiesPanel(QWidget):
    """Every knob of one node, as the box its type asks for, typed straight into the node.

    Values are written into `node.parameters` as they change, and out-of-range numbers are
    passed on rather than clamped - the handler is what answers for an extreme, so the run
    can report that answer instead of this widget guessing it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node: Optional[PipelineNode] = None
        self.definition: Optional[NodeDefinition] = None
        self.widgets: Dict[str, QWidget] = {}
        self._frozen = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.title = QLabel('No node selected')
        self.title.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(self.form_host)
        layout.addWidget(scroll, 1)

        self.notes = QLabel('')
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet('color: #E0A800;')
        layout.addWidget(self.notes)

        self.summary = QLabel('')
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet('color: #9AA3B2;')
        layout.addWidget(self.summary)

    # ---- building the rows ----

    def show_empty(self, message: str = 'No node selected') -> None:
        self._frozen = True
        self.node = None
        self.definition = None
        self._clear_form()
        self.title.setText(message)
        self._row(QLabel('Double-click a node in the palette on the left, then click it here '
                         'to set its knobs.'))
        self.notes.setText('')
        self.summary.setText('')
        self._frozen = False

    def load_node(self, node: PipelineNode, definition: NodeDefinition,
                  stale: List[str]) -> None:
        self._frozen = True
        self.node = node
        self.definition = definition
        self._clear_form()
        self.title.setText(definition.name)
        self._row(QLabel(definition.description), wrap=True)

        reason = definition_not_backed(definition)
        if reason:
            warning = QLabel(reason)
            warning.setWordWrap(True)
            warning.setStyleSheet('color: #E74C3C;')
            self._row(warning)

        notes: List[str] = []
        for param in definition.parameters:
            widget = self._widget_for(param, notes)
            if widget is not None:
                label = QLabel(param.name + (' *' if param.required else ''))
                label.setToolTip(self._tooltip_for(param))
                self.form.addRow(label, widget)

        for name in stale:
            self._stale_row(name)

        self.notes.setText('\n'.join(notes))
        set_count = sum(1 for param in definition.parameters
                        if param.name in node.parameters)
        self.summary.setText(f'{set_count} of {len(definition.parameters)} knobs typed in. '
                              f'Everything else runs on the value the node ships with.')
        self._frozen = False

    def _clear_form(self) -> None:
        self.widgets.clear()
        while self.form.count():
            slot = self.form.takeAt(0)
            widget = slot.widget() if slot is not None else None
            if widget is None:
                continue
            widget.hide()
            widget.deleteLater()

    def _row(self, widget: QWidget, wrap: bool = False) -> None:
        if wrap:
            widget.setWordWrap(True)
        self.form.addRow(widget)

    def _tooltip_for(self, param) -> str:
        bounds = ''
        if param.min_value is not None or param.max_value is not None:
            bounds = (f"\n\nThe node suggests {param.min_value} to {param.max_value}. "
                      f"Anything you type is passed to the backend as it stands.")
        options = f"\n\nOptions: {', '.join(str(o) for o in param.options)}" \
            if param.options else ''
        return f'{param.description}{options}{bounds}'

    # ---- one widget per knob type ----

    def _widget_for(self, param, notes: List[str]) -> Optional[QWidget]:
        stored = self.node.parameters.get(param.name, param.default)
        kind = param.type

        if kind == ParameterType.BOOL:
            box = QCheckBox()
            box.setChecked(stored if isinstance(stored, bool) else
                           str(stored).strip().lower() in ('true', '1', 'yes', 'on'))
            box.toggled.connect(lambda value: self._commit(param.name, bool(value)))
            return self._wrap(param.name, box)

        if kind == ParameterType.ENUM:
            return self._enum_widget(param, stored, notes)

        if kind in (ParameterType.FILE, ParameterType.FOLDER):
            return self._path_widget(param, stored)

        if kind == ParameterType.COLOR:
            return self._color_widget(param, stored, notes)

        if kind == ParameterType.VECTOR3:
            return self._vector_widget(param, stored, notes)

        if kind == ParameterType.INT:
            box = QSpinBox()
            box.setRange(-INT_LIMIT, INT_LIMIT)
            value, note = _as_int(stored)
            if note:
                notes.append(f'{param.name}: {note}')
            box.setValue(value)
            box.valueChanged.connect(lambda value: self._commit(param.name, int(value)))
            return self._wrap(param.name, box)

        if kind == ParameterType.FLOAT:
            box = QDoubleSpinBox()
            box.setRange(-NUMBER_LIMIT, NUMBER_LIMIT)
            box.setDecimals(6)
            value, note = _as_float(stored)
            if note:
                notes.append(f'{param.name}: {note}')
            box.setValue(value)
            box.valueChanged.connect(lambda value: self._commit(param.name, float(value)))
            return self._wrap(param.name, box)

        box = QLineEdit('' if stored is None else str(stored))
        box.textChanged.connect(lambda text: self._commit(param.name, text))
        return self._wrap(param.name, box)

    def _enum_widget(self, param, stored, notes: List[str]) -> QWidget:
        box = QComboBox()
        named = [str(option) for option in param.options]
        text = '' if stored is None else str(stored).strip()
        if text and text not in named:
            box.addItem(text)
            notes.append(f'{param.name}: this file asks for {text!r}, which the node does not '
                         f'offer ({", ".join(named) if named else "nothing"}). It stays so you '
                         f'can see it; the run will refuse by name.')
        box.addItems(named)
        if text:
            box.setCurrentIndex(box.findText(text))
        box.currentTextChanged.connect(lambda text: self._commit(param.name, text))
        return self._wrap(param.name, box)

    def _path_widget(self, param, stored) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit('' if stored is None else str(stored))
        line.setPlaceholderText('D:\\...' if param.type == ParameterType.FILE
                                else 'folder path')
        line.textChanged.connect(lambda text: self._commit(param.name, text))
        row.addWidget(line, 1)
        button = QPushButton('Browse')
        button.clicked.connect(lambda: self._browse(param.name, param.type, line))
        row.addWidget(button)
        host = QWidget()
        host.setLayout(row)
        return self._wrap(param.name, host)

    def _color_widget(self, param, stored, notes: List[str]) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit('' if stored is None else str(stored))
        line.textChanged.connect(lambda text: self._commit(param.name, text))
        row.addWidget(line, 1)
        swatch = QPushButton()
        swatch.setFixedWidth(28)
        swatch.setToolTip('Pick the colour')
        swatch.clicked.connect(lambda: self._pick_colour(param.name, line, swatch))
        row.addWidget(swatch)
        self._paint_swatch(line.text(), swatch)
        if stored is not None and not QColor(line.text()).isValid():
            notes.append(f'{param.name}: {stored!r} is not a colour this node can use. The '
                         f'box keeps it so you can fix it.')
        host = QWidget()
        host.setLayout(row)
        return self._wrap(param.name, host)

    def _vector_widget(self, param, stored, notes: List[str]) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        parts: List[Any] = []
        if isinstance(stored, (list, tuple)):
            parts = list(stored)
        elif isinstance(stored, str):
            chunks = [chunk for chunk in stored.replace(';', ',').replace(' ', ',').split(',')
                      if chunk]
            parts = chunks
        if stored is not None and len(parts) != 3:
            notes.append(f'{param.name}: this node carries {stored!r}, which is not three '
                         f'numbers. The boxes start at 0 so you can type them.')
        boxes = []
        for axis in range(3):
            box = QDoubleSpinBox()
            box.setRange(-NUMBER_LIMIT, NUMBER_LIMIT)
            box.setDecimals(6)
            value = 0.0
            if axis < len(parts):
                value, note = _as_float(parts[axis])
                if note:
                    notes.append(f'{param.name} [{("X", "Y", "Z")[axis]}]: {note}')
            box.setValue(value)
            box.setToolTip(('X' if axis == 0 else 'Y' if axis == 1 else 'Z')
                           + ' of ' + param.name)
            row.addWidget(box, 1)
            boxes.append(box)

        def commit(*_args):
            self._commit(param.name, [float(box.value()) for box in boxes])

        for box in boxes:
            box.valueChanged.connect(commit)
        host = QWidget()
        host.setLayout(row)
        return self._wrap(param.name, host)

    def _stale_row(self, name: str) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        text = QLabel(f'{name}: {self.node.parameters.get(name)!r}')
        text.setWordWrap(True)
        row.addWidget(text, 1)
        button = QPushButton('Remove')
        button.setToolTip('This file names a knob no handler reads. Delete it from the node.')
        button.clicked.connect(lambda: self.remove_stale(name))
        row.addWidget(button)
        host = QWidget()
        host.setLayout(row)
        label = QLabel('no longer a knob')
        label.setStyleSheet('color: #E74C3C;')
        self.form.addRow(label, host)

    def _wrap(self, name: str, widget: QWidget) -> QWidget:
        self.widgets[name] = widget
        return widget

    # ---- writing ----

    def _commit(self, name: str, value: Any) -> None:
        if self._frozen or self.node is None:
            return
        if value == '' or value is None:
            self.node.parameters.pop(name, None)
        else:
            self.node.parameters[name] = value

    def remove_stale(self, name: str) -> None:
        if self.node is not None:
            self.node.parameters.pop(name, None)
        self.reload()

    def reload(self) -> None:
        if self.node is not None and self.definition is not None:
            stale = [name for name in sorted(self.node.parameters)
                     if name not in {param.name for param in self.definition.parameters}]
            self.load_node(self.node, self.definition, stale)

    # ---- dialogs ----

    def _browse(self, name: str, kind: ParameterType, line: QLineEdit) -> None:
        if kind == ParameterType.FILE:
            path, _ = QFileDialog.getOpenFileName(self, 'Choose the file')
        else:
            path = QFileDialog.getExistingDirectory(self, 'Choose the folder')
        if path:
            line.setText(path.replace('\\', '/'))

    def _pick_colour(self, name: str, line: QLineEdit, swatch: QPushButton) -> None:
        picked = QColorDialog.getColor(QColor(line.text()) if QColor(line.text()).isValid()
                                       else QColor('#FFFFFF'), self, 'Pick the colour')
        if picked.isValid():
            line.setText(picked.name().upper())
            self._paint_swatch(line.text(), swatch)

    @staticmethod
    def _paint_swatch(text: str, swatch: QPushButton) -> None:
        colour = QColor(text)
        if colour.isValid():
            swatch.setStyleSheet(f'background-color: {colour.name()}; border: 1px solid '
                                 f'#4A4F5C;')
        else:
            swatch.setStyleSheet('background-color: transparent; border: 1px dashed #E74C3C;')


# ============================================================================
# THE RUN
# ============================================================================

class PipelineRunThread(QThread):
    """Run one pipeline on its own thread and carry its answers back to the pane.

    `execute_pipeline` is Qt-free and calls `log`/`node_hook` from this thread, so they are
    wired to signals here - the only way a long node reaches the screen without the pane
    freezing, and without a Qt object being touched from two threads at once. Staging lives
    under the app's temp folder and is left in place, because the files the run reports are
    staging paths and deleting them would point the report at nothing.
    """

    log_line = pyqtSignal(str)
    node_state = pyqtSignal(str, str, str, str)
    run_finished = pyqtSignal(dict)

    def __init__(self, pipeline: Pipeline, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.engine = PipelineEngine(staging_root=get_temp_directory())
        self._stop_requested = False

    def request_stop(self) -> None:
        """Ask for a stop. The node running now finishes the file it is on first."""
        self._stop_requested = True

    def run(self) -> None:
        result = self.engine.execute_pipeline(
            self.pipeline, should_cancel=lambda: self._stop_requested,
            log=self.log_line.emit, node_hook=self.node_state.emit)
        self.run_finished.emit(result)


# ============================================================================
# THE PANE
# ============================================================================

class PipelineEditorTab(QWidget):
    """Node graph on the left, the run's own answers on the bottom, its knobs on the right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pipeline = self._new_pipeline()
        self.file_path: Optional[str] = None
        self._workers: List[PipelineRunThread] = []
        self._active_thread: Optional[PipelineRunThread] = None
        self.init_ui()

    @staticmethod
    def _new_pipeline() -> Pipeline:
        return Pipeline(id=str(uuid.uuid4()), name='New Pipeline')

    # ---- layout ----

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._toolbar())

        self.summary_label = QLabel('Ready. Nothing has run yet, so nothing is claimed.')
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.palette = NodePaletteWidget()
        self.palette.node_requested.connect(self.add_node_from_palette)
        self.palette.setMaximumWidth(260)
        splitter.addWidget(self.palette)

        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel('Pipeline'))
        self.name_edit = QLineEdit(self.pipeline.name)
        self.name_edit.setPlaceholderText('Name this pipeline')
        self.name_edit.textChanged.connect(lambda text: setattr(self.pipeline, 'name', text))
        name_row.addWidget(self.name_edit, 1)
        self.node_count_label = QLabel('0 nodes, 0 wires')
        name_row.addWidget(self.node_count_label)
        centre_layout.addLayout(name_row)

        self.view = PipelineGraphicsView()
        self.view.node_selected.connect(self.on_node_selected)
        self.view.nodes_deleted.connect(self.delete_nodes)
        self.view.wires_deleted.connect(self.delete_wires)
        self.view.connection_created.connect(self.on_connection_created)
        centre_layout.addWidget(self.view, 3)

        results = QGroupBox('What each node answered')
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(4, 4, 4, 4)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(
            ['#', 'Node', 'Status', 'What ran, in the numbers it measured', 'node id'])
        self.results_table.setColumnHidden(4, True)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        results_layout.addWidget(self.results_table)
        centre_layout.addWidget(results, 2)

        log_box = QGroupBox('Execution Log')
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(4, 4, 4, 4)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont('Consolas', 9))
        self.log_output.setMaximumHeight(140)
        log_layout.addWidget(self.log_output)
        centre_layout.addWidget(log_box)

        splitter.addWidget(centre)

        self.properties = PropertiesPanel()
        self.properties.setMaximumWidth(340)
        splitter.addWidget(self.properties)

        splitter.setSizes([240, 700, 320])
        layout.addWidget(splitter, 1)
        self.refresh_view()
        self.properties.show_empty()

    def _toolbar(self) -> QWidget:
        host = QWidget()
        bar = QHBoxLayout(host)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)

        def button(text: str, icon: str, tip: str, handler,
                   shortcut: str = '', primary: bool = False) -> QPushButton:
            widget = QPushButton(text)
            widget.setIcon(get_icon(icon, color='#D5D8DF', size=14))
            widget.setToolTip(f'{tip}  ({shortcut})' if shortcut else tip)
            if shortcut:
                widget.setShortcut(shortcut)
            if primary:
                widget.setProperty('primary', 'true')
            widget.clicked.connect(handler)
            bar.addWidget(widget)
            return widget

        button('New', 'add', 'A blank pipeline', self.new_pipeline, 'Ctrl+N')
        button('Open', 'folder', 'Open a saved pipeline', self.open_pipeline, 'Ctrl+O')
        button('Save', 'backup', 'Save this pipeline', self.save_pipeline, 'Ctrl+S')
        button('Save As', 'backup', 'Save it to a new file', self.save_pipeline_as,
               'Ctrl+Shift+S')
        bar.addSpacing(12)
        self.run_btn = button('Run Pipeline', 'play',
                              'Run every node in dependency order', self.run_pipeline,
                              'Ctrl+R', primary=True)
        self.stop_btn = button('Stop', 'stop',
                               'Stop after the file that is in hand', self.stop_pipeline,
                               'Ctrl+T')
        self.stop_btn.setEnabled(False)
        bar.addSpacing(12)
        button('Zoom In', 'search', 'Zoom in', lambda: self.view.scale(1.2, 1.2))
        button('Zoom Out', 'search', 'Zoom out',
               lambda: self.view.scale(1 / 1.2, 1 / 1.2))
        button('Fit View', 'focus', 'Fit the whole graph on screen',
               lambda: self.view.fit_all())
        bar.addStretch(1)
        return host

    # ---- the graph on screen, always rebuilt from the Pipeline ----

    def refresh_view(self, selected_id: Optional[str] = None) -> None:
        self.view.clear_all()
        for node in self.pipeline.nodes:
            definition = node.get_definition()
            if definition is not None:
                self.view.add_node_item(node, definition)
        for connection in self.pipeline.connections:
            self.view.add_wire_item(connection)
        self.node_count_label.setText(f'{len(self.pipeline.nodes)} nodes, '
                                      f'{len(self.pipeline.connections)} wires')
        if selected_id is not None:
            item = self.view.node_items.get(selected_id)
            if item is not None:
                item.setSelected(True)

    def log(self, sentence: str) -> None:
        self.log_output.append(sentence)

    # ---- new / open / save ----

    def new_pipeline(self) -> None:
        self.pipeline = self._new_pipeline()
        self.file_path = None
        self.name_edit.setText(self.pipeline.name)
        self.results_table.setRowCount(0)
        self.log_output.clear()
        self.refresh_view()
        self.properties.show_empty()
        self.summary_label.setText('A blank pipeline. Nothing has run yet.')

    def open_pipeline(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Open pipeline', '',
                                              'Pipeline files (*.json)')
        if not path:
            return
        from ..processing.pipeline_engine import load_pipeline
        pipeline, warnings = load_pipeline(path)
        if pipeline is None:
            QMessageBox.warning(self, 'Not loaded', '\n'.join(warnings))
            self.log(f"NOT LOADED {path}: {'; '.join(warnings)}")
            return
        self.pipeline = pipeline
        self.file_path = path
        self.name_edit.setText(pipeline.name)
        self.results_table.setRowCount(0)
        self.refresh_view()
        self.properties.show_empty()
        self.log(f"Opened {path}: {len(pipeline.nodes)} node(s), "
                 f"{len(pipeline.connections)} wire(s)")
        if warnings:
            QMessageBox.information(self, 'What this file brought with it',
                                    '\n\n'.join(warnings)
                                    + '\n\nThe pipeline was loaded as it is; nothing in the '
                                      'file was rewritten.')

    def save_pipeline(self) -> None:
        if self.file_path:
            self.save_pipeline_to_file(self.file_path)
        else:
            self.save_pipeline_as()

    def save_pipeline_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, 'Save pipeline', '',
                                             'Pipeline files (*.json)')
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        if self.save_pipeline_to_file(path):
            self.file_path = path

    def save_pipeline_to_file(self, path: str) -> bool:
        from ..processing.pipeline_engine import save_pipeline
        ok, why = save_pipeline(self.pipeline, path)
        if ok:
            self.log(f'Saved {path}: {len(self.pipeline.nodes)} node(s) and '
                     f'{len(self.pipeline.connections)} wire(s) were written and counted back '
                     f'off the file')
            self.summary_label.setText(f'Saved to {path}.')
            return True
        QMessageBox.warning(self, 'Not saved', why)
        self.log(f'NOT SAVED: {why}')
        return False

    # ---- editing the graph ----

    def add_node_from_palette(self, definition_id: str,
                              parameters: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Put one node of this type on the graph, or say why it cannot be put there."""
        definition = NODE_DEFINITIONS.get(definition_id)
        if definition is None:
            self.log(f'NOT ADDED: this build has no node type {definition_id}')
            QMessageBox.warning(self, 'Not added',
                                f'This build has no node type {definition_id}.')
            return None
        reason = definition_not_backed(definition)
        if reason:
            self.log(f'NOT ADDED: {reason}')
            QMessageBox.warning(self, 'Not added', reason)
            return None
        position = self.view.mapToScene(self.view.viewport().rect().center())
        offset = 24 * sum(1 for node in self.pipeline.nodes
                          if node.definition_id == definition_id)
        node = PipelineNode(id=str(uuid.uuid4()), definition_id=definition_id,
                            position=(position.x() - 105 + offset,
                                      position.y() - 46 + offset),
                            parameters=dict(parameters or {}))
        ok, why = self.pipeline.add_node(node)
        if not ok:
            self.log(f'NOT ADDED: {why}')
            return None
        self.refresh_view(selected_id=node.id)
        self.on_node_selected(node.id)
        self.log(f'Added {definition.name}. Its knobs are on the right; nothing has run yet.')
        return node.id

    def accept_model_file(self, path: str) -> None:
        """Take a file the Library handed over as a Load node on this graph."""
        cloud = path.lower().endswith(CLOUD_SUFFIXES)
        definition_id = 'input.load_cloud' if cloud else 'input.load_model'
        node_id = self.add_node_from_palette(definition_id,
                                             {'file_path': path.replace('\\', '/')})
        if node_id:
            self.log(f"{NODE_DEFINITIONS[definition_id].name} now points at {path}; wire it "
                     f"to a step and press Run Pipeline.")

    def delete_nodes(self, node_ids: List[str]) -> None:
        removed = 0
        for node_id in node_ids:
            ok, why = self.pipeline.remove_node(node_id)
            if ok:
                removed += 1
            else:
                self.log(f'NOT DELETED: {why}')
        self.refresh_view()
        self.properties.reload()
        if removed:
            self.log(f'Deleted {removed} node(s) and every wire into or out of them.')

    def delete_wires(self, pairs: List[Tuple[str, str]]) -> None:
        for from_id, to_id in pairs:
            ok, why = self.pipeline.remove_connection(PipelineConnection(from_id, to_id))
            if not ok:
                self.log(f'NOT DELETED: {why}')
        self.refresh_view()
        self.properties.reload()

    def on_connection_created(self, from_id: str, to_id: str) -> None:
        ok, why = self.pipeline.add_connection(PipelineConnection(from_id, to_id))
        if ok:
            self.refresh_view()
            source = self.pipeline.node_by_id(from_id).get_definition()
            target = self.pipeline.node_by_id(to_id).get_definition()
            self.log(f'Wired {source.name} to {target.name}.')
        else:
            self.log(f'NOT WIRED: {why}')

    def on_node_selected(self, node_id: str) -> None:
        node = self.pipeline.node_by_id(node_id)
        if node is None:
            self.properties.show_empty()
            return
        definition = node.get_definition()
        if definition is None:
            self.properties.show_empty(
                f'{node_id} is a {node.definition_id}, which this build does not have')
            return
        self.properties.load_node(node, definition, self.pipeline.unknown_parameters(node))

    # ---- running ----

    def _keep_worker(self, thread: PipelineRunThread) -> None:
        """Hold every started worker until it says it is done.

        Dropping the last Python reference of a running QThread is answered by Qt with a
        process abort - no exception, no message, the window simply goes.
        """
        self._workers.append(thread)
        thread.finished.connect(lambda: self._release_worker(thread))
        # Both the verdict and the thread's own end reopen the pane, so a run that somehow
        # ended without answering cannot leave the buttons greyed out forever.
        thread.finished.connect(self._reopen_pane)

    def _release_worker(self, thread: Optional[PipelineRunThread]) -> None:
        """Drop a worker only once it has said it finished.

        `run_finished` is not that moment: the thread is still winding down, and removing
        the last reference to a live QThread is answered by Qt with a process abort. So the
        pane is reopened by `_reopen_pane` and the reference is dropped here, on `finished`.
        """
        if thread in self._workers:
            self._workers.remove(thread)

    def shutdown_runs(self, timeout_ms: int = 5000) -> int:
        """Stop the run this pane started, and make sure it reports no more.

        A node's row, its log line and the run's summary are three separate channels into
        three separate widgets, and a run that answers after the window is gone writes
        into memory Qt has freed - which ends the process with a heap fault instead of a
        traceback. So all of them come off before anything waits, and the buttons are not
        reopened here: `_reopen_pane` is a receiver like the rest, and the pane is going
        away. Returns the workers this pane still cannot let go of, because the reference
        of a running thread is what keeps Qt from aborting.
        """
        running = drain(self._workers, timeout_ms)
        self._active_thread = None
        return len(running)

    def _reopen_pane(self) -> None:
        self._active_thread = None
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.palette.setEnabled(True)
        self.properties.setEnabled(True)

    def run_pipeline(self) -> None:
        if self._active_thread is not None:
            self.log('NOT STARTED: a run is already in progress. Stop it first.')
            return
        if not self.pipeline.nodes:
            QMessageBox.warning(self, 'Nothing to run',
                                f'{self.pipeline.name} has no nodes. Double-click one in the '
                                f'palette on the left.')
            return
        problems = self.pipeline.problems()
        if problems:
            QMessageBox.warning(self, 'This pipeline will not run', '\n\n'.join(problems))
            self.log('NOT STARTED: ' + '; '.join(problems))
            self.summary_label.setText(f'Not started: {problems[0]}')
            return

        self.results_table.setRowCount(0)
        self.log_output.clear()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.palette.setEnabled(False)
        self.properties.setEnabled(False)
        self.properties.show_empty('Running - the knobs are locked until the run answers')
        self.summary_label.setText(f'Running {self.pipeline.name}: '
                                   f'{len(self.pipeline.nodes)} node(s).')

        thread = PipelineRunThread(self.pipeline)
        thread.log_line.connect(self.log)
        thread.node_state.connect(self.on_node_state)
        thread.run_finished.connect(self.on_run_finished)
        self._keep_worker(thread)
        self._active_thread = thread
        thread.start()

    def stop_pipeline(self) -> None:
        if self._active_thread is None:
            self.log('Nothing is running, so there is nothing to stop.')
            return
        self._active_thread.request_stop()
        self.stop_btn.setEnabled(False)
        self.summary_label.setText('Stopping after the file that is in hand.')

    def on_node_state(self, node_id: str, name: str, status: str, detail: str) -> None:
        self.view.set_node_result(node_id, status, detail)
        if status == 'running':
            return
        row = self._row_for(node_id, name)
        self._write_row(row, status, detail if detail or status != 'done'
                        else 'done, and nothing was reported about it')

    def _row_for(self, node_id: str, name: str) -> int:
        """The row this node already has, or the next empty one.

        Rows are keyed by node id in a hidden column so a node that refused, then ran again,
        updates the row the person is looking at instead of adding a second verdict.
        """
        for existing in range(self.results_table.rowCount()):
            item = self.results_table.item(existing, 4)
            if item is not None and item.text() == node_id:
                return existing
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.results_table.setItem(row, 1, QTableWidgetItem(name))
        self.results_table.setItem(row, 4, QTableWidgetItem(node_id))
        return row

    def _write_row(self, row: int, status: str, detail: str) -> None:
        unknown = status not in STATUSES and status != 'running'
        state = QTableWidgetItem(f'{status} (not a status the engine reports)'
                                 if unknown else (status or 'no status'))
        state.setForeground(QColor(STATUS_COLORS.get(status, NOT_RUN_COLOR)))
        self.results_table.setItem(row, 2, state)
        answer = QTableWidgetItem(detail)
        answer.setToolTip(detail)
        self.results_table.setItem(row, 3, answer)
        self.results_table.resizeRowToContents(row)

    def on_run_finished(self, result: Dict[str, Any]) -> None:
        for position, row in enumerate(result.get('nodes') or []):
            where = self._row_for(row['id'], row['name'])
            self.results_table.setItem(where, 0, QTableWidgetItem(str(position + 1)))
            self._write_row(where, row['status'], row['detail'])
        counts = result.get('counts') or {}
        files = result.get('files') or []
        reason = result.get('reason') or ''
        sentence = (f"{result.get('status', 'unknown')} in {result.get('elapsed', 0)}s - "
                    f"{reason or counts}")
        self.summary_label.setText(f"{sentence} | {len(files)} file(s) written | staging: "
                                   f"{result.get('staging', 'none')}")
        if result.get('exception'):
            self.log(f"NODE CRASHED WITH {result['exception']}")
        if counts.get('failed'):
            QMessageBox.warning(self, 'A node crashed',
                                f"{result['status']}: {reason}\n\nThe files its earlier nodes "
                                f"wrote are still in the staging folder named in the bar above.")
        elif counts.get('refused') or counts.get('invalid'):
            self.log(f"{counts['refused']} refused, {counts['invalid']} read wrong. The rows "
                     f"say which, in the words the engine answered with.")
        selected = [item for item in self.view.graph.selectedItems()
                    if isinstance(item, NodeGraphicsItem)]
        if selected:
            self.on_node_selected(selected[0].node.id)
        else:
            self.properties.show_empty(
                'No node selected - click one to see the knobs it ran with.')
        self._reopen_pane()
