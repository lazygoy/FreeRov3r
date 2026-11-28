"""Experimental workshop-console navigation shell.

This module intentionally changes only the application shell. Existing diagnostic
workspaces remain the same QTabWidget pages, preserving their callbacks and state.
The experimental branch can therefore be compared with main without duplicating
or rewriting diagnostic logic.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


_NAV_GROUPS = (
    ("VEHICLE", ("Sensors", "Modules", "Topology")),
    ("DIAGNOSTICS", ("OBD-II", "Special Functions")),
    ("DATA", ("Graph", "Solutions", "Vehicle History")),
    ("DEVELOPMENT", ("Capture", "D-PDU", "Research", "Tuning", "Wiring Diagrams")),
    ("CONFIGURATION", ("Settings",)),
)

_NAV_GLYPHS = {
    "Capture": "◉",
    "Sensors": "⌁",
    "OBD-II": "▤",
    "Graph": "⌗",
    "Modules": "▦",
    "Special Functions": "⚙",
    "Topology": "⌘",
    "Wiring Diagrams": "⌖",
    "Solutions": "✧",
    "Vehicle History": "◷",
    "Research": "⌕",
    "D-PDU": "⇄",
    "Tuning": "↗",
    "Settings": "⚙",
}


class NavigationWorkspace(QScrollArea):
    """High-contrast, left-rail experimental shell for existing workspaces."""

    def __init__(
        self,
        tabs,
        heading_font_family,
        body_font_family,
        toggle_quick_drawer,
        on_tab_changed,
        on_workspace_mode_changed=None,
        on_home=None,
        parent=None,
    ):
        super().__init__(parent)
        self.tabs = tabs
        self._nav_buttons = {}
        self._nav_sections = []
        tabs.tabBar().hide()

        root = QWidget()
        root.setObjectName("experimentalWorkspace")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        # Persistent navigation rail.
        rail = QFrame()
        rail.setObjectName("experimentalRail")
        rail.setFixedWidth(218)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(12, 14, 12, 12)
        rail_layout.setSpacing(7)

        brand = QLabel("FREEROV3R")
        brand.setObjectName("experimentalBrand")
        brand.setFont(QFont(heading_font_family, 17, QFont.Black))
        rail_layout.addWidget(brand)

        brand_subtitle = QLabel("VEHICLE SYSTEMS CONSOLE")
        brand_subtitle.setObjectName("experimentalBrandSubtitle")
        brand_subtitle.setFont(QFont(body_font_family, 7, QFont.Bold))
        rail_layout.addWidget(brand_subtitle)

        rail_divider = QFrame()
        rail_divider.setObjectName("experimentalDivider")
        rail_divider.setFrameShape(QFrame.HLine)
        rail_layout.addWidget(rail_divider)

        self.workspace_mode_selector = QComboBox()
        self.workspace_mode_selector.setObjectName("experimentalModeSelector")
        self.workspace_mode_selector.addItem("DIAGNOSTICS", "diagnostics")
        self.workspace_mode_selector.addItem("DEVELOPMENT & RESEARCH", "research")
        self.workspace_mode_selector.setToolTip(
            "Switch between commercial-style vehicle diagnostics and the engineering workbench"
        )
        if on_workspace_mode_changed is not None:
            self.workspace_mode_selector.currentIndexChanged.connect(
                self._handle_mode_change
            )
            self._on_workspace_mode_changed = on_workspace_mode_changed
        else:
            self._on_workspace_mode_changed = None
        rail_layout.addWidget(self.workspace_mode_selector)

        for group_name, tab_names in _NAV_GROUPS:
            section = QLabel(group_name)
            section.setObjectName("experimentalSectionLabel")
            section.setFont(QFont(body_font_family, 8, QFont.Bold))
            rail_layout.addWidget(section)
            section_buttons = []
            self._nav_sections.append((section, section_buttons))
            for tab_name in tab_names:
                index = next(
                    (i for i in range(tabs.count()) if tabs.tabText(i) == tab_name),
                    None,
                )
                if index is None:
                    continue
                button = QToolButton()
                button.setObjectName("experimentalNavButton")
                button.setText(f"{_NAV_GLYPHS.get(tab_name, '•')}   {tab_name}")
                button.setToolButtonStyle(Qt.ToolButtonTextOnly)
                button.setCheckable(True)
                button.setAutoRaise(False)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                button.setMinimumHeight(36)
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(
                    lambda checked=False, tab_index=index: tabs.setCurrentIndex(tab_index)
                )
                rail_layout.addWidget(button)
                self._nav_buttons[index] = button
                section_buttons.append(index)

        rail_layout.addStretch(1)

        rail_footer = QLabel("L319 PLATFORM  •  EXPERIMENTAL UI")
        rail_footer.setObjectName("experimentalRailFooter")
        rail_footer.setWordWrap(True)
        rail_layout.addWidget(rail_footer)
        root_layout.addWidget(rail)

        # Main work surface.
        main = QWidget()
        main.setObjectName("experimentalMain")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("experimentalHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 13, 18, 13)
        header_layout.setSpacing(12)

        title_column = QVBoxLayout()
        title_column.setSpacing(3)
        self.workspace_title = QLabel("Capture")
        self.workspace_title.setObjectName("experimentalWorkspaceTitle")
        self.workspace_title.setFont(QFont(heading_font_family, 19, QFont.Bold))
        self.workspace_subtitle = QLabel(
            "Live vehicle network, interface state and recording controls"
        )
        self.workspace_subtitle.setObjectName("experimentalWorkspaceSubtitle")
        self.workspace_subtitle.setFont(QFont(body_font_family, 9))
        title_column.addWidget(self.workspace_title)
        title_column.addWidget(self.workspace_subtitle)
        header_layout.addLayout(title_column, 1)

        self.header_vehicle = QLabel("NO VEHICLE SELECTED")
        self.header_vehicle.setObjectName("experimentalVehicleStatus")
        self.header_vehicle.setFont(QFont(body_font_family, 8, QFont.Bold))
        self.header_vehicle.setToolTip(
            "Select or identify a vehicle in the Sensors workspace."
        )
        header_layout.addWidget(self.header_vehicle)

        self.header_connection = QLabel("● OFFLINE")
        self.header_connection.setObjectName("experimentalConnectionOffline")
        self.header_connection.setFont(QFont(body_font_family, 8, QFont.Bold))
        header_layout.addWidget(self.header_connection)

        self.header_traffic = QLabel("0 FRAMES  /  0.0 FPS")
        self.header_traffic.setObjectName("experimentalTraffic")
        self.header_traffic.setFont(QFont(body_font_family, 8, QFont.Bold))
        header_layout.addWidget(self.header_traffic)

        self.home_button = QToolButton()
        self.home_button.setObjectName("experimentalHomeButton")
        self.home_button.setText("WORKSPACE HOME")
        self.home_button.setToolTip("Return to the task selection screen")
        if on_home is not None:
            self.home_button.clicked.connect(on_home)
        header_layout.addWidget(self.home_button)

        self.drawer_button = QToolButton()
        self.drawer_button.setObjectName("experimentalContextButton")
        self.drawer_button.setText("CONTEXT  ☷")
        self.drawer_button.setToolTip("Open vehicle context and workspace shortcuts")
        self.drawer_button.clicked.connect(toggle_quick_drawer)
        header_layout.addWidget(self.drawer_button)

        main_layout.addWidget(header)

        content_frame = QFrame()
        content_frame.setObjectName("experimentalContentFrame")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.addWidget(tabs, 1)
        main_layout.addWidget(content_frame, 1)

        root_layout.addWidget(main, 1)

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidget(root)

        tabs.currentChanged.connect(self._sync_current)
        tabs.currentChanged.connect(on_tab_changed)
        self._refresh_navigation_visibility()
        self._sync_current(tabs.currentIndex())

        self.setStyleSheet("""
            QWidget#experimentalWorkspace { background: #0b1014; }
            QFrame#experimentalRail {
                background: #111a20;
                border: 1px solid #26353b;
                border-radius: 13px;
            }
            QLabel#experimentalBrand { color: #e9f2ec; letter-spacing: 1.4px; }
            QLabel#experimentalBrandSubtitle {
                color: #79a58a; letter-spacing: 1.2px; padding-bottom: 8px;
            }
            QFrame#experimentalDivider { color: #293b3d; max-height: 1px; }
            QLabel#experimentalSectionLabel {
                color: #719184; letter-spacing: 1.5px;
                padding: 12px 5px 3px 5px;
            }
            QComboBox#experimentalModeSelector {
                background: #1a2928; color: #bce5c8;
                border: 1px solid #3a6250; border-radius: 7px;
                padding: 9px; font-weight: 700;
            }
            QToolButton#experimentalNavButton {
                text-align: left; color: #a8b8b1;
                background: transparent; border: 1px solid transparent;
                border-radius: 7px; padding: 8px 10px;
                font-size: 9pt; font-weight: 600;
            }
            QToolButton#experimentalNavButton:hover {
                color: #f0f6f1; background: #1d2c2c;
                border-color: #344b43;
            }
            QToolButton#experimentalNavButton:checked {
                color: #eaffef; background: #1b4934;
                border: 1px solid #397b55; font-weight: 800;
            }
            QLabel#experimentalRailFooter {
                color: #62766c; font-size: 7pt;
                border-top: 1px solid #293b3d; padding-top: 10px;
            }
            QFrame#experimentalHeader {
                background: #121d22; border: 1px solid #2a3b3d;
                border-radius: 13px;
            }
            QLabel#experimentalWorkspaceTitle {
                color: #f1f6f2; letter-spacing: 1px;
            }
            QLabel#experimentalWorkspaceSubtitle { color: #8da49a; }
            QLabel#experimentalVehicleStatus {
                color: #c4d7cb; background: #1c2b2b;
                border: 1px solid #354d45; border-radius: 7px;
                padding: 9px 11px;
            }
            QLabel#experimentalConnectionOffline,
            QLabel#headerOffline {
                color: #c5cdd0; background: #252e32;
                border: 1px solid #414c50; border-radius: 7px;
                padding: 9px 11px;
            }
            QLabel#headerOnline {
                color: #d8f5df; background: #173c2b;
                border: 1px solid #397b55; border-radius: 7px;
                padding: 9px 11px;
            }
            QLabel#headerSimulation {
                color: #f4e5bf; background: #42351d;
                border: 1px solid #806a37; border-radius: 7px;
                padding: 9px 11px;
            }
            QLabel#experimentalTraffic { color: #93b9a2; padding: 4px; }
            QToolButton#experimentalHomeButton {
                color: #a9bdb3; background: #1a2529;
                border: 1px solid #344448; border-radius: 7px;
                padding: 9px 11px; font-weight: 700;
            }
            QToolButton#experimentalHomeButton:hover {
                color: #edf7f0; background: #263b36;
            }
            QToolButton#experimentalContextButton {
                color: #e7f4ea; background: #234b37;
                border: 1px solid #4b8662; border-radius: 7px;
                padding: 9px 11px; font-weight: 700;
            }
            QToolButton#experimentalContextButton:hover { background: #2b6044; }
            QFrame#experimentalContentFrame {
                background: #10171b; border: 1px solid #26363a;
                border-radius: 13px;
            }
        """)

    def _handle_mode_change(self, _index):
        if self._on_workspace_mode_changed is not None:
            self._on_workspace_mode_changed(
                self.workspace_mode_selector.currentData()
            )
        self._refresh_navigation_visibility()

    def set_workspace_mode(self, mode):
        index = self.workspace_mode_selector.findData(mode)
        if index >= 0 and index != self.workspace_mode_selector.currentIndex():
            self.workspace_mode_selector.blockSignals(True)
            self.workspace_mode_selector.setCurrentIndex(index)
            self.workspace_mode_selector.blockSignals(False)
        self._refresh_navigation_visibility()

    def _refresh_navigation_visibility(self):
        for index, button in self._nav_buttons.items():
            try:
                visible = self.tabs.isTabVisible(index)
            except AttributeError:
                visible = True
            button.setVisible(visible)
        for section, indices in self._nav_sections:
            section.setVisible(any(
                not self._nav_buttons[index].isHidden()
                for index in indices if index in self._nav_buttons
            ))

    def _sync_current(self, index):
        for tab_index, button in self._nav_buttons.items():
            button.setChecked(tab_index == index)
        self._refresh_navigation_visibility()
