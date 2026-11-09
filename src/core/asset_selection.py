"""The one selected asset shared by RenderFox workspaces."""

import os
from PyQt6.QtCore import QObject, pyqtSignal


class AssetSelection(QObject):
    """Stores a real file path once and announces meaningful changes."""

    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ''

    @property
    def path(self):
        return self._path

    def select(self, path: str) -> bool:
        normalized = os.path.abspath(path) if path else ''
        if not normalized or not os.path.isfile(normalized):
            return False
        if normalized == self._path:
            return True
        self._path = normalized
        self.changed.emit(normalized)
        return True
