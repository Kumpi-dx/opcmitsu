"""Logs page: live tail of application logs."""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..logging_setup import GTailHandler
from .theme import C

_LEVEL_COLOR = {
    "DEBUG": C["muted"],
    "INFO": C["text"],
    "WARNING": C["amber"],
    "ERROR": C["red"],
    "CRITICAL": C["red"],
}


class LogEmitter(QObject):
    entry = pyqtSignal(str, str)  # message, levelname


class LogsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.emitter = LogEmitter()
        self._max_lines = 5000
        self._min_level = 0
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("Logs")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(QLabel("Level:"))
        self.level_combo = QComboBox()
        self.level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.level_combo.setCurrentText("INFO")
        self.level_combo.currentTextChanged.connect(self._set_level)
        top.addWidget(self.level_combo)
        self.autoscroll = QCheckBox("Auto-scroll")
        self.autoscroll.setChecked(True)
        top.addWidget(self.autoscroll)
        btn_clear = QPushButton("Bersihkan")
        btn_clear.clicked.connect(self._clear)
        top.addWidget(btn_clear)
        root.addLayout(top)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(self._max_lines)
        root.addWidget(self.view, 1)

        self.emitter.entry.connect(self._append)

    # ---- handler wiring -------------------------------------------------
    def create_handler(self) -> GTailHandler:
        handler = GTailHandler()
        handler.set_callback(self._forward)
        return handler

    def _forward(self, record: logging.LogRecord) -> None:
        if record.levelno < self._min_level:
            return
        try:
            msg = self._format(record)
        except Exception:
            msg = record.getMessage()
        self.emitter.entry.emit(msg, record.levelname)

    @staticmethod
    def _format(record: logging.LogRecord) -> str:
        ts = LogsPage._ts(record)
        return f"{ts} {record.levelname:<7} {record.name}: {record.getMessage()}"

    @staticmethod
    def _ts(record: logging.LogRecord) -> str:
        from datetime import datetime

        return datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

    def _append(self, msg: str, level: str) -> None:
        color = _LEVEL_COLOR.get(level.upper(), C["text"])
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(
            f"<span style='color:{color}'>{_esc(msg)}</span><br>"
        )
        if self.autoscroll.isChecked():
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _set_level(self, text: str) -> None:
        self._min_level = getattr(logging, text, logging.INFO)

    def _clear(self) -> None:
        self.view.clear()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")