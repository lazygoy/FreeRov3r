"""L319 factory wiring-network reference and optional local PDF viewer."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHeaderView, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    HAS_PDF_VIEWER = True
except ImportError:
    QPdfDocument = QPdfView = None
    HAS_PDF_VIEWER = False

from .diagnostics.l319_wiring import NETWORKS as L319_WIRING_NETWORKS
from .diagnostics.l319_wiring import SOURCE_URL as L319_WIRING_SOURCE_URL
from .diagnostics.l319_wiring import DEFAULT_ENGINE as L319_DEFAULT_ENGINE


class WiringDiagramsTab(QWidget):
    """Factory-reference L319 network explorer and optional local PDF viewer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_document = None
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        heading = QLabel("LAND ROVER DISCOVERY 4 / LR4  •  FACTORY WIRING REFERENCE")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        intro = QLabel(
            f"Default configuration: {L319_DEFAULT_ENGINE}  •  2010 model-year LHD reference. "
            "Factory network data is separate from simulated scan results and is not proof "
            "that a particular vehicle is equipped with every listed module."
        )
        intro.setWordWrap(True)
        intro.setObjectName("mutedText")
        root.addWidget(intro)

        self.pages = QTabWidget()
        root.addWidget(self.pages, 1)

        network_page = QWidget()
        network_layout = QVBoxLayout(network_page)
        network_layout.setContentsMargins(4, 6, 4, 4)
        top = QHBoxLayout()
        top.addWidget(QLabel("NETWORK:"))
        self.network_select = QComboBox()
        for key, info in L319_WIRING_NETWORKS.items():
            self.network_select.addItem(info["title"], key)
        self.network_select.currentIndexChanged.connect(self.refresh_network)
        top.addWidget(self.network_select, 1)
        network_layout.addLayout(top)

        self.network_summary = QLabel()
        self.network_summary.setWordWrap(True)
        self.network_summary.setObjectName("mutedText")
        network_layout.addWidget(self.network_summary)

        split = QHBoxLayout()
        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(["Module", "Factory ID"])
        self.module_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.module_tree.setMinimumWidth(300)
        self.module_tree.itemSelectionChanged.connect(self.show_module)
        split.addWidget(self.module_tree, 2)

        detail_column = QVBoxLayout()
        detail_title = QLabel("WIRING / CONNECTOR DETAILS")
        detail_title.setObjectName("sectionTitle")
        detail_column.addWidget(detail_title)
        self.module_detail = QPlainTextEdit()
        self.module_detail.setReadOnly(True)
        self.module_detail.setPlaceholderText("Select a factory-listed module.")
        detail_column.addWidget(self.module_detail, 1)
        split.addLayout(detail_column, 3)
        network_layout.addLayout(split, 1)
        self.pages.addTab(network_page, "Network Reference")

        pdf_page = QWidget()
        pdf_layout = QVBoxLayout(pdf_page)
        pdf_controls = QHBoxLayout()
        load_pdf = QPushButton("Load Local Wiring PDF")
        load_pdf.clicked.connect(self.load_local_pdf)
        pdf_controls.addWidget(load_pdf)
        open_source = QPushButton("Open Online Reference")
        open_source.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(L319_WIRING_SOURCE_URL)))
        pdf_controls.addWidget(open_source)
        pdf_controls.addStretch(1)
        pdf_layout.addLayout(pdf_controls)
        if HAS_PDF_VIEWER:
            self.pdf_view = QPdfView()
            self.pdf_document = QPdfDocument(self)
            self.pdf_view.setDocument(self.pdf_document)
            try:
                self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            except AttributeError:
                pass
            pdf_layout.addWidget(self.pdf_view, 1)
            pdf_note = QLabel("Load a PDF copy you are entitled to use. Scroll through pages; the network reference identifies the relevant factory page numbers.")
        else:
            self.pdf_view = None
            pdf_note = QLabel(
                "This build does not have the optional Qt PDF viewer installed. "
                "Load Local Wiring PDF will open your selected file in the system PDF reader. "
                "The factory network references remain available in the Network Reference tab."
            )
        pdf_note.setWordWrap(True)
        pdf_note.setObjectName("mutedText")
        pdf_layout.addWidget(pdf_note)
        self.pages.addTab(pdf_page, "Factory Diagram Viewer")

        self.refresh_network()

    def refresh_network(self, *_):
        key = self.network_select.currentData()
        info = L319_WIRING_NETWORKS.get(key)
        self.module_tree.clear()
        self.module_detail.clear()
        if not info:
            return
        self.network_summary.setText(
            f"{info['description']}\n{info['pages']}\n{info['pair']}\n"
            f"Diagnostic socket: {info['dlc']}"
        )
        for code, component, name, connector, notes in info["modules"]:
            item = QTreeWidgetItem([f"{code}  •  {name}", component])
            item.setData(0, Qt.UserRole, (code, component, name, connector, notes, key))
            self.module_tree.addTopLevelItem(item)
        if self.module_tree.topLevelItemCount():
            self.module_tree.setCurrentItem(self.module_tree.topLevelItem(0))

    def show_module(self):
        item = self.module_tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        if not data:
            self.module_detail.clear()
            return
        code, component, name, connector, notes, key = data
        info = L319_WIRING_NETWORKS[key]
        self.module_detail.setPlainText(
            f"MODULE: {name}\nSHORT NAME: {code}\nFACTORY COMPONENT ID: {component}\n"
            f"NETWORK: {info['title']}\nREFERENCE: {info['pages']}\n\n"
            f"CONNECTOR / PIN REFERENCES\n{connector}\n\n"
            f"NOTES\n{notes}\n\n"
            f"NETWORK CONDUCTORS\n{info['pair']}\n\n"
            f"DIAGNOSTIC SOCKET\n{info['dlc']}\n\n"
            "DATA STATUS: TRANSCRIBED FACTORY REFERENCE. NOT LIVE VEHICLE DETECTION. "
            "Confirm model year, VIN, market, equipment and connector view before probing."
        )

    def load_local_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Land Rover wiring diagram PDF", "", "PDF files (*.pdf)"
        )
        if not path:
            return
        if HAS_PDF_VIEWER:
            status = self.pdf_document.load(path)
            if status != QPdfDocument.Status.Ready:
                QMessageBox.warning(self, "PDF load failed", f"Qt could not load this PDF. Status: {status}")
                return
            self.pages.setCurrentIndex(1)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
