"""Startup welcome dialog."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .assets import load_asset_pixmap


def show_startup_splash(window):
if not window.settings.get("show_startup_splash", True):
    return
dialog = QDialog(window)
dialog.setObjectName("startupSplash")
dialog.setWindowTitle("Welcome to FreeRov3r")
dialog.setWindowModality(Qt.ApplicationModal)
screen = QApplication.primaryScreen()
available = screen.availableGeometry() if screen else window.geometry()
dialog_width = min(1100, max(640, available.width() - 40))
dialog_height = min(660, max(480, available.height() - 40))
dialog.setMinimumSize(min(640, dialog_width), min(480, dialog_height))
dialog.resize(dialog_width, dialog_height)
layout = QVBoxLayout(dialog)
layout.setContentsMargins(24, 20, 24, 18)
layout.setSpacing(12)
content_scroll = QScrollArea(dialog)
content_scroll.setWidgetResizable(True)
content_scroll.setFrameShape(QFrame.NoFrame)
content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
content_widget = QWidget()
content_layout = QVBoxLayout(content_widget)
content_layout.setContentsMargins(0, 0, 0, 0)
content_layout.setSpacing(12)
splash_banner = QLabel()
splash_banner.setAlignment(Qt.AlignCenter)
banner_height = min(210, max(110, int(dialog_height * 0.30)))
splash_banner.setFixedHeight(banner_height)
splash_banner.setSizePolicy(
    QSizePolicy.Expanding, QSizePolicy.Fixed
)

splash_source = load_asset_pixmap("brand_banner.svg")
if not splash_source.isNull():
    banner_width = max(1, dialog_width - 64)
    scaled_banner = splash_source.scaled(
        banner_width, banner_height,
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation
    )
    crop_x = max(0, (scaled_banner.width() - banner_width) // 2)
    crop_y = max(0, (scaled_banner.height() - banner_height) // 2)
    splash_banner.setPixmap(
        scaled_banner.copy(crop_x, crop_y, banner_width, banner_height)
    )

content_layout.addWidget(splash_banner)

title = QLabel("What would you like to do?")
title.setObjectName("splashTitle")
splash_title_font = QFont(window.heading_font_family, 25, QFont.Bold)
splash_title_font.setItalic(True)
title.setFont(splash_title_font)
content_layout.addWidget(title)
subtitle = QLabel(
    "Start with a simple task. You can switch workspaces at any time "
    "using Quick Nav on the right."
)
subtitle.setObjectName("splashSubtitle")
subtitle.setWordWrap(True)
content_layout.addWidget(subtitle)
grid = QGridLayout()
grid.setSpacing(12)
choices = [
    ("Connect to a vehicle", "Choose your adapter and passively monitor vehicle traffic.",
     "Open capture", lambda: window._navigate_to_tab("Capture")),
    ("Try the simulator", "Start a clearly labeled demo using synthetic vehicle data. No hardware required.",
     "Start demo", window._start_simulator_demo),
    ("Explore sample modules", "Browse example module categories and sample faults. These are test fixtures, not a real scan.",
     "View sample modules", lambda: window._navigate_to_tab("Modules")),
    ("Open the full workspace", "Go straight to the complete set of generic diagnostic, graphing and history tools.",
     "Open workspace", lambda: window._navigate_to_tab("Capture")),
     ("Vehicle setup wizard", "Detect an interface, read or enter a VIN, identify the vehicle and select its capability package.",
      "Start setup", window.run_setup_wizard),
]
splash_columns = 2 if dialog_width < 900 else 3
for index, (heading, description, action_text, action) in enumerate(choices):
    card = QFrame()
    card.setObjectName("splashCard")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(16, 14, 16, 14)
    card_layout.setSpacing(8)
    heading_label = QLabel(heading)
    heading_label.setObjectName("splashCardTitle")
    card_layout.addWidget(heading_label)
    detail = QLabel(description)
    detail.setObjectName("splashCardText")
    detail.setWordWrap(True)
    card_layout.addWidget(detail, 1)
    action_button = QPushButton(action_text)
    action_button.setObjectName("splashAction")
    action_button.setMinimumHeight(38)
    action_button.clicked.connect(
        lambda checked=False, callback=action: (dialog.accept(), callback())
    )
    card_layout.addWidget(action_button)
    grid.addWidget(card, index // splash_columns, index % splash_columns)
content_layout.addLayout(grid)
content_scroll.setWidget(content_widget)
layout.addWidget(content_scroll, 1)
footer = QHBoxLayout()
window.splash_skip_checkbox = QCheckBox("Don't show this welcome screen at startup")
window.splash_skip_checkbox.toggled.connect(window._set_startup_splash_preference)
footer.addWidget(window.splash_skip_checkbox)
footer.addStretch(1)
close_button = QPushButton("Continue to workspace")
close_button.setObjectName("splashContinue")
close_button.clicked.connect(dialog.accept)
footer.addWidget(close_button)
layout.addLayout(footer)
dialog.exec()
