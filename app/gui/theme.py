"""Modern dark theme (QSS) for the PyQt6 GUI.

Density tuned for a 1366x768 screen: compact font, thin paddings, and a single
uniform height for all interactive controls so proportions stay balanced.

Colours are defined once in ``C`` and every widget (including native
sub-controls such as spin-box buttons, combo popups and menus) is styled so no
default-light Qt palette leaks through and text always stays readable.
"""

from __future__ import annotations

C = {
    # surfaces
    "bg": "#0b1120",
    "bg_alt": "#0f1a2e",
    "card": "#14213a",
    "card_hover": "#1b2c4a",
    "input_bg": "#0a1424",
    "sel_bg": "#1e3a5f",
    # lines
    "border": "#23344f",
    "border_light": "#33507a",
    # text
    "text": "#e6edf6",
    "muted": "#9fb3d1",
    "muted_dim": "#7d90ad",
    "disabled": "#5d6f8c",
    "on_accent": "#04121f",
    # accents
    "accent": "#38bdf8",
    "accent_dark": "#0ea5e9",
    "green": "#34d399",
    "green_dark": "#10b981",
    "red": "#f87171",
    "red_dark": "#ef4444",
    "amber": "#fbbf24",
    "purple": "#a78bfa",
}

FONT_FAMILY = "Segoe UI"

# Shared metrics so every page keeps the same rhythm.
RADIUS_CARD = 10
RADIUS_CTRL = 6
CTRL_HEIGHT = 24  # content height (before padding) for buttons & inputs

QSS = f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: 12px;
    color: {C['text']};
}}
QMainWindow, QWidget#root, QDialog {{
    background-color: {C['bg']};
}}
QWidget {{
    background-color: transparent;
}}
QFrame#card {{
    background-color: {C['card']};
    border: 1px solid {C['border']};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#sidebar {{
    background-color: {C['bg_alt']};
    border: none;
    border-right: 1px solid {C['border']};
}}
QFrame#header {{
    background-color: {C['bg_alt']};
    border: none;
    border-bottom: 1px solid {C['border']};
}}
QLabel {{
    background: transparent;
}}
QLabel#h1 {{
    font-size: 16px;
    font-weight: 700;
}}
QLabel#h2 {{
    font-size: 13px;
    font-weight: 600;
}}
QLabel#muted {{
    color: {C['muted']};
}}
QLabel#logo {{
    font-size: 15px;
    font-weight: 800;
    color: {C['accent']};
}}
QLabel#cardTitle {{
    font-size: 11px;
    font-weight: 600;
    color: {C['muted']};
}}
QLabel#cardValue {{
    font-size: 17px;
    font-weight: 700;
}}
QPushButton {{
    background-color: {C['card_hover']};
    border: 1px solid {C['border']};
    border-radius: {RADIUS_CTRL}px;
    padding: 3px 11px;
    min-height: {CTRL_HEIGHT}px;
    font-weight: 600;
}}
QPushButton:hover {{
    border-color: {C['border_light']};
    background-color: #21334f;
}}
QPushButton:pressed {{
    background-color: {C['input_bg']};
}}
QPushButton:disabled {{
    color: {C['disabled']};
    background-color: {C['input_bg']};
    border-color: {C['border']};
}}
QPushButton#primary {{
    background-color: {C['accent_dark']};
    border-color: {C['accent_dark']};
    color: {C['on_accent']};
}}
QPushButton#primary:hover {{
    background-color: {C['accent']};
    border-color: {C['accent']};
}}
QPushButton#success {{
    background-color: {C['green_dark']};
    border-color: {C['green_dark']};
    color: {C['on_accent']};
}}
QPushButton#success:hover {{
    background-color: {C['green']};
    border-color: {C['green']};
}}
QPushButton#danger {{
    background-color: {C['red_dark']};
    border-color: {C['red_dark']};
    color: #ffffff;
}}
QPushButton#danger:hover {{
    background-color: {C['red']};
    border-color: {C['red']};
}}
QPushButton#ghost {{
    background-color: transparent;
    border-color: transparent;
}}
QPushButton#ghost:hover {{
    background-color: {C['card_hover']};
    border-color: {C['border']};
}}
QPushButton#nav {{
    background-color: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: {RADIUS_CTRL}px;
    text-align: left;
    padding: 6px 12px;
    min-height: 26px;
    font-weight: 600;
    color: {C['muted']};
    outline: none;
}}
QPushButton#nav:hover {{
    color: {C['text']};
    background-color: {C['card']};
}}
QPushButton#nav:checked {{
    color: {C['text']};
    background-color: {C['card_hover']};
    border-left: 3px solid {C['accent']};
    outline: none;
}}
QPushButton#nav:checked:hover {{
    background-color: {C['card_hover']};
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: {RADIUS_CTRL}px;
    padding: 2px 8px;
    min-height: {CTRL_HEIGHT}px;
    selection-background-color: {C['accent_dark']};
    selection-color: {C['on_accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateTimeEdit:focus {{
    border-color: {C['accent']};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled, QDateTimeEdit:disabled {{
    color: {C['disabled']};
}}
QLineEdit::placeholder {{
    color: {C['muted_dim']};
}}

/* spin-box steppers (otherwise Fusion draws light default buttons) */
QSpinBox, QDoubleSpinBox {{
    padding-right: 18px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 16px;
    margin: 1px 1px 0 0;
    border: none;
    border-left: 1px solid {C['border']};
    border-top-right-radius: {RADIUS_CTRL}px;
    background-color: {C['card_hover']};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 16px;
    margin: 0 1px 1px 0;
    border: none;
    border-left: 1px solid {C['border']};
    border-bottom-right-radius: {RADIUS_CTRL}px;
    background-color: {C['card_hover']};
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {C['border']};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {C['muted']};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C['muted']};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
    background: transparent;
}}
QComboBox::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C['muted']};
    margin-right: 7px;
}}
QComboBox::down-arrow:on {{
    border-top-color: {C['accent']};
}}
QComboBox QAbstractItemView {{
    background-color: {C['bg_alt']};
    border: 1px solid {C['border']};
    border-radius: {RADIUS_CTRL}px;
    padding: 2px;
    outline: none;
    selection-background-color: {C['card_hover']};
    selection-color: {C['text']};
    color: {C['text']};
}}
QComboBox QAbstractItemView::item {{
    min-height: 20px;
    padding: 2px 8px;
    border-radius: 4px;
    color: {C['text']};
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {C['card_hover']};
    color: {C['text']};
}}

QCheckBox {{
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid {C['border_light']};
    background-color: {C['input_bg']};
}}
QCheckBox::indicator:checked {{
    background-color: {C['accent_dark']};
    border-color: {C['accent_dark']};
}}
QCheckBox::indicator:hover {{
    border-color: {C['accent']};
}}

QTableWidget, QTableView {{
    background-color: {C['bg']};
    alternate-background-color: {C['bg_alt']};
    border: 1px solid {C['border']};
    border-radius: {RADIUS_CARD}px;
    gridline-color: {C['border']};
    selection-background-color: {C['sel_bg']};
    selection-color: {C['text']};
    color: {C['text']};
}}
QTableWidget::item, QTableView::item {{
    padding: 2px 6px;
    color: {C['text']};
}}
QTableWidget::item:hover, QTableView::item:hover {{
    background-color: {C['card_hover']};
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {C['sel_bg']};
    color: {C['text']};
}}
QHeaderView::section {{
    background-color: {C['card']};
    border: none;
    border-bottom: 1px solid {C['border']};
    border-right: 1px solid {C['border']};
    padding: 4px 8px;
    font-weight: 700;
    color: {C['muted']};
}}
QTableCornerButton::section {{
    background-color: {C['card']};
    border: none;
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}
QAbstractScrollArea::corner {{
    background: transparent;
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {C['border_light']};
    border-radius: 4px;
    min-height: 26px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C['muted_dim']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 9px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {C['border_light']};
    border-radius: 4px;
    min-width: 26px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {C['muted_dim']};
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QPlainTextEdit, QTextEdit {{
    background-color: {C['bg']};
    border: 1px solid {C['border']};
    border-radius: {RADIUS_CARD}px;
    padding: 6px;
    color: {C['text']};
    selection-background-color: {C['sel_bg']};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}

QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: {RADIUS_CARD}px;
    top: -1px;
    margin-top: 2px;
}}
QTabBar::tab {{
    background: {C['input_bg']};
    color: {C['muted']};
    padding: 5px 14px;
    margin-right: 2px;
    border: 1px solid {C['border']};
    border-bottom: none;
    border-top-left-radius: {RADIUS_CTRL}px;
    border-top-right-radius: {RADIUS_CTRL}px;
}}
QTabBar::tab:selected {{
    color: {C['text']};
    background: {C['card']};
    border-color: {C['border_light']};
}}
QTabBar::tab:hover {{
    color: {C['text']};
}}
QStackedWidget {{
    background: transparent;
}}
QProgressBar {{
    border: none;
    background: {C['border']};
    border-radius: 3px;
    text-align: center;
    color: {C['text']};
}}
QProgressBar::chunk {{
    background: {C['green']};
    border-radius: 3px;
}}

QMenu {{
    background-color: {C['bg_alt']};
    border: 1px solid {C['border']};
    border-radius: {RADIUS_CTRL}px;
    padding: 4px;
}}
QMenu::item {{
    padding: 4px 18px;
    border-radius: 4px;
    color: {C['text']};
}}
QMenu::item:selected {{
    background-color: {C['card_hover']};
    color: {C['text']};
}}
QMenu::separator {{
    height: 1px;
    background: {C['border']};
    margin: 4px 6px;
}}

QToolTip {{
    background-color: {C['bg_alt']};
    color: {C['text']};
    border: 1px solid {C['border_light']};
    padding: 4px;
    border-radius: 6px;
}}
QMessageBox {{
    background-color: {C['bg']};
}}
QMessageBox QLabel {{
    color: {C['text']};
}}
"""


def build_stylesheet() -> str:
    return QSS


def apply_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
