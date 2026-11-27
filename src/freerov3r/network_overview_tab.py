"""Vehicle network topology workspace with evidence-labelled simulator state."""

from PySide6.QtGui import QBrush, QColor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QScrollArea, QHeaderView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .diagnostics.l319_wiring import NETWORKS as L319_WIRING_NETWORKS
from .diagnostics.l319_wiring import DEFAULT_ENGINE as L319_DEFAULT_ENGINE


class NetworkOverviewTab(QWidget):
    """Interactive, evidence-labelled topology view over the current module inventory."""

    STATUS_STYLES = {
        "faults": ("#ef5350", "#351d22", "ATTENTION"),
        "clean": ("#35b779", "#17352b", "NO FAULTS"),
        "unscanned": ("#9aa7b5", "#202a35", "NOT SCANNED"),
        "offline": ("#87909a", "#24282d", "NO RESPONSE"),
    }

    def __init__(self, network, vin_provider=None, history_callback=None, parent=None):
        super().__init__(parent)
        self.network = network
        self.vin_provider = vin_provider or (lambda: None)
        self.history_callback = history_callback or (lambda *args, **kwargs: None)
        self.selected_code = None
        self.map_buttons = {}
        self._building = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("VEHICLE NETWORK TOPOLOGY")
        title.setObjectName("sectionTitle")
        title_column.addWidget(title)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        self.heading.setObjectName("mutedText")
        title_column.addWidget(self.heading)
        header.addLayout(title_column, 1)

        self.scan_all_button = QPushButton("⟳  Scan All Modules")
        self.scan_all_button.setObjectName("primaryButton")
        self.scan_all_button.clicked.connect(self.scan_all)
        header.addWidget(self.scan_all_button)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.summary_row = QHBoxLayout()
        self.summary_cards = {}
        for key, label in (
            ("total", "MODULES"),
            ("scanned", "SCANNED"),
            ("faults", "WITH DTCS"),
            ("unscanned", "NOT SCANNED"),
        ):
            card = QFrame()
            card.setObjectName("topologyMetric")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 8, 12, 8)
            value = QLabel("0")
            value.setObjectName("topologyMetricValue")
            caption = QLabel(label)
            caption.setObjectName("topologyMetricLabel")
            card_layout.addWidget(value)
            card_layout.addWidget(caption)
            self.summary_cards[key] = value
            self.summary_row.addWidget(card)
        root.addLayout(self.summary_row)

        legend = QHBoxLayout()
        legend.addWidget(QLabel("STATUS:"))
        for color, label in (
            ("#35b779", "No faults"),
            ("#ef5350", "DTCs present"),
            ("#9aa7b5", "Not scanned"),
            ("#87909a", "No response"),
        ):
            swatch = QLabel("●")
            swatch.setStyleSheet(f"color:{color};font-size:15px;")
            legend.addWidget(swatch)
            text = QLabel(label)
            text.setObjectName("mutedText")
            legend.addWidget(text)
        legend.addStretch(1)
        self.view_toggle = QPushButton("System List")
        self.view_toggle.setCheckable(True)
        self.view_toggle.toggled.connect(self._toggle_view)
        legend.addWidget(self.view_toggle)
        root.addLayout(legend)

        content = QHBoxLayout()
        content.setSpacing(10)

        self.map_scroll = QScrollArea()
        self.map_scroll.setWidgetResizable(True)
        self.map_scroll.setFrameShape(QFrame.NoFrame)
        self.map_scroll.setMinimumWidth(0)
        self.map_scroll.setObjectName("topologyMapScroll")
        self.map_body = QWidget()
        self.map_grid = QGridLayout(self.map_body)
        self.map_grid.setContentsMargins(8, 8, 8, 8)
        self.map_grid.setSpacing(10)
        self.map_tree = QTreeWidget()
        self.map_tree.setObjectName("thinkcarTopologyTree")
        self.map_tree.setHeaderLabels(["VEHICLE NETWORK / MODULE", "SCAN STATUS", "DTCs"])
        self.map_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.map_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.map_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.map_tree.setAlternatingRowColors(False)
        self.map_tree.setUniformRowHeights(True)
        self.map_tree.itemSelectionChanged.connect(self._map_selection_changed)
        self.map_grid.addWidget(self.map_tree, 0, 0)
        self.map_scroll.setWidget(self.map_body)
        content.addWidget(self.map_scroll, 3)

        self.system_list = QTreeWidget()
        self.system_list.setHeaderLabels(["System / module", "Status", "DTCs", "Last scan"])
        self.system_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.system_list.setMinimumWidth(360)
        self.system_list.itemSelectionChanged.connect(self._list_selection_changed)
        self.system_list.itemDoubleClicked.connect(self._open_module_details)
        self.system_list.hide()
        content.addWidget(self.system_list, 3)

        detail_frame = QFrame()
        detail_frame.setObjectName("topologyDetailPanel")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(8)
        detail_title = QLabel("MODULE DETAILS")
        detail_title.setObjectName("sectionTitle")
        detail_layout.addWidget(detail_title)
        self.detail_name = QLabel("Select a module")
        self.detail_name.setObjectName("topologyDetailName")
        self.detail_name.setWordWrap(True)
        detail_layout.addWidget(self.detail_name)
        self.detail_status = QLabel("No module selected")
        self.detail_status.setObjectName("mutedText")
        detail_layout.addWidget(self.detail_status)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("Select a module node to inspect scan status and diagnostic trouble codes.")
        detail_layout.addWidget(self.detail_text, 1)
        self.scan_selected_button = QPushButton("Scan Selected Module")
        self.scan_selected_button.clicked.connect(self.scan_selected)
        self.scan_selected_button.setEnabled(False)
        detail_layout.addWidget(self.scan_selected_button)
        content.addWidget(detail_frame, 2)
        root.addLayout(content, 1)

        self._toggle_view(False)
        self.refresh()

    def set_network(self, network):
        self.network = network
        self.selected_code = None
        self.refresh()

    def _module_status(self, module):
        if not module.available:
            return "offline"
        if module.last_scan is None:
            return "unscanned"
        if module.dtcs:
            return "faults"
        return "clean"

    def _status_text(self, module):
        return self.STATUS_STYLES[self._module_status(module)][2]

    def _toggle_view(self, list_mode):
        self.map_scroll.setVisible(not list_mode)
        self.system_list.setVisible(list_mode)
        self.view_toggle.setText("Topology Map" if list_mode else "System List")

    def _clear_map(self):
        self.map_tree.clear()
        self.map_buttons.clear()

    def _make_module_node(self, module):
        status = self._module_status(module)
        accent, background, label = self.STATUS_STYLES[status]
        node = QPushButton()
        node.setObjectName("topologyModuleNode")
        node.setCheckable(True)
        node.setMinimumSize(145, 82)
        node.setMaximumHeight(100)
        node.setStyleSheet(
            "QPushButton#topologyModuleNode {"
            f"background:{background};border:1px solid {accent};"
            "border-radius:9px;padding:8px;text-align:left;color:#edf2f7;}"
            "QPushButton#topologyModuleNode:checked {border:2px solid #58a6ff;}"
            "QPushButton#topologyModuleNode:hover {border:2px solid #a9c9e8;}"
        )
        dtc_count = len(module.dtcs)
        node.setText(f"{module.code}\n{module.name}\n{label}  ·  {dtc_count} DTC")
        node.setToolTip(
            f"{module.name}\nStatus: {label}\nDTC count: {dtc_count}\n"
            "Inventory is simulated; physical network path and ECU address are not verified."
        )
        node.clicked.connect(lambda checked=False, code=module.code: self.select_module(code))
        self.map_buttons[module.code] = node
        return node

    def _build_map(self):
        """Build a Thinkcar-style expandable vehicle/network/module tree.

        Network membership comes from the transcribed 2010 L319 factory
        reference. Scan state is overlaid only where a simulator fixture can
        be matched; unmatched factory entries remain reference-only.
        """
        self._clear_map()
        root = QTreeWidgetItem([
            f"2010 DISCOVERY 4  •  {L319_DEFAULT_ENGINE}",
            "FACTORY REFERENCE",
            "—",
        ])
        root.setExpanded(True)
        root.setForeground(0, QBrush(QColor("#58a6ff")))
        self.map_tree.addTopLevelItem(root)

        # Explicit aliases only where the simulator fixture represents the
        # same functional module. No guessed mapping for optional equipment.
        fixture_aliases = {
            "ABS/DSC": "ABS",
            "AIR-SUS": "RLM",
            "SAS": "SASM",
            "IC-HS": "IC",
            "IC-MS": "IC",
        }
        for network_key in ("HS-CAN", "MS-CAN", "MOST"):
            info = L319_WIRING_NETWORKS.get(network_key, {})
            branch = QTreeWidgetItem([
                f"▰  {info.get('title', network_key)}",
                "WIRING REFERENCE",
                "—",
            ])
            branch.setExpanded(True)
            branch.setForeground(0, QBrush(QColor("#58a6ff")))
            branch.setToolTip(0, f"{info.get('description', '')}\n{info.get('pages', '')}")
            root.addChild(branch)

            for code, component, name, connector, notes in info.get("modules", []):
                fixture_code = fixture_aliases.get(code, code)
                try:
                    module = self.network.get_module(fixture_code)
                except (KeyError, AttributeError):
                    module = None

                if module is None:
                    status = "REFERENCE ONLY"
                    dtc_count = "—"
                    accent = "#8995a3"
                else:
                    status = self._status_text(module)
                    dtc_count = str(len(module.dtcs))
                    accent = self.STATUS_STYLES[self._module_status(module)][0]

                item = QTreeWidgetItem([
                    f"{code}  ·  {name}  [{component}]",
                    status,
                    dtc_count,
                ])
                item.setData(0, Qt.UserRole, {
                    "fixture_code": fixture_code if module is not None else None,
                    "code": code,
                    "component": component,
                    "name": name,
                    "connector": connector,
                    "notes": notes,
                    "network": network_key,
                })
                item.setForeground(0, QBrush(QColor(accent)))
                item.setForeground(1, QBrush(QColor(accent)))
                item.setToolTip(
                    0,
                    f"{info.get('title', network_key)}\nFactory component: {component}\n"
                    f"Connector: {connector}\n{notes}"
                )
                branch.addChild(item)

        self.map_tree.expandAll()
        self.map_tree.resizeColumnToContents(1)
        self.map_tree.resizeColumnToContents(2)

    def _map_selection_changed(self):
        item = self.map_tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        if not isinstance(data, dict):
            return
        fixture_code = data.get("fixture_code")
        if fixture_code:
            self.select_module(fixture_code)
            return

        network_key = data.get("network")
        info = L319_WIRING_NETWORKS.get(network_key, {})
        self.selected_code = None
        self.detail_name.setText(f"{data.get('code')}  |  {data.get('name')}")
        self.detail_status.setText("FACTORY REFERENCE ONLY  •  NOT IN SIMULATOR INVENTORY")
        self.detail_status.setStyleSheet("color:#8995a3;font-weight:700;")
        self.detail_text.setPlainText(
            f"FACTORY COMPONENT: {data.get('component')}\n"
            f"NETWORK: {info.get('title', network_key)}\n"
            f"REFERENCE: {info.get('pages', '')}\n\n"
            f"CONNECTOR / PIN REFERENCES\n{data.get('connector', '')}\n\n"
            f"NOTES\n{data.get('notes', '')}\n\n"
            f"NETWORK CONDUCTORS\n{info.get('pair', '')}\n\n"
            f"DIAGNOSTIC SOCKET\n{info.get('dlc', '')}\n\n"
            "DATA SOURCE: TRANSCRIBED 2010 L319 FACTORY WIRING REFERENCE.\n"
            "LIVE ECU PRESENCE AND SCAN STATUS HAVE NOT BEEN VERIFIED."
        )
        self.scan_selected_button.setEnabled(False)

    def _build_system_list(self):
        self.system_list.clear()
        groups = {}
        for module in self.network.modules:
            group = groups.get(module.category)
            if group is None:
                group = QTreeWidgetItem([module.category, "", "", ""])
                self.system_list.addTopLevelItem(group)
                groups[module.category] = group
            item = QTreeWidgetItem([
                f"{module.code} — {module.name}",
                self._status_text(module),
                str(len(module.dtcs)),
                module.last_scan or "—",
            ])
            item.setData(0, Qt.UserRole, module.code)
            group.addChild(item)
            accent = self.STATUS_STYLES[self._module_status(module)][0]
            for col in (0, 1):
                item.setForeground(col, QBrush(QColor(accent)))
        self.system_list.expandAll()
        self.system_list.resizeColumnToContents(1)
        self.system_list.resizeColumnToContents(2)
        self.system_list.resizeColumnToContents(3)

    def refresh(self):
        self._building = True
        try:
            modules = list(self.network.modules)
            scanned = [m for m in modules if m.last_scan is not None]
            faults = [m for m in modules if m.last_scan is not None and m.dtcs]
            self.summary_cards["total"].setText(str(len(modules)))
            self.summary_cards["scanned"].setText(str(len(scanned)))
            self.summary_cards["faults"].setText(str(len(faults)))
            self.summary_cards["unscanned"].setText(str(sum(m.last_scan is None for m in modules)))
            vin = self.vin_provider() or "NO VIN SELECTED"
            self.heading.setText(
                f"VIN: {vin}  •  {len(modules)} inventory entries  •  "
                "SIMULATED DATA / PHYSICAL ECU NETWORK NOT VERIFIED"
            )
            self._build_map()
            self._build_system_list()
        finally:
            self._building = False

        if self.selected_code and any(m.code == self.selected_code for m in modules):
            self.select_module(self.selected_code)
        elif modules:
            self.select_module(modules[0].code)
        else:
            self._show_empty_selection()

    def _show_empty_selection(self):
        self.selected_code = None
        self.detail_name.setText("No modules in inventory")
        self.detail_status.setText("No scan data")
        self.detail_text.clear()
        self.scan_selected_button.setEnabled(False)

    def select_module(self, code):
        try:
            module = self.network.get_module(code)
        except (KeyError, AttributeError):
            self._show_empty_selection()
            return
        self.selected_code = code
        for key, button in self.map_buttons.items():
            button.setChecked(key == code)
        for index in range(self.system_list.topLevelItemCount()):
            group = self.system_list.topLevelItem(index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.data(0, Qt.UserRole) == code:
                    self.system_list.setCurrentItem(child)
                    break

        status = self._status_text(module)
        accent = self.STATUS_STYLES[self._module_status(module)][0]
        self.detail_name.setText(f"{module.code}  |  {module.name}")
        self.detail_status.setText(f"{status}  •  {len(module.dtcs)} DTC(S)")
        self.detail_status.setStyleSheet(f"color:{accent};font-weight:700;")
        lines = [
            f"MODULE: {module.code}",
            f"SYSTEM GROUP: {module.category}",
            f"STATUS: {status}",
            f"LAST SCAN: {module.last_scan or 'Never'}",
            f"AVAILABILITY: {'Responding in simulator' if module.available else 'No response in simulator'}",
            "",
            "DIAGNOSTIC TROUBLE CODES",
        ]
        if module.dtcs:
            for dtc in module.dtcs:
                lines.extend([
                    f"{dtc.code}  |  {dtc.status}  |  {dtc.severity}",
                    dtc.description,
                    "",
                ])
        else:
            lines.append("No DTC entries in the current module fixture.")
        lines.extend([
            "",
            "DATA SOURCE: SIMULATED MODULE FIXTURE",
            "ECU ADDRESS: NOT VERIFIED",
            "PHYSICAL BUS / ROUTE: NOT VERIFIED",
        ])
        self.detail_text.setPlainText("\n".join(lines))
        self.scan_selected_button.setEnabled(bool(module.available))

    def _list_selection_changed(self):
        if self._building:
            return
        item = self.system_list.currentItem()
        code = item.data(0, Qt.UserRole) if item else None
        if code:
            self.select_module(code)

    def _open_module_details(self, item, column):
        code = item.data(0, Qt.UserRole)
        if code:
            self.select_module(code)

    def scan_selected(self):
        if not self.selected_code:
            return
        module = self.network.scan_module(self.selected_code)
        self.history_callback(
            "topology_module_scan",
            f"Topology module scan: {module.code}",
            {"module": module.code, "source": "simulated_module_network",
             "dtcs": [dtc.code for dtc in module.dtcs]},
            vin=self.vin_provider(),
        )
        self.refresh()
        self.select_module(module.code)

    def scan_all(self):
        modules = self.network.scan_all()
        self.history_callback(
            "topology_full_scan",
            "Topology full inventory scan",
            {"source": "simulated_module_network",
             "modules_scanned": [module.code for module in modules],
             "dtcs": {module.code: [dtc.code for dtc in module.dtcs] for module in modules}},
            vin=self.vin_provider(),
        )
        self.refresh()
