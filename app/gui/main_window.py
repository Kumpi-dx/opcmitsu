"""Main window: sidebar navigation, header status, stacked pages, live timer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .logs_page import LogsPage
from .settings_page import SettingsPage
from .tags_page import TagsPage
from .widgets import StatusDot

if TYPE_CHECKING:
    from ..config import AppConfig
    from ..gateway import Gateway

log = logging.getLogger("opc_mitsu.gui")


class MainWindow(QMainWindow):
    def __init__(self, gateway: "Gateway", config: "AppConfig", config_path: str) -> None:
        super().__init__()
        self.gateway = gateway
        self.config = config
        self.config_path = config_path
        self.setWindowTitle("opc_mitsu — Gateway PLC Mitsubishi ↔ MySQL")
        self.setMinimumSize(980, 600)
        self._fit_to_screen()
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_all)
        self._timer.start(500)
        self.refresh_header()

    # -------------------------------------------------------------- build
    def _fit_to_screen(self) -> None:
        """Choose a default size that fits the screen and center the window."""
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        w, h = 1180, 700
        if avail is not None:
            w = min(w, max(980, avail.width() - 80))
            h = min(h, max(600, avail.height() - 80))
        self.resize(w, h)
        if avail is not None:
            frame = self.frameGeometry()
            frame.moveCenter(avail.center())
            self.move(frame.topLeft())

    def _build(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_header())
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        root.addLayout(right, 1)

        self.pages: dict[str, QWidget] = {}
        self.tags_page = TagsPage(self.gateway, self.config_path)
        self.settings_page = SettingsPage(self.gateway, self.config_path)
        self.logs_page = LogsPage()

        for key, page in [
            ("tags", self.tags_page),
            ("settings", self.settings_page),
            ("logs", self.logs_page),
        ]:
            self.pages[key] = page
            self.stack.addWidget(page)

        # attach GUI log tail
        handler = self.logs_page.create_handler()
        logging.getLogger("opc_mitsu").addHandler(handler)
        handler.setLevel(logging.DEBUG)

        self.switch_page("tags")

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(184)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(12, 16, 12, 16)
        lay.setSpacing(4)

        logo = QLabel("opc_mitsu")
        logo.setObjectName("logo")
        lay.addWidget(logo)
        sub = QLabel("PLC Mitsubishi · MySQL")
        sub.setObjectName("muted")
        lay.addWidget(sub)
        lay.addSpacing(12)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text in [
            ("tags", "Task"),
            ("settings", "Setup"),
            ("logs", "Logs"),
        ]:
            btn = QPushButton(text)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(36)
            btn.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
            lay.addWidget(btn)

        lay.addStretch(1)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("muted")
        lay.addWidget(ver)
        return sidebar

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(46)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 0, 14, 0)
        lay.setSpacing(10)

        self.page_title = QLabel("Task")
        self.page_title.setObjectName("h1")
        lay.addWidget(self.page_title)
        lay.addStretch(1)

        self.dot_plc = StatusDot(11, "idle")
        self.dot_db = StatusDot(11, "idle")
        lbl_plc = QLabel("PLC")
        lbl_db = QLabel("DB")
        for w in (lbl_plc, lbl_db):
            w.setObjectName("muted")

        lay.addSpacing(8)
        lay.addWidget(self.dot_plc)
        lay.addWidget(lbl_plc)
        lay.addSpacing(10)
        lay.addWidget(self.dot_db)
        lay.addWidget(lbl_db)
        lay.addSpacing(16)

        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("success")
        self.btn_start.clicked.connect(self._start_gateway)
        lay.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.clicked.connect(self._stop_gateway)
        lay.addWidget(self.btn_stop)

        self.btn_restart = QPushButton("Restart")
        self.btn_restart.clicked.connect(self._confirm_restart)
        lay.addWidget(self.btn_restart)
        return header

    # ------------------------------------------------------------ actions
    def switch_page(self, key: str) -> None:
        titles = {
            "tags": "Task",
            "settings": "Setup",
            "logs": "Logs",
        }
        page = self.pages.get(key)
        btn = self.nav_buttons.get(key)
        if page is None or btn is None:
            return
        self.stack.setCurrentWidget(page)
        self.page_title.setText(titles[key])
        if not btn.isChecked():
            btn.setChecked(True)

    def _confirm_restart(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        mb = QMessageBox(self)
        mb.setWindowTitle("Restart Gateway")
        mb.setText("Restart gateway dengan konfigurasi terakhir dari file?")
        mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if mb.exec() == QMessageBox.StandardButton.Yes:
            from ..config import load_config

            self.gateway.restart(load_config(self.config_path))
            self.settings_page.load_from_config(self.gateway.config)
            self.refresh_header()

    def _start_gateway(self) -> None:
        if self.gateway.running:
            return
        from PyQt6.QtWidgets import QMessageBox

        try:
            self.gateway.start()
        except Exception as e:
            log.exception("Gateway gagal start: %s", e)
            QMessageBox.critical(self, "Start", f"Gagal menjalankan gateway: {e}")
            return
        self.settings_page.load_from_config(self.gateway.config)
        self.refresh_header()

    def _stop_gateway(self) -> None:
        if not self.gateway.running:
            return
        try:
            self.gateway.stop()
        except Exception as e:
            log.warning("Error saat stop gateway: %s", e)
        self.refresh_header()

    # ------------------------------------------------------------- refresh
    def refresh_header(self) -> None:
        status = self.gateway.status.get()
        running = self.gateway.running
        if not running:
            self.dot_plc.set_state("off")
            self.dot_db.set_state("off")
        else:
            self.dot_plc.set_state("ok" if status.plc_connected else "bad")
            self.dot_db.set_state(
                "ok"
                if status.db_connected
                else ("off" if self.gateway.config and not self.gateway.config.database.enabled else "bad")
            )
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_restart.setEnabled(running)

    def _refresh_all(self) -> None:
        self.refresh_header()
        current = self.stack.currentWidget()
        try:
            if current is self.tags_page:
                self.tags_page.refresh()
        except Exception as e:
            log.debug("Refresh GUI error: %s", e)

    # -------------------------------------------------------------- events
    def closeEvent(self, event) -> None:  # noqa: N802
        from PyQt6.QtWidgets import QMessageBox

        mb = QMessageBox(self)
        mb.setWindowTitle("Keluar")
        mb.setText("Hentikan gateway dan keluar dari opc_mitsu?")
        mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if mb.exec() == QMessageBox.StandardButton.Yes:
            self._timer.stop()
            try:
                self.gateway.stop()
            except Exception as e:
                log.warning("Error saat stop gateway: %s", e)
            event.accept()
        else:
            event.ignore()