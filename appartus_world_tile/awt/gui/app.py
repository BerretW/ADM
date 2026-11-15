"""GUI entry point."""

from __future__ import annotations

import sys


def _dark_palette():
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: (36, 40, 46),
        QPalette.ColorRole.WindowText: (222, 226, 232),
        QPalette.ColorRole.Base: (26, 29, 34),
        QPalette.ColorRole.AlternateBase: (40, 44, 51),
        QPalette.ColorRole.ToolTipBase: (48, 53, 61),
        QPalette.ColorRole.ToolTipText: (230, 233, 238),
        QPalette.ColorRole.Text: (222, 226, 232),
        QPalette.ColorRole.Button: (48, 53, 61),
        QPalette.ColorRole.ButtonText: (222, 226, 232),
        QPalette.ColorRole.Highlight: (214, 160, 52),
        QPalette.ColorRole.HighlightedText: (20, 22, 26),
        QPalette.ColorRole.Link: (120, 190, 240),
        QPalette.ColorRole.PlaceholderText: (128, 135, 145),
    }
    for role, rgb in roles.items():
        palette.setColor(role, QColor(*rgb))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(110, 116, 125))
    return palette


def run(path: str | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Apparatus World Tile")
    app.setOrganizationName("Apparatus")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    window = MainWindow()
    window.show()
    if path:
        window.open_path(path)
    return app.exec()
