"""
Studio Header Bar for RenderFox.
Provides top-level studio navigation, active asset telemetry, and unified cross-workspace controls.
"""

from __future__ import annotations

import os
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QMenu, QToolButton,
    QFrame, QSizePolicy, QFileDialog, QMessageBox, QDialog, QVBoxLayout,
    QComboBox, QSpinBox, QDoubleSpinBox, QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QAction, QIcon, QFont

from .icon_provider import get_icon, get_tab_icon
from ..processing.texel_density import calculate_texel_density, TexelDensityReport


class TexelDensityDialog(QDialog):
    """Quick dialog to inspect UV texel density for any 3D asset."""

    def __init__(self, model_path: str, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self.setWindowTitle("Texel Density & UV Diagnostics")
        self.setMinimumSize(520, 380)
        self.init_ui()
        self.run_analysis()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel(f"Asset: {os.path.basename(self.model_path)}")
        header.setStyleSheet("font-size: 13pt; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)

        # Controls form
        form = QFormLayout()
        self.res_combo = QComboBox()
        self.res_combo.addItems(["512", "1024", "2048", "4096", "8192"])
        self.res_combo.setCurrentText("2048")
        self.res_combo.currentTextChanged.connect(self.run_analysis)
        form.addRow("Texture Resolution (px):", self.res_combo)

        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(100.0, 10000.0)
        self.target_spin.setValue(1024.0)
        self.target_spin.setSuffix(" px/m (10.24 px/cm)")
        self.target_spin.valueChanged.connect(self.run_analysis)
        form.addRow("Target Density:", self.target_spin)

        layout.addLayout(form)

        # Results box
        self.results_frame = QFrame()
        self.results_frame.setStyleSheet(
            "background-color: #191b24; border: 1px solid #2e3346; border-radius: 8px; padding: 12px;"
        )
        res_layout = QVBoxLayout(self.results_frame)
        self.results_label = QLabel("Analyzing asset...")
        self.results_label.setWordWrap(True)
        self.results_label.setStyleSheet("font-size: 10pt; line-height: 1.5; color: #dcdfe8;")
        res_layout.addWidget(self.results_label)
        layout.addWidget(self.results_frame)

        # Actions
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

    def run_analysis(self):
        try:
            size = int(self.res_combo.currentText())
            target = float(self.target_spin.value())
            report = calculate_texel_density(self.model_path, texture_size=size, target_density_px_per_m=target)
            
            rating_color = "#38ef7d" if report.rating == "Optimal" else "#f59e0b" if report.rating == "Acceptable" else "#f87171"
            
            text = (
                f"<b>Average Texel Density:</b> {report.texel_density_px_per_m:.1f} px/m "
                f"({report.texel_density_px_per_cm:.2f} px/cm)<br>"
                f"<b>Density Range:</b> [{report.min_density_px_per_m:.1f} .. {report.max_density_px_per_m:.1f}] px/m<br>"
                f"<b>3D Surface Area:</b> {report.surface_area_3d:.4f} m²<br>"
                f"<b>UV Space Area:</b> {report.uv_area:.4f} ({report.uv_coverage_percent:.1f}% coverage)<br>"
                f"<b>Flipped UV Triangles:</b> {report.flipped_faces_count}<br>"
                f"<b>Rating:</b> <span style='color: {rating_color}; font-weight: bold;'>{report.rating}</span><br>"
                f"<b>Recommended Texture Resolution:</b> {report.recommended_resolution}x{report.recommended_resolution}"
            )
            self.results_label.setText(text)
        except Exception as e:
            self.results_label.setText(f"Analysis failed: {e}")


class StudioHeaderBar(QFrame):
    """Sleek top studio header showing workspace status, active asset, and shortcuts."""

    open_model_requested = pyqtSignal()
    handoff_requested = pyqtSignal(str, str)  # (workspace_name, file_path)
    theme_toggle_requested = pyqtSignal()

    WORKSPACE_NAMES = {
        0: ("Batch Render", "batch_render", "Queue and dispatch jobs to DCC render engines"),
        1: ("Library", "library", "Browse, tag, and organize asset library"),
        2: ("Models", "models", "Inspect, convert, and examine 3D models"),
        3: ("Mesh Tools", "mesh_tools", "Repair, decimate, and edit mesh geometry"),
        4: ("Point Clouds", "point_clouds", "Process, filter, and surface point cloud scans"),
        5: ("Pre-Processing", "preprocessing", "Topology cleanup, UV preparation, and LODs"),
        6: ("Post-Processing", "postprocessing", "Deliverables, archives, and asset organization"),
        7: ("Rendering", "rendering", "LookDev preview, material shading, and frame capture"),
        8: ("Animation", "animation", "glTF transform playback, timeline, and MP4 export"),
        9: ("Automation", "automation", "Folder watchers, scheduled tasks, and batch operations"),
        10: ("Pipeline", "pipeline", "Visual node-graph asset transformation pipeline"),
        11: ("Scripting", "scripting", "Python rfx engine automation and scripting editor"),
        12: ("Performance", "performance", "Hardware benchmark, tuning, and telemetry"),
        13: ("Diagnostics", "diagnostics", "System health audit, logs, and self-checks"),
        14: ("Settings", "settings", "Preferences, paths, themes, and configuration"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioHeader")
        self.setFixedHeight(44)
        self._current_asset = ""
        self._current_workspace_idx = 0
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        # 1. Studio Brand Pill
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(6)
        
        self.logo_label = QLabel("RENDERFOX")
        self.logo_label.setStyleSheet(
            "font-size: 11pt; font-weight: 800; letter-spacing: 1px; color: #ffffff;"
        )
        brand_layout.addWidget(self.logo_label)

        self.ver_label = QLabel("STUDIO 2.4")
        self.ver_label.setStyleSheet(
            "background-color: #2b3a67; color: #8cb4ff; font-size: 7.5pt; font-weight: 700; "
            "padding: 2px 6px; border-radius: 4px;"
        )
        brand_layout.addWidget(self.ver_label)
        layout.addLayout(brand_layout)

        # Separator line
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #2e3346; max-height: 20px;")
        layout.addWidget(sep1)

        # 2. Workspace Breadcrumb Pill
        self.ws_pill = QLabel("BATCH RENDER")
        self.ws_pill.setStyleSheet(
            "background-color: #1e2230; color: #a5b4d4; font-size: 8.5pt; font-weight: 600; "
            "padding: 4px 10px; border: 1px solid #2e354a; border-radius: 5px;"
        )
        layout.addWidget(self.ws_pill)

        layout.addSpacing(6)

        # 3. Active Asset HUD Pill (Center)
        self.asset_btn = QToolButton()
        self.asset_btn.setObjectName("activeAssetPill")
        self.asset_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.asset_btn.setText("No Asset Loaded (Click to Browse)")
        self.asset_btn.setIcon(get_icon("models"))
        self.asset_btn.setStyleSheet("""
            QToolButton#activeAssetPill {
                background-color: #191b24;
                border: 1px solid #2e3346;
                border-radius: 6px;
                color: #8c93a8;
                padding: 4px 12px;
                font-size: 8.5pt;
                font-weight: 500;
            }
            QToolButton#activeAssetPill:hover {
                background-color: #212431;
                border-color: #4b7bec;
                color: #ffffff;
            }
        """)
        self.setup_asset_menu()
        layout.addWidget(self.asset_btn)

        layout.addStretch()

        # 4. Quick Action Buttons (Right)
        # Load Model Button
        self.open_btn = QPushButton("Open Model")
        self.open_btn.setIcon(get_icon("import_model", size=16))
        self.open_btn.setIconSize(QSize(16, 16))
        self.open_btn.setMinimumWidth(104)
        self.open_btn.setMinimumHeight(26)
        self.open_btn.setToolTip("Open a 3D model from disk (Ctrl+O)")
        self.open_btn.clicked.connect(self.open_model_requested.emit)
        layout.addWidget(self.open_btn)

        # Texel Density Tool Button
        self.texel_btn = QPushButton("Texel Density")
        self.texel_btn.setIcon(get_icon("mesh_tools", size=16))
        self.texel_btn.setIconSize(QSize(16, 16))
        self.texel_btn.setMinimumWidth(110)
        self.texel_btn.setMinimumHeight(26)
        self.texel_btn.setToolTip("Inspect UV texel density and surface resolution")
        self.texel_btn.clicked.connect(self.open_texel_density)
        layout.addWidget(self.texel_btn)

        # Theme Toggle Button
        self.theme_btn = QPushButton()
        self.theme_btn.setIcon(get_icon("settings", size=16))
        self.theme_btn.setIconSize(QSize(16, 16))
        self.theme_btn.setFixedSize(28, 26)
        self.theme_btn.setToolTip("Toggle Theme (Dark / Midnight / Light)")
        self.theme_btn.clicked.connect(self.theme_toggle_requested.emit)
        self.theme_btn.setStyleSheet("padding: 0px;")
        layout.addWidget(self.theme_btn)

    def setup_asset_menu(self):
        """Create dropdown menu for active asset actions."""
        menu = QMenu(self)
        
        if self._current_asset:
            title_action = menu.addAction(f"Active: {os.path.basename(self._current_asset)}")
            title_action.setEnabled(False)
            menu.addSeparator()

            menu.addAction("Inspect in Model Viewer", lambda: self.handoff_requested.emit("models", self._current_asset))
            menu.addAction("Edit in Mesh Tools", lambda: self.handoff_requested.emit("mesh_tools", self._current_asset))
            menu.addAction("Prepare in Pre-Processing", lambda: self.handoff_requested.emit("preprocessing", self._current_asset))
            menu.addAction("LookDev in Rendering", lambda: self.handoff_requested.emit("rendering", self._current_asset))
            menu.addAction("Preview & Rig in Animation", lambda: self.handoff_requested.emit("animation", self._current_asset))
            menu.addAction("Polish in Post-Processing", lambda: self.handoff_requested.emit("postprocessing", self._current_asset))
            menu.addSeparator()
            menu.addAction("Calculate Texel Density...", self.open_texel_density)
            menu.addSeparator()
            open_other = menu.addAction("Open Different Model...")
            open_other.triggered.connect(self.open_model_requested.emit)
        else:
            open_action = menu.addAction("Browse for Model...")
            open_action.triggered.connect(self.open_model_requested.emit)

        self.asset_btn.setMenu(menu)

    def set_active_asset(self, path: str):
        """Update active asset display across the header."""
        self._current_asset = path
        if path and os.path.isfile(path):
            name = os.path.basename(path)
            ext = os.path.splitext(name)[1].upper().lstrip('.')
            size_kb = os.path.getsize(path) / 1024.0
            
            # Format size nicely
            if size_kb > 1024:
                size_str = f"{size_kb / 1024.0:.1f} MB"
            else:
                size_str = f"{size_kb:.0f} KB"

            self.asset_btn.setText(f"[{ext}] {name}  •  {size_str}")
            self.asset_btn.setStyleSheet("""
                QToolButton#activeAssetPill {
                    background-color: #1a2233;
                    border: 1px solid #3b69d8;
                    border-radius: 6px;
                    color: #75a7ff;
                    padding: 4px 12px;
                    font-size: 9pt;
                    font-weight: 600;
                }
                QToolButton#activeAssetPill:hover {
                    background-color: #222e46;
                    border-color: #608eff;
                    color: #ffffff;
                }
            """)
        else:
            self.asset_btn.setText("No Asset Loaded (Click to Browse)")
            self.asset_btn.setStyleSheet("""
                QToolButton#activeAssetPill {
                    background-color: #191b24;
                    border: 1px solid #2e3346;
                    border-radius: 6px;
                    color: #8c93a8;
                    padding: 4px 12px;
                    font-size: 8.5pt;
                    font-weight: 500;
                }
                QToolButton#activeAssetPill:hover {
                    background-color: #212431;
                    border-color: #4b7bec;
                    color: #ffffff;
                }
            """)
        self.setup_asset_menu()

    def set_active_workspace(self, index: int):
        """Update workspace indicator pill when user switches tabs."""
        self._current_workspace_idx = index
        info = self.WORKSPACE_NAMES.get(index, ("Workspace", "workspace", ""))
        self.ws_pill.setText(info[0].upper())
        self.ws_pill.setToolTip(f"{info[0]}: {info[2]}")

    def open_texel_density(self):
        """Open texel density analysis for active asset."""
        if not self._current_asset or not os.path.isfile(self._current_asset):
            path, _ = QFileDialog.getOpenFileName(
                self, "Select 3D Model for Texel Density", "",
                "3D Models (*.obj *.glb *.gltf *.ply *.stl *.fbx *.dae *.3mf);;All Files (*.*)"
            )
            if not path:
                return
            target_path = path
        else:
            target_path = self._current_asset

        dialog = TexelDensityDialog(target_path, self)
        dialog.exec()
