"""Omron FINS TCP driver (Ethernet: NJ/NX, CP/CJ, CV series).

Tag address notation (case-insensitive):
  D100      DM word   (bit: D100.5 -> bit 5 of DM word 100)
  C100      CIO word  (bit: C100.0)
  W100      WR word   (bit: W100.3)
  H100      HR word   (bit: H100.7)
  A100      AR word   (bit: A100.2)

Bit tags may omit ".n" (defaults to bit 0). Word tags must not carry a bit suffix.
32-bit values span 2 consecutive words (high word first); ``swap_words: true``
swaps the word order. ``scale``/``offset`` work like the Mitsubishi driver.

Node address: on connect the client performs the FINS/TCP node address exchange;
``fins_node: 0`` (default) uses the node assigned by the PLC, a non-zero value
forces DA1. ``fins_network`` = DNA, ``fins_unit`` = DA2.
"""

from __future__ import annotations

import logging
import socket
import struct
from typing import Any

from .config import PlcConfig, TagConfig
from .modbus_client import decode_value, encode_value
from .plc_client import (
    TYPE_BIT,
    TYPE_INT32,
    TYPE_UINT32,
    TYPE_FLOAT32,
    BasePlcClient,
    PlcError,
    _apply_scale,
    _reverse_scale,
)

log = logging.getLogger("opc_mitsu.fins")

_DWORD_TYPES = {TYPE_INT32, TYPE_UINT32, TYPE_FLOAT32}

# area letter -> (bit area code, word area code)
_AREAS: dict[str, tuple[int, int]] = {
    "D": (0x02, 0x82),  # DM
    "C": (0x80, 0xB0),  # CIO
    "W": (0x91, 0xB1),  # WR
    "H": (0x82, 0xB2),  # HR
    "A": (0x90, 0xB3),  # AR
}

_MAX_WORD_RUN = 500
_RUN_GAP = 32

_END_CODES = {
    0x0000: "normal",
    0x0001: "service cancelled",
    0x1001: "local node not in network",
    0x1002: "token timeout",
    0x1003: "retries failed",
    0x1004: "too many frames sent",
    0x1005: "node address range error",
    0x1006: "node address duplication error",
    0x1101: "CPU unit ID error",
    0x1102: "detector of network error",
    0x1103: "unknown destination node",
    0x1104: "routing table error",
    0x1201: "destination node busy",
    0x1202: "response timeout",
    0x2002: "FINS TCP header error",
    0x2003: "FINS TCP body too long",
    0x2004: "FINS TCP command error",
    0x2101: "not readable",
    0x2102: "not writable",
    0x2103: "wrong size",
    0x2104: "address range exceeded",
    0x2201: "password error",
    0x2202: "parameter error",
    0x2203: "access denied",
    0x2204: "abort",
    0x2301: "fault error",
    0x2302: "maintenance error",
    0x2401: "no command",
    0x2402: "read only",
    0x2403: "protected",
    0x2404: "table missing",
    0x2405: "data missing",
    0x2406: "record missing",
    0x2407: "access control error",
}


def parse_address(tag: TagConfig) -> tuple[str, int, int]:
    """Return (area letter, word address, bit position) for a FINS tag."""
    text = (tag.address or "").strip().upper()
    letter = text[:1] if text else ""
    if letter not in _AREAS:
        raise PlcError(f"Alamat FINS tidak dikenal: '{tag.address}' (contoh: D100, C10.3, H5)")
    rest = text[1:]
    bit = 0
    has_bit = "." in rest
    if has_bit:
        word_s, _, bit_s = rest.partition(".")
        if not word_s.isdigit() or not bit_s.isdigit() or not (0 <= int(bit_s) <= 15):
            raise PlcError(f"Alamat FINS tidak valid: '{tag.address}' (contoh: D100, C10.3)")
        bit = int(bit_s)
    else:
        word_s = rest
    if not word_s.isdigit() or int(word_s) > 0xFFFF:
        raise PlcError(f"Alamat FINS tidak valid: '{tag.address}' (contoh: D100, C10.3)")
    if tag.type == TYPE_BIT and not has_bit:
        bit = 0
    if tag.type != TYPE_BIT and has_bit:
        raise PlcError(f"Tag word '{tag.name}' tidak boleh pakai '.bit': '{tag.address}'")
    return letter, int(word_s), bit


def _span(tag: TagConfig) -> int:
    return 2 if tag.type in _DWORD_TYPES else 1


class OmronFinsClient(BasePlcClient):
    def __init__(self, config: PlcConfig) -> None:
        super().__init__(config)
        self._sock: socket.socket | None = None
        self._server_node = 0
        self._client_node = 0

    # ---- lifecycle ------------------------------------------------------
    @property
    def connected(self) -> bool:
        return bool(self._sock is not None and self._sock.fileno() >= 0)

    def connect(self) -> None:
        with self._lock:
            self._open_locked()
            log.info(
                "Terhubung ke Omron FINS %s:%s (DNA=%d DA1=%d DA2=%d)",
                self.config.ip, self.config.port,
                self.config.fins_network, self._da1(), self.config.fins_unit,
            )

    def _da1(self) -> int:
        return int(self.config.fins_node) if self.config.fins_node else self._server_node

    def _open_locked(self) -> None:
        self._drop_locked()
        sock = socket.create_connection(
            (self.config.ip, int(self.config.port)), timeout=max(0.5, float(self.config.timeout_sec))
        )
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._negotiate_node()

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

    def disconnect(self) -> None:
        with self._lock:
            self._drop_locked()

    # ---- FINS/TCP framing -----------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise PlcError("Koneksi FINS terputus")
            buf += chunk
        return buf

    def _negotiate_node(self) -> None:
        """FINS/TCP node address exchange (command 1); assigns DA1/SA1."""
        request = b"FINS" + struct.pack(">III", 14, 1, 0) + struct.pack(">HHH", 0, 0, 0)
        assert self._sock is not None
        self._sock.sendall(request)
        header = self._recv_exact(16)  # FINS(4)+length(4)+cmd(4)+err(4)
        magic, length, cmd, err = struct.unpack(">4sIII", header)
        payload = self._recv_exact(length - 8) if length > 8 else b""
        if magic != b"FINS" or err != 0:
            raise PlcError("Negosiasi node FINS gagal (header/err tidak valid)")
        if cmd == 1 and len(payload) >= 6:
            self._client_node = struct.unpack(">H", payload[0:2])[0]
            self._server_node = struct.unpack(">H", payload[4:6])[0]
            log.info("FINS node: client=%d server=%d", self._client_node, self._server_node)
        else:
            log.warning("Respons node FINS tak terduga (cmd=%s), pakai fins_node", cmd)

    def _header(self) -> bytes:
        return bytes([
            0x80, 0x00, 0x02,                       # ICF, RSV, GCT
            int(self.config.fins_network) & 0xFF,   # DNA
            self._da1() & 0xFF,                     # DA1
            int(self.config.fins_unit) & 0xFF,      # DA2
            0x00,                                   # SNA
            self._client_node & 0xFF,               # SA1
            0x00,                                   # SA2
        ])

    def _command(self, mrc: int, src: int, body: bytes) -> bytes:
        """Send a FINS command; return the data portion of the response."""
        if self._sock is None:
            self._open_locked()
        fins = self._header() + bytes([mrc, src]) + body
        frame = struct.pack(">II", 2, 0) + fins  # cmd=2 (data), err=0
        assert self._sock is not None
        # length = jumlah byte setelah field length: cmd(4) + err(4) + fins frame
        self._sock.sendall(b"FINS" + struct.pack(">I", len(frame)) + frame)
        header = self._recv_exact(16)  # FINS(4)+length(4)+cmd(4)+err(4)
        magic, length, cmd, err = struct.unpack(">4sIII", header)
        if magic != b"FINS":
            raise PlcError("Header FINS/TCP tidak valid")
        payload = self._recv_exact(length - 8)
        if err != 0:
            raise PlcError(f"FINS/TCP error {err:#06x}")
        if cmd != 2:
            raise PlcError(f"Command FINS/TCP tak terduga: {cmd}")
        if len(payload) < 13:
            raise PlcError("Respons FINS tidak lengkap")
        # header FINS = 9 byte (ICF..SA2), lalu MRC(1) SRC(1) end(2) data
        end_code = struct.unpack(">H", payload[11:13])[0]
        if end_code != 0:
            raise PlcError(
                f"FINS end code {end_code:#06x}: {_END_CODES.get(end_code, 'error')}"
            )
        return payload[13:]

    # ---- read -----------------------------------------------------------
    def read_tags(self, tags: list[TagConfig]) -> dict[str, Any]:
        if not tags:
            return {}
        with self._lock:
            self._live_locked()
            results: dict[str, Any] = {}
            try:
                by_area: dict[str, list[tuple[int, int, TagConfig]]] = {}
                for t in tags:
                    letter, addr, bit = parse_address(t)
                    by_area.setdefault(letter, []).append((addr, bit, t))
                for letter, entries in by_area.items():
                    _, word_code = _AREAS[letter]
                    entries.sort(key=lambda e: e[0])
                    runs: list[tuple[int, int]] = []
                    for addr, _bit, t in entries:
                        span = _span(t)
                        if runs:
                            rs, rc = runs[-1]
                            if addr - (rs + rc) <= _RUN_GAP and addr + span - rs <= _MAX_WORD_RUN:
                                runs[-1] = (rs, max(rs + rc, addr + span) - rs)
                                continue
                        runs.append((addr, span))
                    cache: dict[int, int] = {}
                    for start, count in runs:
                        data = self._command(
                            0x01, 0x01,
                            bytes([word_code]) + struct.pack(">H", start) + bytes([0x00]) + struct.pack(">H", count),
                        )
                        for i in range(count):
                            cache[start + i] = struct.unpack(">H", data[2 * i:2 * i + 2])[0]
                    for addr, bit, t in entries:
                        s = _span(t)
                        raw_words = [cache.get(addr + i, 0) for i in range(s)]
                        if t.type == TYPE_BIT:
                            results[t.name] = bool((raw_words[0] >> bit) & 1)
                        else:
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
                letter, addr, bit = parse_address(tag)
                bit_code, word_code = _AREAS[letter]
                value = _reverse_scale(value, tag)
                if tag.type == TYPE_BIT:
                    body = (
                        bytes([bit_code]) + struct.pack(">H", addr) + bytes([bit])
                        + struct.pack(">H", 1) + struct.pack(">H", 0x0001 if bool(value) else 0x0000)
                    )
                else:
                    words = encode_value(tag, value)
                    body = (
                        bytes([word_code]) + struct.pack(">H", addr) + bytes([0x00])
                        + struct.pack(">H", len(words))
                        + struct.pack(">" + "H" * len(words), *words)
                    )
                self._command(0x01, 0x02, body)
                log.debug("Tulis %s = %s (%s%d.%d)", tag.name, value, letter, addr, bit)
            except Exception:
                self._drop_locked()
                raise
