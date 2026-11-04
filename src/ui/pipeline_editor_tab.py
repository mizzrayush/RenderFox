"""
Pipeline Editor Tab - Visual node-based pipeline creation and editing.
"""

import os
import json
from typing import Dict, List, Optional, Tuple
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
    QLabel, QLineEdit, QTextEdit, QScrollArea, QGroupBox,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsRectItem, QGraphicsLineItem, QGraphicsTextItem, QGraphicsPathItem,
    QMenu, QFileDialog, QMessageBox, QToolBar, QListWidget, QListWidgetItem,
    QFormLayout, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QColorDialog,
    QFrame, QStyle, QApplication
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QSizeF, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainter, QFont, QLinearGradient,
    QPainterPath, QPolygonF, QPalette, QAction, QIcon
)

from ..processing.pipeline_engine import (
    PipelineEngine, Pipeline, PipelineNode, PipelineConnection,
    NodeDefinition, NODE_DEFINITIONS, NodeCategory, ParameterType,
    get_nodes_by_category
)


# ============================================================================
# GRAPHICS ITEMS
# ============================================================================

class NodeGraphicsItem(QGraphicsItem):
    """Visual representation of a pipeline node."""
    
    WIDTH = 200
    HEIGHT = 80
    HEADER_HEIGHT = 30
    
    def __init__(self, node: PipelineNode, definition: NodeDefinition):
        super().__init__()
        self.node = node
        self.definition = definition
        
        # Visual properties
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        
        self.is_hovered = False
        self.is_executing = False
        self.is_completed = False
        self.is_failed = False
        
        # Connection points
        self.input_point = QPointF(0, self.HEIGHT / 2)
        self.output_point = QPointF(self.WIDTH, self.HEIGHT / 2)
        
        # Set position
        self.setPos(node.position[0], node.position[1])
    
    def boundingRect(self) -> QRectF:
        """Return bounding rectangle."""
        return QRectF(0, 0, self.WIDTH, self.HEIGHT)
    
    def paint(self, painter: QPainter, option, widget=None):
        """Paint the node."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Determine colors
        base_color = QColor(self.definition.color)
        
        if self.is_failed:
            border_color = QColor("#E74C3C")
            border_width = 3
        elif self.is_executing:
            border_color = QColor("#F39C12")
            border_width = 3
        elif self.is_completed:
            border_color = QColor("#27AE60")
            border_width = 3
        elif self.isSelected():
            border_color = QColor("#3498DB")
            border_width = 3
        elif self.is_hovered:
            border_color = base_color.lighter(120)
            border_width = 2
        else:
            border_color = base_color
            border_width = 2
        
        # Draw shadow
        shadow_rect = QRectF(3, 3, self.WIDTH, self.HEIGHT)
        painter.setBrush(QBrush(QColor(0, 0, 0, 50)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(shadow_rect, 8, 8)
        
        # Draw main body
        body_rect = QRectF(0, 0, self.WIDTH, self.HEIGHT)
        gradient = QLinearGradient(0, 0, 0, self.HEIGHT)
        gradient.setColorAt(0, QColor("#2C3E50"))
        gradient.setColorAt(1, QColor("#34495E"))
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(border_color, border_width))
        painter.drawRoundedRect(body_rect, 8, 8)
        
        # Draw header
        header_rect = QRectF(0, 0, self.WIDTH, self.HEADER_HEIGHT)
        header_gradient = QLinearGradient(0, 0, 0, self.HEADER_HEIGHT)
        header_gradient.setColorAt(0, base_color)
        header_gradient.setColorAt(1, base_color.darker(120))
        painter.setBrush(QBrush(header_gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(header_rect, 8, 8)
        
        # Draw header bottom border
        painter.setPen(QPen(base_color.darker(150), 1))
        painter.drawLine(0, self.HEADER_HEIGHT, self.WIDTH, self.HEADER_HEIGHT)
        
        # Draw vector icon
        from .icon_provider import get_icon
        icon = get_icon(self.definition.icon, color="#ffffff", size=16)
        pix = icon.pixmap(16, 16)
        if not pix.isNull():
            painter.drawPixmap(10, int((self.HEADER_HEIGHT - 16) / 2), pix)
        
        # Draw title
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QRectF(32, 0, self.WIDTH - 40, self.HEADER_HEIGHT),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        self.definition.name)
        
        # Draw parameter count
        param_count = len(self.node.parameters)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QPen(QColor("#BDC3C7")))
        param_text = f"{param_count} params"
        painter.drawText(QRectF(10, self.HEADER_HEIGHT + 5, self.WIDTH - 20, 20),
                        Qt.AlignmentFlag.AlignLeft, param_text)
        
        # Draw category badge
        painter.setFont(QFont("Segoe UI", 7))
        category_text = self.definition.category.value.upper()
        painter.drawText(QRectF(10, self.HEIGHT - 20, self.WIDTH - 20, 15),
                        Qt.AlignmentFlag.AlignLeft, category_text)
        
        # Draw connection points
        connection_color = QColor("#3498DB")
        
        # Input point
        painter.setBrush(QBrush(connection_color))
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawEllipse(self.input_point, 6, 6)
        
        # Output point
        painter.setBrush(QBrush(connection_color))
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawEllipse(self.output_point, 6, 6)
        
        # Status indicator
        if self.is_executing:
            painter.setBrush(QBrush(QColor("#F39C12")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(self.WIDTH - 15, 15), 5, 5)
        elif self.is_completed:
            painter.setBrush(QBrush(QColor("#27AE60")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(self.WIDTH - 15, 15), 5, 5)
        elif self.is_failed:
            painter.setBrush(QBrush(QColor("#E74C3C")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(self.WIDTH - 15, 15), 5, 5)
    
    def hoverEnterEvent(self, event):
        """Handle hover enter."""
        self.is_hovered = True
        self.update()
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Handle hover leave."""
        self.is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)
    
    def itemChange(self, change, value):
        """Handle item changes."""
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Update node position
            pos = value
            self.node.position = (pos.x(), pos.y())
        
        return super().itemChange(change, value)
    
    def get_input_scene_pos(self) -> QPointF:
        """Get input connection point in scene coordinates."""
        return self.mapToScene(self.input_point)
    
    def get_output_scene_pos(self) -> QPointF:
        """Get output connection point in scene coordinates."""
        return self.mapToScene(self.output_point)


class ConnectionGraphicsItem(QGraphicsPathItem):
    """Visual representation of a connection between nodes."""
    
    def __init__(self, connection: PipelineConnection, 
                 from_item: NodeGraphicsItem, to_item: NodeGraphicsItem):
        super().__init__()
        self.connection = connection
        self.from_item = from_item
        self.to_item = to_item
        
        # Visual properties
        # Use a gradient pen for a "premium" look
        gradient = QLinearGradient(0, 0, 100, 0)  # Will be updated in paint
        gradient.setColorAt(0, QColor("#3498DB"))
        gradient.setColorAt(1, QColor("#2ECC71"))
        
        self.pen = QPen(QBrush(gradient), 3)
        self.pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(self.pen)
        
        self.setZValue(-1)  # Draw behind nodes
        
        self.update_path()
    
    def update_path(self):
        """Update the connection path."""
        start = self.from_item.get_output_scene_pos()
        end = self.to_item.get_input_scene_pos()
        
        # Create curved path
        path = QPainterPath()
        path.moveTo(start)
        
        # Calculate control points for bezier curve
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        
        # Adjust control point offset based on distance
        # Use a smoother curvature logic
        control_offset_x = max(abs(dx) * 0.5, 50)
        control_offset_y = 0  # Keep control points horizontally aligned with ports
        
        # If nodes are close horizontally but far vertically, increase offset to avoid "S" shape being too tight
        if abs(dx) < 100 and abs(dy) > 50:
             control_offset_x = 100
        
        # Improved Bezier Logic (Smoother)
        ctrl1 = QPointF(start.x() + control_offset_x, start.y() + control_offset_y)
        ctrl2 = QPointF(end.x() - control_offset_x, end.y() - control_offset_y)
        
        path.cubicTo(ctrl1, ctrl2, end)
        
        self.setPath(path)
        
        # Update gradient for the pen based on start/end points
        gradient = QLinearGradient(start, end)
        gradient.setColorAt(0, QColor("#3498DB"))  # Blue at start
        gradient.setColorAt(1, QColor("#2ECC71"))  # Green at end
        self.pen.setBrush(QBrush(gradient))
        self.setPen(self.pen)


# ============================================================================
# PIPELINE GRAPHICS VIEW
# ============================================================================

class PipelineGraphicsView(QGraphicsView):
    """Graphics view for the pipeline editor."""
    
    node_selected = pyqtSignal(PipelineNode, NodeDefinition)
    nodes_deleted = pyqtSignal(list)  # List of node IDs
    connection_created = pyqtSignal(str, str)  # from_node_id, to_node_id
    
    def __init__(self):
        super().__init__()
        
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(-5000, -5000, 10000, 10000)
        self.setScene(self.scene)
        
        # View settings
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        
        # Background
        self.setBackgroundBrush(QBrush(QColor("#1E1E1E")))
        
        # Node and connection tracking
        self.node_items: Dict[str, NodeGraphicsItem] = {}
        self.connection_items: List[ConnectionGraphicsItem] = []
        
        # Connection drawing state
        self.temp_connection_line: Optional[QGraphicsLineItem] = None
        self.connection_start_node: Optional[str] = None
    
    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        zoom_factor = 1.15
        
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
        else:
            self.scale(1 / zoom_factor, 1 / zoom_factor)
    
    def mousePressEvent(self, event):
        """Handle mouse press."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            super().mousePressEvent(event)
            return
            
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if we clicked on an output port
            item = self.itemAt(event.pos())
            if isinstance(item, NodeGraphicsItem):
                # Check distance to output port
                # We need scene pos for distance check
                scene_pos = self.mapToScene(event.pos())
                output_pos = item.get_output_scene_pos()
                
                # Simple distance check (radius 10)
                dist = (scene_pos - output_pos).manhattanLength()
                if dist < 20:
                    # Start connection
                    self.connection_start_node = item.node.id
                    self.temp_connection_line = QGraphicsLineItem(
                        output_pos.x(), output_pos.y(),
                        scene_pos.x(), scene_pos.y()
                    )
                    self.temp_connection_line.setPen(QPen(QColor("#3498DB"), 2, Qt.PenStyle.DashLine))
                    self.scene.addItem(self.temp_connection_line)
                    return # Consume event

        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move."""
        if self.temp_connection_line:
            scene_pos = self.mapToScene(event.pos())
            line = self.temp_connection_line.line()
            line.setP2(scene_pos)
            self.temp_connection_line.setLine(line)
            
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseReleaseEvent(event)
            return

        if self.temp_connection_line:
            # Finish connection
            scene_pos = self.mapToScene(event.pos())
            
            # Check if we released on an input port
            # We need to find items at this position
            items = self.scene.items(scene_pos)
            target_node_id = None
            
            for item in items:
                if isinstance(item, NodeGraphicsItem):
                    # Check input port
                    input_pos = item.get_input_scene_pos()
                    dist = (scene_pos - input_pos).manhattanLength()
                    if dist < 20:
                        target_node_id = item.node.id
                        break
            
            if target_node_id and target_node_id != self.connection_start_node:
                # Create connection
                # We need to signal the parent to create the connection in the engine
                # But for now we just emit a signal or call a method on parent?
                # The view doesn't have reference to engine directly usually.
                # Let's emit a signal.
                self.connection_created.emit(self.connection_start_node, target_node_id)
            
            # Cleanup
            self.scene.removeItem(self.temp_connection_line)
            self.temp_connection_line = None
            self.connection_start_node = None
            return

        super().mouseReleaseEvent(event)
    
    def keyPressEvent(self, event):
        """Handle key press."""
        if event.key() == Qt.Key.Key_Delete:
            # Delete selected nodes
            selected_items = self.scene.selectedItems()
            node_ids = []
            
            for item in selected_items:
                if isinstance(item, NodeGraphicsItem):
                    node_ids.append(item.node.id)
            
            if node_ids:
                self.nodes_deleted.emit(node_ids)
        
        super().keyPressEvent(event)
    
    def add_node_item(self, node: PipelineNode, definition: NodeDefinition):
        """Add a node to the view."""
        item = NodeGraphicsItem(node, definition)
        self.scene.addItem(item)
        self.node_items[node.id] = item
        
        # Connect selection signal
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
    
    def remove_node_item(self, node_id: str):
        """Remove a node from the view."""
        if node_id in self.node_items:
            item = self.node_items[node_id]
            self.scene.removeItem(item)
            del self.node_items[node_id]
    
    def add_connection_item(self, connection: PipelineConnection):
        """Add a connection to the view."""
        from_item = self.node_items.get(connection.from_node)
        to_item = self.node_items.get(connection.to_node)
        
        if from_item and to_item:
            conn_item = ConnectionGraphicsItem(connection, from_item, to_item)
            self.scene.addItem(conn_item)
            self.connection_items.append(conn_item)
    
    def update_connections(self):
        """Update all connection paths."""
        for conn_item in self.connection_items:
            conn_item.update_path()
    
    def clear_all(self):
        """Clear all items."""
        self.scene.clear()
        self.node_items.clear()
        self.connection_items.clear()


# ============================================================================
# NODE PALETTE
# ============================================================================

class NodePaletteWidget(QWidget):
    """Widget displaying available nodes organized by category."""
    
    node_double_clicked = pyqtSignal(str)  # definition_id
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Search box
        search_layout = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search nodes...")
        self.search_box.textChanged.connect(self.filter_nodes)
        search_layout.addWidget(self.search_box)
        layout.addLayout(search_layout)
        
        # Category tabs
        for category in NodeCategory:
            group = QGroupBox(category.value.title() + " Nodes")
            group_layout = QVBoxLayout()
            
            list_widget = QListWidget()
            list_widget.itemDoubleClicked.connect(self.on_node_double_clicked)
            
            # Add nodes for this category
            from .icon_provider import get_icon
            nodes = get_nodes_by_category(category)
            for node_def in nodes:
                item = QListWidgetItem(node_def.name)
                item.setIcon(get_icon(node_def.icon, color="#8c93a8", size=16))
                item.setData(Qt.ItemDataRole.UserRole, node_def.id)
                item.setToolTip(node_def.description)
                list_widget.addItem(item)
            
            group_layout.addWidget(list_widget)
            group.setLayout(group_layout)
            layout.addWidget(group)
        
        layout.addStretch()
    
    def filter_nodes(self, text: str):
        """Filter nodes based on search text."""
        search_text = text.lower().strip()
        
        # Iterate through all group boxes (categories)
        layout = self.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            
            if isinstance(widget, QGroupBox):
                # Find the list widget inside the group box
                list_widget = widget.findChild(QListWidget)
                if not list_widget:
                    continue
                
                visible_count = 0
                # Filter items
                for j in range(list_widget.count()):
                    list_item = list_widget.item(j)
                    item_text = list_item.text().lower()
                    
                    if not search_text or search_text in item_text:
                        list_item.setHidden(False)
                        visible_count += 1
                    else:
                        list_item.setHidden(True)
                
                # Hide group if no items visible
                if visible_count > 0:
                    widget.show()
                else:
                    widget.hide()
    
    def on_node_double_clicked(self, item: QListWidgetItem):
        """Handle node double click."""
        definition_id = item.data(Qt.ItemDataRole.UserRole)
        self.node_double_clicked.emit(definition_id)


# ============================================================================
# PROPERTIES PANEL
# ============================================================================

class PropertiesPanel(QWidget):
    """Panel for editing node properties."""
    
    parameter_changed = pyqtSignal(str, str, object)  # node_id, param_name, value
    
    def __init__(self):
        super().__init__()
        self.current_node: Optional[PipelineNode] = None
        self.current_definition: Optional[NodeDefinition] = None
        self.widgets: Dict[str, QWidget] = {}
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("Properties")
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # Scroll area for parameters
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        self.params_widget = QWidget()
        self.params_layout = QFormLayout(self.params_widget)
        scroll.setWidget(self.params_widget)
        
        layout.addWidget(scroll)
        
        # Show empty state
        self.show_empty_state()
    
    def show_empty_state(self):
        """Show empty state."""
        self.clear_parameters()
        label = QLabel("No node selected")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #7F8C8D;")
        self.params_layout.addRow(label)
    
    def clear_parameters(self):
        """Clear all parameter widgets."""
        while self.params_layout.count():
            item = self.params_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.widgets.clear()
    
    def load_node(self, node: PipelineNode, definition: NodeDefinition):
        """Load a node for editing."""
        self.current_node = node
        self.current_definition = definition
        self.clear_parameters()
        
        # Node info header
        info_label = QLabel(definition.name)
        info_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.params_layout.addRow(info_label)
        
        desc_label = QLabel(definition.description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #95A5A6;")
        self.params_layout.addRow(desc_label)
        
        # Add separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self.params_layout.addRow(line)
        
        # Create widgets for each parameter
        for param in definition.parameters:
            widget = self.create_parameter_widget(param)
            if widget:
                label = QLabel(param.name + ("*" if param.required else ""))
                label.setToolTip(param.description)
                self.params_layout.addRow(label, widget)
                self.widgets[param.name] = widget
    
    def create_parameter_widget(self, param) -> Optional[QWidget]:
        """Create appropriate widget for parameter type."""
        widget = None
        current_value = self.current_node.parameters.get(param.name, param.default)
        
        if param.type == ParameterType.STRING:
            widget = QLineEdit()
            widget.setText(str(current_value) if current_value else "")
            widget.textChanged.connect(
                lambda v: self.on_parameter_changed(param.name, v)
            )
        
        elif param.type == ParameterType.INT:
            widget = QSpinBox()
            if param.min_value is not None:
                widget.setMinimum(int(param.min_value))
            if param.max_value is not None:
                widget.setMaximum(int(param.max_value))
            widget.setValue(int(current_value) if current_value else 0)
            widget.valueChanged.connect(
                lambda v: self.on_parameter_changed(param.name, v)
            )
        
        elif param.type == ParameterType.FLOAT:
            widget = QDoubleSpinBox()
            if param.min_value is not None:
                widget.setMinimum(param.min_value)
            if param.max_value is not None:
                widget.setMaximum(param.max_value)
            widget.setValue(float(current_value) if current_value else 0.0)
            widget.setDecimals(3)
            widget.valueChanged.connect(
                lambda v: self.on_parameter_changed(param.name, v)
            )
        
        elif param.type == ParameterType.BOOL:
            widget = QCheckBox()
            widget.setChecked(bool(current_value) if current_value else False)
            widget.stateChanged.connect(
                lambda v: self.on_parameter_changed(param.name, widget.isChecked())
            )
        
        elif param.type == ParameterType.ENUM:
            widget = QComboBox()
            widget.addItems([str(opt) for opt in param.options])
            if current_value:
                index = widget.findText(str(current_value))
                if index >= 0:
                    widget.setCurrentIndex(index)
            widget.currentTextChanged.connect(
                lambda v: self.on_parameter_changed(param.name, v)
            )
        
        elif param.type == ParameterType.FILE:
            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)
            
            line_edit = QLineEdit()
            line_edit.setText(str(current_value) if current_value else "")
            
            browse_btn = QPushButton("Browse...")
            browse_btn.clicked.connect(
                lambda: self.browse_file(param.name, line_edit)
            )
            
            h_layout.addWidget(line_edit)
            h_layout.addWidget(browse_btn)
            widget = container
        
        elif param.type == ParameterType.FOLDER:
            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)
            
            line_edit = QLineEdit()
            line_edit.setText(str(current_value) if current_value else "")
            
            browse_btn = QPushButton("Browse...")
            browse_btn.clicked.connect(
                lambda: self.browse_folder(param.name, line_edit)
            )
            
            h_layout.addWidget(line_edit)
            h_layout.addWidget(browse_btn)
            widget = container
        
        return widget
    
    def on_parameter_changed(self, param_name: str, value):
        """Handle parameter value change."""
        if self.current_node:
            self.current_node.parameters[param_name] = value
            self.parameter_changed.emit(self.current_node.id, param_name, value)
    
    def browse_file(self, param_name: str, line_edit: QLineEdit):
        """Browse for file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if file_path:
            line_edit.setText(file_path)
            self.on_parameter_changed(param_name, file_path)
    
    def browse_folder(self, param_name: str, line_edit: QLineEdit):
        """Browse for folder."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            line_edit.setText(folder_path)
            self.on_parameter_changed(param_name, folder_path)


# ============================================================================
# MAIN PIPELINE EDITOR TAB
# ============================================================================

class PipelineEditorTab(QWidget):
    """Main pipeline editor tab with visual node editor."""
    
    def __init__(self, job_manager=None):
        super().__init__()
        self.job_manager = job_manager
        self.current_pipeline: Optional[Pipeline] = None
        self.current_file_path: Optional[str] = None
        
        # Initialize pipeline engine
        self.engine = PipelineEngine(job_manager)
        self.engine.log_message.connect(self.add_log_message)
        self.engine.node_started.connect(self.on_node_started)
        self.engine.node_completed.connect(self.on_node_completed)
        self.engine.node_failed.connect(self.on_node_failed)
        self.engine.pipeline_completed.connect(self.on_pipeline_completed)
        
        self.init_ui()
        self.create_new_pipeline()
    
    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        
        # Toolbar
        toolbar = self.create_toolbar()
        layout.addWidget(toolbar)
        
        # Main splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left: Node palette
        self.node_palette = NodePaletteWidget()
        self.node_palette.node_double_clicked.connect(self.add_node_from_palette)
        self.node_palette.setMaximumWidth(250)
        main_splitter.addWidget(self.node_palette)
        
        # Center: Graphics view
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        # Pipeline info
        info_layout = QHBoxLayout()
        self.pipeline_name_edit = QLineEdit()
        self.pipeline_name_edit.setPlaceholderText("Pipeline Name")
        self.pipeline_name_edit.textChanged.connect(self.on_pipeline_name_changed)
        info_layout.addWidget(QLabel("Name:"))
        info_layout.addWidget(self.pipeline_name_edit)
        center_layout.addLayout(info_layout)
        
        self.graphics_view = PipelineGraphicsView()
        self.graphics_view.node_selected.connect(self.on_node_selected)
        self.graphics_view.nodes_deleted.connect(self.delete_nodes)
        self.graphics_view.connection_created.connect(self.on_connection_created)
        center_layout.addWidget(self.graphics_view)
        
        # Log output
        log_group = QGroupBox("Execution Log")
        log_layout = QVBoxLayout()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        center_layout.addWidget(log_group)
        
        main_splitter.addWidget(center_widget)
        
        # Right: Properties panel
        self.properties_panel = PropertiesPanel()
        self.properties_panel.parameter_changed.connect(self.on_parameter_changed)
        self.properties_panel.setMaximumWidth(300)
        main_splitter.addWidget(self.properties_panel)
        
        # Set splitter proportions
        main_splitter.setSizes([250, 700, 300])
        
        layout.addWidget(main_splitter)
    
    def create_toolbar(self) -> QToolBar:
        """Create toolbar."""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        
        from .icon_provider import get_icon
        # File actions
        new_action = QAction("New", self)
        new_action.setIcon(get_icon("add"))
        new_action.triggered.connect(self.create_new_pipeline)
        toolbar.addAction(new_action)
        
        open_action = QAction("Open", self)
        open_action.setIcon(get_icon("folder"))
        open_action.triggered.connect(self.open_pipeline)
        toolbar.addAction(open_action)
        
        save_action = QAction("Save", self)
        save_action.setIcon(get_icon("backup"))
        save_action.triggered.connect(self.save_pipeline)
        toolbar.addAction(save_action)
        
        save_as_action = QAction("Save As", self)
        save_as_action.setIcon(get_icon("backup"))
        save_as_action.triggered.connect(self.save_pipeline_as)
        toolbar.addAction(save_as_action)
        
        toolbar.addSeparator()
        
        # Execution actions
        self.run_btn = QPushButton("Run Pipeline")
        self.run_btn.setIcon(get_icon("play"))
        self.run_btn.setProperty("primary", "true")
        self.run_btn.clicked.connect(self.run_pipeline)
        toolbar.addWidget(self.run_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(get_icon("stop"))
        self.stop_btn.clicked.connect(self.stop_pipeline)
        self.stop_btn.setEnabled(False)
        toolbar.addWidget(self.stop_btn)
        
        toolbar.addSeparator()
        
        # View actions
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setIcon(get_icon("search"))
        zoom_in_action.triggered.connect(lambda: self.graphics_view.scale(1.2, 1.2))
        toolbar.addAction(zoom_in_action)
        
        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setIcon(get_icon("search"))
        zoom_out_action.triggered.connect(lambda: self.graphics_view.scale(0.8, 0.8))
        toolbar.addAction(zoom_out_action)
        
        fit_action = QAction("Fit View", self)
        fit_action.setIcon(get_icon("focus"))
        fit_action.triggered.connect(lambda: self.graphics_view.fitInView(
            self.graphics_view.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio
        ))
        toolbar.addAction(fit_action)
        
        return toolbar
    
    def create_new_pipeline(self):
        """Create a new pipeline."""
        import uuid
        self.current_pipeline = Pipeline(
            id=str(uuid.uuid4()),
            name="New Pipeline",
            description=""
        )
        self.current_file_path = None
        self.pipeline_name_edit.setText(self.current_pipeline.name)
        self.engine._current_pipeline = self.current_pipeline
        self.graphics_view.clear_all()
        self.log_output.clear()
    
    def open_pipeline(self):
        """Open existing pipeline."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Pipeline", "", "Pipeline Files (*.json)"
        )
        
        if file_path:
            from ..processing.pipeline_engine import load_pipeline
            pipeline = load_pipeline(file_path)
            
            if pipeline:
                self.current_pipeline = pipeline
                self.current_file_path = file_path
                self.engine._current_pipeline = self.current_pipeline
                self.load_pipeline_to_view()
                self.add_log_message(f"Opened pipeline: {file_path}")
            else:
                QMessageBox.warning(self, "Error", "Failed to open pipeline")
    
    def save_pipeline(self):
        """Save current pipeline."""
        if self.current_file_path:
            self.save_pipeline_to_file(self.current_file_path)
        else:
            self.save_pipeline_as()
    
    def save_pipeline_as(self):
        """Save pipeline as new file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Pipeline As", "", "Pipeline Files (*.json)"
        )
        
        if file_path:
            if not file_path.endswith('.json'):
                file_path += '.json'
            self.save_pipeline_to_file(file_path)
            self.current_file_path = file_path
        self.engine._current_pipeline = self.current_pipeline
    
    def save_pipeline_to_file(self, file_path: str):
        """Save pipeline to file."""
        from ..processing.pipeline_engine import save_pipeline
        
        if save_pipeline(self.current_pipeline, file_path):
            self.add_log_message(f"Saved pipeline: {file_path}")
        else:
            QMessageBox.warning(self, "Error", "Failed to save pipeline")
    
    def load_pipeline_to_view(self):
        """Load current pipeline into the view."""
        self.graphics_view.clear_all()
        self.pipeline_name_edit.setText(self.current_pipeline.name)
        self.engine._current_pipeline = self.current_pipeline
        
        # Add nodes
        for node in self.current_pipeline.nodes:
            definition = node.get_definition()
            if definition:
                self.graphics_view.add_node_item(node, definition)
        
        # Add connections
        for connection in self.current_pipeline.connections:
            self.graphics_view.add_connection_item(connection)
    
    def add_node_from_palette(self, definition_id: str):
        """Add node from palette."""
        import uuid
        
        definition = NODE_DEFINITIONS.get(definition_id)
        if not definition:
            return
        
        # Create node at center of view
        view_center = self.graphics_view.mapToScene(
            self.graphics_view.viewport().rect().center()
        )
        
        node = PipelineNode(
            id=str(uuid.uuid4()),
            definition_id=definition_id,
            position=(view_center.x(), view_center.y()),
            parameters={}
        )
        
        # Set default parameters
        for param in definition.parameters:
            if param.default is not None:
                node.parameters[param.name] = param.default
        
        self.current_pipeline.nodes.append(node)
        self.graphics_view.add_node_item(node, definition)
        self.add_log_message(f"Added node: {definition.name}")
    
    def delete_nodes(self, node_ids: List[str]):
        """Delete nodes."""
        for node_id in node_ids:
            # Remove from pipeline
            self.current_pipeline.nodes = [
                n for n in self.current_pipeline.nodes if n.id != node_id
            ]
            
            # Remove connections
            self.current_pipeline.connections = [
                c for c in self.current_pipeline.connections
                if c.from_node != node_id and c.to_node != node_id
            ]
            
            # Remove from view
            self.graphics_view.remove_node_item(node_id)
        
        # Reload view
        self.load_pipeline_to_view()
        self.add_log_message(f"Deleted {len(node_ids)} node(s)")
    
    def on_node_selected(self, node: PipelineNode, definition: NodeDefinition):
        """Handle node selection."""
        self.properties_panel.load_node(node, definition)
    
    def on_parameter_changed(self, node_id: str, param_name: str, value):
        """Handle parameter change."""
        # Already updated in the node object
        pass
    
    def on_pipeline_name_changed(self, name: str):
        """Handle pipeline name change."""
        if self.current_pipeline:
            self.current_pipeline.name = name

    def on_connection_created(self, from_node_id: str, to_node_id: str):
        """Handle new connection creation."""
        if not self.current_pipeline:
            return
            
        # Create connection object
        connection = PipelineConnection(from_node_id, to_node_id)
        
        # Add to pipeline
        if self.engine.add_connection(connection):
            # Add to view
            self.graphics_view.add_connection_item(connection)
            self.log_output.append(f"Connected {from_node_id} -> {to_node_id}")
        else:
            self.log_output.append(f"Failed to connect {from_node_id} -> {to_node_id} (Cycle detected?)")
    
    def run_pipeline(self):
        """Run the pipeline."""
        if not self.current_pipeline or not self.current_pipeline.nodes:
            QMessageBox.warning(self, "Warning", "Pipeline is empty")
            return
        
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_output.clear()
        
        # Reset node states
        for item in self.graphics_view.node_items.values():
            item.is_executing = False
            item.is_completed = False
            item.is_failed = False
            item.update()
        
        # Execute in separate thread
        QTimer.singleShot(100, lambda: self.engine.execute_pipeline(self.current_pipeline))
    
    def stop_pipeline(self):
        """Stop pipeline execution."""
        self.engine.stop()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
    
    def on_node_started(self, node_id: str):
        """Handle node execution started."""
        if node_id in self.graphics_view.node_items:
            item = self.graphics_view.node_items[node_id]
            item.is_executing = True
            item.update()
    
    def on_node_completed(self, node_id: str):
        """Handle node execution completed."""
        if node_id in self.graphics_view.node_items:
            item = self.graphics_view.node_items[node_id]
            item.is_executing = False
            item.is_completed = True
            item.update()
    
    def on_node_failed(self, node_id: str, error: str):
        """Handle node execution failed."""
        if node_id in self.graphics_view.node_items:
            item = self.graphics_view.node_items[node_id]
            item.is_executing = False
            item.is_failed = True
            item.update()
    
    def on_pipeline_completed(self):
        """Handle pipeline execution completed."""
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
    
    def add_log_message(self, message: str):
        """Add message to log."""
        self.log_output.append(message)
