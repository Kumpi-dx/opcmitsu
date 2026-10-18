from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
import time
from typing import Any

import pymysql
import pymysql.cursors

from .config import DatabaseConfig

log = logging.getLogger("opc_mitsu.db")

_BATCH_MAX = 500
_RETRY_INTERVAL = 5.0


def _ts_to_mysql(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class DatabaseManager:
    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._queue: queue.Queue[tuple] = queue.Queue(maxsize=config.queue_size)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._conn: pymysql.Connection | None = None
        self._connected = False
        self._last_error = ""
        self._lock = threading.Lock()
        self._db_ready = False
        self._stats = {"rows_written": 0, "rows_failed": 0, "dropped": 0, "reconnects": 0}

    # ---- connection ------------------------------------------------------
    def _get_connection(self) -> pymysql.Connection:
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
        )

    def connect(self) -> None:
        with self._lock:
            try:
                self._conn = self._get_connection()
                self._db_ready = False
                if self.config.create_schema:
                    self._ensure_schema(self._conn)
                else:
                    try:
                        self._conn.select_db(self.config.database)
                    except Exception:
                        pass
                self._db_ready = True
                self._connected = True
                self._last_error = ""
                log.info("Terhubung ke database MySQL %s:%s db=%s", self.config.host, self.config.port, self.config.database)
            except Exception as e:
                self._connected = False
                self._last_error = str(e)
                log.error("Gagal terhubung ke MySQL: %s", e)

    def disconnect(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._connected = False
            self._db_ready = False

    @property
    def connected(self) -> bool:
        return self._connected

    # ---- schema ----------------------------------------------------------
    def _table_names(self) -> tuple[str, str]:
        return self.config.status_table, self.config.transmit_table

    def _ensure_schema(self, conn: pymysql.Connection) -> None:
        db = self.config.database
        status_t, transmit_t = self._table_names()
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET latin1 COLLATE latin1_swedish_ci"
            )
        conn.select_db(db)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{db}`.`{status_t}` (
                    `CLIENT_HDL`   INT(11)      NOT NULL AUTO_INCREMENT,
                    `DEV_NAME`     VARCHAR(30)  NOT NULL DEFAULT 'MITSUBISHI',
                    `GROUP_NAME`   VARCHAR(30)  NOT NULL,
                    `TAG_NAME`     VARCHAR(50)  NOT NULL DEFAULT '',
                    `REG_VALUE`    VARCHAR(50)  DEFAULT NULL,
                    `TR_TIME`      DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    `CONNECT_STAT` CHAR(1)      DEFAULT '1',
                    PRIMARY KEY (`CLIENT_HDL`) USING BTREE,
                    UNIQUE KEY `uk_dev_tag` (`DEV_NAME`, `TAG_NAME`),
                    INDEX `idx_group` (`GROUP_NAME`)
                ) ENGINE=MyISAM DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci ROW_FORMAT=DYNAMIC
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{db}`.`{transmit_t}` (
                    `ID`        INT(11)          NOT NULL AUTO_INCREMENT,
                    `DEV_NAME`  VARCHAR(100)     DEFAULT NULL,
                    `REG_NAME`  VARCHAR(100)     DEFAULT NULL,
                    `REG_VALUE` VARCHAR(50)      DEFAULT NULL,
                    `TTL`       SMALLINT(5) UNSIGNED DEFAULT NULL,
                    `TR_TIME`   DATETIME         DEFAULT NULL,
                    PRIMARY KEY (`ID`)
                ) ENGINE=MyISAM DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci
                """
            )
            # migrations for pre-existing tables from the original system
            if not self._column_exists(cur, db, transmit_t, "ID"):
                try:
                    cur.execute(
                        f"ALTER TABLE `{db}`.`{transmit_t}` ADD COLUMN `ID` INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST"
                    )
                except Exception as e:
                    log.warning("Tambah kolom ID ke %s gagal: %s", transmit_t, e)
            if not self._index_exists(cur, db, status_t, "uk_dev_tag"):
                try:
                    cur.execute(
                        f"ALTER TABLE `{db}`.`{status_t}` ADD UNIQUE KEY `uk_dev_tag` (`DEV_NAME`, `TAG_NAME`)"
                    )
                except Exception as e:
                    log.warning("Tambah unique key ke %s gagal: %s", status_t, e)

    @staticmethod
    def _column_exists(cur, db: str, table: str, column: str) -> bool:
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s AND column_name=%s",
            (db, table, column),
        )
        row = cur.fetchone()
        return bool(row and row["n"])

    @staticmethod
    def _index_exists(cur, db: str, table: str, index: str) -> bool:
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.statistics "
            "WHERE table_schema=%s AND table_name=%s AND index_name=%s",
            (db, table, index),
        )
        row = cur.fetchone()
        return bool(row and row["n"])

    def test_connection(self) -> tuple[bool, str]:
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT VERSION() AS v")
                row = cur.fetchone()
            conn.close()
            version = row["v"] if row else "?"
            return True, f"Koneksi OK - MySQL {version}"
        except Exception as e:
            return False, f"Gagal: {e}"

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.connect()
        self._thread = threading.Thread(target=self._run, name="db-writer", daemon=True)
        self._thread.start()
        log.info("Writer database dimulai (status=%s, transmit=%s).", self.config.status_table, self.config.transmit_table)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self.flush()
        self.disconnect()

    # ---- status mirror (read) -------------------------------------------
    def enqueue_status(self, dev: str, group: str, tag: str, value_text: str | None, conn_stat: str, ts: float) -> None:
        if not self.config.enabled:
            return
        try:
            self._queue.put_nowait((dev, group, tag, value_text, conn_stat, ts))
        except queue.Full:
            with self._lock:
                self._stats["dropped"] += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._connected:
                time.sleep(0.5)
                if not self._stop.is_set():
                    self.connect()
                    with self._lock:
                        self._stats["reconnects"] += 1
                continue
            batch: list[tuple] = []
            deadline = time.time() + 1.0
            while len(batch) < _BATCH_MAX and time.time() < deadline:
                try:
                    item = self._queue.get(timeout=0.2)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue
                batch.append(item)
                if len(batch) >= _BATCH_MAX:
                    break
            if batch:
                self._write_batch(batch)

    def _write_batch(self, batch: list[tuple]) -> None:
        """Upsert the live register mirror (one row per DEV_NAME + TAG_NAME)."""
        db = self.config.database
        table = self.config.status_table
        rows = [
            (dev, group, tag, value_text, _ts_to_mysql(ts), conn_stat)
            for dev, group, tag, value_text, conn_stat, ts in batch
        ]
        sql = (
            f"INSERT INTO `{db}`.`{table}` "
            "(DEV_NAME, GROUP_NAME, TAG_NAME, REG_VALUE, TR_TIME, CONNECT_STAT) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE REG_VALUE=VALUES(REG_VALUE), TR_TIME=VALUES(TR_TIME), CONNECT_STAT=VALUES(CONNECT_STAT)"
        )
        try:
            with self._lock:
                conn = self._conn
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            with self._lock:
                self._stats["rows_written"] += len(rows)
        except Exception as e:
            with self._lock:
                self._stats["rows_failed"] += len(rows)
                self._connected = False
                self._last_error = str(e)
            log.error("Upsert status gagal (%d baris): %s", len(rows), e)

    def flush(self) -> None:
        if self._connected:
            batch = []
            while True:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            if batch:
                self._write_batch(batch)

    # ---- queries ---------------------------------------------------------
    def fetch_status(self, limit: int = 500) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        db = self.config.database
        table = self.config.status_table
        sql = (
            f"SELECT CLIENT_HDL, DEV_NAME, GROUP_NAME, TAG_NAME, REG_VALUE, TR_TIME, CONNECT_STAT "
            f"FROM `{db}`.`{table}` ORDER BY GROUP_NAME, TAG_NAME LIMIT %s"
        )
        try:
            with self._lock:
                conn = self._conn
            with conn.cursor() as cur:
                cur.execute(sql, (int(limit),))
                return list(cur.fetchall())
        except Exception as e:
            log.error("Query status gagal: %s", e)
            return []

    def fetch_transmit(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        db = self.config.database
        table = self.config.transmit_table
        sql = (
            f"SELECT ID, DEV_NAME, REG_NAME, REG_VALUE, TTL, TR_TIME "
            f"FROM `{db}`.`{table}` ORDER BY ID LIMIT %s"
        )
        try:
            with self._lock:
                conn = self._conn
            with conn.cursor() as cur:
                cur.execute(sql, (int(limit),))
                return list(cur.fetchall())
        except Exception as e:
            log.error("Query transmit gagal: %s", e)
            return []

    def delete_transmit(self, row_id: int) -> bool:
        if not self._connected:
            return False
        db = self.config.database
        table = self.config.transmit_table
        try:
            with self._lock:
                conn = self._conn
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM `{db}`.`{table}` WHERE ID=%s", (int(row_id),))
            return True
        except Exception as e:
            log.error("Hapus transmit id=%s gagal: %s", row_id, e)
            return False

    # ---- stats -----------------------------------------------------------
    def stats(self) -> dict[str, int]:
        with self._lock:
            d = dict(self._stats)
        d["queue_size"] = self._queue.qsize()
        d["last_error"] = self._last_error
        return d