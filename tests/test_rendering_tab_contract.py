"""
Rendering tab contract test.

The Rendering Studio's toolbar and its two render buttons are clicked, and each one
has to change the viewport or leave a file behind. Before this pass, "Render Image"
and "Render Frame" had no `clicked.connect` at all, the four view modes, Reset View,
Snapshot and both toggles were decorations, and the Settings panel was built inside
`addTab(...)` and thrown away - so nothing in the application could even reach them.

Run: python -X utf8 tests/test_rendering_tab_contract.py
"""

import os
import shutil
import sys
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

import cv2
from PyQt6.QtWidgets import QApplication, QFileDialog, QPushButton, QToolBar

from src.processing import postprocessor
from src.ui.rendering_tab import RenderingTab

MODE_EXPECTATIONS = {
    # label -> (render_mode, textures, vertex colors)
    'Wireframe': ('wireframe', False, True),
    'Solid': ('fill', False, False),
    'Material': ('fill', True, True),
    'Rendered': ('fill', True, True),
}


class RenderingTabCase(unittest.TestCase):
    """A real tab, a real output folder, and the file dialogs pointed at it."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.previous_dialogs = (QFileDialog.getExistingDirectory,
                              QFileDialog.getSaveFileName)

    @classmethod
    def tearDownClass(cls):
        QFileDialog.getExistingDirectory = cls.previous_dialogs[0]
        QFileDialog.getSaveFileName = cls.previous_dialogs[1]

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_rendering_')
        self.model = os.path.join(self.work, 'hero.obj')
        self.previous = (self.model, os.getcwd())
        self.tab = RenderingTab()
        self.messages = []
        self.tab.status_message.connect(self.messages.append)
        self.tab.set_model(self.model)
        QFileDialog.getExistingDirectory = lambda *args, **kwargs: self.out
        QFileDialog.getSaveFileName = lambda *args, **kwargs: (
            os.path.join(self.out, 'snapshot.png'), 'PNG image (*.png)')

    def tearDown(self):
        os.chdir(self.previous[1])
        shutil.rmtree(self.work, ignore_errors=True)
        self.tab.deleteLater()

    @property
    def out(self):
        directory = os.path.join(self.work, 'out')
        os.makedirs(directory, exist_ok=True)
        return directory

    def toolbar(self):
        return self.tab.findChild(QToolBar)

    def action(self, label):
        for action in self.toolbar().actions():
            if action.text() == label:
                return action
        self.fail(f'the rendering toolbar has no {label!r} action')

    def button(self, label):
        for widget in self.toolbar().findChildren(QPushButton):
            if widget.text() == label:
                return widget
        self.fail(f'the rendering toolbar has no {label!r} button')

    def statuses(self):
        return ' | '.join(self.messages)


class TestToolbarWiring(RenderingTabCase):
    """A control that is not connected to anything is not a control."""

    def test_01_every_action_and_button_is_connected(self):
        labels = list(MODE_EXPECTATIONS) + ['Reset View', 'Snapshot', 'Toggle Grid',
                                           'Toggle Overlays', 'Export Scene']
        for label in labels:
            with self.subTest(action=label):
                action = self.action(label)
                self.assertGreater(action.receivers(action.triggered), 0,
                                   f'{label} is drawn but connected to nothing')
        for button, name in ((self.tab.settings_panel.render_btn, 'Render Image'),
                             (self.button('Render Frame'), 'Render Frame')):
            with self.subTest(button=name):
                self.assertGreater(button.receivers(button.clicked), 0,
                                   f'{name} is drawn but connected to nothing')

    def test_02_a_button_cannot_claim_a_selection_there_is_no_way_to_make(self):
        """Nothing in this tab selects a part of the model, so "Focus Selected" was a lie.

        The viewport frames every model to a 2-unit box as it loads, and Reset View
        returns the camera to that framing, so the action had no distinct behaviour
        to be given either.
        """
        self.assertNotIn('Focus Selected',
                         [action.text() for action in self.toolbar().actions()])

    def test_03_the_settings_panel_the_tab_can_reach_is_the_one_on_screen(self):
        self.assertIs(self.tab.tool_panel.widget(3).widget(), self.tab.settings_panel)
        self.assertEqual('Settings', self.tab.tool_panel.tabText(3))


class TestViewportModes(RenderingTabCase):
    """Each mode is a switch the viewport really has."""

    def test_04_the_four_modes_leave_the_viewport_in_the_documented_state(self):
        for label, (mode, textures, colors) in MODE_EXPECTATIONS.items():
            with self.subTest(mode=label):
                self.action(label).trigger()
                viewer = self.tab.viewport
                self.assertEqual(mode, viewer.render_mode)
                self.assertEqual(textures, viewer.use_textures)
                self.assertEqual(colors, viewer.use_vertex_colors)
                self.assertIn(label, self.statuses())
                if label == 'Rendered':
                    self.assertFalse(viewer.show_grid)
                    self.assertFalse(viewer.show_overlays)

    def test_05_the_toggles_flip_the_thing_their_label_names(self):
        viewer = self.tab.viewport
        for label, attribute in (('Toggle Grid', 'show_grid'),
                                 ('Toggle Overlays', 'show_overlays')):
            with self.subTest(control=label):
                start = getattr(viewer, attribute)
                self.action(label).trigger()
                self.assertEqual(not start, getattr(viewer, attribute))
                self.action(label).trigger()
                self.assertEqual(start, getattr(viewer, attribute))

    def test_06_reset_view_puts_the_camera_back(self):
        viewer = self.tab.viewport
        self.action('Toggle Grid').trigger()
        self.action('Rendered').trigger()
        viewer.camera_distance = 0.4
        viewer.model_rotation_z = 55.0
        self.action('Reset View').trigger()
        self.assertEqual(5.0, viewer.camera_distance)
        self.assertEqual(0.0, viewer.model_rotation_z)
        self.assertIn('View reset', self.statuses())

    def test_07_snapshot_writes_the_file_the_dialog_named(self):
        self.action('Snapshot').trigger()
        path = os.path.join(self.out, 'snapshot.png')
        self.assertTrue(os.path.isfile(path), self.statuses())
        self.assertGreater(os.path.getsize(path), 0)


class TestRenderFrame(RenderingTabCase):
    """The two render buttons have to produce the frame they claim."""

    def frames(self):
        return sorted(os.listdir(self.out))

    def test_08_a_rendered_frame_is_the_resolution_and_format_it_asks_for(self):
        for label, size, extension in (('1920x1080 (HD)', (1920, 1080), 'png'),
                                        ('1280x720 (HD)', (1280, 720), 'png'),
                                        ('3840x2160 (4K)', (3840, 2160), 'png')):
            with self.subTest(resolution=label):
                shutil.rmtree(self.out, ignore_errors=True)
                self.tab.settings_panel.res_combo.setCurrentText(label)
                self.tab.render_frame()
                written = self.frames()
                self.assertEqual(['hero_0001.png'], written, self.statuses())
                image = cv2.imread(os.path.join(self.out, written[0]))
                self.assertEqual((size[1], size[0], 3), image.shape,
                                 f'{label} wrote a different picture than it said')

    def test_09_the_format_reaches_the_file(self):
        self.tab.settings_panel.format_combo.setCurrentText('JPG Sequence')
        self.tab.render_frame()
        self.assertEqual(['hero_0001.jpg'], self.frames(), self.statuses())
        self.assertIsNotNone(cv2.imread(os.path.join(self.out, 'hero_0001.jpg')))

    def test_10_custom_uses_the_viewports_own_size(self):
        self.tab.settings_panel.res_combo.setCurrentText('Custom')
        expected = (self.tab.viewport.width(), self.tab.viewport.height())
        self.tab.render_frame()
        image = cv2.imread(os.path.join(self.out, self.frames()[0]))
        self.assertEqual((expected[1], expected[0], 3), image.shape)

    def test_11_the_settings_button_and_the_toolbar_button_do_the_same_job(self):
        self.tab.settings_panel.render_btn.click()
        self.assertEqual(['hero_0001.png'], self.frames(), self.statuses())

    def test_12_denoising_keeps_the_frame_when_it_cannot_do_its_job(self):
        """A refused denoise must not cost the user the render they already have."""
        original = postprocessor.ImageDenoiser.denoise_image
        postprocessor.ImageDenoiser.denoise_image = lambda self, *a, **k: False
        try:
            self.tab.render_frame()
        finally:
            postprocessor.ImageDenoiser.denoise_image = original
        self.assertEqual(['hero_0001.png'], self.frames())
        self.assertIn('as rendered', self.statuses())
        self.assertIsNotNone(cv2.imread(os.path.join(self.out, 'hero_0001.png')))

    def test_13_denoising_on_writes_one_file_not_a_work_copy(self):
        self.tab.render_frame()
        self.assertEqual(['hero_0001.png'], self.frames(),
                         'a temporary file was left beside the frame')
        self.assertIn('denoised', self.statuses())

    def test_14_declining_the_folder_is_not_a_render(self):
        QFileDialog.getExistingDirectory = lambda *args, **kwargs: ''
        self.tab.render_frame()
        self.assertEqual([], self.frames())
        self.assertIn('no output folder', self.statuses())

    def test_15_a_frame_is_named_after_the_model_it_came_from(self):
        self.tab.set_model(os.path.join(self.work, 'Shot 020.obj'))
        self.tab.render_frame()
        self.assertEqual(['Shot 020_0001.png'], self.frames(), self.statuses())


if __name__ == '__main__':
    unittest.main(verbosity=2)
