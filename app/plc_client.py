"""PLC communication using pymcprotocol (MELSEC MC protocol)."""

from __future__ import annotations

import logging
import struct
import threading
import time
from typing import Any

from pymcprotocol import Type3E

from .config import PlcConfig, TagConfig

log = logging.getLogger("opc_mitsu.plc")

TYPE_BIT = "bit"
TYPE_INT16 = "int16"
TYPE_UINT16 = "uint16"
TYPE_INT32 = "int32"
TYPE_UINT32 = "uint32"
TYPE_FLOAT32 = "float32"

_WORD_TYPES = {TYPE_INT16, TYPE_UINT16}
_DWORD_TYPES = {TYPE_INT32, TYPE_UINT32, TYPE_FLOAT32}


class PlcError(Exception):
    pass


def _apply_scale(raw: Any, tag: TagConfig) -> Any:
    if isinstance(raw, (int, float)) and (tag.scale != 1.0 or tag.offset != 0.0):
        return raw * tag.scale + tag.offset
    return raw


def _reverse_scale(value: Any, tag: TagConfig) -> Any:
    if isinstance(value, (int, float)):
        if tag.scale == 0.0:
            tag.scale = 1.0
        return (value - tag.offset) / tag.scale
    return value


class BasePlcClient:
    def __init__(self, config: PlcConfig) -> None:
        self.config = config
        self._lock = threading.Lock()

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    @property
    def connected(self) -> bool:
        raise NotImplementedError

    def read_tags(self, tags: list[TagConfig]) -> dict[str, Any]:
        raise NotImplementedError

    def write_tag(self, tag: TagConfig, value: Any) -> None:
        raise NotImplementedError


class MitsubishiPlcClient(BasePlcClient):
    def __init__(self, config: PlcConfig) -> None:
        super().__init__(config)
        self._plc: Type3E | None = None
        self._last_io = 0.0
        # The Q-series Ethernet module (E71) closes an MC connection that stays
        # quiet for a couple of cycles, so a socket is opened fresh whenever the
        # link has been unused for longer than this (writes inside the same poll
        # cycle reuse the existing socket).
        self._max_idle = 0.4

    @property
    def connected(self) -> bool:
        return bool(self._plc is not None and self._plc._is_connected)

    def _build_plc(self) -> Type3E:
        plc = Type3E(plctype=self.config.plctype)
        plc.setaccessopt(
            commtype=self.config.protocol,
            network=self.config.network if self.config.network else None,
            pc=self.config.pc if self.config.pc else None,
            dest_moduleio=self.config.dest_moduleio if self.config.dest_moduleio else None,
            dest_modulesta=self.config.dest_modulesta if self.config.dest_modulesta else None,
        )
        return plc

    def connect(self) -> None:
        with self._lock:
            self._open_locked()
            log.info("Terhubung ke PLC Mitsubishi %s:%s (%s)", self.config.ip, self.config.port, self.config.protocol)

    def _open_locked(self) -> Type3E:
        """(Re)open a fresh socket. Caller must hold ``self._lock``."""
        if self._plc is not None:
            try:
                self._plc.close()
            except Exception:
                pass
        plc = self._build_plc()
        plc.soc_timeout = max(1.0, float(self.config.timeout_sec))
        plc.connect(self.config.ip, self.config.port)
        self._plc = plc
        self._last_io = time.time()
        return plc

    def _drop_locked(self) -> None:
        if self._plc is not None:
            try:
                self._plc.close()
            except Exception:
                pass
        self._plc = None

    def _live_locked(self) -> Type3E:
        """Return a usable socket, reconnecting if idle/stale. Holds the lock."""
        plc = self._plc
        if plc is None or not plc._is_connected or (time.time() - self._last_io) > self._max_idle:
            plc = self._open_locked()
        return plc

    def disconnect(self) -> None:
        with self._lock:
            self._drop_locked()

    def read_tags(self, tags: list[TagConfig]) -> dict[str, Any]:
        if not tags:
            return {}
        with self._lock:
            plc = self._live_locked()
            results: dict[str, Any] = {}
            try:
                word_tags: list[TagConfig] = [t for t in tags if t.type in _WORD_TYPES]
                dword_tags: list[TagConfig] = [t for t in tags if t.type in _DWORD_TYPES]
                bit_tags: list[TagConfig] = [t for t in tags if t.type == TYPE_BIT]

                if word_tags or dword_tags:
                    word_devices = [t.address for t in word_tags]
                    dword_devices = [t.address for t in dword_tags]
                    word_values, dword_values = plc.randomread(word_devices, dword_devices)

                    for tag, raw in zip(word_tags, word_values):
                        results[tag.name] = _apply_scale(_to_word(tag, raw), tag)
                    for tag, raw in zip(dword_tags, dword_values):
                        results[tag.name] = _apply_scale(_to_dword(tag, raw), tag)

                for tag in bit_tags:
                    bits = plc.batchread_bitunits(tag.address, 1)
                    results[tag.name] = bool(bits[0])
            except Exception:
                self._drop_locked()
                raise
            self._last_io = time.time()
            return results

    def write_tag(self, tag: TagConfig, value: Any) -> None:
        with self._lock:
            plc = self._live_locked()
            try:
                value = _reverse_scale(value, tag)
                if tag.type == TYPE_BIT:
                    bits = [1 if bool(value) else 0]
                    plc.batchwrite_bitunits(tag.address, bits)
                elif tag.type in _WORD_TYPES:
                    raw = int(value) & 0xFFFF
                    if raw >= 0x8000:
                        raw -= 0x10000
                    plc.batchwrite_wordunits(tag.address, [raw])
                elif tag.type in _DWORD_TYPES:
                    encoded = _encode_dword(tag, value)
                    plc.randomwrite([], [], [tag.address], [encoded])
                else:
                    raise PlcError(f"Tipe tag tidak didukung: {tag.type}")
            except PlcError:
                raise
            except Exception:
                self._drop_locked()
                raise
            self._last_io = time.time()
            log.debug("Tulis %s = %s ke %s", tag.name, value, tag.address)


def _to_word(tag: TagConfig, raw: int) -> Any:
    if tag.type == TYPE_UINT16:
        return raw & 0xFFFF
    return raw  # int16 sudah signed


def _to_dword(tag: TagConfig, raw: int) -> Any:
    raw_unsigned = raw & 0xFFFFFFFF
    if tag.type == TYPE_UINT32:
        return raw_unsigned
    if tag.type == TYPE_FLOAT32:
        data = struct.pack("<I", raw_unsigned)
        if tag.swap_words:
            data = data[2:] + data[:2]
        return struct.unpack("<f", data)[0]
    if tag.type == TYPE_INT32:
        if raw_unsigned >= 0x80000000:
            raw_unsigned -= 0x100000000
        return raw_unsigned
    return raw_unsigned


def _encode_dword(tag: TagConfig, value: Any) -> int:
    if tag.type == TYPE_UINT32:
        return int(value) & 0xFFFFFFFF
    if tag.type == TYPE_FLOAT32:
        data = struct.pack("<f", float(value))
        if tag.swap_words:
            data = data[2:] + data[:2]
        return struct.unpack("<i", data)[0]
    if tag.type == TYPE_INT32:
        return int(value)
    return int(value) & 0xFFFFFFFF


def create_plc_client(config: PlcConfig) -> BasePlcClient:
    driver = (config.driver or "mitsubishi").lower()
    if driver == "mitsubishi":
        return MitsubishiPlcClient(config)
    if driver == "modbus_tcp":
        from .modbus_client import ModbusTcpClient

        return ModbusTcpClient(config)
    if driver == "modbus_rtu":
        from .modbus_client import ModbusRtuClient

        return ModbusRtuClient(config)
    if driver == "omron_fins":
        from .fins_client import OmronFinsClient

        return OmronFinsClient(config)
    raise PlcError(f"Driver PLC tidak dikenal: {config.driver}")