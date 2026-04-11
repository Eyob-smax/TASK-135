"""
Windows 11 – compatible visual theme for the District Console.

Applies a Fluent-inspired light palette using the Fusion style engine as the
base. High-DPI scaling is configured via Qt attributes before the QApplication
is created; call ``configure_highdpi()`` at module import time (before
QApplication instantiation) and ``apply_theme(app)`` once the app exists.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

# ──────────────────────────────────────────────────────────────────────────────
# Colour tokens — Windows 11 Fluent light palette
# ──────────────────────────────────────────────────────────────────────────────
_C = {
    "bg":          "#f3f3f3",   # Window / application background
    "surface":     "#ffffff",   # Card / panel surface
    "border":      "#d1d1d1",   # Subtle border
    "accent":      "#0078d4",   # Microsoft blue accent
    "accent_dark": "#005a9e",   # Hover/pressed state
    "accent_text": "#ffffff",   # Text on accent background
    "text":        "#1a1a1a",   # Primary text
    "text_dim":    "#666666",   # Secondary / placeholder text
    "danger":      "#c42b1c",   # Destructive actions
    "warn":        "#9d5d00",   # Warnings
    "success":     "#107c10",   # Positive feedback
    "frozen":      "#e6f2ff",   # Frozen stock row tint
    "approval":    "#fff8e0",   # Awaiting approval row tint
    "selected":    "#cce4f7",   # Table row selection
}

_STYLESHEET = f"""
/* ── Base window ── */
QMainWindow, QDialog, QWidget {{
    background-color: {_C['bg']};
    color: {_C['text']};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10pt;
}}

/* ── Menu bar ── */
QMenuBar {{
    background-color: {_C['surface']};
    border-bottom: 1px solid {_C['border']};
    padding: 2px;
}}
QMenuBar::item:selected {{
    background-color: {_C['selected']};
    border-radius: 4px;
}}
QMenu {{
    background-color: {_C['surface']};
    border: 1px solid {_C['border']};
    padding: 4px 0;
}}
QMenu::item {{
    padding: 6px 28px 6px 20px;
}}
QMenu::item:selected {{
    background-color: {_C['selected']};
}}
QMenu::separator {{
    height: 1px;
    background: {_C['border']};
    margin: 4px 0;
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {_C['accent']};
    color: {_C['accent_text']};
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    min-width: 80px;
}}
QPushButton:hover {{
    background-color: {_C['accent_dark']};
}}
QPushButton:pressed {{
    background-color: #004578;
}}
QPushButton:disabled {{
    background-color: {_C['border']};
    color: {_C['text_dim']};
}}
QPushButton[flat="true"] {{
    background-color: transparent;
    color: {_C['accent']};
    border: 1px solid {_C['accent']};
}}
QPushButton[flat="true"]:hover {{
    background-color: {_C['selected']};
}}

/* ── Inputs ── */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {_C['surface']};
    border: 1px solid {_C['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {_C['text']};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {_C['accent']};
    outline: none;
}}
QLineEdit[invalid="true"] {{
    border-color: {_C['danger']};
}}

/* ── Labels ── */
QLabel[heading="true"] {{
    font-size: 13pt;
    font-weight: 600;
}}
QLabel[subheading="true"] {{
    font-size: 10pt;
    color: {_C['text_dim']};
}}
QLabel[error="true"] {{
    color: {_C['danger']};
    font-size: 9pt;
}}
QLabel[success="true"] {{
    color: {_C['success']};
    font-size: 9pt;
}}

/* ── Tables ── */
QTableWidget, QTableView {{
    background-color: {_C['surface']};
    gridline-color: {_C['border']};
    selection-background-color: {_C['selected']};
    border: 1px solid {_C['border']};
    border-radius: 4px;
}}
QHeaderView::section {{
    background-color: {_C['bg']};
    border: none;
    border-bottom: 1px solid {_C['border']};
    padding: 6px 8px;
    font-weight: 600;
}}
QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
}}

/* ── Dock widgets ── */
QDockWidget {{
    titlebar-close-icon: none;
}}
QDockWidget::title {{
    background-color: {_C['bg']};
    padding: 4px 8px;
    font-weight: 600;
    border-bottom: 1px solid {_C['border']};
}}

/* ── MDI area ── */
QMdiArea {{
    background-color: #e8e8e8;
}}
QMdiSubWindow {{
    background-color: {_C['surface']};
    border: 1px solid {_C['border']};
}}
QMdiSubWindow::title {{
    background-color: {_C['bg']};
    padding: 4px;
}}

/* ── Toolbars ── */
QToolBar {{
    background-color: {_C['surface']};
    border-bottom: 1px solid {_C['border']};
    spacing: 4px;
    padding: 2px 4px;
}}
QToolButton {{
    background: transparent;
    border-radius: 4px;
    padding: 4px 8px;
}}
QToolButton:hover {{
    background-color: {_C['selected']};
}}

/* ── Status bar ── */
QStatusBar {{
    background-color: {_C['surface']};
    border-top: 1px solid {_C['border']};
    color: {_C['text_dim']};
}}

/* ── Scroll bars (thin Fluent style) ── */
QScrollBar:vertical {{
    width: 8px;
    background: transparent;
}}
QScrollBar::handle:vertical {{
    background: {_C['border']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    height: 8px;
    background: transparent;
}}
QScrollBar::handle:horizontal {{
    background: {_C['border']};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Tabs ── */
QTabWidget::pane {{
    border: 1px solid {_C['border']};
    border-radius: 4px;
}}
QTabBar::tab {{
    background: {_C['bg']};
    border: none;
    padding: 6px 16px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    border-bottom: 2px solid {_C['accent']};
    font-weight: 600;
}}
QTabBar::tab:hover {{
    background: {_C['selected']};
}}

/* ── Group box ── */
QGroupBox {{
    border: 1px solid {_C['border']};
    border-radius: 6px;
    margin-top: 12px;
    padding: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {_C['text_dim']};
}}

/* ── Notification bar (custom widget role) ── */
QWidget#NotificationBar[severity="info"] {{
    background-color: #ddf0ff;
    border-bottom: 1px solid #a8d4f5;
}}
QWidget#NotificationBar[severity="success"] {{
    background-color: #dff6dd;
    border-bottom: 1px solid #92d88d;
}}
QWidget#NotificationBar[severity="warning"] {{
    background-color: #fff4ce;
    border-bottom: 1px solid #f0d060;
}}
QWidget#NotificationBar[severity="error"] {{
    background-color: #fde7e9;
    border-bottom: 1px solid #f1a7ab;
}}
"""

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def configure_highdpi() -> None:
    """
    Enable per-monitor high-DPI scaling.

    Must be called **before** QApplication is instantiated.
    On Windows 11, this ensures sharp rendering on 125 %, 150 %, 200 % displays.
    """
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def apply_theme(app: QApplication) -> None:
    """Apply the Fluent light palette and stylesheet to *app*."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(_C["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(_C["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(_C["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(_C["bg"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(_C["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(_C["accent"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(_C["accent_text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(_C["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(_C["accent_text"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(_C["accent"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_C["text_dim"]))
    app.setPalette(palette)

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    app.setStyleSheet(_STYLESHEET)


def color(name: str) -> str:
    """Return a hex colour token by name (for inline widget styling)."""
    return _C.get(name, "#000000")
