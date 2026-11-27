"""Persistent navigation rail and vehicle-context header."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)


class NavigationWorkspace(QScrollArea):
    def __init__(
        self,
        tabs,
        heading_font_family,
        body_font_family,
        toggle_quick_drawer,
        on_tab_changed,
        on_workspace_mode_changed=None,
        parent=None,
    ):
        super().__init__(parent)
        tabs.tabBar().hide()
        workspace = QWidget()
        outer_layout = QVBoxLayout(workspace)
        outer_layout.setContentsMargins(7, 6, 7, 7)
        outer_layout.setSpacing(6)

        header = QWidget()
        header.setObjectName("workspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(10)

        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        self.workspace_title = QLabel("Capture")
        self.workspace_title.setObjectName("workspaceTitle")
        workspace_title_font = QFont(heading_font_family, 20, QFont.Bold)
        workspace_title_font.setItalic(True)
        self.workspace_title.setFont(workspace_title_font)
        self.workspace_subtitle = QLabel("Passive vehicle diagnostics and CAN monitoring")
        self.workspace_subtitle.setObjectName("workspaceSubtitle")
        self.workspace_subtitle.setFont(QFont(body_font_family, 9, QFont.Medium))
        title_column.addWidget(self.workspace_title)
        title_column.addWidget(self.workspace_subtitle)
        header_layout.addLayout(title_column, 1)

        self.workspace_mode_selector = QComboBox()
        self.workspace_mode_selector.setObjectName("workspaceModeSelector")
        self.workspace_mode_selector.addItem("Diagnostics", "diagnostics")
        self.workspace_mode_selector.addItem("CAN Research Lab", "research")
        self.workspace_mode_selector.setToolTip(
            "Switch between vehicle diagnostics and passive CAN research"
        )
        if on_workspace_mode_changed is not None:
            self.workspace_mode_selector.currentIndexChanged.connect(
                lambda _index: on_workspace_mode_changed(
                    self.workspace_mode_selector.currentData()
                )
            )
        header_layout.addWidget(self.workspace_mode_selector)

        self.header_vehicle = QLabel("NO VEHICLE SELECTED")
        self.header_vehicle.setObjectName("headerVehicle")
        self.header_vehicle.setFont(QFont(body_font_family, 9, QFont.DemiBold))
        self.header_vehicle.setToolTip("Select or identify a vehicle in the Sensors workspace.")
        header_layout.addWidget(self.header_vehicle)

        self.header_connection = QLabel("● OFFLINE")
        self.header_connection.setObjectName("headerOffline")
        self.header_connection.setFont(QFont(body_font_family, 9, QFont.Bold))
        header_layout.addWidget(self.header_connection)

        self.header_traffic = QLabel("0 frames  |  0.0 fps")
        self.header_traffic.setObjectName("headerTraffic")
        self.header_traffic.setFont(QFont(body_font_family, 10, QFont.DemiBold))
        header_layout.addWidget(self.header_traffic)

        self.drawer_button = QToolButton()
        self.drawer_button.setObjectName("drawerToggle")
        self.drawer_button.setText("☷  QUICK PANEL")
        self.drawer_button.setToolTip("Open vehicle context and workspace shortcuts")
        self.drawer_button.clicked.connect(toggle_quick_drawer)
        header_layout.addWidget(self.drawer_button)

        outer_layout.addWidget(header)

        content_row = QHBoxLayout()
        content_row.setSpacing(10)
        content_row.addWidget(tabs, 1)
        outer_layout.addLayout(content_row, 1)
        workspace.setMinimumSize(0, 0)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidget(workspace)
        tabs.currentChanged.connect(on_tab_changed)
