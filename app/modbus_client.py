"""Modbus TCP/RTU driver (multi-brand: Schneider, Delta, LS, Inovance, Wago, ...).

Tag address notation (case-insensitive):
  C10    coil            (FC1 read / FC5 write, bit type)
  DI10   discrete input  (FC2 read-only, bit type)
  HR100  holding register (FC3 read / FC6|FC16 write, word types)
  IR100  input register  (FC4 read-only, word types)

32-bit values span 2 consecutive registers (high word first); ``swap_words: true``
on the tag swaps the word order. ``scale``/``offset`` work like the Mitsubishi driver.
"""

from __future__ import annotations

import logging
import socket
import struct
from typing import Any

from .config import PlcConfig, TagConfig
from .plc_client import (
    TYPE_BIT,
    TYPE_FLOAT32,
    TYPE_INT16,
    TYPE_INT32,
    TYPE_UINT16,
    TYPE_UINT32,
    BasePlcClient,
    PlcError,
    _apply_scale,
    _reverse_scale,
)

log = logging.getLogger("opc_mitsu.modbus")

_DWORD_TYPES = {TYPE_INT32, TYPE_UINT32, TYPE_FLOAT32}

_MAX_REG_RUN = 125  # spec limit per request (FC3/FC4)
_MAX_BIT_RUN = 200  # conservative limit per request (FC1/FC2)
_REG_GAP = 32       # merge tags whose register addresses are this close
_BIT_GAP = 16

# area prefix -> (is_bit, read_fc, write_fc) ; write_fc None = read-only
_AREAS: dict[str, tuple[bool, int, int | None]] = {
    "DI": (True, 2, None),
    "C": (True, 1, 5),
    "HR": (False, 3, 6),
    "IR": (False, 4, None),
}

_EXCEPTIONS = {
    1: "illegal function",
    2: "illegal data address",
    3: "illegal data value",
    4: "slave device failure",
    5: "acknowledge",
    6: "slave device busy",
    10: "gateway path unavailable",
    11: "gateway target device no response",
}


def parse_address(tag: TagConfig) -> tuple[bool, int]:
    """Return (is_bit, address) for a Modbus tag. Raises PlcError on bad notation."""
    text = (tag.address or "").strip().upper()
    for prefix in ("DI", "HR", "IR", "C"):
        if text.startswith(prefix):
            rest = text[len(prefix):]
            if not rest.isdigit():
                raise PlcError(f"Alamat Modbus tidak valid: '{tag.address}' (contoh: HR100, C10)")
            is_bit = _AREAS[prefix][0]
            if tag.type == TYPE_BIT and not is_bit:
                raise PlcError(f"Tag bit '{tag.name}' butuh alamat C/DI, bukan {prefix}")
            if tag.type != TYPE_BIT and is_bit:
                raise PlcError(f"Tag '{tag.name}' (tipe {tag.type}) butuh alamat HR/IR, bukan {prefix}")
            return is_bit, int(rest)
    raise PlcError(f"Alamat Modbus tidak dikenal: '{tag.address}' (contoh: HR100, DI10, C5, IR20)")


def _area_prefix(tag: TagConfig) -> str:
    text = (tag.address or "").strip().upper()
    for prefix in ("DI", "HR", "IR", "C"):
        if text.startswith(prefix):
            return prefix
    raise PlcError(f"Alamat Modbus tidak dikenal: '{tag.address}'")


def _tag_addr(tag: TagConfig) -> int:
    text = (tag.address or "").strip().upper()
    for prefix in ("DI", "HR", "IR", "C"):
        if text.startswith(prefix):
            return int(text[len(prefix):])
    raise PlcError(f"Alamat Modbus tidak dikenal: '{tag.address}'")


def decode_value(tag: TagConfig, words: list[int]) -> Any:
    """Decode 1-2 raw 16-bit registers into the tag's engineering type (pre-scale)."""
    w0 = words[0] & 0xFFFF
    if tag.type == TYPE_INT16:
        return w0 - 0x10000 if w0 >= 0x8000 else w0
    if tag.type == TYPE_UINT16:
        return w0
    if len(words) < 2:
        raise PlcError(f"Tag '{tag.name}' ({tag.type}) butuh 2 register")
    w1 = words[1] & 0xFFFF
    if tag.swap_words:
        w0, w1 = w1, w0
    raw = (w0 << 16) | w1
    if tag.type == TYPE_UINT32:
        return raw
    if tag.type == TYPE_INT32:
        return raw - 0x100000000 if raw >= 0x80000000 else raw
    if tag.type == TYPE_FLOAT32:
        return struct.unpack(">f", struct.pack(">I", raw))[0]
    raise PlcError(f"Tipe tag tidak didukung: {tag.type}")


def encode_value(tag: TagConfig, value: Any) -> list[int]:
    """Encode an engineering value into raw 16-bit registers (post-scale)."""
    if tag.type == TYPE_INT16:
        return [int(value) & 0xFFFF]
    if tag.type == TYPE_UINT16:
        return [int(value) & 0xFFFF]
    if tag.type == TYPE_INT32 or tag.type == TYPE_UINT32:
        raw = int(value) & 0xFFFFFFFF
    elif tag.type == TYPE_FLOAT32:
        raw = struct.unpack(">I", struct.pack(">f", float(value)))[0]
    else:
        raise PlcError(f"Tipe tag tidak didukung: {tag.type}")
    w0, w1 = (raw >> 16) & 0xFFFF, raw & 0xFFFF
    if tag.swap_words:
        w0, w1 = w1, w0
    return [w0, w1]


def _span(tag: TagConfig) -> int:
    return 2 if tag.type in _DWORD_TYPES else 1


def _runs(addrs: list[int], max_span: int, max_len: int, gap: int) -> list[tuple[int, int]]:
    """Merge sorted start addresses into (start, count) runs."""
    runs: list[tuple[int, int]] = []
    for a in addrs:
        if runs:
            start, count = runs[-1]
            end = start + count
            new_end = max(end, a + max_span)
            if new_end - start <= max_len and a - end <= gap:
                runs[-1] = (start, new_end - start)
                continue
        runs.append((a, max_span))
    return runs


class ModbusClient(BasePlcClient):
    def __init__(self, config: PlcConfig) -> None:
        super().__init__(config)

    def _exchange(self, pdu: bytes) -> bytes:
        """Request/response at the PDU level (no address/unit). Returns response PDU."""
        raise NotImplementedError

    # ---- lifecycle ------------------------------------------------------
    def connect(self) -> None:
        with self._lock:
            self._open_locked()
            log.info("Terhubung ke Modbus %s", self._describe())

    def _describe(self) -> str:
        raise NotImplementedError

    def _open_locked(self) -> None:
        raise NotImplementedError

    def _drop_locked(self) -> None:
        raise NotImplementedError

    def _live_locked(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        with self._lock:
            self._drop_locked()

    # ---- read -----------------------------------------------------------
    def read_tags(self, tags: list[TagConfig]) -> dict[str, Any]:
        if not tags:
            return {}
        with self._lock:
            self._live_locked()
            results: dict[str, Any] = {}
            try:
                for t in tags:
                    parse_address(t)  # validasi notasi alamat vs tipe tag
                bit_tags = [t for t in tags if t.type == TYPE_BIT]
                reg_tags = [t for t in tags if t.type != TYPE_BIT]

                # coils / discrete inputs: one bit address per tag, merged into runs
                by_prefix: dict[str, list[TagConfig]] = {}
                for t in bit_tags:
                    by_prefix.setdefault(_area_prefix(t), []).append(t)
                for prefix, group in by_prefix.items():
                    is_bit, read_fc, _ = _AREAS[prefix]
                    if not is_bit:
                        raise PlcError(f"Tag bit '{group[0].name}' butuh alamat C/DI, bukan {prefix}")
                    group.sort(key=_tag_addr)
                    addrs = [_tag_addr(t) for t in group]
                    for start, count in _runs(addrs, 1, _MAX_BIT_RUN, _BIT_GAP):
                        data = self._exchange(bytes([read_fc]) + struct.pack(">HH", start, count))
                        bits = _bits_from_bytes(data[2:2 + (count + 7) // 8])
                        for t in group:
                            a = _tag_addr(t)
                            if start <= a < start + count:
                                results[t.name] = bits[a - start]

                # holding / input registers
                by_prefix = {}
                for t in reg_tags:
                    by_prefix.setdefault(_area_prefix(t), []).append(t)
                for prefix, group in by_prefix.items():
                    _, read_fc, _ = _AREAS[prefix]
                    group.sort(key=_tag_addr)
                    # each tag owns [addr, addr+span)
                    entries: list[tuple[int, int]] = [(_tag_addr(t), _span(t)) for t in group]
                    for start, count in _merge_spans(entries, _MAX_REG_RUN, _REG_GAP):
                        data = self._exchange(bytes([read_fc]) + struct.pack(">HH", start, count))
                        words = list(struct.unpack(">" + "H" * (count), data[2:2 + 2 * count]))
                        for t in group:
                            a = _tag_addr(t)
                            s = _span(t)
                            if start <= a and a + s <= start + count:
                                raw_words = words[a - start: a - start + s]
                                results[t.name] = _apply_scale(decode_value(t, raw_words), t)
            except Exception:
                self._drop_locked()
                raise
            return results

    # ---- write ----------------------------------------------------------
    def write_tag(self, tag: TagConfig, value: Any) -> None:
        with self._lock:
            self._live_locked()
            try:
                parse_address(tag)  # validasi notasi alamat vs tipe tag
                prefix = _area_prefix(tag)
                _, read_fc, write_fc = _AREAS[prefix]
                addr = _tag_addr(tag)
                value = _reverse_scale(value, tag)
                if write_fc is None:
                    raise PlcError(f"Area {prefix} hanya bisa dibaca (tag {tag.name})")
                if tag.type == TYPE_BIT:
                    pdu = bytes([5]) + struct.pack(">HH", addr, 0xFF00 if bool(value) else 0x0000)
                else:
                    words = encode_value(tag, value)
                    if len(words) == 1:
                        pdu = bytes([6]) + struct.pack(">HH", addr, words[0])
                    else:
                        payload = struct.pack(">" + "H" * len(words), *words)
                        pdu = bytes([16]) + struct.pack(">HHB", addr, len(words), len(payload)) + payload
                self._exchange(pdu)
                log.debug("Tulis %s = %s (%s%d)", tag.name, value, prefix, addr)
            except Exception:
                self._drop_locked()
                raise

    # ---- helpers --------------------------------------------------------
    @staticmethod
    def _check_response(pdu: bytes, request_fc: int) -> bytes:
        if not pdu:
            raise PlcError("Respons Modbus kosong")
        fc = pdu[0]
        if fc & 0x80:
            code = pdu[1] if len(pdu) > 1 else 0
            raise PlcError(f"Exception Modbus FC{request_fc}: {_EXCEPTIONS.get(code, f'code {code}')}")
        if fc != request_fc:
            raise PlcError(f"Respons Modbus tak terduga: FC{fc} (diminta FC{request_fc})")
        return pdu


def _bits_from_bytes(data: bytes) -> list[bool]:
    bits: list[bool] = []
    for b in data:
        for i in range(8):
            bits.append(bool(b & (1 << i)))
    return bits


def _merge_spans(entries: list[tuple[int, int]], max_len: int, gap: int) -> list[tuple[int, int]]:
    """Merge (addr, span) entries into (start, total_count) runs."""
    runs: list[tuple[int, int]] = []
    for addr, span in sorted(entries):
        if runs:
            start, count = runs[-1]
            end = start + count
            new_end = max(end, addr + span)
            if new_end - start <= max_len and addr - end <= gap:
                runs[-1] = (start, new_end - start)
                continue
        runs.append((addr, span))
    return runs


class ModbusTcpClient(ModbusClient):
    def __init__(self, config: PlcConfig) -> None:
        super().__init__(config)
        self._sock: socket.socket | None = None
        self._tid = 0

    def _describe(self) -> str:
        return f"TCP {self.config.ip}:{self.config.port} (unit {self.config.unit_id})"

    def _open_locked(self) -> None:
        self._drop_locked()
        sock = socket.create_connection(
            (self.config.ip, int(self.config.port)), timeout=max(0.5, float(self.config.timeout_sec))
        )
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock

    def _drop_locked(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _live_locked(self) -> None:
        if self._sock is None:
            self._open_locked()

    @property
    def connected(self) -> bool:
        return bool(self._sock is not None and self._sock.fileno() >= 0)

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise PlcError("Koneksi Modbus terputus")
            buf += chunk
        return buf

    def _exchange(self, pdu: bytes) -> bytes:
        if self._sock is None:
            self._open_locked()
        self._tid = (self._tid + 1) & 0xFFFF
        unit = int(self.config.unit_id) & 0xFF
        mbap = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, unit)
        assert self._sock is not None
        self._sock.sendall(mbap + pdu)
        header = self._recv_exact(7)
        tid, _proto, length, runit = struct.unpack(">HHHB", header)
        body = self._recv_exact(length - 1)
        if runit != unit:
            raise PlcError(f"Unit id tak terduka: {runit} (diminta {unit})")
        if tid != self._tid:
            log.warning("Transaction id tidak cocok: %s vs %s", tid, self._tid)
        return self._check_response(body, pdu[0])


class ModbusRtuClient(ModbusClient):
    def __init__(self, config: PlcConfig) -> None:
        super().__init__(config)
        self._serial: Any = None

    def _describe(self) -> str:
        c = self.config
        return f"RTU {c.serial_port} {c.baudrate} {c.parity}{c.stopbits} (unit {c.unit_id})"

    def _open_locked(self) -> None:
        self._drop_locked()
        try:
            import serial  # pyserial (opsional, hanya untuk driver modbus_rtu)
        except ImportError as e:
            raise PlcError("Driver modbus_rtu butuh pyserial: pip install pyserial") from e
        self._serial = serial.Serial(
            port=self.config.serial_port,
            baudrate=int(self.config.baudrate),
            parity=self.config.parity,
            stopbits=int(self.config.stopbits),
            bytesize=8,
            timeout=max(0.2, float(self.config.timeout_sec)),
            write_timeout=max(0.2, float(self.config.timeout_sec)),
        )

    def _drop_locked(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def _live_locked(self) -> None:
        if self._serial is None or not getattr(self._serial, "is_open", True):
            self._open_locked()

    @property
    def connected(self) -> bool:
        return bool(self._serial is not None and getattr(self._serial, "is_open", True))

    def _exchange(self, pdu: bytes) -> bytes:
        if self._serial is None:
            self._open_locked()
        ser = self._serial
        addr = int(self.config.unit_id) & 0xFF
        frame = bytes([addr]) + pdu + struct.pack("<H", crc16(bytes([addr]) + pdu))
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        ser.write(frame)
        echo = ser.read(1)  # slave address echo
        if not echo:
            raise PlcError("Timeout respons Modbus RTU")
        if echo[0] != addr:
            raise PlcError(f"Address echo Modbus RTU tak terduga: {echo[0]} (diminta {addr})")
        fc = ser.read(1)
        if not fc:
            raise PlcError("Timeout respons Modbus RTU")
        fc_val = fc[0]
        if fc_val & 0x80:
            code = ser.read(1)
            ser.read(2)  # CRC
            raise PlcError(
                f"Exception Modbus RTU FC{pdu[0]}: {_EXCEPTIONS.get(code[0] if code else 0, '?')}"
            )
        if fc_val in (1, 2, 3, 4):
            bc = ser.read(1)
            if not bc:
                raise PlcError("Respons Modbus RTU tidak lengkap")
            data = ser.read(bc[0])
            body = bytes([fc_val, bc[0]]) + data
        elif fc_val in (5, 6, 15, 16):
            data = ser.read(4)
            body = bytes([fc_val]) + data
        else:
            raise PlcError(f"FC Modbus RTU tak terduga: FC{fc_val}")
        crc = ser.read(2)
        if len(crc) == 2 and struct.unpack("<H", crc)[0] != crc16(bytes([addr]) + body):
            log.warning("CRC Modbus RTU tidak cocok (diabaikan)")
        return self._check_response(body, pdu[0])


def crc16(data: bytes) -> int:
    """Modbus CRC16 (poly 0xA001), returns little-endian int (lo byte first)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc
