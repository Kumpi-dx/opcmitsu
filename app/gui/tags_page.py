"""Task page: live Read Data table + Write Data table for configured tags.

The tag list (TAG_NAME) is not managed here; it is read from the YAML config
file. Use "Muat Ulang dari config.yaml" to re-apply the file live.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import TagConfig, load_config
from ..store import QUALITY_GOOD
from .theme import C
from .widgets import format_ts

if TYPE_CHECKING:
    from ..gateway import Gateway


_READ_COLS = ["No", "Nama", "Alamat", "Tipe", "Akses", "Nilai", "Kualitas", "Waktu"]
_WRITE_COLS = ["Nama", "Alamat", "Tipe", "Nilai", "Aksi", "Status"]


class TagsPage(QWidget):
    def __init__(self, gateway: "Gateway", config_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gateway = gateway
        self.config_path = config_path
        self._write_inputs: dict[str, QLineEdit] = {}
        self._write_status: dict[str, QLabel] = {}
        self._write_signature: tuple = ()
        self._build()

    # -------------------------------------------------------------- build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("Task")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addStretch(1)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("muted")
        top.addWidget(self.lbl_count)
        root.addLayout(top)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        btn_reload = QPushButton("Muat Ulang dari config.yaml")
        btn_reload.setObjectName("primary")
        btn_reload.clicked.connect(self._reload_tags)
        toolbar.addWidget(btn_reload)
        toolbar.addStretch(1)
        hint = QLabel("Daftar TAG_NAME dikelola melalui file config.yaml.")
        hint.setObjectName("muted")
        toolbar.addWidget(hint)
        root.addLayout(toolbar)

        self.tabs = QTabWidget()

        # --- Read Data
        self.read_table = QTableWidget(0, len(_READ_COLS))
        self.read_table.setHorizontalHeaderLabels(_READ_COLS)
        self.read_table.verticalHeader().setVisible(False)
        self.read_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.read_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.read_table.setAlternatingRowColors(True)
        read_vh = self.read_table.verticalHeader()
        read_vh.setDefaultSectionSize(30)
        rh = self.read_table.horizontalHeader()
        rh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        rh.setStretchLastSection(False)
        rh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in {0: 46, 2: 96, 3: 84, 4: 70, 5: 120, 6: 104, 7: 96}.items():
            rh.resizeSection(col, width)
        read_wrap = QWidget()
        rl = QVBoxLayout(read_wrap)
        rl.setContentsMargins(0, 8, 0, 0)
        rl.addWidget(self.read_table)
        self.tabs.addTab(read_wrap, "Read Data")

        # --- Write Data
        self.write_table = QTableWidget(0, len(_WRITE_COLS))
        self.write_table.setHorizontalHeaderLabels(_WRITE_COLS)
        self.write_table.verticalHeader().setVisible(False)
        self.write_table.setAlternatingRowColors(True)
        self.write_table.verticalHeader().setDefaultSectionSize(40)
        wh = self.write_table.horizontalHeader()
        wh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        wh.setStretchLastSection(False)
        wh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for col, width in {0: 150, 1: 96, 2: 84, 3: 150, 4: 88}.items():
            wh.resizeSection(col, width)
        write_wrap = QWidget()
        wl = QVBoxLayout(write_wrap)
        wl.setContentsMargins(0, 8, 0, 0)
        wl.setSpacing(8)
        wrow = QHBoxLayout()
        btn_all = QPushButton("Tulis Semua")
        btn_all.setObjectName("primary")
        btn_all.clicked.connect(self._write_all)
        wrow.addWidget(btn_all)
        wrow.addStretch(1)
        wl.addLayout(wrow)
        wl.addWidget(self.write_table)
        self.tabs.addTab(write_wrap, "Write Data")

        root.addWidget(self.tabs, 1)

    # ---------------------------------------------------------- tag list
    def _tags(self) -> list[TagConfig]:
        return list(self.gateway.active_tags())

    def _reload_tags(self) -> None:
        try:
            cfg = load_config(self.config_path)
        except Exception as e:
            QMessageBox.critical(self, "Muat Ulang", f"Gagal memuat konfigurasi: {e}")
            return
        self.gateway.set_tags(cfg.tags)
        self._write_signature = ()
        self._rebuild_read()
        self._rebuild_write()
        self.lbl_count.setText(f"{len(cfg.tags)} tag dimuat dari config.yaml")

    # ------------------------------------------------------------ read tab
    def _rebuild_read(self) -> None:
        tags = self._tags()
        self.read_table.setRowCount(len(tags))
        for row, tag in enumerate(tags):
            self.read_table.setItem(row, 0, _center(str(row + 1)))
            self.read_table.setItem(row, 1, QTableWidgetItem(tag.name))
            self.read_table.setItem(row, 2, QTableWidgetItem(tag.address))
            self.read_table.setItem(row, 3, QTableWidgetItem(tag.type))
            access = _center("RW" if tag.writable else "RO")
            if not tag.writable:
                access.setForeground(QColor(C["muted_dim"]))
            self.read_table.setItem(row, 4, access)
            self.read_table.setItem(row, 5, _center("-"))
            self.read_table.setItem(row, 6, _center("-"))
            self.read_table.setItem(row, 7, QTableWidgetItem("-"))

    def _refresh_read(self) -> None:
        tags = self._tags()
        if self.read_table.rowCount() != len(tags):
            self._rebuild_read()
        snap = self.gateway.store.snapshot()
        for row, tag in enumerate(tags):
            tv = snap.get(tag.name)
            val_item = self.read_table.item(row, 5)
            q_item = self.read_table.item(row, 6)
            ts_item = self.read_table.item(row, 7)
            if tv is None:
                val_item.setText("-")
                q_item.setText("Belum ada")
                continue
            good = tv.quality == QUALITY_GOOD
            if tag.type == "bit" or isinstance(tv.value, bool):
                val_item.setText("ON" if tv.value else "OFF")
                val_item.setForeground(QColor(C["green"] if tv.value else C["red"]))
            elif isinstance(tv.value, float):
                val_item.setText(f"{tv.value:,.2f}")
                val_item.setForeground(QColor(C["text"]))
            else:
                val_item.setText(f"{tv.value:,}" if isinstance(tv.value, int) else str(tv.value))
                val_item.setForeground(QColor(C["text"]))
            if not good:
                val_item.setText("-")
                val_item.setForeground(QColor(C["red"]))
            q_item.setText(tv.quality)
            q_item.setForeground(QColor(C["green"] if good else (C["amber"] if tv.quality == "Uncertain" else C["red"])))
            ts_item.setText(_fmt_time(tv.timestamp))
            ts_item.setToolTip(format_ts(tv.timestamp))

    # ----------------------------------------------------------- write tab
    def _rebuild_write(self) -> None:
        tags = self._tags()
        signature = tuple((t.name, t.address, t.type, t.writable) for t in tags)
        if signature == self._write_signature:
            return
        self._write_signature = signature
        self._write_inputs.clear()
        self._write_status.clear()
        self.write_table.setRowCount(len(tags))
        for row, tag in enumerate(tags):
            self.write_table.setItem(row, 0, QTableWidgetItem(tag.name))
            self.write_table.setItem(row, 1, QTableWidgetItem(tag.address))
            self.write_table.setItem(row, 2, QTableWidgetItem(tag.type))

            editor = QLineEdit()
            editor.setPlaceholderText("ON/OFF" if tag.type == "bit" else "nilai...")
            editor.setEnabled(tag.writable)
            editor.returnPressed.connect(lambda n=tag.name: self._write_one(n))
            self.write_table.setCellWidget(row, 3, editor)
            self._write_inputs[tag.name] = editor

            btn = QPushButton("Tulis")
            btn.setObjectName("primary" if tag.writable else "ghost")
            btn.setMinimumHeight(28)
            btn.setEnabled(tag.writable)
            btn.clicked.connect(lambda _=False, n=tag.name: self._write_one(n))
            self.write_table.setCellWidget(row, 4, btn)

            status = QLabel("-")
            status.setObjectName("muted")
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.write_table.setCellWidget(row, 5, status)
            self._write_status[tag.name] = status

    def _refresh_write(self) -> None:
        self._rebuild_write()
        for name, label in self._write_status.items():
            res = self.gateway.write_status(name)
            if not res:
                label.setText("siap")
                label.setStyleSheet(f"color: {C['muted']}")
                continue
            _, ok, msg = res
            if ok is None:
                label.setText("mengirim...")
                label.setStyleSheet(f"color: {C['amber']}")
            elif ok:
                label.setText("berhasil")
                label.setStyleSheet(f"color: {C['green']}")
            else:
                label.setText(f"gagal: {msg[:22]}")
                label.setStyleSheet(f"color: {C['red']}")

    # ------------------------------------------------------------- writes
    def _write_one(self, name: str) -> None:
        tag = next((t for t in self._tags() if t.name == name and t.writable), None)
        if tag is None:
            return
        editor = self._write_inputs.get(name)
        if editor is None:
            return
        try:
            value = _parse_value(tag.type, editor.text())
        except ValueError:
            QMessageBox.warning(self, "Nilai tidak valid", f"'{editor.text()}' bukan nilai {tag.type} yang valid.")
            return
        self.gateway.write_tag_now(name, value)

    def _write_all(self) -> None:
        for name, editor in self._write_inputs.items():
            if editor.isEnabled() and editor.text().strip():
                self._write_one(name)

    # ------------------------------------------------------------ refresh
    def refresh(self) -> None:
        self._refresh_read()
        self._refresh_write()
        if not self.lbl_count.text():
            self.lbl_count.setText(f"{len(self._tags())} tag")


def _parse_value(tag_type: str, text: str) -> Any:
    text = text.strip()
    if tag_type == "bit":
        return text.lower() in ("1", "on", "true", "yes", "ya", "h")
    if tag_type in ("int16", "uint16", "int32", "uint32"):
        return int(float(text))
    return float(text)


def _center(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def _fmt_time(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))