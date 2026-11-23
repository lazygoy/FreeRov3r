"""Native Qt drawer and toast primitives for the FreeRov3r workspace."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import QButtonGroup, QDockWidget, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class QuickDrawer(QDockWidget):
    """Non-modal right-side panel for vehicle context and workspace navigation."""
    def __init__(self, parent, navigate):
        super().__init__("QUICK NAV", parent)
        self.setObjectName("quickDrawer")
        self.setAllowedAreas(Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.setMinimumWidth(210)
        self.setMaximumWidth(340)
        scroll = QScrollArea(self)
        scroll.setObjectName("quickDrawerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body = QWidget()
        body.setMinimumWidth(0)
        body.setObjectName("drawerBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)
        brand_logo = QLabel()
        brand_logo.setObjectName("drawerBrandLogo")
        logo_path = Path(__file__).resolve().parent / "assets" / "brand_badge.svg"
        logo_pixmap = QPixmap(str(logo_path))
        if not logo_pixmap.isNull():
            brand_logo.setPixmap(logo_pixmap.scaled(66, 66, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand_row.addWidget(brand_logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        brand_name = QLabel("FreeRov3r")
        brand_name.setObjectName("drawerBrandName")
        brand_text.addWidget(brand_name)
        brand_tagline = QLabel("DIAGNOSTICS  •  MONITORING")
        brand_tagline.setObjectName("drawerBrandTagline")
        brand_text.addWidget(brand_tagline)
        brand_row.addLayout(brand_text, 1)
        layout.addLayout(brand_row)
        title = QLabel("QUICK NAV")
        title.setObjectName("drawerTitle")
        layout.addWidget(title)
        subtitle = QLabel("Vehicle context and workspace shortcuts")
        subtitle.setObjectName("drawerSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        card = QFrame()
        card.setObjectName("drawerCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(7)
        caption = QLabel("SELECTED VEHICLE")
        caption.setObjectName("drawerCaption")
        card_layout.addWidget(caption)
        self.vehicle_value = QLabel("NO VEHICLE SELECTED")
        self.vehicle_value.setObjectName("drawerValue")
        self.vehicle_value.setWordWrap(True)
        card_layout.addWidget(self.vehicle_value)
        self.connection_value = QLabel("OFFLINE")
        self.connection_value.setObjectName("drawerStatus")
        card_layout.addWidget(self.connection_value)
        self.traffic_value = QLabel("0 frames · 0.0 fps")
        self.traffic_value.setObjectName("drawerCaption")
        card_layout.addWidget(self.traffic_value)
        layout.addWidget(card)
        section = QLabel("WORKSPACES")
        section.setObjectName("drawerSection")
        layout.addWidget(section)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        entries = [
            ("⌂   Home", "Home"), ("⌁   CAN Capture", "Capture"), ("◉   Sensor Monitor", "Sensors"),
            ("▥   Sensor Graph", "Graph"), ("◫   OBD-II", "OBD-II"),
            ("▦   Module Diagnostics", "Modules"), ("✦   Special Functions", "Special Functions"),
            ("⌘   Network Overview", "Network"),
            ("✦   Diagnostic Solutions", "Solutions"), ("◷   Vehicle History", "Vehicle History"),
            ("⚙   Settings", "Settings"),
        ]
        for label, target in entries:
            button = QPushButton(label)
            button.setObjectName("drawerNavButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, name=target: navigate(name))
            self.nav_group.addButton(button)
            self.nav_buttons[target] = button
            layout.addWidget(button)
        note = QLabel(
            "Passive monitoring only. ECU transmission, coding and programming remain "
            "disabled until vehicle-specific protocols are verified."
        )
        note.setObjectName("drawerNote")
        note.setWordWrap(True)
        layout.addStretch(1)
        support_button = QPushButton("☕  Buy Me a Coffee")
        support_button.setObjectName("drawerSupportButton")
        support_button.setCursor(Qt.PointingHandCursor)
        support_button.setToolTip("Support FreeRov3r development")
        support_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://www.buymeacoffee.com/lazygoy"))
        )
        layout.addWidget(support_button)
        layout.addWidget(note)
        scroll.setWidget(body)
        self.setWidget(scroll)

    def set_current_workspace(self, name):
        button = self.nav_buttons.get(name)
        if button is not None:
            button.setChecked(True)

    def update_context(self, vehicle, connection, traffic):
        self.vehicle_value.setText(vehicle or "NO VEHICLE SELECTED")
        self.connection_value.setText(connection or "OFFLINE")
        self.traffic_value.setText(traffic or "0 frames · 0.0 fps")


class ToastManager:
    """Compact non-modal notifications that do not interrupt diagnostic work."""
    def __init__(self, parent):
        self.parent = parent
        self.current = None

    def show(self, message, kind="info", duration=3200):
        if self.current is not None:
            self.current.deleteLater()
        toast = QFrame(self.parent)
        toast.setObjectName("toastNotification")
        toast.setProperty("kind", kind)
        toast.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        toast.setMaximumWidth(420)
        layout = QHBoxLayout(toast)
        layout.setContentsMargins(16, 12, 18, 12)
        layout.setSpacing(10)
        marker = QLabel({"success": "✓", "warning": "!", "error": "×"}.get(kind, "i"))
        marker.setObjectName("toastMarker")
        layout.addWidget(marker)
        label = QLabel(str(message))
        label.setObjectName("toastText")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        toast.adjustSize()
        toast.move(max(16, self.parent.width() - toast.width() - 26), 84)
        toast.show()
        toast.raise_()
        self.current = toast
        QTimer.singleShot(duration, toast.deleteLater)
        QTimer.singleShot(duration + 100, lambda: self._clear_if_current(toast))

    def _clear_if_current(self, toast):
        if self.current is toast:
            self.current = None
