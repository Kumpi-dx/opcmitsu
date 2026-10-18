"""Settings page: edit all configuration and apply/restart the gateway."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    AppConfig,
    DatabaseConfig,
    PlcConfig,
    TagConfig,
    load_config,
    save_config,
)
from .theme import C

if TYPE_CHECKING:
    from ..gateway import Gateway


def _row(lbl: str, widget: QWidget) -> tuple[QWidget, QWidget]:
    lab = QLabel(lbl)
    lab.setMinimumWidth(138)
    lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lab, widget


class SettingsPage(QWidget):
    def __init__(self, gateway: "Gateway", config_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gateway = gateway
        self.config_path = config_path
        self._tags: list[TagConfig] = []
        self._build()
        self.load_from_config(gateway.config)

    # ---------------------------------------------------------------- UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("Setup")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addStretch(1)
        lbl = QLabel(self.config_path)
        lbl.setObjectName("muted")
        top.addWidget(lbl)
        root.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self._form = QVBoxLayout(container)
        self._form.setContentsMargins(0, 0, 6, 0)
        self._form.setSpacing(10)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_reload = QPushButton("Muat Ulang dari File")
        btn_reload.clicked.connect(self._reload_from_file)
        bottom.addWidget(btn_reload)
        btn_save = QPushButton("Simpan Konfigurasi")
        btn_save.clicked.connect(self._save_only)
        bottom.addWidget(btn_save)
        btn_apply = QPushButton("Simpan & Restart Gateway")
        btn_apply.setObjectName("primary")
        btn_apply.clicked.connect(self._save_and_restart)
        bottom.addWidget(btn_apply)
        root.addLayout(bottom)

        # ----- app
        card, grid = self._new_card("Aplikasi")
        self.app_name = QLineEdit()
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._place(grid, [_row("Nama aplikasi", self.app_name), _row("Level log", self.log_level)])
        self._form.addWidget(card)

        # ----- plc
        card, grid = self._new_card("Koneksi PLC")
        self.plc_driver = QComboBox()
        self.plc_driver.addItems(["mitsubishi", "modbus_tcp", "modbus_rtu", "omron_fins"])
        self.plc_ip = QLineEdit()
        self.plc_port = self._spin(0, 65535)
        self.plc_protocol = QComboBox()
        self.plc_protocol.addItems(["binary", "ascii"])
        self.plc_plctype = QComboBox()
        self.plc_plctype.addItems(["Q", "L", "QnA", "iQ-L", "iQ-R"])
        self.plc_network = self._spin(0, 255)
        self.plc_pc = self._spin(0, 255)
        self.plc_destio = self._spin(0, 65535)
        self.plc_dest_st = self._spin(0, 255)
        self.plc_unit = self._spin(0, 247)
        self.plc_serial_port = QLineEdit()
        self.plc_baud = self._spin(300, 115200)
        self.plc_parity = QComboBox()
        self.plc_parity.addItems(["N", "E", "O"])
        self.plc_stopbits = QComboBox()
        self.plc_stopbits.addItems(["1", "2"])
        self.plc_fins_net = self._spin(0, 255)
        self.plc_fins_node = self._spin(0, 255)
        self.plc_fins_unit = self._spin(0, 255)
        self.plc_timeout = self._dspin(0.5, 60.0, 1)
        self.plc_poll = self._dspin(0.1, 600.0, 2)
        self.plc_reconnect = QCheckBox("Auto reconnect")
        self.plc_driver.currentTextChanged.connect(self._on_driver_changed)
        f0, f1, f2 = _row("Driver", self.plc_driver), _row("IP address", self.plc_ip), _row("Port", self.plc_port)
        f3, f4, f5 = _row("Protokol (MC)", self.plc_protocol), _row("Tipe PLC", self.plc_plctype), _row("Network No", self.plc_network)
        f6, f7, f8 = _row("PC No", self.plc_pc), _row("Dest module I/O", self.plc_destio), _row("Dest module st.", self.plc_dest_st)
        f9, f10, f11 = _row("Unit ID (Modbus)", self.plc_unit), _row("Port serial (RTU)", self.plc_serial_port), _row("Baudrate", self.plc_baud)
        f12, f13, f14 = _row("Parity", self.plc_parity), _row("Stop bits", self.plc_stopbits), _row("FINS Network (DNA)", self.plc_fins_net)
        f15, f16, f17 = _row("FINS Node (DA1)", self.plc_fins_node), _row("FINS Unit (DA2)", self.plc_fins_unit), _row("Timeout (s)", self.plc_timeout)
        f18 = _row("Interval polling (s)", self.plc_poll)
        self._place(
            grid,
            [f0, f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f13, f14, f15, f16, f17, f18],
            span2=[self.plc_reconnect],
        )
        self._form.addWidget(card)

        # ----- db
        card, grid = self._new_card("Database MySQL / MariaDB")
        self.db_enabled = QCheckBox("Aktifkan sinkronisasi ke database")
        self.db_host = QLineEdit()
        self.db_port = self._spin(1, 65535)
        self.db_user = QLineEdit()
        self.db_pass = QLineEdit()
        self.db_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.db_name = QLineEdit()
        self.db_status_table = QLineEdit()
        self.db_transmit_table = QLineEdit()
        self.db_dev_name = QLineEdit()
        self.db_group_name = QLineEdit()
        self.db_write_from_db = QCheckBox("Proses perintah tulis dari tabel transmit")
        self.db_create = QCheckBox("Buat schema otomatis")
        self._place(grid, [
            _row("Host", self.db_host), _row("Port", self.db_port),
            _row("User", self.db_user), _row("Password", self.db_pass),
            _row("Nama database", self.db_name), _row("Tabel status (read)", self.db_status_table),
            _row("Tabel transmit (write)", self.db_transmit_table),
            _row("DEV_NAME", self.db_dev_name), _row("GROUP_NAME", self.db_group_name),
        ], span2=[self.db_enabled, self.db_write_from_db, self.db_create])
        self._form.addWidget(card)

        self._form.addStretch(1)

    # ------------------------------------------------------------- helpers
    def _new_card(self, title: str) -> tuple[QFrame, QGridLayout]:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        t = QLabel(title)
        t.setObjectName("h2")
        lay.addWidget(t)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        lay.addLayout(grid)
        return card, grid

    @staticmethod
    def _spin(lo: int, hi: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        return s

    @staticmethod
    def _dspin(lo: float, hi: float, dec: int) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSingleStep(0.1 if dec > 0 else 1)
        return s

    def _place(self, grid: QGridLayout, pairs: list[tuple[QWidget, QWidget]], span2: list[QWidget] | None = None, extra: tuple[QWidget, QWidget] | None = None) -> None:
        cols = 3
        for i, (lab, wid) in enumerate(pairs):
            wid.setMinimumWidth(150)
            r, c = divmod(i, cols)
            grid.addWidget(lab, r, c * 2)
            grid.addWidget(wid, r, c * 2 + 1)
        slots = len(pairs)
        if extra and extra[1] is not None:
            extra[1].setMinimumWidth(150)
            r, c = divmod(slots, cols)
            grid.addWidget(extra[0], r, c * 2)
            grid.addWidget(extra[1], r, c * 2 + 1)
            slots += 1
        row = (slots + cols - 1) // cols
        for w in span2 or []:
            grid.addWidget(w, row, 0, 1, cols * 2)
            row += 1
        # keep every value column the same width so the grid looks balanced
        for c in range(cols):
            grid.setColumnStretch(c * 2, 0)
            grid.setColumnStretch(c * 2 + 1, 1)

    # --------------------------------------------------------------- data
    def _on_driver_changed(self, driver: str) -> None:
        """Enable only the fields relevant to the selected PLC driver."""
        eth = driver != "modbus_rtu"
        mits = driver == "mitsubishi"
        modbus = driver in ("modbus_tcp", "modbus_rtu")
        fins = driver == "omron_fins"
        for w in (
            self.plc_ip, self.plc_port,
            self.plc_protocol, self.plc_plctype, self.plc_network, self.plc_pc,
            self.plc_destio, self.plc_dest_st,
            self.plc_unit, self.plc_serial_port, self.plc_baud, self.plc_parity, self.plc_stopbits,
            self.plc_fins_net, self.plc_fins_node, self.plc_fins_unit,
        ):
            w.setEnabled(False)
        self.plc_timeout.setEnabled(True)
        self.plc_poll.setEnabled(True)
        self.plc_reconnect.setEnabled(True)
        if eth:
            self.plc_ip.setEnabled(True)
            self.plc_port.setEnabled(True)
        if mits:
            for w in (
                self.plc_protocol, self.plc_plctype, self.plc_network, self.plc_pc,
                self.plc_destio, self.plc_dest_st,
            ):
                w.setEnabled(True)
        if modbus:
            self.plc_unit.setEnabled(True)
        if not eth:
            for w in (self.plc_serial_port, self.plc_baud, self.plc_parity, self.plc_stopbits):
                w.setEnabled(True)
        if fins:
            for w in (self.plc_fins_net, self.plc_fins_node, self.plc_fins_unit):
                w.setEnabled(True)

    def load_from_config(self, cfg: AppConfig | None) -> None:
        if cfg is None:
            return
        self.app_name.setText(cfg.name)
        self.log_level.setCurrentText(cfg.log_level.upper())

        p = cfg.plc
        self.plc_driver.setCurrentText(p.driver)
        self.plc_ip.setText(p.ip)
        self.plc_port.setValue(p.port)
        self.plc_protocol.setCurrentText(p.protocol)
        self.plc_plctype.setCurrentText(p.plctype)
        self.plc_network.setValue(p.network)
        self.plc_pc.setValue(p.pc)
        self.plc_destio.setValue(p.dest_moduleio)
        self.plc_dest_st.setValue(p.dest_modulesta)
        self.plc_unit.setValue(p.unit_id)
        self.plc_serial_port.setText(p.serial_port)
        self.plc_baud.setValue(p.baudrate)
        self.plc_parity.setCurrentText(p.parity)
        self.plc_stopbits.setCurrentText(str(p.stopbits))
        self.plc_fins_net.setValue(p.fins_network)
        self.plc_fins_node.setValue(p.fins_node)
        self.plc_fins_unit.setValue(p.fins_unit)
        self.plc_timeout.setValue(p.timeout_sec)
        self.plc_poll.setValue(p.poll_interval)
        self.plc_reconnect.setChecked(p.auto_reconnect)
        self._on_driver_changed(p.driver)

        d = cfg.database
        self.db_enabled.setChecked(d.enabled)
        self.db_host.setText(d.host)
        self.db_port.setValue(d.port)
        self.db_user.setText(d.user)
        self.db_pass.setText(d.password)
        self.db_name.setText(d.database)
        self.db_status_table.setText(d.status_table)
        self.db_transmit_table.setText(d.transmit_table)
        self.db_dev_name.setText(d.dev_name)
        self.db_group_name.setText(d.group_name)
        self.db_write_from_db.setChecked(d.write_from_db)
        self.db_create.setChecked(d.create_schema)

        self._tags = list(cfg.tags)

    def _collect(self) -> AppConfig:
        tags: list[TagConfig] = list(self._tags)
        return AppConfig(
            name=self.app_name.text() or "opc_mitsu",
            log_level=self.log_level.currentText(),
            plc=PlcConfig(
                driver=self.plc_driver.currentText(),
                ip=self.plc_ip.text().strip(),
                port=self.plc_port.value(),
                protocol=self.plc_protocol.currentText(),
                plctype=self.plc_plctype.currentText(),
                network=self.plc_network.value(),
                pc=self.plc_pc.value(),
                dest_moduleio=self.plc_destio.value(),
                dest_modulesta=self.plc_dest_st.value(),
                timeout_sec=self.plc_timeout.value(),
                poll_interval=self.plc_poll.value(),
                auto_reconnect=self.plc_reconnect.isChecked(),
                unit_id=self.plc_unit.value(),
                serial_port=self.plc_serial_port.text().strip() or "COM1",
                baudrate=self.plc_baud.value(),
                parity=self.plc_parity.currentText(),
                stopbits=int(self.plc_stopbits.currentText()),
                fins_network=self.plc_fins_net.value(),
                fins_node=self.plc_fins_node.value(),
                fins_unit=self.plc_fins_unit.value(),
            ),
            database=DatabaseConfig(
                enabled=self.db_enabled.isChecked(),
                host=self.db_host.text().strip(),
                port=self.db_port.value(),
                user=self.db_user.text().strip(),
                password=self.db_pass.text(),
                database=self.db_name.text().strip(),
                status_table=self.db_status_table.text().strip() or "t_reg_status",
                transmit_table=self.db_transmit_table.text().strip() or "t_transmit",
                dev_name=self.db_dev_name.text().strip() or "MITSUBISHI",
                group_name=self.db_group_name.text().strip() or "PLC1",
                write_from_db=self.db_write_from_db.isChecked(),
                create_schema=self.db_create.isChecked(),
            ),
            tags=tags,
        )

    # ----------------------------------------------------------- actions
    def _reload_from_file(self) -> None:
        try:
            cfg = load_config(self.config_path)
        except Exception as e:
            QMessageBox.critical(self, "Konfigurasi", f"Gagal memuat file: {e}")
            return
        self.load_from_config(cfg)

    def _save_only(self) -> None:
        cfg = self._collect()
        save_config(cfg, self.config_path)
        self.gateway.set_tags(cfg.tags)
        QMessageBox.information(self, "Konfigurasi", f"Konfigurasi tersimpan ke:\n{self.config_path}")

    def _save_and_restart(self) -> None:
        cfg = self._collect()
        try:
            save_config(cfg, self.config_path)
            from ..config import load_config

            valid = load_config(self.config_path)
        except Exception as e:
            QMessageBox.critical(self, "Konfigurasi", f"Konfigurasi tidak valid: {e}")
            return
        mb = QMessageBox(self)
        mb.setWindowTitle("Restart Gateway")
        mb.setText("Simpan konfigurasi dan restart gateway?")
        mb.setInformativeText("Koneksi PLC/DB akan dibuat ulang dengan pengaturan baru.")
        mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if mb.exec() != QMessageBox.StandardButton.Yes:
            return
        self.gateway.restart(valid)
        self.load_from_config(self.gateway.config)
        QMessageBox.information(self, "Gateway", "Gateway berhasil direstart dengan konfigurasi baru.")