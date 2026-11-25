"""Load packaged artwork reliably in source and PyInstaller builds."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSET_DIR = Path(__file__).resolve().parent / "assets"


def load_asset_pixmap(name: str) -> QPixmap:
    """Load raster artwork or render SVG artwork into a QPixmap.

    Explicit SVG rendering avoids depending on Qt image-format plugin lookup,
    which can differ between a development install and a frozen Windows app.
    """
    path = (ASSET_DIR / name).resolve()
    if path.parent != ASSET_DIR.resolve() or not path.is_file():
        return QPixmap()

    if path.suffix.lower() == ".svg":
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return QPixmap()
        size = renderer.defaultSize()
        if not size.isValid() or size.isEmpty():
            return QPixmap()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap

    return QPixmap(str(path))
