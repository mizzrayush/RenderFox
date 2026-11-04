from PyQt6.QtWidgets import QApplication

import src.ui.library_tab

# Dummy function
def dummy(*args, **kwargs):
    pass

# Patch missing slot
src.ui.library_tab.LibraryTab.on_asset_selected = dummy

# Patch entire connection setup (causing grid_view error)
src.ui.library_tab.LibraryTab.setup_connections = dummy
src.ui.library_tab.LibraryTab.grid_view = dummy


# Now load the UI safely
from src.ui.main_window import MainWindow

app = QApplication([])
w = MainWindow()
w.show()
app.exec()
