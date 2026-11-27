"""Responsive branded application banner widget."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


class ResponsiveBanner(QLabel):
    """Wide photographic banner with layout-safe custom painting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self._rendered_pixmap = QPixmap()
        self._refreshing = False
        self._last_render_size = None

        self.setObjectName("brandBanner")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(132)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_source_pixmap(self, pixmap):
        self._source_pixmap = pixmap
        self._last_render_size = None
        self._refresh_banner()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_banner()

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self._rendered_pixmap.isNull():
            painter.drawPixmap(0, 0, self._rendered_pixmap)
        else:
            painter.fillRect(self.rect(), self.palette().window())
        painter.end()

    def _refresh_banner(self):
        if (
            self._refreshing
            or self._source_pixmap.isNull()
            or self.width() < 2
            or self.height() < 2
        ):
            return

        target_size = self.size()
        if target_size == self._last_render_size:
            return

        self._refreshing = True
        try:
            scaled = self._source_pixmap.scaled(
                target_size,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )

            x = max(0, (scaled.width() - self.width()) // 2)
            y = max(0, (scaled.height() - self.height()) // 2)
            rendered = scaled.copy(x, y, self.width(), self.height())

            painter = QPainter(rendered)
            painter.setRenderHint(QPainter.Antialiasing)

            title_font = QFont(
                "Gill Sans MT", max(20, int(self.height() * 0.34))
            )
            title_font.setBold(True)
            title_font.setItalic(True)
            painter.setFont(title_font)
            painter.setPen(QColor("#f4f7f3"))
            painter.drawText(34, int(self.height() * 0.55), "FreeRov3r")

            tagline_font = QFont(
                "Gill Sans MT", max(8, int(self.height() * 0.095))
            )
            tagline_font.setBold(True)
            painter.setFont(tagline_font)
            painter.setPen(QColor("#d5e2d8"))
            painter.drawText(
                38,
                int(self.height() * 0.76),
                "DIAGNOSTICS  •  MONITORING  •  SOLUTIONS"
            )

            painter.end()

            self._rendered_pixmap = rendered
            self._last_render_size = target_size
            self.update()

        finally:
            self._refreshing = False
