"""
Animation Tab - Professional 3D Animation Interface for RenderFox.
Features:
- Timeline with multi-track support
- Keyframe manipulation (Move, Scale, Copy/Paste)
- Property Inspector with keying support
- Transport controls (Play, Pause, Loop)
- Curve Editor (Placeholder)
- Dope Sheet view
"""

import math
from enum import Enum
from typing import List, Dict, Optional, Any, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QFrame,
    QScrollArea, QToolBar, QComboBox, QCheckBox, QMenu,
    QTreeWidget, QTreeWidgetItem, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsTextItem, QGraphicsPathItem, QStyle, QApplication,
    QColorDialog, QMessageBox, QTabWidget, QGroupBox, QFormLayout,
    QSizePolicy, QAbstractSlider, QFileDialog
)
import os
from .icon_provider import get_icon
from PyQt6.QtCore import (
    Qt, pyqtSignal, QPointF, QRectF, QSize, QTimer, QLineF,
    QMimeData, QObject, QEvent
)
from PyQt6.QtGui import (
    QColor, QPen, QBrush, QPainter, QFont, QPainterPath,
    QLinearGradient, QRadialGradient, QIcon, QAction,
    QDrag, QCursor, QMouseEvent, QKeyEvent, QWheelEvent
)
from .icon_provider import get_icon

from ..core.animation_data import Keyframe, AnimationTrack, AnimationClip, EasingType, AudioTrack
from ..core.animation_engine import AnimationEngine
from ..core.animation_importer import AnimationImporter
from ..core.video_exporter import VideoExporter
from .model_viewer import ModelViewer3D

# ============================================================================
# CONSTANTS & STYLES
# ============================================================================

class TimelineColors:
    BACKGROUND = QColor("#1E1E1E")
    RULER_BG = QColor("#252526")
    RULER_TEXT = QColor("#888888")
    RULER_TICK = QColor("#555555")
    TRACK_BG_ODD = QColor("#2D2D30")
    TRACK_BG_EVEN = QColor("#252526")
    TRACK_SELECTED = QColor("#3E3E42")
    PLAYHEAD = QColor("#FF4081")  # Pinkish red
    PLAYHEAD_LINE = QColor(255, 64, 129, 128)
    KEYFRAME_NORMAL = QColor("#E0E0E0")
    KEYFRAME_SELECTED = QColor("#FFC107")  # Amber
    KEYFRAME_ACTIVE = QColor("#FF4081")
    SELECTION_RECT = QColor(52, 152, 219, 50)
    SELECTION_BORDER = QColor(52, 152, 219)
    GRID_LINE = QColor(60, 60, 60)

class PlaybackMode(Enum):
    ONCE = 0
    LOOP = 1
    PING_PONG = 2

# ============================================================================
# DATA MODELS (UI-Facing)
# ============================================================================

# Local aliases for compatibility if needed, or just use imported classes directly.
# We will use imported classes directly in the rest of the file.
KeyframeData = Keyframe
TrackData = AnimationTrack

# ============================================================================
# CUSTOM WIDGETS: TIMELINE COMPONENTS
# ============================================================================

class TimeRulerItem(QGraphicsItem):
    """The ruler bar at the top of the timeline."""
    
    HEIGHT = 30
    
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.setZValue(100)  # Always on top
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, False)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        
    def boundingRect(self) -> QRectF:
        # Infinite width effectively
        visible_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        return QRectF(visible_rect.left(), 0, visible_rect.width(), self.HEIGHT)
        
    def paint(self, painter: QPainter, option, widget=None):
        rect = self.boundingRect()
        
        # Background
        painter.fillRect(rect, TimelineColors.RULER_BG)
        
        # Bottom border
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.drawLine(QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.bottom()))
        
        # Ticks and Numbers
        # We need to calculate visible range based on view transform
        start_x = rect.left()
        end_x = rect.right()
        
        pixels_per_frame = self.view.transform().m11() * self.view.pixels_per_frame_base
        
        # Determine step size based on zoom level
        step = 1
        if pixels_per_frame < 5: step = 10
        if pixels_per_frame < 2: step = 50
        if pixels_per_frame < 0.5: step = 100
        
        first_frame = int(start_x / self.view.pixels_per_frame_base)
        last_frame = int(end_x / self.view.pixels_per_frame_base) + 1
        
        # Align to step
        first_frame = (first_frame // step) * step
        
        painter.setFont(QFont("Segoe UI", 8))
        
        for frame in range(first_frame, last_frame, step):
            x = frame * self.view.pixels_per_frame_base
            
            # Draw tick
            painter.setPen(QPen(TimelineColors.RULER_TICK, 1))
            if frame % (step * 5) == 0:
                # Major tick
                painter.drawLine(QPointF(x, 15), QPointF(x, 30))
                # Draw text
                painter.setPen(TimelineColors.RULER_TEXT)
                painter.drawText(QPointF(x + 2, 12), str(frame))
            else:
                # Minor tick
                painter.drawLine(QPointF(x, 22), QPointF(x, 30))

class PlayheadItem(QGraphicsItem):
    """The draggable playhead scrubber."""
    
    HEAD_WIDTH = 15
    HEAD_HEIGHT = 30
    
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.setZValue(200)  # Above ruler
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False) # Handled manually
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.current_frame = 0
        
    def set_frame(self, frame):
        self.current_frame = frame
        self.setPos(frame * self.view.pixels_per_frame_base, 0)
        
    def boundingRect(self) -> QRectF:
        # Head + infinite line
        visible_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        return QRectF(-self.HEAD_WIDTH/2, 0, self.HEAD_WIDTH, visible_rect.height())
        
    def paint(self, painter: QPainter, option, widget=None):
        # Draw Line
        visible_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        line_pen = QPen(TimelineColors.PLAYHEAD_LINE, 1)
        painter.setPen(line_pen)
        painter.drawLine(QPointF(0, self.HEAD_HEIGHT), QPointF(0, visible_rect.bottom()))
        
        # Draw Head (Pentagon shape)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(TimelineColors.PLAYHEAD))
        
        path = QPainterPath()
        w = self.HEAD_WIDTH
        h = self.HEAD_HEIGHT
        path.moveTo(-w/2, 0)
        path.lineTo(w/2, 0)
        path.lineTo(w/2, h - 5)
        path.lineTo(0, h)
        path.lineTo(-w/2, h - 5)
        path.closeSubpath()
        
        painter.drawPath(path)

class KeyframeGraphicsItem(QGraphicsItem):
    """Visual representation of a keyframe."""
    
    SIZE = 10
    
    def __init__(self, key_data: KeyframeData, track_item):
        super().__init__(parent=track_item)
        self.key_data = key_data
        self.track_item = track_item
        
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Initial position
        self.setPos(key_data.frame * track_item.view.pixels_per_frame_base, track_item.HEIGHT / 2)
        
    def boundingRect(self) -> QRectF:
        return QRectF(-self.SIZE/2, -self.SIZE/2, self.SIZE, self.SIZE)
        
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Color based on state
        if self.isSelected():
            color = TimelineColors.KEYFRAME_SELECTED
            border = Qt.GlobalColor.white
        else:
            color = TimelineColors.KEYFRAME_NORMAL
            border = QColor("#555")
            
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(border, 1))
        
        # Draw Diamond
        painter.save()
        painter.rotate(45)
        s = self.SIZE / 1.414  # Adjust size for rotation
        painter.drawRect(QRectF(-s/2, -s/2, s, s))
        painter.restore()
        
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            # Constrain Y movement (lock to track)
            new_pos = value
            new_pos.setY(self.track_item.HEIGHT / 2)
            
            # Snap X to frame
            frame_width = self.track_item.view.pixels_per_frame_base
            frame = round(new_pos.x() / frame_width)
            
            # Prevent negative frames
            if frame < 0: frame = 0
            
            new_pos.setX(frame * frame_width)
            
            # Update data model if changed
            if self.key_data.frame != frame:
                # Remove from old frame position in track
                # This is tricky because we need to update the list order
                # For now, just update the frame index, we might need to re-sort the track later
                self.key_data.frame = frame
                self.track_item.track_data.keyframes.sort() # Keep sorted
                
                # Notify view
                # self.track_item.view.keyframe_moved.emit(self.key_data) 
            
            return new_pos
        return super().itemChange(change, value)
        
    def mousePressEvent(self, event):
        # Select on click
        super().mousePressEvent(event)
        self.setSelected(True)

class TrackGraphicsItem(QGraphicsRectItem):
    """Visual container for a track in the timeline."""
    
    HEIGHT = 30
    
    def __init__(self, track_data: TrackData, view, index: int):
        super().__init__()
        self.track_data = track_data
        self.view = view
        self.index = index
        
        # Set geometry
        # Width is effectively infinite, handled in paint
        self.setRect(0, 0, 100000, self.HEIGHT)
        self.setPos(0, 30 + (index * self.HEIGHT)) # Offset by ruler height
        
    def paint(self, painter: QPainter, option, widget=None):
        # Background
        visible_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        bg_rect = QRectF(visible_rect.left(), 0, visible_rect.width(), self.HEIGHT)
        
        # Determine color
        if isinstance(self.track_data, AudioTrack):
            color = QColor("#2ECC71") # Greenish
            color.setAlpha(50)
        else:
            color = TimelineColors.TRACK_BG_ODD if self.index % 2 == 1 else TimelineColors.TRACK_BG_EVEN
            
        painter.fillRect(bg_rect, color)
        
        # Bottom border
        painter.setPen(QPen(QColor("#333"), 1))
        painter.drawLine(QPointF(bg_rect.left(), self.HEIGHT), QPointF(bg_rect.right(), self.HEIGHT))
        
        # Grid lines (vertical)
        pixels_per_frame = self.view.transform().m11() * self.view.pixels_per_frame_base
        step = 10 # Default grid step
        if pixels_per_frame < 5: step = 50
        
        start_frame = int(visible_rect.left() / self.view.pixels_per_frame_base)
        end_frame = int(visible_rect.right() / self.view.pixels_per_frame_base)
        
        painter.setPen(QPen(TimelineColors.GRID_LINE, 1))
        for f in range(start_frame, end_frame + 1):
            if f % step == 0:
                x = f * self.view.pixels_per_frame_base
                painter.drawLine(QPointF(x, 0), QPointF(x, self.HEIGHT))
                
        # Audio Waveform Visualization (Dummy for now)
        if isinstance(self.track_data, AudioTrack):
            painter.setPen(QPen(QColor("#27AE60"), 1))
            mid_y = self.HEIGHT / 2
            
            # Draw a simple sine wave pattern to represent audio
            path = QPainterPath()
            path.moveTo(self.track_data.start_frame * self.view.pixels_per_frame_base, mid_y)
            
            # Only draw visible portion
            draw_start = max(self.track_data.start_frame, start_frame)
            draw_end = min(end_frame, self.track_data.start_frame + 1000) # Assume 1000 frames max for now
            
            for f in range(draw_start, draw_end, 1):
                x = f * self.view.pixels_per_frame_base
                # Fake waveform
                amp = 10 * math.sin(f * 0.5)
                path.lineTo(x, mid_y + amp)
                
            painter.drawPath(path)
            
            # Draw label
            painter.setPen(QColor("#FFF"))
            painter.drawText(QPointF(self.track_data.start_frame * self.view.pixels_per_frame_base + 5, 20), f"🎵 {self.track_data.name}")

class TimelineView(QGraphicsView):
    """The main graphics view for the timeline."""
    
    frame_changed = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        # Settings
        self.pixels_per_frame_base = 10.0
        self.setBackgroundBrush(QBrush(TimelineColors.BACKGROUND))
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        
        # State
        self.current_frame = 0
        self.is_scrubbing = False
        
        # Items
        self.ruler = TimeRulerItem(self)
        self.scene.addItem(self.ruler)
        
        self.playhead = PlayheadItem(self)
        self.scene.addItem(self.playhead)
        
        self.tracks: List[TrackGraphicsItem] = []
        
        # Selection
        self.scene.selectionChanged.connect(self.on_selection_changed)
        
    def on_selection_changed(self):
        """Handle selection changes."""
        selected_items = self.scene.selectedItems()
        # Filter for keyframes
        selected_keys = [item for item in selected_items if isinstance(item, KeyframeGraphicsItem)]
        
        # Update data model selection state
        # First clear all
        for track in self.tracks:
            for kf in track.track_data.keyframes:
                kf.selected = False
                
        # Set selected
        for item in selected_keys:
            item.key_data.selected = True
            
        # TODO: Update Inspector to show selected key properties
        
    def add_track(self, track_data: TrackData):
        """Add a track to the timeline."""
        index = len(self.tracks)
        track_item = TrackGraphicsItem(track_data, self, index)
        self.scene.addItem(track_item)
        self.tracks.append(track_item)
        
        # Add keyframes
        if hasattr(track_data, 'keyframes'):
            for key_data in track_data.keyframes:
                key_item = KeyframeGraphicsItem(key_data, track_item)
                # No need to add to scene explicitly if parent is set? 
                # Actually QGraphicsItem parent/child doesn't auto-add to scene in all cases, 
                # but usually it does if parent is in scene.
                # Let's be safe.
                # key_item.setParentItem(track_item) # Done in __init__
                pass
            
    def set_frame(self, frame: int):
        """Set the current frame."""
        self.current_frame = frame
        self.playhead.set_frame(frame)
        self.frame_changed.emit(frame)
        self.scene.update() # Force redraw
        
    def wheelEvent(self, event: QWheelEvent):
        """Handle zoom and pan."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Zoom
            zoom_factor = 1.1 if event.angleDelta().y() > 0 else 0.9
            self.scale(zoom_factor, 1.0) # Only zoom X axis
        else:
            # Scroll
            super().wheelEvent(event)
            
    def mousePressEvent(self, event: QMouseEvent):
        # Check if clicking in ruler area
        scene_pos = self.mapToScene(event.pos())
        if scene_pos.y() < TimeRulerItem.HEIGHT:
            self.is_scrubbing = True
            self.update_scrub(scene_pos.x())
        else:
            super().mousePressEvent(event)
            
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.is_scrubbing:
            scene_pos = self.mapToScene(event.pos())
            self.update_scrub(scene_pos.x())
        else:
            super().mouseMoveEvent(event)
            
    def mouseReleaseEvent(self, event: QMouseEvent):
        self.is_scrubbing = False
        super().mouseReleaseEvent(event)
        
    def update_scrub(self, x_pos):
        frame = max(0, int(x_pos / self.pixels_per_frame_base))
        self.set_frame(frame)
        
    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        # We handle background in items mostly, but could draw grid here

# ============================================================================
# CUSTOM WIDGETS: CONTROLS & INSPECTOR
# ============================================================================

class TransportControls(QWidget):
    """Playback control bar."""
    
    play_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    next_key_clicked = pyqtSignal()
    prev_key_clicked = pyqtSignal()
    loop_toggled = pyqtSignal(bool)
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Style for buttons
        btn_style = """
            QPushButton {
                background-color: #262936;
                border: 1px solid #363b4d;
                border-radius: 4px;
                padding: 5px;
                color: #e4e7f2;
                min-width: 32px;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #353a4c; border-color: #4b7bec; }
            QPushButton:pressed { background-color: #1e202b; }
            QPushButton:checked { background-color: #3b69d8; border-color: #4b7bec; }
        """
        self.setStyleSheet(btn_style)
        
        # Buttons with crisp SVG vector icons
        self.prev_key_btn = QPushButton()
        self.prev_key_btn.setIcon(get_icon("step_back"))
        self.prev_key_btn.setToolTip("Previous Keyframe")
        
        self.prev_frame_btn = QPushButton()
        self.prev_frame_btn.setIcon(get_icon("arrow_left"))
        self.prev_frame_btn.setToolTip("Previous Frame")
        
        self.play_btn = QPushButton()
        self.play_btn.setIcon(get_icon("play"))
        self.play_btn.setToolTip("Play / Pause (Space)")
        
        self.next_frame_btn = QPushButton()
        self.next_frame_btn.setIcon(get_icon("arrow_right"))
        self.next_frame_btn.setToolTip("Next Frame")
        
        self.next_key_btn = QPushButton()
        self.next_key_btn.setIcon(get_icon("step_forward"))
        self.next_key_btn.setToolTip("Next Keyframe")
        
        self.loop_btn = QPushButton()
        self.loop_btn.setIcon(get_icon("refresh"))
        self.loop_btn.setToolTip("Toggle Loop Playback")
        self.loop_btn.setCheckable(True)
        
        # Frame counter
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(0, 99999)
        self.frame_spin.setStyleSheet("background: #1e202a; color: #45aaf2; font-weight: bold; border: 1px solid #303444; padding: 4px;")
        
        # FPS Combo
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["24 fps", "30 fps", "60 fps"])
        self.fps_combo.setCurrentText("30 fps")
        
        layout.addStretch()
        layout.addWidget(self.loop_btn)
        layout.addWidget(self.prev_key_btn)
        layout.addWidget(self.prev_frame_btn)
        layout.addWidget(self.play_btn)
        layout.addWidget(self.next_frame_btn)
        layout.addWidget(self.next_key_btn)
        layout.addSpacing(10)
        layout.addWidget(QLabel("Frame:"))
        layout.addWidget(self.frame_spin)
        layout.addSpacing(10)
        layout.addWidget(self.fps_combo)
        layout.addStretch()
        
        # Connections
        self.play_btn.clicked.connect(self.toggle_play)
        
        self.is_playing = False
        
    def toggle_play(self):
        from .icon_provider import get_icon
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.play_btn.setIcon(get_icon("pause"))
            self.play_clicked.emit()
        else:
            self.play_btn.setIcon(get_icon("play"))
            self.pause_clicked.emit()

class PropertyInspector(QWidget):
    """Right-side panel for editing object properties and adding keys."""
    
    key_property = pyqtSignal(str, object) # property_path, value
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        self.widgets = {} # Map property_path -> widget
        
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("Property Inspector")
        header.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        layout.addWidget(header)
        
        # Object Selector
        self.object_combo = QComboBox()
        self.object_combo.addItems(["No Selection", "Cube_01", "Camera_Main", "Light_Sun"])
        layout.addWidget(self.object_combo)
        
        # Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        self.props_widget = QWidget()
        self.props_layout = QVBoxLayout(self.props_widget)
        self.props_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Transform Group
        self.add_transform_group()
        
        # Material Group
        self.add_material_group()
        
        scroll.setWidget(self.props_widget)
        layout.addWidget(scroll)
        
    def add_transform_group(self):
        group = QGroupBox("Transform")
        layout = QFormLayout(group)
        
        # Position
        self.pos_x = self.create_spinbox("X")
        self.pos_y = self.create_spinbox("Y")
        self.pos_z = self.create_spinbox("Z")
        layout.addRow("Position X:", self.create_keyed_widget(self.pos_x, "transform.position.x"))
        layout.addRow("Position Y:", self.create_keyed_widget(self.pos_y, "transform.position.y"))
        layout.addRow("Position Z:", self.create_keyed_widget(self.pos_z, "transform.position.z"))
        
        # Rotation
        self.rot_x = self.create_spinbox("X")
        self.rot_y = self.create_spinbox("Y")
        self.rot_z = self.create_spinbox("Z")
        layout.addRow("Rotation X:", self.create_keyed_widget(self.rot_x, "transform.rotation.x"))
        layout.addRow("Rotation Y:", self.create_keyed_widget(self.rot_y, "transform.rotation.y"))
        layout.addRow("Rotation Z:", self.create_keyed_widget(self.rot_z, "transform.rotation.z"))
        
        # Scale
        self.scale_x = self.create_spinbox("X", 1.0)
        self.scale_y = self.create_spinbox("Y", 1.0)
        self.scale_z = self.create_spinbox("Z", 1.0)
        layout.addRow("Scale X:", self.create_keyed_widget(self.scale_x, "transform.scale.x"))
        layout.addRow("Scale Y:", self.create_keyed_widget(self.scale_y, "transform.scale.y"))
        layout.addRow("Scale Z:", self.create_keyed_widget(self.scale_z, "transform.scale.z"))
        
        self.props_layout.addWidget(group)
        
    def add_material_group(self):
        group = QGroupBox("Material")
        layout = QFormLayout(group)
        
        self.opacity = self.create_spinbox("Opacity", 1.0, 0.0, 1.0, 0.01)
        layout.addRow("Opacity:", self.create_keyed_widget(self.opacity, "material.opacity"))
        
        self.props_layout.addWidget(group)
        
    def create_spinbox(self, name, default=0.0, min_val=-10000.0, max_val=10000.0, step=0.1):
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setSingleStep(step)
        spin.setValue(default)
        return spin
        
    def create_keyed_widget(self, widget, property_path):
        """Wrap a widget with a keyframe button."""
        # Store widget mapping
        self.widgets[property_path] = widget
        
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        key_btn = QPushButton("◇")
        key_btn.setFixedWidth(25)
        key_btn.setToolTip(f"Add Keyframe for {property_path}")
        key_btn.setStyleSheet("""
            QPushButton { color: #888; border: none; font-size: 16px; }
            QPushButton:hover { color: #FF4081; }
        """)
        key_btn.clicked.connect(lambda: self.key_property.emit(property_path, widget.value()))
        
        layout.addWidget(widget)
        layout.addWidget(key_btn)
        return container
        
    def update_property(self, property_path, value):
        """Update a property widget value without triggering signals."""
        if property_path in self.widgets:
            widget = self.widgets[property_path]
            widget.blockSignals(True)
            widget.setValue(float(value))
            widget.blockSignals(False)

# ============================================================================
# MAIN ANIMATION TAB
# ============================================================================

class AnimationTab(QWidget):
    """The main Animation Tab widget."""

    asset_loaded = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Engine
        self.engine = AnimationEngine()
        self.engine.frame_changed.connect(self.update_viewport_from_frame)
        self.clip = AnimationClip()
        self.engine.set_clip(self.clip)
        self.current_frame = 0
        self.imported_animation_clip = None
        
        # Data
        # We'll use the clip's tracks directly, but keep a reference for UI helper
        self.tracks = self.clip.tracks 
        
        self.init_ui()
        self.setup_connections()
        self.animation_asset_status.setText(
            "No animation loaded. Load a model, import a clip, or key transform properties to begin.")
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        self.toolbar = self.create_toolbar()
        main_layout.addWidget(self.toolbar)
        
        # Main Splitter (Vertical: Top=Viewport/Props, Bottom=Timeline)
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Top Splitter (Horizontal: Left=Viewport, Right=Props)
        self.top_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 1. Viewport Container (3D View)
        self.viewport_container = QWidget()
        self.viewport_container.setStyleSheet("background-color: #111;")
        viewport_layout = QVBoxLayout(self.viewport_container)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        
        # 3D Viewport
        self.viewport = ModelViewer3D()
        viewport_layout.addWidget(self.viewport)
        self.animation_asset_status = QLabel("No skeletal animation data loaded")
        self.animation_asset_status.setObjectName("animationAssetStatus")
        self.animation_asset_status.setWordWrap(True)
        self.animation_asset_status.setStyleSheet("padding: 6px 10px; color: #9aa0b4;")
        viewport_layout.addWidget(self.animation_asset_status)
        
        self.top_splitter.addWidget(self.viewport_container)
        
        # 2. Property Inspector
        self.inspector = PropertyInspector()
        self.top_splitter.addWidget(self.inspector)
        self.top_splitter.setSizes([800, 300])
        
        self.main_splitter.addWidget(self.top_splitter)
        
        # 3. Timeline Area
        self.timeline_widget = QWidget()
        timeline_layout = QVBoxLayout(self.timeline_widget)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(0)
        
        # Transport Controls
        self.transport = TransportControls()
        timeline_layout.addWidget(self.transport)
        
        # Timeline Splitter (Left=Track Headers, Right=Graph)
        self.timeline_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Track Headers (Tree Widget)
        self.track_headers = QTreeWidget()
        self.track_headers.setHeaderLabels(["Track", "Value"])
        self.track_headers.setColumnWidth(0, 150)
        self.track_headers.setStyleSheet("""
            QTreeWidget {
                background-color: #252526;
                color: #DDD;
                border: none;
                border-right: 1px solid #333;
            }
            QHeaderView::section {
                background-color: #333;
                color: #DDD;
                border: none;
                height: 30px;
            }
        """)
        self.timeline_splitter.addWidget(self.track_headers)
        
        # Timeline Graph View
        self.timeline_view = TimelineView()
        self.timeline_splitter.addWidget(self.timeline_view)
        self.timeline_splitter.setSizes([250, 800])
        
        timeline_layout.addWidget(self.timeline_splitter)
        
        self.main_splitter.addWidget(self.timeline_widget)
        self.main_splitter.setSizes([600, 300])
        
        main_layout.addWidget(self.main_splitter)
        
    def create_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        
        # Actions with crisp vector icons
        new_act = toolbar.addAction("New Animation")
        new_act.setIcon(get_icon("add"))
        new_act.triggered.connect(self.new_animation)
        
        load_act = toolbar.addAction("Load Model")
        load_act.setIcon(get_icon("models"))
        load_act.triggered.connect(self.load_model_dialog)
        
        open_act = toolbar.addAction("Open Animation")
        open_act.setIcon(get_icon("folder"))
        open_act.triggered.connect(self.open_animation)
        
        save_act = toolbar.addAction("Save Animation")
        save_act.setIcon(get_icon("backup"))
        save_act.triggered.connect(self.save_animation)
        
        toolbar.addSeparator()
        
        render_act = toolbar.addAction("Render Video")
        render_act.setIcon(get_icon("video"))
        render_act.triggered.connect(self.render_video)
        
        toolbar.addSeparator()
        
        audio_act = toolbar.addAction("Import Audio")
        audio_act.setIcon(get_icon("audio"))
        audio_act.triggered.connect(self.import_audio)
        
        toolbar.addSeparator()
        
        cut_act = toolbar.addAction("Cut")
        cut_act.setIcon(get_icon("cut"))
        
        copy_act = toolbar.addAction("Copy")
        copy_act.setIcon(get_icon("copy"))
        
        paste_act = toolbar.addAction("Paste")
        paste_act.setIcon(get_icon("paste"))
        
        toolbar.addSeparator()
        
        # Auto Key Toggle
        self.auto_key_btn = QAction("Auto Key", self)
        self.auto_key_btn.setIcon(get_icon("keyframe", color="#ff4757"))
        self.auto_key_btn.setCheckable(True)
        toolbar.addAction(self.auto_key_btn)
        
        return toolbar
        
    def setup_connections(self):
        # Transport
        self.transport.play_clicked.connect(self.engine.play)
        self.transport.pause_clicked.connect(self.engine.pause)
        self.transport.frame_spin.valueChanged.connect(self.engine.set_frame)
        self.transport.loop_toggled.connect(lambda loop: setattr(self.engine, '_loop', loop))
        
        # Frame Stepping
        self.transport.next_frame_btn.clicked.connect(self.engine.next_frame)
        self.transport.prev_frame_btn.clicked.connect(self.engine.prev_frame)
        
        # FPS Control
        self.transport.fps_combo.currentTextChanged.connect(self.on_fps_changed)
        
        # Engine Signals
        self.engine.frame_changed.connect(self.on_frame_changed)
        self.engine.playback_started.connect(self.on_playback_started)
        self.engine.playback_stopped.connect(self.on_playback_stopped)
        
        # Timeline
        self.timeline_view.frame_changed.connect(self.engine.set_frame)
        
        # Inspector
        self.inspector.key_property.connect(self.add_keyframe)
        
    def on_fps_changed(self, text):
        """Handle FPS change."""
        fps = int(text.split()[0])
        self.engine.fps = fps
        self.clip.fps = fps # Update data model too
        
    def on_frame_changed(self, frame):
        """Handle frame change from engine."""
        self.current_frame = frame # Keep local ref for add_keyframe
        
        # Update Transport UI
        self.transport.frame_spin.blockSignals(True)
        self.transport.frame_spin.setValue(frame)
        self.transport.frame_spin.blockSignals(False)
        
        # Update Timeline UI
        self.timeline_view.set_frame(frame)
        
        # Update Inspector Values (Interpolation)
        self.update_inspector_values(frame)
        
    def on_playback_started(self):
        from .icon_provider import get_icon
        self.transport.play_btn.setIcon(get_icon("pause"))
        self.transport.is_playing = True
        
    def on_playback_stopped(self):
        from .icon_provider import get_icon
        self.transport.play_btn.setIcon(get_icon("play"))
        self.transport.is_playing = False
        
    def update_inspector_values(self, frame):
        """Update property inspector based on interpolated values."""
        for track in self.tracks:
            # Calculate value at current frame (interpolated)
            val = track.get_value_at_frame(frame)
            
            # Update Inspector UI
            self.inspector.update_property(track.property_path, val)
            
            # TODO: If we had a 3D viewport, we would update the actual object here too
            # e.g. scene.find_object(track.object_name).set_property(track.property_name, val)

    def add_track(self, track_data: TrackData):
        """Add a track to the UI."""
        self.tracks.append(track_data)
        
        # Add to Header
        item = QTreeWidgetItem([track_data.name, ""])
        item.setSizeHint(0, QSize(0, 30)) # Match track height
        self.track_headers.addTopLevelItem(item)
        
        # Add Mute Button for Audio
        if isinstance(track_data, AudioTrack):
            mute_btn = QPushButton()
            mute_btn.setIcon(get_icon("volume"))
            mute_btn.setCheckable(True)
            mute_btn.setFixedWidth(30)
            mute_btn.setStyleSheet("""
                QPushButton { background: transparent; border: none; }
                QPushButton:checked { color: #ff4757; }
            """)
            mute_btn.toggled.connect(lambda checked, t=track_data, b=mute_btn: self.toggle_mute(t, checked, b))
            self.track_headers.setItemWidget(item, 1, mute_btn)
        
        # Add to Timeline View
        self.timeline_view.add_track(track_data)
        
    def toggle_mute(self, track, muted, btn):
        """Handle mute toggle."""
        track.muted = muted
        btn.setIcon(get_icon("volume_mute") if muted else get_icon("volume"))
        self.engine.update_audio_settings()

    def add_keyframe(self, property_path, value):
        """Add a keyframe at the current frame."""
        # Find existing track or create new one
        track = None
        for t in self.tracks:
            if hasattr(t, 'property_path') and t.property_path == property_path:
                track = t
                break
                
        if not track:
            # Create new track
            track_name = property_path.split('.')[-1].replace('_', ' ').title()
            if "position" in property_path: track_name = f"Pos {track_name}"
            elif "rotation" in property_path: track_name = f"Rot {track_name}"
            elif "scale" in property_path: track_name = f"Scale {track_name}"
            
            track = TrackData(track_name, property_path)
            self.add_track(track)
            
        # Add keyframe to data model
        track.add_keyframe(self.current_frame, value)
        
        # Refresh UI
        self.refresh_timeline()
        
        # Visual feedback
        self.statusBar().showMessage(f"Keyed {property_path} at frame {self.current_frame}", 2000)

    def statusBar(self):
        # Helper to access main window status bar if available
        parent = self.parent()
        while parent:
            if hasattr(parent, "statusBar"):
                return parent.statusBar()
            parent = parent.parent()
        return None

    def new_animation(self):
        """Reset to a new animation."""
        self.clip = AnimationClip("New Animation")
        self.engine.set_clip(self.clip)
        self.refresh_timeline()
        
    def save_animation(self):
        """Save current animation to file."""
        path, _ = QFileDialog.getSaveFileName(self, "Save Animation", "", "JSON Files (*.json)")
        if path:
            if self.clip.save_to_file(path):
                sb = self.statusBar()
                if sb: sb.showMessage(f"Animation saved to {path}", 3000)
            else:
                sb = self.statusBar()
                if sb: sb.showMessage("Error saving animation!", 3000)
                
    def open_animation(self):
        """Load animation from file."""
        path, _ = QFileDialog.getOpenFileName(self, "Open Animation", "", "JSON Files (*.json)")
        if path:
            new_clip = AnimationClip.load_from_file(path)
            if new_clip:
                self.clip = new_clip
                self.engine.set_clip(self.clip)
                self.refresh_timeline()
                sb = self.statusBar()
                if sb: sb.showMessage(f"Animation loaded from {path}", 3000)
            else:
                sb = self.statusBar()
                if sb: sb.showMessage("Error loading animation!", 3000)
                
    
    def load_model_dialog(self):
        """Open dialog to load a 3D model."""
        path, _ = QFileDialog.getOpenFileName(
            self, 
            "Load Model", 
            "", 
            "3D Models (*.obj *.ply *.stl *.gltf *.glb *.fbx *.dae *.x3d)"
        )
        if path:
            self.load_model_from_path(path)

    def load_model_from_path(self, path):
        """Load a model from the given path into the viewport."""
        if not os.path.exists(path):
            return
            
        # Use the viewport's load_model method
        if hasattr(self.viewport, 'load_model'):
            success = self.viewport.load_model(path)
            if success:
                self.asset_loaded.emit(path)
                report = AnimationImporter.load(path)
                if report.success:
                    clips = ', '.join(f"{clip.name} ({clip.channel_count} channels)"
                                      for clip in report.clips) or 'no clips'
                    self.imported_animation_clip = next(
                        (clip for clip in report.clips if clip.channels), None)
                    if self.imported_animation_clip:
                        duration = self.imported_animation_clip.duration_seconds or 0.0
                        self.clip.duration = max(1, round(duration * self.clip.fps))
                        self.engine.set_clip(self.clip)
                        self.engine.set_frame(0)
                        playback_note = (
                            f"Transform playback is active for node "
                            f"{min(channel.node for channel in self.imported_animation_clip.channels)}.")
                    else:
                        playback_note = "The file exposes metadata but no readable transform curves."
                    self.animation_asset_status.setText(
                        f"Skeletal data read from file: {report.skeleton_count} skin(s), "
                        f"{report.joint_count} joint(s); {clips}. {playback_note} "
                        "Skin deformation is unavailable until the viewport has a skinned-mesh renderer.")
                else:
                    self.imported_animation_clip = None
                    self.animation_asset_status.setText(f"No playable skeletal data: {report.message}")
                sb = self.statusBar()
                if sb: sb.showMessage(f"Loaded model: {os.path.basename(path)}", 3000)
            else:
                QMessageBox.warning(self, "Load Failed", f"Failed to load model:\n{path}")
        else:
            QMessageBox.warning(self, "Error", "Viewport does not support loading models.")

    def refresh_timeline(self):
        """Rebuild timeline UI from current clip data."""
        self.tracks = self.clip.tracks
        self.track_headers.clear()
        
        # Remove old track items
        for item in self.timeline_view.tracks:
            if item.scene():
                self.timeline_view.scene.removeItem(item)
        self.timeline_view.tracks.clear()
        
        # Re-add tracks
        for track in self.tracks:
            self.add_track(track)

    def render_video(self):
        """Render the animation to MP4."""
        path, _ = QFileDialog.getSaveFileName(self, "Render Video", "", "MP4 Video (*.mp4)")
        if not path: return
        
        # Find audio track
        audio_path = None
        audio_offset = 0
        for track in self.tracks:
            if isinstance(track, AudioTrack) and not track.muted:
                audio_path = track.file_path
                audio_offset = track.start_frame
                break
                
        # Setup Exporter
        self.exporter = VideoExporter()
        self.exporter.finished.connect(self.on_render_finished)
        self.exporter.progress_changed.connect(lambda p: self.status_bar.showMessage(f"Rendering... {p}%", 0))
        
        self.status_bar.showMessage("Starting Render...", 0)
        
        # Disable UI
        self.setEnabled(False)
        
        # Start Render
        # We render the viewport (3D view)
        # Currently viewport is a placeholder, but we'll capture it anyway
        self.exporter.render(
            viewport=self.viewport,
            output_path=path,
            start_frame=0,
            end_frame=self.clip.duration,
            fps=self.clip.fps,
            audio_path=audio_path,
            audio_offset_frames=audio_offset,
            frame_callback=self.engine.set_frame
        )
        
    def on_render_finished(self, success, message):
        """Handle render completion."""
        self.setEnabled(True)
        if success:
            QMessageBox.information(self, "Render Complete", message)
            self.status_bar.showMessage("Render Complete", 3000)
        else:
            QMessageBox.critical(self, "Render Failed", message)
            self.status_bar.showMessage("Render Failed", 3000)

    def import_audio(self):
        """Import an audio file as a track."""
        path, _ = QFileDialog.getOpenFileName(self, "Import Audio", "", "Audio Files (*.wav *.mp3 *.ogg)")
        if path:
            # Create Audio Track
            name = os.path.basename(path)
            track = AudioTrack(name, path)
            
            # Add to clip
            self.clip.tracks.append(track)
            
            # Add to UI
            self.add_track(track)
            
            # Update Engine
            self.engine.set_clip(self.clip)
            
            self.status_bar.showMessage(f"Imported audio: {name}", 3000)

    def update_viewport_from_frame(self, frame):
        """Update 3D viewport based on current frame data."""
        if not self.clip: return
        
        # Get interpolated values for the current frame
        # We assume tracks are named after properties for now (e.g., "Position.X")
        # In a real system, we'd map objects to tracks more robustly
        
        pos = [0.0, 0.0, 0.0]
        rot = [0.0, 0.0, 0.0]
        scale = [1.0, 1.0, 1.0]
        
        # Current model transforms (if we want relative updates, but let's do absolute for now)
        # self.viewport.model_position etc.
        
        # Iterate tracks and apply values
        for track in self.clip.tracks:
            if isinstance(track, AudioTrack): continue
            
            val = track.get_value_at_frame(frame)
            
            if "Position.X" in track.property_path: pos[0] = val
            elif "Position.Y" in track.property_path: pos[1] = val
            elif "Position.Z" in track.property_path: pos[2] = val
            elif "Rotation.X" in track.property_path: rot[0] = val
            elif "Rotation.Y" in track.property_path: rot[1] = val
            elif "Rotation.Z" in track.property_path: rot[2] = val
            elif "Scale.X" in track.property_path: scale[0] = val
            elif "Scale.Y" in track.property_path: scale[1] = val
            elif "Scale.Z" in track.property_path: scale[2] = val
            
        # Update Viewport
        self.viewport.model_translation_x = pos[0]
        self.viewport.model_translation_y = pos[1]
        self.viewport.model_translation_z = pos[2]
        
        self.viewport.model_rotation_x = rot[0]
        self.viewport.model_rotation_y = rot[1]
        self.viewport.model_rotation_z = rot[2]
        
        self.viewport.model_scale = scale[0] # Uniform scale for now

        # A normal ModelViewer viewport has one global transform, so a verified glTF
        # curve can drive its first animated node but cannot pretend to deform a skin.
        # Editable timeline tracks remain the fallback for non-glTF assets.
        if self.imported_animation_clip:
            transforms = AnimationImporter.sample(self.imported_animation_clip,
                                                  frame / max(1, self.clip.fps))
            if transforms:
                node = min(transforms)
                transform = transforms[node]
                translation = transform.get('translation')
                if translation:
                    self.viewport.model_translation_x, self.viewport.model_translation_y, self.viewport.model_translation_z = translation
                scale_value = transform.get('scale')
                if scale_value:
                    self.viewport.model_scale = sum(scale_value) / 3.0
                rotation = transform.get('rotation')
                if rotation and len(rotation) == 4:
                    x, y, z, w = rotation
                    sinr_cosp, cosr_cosp = 2 * (w * x + y * z), 1 - 2 * (x * x + y * y)
                    sinp = 2 * (w * y - z * x)
                    siny_cosp, cosy_cosp = 2 * (w * z + x * y), 1 - 2 * (y * y + z * z)
                    self.viewport.model_rotation_x = math.degrees(math.atan2(sinr_cosp, cosr_cosp))
                    self.viewport.model_rotation_y = math.degrees(math.asin(max(-1.0, min(1.0, sinp))))
                    self.viewport.model_rotation_z = math.degrees(math.atan2(siny_cosp, cosy_cosp))
        
        self.viewport.update()

