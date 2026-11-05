"""
Point Clouds tab: the pane that drives `src/processing/point_cloud_processor.py`.

One control, one verb. Every button here names an operation the backend already answers, and
every number shown is one the backend read back off the file that operation left on disk -
never counted off an object still held in memory. The pane owns threading, dialogs and the
sentences built from those numbers; the backend owns the vocabulary and the measurement.

What used to sit here instead was a second, private copy of that work: `import open3d`
closures written inside the click handlers, `self.processor` and `self.current_cloud_path`
read by the Poisson and distance handlers but never assigned (so both crashed the moment
they were clicked), `cluster_dbscan` / `register_point_clouds` / `apply_transform` /
`reconstruct_mesh` calls to methods the backend does not have, `path.replace('.', '_x.')`
to name the output (which rewrites every dot in the path, including the ones in a folder
called `v1.2`), a blocking `matplotlib.pyplot.show()` for the histogram, and thirteen
controls with nothing connected to them. Those closures are gone. The verbs they imitate
are real now, and each control calls exactly one of them.
"""

import os
from functools import partial

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QDialog,
                             QFormLayout, QLabel, QGroupBox, QGridLayout, QComboBox,
                             QFrame, QSpinBox, QCheckBox, QTextEdit, QTabWidget, QSlider,
                             QDoubleSpinBox, QFileDialog, QMessageBox, QListWidget,
                             QSplitter, QScrollArea, QProgressDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from ..processing.point_cloud_processor import PointCloudProcessor
from .unified_viewer import UnifiedOpen3DViewer
from .icon_provider import get_icon


# The verbs that leave a surface behind rather than another cloud - the backend's own list,
# because it is the one that writes those files. A surface goes to the viewer and to "Export
# as Mesh"; it never becomes the current model, since the next cloud operation on it would
# silently be measuring a mesh's vertices.
SURFACE_OPERATIONS = PointCloudProcessor.SURFACE_VERBS

# How many files each verb is expected to leave on disk. This is the whole of a progress
# dialog's honesty: the maximum is the number of files the run was asked to make, and the
# value is the number that actually landed. Nothing here is a percentage guessed at from
# how far along the operation feels, which is what the old indeterminate bar was really
# showing - motion, with no claim about progress behind it.
VERB_OUTPUT_FILES = {
    'analyze': 0, 'center': 1, 'normalize': 1, 'dedup': 1, 'voxel': 1, 'uniform': 1,
    'outliers_statistical': 1, 'outliers_radius': 1, 'crop': 1, 'translate': 1,
    'rotate': 1, 'scale': 1, 'normals': 1, 'planes': 2, 'cluster': 1, 'hull': 1,
    'poisson': 1, 'ball_pivoting': 1, 'alpha_shape': 1, 'features': 0,
    'register_icp': 1, 'register_ransac': 1, 'distances': 0, 'export': 1, 'pick': 1,
}

OP_NAMES = {
    'analyze': 'Measure', 'center': 'Center', 'normalize': 'Normalise',
    'dedup': 'Remove duplicates', 'voxel': 'Voxel downsample', 'uniform': 'Uniform downsample',
    'outliers_statistical': 'Statistical filter', 'outliers_radius': 'Radius filter',
    'crop': 'Crop to box', 'translate': 'Translate', 'rotate': 'Rotate', 'scale': 'Scale',
    'normals': 'Estimate normals', 'planes': 'Detect plane', 'cluster': 'DBSCAN clusters',
    'hull': 'Convex hull', 'poisson': 'Poisson surface', 'ball_pivoting': 'Ball pivoting',
    'alpha_shape': 'Alpha shape', 'features': 'FPFH features', 'register_icp': 'ICP align',
    'register_ransac': 'RANSAC align', 'distances': 'Neighbour distances', 'export': 'Export',
    'pick': 'Pick points',
}

RUNNING_TEXT = {
    'analyze': 'Measuring the cloud...',
    'center': 'Moving the centre to the origin...',
    'normalize': 'Scaling the longest side to 1...',
    'dedup': 'Dropping coincident points...',
    'voxel': 'Downsampling by voxel...',
    'uniform': 'Keeping every K-th point...',
    'outliers_statistical': 'Removing statistical outliers...',
    'outliers_radius': 'Removing radius outliers...',
    'crop': 'Cropping to the box...',
    'translate': 'Moving the cloud...',
    'rotate': 'Turning the cloud...',
    'scale': 'Scaling the cloud...',
    'normals': 'Estimating normals...',
    'planes': 'Fitting a plane...',
    'cluster': 'Clustering by density...',
    'hull': 'Building the convex hull...',
    'poisson': 'Reconstructing the Poisson surface...',
    'ball_pivoting': 'Rolling the ball over the cloud...',
    'alpha_shape': 'Building the alpha shape...',
    'features': 'Computing FPFH features...',
    'register_icp': 'Aligning by ICP...',
    'register_ransac': 'Aligning by RANSAC...',
    'distances': 'Measuring neighbour distances...',
    'export': 'Writing the file...',
    'pick': 'Waiting for the selection window...',
}


class CloudRunThread(QThread):
    """Run one verb away from the click handler and post the verdict it answered with.

    `PointCloudProcessor.run` is total - every path out of it is a dict, including the ones
    that caught an exception - so there is no error channel to carry here. That is also why
    `finished` is connected to the pane's back stop: if this thread ever ended without
    emitting, the modal dialog would still be waiting for a verdict that never comes.
    """

    verdict_ready = pyqtSignal(dict)

    def __init__(self, processor, operation, params):
        super().__init__()
        self.processor = processor
        self.operation = operation
        self.params = params
        self._stop_requested = False

    def request_stop(self):
        """Ask for a stop. A verb in the middle of a file finishes that file first."""
        self._stop_requested = True

    def run(self):
        verdict = self.processor.run(self.operation, self.params,
                                     lambda: self._stop_requested)
        self.verdict_ready.emit(verdict)


class BoundingBoxDialog(QDialog):
    """Enter the box to crop to, opened on the box the cloud actually fills."""

    def __init__(self, parent, min_bound=None, max_bound=None):
        super().__init__(parent)
        self.setWindowTitle("Crop Bounding Box")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        mins = list(min_bound or [-1.0, -1.0, -1.0])
        maxs = list(max_bound or [1.0, 1.0, 1.0])
        # ±1e12 rather than the ±10000 the box used to allow: a crop box is in the cloud's
        # own units, and a survey scan measured in metres is already past 10000 the day it
        # is opened. A box that makes no sense is refused by the backend with the numbers
        # it measured, not clamped away by this widget before the user can see it.
        self._spins = []
        for axis, low, high in zip('xyz', mins, maxs):
            self._spins.append(self._spin(low))
            self._spins.append(self._spin(high))
            form.addRow(f"Min {axis.upper()}:", self._spins[-2])
            form.addRow(f"Max {axis.upper()}:", self._spins[-1])

        layout.addLayout(form)
        layout.addWidget(QLabel("Values are in the units of the loaded file. The box starts "
                                "on the bounds of this cloud."))

        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Crop")
        ok_btn.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)

    @staticmethod
    def _spin(value):
        box = QDoubleSpinBox()
        box.setRange(-1e12, 1e12)
        box.setDecimals(6)
        box.setValue(float(value))
        return box

    def get_bounds(self):
        return ([self._spins[0].value(), self._spins[2].value(), self._spins[4].value()],
                [self._spins[1].value(), self._spins[3].value(), self._spins[5].value()])


class PointCloudsTab(QWidget):
    """Point cloud processing, measurement and surface reconstruction."""

    mesh_generated = pyqtSignal(str)
    add_to_library_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pc_processor = PointCloudProcessor()

        self.current_model_path = None
        self.target_model_path = None
        self.last_surface_path = None
        self.last_statistics = None
        self.last_distances = None

        self._active_thread = None
        self._active_sentence = None
        self._run_progress = None
        self._workers = []

        self.init_ui()
        self.setup_connections()

    # ---- the one way a verb is started -----------------------------------------

    def _keep_worker(self, thread):
        """Hold every started worker until it says it is done.

        Dropping the last Python reference of a running QThread is answered by Qt with a
        process abort - no exception, no message, the window simply goes. A worker is
        therefore released only by its own `finished` signal.
        """
        self._workers.append(thread)
        thread.finished.connect(lambda: self._workers.remove(thread))
        return thread

    def _no_file_message(self):
        QMessageBox.warning(self, "No point cloud loaded",
                            "Load a point cloud first. This operation works on the file "
                            "that is current now.")

    def _run(self, operation, params, sentence=None, silent=False):
        """Start one verb with a dialog whose numbers are files, or refuse to start it.

        `silent` is the follow-up measure a verb triggers on the file it just wrote. It
        shares this path entirely - worker, verdict, one-run guard - and adds no dialog and
        no status line of its own, because the user asked for one operation and a second
        "Measuring the cloud..." window for the same click reads like it did two things.
        """
        if self._active_thread is not None:
            QMessageBox.information(self, "One run at a time",
                                    f"{self._active_sentence} is still running. Wait for it "
                                    f"or press Cancel in its dialog before starting "
                                    f"{RUNNING_TEXT[operation].lower()}")
            return False

        sentence = sentence or RUNNING_TEXT[operation]
        expected = VERB_OUTPUT_FILES.get(operation, 1)
        progress = None
        if not silent:
            progress = QProgressDialog(sentence, "Cancel", 0, max(expected, 1), self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            # The dialog closes when the verdict has been reported, not when the number
            # happens to reach the maximum - an operation that leaves no file behind
            # finishes at 0 of 1.
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.setValue(0)
            progress.show()
            self.operation_label.setText(sentence)

        self._run_progress = progress
        self._active_sentence = sentence
        thread = self._keep_worker(CloudRunThread(self.pc_processor, operation, params))
        self._active_thread = thread
        thread.verdict_ready.connect(partial(self._verdict, progress, thread, silent=silent))
        thread.finished.connect(partial(self._end_run, progress, thread))
        if progress is not None:
            progress.canceled.connect(thread.request_stop)
        thread.start()
        return True

    def _dismiss(self, progress):
        if progress is None:
            return
        # `QDialog.wasClosed` is not exposed by PyQt6, so "is it still on screen" is the
        # question asked the way every Qt binding answers it.
        if progress.isVisible():
            progress.setValue(progress.maximum())
            progress.close()

    def _verdict(self, progress, thread, verdict, silent=False):
        """Report the single verdict the worker produced.

        The dialog and the thread arrive as arguments, never read back off
        `self._run_progress`/`self._active_thread`: `QProgressDialog.setValue` runs an event
        loop, so anything connected to the worker's signals can have already run a handler
        that nulled the attribute. The thread identity is here for the same reason - on the
        first live run every verb that measured its own result answered eight "ended without
        reporting a result" warnings, because the verb's `finished` signal landed while the
        pane was holding the newer measure thread.
        """
        if self._active_thread is thread:
            self._active_thread = None
        self._dismiss(progress)
        operation = verdict.get('operation', 'run')
        files = [f for f in (verdict.get('files') or []) if f]

        if verdict.get('success'):
            self._adopt(operation, files, verdict)
            if not silent:
                self._record(verdict, self._headline(verdict))
            self._report_family(operation, verdict)
        elif verdict.get('stopped'):
            reason = verdict.get('error') or 'the run was stopped'
            if silent:
                self.operation_label.setText(f"Measure of the result stopped: {reason}")
            else:
                self.operation_label.setText(f"Stopped: {reason}")
                QMessageBox.warning(self, f"{OP_NAMES.get(operation, operation)} stopped",
                                    reason)
            if files:
                # A stopped run still says which of its files are really on disk.
                self.history_list.addItem(
                    f"{OP_NAMES.get(operation, operation)} stopped after writing "
                    f"{', '.join(os.path.basename(f) for f in files)}")
                self.history_list.scrollToBottom()
        else:
            reason = verdict.get('error') or 'the run reported neither a file nor a reason'
            if silent:
                # The verb itself wrote its file; only the measurement of it failed, and
                # that belongs on the status line rather than in a dialog over a click that
                # did produce something.
                self.operation_label.setText(f"Measure of the result: {reason}")
                return
            self.operation_label.setText(f"{OP_NAMES.get(operation, operation)}: {reason}")
            QMessageBox.warning(self, f"{OP_NAMES.get(operation, operation)} refused", reason)

    def _end_run(self, progress, thread):
        """Back stop: this thread ended, so its dialog must go whether a verdict arrived."""
        self._dismiss(progress)
        if self._run_progress is progress:
            self._run_progress = None
        if self._active_thread is not thread:
            # A newer run owns the pane now, and its verdict is still on its way.
            return
        self._active_thread = None
        sentence = self._active_sentence or 'The run'
        self.operation_label.setText(f"{sentence} ended without reporting a result")
        QMessageBox.warning(self, "No result reported",
                            f"{sentence} ended without reporting a result. No file is "
                            f"claimed - check the folder it writes into.")

    def _adopt(self, operation, files, verdict):
        """Make the file a cloud verb just wrote the current model, so runs chain.

        This is the whole ecosystem argument in one method: downsample, then filter, then
        reconstruct works because each step's output is what the next step reads. The old
        pane updated `current_model_path` for three of its operations and not for the rest,
        so which button you had last clicked decided which file the next one used.
        """
        if operation in SURFACE_OPERATIONS and files:
            self.last_surface_path = files[0]
            self.viewer.load_from_file(files[0])
            return
        if operation == 'planes':
            # Two clouds, on-plane and off-plane. Neither is "the model"; the run names both.
            return
        if files and operation not in ('analyze', 'distances', 'features', 'export'):
            self.load_model(files[0], keep_history=True, announce=False)

    def _record(self, verdict, headline):
        operation = verdict.get('operation')
        self.history_list.addItem(f'{OP_NAMES.get(operation, operation)}: {headline}')
        self.history_list.scrollToBottom()
        self.operation_label.setText(headline)

    # ---- the sentences the numbers turn into ------------------------------------

    @staticmethod
    def _measure_text(value, digits=6):
        if isinstance(value, float):
            return f'{value:.{digits}f}'
        if isinstance(value, (list, tuple)):
            return ', '.join(PointCloudsTab._measure_text(v, digits) for v in value)
        return str(value)

    @staticmethod
    def _count(value):
        return f'{int(value):,}' if isinstance(value, (int, float)) else str(value)

    def _statistics_block(self, stats, size_bytes=None):
        lines = [
            f"Points: {self._count(stats['point_count'])}",
            f"Colours: {'yes' if stats['has_colors'] else 'no'}",
            f"Normals: {'yes' if stats['has_normals'] else 'no'}",
            f"Extent (x, y, z): {self._measure_text(stats['bounding_box'], 4)}",
            f"Centre (x, y, z): {self._measure_text(stats['centroid'], 4)}",
            f"Density: {stats['density']:.3f} points per unit cubed",
        ]
        if size_bytes is not None:
            lines.append(f"File: {size_bytes / 1024.0:.1f} KB")
        return lines

    def _headline(self, verdict):
        """One line that says what the run measured, from the verdict's own numbers."""
        operation = verdict.get('operation')
        measure = verdict.get('measure') or {}
        before = verdict.get('points_before')
        after = verdict.get('points_after')

        if operation == 'analyze':
            stats = measure.get('statistics') or {}
            return f"{self._count(stats.get('point_count'))} points measured"
        if operation == 'distances':
            return (f"mean {measure.get('average', 0):.6g}, min "
                    f"{measure.get('minimum', 0):.6g}, max {measure.get('maximum', 0):.6g} "
                    f"over {self._count(measure.get('samples'))} samples")
        if operation == 'features':
            return (f"voxel {measure.get('voxel_size', 0):.6g}: "
                    f"{self._count(measure.get('source_descriptors'))} source and "
                    f"{self._count(measure.get('target_descriptors'))} target descriptors")
        if operation in ('register_icp', 'register_ransac'):
            return (f"fitness {measure.get('fitness', 0):.4f}, RMSE "
                    f"{measure.get('rmse', 0):.6g} on "
                    f"{self._count(measure.get('correspondences'))} pairs -> "
                    f"{os.path.basename(verdict.get('output_path') or '')}")
        if operation == 'planes':
            return (f"plane {self._measure_text(measure.get('plane_equation'), 4)}: "
                    f"{self._count(measure.get('on_plane'))} on it, "
                    f"{self._count(measure.get('off_plane'))} off it")
        if operation in SURFACE_OPERATIONS:
            return (f"{self._count(measure.get('vertices'))} vertices, "
                    f"{self._count(measure.get('faces'))} faces -> "
                    f"{os.path.basename(verdict.get('output_path') or '')}")
        if operation == 'cluster':
            return (f"{measure.get('clusters')} clusters, "
                    f"{self._count(measure.get('noise'))} noise points")
        if operation == 'export':
            where = os.path.basename(verdict.get('output_path') or '')
            extra = (' - positions only, no faces, for software outside this app'
                     if not measure.get('readable_here') else '')
            return f"{self._count(after)} points written to {where}{extra}"
        if operation == 'pick':
            return f"{self._count(measure.get('picked'))} points picked"
        if operation == 'center':
            return f"moved by {self._measure_text(measure.get('moved_by'), 4)}"
        if operation == 'normalize':
            return f"scaled by {measure.get('scale', 0):.6g} to a unit extent"
        if operation == 'dedup':
            return f"{self._count(measure.get('removed'))} coincident points removed"
        if operation == 'voxel':
            return (f"voxel {measure.get('voxel_size', 0):.6g}: kept {self._count(after)} of "
                    f"{self._count(before)} ({measure.get('reduction', 0):.1f}% gone)")
        if operation == 'uniform':
            return f"every {measure.get('every_k')}th point: {self._count(after)} kept"
        if operation == 'outliers_statistical':
            return (f"{self._count(measure.get('removed'))} of {self._count(before)} removed "
                    f"({measure.get('nb_neighbors')} neighbours, ratio "
                    f"{measure.get('std_ratio')})")
        if operation == 'outliers_radius':
            return (f"{self._count(measure.get('removed'))} of {self._count(before)} removed "
                    f"({measure.get('nb_points')} within {measure.get('radius'):.6g})")
        if operation == 'crop':
            return (f"box kept {self._count(after)} of {self._count(before)}; "
                    f"{self._count(measure.get('removed'))} outside it")
        if operation == 'translate':
            return f"moved by {self._measure_text(measure.get('offset'), 4)}"
        if operation == 'rotate':
            return f"turned {self._measure_text(measure.get('degrees'), 2)} degrees"
        if operation == 'scale':
            return (f"scaled by {measure.get('factor'):.6g} to extent "
                    f"{self._measure_text(measure.get('extent'), 4)}")
        if operation == 'normals':
            return f"normals on {self._count(after)} points, {measure.get('knn')} neighbours each"
        # Only a verb with no sentence of its own falls back to the point counts. Keeping
        # this last is the point: before it sat here, `voxel` reported "900 -> 300" and the
        # voxel size the user typed never appeared.
        if before is not None and after is not None:
            return f"{self._count(before)} -> {self._count(after)} points"
        return str(verdict.get('error') or verdict.get('output_path') or 'no files written')

    def _detail(self, verdict):
        """The multi-line report for the family's own text area."""
        operation = verdict.get('operation')
        measure = verdict.get('measure') or {}
        if operation == 'analyze':
            return self._statistics_block(measure.get('statistics') or {},
                                          measure.get('bytes'))
        if operation in ('register_icp', 'register_ransac', 'features'):
            lines = [f"{OP_NAMES.get(operation)}: {self._headline(verdict)}"]
            matrix = measure.get('transformation')
            if matrix:
                lines.append('Transformation applied to the source:')
                lines.extend('  ' + self._measure_text(row, 4) for row in matrix)
            if operation == 'register_ransac':
                lines.append(f"at voxel {measure.get('voxel_size', 0):.6g}, match distance "
                             f"{measure.get('distance_threshold', 0):.6g}")
            if operation == 'register_icp':
                lines.append(f"{measure.get('correspondences')} pairs under the threshold, "
                             f"{measure.get('max_iteration', '')}")
            if operation == 'features':
                lines.append(f"{self._count(measure.get('source_points'))} source and "
                             f"{self._count(measure.get('target_points'))} points after "
                             f"downsampling; the next RANSAC run uses this voxel")
            return lines
        if operation == 'distances':
            lines = [f"Nearest-neighbour distances over "
                     f"{self._count(measure.get('samples'))} samples:",
                     f"  minimum  {measure.get('minimum', 0):.6g}",
                     f"  average  {measure.get('average', 0):.6g}",
                     f"  maximum  {measure.get('maximum', 0):.6g}"]
            lines.append('Run "Show Distance Histogram" for the ' +
                         str(len((measure.get('histogram') or {}).get('counts') or [])) +
                         ' bins between them.')
            return lines
        if operation == 'planes':
            return [f"Plane equation (a, b, c, d): "
                    f"{self._measure_text(measure.get('plane_equation'), 6)}",
                    f"On the plane: {self._count(measure.get('on_plane'))} points",
                    f"Off the plane: {self._count(measure.get('off_plane'))} points",
                    f"Within {measure.get('distance_threshold', 0):.6g} of it, "
                    f"{measure.get('num_iterations')} RANSAC iterations",
                    'Two files: ' + ', '.join(os.path.basename(f)
                                              for f in (verdict.get('files') or []))]
        return [self._headline(verdict)]

    def _fill_info(self, verdict):
        measure = verdict.get('measure') or {}
        stats = measure.get('statistics')
        if not stats:
            return
        self.last_statistics = stats
        self.info_points.setText(self._count(stats['point_count']))
        self.info_has_normals.setText('yes' if stats['has_normals'] else 'no')
        self.info_has_colors.setText('yes' if stats['has_colors'] else 'no')
        self.info_bounds.setText(self._measure_text(stats['bounding_box'], 4))

    def _measured_bounds(self):
        """The box the current cloud fills, from the measurement of it."""
        stats = self.last_statistics
        if not stats:
            return None, None
        centre = stats['centroid']
        extent = stats['bounding_box']
        return ([c - e / 2.0 for c, e in zip(centre, extent)],
                [c + e / 2.0 for c, e in zip(centre, extent)])

    # ---- the interface -----------------------------------------------------------

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        main_layout.addWidget(self.create_model_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = self.create_left_panel()
        scroll_left = QScrollArea()
        scroll_left.setWidget(left_panel)
        scroll_left.setWidgetResizable(True)
        scroll_left.setFrameShape(QFrame.Shape.NoFrame)
        splitter.addWidget(scroll_left)
        splitter.addWidget(self.create_right_panel())
        splitter.setSizes([380, 820])
        main_layout.addWidget(splitter)

    def create_model_header(self):
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        frame.setMaximumHeight(80)

        layout = QVBoxLayout(frame)
        header_layout = QHBoxLayout()

        self.current_model_label = QLabel("No point cloud loaded")
        self.current_model_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.change_model_btn = QPushButton("Change Model")
        self.change_model_btn.setIcon(get_icon("folder"))
        self.add_model_btn = QPushButton("Add to Library")
        self.add_model_btn.setIcon(get_icon("add"))
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setIcon(get_icon("refresh"))

        header_layout.addWidget(self.current_model_label)
        header_layout.addStretch()
        header_layout.addWidget(self.change_model_btn)
        header_layout.addWidget(self.add_model_btn)
        header_layout.addWidget(self.reload_btn)

        explanation = QLabel("Load a scan, run one operation at a time, and every number "
                             "here is measured off the file that operation wrote")
        explanation.setStyleSheet("color: #8c93a8; font-size: 8.5pt;")
        explanation.setWordWrap(True)

        layout.addLayout(header_layout)
        layout.addWidget(explanation)
        return frame

    def create_left_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.tools_tabs = QTabWidget()
        self.tools_tabs.addTab(self.create_basic_operations_tab(), "Basic")
        self.tools_tabs.addTab(self.create_filtering_tab(), "Filter")
        self.tools_tabs.addTab(self.create_registration_tab(), "Register")
        self.tools_tabs.addTab(self.create_reconstruction_tab(), "Reconstruct")
        self.tools_tabs.addTab(self.create_analysis_tab(), "Analyze")
        layout.addWidget(self.tools_tabs)

        status_group = QGroupBox("Operations")
        status_layout = QVBoxLayout()
        self.operation_label = QLabel("Ready")
        self.operation_label.setWordWrap(True)
        status_layout.addWidget(self.operation_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        layout.addStretch()
        return widget

    def _length_spin(self, value=0.0, low=0.0, high=1e12, decimals=6, step=None):
        """A typed number box that does not quietly rewrite what was typed.

        The ranges used to be 0.001 to 1.0 whatever the scan was, so a 40 m site file could
        not be entered at all and a 0 could not be entered to see what happened. The backend
        is what refuses a length of 0, with the sentence "a voxel edge of 0 is not a length"
        - which is a reason, where a clamp is silence.
        """
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(decimals)
        box.setValue(value)
        if step is not None:
            box.setSingleStep(step)
        return box

    def _angle_spin(self, value=0.0):
        box = QDoubleSpinBox()
        box.setRange(-1e12, 1e12)
        box.setDecimals(4)
        box.setValue(value)
        box.setSuffix(' deg')
        return box

    def create_basic_operations_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)

        io_group = QGroupBox("Import/Export")
        io_layout = QVBoxLayout()
        self.load_pcd_btn = QPushButton("Load Point Cloud")
        self.load_pcd_btn.setIcon(get_icon("folder"))
        self.save_pcd_btn = QPushButton("Save Point Cloud")
        self.save_pcd_btn.setIcon(get_icon("backup"))
        self.export_mesh_btn = QPushButton("Export as Mesh")
        self.export_mesh_btn.setIcon(get_icon("export"))
        io_layout.addWidget(self.load_pcd_btn)
        io_layout.addWidget(self.save_pcd_btn)
        io_layout.addWidget(self.export_mesh_btn)
        io_group.setLayout(io_layout)
        layout.addWidget(io_group)

        transform_group = QGroupBox("Transformations")
        transform_layout = QVBoxLayout()

        transform_layout.addWidget(QLabel("Translation, in the units of the file:"))
        trans_frame = QFrame()
        trans_layout = QFormLayout(trans_frame)
        self.trans_x_spin = self._length_spin(low=-1e12)
        self.trans_y_spin = self._length_spin(low=-1e12)
        self.trans_z_spin = self._length_spin(low=-1e12)
        trans_layout.addRow("X:", self.trans_x_spin)
        trans_layout.addRow("Y:", self.trans_y_spin)
        trans_layout.addRow("Z:", self.trans_z_spin)
        self.apply_translation_btn = QPushButton("Apply Translation")
        transform_layout.addWidget(trans_frame)
        transform_layout.addWidget(self.apply_translation_btn)

        transform_layout.addWidget(QLabel("Rotation about the cloud's own centre:"))
        rot_frame = QFrame()
        rot_layout = QFormLayout(rot_frame)
        self.rot_x_spin = self._angle_spin()
        self.rot_y_spin = self._angle_spin()
        self.rot_z_spin = self._angle_spin()
        rot_layout.addRow("X:", self.rot_x_spin)
        rot_layout.addRow("Y:", self.rot_y_spin)
        rot_layout.addRow("Z:", self.rot_z_spin)
        self.apply_rotation_btn = QPushButton("Apply Rotation")
        transform_layout.addWidget(rot_frame)
        transform_layout.addWidget(self.apply_rotation_btn)

        transform_layout.addWidget(QLabel("Scale, above 0:"))
        scale_layout = QHBoxLayout()
        self.scale_spin = self._length_spin(1.0, decimals=4, step=0.1)
        self.apply_scale_btn = QPushButton("Apply Scale")
        scale_layout.addWidget(self.scale_spin)
        scale_layout.addWidget(self.apply_scale_btn)
        transform_layout.addLayout(scale_layout)

        transform_group.setLayout(transform_layout)
        layout.addWidget(transform_group)

        processing_group = QGroupBox("Basic Processing")
        processing_layout = QVBoxLayout()
        self.center_btn = QPushButton("Center Point Cloud")
        self.normalize_btn = QPushButton("Normalize Scale")
        self.remove_duplicates_btn = QPushButton("Remove Duplicates")
        self.estimate_normals_btn = QPushButton("Estimate Normals")
        knn_layout = QHBoxLayout()
        knn_layout.addWidget(QLabel("Neighbours per point:"))
        # 1e12 upper bound on purpose: the backend reads the cloud first and answers
        # "300 neighbours needs a cloud of at least 300 points and this one has 90",
        # which is the only way a user finds out how big their scan is.
        self.normals_knn_spin = QSpinBox()
        self.normals_knn_spin.setRange(3, 1000000)
        self.normals_knn_spin.setValue(30)
        knn_layout.addWidget(self.normals_knn_spin)
        knn_layout.addStretch()
        processing_layout.addWidget(self.center_btn)
        processing_layout.addWidget(self.normalize_btn)
        processing_layout.addWidget(self.remove_duplicates_btn)
        processing_layout.addLayout(knn_layout)
        processing_layout.addWidget(self.estimate_normals_btn)
        processing_group.setLayout(processing_layout)
        layout.addWidget(processing_group)

        layout.addStretch()
        return scroll

    def create_filtering_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)

        outlier_group = QGroupBox("Statistical Outlier Removal")
        outlier_layout = QFormLayout()
        self.outlier_neighbors_spin = QSpinBox()
        self.outlier_neighbors_spin.setRange(1, 1000000)
        self.outlier_neighbors_spin.setValue(20)
        self.outlier_std_spin = self._length_spin(2.0, decimals=3, step=0.1)
        outlier_layout.addRow("Neighbors:", self.outlier_neighbors_spin)
        outlier_layout.addRow("Std Ratio:", self.outlier_std_spin)
        self.remove_outliers_btn = QPushButton("Remove Statistical Outliers")
        outlier_group.setLayout(outlier_layout)
        layout.addWidget(outlier_group)
        layout.addWidget(self.remove_outliers_btn)

        radius_group = QGroupBox("Radius Outlier Removal")
        radius_layout = QFormLayout()
        self.radius_spin = self._length_spin(0.05, step=0.001)
        self.min_points_spin = QSpinBox()
        self.min_points_spin.setRange(1, 1000000)
        self.min_points_spin.setValue(16)
        radius_layout.addRow("Radius:", self.radius_spin)
        radius_layout.addRow("Min Points:", self.min_points_spin)
        self.remove_radius_outliers_btn = QPushButton("Remove Radius Outliers")
        radius_group.setLayout(radius_layout)
        layout.addWidget(radius_group)
        layout.addWidget(self.remove_radius_outliers_btn)

        voxel_group = QGroupBox("Voxel Downsampling")
        voxel_layout = QFormLayout()
        self.voxel_size_spin = self._length_spin(0.01, step=0.001)
        voxel_layout.addRow("Voxel Size:", self.voxel_size_spin)
        self.voxel_downsample_btn = QPushButton("Apply Voxel Downsampling")
        voxel_group.setLayout(voxel_layout)
        layout.addWidget(voxel_group)
        layout.addWidget(self.voxel_downsample_btn)

        uniform_group = QGroupBox("Uniform Downsampling")
        uniform_layout = QFormLayout()
        self.uniform_k_spin = QSpinBox()
        self.uniform_k_spin.setRange(1, 1000000)
        self.uniform_k_spin.setValue(5)
        uniform_layout.addRow("Every K-th Point:", self.uniform_k_spin)
        self.uniform_downsample_btn = QPushButton("Apply Uniform Downsampling")
        uniform_group.setLayout(uniform_layout)
        layout.addWidget(uniform_group)
        layout.addWidget(self.uniform_downsample_btn)

        crop_group = QGroupBox("Cropping")
        crop_layout = QVBoxLayout()
        self.crop_box_btn = QPushButton("Crop to Bounding Box")
        self.crop_interactive_btn = QPushButton("Interactive Crop")
        crop_layout.addWidget(self.crop_box_btn)
        crop_layout.addWidget(self.crop_interactive_btn)
        crop_group.setLayout(crop_layout)
        layout.addWidget(crop_group)

        layout.addStretch()
        return scroll

    def create_registration_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)

        target_group = QGroupBox("Target Point Cloud")
        target_layout = QVBoxLayout()
        self.load_target_btn = QPushButton("Load Target")
        self.load_target_btn.setIcon(get_icon("folder"))
        self.target_info_label = QLabel("No target loaded")
        self.target_info_label.setWordWrap(True)
        target_layout.addWidget(self.load_target_btn)
        target_layout.addWidget(self.target_info_label)
        target_group.setLayout(target_layout)
        layout.addWidget(target_group)

        icp_group = QGroupBox("ICP Registration")
        icp_layout = QFormLayout()
        self.icp_threshold_spin = self._length_spin(0.02, step=0.001)
        self.icp_max_iter_spin = QSpinBox()
        self.icp_max_iter_spin.setRange(1, 1000000)
        self.icp_max_iter_spin.setValue(100)
        icp_layout.addRow("Match distance:", self.icp_threshold_spin)
        icp_layout.addRow("Max Iterations:", self.icp_max_iter_spin)
        self.run_icp_btn = QPushButton("Run ICP Registration")
        icp_group.setLayout(icp_layout)
        layout.addWidget(icp_group)
        layout.addWidget(self.run_icp_btn)

        feature_group = QGroupBox("Feature-based Registration")
        feature_layout = QFormLayout()
        self.feature_voxel_spin = self._length_spin(0.0, step=0.01)
        self.feature_voxel_spin.setToolTip("0 means: take the spacing of the cloud itself "
                                           "and use 1.5 times it")
        feature_layout.addRow("Voxel (0 = measured):", self.feature_voxel_spin)
        self.extract_features_btn = QPushButton("Extract FPFH Features")
        self.run_ransac_btn = QPushButton("Run RANSAC Registration")
        feature_group.setLayout(feature_layout)
        layout.addWidget(feature_group)
        layout.addWidget(self.extract_features_btn)
        layout.addWidget(self.run_ransac_btn)

        results_group = QGroupBox("Registration Results")
        results_layout = QVBoxLayout()
        self.registration_results = QTextEdit()
        self.registration_results.setMaximumHeight(160)
        self.registration_results.setReadOnly(True)
        results_layout.addWidget(self.registration_results)
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        layout.addStretch()
        return scroll

    def create_reconstruction_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)

        format_group = QGroupBox("Surface Output")
        format_layout = QFormLayout()
        # Every format the app's own mesh writer answers True for, asked of it at startup -
        # not a list of extensions this build may not be able to write.
        self.surface_format_combo = QComboBox()
        self.surface_format_combo.addItems(self.pc_processor.surface_formats())
        # .ply is the opening choice rather than whatever the list's alphabetical first
        # happens to be, because it is the surface format this app always reads back.
        if '.ply' in self.pc_processor.surface_formats():
            self.surface_format_combo.setCurrentText('.ply')
        self.surface_format_combo.setToolTip("Written through FormatConverter, the same "
                                             "writer Mesh Tools reads back")
        format_layout.addRow("Save surfaces as:", self.surface_format_combo)
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)

        poisson_group = QGroupBox("Poisson Surface Reconstruction")
        poisson_layout = QFormLayout()
        # Depth 12 is the ceiling because a deeper octree is answered by the native
        # allocator killing the process, not by an exception this pane could report.
        self.poisson_depth_spin = QSpinBox()
        self.poisson_depth_spin.setRange(1, 12)
        self.poisson_depth_spin.setValue(9)
        self.poisson_width_spin = QSpinBox()
        self.poisson_width_spin.setRange(0, 100)
        self.poisson_width_spin.setValue(0)
        self.poisson_scale_spin = self._length_spin(1.1, decimals=3, step=0.1)
        self.poisson_linear_fit_cb = QCheckBox("Linear fit (faster, faceted)")
        self.poisson_trim_cb = QCheckBox("Trim the low-density shell")
        self.poisson_trim_cb.setToolTip("Poisson closes every open boundary with a skin of "
                                        "near-zero density; this cuts it by density "
                                        "percentiles 1 and 99")
        self.poisson_trim_cb.setChecked(True)
        poisson_layout.addRow("Octree depth:", self.poisson_depth_spin)
        poisson_layout.addRow("Width:", self.poisson_width_spin)
        poisson_layout.addRow("Scale:", self.poisson_scale_spin)
        poisson_layout.addRow(self.poisson_linear_fit_cb)
        poisson_layout.addRow(self.poisson_trim_cb)
        self.run_poisson_btn = QPushButton("Run Poisson Reconstruction")
        poisson_group.setLayout(poisson_layout)
        layout.addWidget(poisson_group)
        layout.addWidget(self.run_poisson_btn)

        ball_group = QGroupBox("Ball Pivoting Algorithm")
        ball_layout = QFormLayout()
        self.ball_radius_spin = self._length_spin(0.0, step=0.001)
        self.ball_radius_spin.setToolTip("0 means: three radii derived from the cloud's own "
                                         "neighbour spacing")
        ball_layout.addRow("Ball Radius (0 = measured):", self.ball_radius_spin)
        self.run_ball_pivoting_btn = QPushButton("Run Ball Pivoting")
        ball_group.setLayout(ball_layout)
        layout.addWidget(ball_group)
        layout.addWidget(self.run_ball_pivoting_btn)

        alpha_group = QGroupBox("Alpha Shapes")
        alpha_layout = QFormLayout()
        self.alpha_value_spin = self._length_spin(0.03, step=0.001)
        alpha_layout.addRow("Alpha Value:", self.alpha_value_spin)
        self.run_alpha_shapes_btn = QPushButton("Create Alpha Shape")
        alpha_group.setLayout(alpha_layout)
        layout.addWidget(alpha_group)
        layout.addWidget(self.run_alpha_shapes_btn)

        hull_group = QGroupBox("Convex Hull")
        hull_layout = QVBoxLayout()
        self.create_convex_hull_btn = QPushButton("Create Convex Hull")
        hull_layout.addWidget(self.create_convex_hull_btn)
        hull_group.setLayout(hull_layout)
        layout.addWidget(hull_group)

        layout.addStretch()
        return scroll

    def create_analysis_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)

        stats_group = QGroupBox("Statistics")
        stats_layout = QVBoxLayout()
        self.compute_stats_btn = QPushButton("Compute Statistics")
        self.stats_display = QTextEdit()
        self.stats_display.setMaximumHeight(160)
        self.stats_display.setReadOnly(True)
        stats_layout.addWidget(self.compute_stats_btn)
        stats_layout.addWidget(self.stats_display)
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        distance_group = QGroupBox("Distance Analysis")
        distance_layout = QVBoxLayout()
        self.compute_distances_btn = QPushButton("Compute Nearest Distances")
        self.distance_histogram_btn = QPushButton("Show Distance Histogram")
        self.histogram_view = QTextEdit()
        self.histogram_view.setReadOnly(True)
        self.histogram_view.setMaximumHeight(200)
        self.histogram_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        distance_layout.addWidget(self.compute_distances_btn)
        distance_layout.addWidget(self.distance_histogram_btn)
        distance_layout.addWidget(self.histogram_view)
        distance_group.setLayout(distance_layout)
        layout.addWidget(distance_group)

        clustering_group = QGroupBox("Clustering")
        clustering_layout = QFormLayout()
        self.cluster_eps_spin = self._length_spin(0.02, step=0.001)
        self.cluster_min_points_spin = QSpinBox()
        self.cluster_min_points_spin.setRange(1, 1000000)
        self.cluster_min_points_spin.setValue(10)
        clustering_layout.addRow("Epsilon:", self.cluster_eps_spin)
        clustering_layout.addRow("Min Points:", self.cluster_min_points_spin)
        self.run_clustering_btn = QPushButton("Run DBSCAN Clustering")
        clustering_group.setLayout(clustering_layout)
        layout.addWidget(clustering_group)
        layout.addWidget(self.run_clustering_btn)

        plane_group = QGroupBox("Plane Detection")
        plane_layout = QFormLayout()
        self.plane_threshold_spin = self._length_spin(0.01, step=0.001)
        self.plane_ransac_n_spin = QSpinBox()
        self.plane_ransac_n_spin.setRange(3, 10)
        self.plane_ransac_n_spin.setValue(3)
        self.plane_iterations_spin = QSpinBox()
        self.plane_iterations_spin.setRange(1, 1000000)
        self.plane_iterations_spin.setValue(1000)
        plane_layout.addRow("Distance Threshold:", self.plane_threshold_spin)
        plane_layout.addRow("Points per trial:", self.plane_ransac_n_spin)
        plane_layout.addRow("Iterations:", self.plane_iterations_spin)
        self.detect_planes_btn = QPushButton("Detect Planes (RANSAC)")
        plane_group.setLayout(plane_layout)
        layout.addWidget(plane_group)
        layout.addWidget(self.detect_planes_btn)

        layout.addStretch()
        return scroll

    def create_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.create_viewer_tab(), "3D Viewer")
        self.right_tabs.addTab(self.create_info_tab(), "Information")
        self.right_tabs.addTab(self.create_results_tab(), "Results")
        layout.addWidget(self.right_tabs)
        return widget

    def create_viewer_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.viewer = UnifiedOpen3DViewer()
        layout.addWidget(self.viewer)

        controls_frame = QFrame()
        controls_layout = QHBoxLayout(controls_frame)

        controls_layout.addWidget(QLabel("Point Size:"))
        # The slider is 1-10 because that is the range a drag is useful over; the box beside
        # it is 0-200 because typing is not a drag. The two stay in step both ways.
        self.point_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.point_size_slider.setRange(1, 10)
        self.point_size_slider.setValue(3)
        self.point_size_box = self._length_spin(3.0, high=200.0, decimals=2, step=0.5)
        self.point_size_box.setSuffix(' px')
        controls_layout.addWidget(self.point_size_slider)
        controls_layout.addWidget(self.point_size_box)

        self.show_normals_cb = QCheckBox("Show Normals")
        self.show_wireframe_cb = QCheckBox("Wireframe")
        controls_layout.addWidget(self.show_normals_cb)
        controls_layout.addWidget(self.show_wireframe_cb)
        controls_layout.addStretch()

        self.reset_view_btn = QPushButton("Reset View")
        self.reset_view_btn.setIcon(get_icon("reset_view"))
        self.fit_view_btn = QPushButton("Fit to View")
        self.fit_view_btn.setIcon(get_icon("focus"))
        self.screenshot_btn = QPushButton("Screenshot")
        self.screenshot_btn.setIcon(get_icon("camera"))
        controls_layout.addWidget(self.reset_view_btn)
        controls_layout.addWidget(self.fit_view_btn)
        controls_layout.addWidget(self.screenshot_btn)

        layout.addWidget(controls_frame)
        return widget

    def create_info_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()
        self.info_filename = QLabel("No point cloud loaded")
        self.info_points = QLabel("-")
        self.info_has_normals = QLabel("-")
        self.info_has_colors = QLabel("-")
        self.info_bounds = QLabel("-")
        self.info_surface = QLabel("none built from this cloud yet")
        self.info_surface.setWordWrap(True)
        basic_layout.addRow("Filename:", self.info_filename)
        basic_layout.addRow("Points:", self.info_points)
        basic_layout.addRow("Has Normals:", self.info_has_normals)
        basic_layout.addRow("Has Colors:", self.info_has_colors)
        basic_layout.addRow("Extent (x, y, z):", self.info_bounds)
        basic_layout.addRow("Surface:", self.info_surface)
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)

        stats_group = QGroupBox("Detailed Statistics")
        stats_layout = QVBoxLayout()
        self.detailed_stats = QTextEdit()
        self.detailed_stats.setReadOnly(True)
        self.detailed_stats.setMaximumHeight(220)
        stats_layout.addWidget(self.detailed_stats)
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        layout.addStretch()
        return widget

    def create_results_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        history_group = QGroupBox("Processing History")
        history_layout = QVBoxLayout()
        self.history_list = QListWidget()
        self.clear_history_btn = QPushButton("Clear History")
        history_layout.addWidget(self.history_list)
        history_layout.addWidget(self.clear_history_btn)
        history_group.setLayout(history_layout)
        layout.addWidget(history_group)

        export_group = QGroupBox("Export Options")
        export_layout = QGridLayout()
        self.export_pcd_btn = QPushButton("Export PCD")
        self.export_ply_btn = QPushButton("Export PLY")
        self.export_xyz_btn = QPushButton("Export XYZ")
        self.export_obj_btn = QPushButton("Export OBJ")
        export_layout.addWidget(self.export_pcd_btn, 0, 0)
        export_layout.addWidget(self.export_ply_btn, 0, 1)
        export_layout.addWidget(self.export_xyz_btn, 1, 0)
        export_layout.addWidget(self.export_obj_btn, 1, 1)
        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        note = QLabel("PCD, PLY and XYZ are read back by this app. OBJ leaves as a vertex "
                      "list for software outside it - a mesh file with no faces is not a "
                      "mesh here.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #8c93a8; font-size: 8.5pt;")
        layout.addWidget(note)

        layout.addStretch()
        return widget

    def setup_connections(self):
        self.change_model_btn.clicked.connect(self.change_model)
        self.reload_btn.clicked.connect(self.reload_current_model)
        self.add_model_btn.clicked.connect(self.add_to_library)

        self.load_pcd_btn.clicked.connect(self.load_point_cloud)
        self.save_pcd_btn.clicked.connect(self.save_point_cloud)
        self.export_mesh_btn.clicked.connect(self.export_as_mesh)

        self.apply_translation_btn.clicked.connect(self.apply_translation)
        self.apply_rotation_btn.clicked.connect(self.apply_rotation)
        self.apply_scale_btn.clicked.connect(self.apply_scale)
        self.center_btn.clicked.connect(self.center_point_cloud)
        self.normalize_btn.clicked.connect(self.normalize_point_cloud)
        self.remove_duplicates_btn.clicked.connect(self.remove_duplicates)
        self.estimate_normals_btn.clicked.connect(self.estimate_normals)

        self.remove_outliers_btn.clicked.connect(self.remove_statistical_outliers)
        self.remove_radius_outliers_btn.clicked.connect(self.remove_radius_outliers)
        self.voxel_downsample_btn.clicked.connect(self.voxel_downsample)
        self.uniform_downsample_btn.clicked.connect(self.uniform_downsample)
        self.crop_box_btn.clicked.connect(self.crop_box)
        self.crop_interactive_btn.clicked.connect(self.crop_interactive)

        self.load_target_btn.clicked.connect(self.load_target_model)
        self.run_icp_btn.clicked.connect(self.run_icp_registration)
        self.extract_features_btn.clicked.connect(self.extract_features)
        self.run_ransac_btn.clicked.connect(self.run_ransac_registration)

        self.run_poisson_btn.clicked.connect(self.poisson_reconstruction)
        self.run_ball_pivoting_btn.clicked.connect(self.run_ball_pivoting)
        self.run_alpha_shapes_btn.clicked.connect(self.run_alpha_shapes)
        self.create_convex_hull_btn.clicked.connect(self.create_convex_hull)

        self.compute_stats_btn.clicked.connect(self.compute_statistics)
        self.compute_distances_btn.clicked.connect(self.compute_distances)
        self.distance_histogram_btn.clicked.connect(self.show_distance_histogram)
        self.run_clustering_btn.clicked.connect(self.run_clustering)
        self.detect_planes_btn.clicked.connect(self.detect_planes)

        self.export_pcd_btn.clicked.connect(lambda: self.export_point_cloud('.pcd'))
        self.export_ply_btn.clicked.connect(lambda: self.export_point_cloud('.ply'))
        self.export_xyz_btn.clicked.connect(lambda: self.export_point_cloud('.xyz'))
        self.export_obj_btn.clicked.connect(lambda: self.export_point_cloud('.obj'))
        self.clear_history_btn.clicked.connect(self.clear_history)

        self.point_size_slider.valueChanged.connect(self._point_size_from_slider)
        self.point_size_box.valueChanged.connect(self._point_size_from_box)
        self.show_normals_cb.toggled.connect(self.viewer.set_show_normals)
        self.show_wireframe_cb.toggled.connect(self.viewer.set_show_wireframe)
        self.reset_view_btn.clicked.connect(self.reset_display)
        self.fit_view_btn.clicked.connect(self.fit_to_view)
        self.screenshot_btn.clicked.connect(self.capture_screen)

    # ---- loading -----------------------------------------------------------------

    def _cloud_filter(self):
        return ("Point clouds (%s);;All files (*)"
                % ' '.join('*' + ext for ext in self.pc_processor.readable_formats()))

    def change_model(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Point Cloud", "",
                                                   self._cloud_filter())
        if file_path:
            self.load_model(file_path)

    def load_point_cloud(self):
        self.change_model()

    def load_point_cloud_file(self, file_path):
        """The entry point the rest of the app uses to hand a file to this pane."""
        self.load_model(file_path)

    def load_model(self, file_path, keep_history=False, announce=True):
        """Show one file and measure it, or say why neither happened.

        Loading used to set `current_model_path` first and then discover the viewer could
        not open the file, so the header named a model the pane was not holding. The viewer
        answer comes first now, and the labels only move once there is something on screen
        that matches them.

        `announce=False` is a verb's own follow-up measure: no status line, no dialog, and
        the sentence the user asked about stays where it is.
        """
        if not os.path.isfile(file_path):
            QMessageBox.warning(self, "No such file", f"There is no file at {file_path}")
            return

        if announce:
            self.operation_label.setText(f"Opening {os.path.basename(file_path)}...")
        if not self.viewer.load_from_file(file_path):
            self.operation_label.setText(f"Cannot show {os.path.basename(file_path)}")
            QMessageBox.warning(
                self, "Cannot show this file",
                f"{os.path.basename(file_path)} opens here as neither a mesh with faces nor "
                f"a cloud with points. A cloud reader here takes "
                f"{', '.join(self.pc_processor.readable_formats())}.")
            return

        replaced = os.path.normcase(file_path) != os.path.normcase(self.current_model_path or '')
        self.current_model_path = file_path
        if replaced:
            # A surface or a distance report describes the points it was made from, so a
            # different cloud retires them. The same file coming back - Reload, or a verb
            # measuring what it just wrote - does not; that used to answer "no surface has
            # been built" after a surface had been built two clicks earlier.
            self.last_distances = None
            self.last_surface_path = None
        self.info_filename.setText(os.path.basename(file_path))
        self.current_model_label.setText(f"Current: {os.path.basename(file_path)}")
        if not keep_history:
            self._forget_previous_run()
        self._run('analyze', {'file_path': file_path}, silent=not announce)

    def _forget_previous_run(self):
        """Drop every report that belongs to the file this one replaced."""
        self.history_list.clear()
        self.detailed_stats.setPlainText('')
        self.stats_display.setPlainText('')
        self.histogram_view.setPlainText('')
        self.registration_results.setPlainText('')
        self.last_statistics = None
        for label in (self.info_points, self.info_has_normals, self.info_has_colors,
                      self.info_bounds):
            label.setText('-')
        self.info_surface.setText('none built from this cloud yet')

    def reload_current_model(self):
        if not self.current_model_path:
            self._no_file_message()
            return
        self.load_model(self.current_model_path)

    def add_to_library(self):
        if not self.current_model_path:
            self._no_file_message()
            return
        self.add_to_library_requested.emit(self.current_model_path)
        self.operation_label.setText(
            f"{os.path.basename(self.current_model_path)} handed to the Library pane")

    # ---- export ------------------------------------------------------------------

    def save_point_cloud(self):
        if not self.current_model_path:
            self._no_file_message()
            return
        extension = os.path.splitext(self.current_model_path)[1].lower() or '.ply'
        self.export_point_cloud(extension)

    def export_point_cloud(self, extension):
        """Ask where the current cloud goes and in what file, then let the backend write it.

        The four Export buttons used to call `save_point_cloud(pcd, path)` with an open3d
        object that the pane never held, and `.obj` - which the button offered - is not a
        file `o3d.io.write_point_cloud` writes at all. One verb answers for all four now,
        and the verdict says whether this app can read the result back.
        """
        if not self.current_model_path:
            self._no_file_message()
            return
        suggested = self.pc_processor.output_path(self.current_model_path, 'export', extension)
        target, _ = QFileDialog.getSaveFileName(
            self, f"Export {extension.upper()}", suggested,
            f"{extension.upper().lstrip('.')} files (*{extension});;All files (*)")
        if not target:
            return
        if not os.path.splitext(target)[1]:
            target += extension
        self._run('export', {'file_path': self.current_model_path, 'output_path': target})

    def export_as_mesh(self):
        """Write the surface this cloud produced in the format chosen, and hand it on.

        The button was not connected at all, while its name promised a mesh to a user who
        had already asked for a reconstruction. It only has something to export once a
        surface verb has run, so that is what it says when nothing has - rather than
        writing a file from the cloud and calling it a mesh.
        """
        if not self.last_surface_path:
            QMessageBox.information(
                self, "No surface to export",
                "No surface has been built from "
                f"{os.path.basename(self.current_model_path or 'this cloud')} yet. Run "
                f"Poisson, Ball Pivoting, Alpha Shape or Convex Hull first - this exports "
                f"the file one of those wrote, in the format chosen on the Reconstruct tab.")
            return
        formats = self.pc_processor.surface_formats()
        chosen = self.surface_format_combo.currentText() or '.ply'
        suggested = self.pc_processor.surface_target(self.current_model_path
                                                    or self.last_surface_path, chosen)
        target, selected = QFileDialog.getSaveFileName(
            self, "Export surface as", suggested,
            "Surface files (%s);;All files (*)" % ' '.join('*' + f for f in formats))
        if not target:
            return
        if not os.path.splitext(target)[1]:
            # Whatever the dialog's filter was, the name the user typed decides the file.
            tail = (selected or '').rpartition('*')[2].strip()
            target += tail if tail.startswith('.') else chosen

        from ..processing.format_converter import FormatConverter
        converter = FormatConverter()
        mesh, opened_with = converter.read_mesh(self.last_surface_path)
        if mesh is None:
            QMessageBox.warning(self, "Cannot read the surface",
                                f"{os.path.basename(self.last_surface_path)} cannot be "
                                f"opened here any more: {opened_with}")
            return
        ok, message = converter.write_mesh(mesh, target)
        if not ok:
            QMessageBox.warning(self, "Export refused", message)
            return
        read_back, opened_with = converter.read_mesh(target)
        if read_back is None:
            QMessageBox.warning(self, "Export unreadable",
                                f"{os.path.basename(target)} was written but this app "
                                f"cannot open it again: {opened_with}")
            return
        self._record_measured(
            f"Surface exported: {len(read_back.vertices):,} vertices, "
            f"{len(read_back.faces):,} faces -> {os.path.basename(target)}")
        reply = QMessageBox.question(
            self, "Open in Mesh Tools",
            f"{os.path.basename(target)} holds {len(read_back.faces):,} faces. Open it in "
            f"Mesh Tools?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.mesh_generated.emit(target)

    def _record_measured(self, headline):
        """A line in the history for work the pane itself did, not a verb."""
        self.history_list.addItem(headline)
        self.history_list.scrollToBottom()
        self.operation_label.setText(headline)

    # ---- the verbs, one handler each --------------------------------------------

    def _cloud_needed(self, operation, params):
        if not self.current_model_path:
            self._no_file_message()
            return False
        return self._run(operation, {'file_path': self.current_model_path, **params})

    def center_point_cloud(self):
        self._cloud_needed('center', {})

    def normalize_point_cloud(self):
        self._cloud_needed('normalize', {})

    def remove_duplicates(self):
        self._cloud_needed('dedup', {})

    def estimate_normals(self):
        self._cloud_needed('normals', {'knn': self.normals_knn_spin.value()})

    def apply_translation(self):
        offset = [self.trans_x_spin.value(), self.trans_y_spin.value(),
                  self.trans_z_spin.value()]
        self._cloud_needed('translate', {'dx': offset[0], 'dy': offset[1], 'dz': offset[2]})

    def apply_rotation(self):
        self._cloud_needed('rotate', {'rx': self.rot_x_spin.value(),
                                      'ry': self.rot_y_spin.value(),
                                      'rz': self.rot_z_spin.value()})

    def apply_scale(self):
        self._cloud_needed('scale', {'factor': self.scale_spin.value()})

    def remove_statistical_outliers(self):
        self._cloud_needed('outliers_statistical',
                           {'nb_neighbors': self.outlier_neighbors_spin.value(),
                            'std_ratio': self.outlier_std_spin.value()})

    def remove_radius_outliers(self):
        self._cloud_needed('outliers_radius',
                           {'radius': self.radius_spin.value(),
                            'nb_points': self.min_points_spin.value()})

    def voxel_downsample(self):
        self._cloud_needed('voxel', {'voxel_size': self.voxel_size_spin.value()})

    def uniform_downsample(self):
        self._cloud_needed('uniform', {'every_k': self.uniform_k_spin.value()})

    def crop_box(self):
        if not self.current_model_path:
            self._no_file_message()
            return
        mins, maxs = self._measured_bounds()
        dialog = BoundingBoxDialog(self, mins, maxs)
        if not dialog.exec():
            return
        lower, upper = dialog.get_bounds()
        self._run('crop', {'file_path': self.current_model_path, 'min_bound': lower,
                           'max_bound': upper})

    def crop_interactive(self):
        """Pick the points to keep in an Open3D window, then write exactly those.

        `VisualizerWithEditing` does not crop anything itself and writes nothing itself -
        it only remembers the indices clicked - so the file behind this button comes from
        the backend reading those indices. The instructions used to promise that pressing
        'S' saved a crop, which that window does not do.
        """
        if not self.current_model_path:
            self._no_file_message()
            return
        QMessageBox.information(
            self, "Pick the points to keep",
            "An Open3D window opens beside this app.\n\n"
            "Left-click the points to keep.\n"
            "Press Q, or close the window, when you are done.\n\n"
            "The points you picked are written to a new file beside the current one. "
            "Closing the window without a click is refused, not saved as an empty cloud.")
        self._cloud_needed('pick', {})

    def load_target_model(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Target Point Cloud", "",
                                                   self._cloud_filter())
        if not file_path:
            return
        self.target_model_path = file_path
        size = os.path.getsize(file_path) / 1024.0
        self.target_info_label.setText(
            f"Target: {os.path.basename(file_path)} ({size:.1f} KB). Its points are counted "
            f"by the run that uses it.")

    def _registration_params(self, operation):
        if not self.current_model_path:
            self._no_file_message()
            return None
        if not self.target_model_path:
            QMessageBox.warning(self, "No target loaded",
                                "Alignment needs two clouds. Load a target on this tab "
                                f"first; the source is {os.path.basename(self.current_model_path)}.")
            return None
        params = {'source_path': self.current_model_path, 'target_path': self.target_model_path}
        if operation == 'register_icp':
            params['threshold'] = self.icp_threshold_spin.value()
            params['max_iteration'] = self.icp_max_iter_spin.value()
        elif operation == 'register_ransac':
            voxel = self.feature_voxel_spin.value()
            if voxel > 0:
                params['voxel_size'] = voxel
        # A feature pass leaves no file of its own, so it gets no name for one; the two
        # `register_*` verbs name their aligned cloud in the backend.
        return params

    def run_icp_registration(self):
        params = self._registration_params('register_icp')
        if params:
            self._run('register_icp', params)

    def extract_features(self):
        params = self._registration_params('features')
        if not params:
            return
        voxel = self.feature_voxel_spin.value()
        if voxel > 0:
            params['voxel_size'] = voxel
        self._run('features', params)

    def run_ransac_registration(self):
        params = self._registration_params('register_ransac')
        if params:
            self._run('register_ransac', params)

    def _surface_params(self, operation, params):
        """Hand a surface verb the cloud and the format, and let the verb name its own file.

        The name carries the verb - `scan_poisson.ply`, `scan_hull.ply` - because four
        reconstructions of one scan are four different answers, and one name for all four
        means the third quietly deletes the first. That rule belongs to the backend
        (`PointCloudProcessor.target_path`), so a task that reconstructs the same scan
        unattended writes the file the button writes rather than a second name for it.
        """
        if not self.current_model_path:
            self._no_file_message()
            return False
        self._run(operation, {'file_path': self.current_model_path,
                              'extension': self.surface_format_combo.currentText() or '.ply',
                              **params})
        return True

    def poisson_reconstruction(self):
        self._surface_params('poisson', {'depth': self.poisson_depth_spin.value(),
                                         'width': self.poisson_width_spin.value(),
                                         'scale': self.poisson_scale_spin.value(),
                                         'linear_fit': self.poisson_linear_fit_cb.isChecked(),
                                         'trim': self.poisson_trim_cb.isChecked()})

    def run_ball_pivoting(self):
        radius = self.ball_radius_spin.value()
        params = {'ball_radius': radius} if radius > 0 else {}
        self._surface_params('ball_pivoting', params)

    def run_alpha_shapes(self):
        self._surface_params('alpha_shape', {'alpha': self.alpha_value_spin.value()})

    def create_convex_hull(self):
        self._surface_params('hull', {})

    def compute_statistics(self):
        self._cloud_needed('analyze', {})

    def compute_distances(self):
        self._cloud_needed('distances', {})

    def show_distance_histogram(self):
        """Draw the bins the distance run measured, as text in this pane.

        This used to open a matplotlib window with `plt.show()`, which runs its own GUI
        event loop - the app waited inside the pane's click handler until the chart window
        was closed, and the chart was a second figure of the same numbers with no numbers
        printed on it. The bins are in the verdict already, so they are printed here.
        """
        if not self.last_distances:
            QMessageBox.information(self, "No distances measured",
                                    "Run 'Compute Nearest Distances' first - this draws the "
                                    "bins that measurement returned.")
            return
        measure = self.last_distances
        counts = measure['histogram']['counts']
        edges = measure['histogram']['edges']
        widest = max(counts) if counts else 0
        lines = [f"Nearest-neighbour distances, {measure['samples']:,} samples in "
                 f"{len(counts)} bins", ""]
        for index, count in enumerate(counts):
            bar = '#' * int(round(count * 40.0 / widest)) if widest else ''
            lines.append(f"{edges[index]:>10.6g} - {edges[index + 1]:<10.6g} |{bar} "
                         f"{count:,}")
        self.histogram_view.setPlainText('\n'.join(lines))
        self.operation_label.setText(f"Histogram of {measure['samples']:,} distances drawn")

    def run_clustering(self):
        self._cloud_needed('cluster', {'eps': self.cluster_eps_spin.value(),
                                       'min_points': self.cluster_min_points_spin.value()})

    def detect_planes(self):
        if not self.current_model_path:
            self._no_file_message()
            return
        self._run('planes', {
            'file_path': self.current_model_path,
            'distance_threshold': self.plane_threshold_spin.value(),
            'ransac_n': self.plane_ransac_n_spin.value(),
            'num_iterations': self.plane_iterations_spin.value(),
        })

    def clear_history(self):
        self.history_list.clear()
        self.operation_label.setText("History cleared")

    # ---- the per-family reports --------------------------------------------------

    def _report_family(self, operation, verdict):
        """Send a verdict's detail to the text area that already belongs to its family."""
        if operation == 'analyze':
            self._fill_info(verdict)
            self.detailed_stats.setPlainText('\n'.join(self._detail(verdict)))
        elif operation == 'distances':
            self.last_distances = verdict.get('measure')
            self.stats_display.setPlainText('\n'.join(self._detail(verdict)))
        elif operation in ('register_icp', 'register_ransac', 'features'):
            self.registration_results.setPlainText('\n'.join(self._detail(verdict)))
        elif operation == 'planes':
            # Plane fitting is a measurement, and the Analyze tab is where its button is, so
            # its two files are reported in that tab's own text area - not in the
            # Registration box on a different tab, which is where this pane used to hide it.
            self.stats_display.setPlainText('\n'.join(self._detail(verdict)))
        elif operation in SURFACE_OPERATIONS:
            self.info_surface.setText(
                f"{os.path.basename(verdict.get('output_path') or '')} - "
                f"{self._count((verdict.get('measure') or {}).get('vertices'))} vertices, "
                f"{self._count((verdict.get('measure') or {}).get('faces'))} faces")

    # ---- the viewer --------------------------------------------------------------

    def _point_size_from_slider(self, value):
        if self.point_size_box.value() != float(value):
            self.point_size_box.setValue(float(value))
        self.viewer.set_point_size(float(value))

    def _point_size_from_box(self, value):
        in_range = float(self.point_size_slider.minimum()) <= value <= \
            float(self.point_size_slider.maximum())
        if in_range and self.point_size_slider.value() != int(round(value)):
            self.point_size_slider.setValue(int(round(value)))
        elif not in_range:
            # Out of the slider's reach, so say so on the slider instead of pretending it
            # still shows the number the box holds.
            self.point_size_slider.blockSignals(True)
            self.point_size_slider.setValue(self.point_size_slider.minimum() if value <
                                            self.point_size_slider.minimum() else
                                            self.point_size_slider.maximum())
            self.point_size_slider.blockSignals(False)
        self.viewer.set_point_size(float(value))

    def reset_display(self):
        """Put this pane's own display controls back to their defaults and redraw.

        The viewer is a static image, so there is no camera here to point anywhere: the
        two view buttons differ by what they change. This one moves the three controls
        back and redraws; 'Fit to View' leaves them alone and only redraws.
        """
        self.point_size_box.blockSignals(True)
        self.point_size_slider.blockSignals(True)
        self.point_size_box.setValue(3.0)
        self.point_size_slider.setValue(3)
        self.point_size_box.blockSignals(False)
        self.point_size_slider.blockSignals(False)
        self.show_normals_cb.blockSignals(True)
        self.show_wireframe_cb.blockSignals(True)
        self.show_normals_cb.setChecked(False)
        self.show_wireframe_cb.setChecked(False)
        self.show_normals_cb.blockSignals(False)
        self.show_wireframe_cb.blockSignals(False)
        self.viewer.set_point_size(3.0)
        self.viewer.set_show_normals(False)
        self.viewer.set_show_wireframe(False)
        self.operation_label.setText("Display back to the defaults it loaded with")

    def fit_to_view(self):
        if not self.viewer.fit_to_view():
            QMessageBox.information(self, "Nothing to frame",
                                    "There is no geometry in the viewer right now.")
            return
        # Present tense on purpose: the render runs on its own thread and the picture
        # replaces itself when it lands. Claiming it was already re-rendered is a claim
        # this pane has no way to make at the moment the click returns.
        self.operation_label.setText("Preview re-rendering at the panel's current size")

    def capture_screen(self):
        """Save the preview that is on screen, or say there is not one.

        The image is Open3D's render of the geometry, so a screenshot before the first
        render finishes has nothing in it - the old code read the label's pixmap directly
        and reported a successful save of a picture that never existed.
        """
        pixmap = self.viewer.preview_pixmap()
        if pixmap is None:
            QMessageBox.warning(self, "No image yet",
                                "The viewer has no rendered preview to save. Press 'Fit to "
                                "View' to render one.")
            return
        base = os.path.splitext(os.path.basename(self.current_model_path or 'preview'))[0]
        target, _ = QFileDialog.getSaveFileName(self, "Save Screenshot", f"{base}.png",
                                                "Images (*.png *.jpg)")
        if not target:
            return
        if not os.path.splitext(target)[1]:
            target += '.png'
        if not pixmap.save(target):
            QMessageBox.warning(self, "Screenshot not written",
                                f"{target} could not be written - this build cannot encode "
                                f"that extension.")
            return
        self._record_measured(f"Screenshot saved to {os.path.basename(target)}")
