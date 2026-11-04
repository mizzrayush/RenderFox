"""
Node Graph Editor for RenderFox Materials.
"""

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsProxyWidget,
    QWidget, QVBoxLayout, QLabel, QFrame, QMenu, QGraphicsPathItem
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath, QFont

from ...core.material_data import Material, ShaderNode, ShaderNodeType, NodeSocket

# ============================================================================
# GRAPHICS ITEMS
# ============================================================================

class NodeSocketItem(QGraphicsItem):
    """Visual representation of a socket."""
    
    def __init__(self, socket: NodeSocket, parent_node, index, is_input):
        super().__init__(parent_node)
        self.socket = socket
        self.is_input = is_input
        self.index = index
        self.radius = 6.0
        
        # Position relative to node
        y = 40 + index * 24
        if is_input:
            self.setPos(-10, y)
        else:
            self.setPos(parent_node.boundingRect().width() + 10, y)
            
        self.setAcceptHoverEvents(True)
        
    def boundingRect(self):
        return QRectF(-self.radius, -self.radius, self.radius * 2, self.radius * 2)
        
    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Color based on type
        color = QColor("#AAAAAA")
        if self.socket.type == "vec3": color = QColor("#6363C7") # Blueish
        elif self.socket.type == "float": color = QColor("#A1A1A1") # Grey
        elif self.socket.type == "shader": color = QColor("#63C763") # Green
        
        
        # Hover Effect
        if self.isUnderMouse():
            painter.setBrush(QBrush(QColor("#FFF")))
            painter.setPen(QPen(QColor("#FFF"), 2))
            painter.drawEllipse(self.boundingRect())
        
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.boundingRect().adjusted(2, 2, -2, -2))
        
        # Label
        painter.setPen(QPen(QColor("#EEE")))
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        
        if self.is_input:
            painter.drawText(QRectF(15, -10, 100, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.socket.name)
        else:
            painter.drawText(QRectF(-115, -10, 100, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.socket.name)

class NodeItem(QGraphicsItem):
    """Visual representation of a node."""
    
    def __init__(self, node: ShaderNode):
        super().__init__()
        self.node = node
        self.width = 160
        self.height = 40 + max(len(node.inputs), len(node.outputs)) * 24 + 10
        
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | 
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        
        self.setPos(node.position[0], node.position[1])
        
        # Create Sockets
        self.input_items = []
        for i, sock in enumerate(node.inputs):
            item = NodeSocketItem(sock, self, i, True)
            self.input_items.append(item)
            
        self.output_items = []
        for i, sock in enumerate(node.outputs):
            item = NodeSocketItem(sock, self, i, False)
            self.output_items.append(item)
            
    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)
        
    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background (Transparent Dark)
        painter.setBrush(QBrush(QColor(30, 30, 30, 200)))
        if self.isSelected():
            painter.setPen(QPen(QColor("#007acc"), 2))
        else:
            painter.setPen(QPen(QColor("#111"), 1))
            
        path = QPainterPath()
        path.addRoundedRect(self.boundingRect(), 4, 4)
        painter.drawPath(path)
        
        # Header (Thinner, Darker)
        header_rect = QRectF(0, 0, self.width, 24)
        painter.setBrush(QBrush(QColor("#252526")))
        painter.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.addRoundedRect(header_rect, 4, 4)
        painter.drawPath(path)
        # Fix bottom corners of header
        painter.drawRect(0, 20, self.width, 4)
        
        # Title
        painter.setPen(QPen(QColor("#EEE")))
        font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(header_rect, Qt.AlignmentFlag.AlignCenter, self.node.name)
        
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            self.node.position = [value.x(), value.y()]
            if self.scene():
                for item in self.scene().items():
                    if isinstance(item, LinkItem):
                        if (item.start_item and item.start_item.parentItem() == self) or \
                           (item.end_item and item.end_item.parentItem() == self):
                            item.prepareGeometryChange()
                            item.update()
        return super().itemChange(change, value)

class LinkItem(QGraphicsItem):
    """Visual connection between sockets."""
    
    def __init__(self, start_item: NodeSocketItem, end_item: NodeSocketItem):
        super().__init__()
        self.start_item = start_item
        self.end_item = end_item
        self.setZValue(-1) # Behind nodes
        
    def boundingRect(self):
        return self.shape().boundingRect()
        
    def shape(self):
        path = QPainterPath()
        start = self.start_item.scenePos()
        end = self.end_item.scenePos() if self.end_item else QPointF(0,0)
        
        path.moveTo(start)
        
        dx = end.x() - start.x()
        ctrl1 = QPointF(start.x() + dx * 0.5, start.y())
        ctrl2 = QPointF(end.x() - dx * 0.5, end.y())
        
        path.cubicTo(ctrl1, ctrl2, end)
        return path
        
    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#888"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.shape())

# ============================================================================
# GRAPH WIDGET
# ============================================================================

class NodeGraphWidget(QGraphicsView):
    """The main widget for editing node graphs."""
    
    material_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        
        # Grid background
        self.setBackgroundBrush(QBrush(QColor("#1e1e1e")))
        
        self.material = None
        self.drag_start_socket = None
        self.drag_line = None
        
    def set_material(self, material: Material):
        """Load a material into the graph."""
        self.material = material
        self.scene.clear()
        
        # Create Nodes
        node_map = {} # ID -> NodeItem
        socket_map = {} # SocketID -> SocketItem
        
        for node in material.nodes:
            item = NodeItem(node)
            self.scene.addItem(item)
            node_map[node.id] = item
            
            # Map sockets by ID
            for sock_item in item.input_items:
                socket_map[sock_item.socket.id] = sock_item
            for sock_item in item.output_items:
                socket_map[sock_item.socket.id] = sock_item
            
        # Create Links
        for link in material.links:
            # Link uses socket IDs
            if link.from_socket_id in socket_map and link.to_socket_id in socket_map:
                start_item = socket_map[link.from_socket_id]
                end_item = socket_map[link.to_socket_id]
                link_item = LinkItem(start_item, end_item)
                self.scene.addItem(link_item)
        
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        add_menu = menu.addMenu("Add Node")
        
        for node_type in ShaderNodeType:
            action = add_menu.addAction(node_type.value)
            action.triggered.connect(lambda checked, t=node_type: self.add_node(t, event.pos()))
            
        menu.exec(event.globalPos())
        
    def add_node(self, node_type: ShaderNodeType, pos):
        if not self.material: return
        
        node = ShaderNode.create(node_type)
        scene_pos = self.mapToScene(pos)
        node.position = [scene_pos.x(), scene_pos.y()]
        
        self.material.nodes.append(node)
        
        item = NodeItem(node)
        self.scene.addItem(item)
        
        self.material_changed.emit()

    # --- Connection Logic ---

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, NodeSocketItem) and event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_socket = item
            self.drag_line = QGraphicsPathItem()
            self.drag_line.setPen(QPen(QColor("#FFF"), 2, Qt.PenStyle.DashLine))
            self.scene.addItem(self.drag_line)
            return # Consume event
            
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        if self.drag_line and self.drag_start_socket:
            start_pos = self.drag_start_socket.scenePos()
            end_pos = self.mapToScene(event.pos())
            
            path = QPainterPath()
            path.moveTo(start_pos)
            path.lineTo(end_pos)
            self.drag_line.setPath(path)
            return
            
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        if self.drag_line:
            self.scene.removeItem(self.drag_line)
            self.drag_line = None
            
            item = self.itemAt(event.pos())
            if isinstance(item, NodeSocketItem) and item != self.drag_start_socket:
                # Validate connection (Input <-> Output)
                if item.is_input != self.drag_start_socket.is_input:
                    self.create_connection(self.drag_start_socket, item)
            
            self.drag_start_socket = None
            return
            
        super().mouseReleaseEvent(event)
        
    def create_connection(self, socket1, socket2):
        """Create a link between two sockets."""
        # Determine start (output) and end (input)
        if socket1.is_input:
            input_sock, output_sock = socket1, socket2
        else:
            input_sock, output_sock = socket2, socket1
            
        # Add visual link
        link = LinkItem(output_sock, input_sock)
        self.scene.addItem(link)
        
        # Update Material Data
        # Link format: NodeLink object
        from_node = output_sock.parentItem().node
        to_node = input_sock.parentItem().node
        
        # Need to import NodeLink if not already imported, or use the class from material_data
        from ...core.material_data import NodeLink
        
        new_link = NodeLink(
            from_node_id=from_node.id,
            from_socket_id=output_sock.socket.id,
            to_node_id=to_node.id,
            to_socket_id=input_sock.socket.id
        )
        self.material.links.append(new_link)
        
        self.material_changed.emit()
