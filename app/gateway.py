"""Gateway orchestrator: polls the PLC and mirrors values to MySQL."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from .config import AppConfig, TagConfig
from .database import DatabaseManager
from .plc_client import BasePlcClient, create_plc_client
from .store import QUALITY_BAD, QUALITY_GOOD, StatusStore, TagStore

log = logging.getLogger("opc_mitsu.gateway")

RECONNECT_WAIT = 3.0
READ_FAIL_THRESHOLD = 3  # consecutive read errors before declaring PLC disconnected


class Gateway:
    def __init__(self, config: AppConfig) -> None:
        self.store = TagStore()
        self.status = StatusStore()
        self.config: AppConfig | None = None
        self._plc: BasePlcClient | None = None
        self._db: DatabaseManager | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._write_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._write_status: dict[str, tuple[float, bool | None, str]] = {}
        self._write_lock = threading.Lock()
        self._last_connect_attempt = 0.0
        self._read_failures = 0
        self._start_time = 0.0
        self._apply_config(config)

    # ---- lifecycle -------------------------------------------------------
    def _apply_config(self, config: AppConfig) -> None:
        self.config = config
        self._tags_by_name = {t.name: t for t in self.config.tags}

    def start(self) -> None:
        cfg = self.config
        if cfg is None:
            raise RuntimeError("Config belum diatur.")
        self._start_time = time.time()
        self._stop.clear()
        self.store.clear()

        if cfg.database.enabled:
            self._db = DatabaseManager(cfg.database)
            self._db.start()
        else:
            self.status.set(db_connected=False, db_message="disabled")

        self._plc = create_plc_client(cfg.plc)
        self._connect_plc()

        self._thread = threading.Thread(target=self._run, name="plc-poller", daemon=True)
        self._thread.start()
        self.status.set(running=True)
        log.info("Gateway opc_mitsu dimulai (tags=%d, poll=%.1fs).", len(cfg.tags), cfg.plc.poll_interval)

    def restart(self, config: AppConfig | None = None) -> None:
        self.stop()
        if config is not None:
            self._apply_config(config)
        self.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=6)
            self._thread = None
        if self._plc:
            try:
                self._plc.disconnect()
            except Exception:
                pass
        if self._db:
            self._db.stop()
            self._db = None
        self.status.set(running=False, plc_connected=False, db_connected=False)
        log.info("Gateway dihentikan.")

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- PLC connection --------------------------------------------------
    def _connect_plc(self) -> None:
        now = time.time()
        if now - self._last_connect_attempt < RECONNECT_WAIT:
            return
        self._last_connect_attempt = now
        try:
            self._plc.connect()
            self.status.set(plc_connected=True, plc_message="Terhubung")
            log.info("Plc terhubung.")
        except Exception as e:
            self.status.set(plc_connected=False, plc_message=str(e))
            log.warning("Koneksi PLC gagal (%s). Coba lagi...", e)

    def _on_plc_write_request(self, tag_name: str, value: Any) -> None:
        self._set_write_status(tag_name, None, "dalam antrian")
        self._write_queue.put((tag_name, value))

    def write_tag_now(self, tag_name: str, value: Any) -> None:
        """Direct write triggered from the GUI."""
        self._on_plc_write_request(tag_name, value)

    def _set_write_status(self, name: str, ok: bool | None, msg: str) -> None:
        with self._write_lock:
            self._write_status[name] = (time.time(), ok, msg)

    def write_status(self, name: str) -> tuple[float, bool | None, str] | None:
        with self._write_lock:
            return self._write_status.get(name)

    # ---- dynamic tags ----------------------------------------------------
    def set_tags(self, tags: list[TagConfig]) -> None:
        """Update the tag list at runtime (used by the GUI config editor)."""
        if self.config is None:
            return
        self.config.tags = list(tags)
        self._tags_by_name = {t.name: t for t in tags}
        active = set(self._tags_by_name)
        for existing in self.store.names():
            if existing not in active:
                self.store.remove(existing)
        with self._write_lock:
            for existing in list(self._write_status):
                if existing not in active:
                    self._write_status.pop(existing, None)
        log.info("Daftar tag diperbarui (%d tag).", len(tags))

    def active_tags(self) -> list[TagConfig]:
        """The tag list owned by this gateway (the OPC-style address space)."""
        if self.config is None:
            return []
        return list(self.config.tags)

    # ---- poller loop -----------------------------------------------------
    def _run(self) -> None:
        interval = max(0.05, float(self.config.plc.poll_interval))
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self._process_writes()
            except Exception as e:
                log.error("Proses tulis gagal: %s", e)
            try:
                self._process_transmit()
            except Exception as e:
                log.error("Proses t_transmit gagal: %s", e)
            try:
                self._poll_once()
            except Exception as e:
                log.error("Polling error: %s", e)
            self._update_uptime()
            elapsed = time.time() - t0
            time.sleep(max(0.0, interval - elapsed))

    def _process_transmit(self) -> None:
        """Apply write commands queued in the database table t_transmit."""
        db_cfg = self.config.database
        if self._db is None or not db_cfg.enabled or not db_cfg.write_from_db:
            return
        if self._plc is None or not self._plc.connected:
            return
        for row in self._db.fetch_transmit(limit=50):
            row_id = row.get("ID")
            reg = str(row.get("REG_NAME") or "").strip()
            tag = self._resolve_tag(reg) if reg else None
            if tag is None:
                log.warning("t_transmit id=%s: register '%s' tidak dikenal, baris dihapus.", row_id, reg)
                if row_id is not None:
                    self._db.delete_transmit(row_id)
                continue
            if not tag.writable:
                log.warning("t_transmit id=%s: tag %s tidak writable, baris dihapus.", row_id, tag.name)
                if row_id is not None:
                    self._db.delete_transmit(row_id)
                continue
            try:
                value = _parse_reg_value(tag.type, row.get("REG_VALUE"))
            except Exception as e:
                log.warning("t_transmit id=%s: nilai '%s' tidak valid (%s), baris dihapus.", row_id, row.get("REG_VALUE"), e)
                if row_id is not None:
                    self._db.delete_transmit(row_id)
                continue
            try:
                self._plc.write_tag(tag, value)
                self._set_write_status(tag.name, True, "dari t_transmit")
                if row_id is not None:
                    self._db.delete_transmit(row_id)
                log.info("t_transmit id=%s -> %s = %s (OK).", row_id, tag.name, value)
            except Exception as e:
                self._set_write_status(tag.name, False, str(e))
                log.error("t_transmit id=%s tulis %s gagal: %s (baris dibiarkan untuk retry).", row_id, tag.name, e)

    def _resolve_tag(self, reg: str) -> TagConfig | None:
        key = reg.strip().lower()
        for tag in self.config.tags:
            if tag.name.lower() == key or tag.address.lower() == key:
                return tag
        return None

    def _process_writes(self) -> None:
        while not self._write_queue.empty():
            try:
                tag_name, value = self._write_queue.get_nowait()
            except queue.Empty:
                break
            tag = self._tags_by_name.get(tag_name)
            if tag is None or self._plc is None:
                continue
            if not tag.writable:
                log.warning("Tulis ditolak: tag %s tidak writable.", tag_name)
                self._set_write_status(tag_name, False, "tag tidak writable")
                continue
            try:
                self._plc.write_tag(tag, value)
                self._set_write_status(tag_name, True, "berhasil")
            except Exception as e:
                log.error("Tulis %s gagal: %s", tag_name, e)
                self._set_write_status(tag_name, False, str(e))
                self.store.set_quality(tag_name, QUALITY_BAD, str(e))

    def _poll_once(self) -> None:
        tags = self.active_tags()
        if not tags:
            return
        plc_cfg = self.config.plc
        if self._plc is None:
            return

        if not self._plc.connected:
            if plc_cfg.auto_reconnect:
                self._connect_plc()
            if not self._plc.connected:
                self._mark_all_bad("PLC tidak terhubung")
                return
            # freshly connected; fall through to read

        t0 = time.time()
        try:
            values = self._plc.read_tags(tags)
        except Exception as e:
            self._read_failures += 1
            polls_total = self.status.get().polls_total + 1
            polls_error = self.status.get().polls_error + 1
            if self._read_failures < READ_FAIL_THRESHOLD:
                # Transient hiccup: keep the socket and the last known values so the
                # status dot does not flicker red on a single missed poll.
                log.warning(
                    "Baca PLC gagal sementara (%d/%d): %s",
                    self._read_failures, READ_FAIL_THRESHOLD, e,
                )
                self.status.update(
                    {"plc_message": str(e), "polls_total": polls_total, "polls_error": polls_error}
                )
                return
            log.error("Baca PLC gagal %d kali berturut-turut, reconnect: %s", self._read_failures, e)
            self.status.update(
                {
                    "plc_connected": False,
                    "plc_message": str(e),
                    "polls_total": polls_total,
                    "polls_error": polls_error,
                }
            )
            self._mark_all_bad(str(e))
            if plc_cfg.auto_reconnect:
                self._plc.disconnect()
                self._last_connect_attempt = 0.0
                self._connect_plc()
            self._read_failures = 0
            return

        self._read_failures = 0
        now = time.time()
        self.status.update(
            {
                "plc_connected": True,
                "plc_message": "Terhubung",
                "reads_last": len(values),
                "last_poll_ms": round((time.time() - t0) * 1000, 1),
                "last_poll_time": now,
                "polls_total": self.status.get().polls_total + 1,
            }
        )

        for tag in tags:
            value = values.get(tag.name)
            if value is None:
                self.store.set_quality(tag.name, QUALITY_BAD, "tidak ada nilai")
                self._enqueue_status(tag, None, "0", now)
                continue
            self.store.update(tag.name, value, QUALITY_GOOD)
            self._enqueue_status(tag, value, "1", now)

    def _mark_all_bad(self, error: str) -> None:
        now = time.time()
        for tag in self.active_tags():
            self.store.set_quality(tag.name, QUALITY_BAD, error)
            self._enqueue_status(tag, None, "0", now)

    def _enqueue_status(self, tag: TagConfig, value: Any, conn_stat: str, now: float) -> None:
        if self._db is None:
            return
        db_cfg = self.config.database
        text = _format_reg_value(tag.type, value) if value is not None else None
        self._db.enqueue_status(db_cfg.dev_name, db_cfg.group_name, tag.name, text, conn_stat, now)

    def _update_uptime(self) -> None:
        self.status.set(gateway_uptime=time.time() - self._start_time)
        if self._db:
            st = self._db.stats()
            self.status.update(
                {
                    "db_connected": self._db.connected,
                    "db_message": "" if self._db.connected else self._db.stats()["last_error"],
                    "db_rows_written": st["rows_written"],
                    "db_queue_size": st["queue_size"],
                }
            )

    # ---- accessors -------------------------------------------------------
    def database_manager(self) -> DatabaseManager | None:
        return self._db

    @property
    def plc(self) -> BasePlcClient | None:
        return self._plc


def _format_reg_value(tag_type: str, value: Any) -> str:
    """Format a PLC value as a string for the t_reg_status.REG_VALUE column."""
    if tag_type == "bit" or isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def _parse_reg_value(tag_type: str, raw: Any) -> Any:
    """Parse a t_transmit.REG_VALUE string into the PLC-appropriate type."""
    text = "" if raw is None else str(raw).strip()
    if tag_type == "bit":
        return text.lower() in ("1", "on", "true", "yes", "ya")
    if tag_type in ("int16", "uint16", "int32", "uint32"):
        return int(float(text))
    return float(text)