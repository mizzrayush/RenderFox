"""Cross-workspace invariants that stop RenderFox regressing into separate apps."""

import ast
import os
import sys
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from src.core.asset_selection import AssetSelection
from src.ui.main_window import MainWindow


class EcosystemContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_store_rejects_missing_assets_and_only_announces_changes(self):
        store = AssetSelection()
        changes = []
        store.changed.connect(changes.append)
        self.assertFalse(store.select('no_such_asset.obj'))
        self.assertEqual([], changes)

    def test_workspace_rail_is_icon_only_and_accessible_by_tooltip(self):
        window = MainWindow()
        try:
            for index in range(window.tab_widget.count()):
                self.assertEqual('', window.tab_widget.tabText(index))
                tooltip = window.tab_widget.tabToolTip(index)
                self.assertIn('\n', tooltip)
                self.assertTrue(tooltip.split('\n', 1)[0])
        finally:
            window.close()
            window.deleteLater()

    def test_main_window_routes_workspace_changes_through_the_shared_store(self):
        path = os.path.join(ROOT, 'tests', 'test_data', 'test_sphere.obj')
        with open(os.path.join(ROOT, 'src', 'ui', 'main_window.py'), encoding='utf-8') as source_file:
            source = source_file.read()
        tree = ast.parse(source)
        methods = {node.name: ast.get_source_segment(source, node) or ''
                   for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow'
                   for node in node.body if isinstance(node, ast.FunctionDef)}
        for name in ('open_in_model_viewer', 'open_in_mesh_tools', 'open_in_rendering',
                     'open_in_animation', 'open_in_preprocessing', 'open_in_postprocessing'):
            self.assertIn('asset_selection.select(file_path)', methods[name])
        self.assertTrue(os.path.isfile(path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
