"""Application-wide light and dark Qt theme definitions."""

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication


def apply_theme(window, enabled: bool, body_font_family: str, heading_font_family: str):
    app = QApplication.instance()
    if enabled:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#171b22"))
        palette.setColor(QPalette.WindowText, QColor("#e7ebf0"))
        palette.setColor(QPalette.Base, QColor("#10141a"))
        palette.setColor(QPalette.AlternateBase, QColor("#202630"))
        palette.setColor(QPalette.Text, QColor("#e7ebf0"))
        palette.setColor(QPalette.Button, QColor("#252d38"))
        palette.setColor(QPalette.ButtonText, QColor("#e7ebf0"))
        palette.setColor(QPalette.Highlight, QColor("#2c8054"))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        app.setPalette(palette)
        window.setStyleSheet("""
            QWidget { font-family: "{BODY_FONT}"; font-size: 10pt; }
            QMainWindow, QWidget { background: #171b22; color: #e7ebf0; }
            QWidget#workspaceHeader { background: #1b2a22; border: 1px solid #42684f; border-radius: 12px; }
            QLabel#brandBanner { background: #08140f; border: 1px solid #42684f; border-radius: 10px; padding: 2px; }
            QDockWidget#quickDrawer { background: #20242c; color: #e7ebf0; border-left: 1px solid #3a4655; }
            QDockWidget#quickDrawer::title { background: #20242c; padding: 10px 14px; font-weight: 700; }
            QWidget#drawerBody { background: #111d17; }
            QLabel#drawerBrandName { color: #f2f7f3; font-size: 16pt; font-weight: 850; letter-spacing: 0.5px; }
            QLabel#drawerBrandTagline { color: #8fb39a; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px; }
            QLabel#drawerBrandLogo { background: transparent; }
            QLabel#drawerTitle, QLabel#drawerSubtitle, QLabel#drawerCaption, QLabel#drawerValue, QLabel#drawerStatus, QLabel#drawerSection, QLabel#drawerNote, QLabel#toastMarker, QLabel#toastText { background: transparent; }
            QFrame#drawerCard { background: #252e39; border: 1px solid #3a4655; border-radius: 12px; }
            QLabel#drawerTitle { color: #f4f7fb; font-size: 14pt; font-weight: 800; letter-spacing: 1px; }
            QLabel#drawerSubtitle, QLabel#drawerCaption { color: #aeb9c6; font-size: 9pt; }
            QLabel#drawerValue { color: #f4f7fb; font-size: 10pt; font-weight: 700; }
            QLabel#drawerStatus { color: #82c5ff; font-weight: 700; }
            QLabel#drawerSection { color: #91a5bb; font-size: 9pt; font-weight: 800; letter-spacing: 1px; padding-top: 8px; }
            QLabel#drawerNote { color: #9caaba; background: #202a36; border: 1px solid #34475b; border-radius: 9px; padding: 10px; font-size: 9pt; }
            QPushButton#drawerNavButton { text-align: left; background: #1b2c22; border: 1px solid #344e3b; border-radius: 8px; padding: 9px 12px; min-height: 22px; }
            QPushButton#drawerNavButton:hover { background: #294b35; border-color: #6da17a; }
            QPushButton#drawerNavButton:checked { background: #245a39; border: 1px solid #72b486; color: #ffffff; font-weight: 800; }
            QToolButton#drawerToggle { background: #214b32; color: #eef8f0; border: 1px solid #4c8c60; border-radius: 8px; padding: 8px 12px; font-weight: 700; }
            QToolButton#drawerToggle:hover { background: #2d6843; }
            QFrame#toastNotification { background: #252e39; border: 1px solid #48617b; border-radius: 12px; }
            QFrame#toastNotification[kind="success"] { border-left: 4px solid #35b779; }
            QFrame#toastNotification[kind="warning"] { border-left: 4px solid #e5a93d; }
            QFrame#toastNotification[kind="error"] { border-left: 4px solid #e05d67; }
            QLabel#toastMarker { color: #8cc8ff; font-size: 15pt; font-weight: 800; }
            QLabel#toastText { color: #f2f6fa; font-size: 9pt; font-weight: 600; }
            QLabel#workspaceTitle { color: #ffffff; font-family: "{HEADING_FONT}"; font-size: 20pt; font-weight: 850; letter-spacing: 1.2px; }
            QLabel#workspaceSubtitle { color: #aebdcb; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 500; }
            QLabel#headerVehicle { background: #303d4c; color: #f3f7fb; border: 1px solid #46586b; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 700; }
            QLabel#headerOffline { background: #343b45; color: #c4ccd5; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
            QLabel#headerOnline { background: #173e30; color: #83e0b2; border: 1px solid #286849; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
            QLabel#headerSimulation { background: #4a391b; color: #ffd27c; border: 1px solid #80602b; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
            QLabel#headerTraffic { color: #dce9f7; font-family: "{BODY_FONT}"; font-size: 10.5pt; font-weight: 700; padding: 4px 6px; }
            QWidget#navigationRail { background: #111720; border: 1px solid #2c3744; border-radius: 10px; }
            QWidget#navigationSeparator { background: #344252; max-height: 1px; }
            QToolButton { background: transparent; color: #aebdcb; border: 1px solid transparent; border-radius: 8px; padding: 7px 2px; font-size: 9pt; font-weight: 600; }
            QToolButton:hover { background: #263342; color: #ffffff; border-color: #3b5269; }
            QToolButton:checked { background: #24496b; color: #ffffff; border: 1px solid #3989d8; }
            QGroupBox { border: 1px solid #303a47; border-radius: 8px; margin-top: 12px; padding: 12px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QLabel#modeBanner { background: #202a36; border: 1px solid #34475b; border-radius: 8px; padding: 14px 16px; color: #dce9f7; font-family: "{BODY_FONT}"; font-size: 11pt; font-weight: 600; }
            QLabel#welcomeSubtitle { color: #9eabb9; font-size: 11pt; }
            QPushButton { background: #283443; color: #eaf1f8; border: 1px solid #3a4b5e; border-radius: 7px; padding: 8px 14px; min-height: 24px; }
            QPushButton:hover { background: #34485e; border-color: #5486b8; }
            QPushButton:pressed { background: #1d5d9c; }
            QPushButton#taskButton { text-align: left; font-size: 11pt; font-weight: 600; padding: 16px 18px; background: #202a36; }
            QPushButton#taskButton:hover { background: #293b4e; }
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QListWidget, QTreeWidget, QTableWidget, QSpinBox { background: #10141a; color: #e7ebf0; border: 1px solid #35404d; border-radius: 5px; padding: 5px; selection-background-color: #2c8054; }
            QComboBox QAbstractItemView { background: #202630; color: #e7ebf0; selection-background-color: #2675c9; }
            QTabWidget::pane { border: 1px solid #303a47; border-radius: 8px; background: #171b22; top: 0; }
            QTabBar::tab { background: #202630; color: #aeb9c6; border: 0; border-bottom: 1px solid #303a47; padding: 14px 12px; min-width: 118px; text-align: left; }
            QTabBar::tab:selected { background: #293b4e; color: #ffffff; border-left: 3px solid #3989d8; font-weight: 600; }
            QHeaderView::section { background: #252e39; color: #dce4ed; border: 0; border-bottom: 1px solid #3a4654; padding: 7px; }
            QCheckBox { spacing: 8px; }
            QDialog#startupSplash { background: #171b22; }
            QLabel#splashEyebrow { color: #78b9f2; font-size: 9pt; font-weight: 800; letter-spacing: 1px; }
            QLabel#splashTitle { color: #f4f7fb; font-family: "{HEADING_FONT}"; font-size: 25pt; font-weight: 850; letter-spacing: -0.4px; }
            QLabel#splashSubtitle { color: #aebdcb; font-size: 10pt; }
            QFrame#splashCard { background: #202a36; border: 1px solid #34475b; border-radius: 12px; }
            QLabel#splashCardTitle { color: #f4f7fb; font-size: 12pt; font-weight: 700; }
            QLabel#splashCardText { color: #aebdcb; font-size: 9pt; }
            QPushButton#splashAction, QPushButton#splashContinue { background: #245a39; border: 1px solid #72b486; font-weight: 700; }
            QPushButton#splashAction:hover, QPushButton#splashContinue:hover { background: #2d7048; }
            QLabel#splashLogo { background: transparent; }
            QToolTip { background: #202630; color: #ffffff; border: 1px solid #526174; }
        """.replace("{BODY_FONT}", body_font_family).replace("{HEADING_FONT}", heading_font_family))
    else:
        palette = app.style().standardPalette()
        palette.setColor(QPalette.Highlight, QColor("#2c8054"))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        app.setPalette(palette)
        window.setStyleSheet("""
            QWidget { font-family: "{BODY_FONT}"; font-size: 10pt; }
            QWidget#workspaceHeader { background: #edf5ef; border: 1px solid #b9d2c0; border-radius: 12px; }
            QLabel#brandBanner { background: #0a1710; border: 1px solid #8da996; border-radius: 10px; padding: 2px; }
            QDockWidget#quickDrawer { background: #f8fafc; color: #1e293b; border-left: 1px solid #d9e0e8; }
            QDockWidget#quickDrawer::title { background: #f1f5f9; padding: 10px 14px; font-weight: 700; }
            QWidget#drawerBody { background: #f0f6f1; }
            QLabel#drawerBrandName { color: #173323; font-size: 16pt; font-weight: 850; letter-spacing: 0.5px; }
            QLabel#drawerBrandTagline { color: #52745d; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px; }
            QLabel#drawerBrandLogo { background: transparent; }
            QLabel#drawerTitle, QLabel#drawerSubtitle, QLabel#drawerCaption, QLabel#drawerValue, QLabel#drawerStatus, QLabel#drawerSection, QLabel#drawerNote, QLabel#toastMarker, QLabel#toastText { background: transparent; }
            QFrame#drawerCard { background: #ffffff; border: 1px solid #d9e0e8; border-radius: 12px; }
            QLabel#drawerTitle { color: #172033; font-size: 14pt; font-weight: 800; letter-spacing: 1px; }
            QLabel#drawerSubtitle, QLabel#drawerCaption { color: #64748b; font-size: 9pt; }
            QLabel#drawerValue { color: #172033; font-size: 10pt; font-weight: 700; }
            QLabel#drawerStatus { color: #1769aa; font-weight: 700; }
            QLabel#drawerSection { color: #64748b; font-size: 9pt; font-weight: 800; letter-spacing: 1px; padding-top: 8px; }
            QLabel#drawerNote { color: #475569; background: #eff6ff; border: 1px solid #d5e5f6; border-radius: 9px; padding: 10px; font-size: 9pt; }
            QPushButton#drawerNavButton { text-align: left; background: #ffffff; border: 1px solid #d0dfd3; border-radius: 8px; padding: 9px 12px; min-height: 22px; color: #243449; }
            QPushButton#drawerNavButton:hover { background: #e7f3e9; border-color: #8bb797; }
            QPushButton#drawerNavButton:checked { background: #245a39; border: 1px solid #72b486; color: #ffffff; font-weight: 800; }
            QToolButton#drawerToggle { background: #e5f0e7; color: #1c5131; border: 1px solid #a7c9ae; border-radius: 8px; padding: 8px 12px; font-weight: 700; }
            QToolButton#drawerToggle:hover { background: #d5e8d9; }
            QFrame#toastNotification { background: #ffffff; border: 1px solid #d3deea; border-radius: 12px; }
            QFrame#toastNotification[kind="success"] { border-left: 4px solid #219b64; }
            QFrame#toastNotification[kind="warning"] { border-left: 4px solid #d28a16; }
            QFrame#toastNotification[kind="error"] { border-left: 4px solid #d94853; }
            QLabel#toastMarker { color: #2675c9; font-size: 15pt; font-weight: 800; }
            QLabel#toastText { color: #243449; font-size: 9pt; font-weight: 600; }
            QLabel#workspaceTitle { color: #172033; font-family: "{HEADING_FONT}"; font-size: 20pt; font-weight: 850; letter-spacing: 1.2px; }
            QLabel#workspaceSubtitle { color: #596b7d; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 500; }
            QLabel#headerVehicle { background: #edf2f7; color: #24384c; border: 1px solid #cbd6e0; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 700; }
            QLabel#headerOffline { background: #eef0f2; color: #596675; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
            QLabel#headerOnline { background: #e1f4e9; color: #17633b; border: 1px solid #a6d7b8; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
            QLabel#headerSimulation { background: #fff1d6; color: #80520b; border: 1px solid #e6c98d; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
            QLabel#headerTraffic { color: #26394b; font-family: "{BODY_FONT}"; font-size: 10.5pt; font-weight: 700; padding: 4px 6px; }
            QWidget#navigationRail { background: #f1f4f7; border: 1px solid #d5dde5; border-radius: 10px; }
            QWidget#navigationSeparator { background: #d5dde5; max-height: 1px; }
            QToolButton { background: transparent; color: #526273; border: 1px solid transparent; border-radius: 8px; padding: 7px 2px; font-size: 9pt; font-weight: 600; }
            QToolButton:hover { background: #e2eaf2; color: #1f3448; border-color: #c4d1de; }
            QToolButton:checked { background: #dceaf7; color: #174b78; border: 1px solid #6a9dcc; }
            QLabel#modeBanner { background: #edf3f8; border: 1px solid #cbd7e2; border-radius: 8px; padding: 14px 16px; color: #26394b; font-family: "{BODY_FONT}"; font-size: 11pt; font-weight: 600; }
            QLabel#welcomeSubtitle { color: #647386; font-size: 11pt; }
            QPushButton { border: 1px solid #c5ced8; border-radius: 7px; padding: 8px 14px; min-height: 24px; }
            QPushButton#taskButton { text-align: left; font-size: 11pt; font-weight: 600; padding: 16px 18px; }
            QTabWidget::pane { border: 1px solid #cbd3dc; border-radius: 8px; }
            QTabBar::tab { padding: 14px 12px; min-width: 118px; text-align: left; }
            QTabBar::tab:selected { font-weight: 600; border-left: 3px solid #2675c9; }
            QGroupBox { border: 1px solid #cbd3dc; border-radius: 8px; margin-top: 12px; padding: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QDialog#startupSplash { background: #f8fafc; }
            QLabel#splashEyebrow { color: #2675c9; font-size: 9pt; font-weight: 800; letter-spacing: 1px; }
            QLabel#splashTitle { color: #172033; font-family: "{HEADING_FONT}"; font-size: 25pt; font-weight: 850; letter-spacing: -0.4px; }
            QLabel#splashSubtitle { color: #596b7d; font-size: 10pt; }
            QFrame#splashCard { background: #ffffff; border: 1px solid #d9e0e8; border-radius: 12px; }
            QLabel#splashCardTitle { color: #172033; font-size: 12pt; font-weight: 700; }
            QLabel#splashCardText { color: #596b7d; font-size: 9pt; }
            QPushButton#splashAction, QPushButton#splashContinue { background: #245a39; color: #ffffff; border: 1px solid #72b486; font-weight: 700; }
            QPushButton#splashAction:hover, QPushButton#splashContinue:hover { background: #2d7048; }
            QLabel#splashLogo { background: transparent; }
        """.replace("{BODY_FONT}", body_font_family).replace("{HEADING_FONT}", heading_font_family))


    # Shared interaction and data-view polish inspired by Beautiful UI / Notchset.
    # Kept native to Qt so the desktop app does not acquire a React runtime.
    window.setStyleSheet(window.styleSheet() + """
        QPushButton {
            border-radius: 7px;
            padding: 5px 9px;
            min-height: 19px;
            font-weight: 650;
        }
        QPushButton:disabled { opacity: 0.45; }
        QLineEdit, QComboBox, QSpinBox, QListWidget, QTreeWidget,
        QTableWidget, QPlainTextEdit {
            border-radius: 6px;
            padding: 4px 6px;
        }
        QGroupBox {
            border-radius: 9px;
            margin-top: 11px;
            padding: 10px 9px 8px 9px;
            font-weight: 700;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        QTabBar::tab {
            padding: 8px 9px;
            min-width: 92px;
        }
        QHeaderView::section {
            padding: 5px 6px;
        }
        QTableWidget::item {
            padding: 3px 5px;
        }
        QCheckBox, QRadioButton {
            spacing: 6px;
            padding: 1px;
        }
        QLabel#workspaceTitle {
            font-size: 16pt;
            letter-spacing: 0.6px;
        }
        QLabel#workspaceSubtitle {
            font-size: 8.5pt;
        }
        QLabel#headerVehicle, QLabel#headerOffline, QLabel#headerOnline,
        QLabel#headerSimulation {
            padding: 6px 8px;
            font-size: 8.5pt;
        }
        QLabel#headerTraffic {
            font-size: 9pt;
            padding: 2px 4px;
        }
        QToolButton#drawerToggle {
            padding: 5px 8px;
        }
        QTableWidget {
            alternate-background-color: rgba(120, 145, 160, 0.08);
            gridline-color: rgba(130, 150, 170, 0.18);
            selection-background-color: #286344;
        }
        QTableWidget::item {
            padding: 7px 8px;
            border-bottom: 1px solid rgba(130, 150, 170, 0.12);
        }
        QHeaderView::section {
            padding: 10px 9px;
            font-weight: 750;
            border: none;
        }
        QCheckBox, QRadioButton { spacing: 9px; padding: 4px 2px; }
        QToolTip { padding: 7px 9px; border-radius: 6px; }
        QScrollBar:vertical {
            width: 10px; margin: 3px; border: none; border-radius: 5px;
        }
        QScrollBar::handle:vertical {
            min-height: 28px; border-radius: 5px;
            background: rgba(130, 150, 170, 0.45);
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal {
            height: 10px; margin: 3px; border: none; border-radius: 5px;
        }
        QScrollBar::handle:horizontal {
            min-width: 28px; border-radius: 5px;
            background: rgba(130, 150, 170, 0.45);
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    """)
