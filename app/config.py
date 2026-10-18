from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

TAG_TYPES = ("bit", "int16", "uint16", "int32", "uint32", "float32")
PLC_TYPES = ("Q", "L", "QnA", "iQ-L", "iQ-R")
PROTOCOLS = ("binary", "ascii")
DRIVERS = ("mitsubishi", "modbus_tcp", "modbus_rtu", "omron_fins")
PARITIES = ("N", "E", "O")


@dataclass
class PlcConfig:
    driver: str = "mitsubishi"
    ip: str = "192.168.1.10"
    port: int = 5000
    protocol: str = "binary"
    plctype: str = "Q"
    network: int = 0
    pc: int = 255
    dest_moduleio: int = 1023
    dest_modulesta: int = 0
    timeout_sec: float = 2.0
    poll_interval: float = 1.0
    auto_reconnect: bool = True
    # Modbus (TCP & RTU)
    unit_id: int = 1
    # Modbus RTU (serial)
    serial_port: str = "COM1"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    # Omron FINS (DNA/DA1/DA2)
    fins_network: int = 0
    fins_node: int = 0
    fins_unit: int = 0


@dataclass
class DatabaseConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "opc_mitsu"
    status_table: str = "t_reg_status"
    transmit_table: str = "t_transmit"
    dev_name: str = "MITSUBISHI"
    group_name: str = "PLC1"
    write_from_db: bool = True
    create_schema: bool = True
    queue_size: int = 20000


@dataclass
class TagConfig:
    name: str
    address: str
    type: str = "int16"
    writable: bool = False
    scale: float = 1.0
    offset: float = 0.0
    swap_words: bool = False
    description: str = ""


@dataclass
class AppConfig:
    name: str = "opc_mitsu"
    log_level: str = "INFO"
    log_dir: str = "logs"
    plc: PlcConfig = field(default_factory=PlcConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    tags: list[TagConfig] = field(default_factory=list)


def _clean_keys(d: Any) -> Any:
    if isinstance(d, dict):
        return {k.replace("-", "_"): _clean_keys(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_clean_keys(i) for i in d]
    return d


def _build(obj: Any, data: dict | None) -> Any:
    if not data or not isinstance(data, dict):
        return obj
    for key, value in data.items():
        if hasattr(obj, key):
            setattr(obj, key, value)
    return obj


def _value_cast(converter, value):
    """Best effort cast used when YAML gives wrong types."""
    try:
        return converter(value)
    except (TypeError, ValueError):
        return value  # keep fallback for empty string passwords etc.


def _rectify(cfg: AppConfig) -> AppConfig:
    p, d = cfg.plc, cfg.database
    p.driver = p.driver if p.driver in DRIVERS else "mitsubishi"
    p.protocol = p.protocol if p.protocol in PROTOCOLS else "binary"
    p.plctype = p.plctype if p.plctype in PLC_TYPES else "Q"
    p.port = _value_cast(int, p.port)
    p.network = _value_cast(int, p.network)
    p.pc = _value_cast(int, p.pc)
    p.dest_moduleio = _value_cast(int, p.dest_moduleio)
    p.dest_modulesta = _value_cast(int, p.dest_modulesta)
    p.timeout_sec = _value_cast(float, p.timeout_sec)
    p.poll_interval = max(0.1, _value_cast(float, p.poll_interval))
    p.auto_reconnect = _value_cast(bool, p.auto_reconnect)
    p.unit_id = min(247, max(0, _value_cast(int, p.unit_id)))
    p.serial_port = str(p.serial_port or "COM1")
    p.baudrate = max(300, _value_cast(int, p.baudrate))
    p.parity = p.parity if p.parity in PARITIES else "N"
    p.stopbits = _value_cast(int, p.stopbits)
    if p.stopbits not in (1, 2):
        p.stopbits = 1
    p.fins_network = min(255, max(0, _value_cast(int, p.fins_network)))
    p.fins_node = min(255, max(0, _value_cast(int, p.fins_node)))
    p.fins_unit = min(255, max(0, _value_cast(int, p.fins_unit)))

    d.enabled = _value_cast(bool, d.enabled)
    d.port = _value_cast(int, d.port)
    d.create_schema = _value_cast(bool, d.create_schema)
    d.write_from_db = _value_cast(bool, d.write_from_db)
    d.status_table = str(d.status_table or "t_reg_status")
    d.transmit_table = str(d.transmit_table or "t_transmit")
    d.queue_size = max(100, _value_cast(int, d.queue_size))

    cleaned_tags: list[TagConfig] = []
    seen: set[str] = set()
    for i, t in enumerate(cfg.tags):
        if not isinstance(t, TagConfig):
            continue
        t.name = str(t.name or f"tag_{(int(i or 0) + 1):d}").strip()
        t.address = str(t.address or "").strip().upper()
        t.type = t.type if t.type in TAG_TYPES else "int16"
        t.writable = _value_cast(bool, t.writable)
        t.scale = _value_cast(float, t.scale)
        t.offset = _value_cast(float, t.offset)
        if not t.name or not t.address:
            continue
        if t.name in seen:
            continue
        seen.add(t.name)
        cleaned_tags.append(t)
    cfg.tags = cleaned_tags
    return cfg


def default_config() -> AppConfig:
    return _rectify(AppConfig(tags=[TagConfig(name="Tag1", address="D100", type="int16")]))


def load_config(path: str | os.PathLike) -> AppConfig:
    path = str(path)
    data: dict = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data = _clean_keys(data)

    cfg = AppConfig()
    _build(cfg, {"name": cfg.name, "log_level": cfg.log_level, "log_dir": cfg.log_dir})
    _build(cfg, data.get("app") or {})

    cfg.plc = _build(PlcConfig(), data.get("plc") or {})
    cfg.database = _build(DatabaseConfig(), data.get("database") or {})

    tags = []
    for item in data.get("tags") or []:
        if isinstance(item, dict):
            base = dict(name="", address="", type="int16")
            base.update(item)
            tags.append(_build(TagConfig(**{k: v for k, v in base.items() if k in TagConfig.__dataclass_fields__}), {}))
    cfg.tags = tags
    return _rectify(cfg)


def save_config(cfg: AppConfig, path: str | os.PathLike) -> None:
    path = str(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    data = {
        "app": {"name": cfg.name, "log_level": cfg.log_level, "log_dir": cfg.log_dir},
        "plc": {
            "driver": cfg.plc.driver,
            "ip": cfg.plc.ip,
            "port": cfg.plc.port,
            "protocol": cfg.plc.protocol,
            "plctype": cfg.plc.plctype,
            "network": cfg.plc.network,
            "pc": cfg.plc.pc,
            "dest_moduleio": cfg.plc.dest_moduleio,
            "dest_modulesta": cfg.plc.dest_modulesta,
            "timeout_sec": cfg.plc.timeout_sec,
            "poll_interval": cfg.plc.poll_interval,
            "auto_reconnect": cfg.plc.auto_reconnect,
            "unit_id": cfg.plc.unit_id,
            "serial_port": cfg.plc.serial_port,
            "baudrate": cfg.plc.baudrate,
            "parity": cfg.plc.parity,
            "stopbits": cfg.plc.stopbits,
            "fins_network": cfg.plc.fins_network,
            "fins_node": cfg.plc.fins_node,
            "fins_unit": cfg.plc.fins_unit,
        },
        "database": {
            "enabled": cfg.database.enabled,
            "host": cfg.database.host,
            "port": cfg.database.port,
            "user": cfg.database.user,
            "password": cfg.database.password,
            "database": cfg.database.database,
            "status_table": cfg.database.status_table,
            "transmit_table": cfg.database.transmit_table,
            "dev_name": cfg.database.dev_name,
            "group_name": cfg.database.group_name,
            "write_from_db": cfg.database.write_from_db,
            "create_schema": cfg.database.create_schema,
            "queue_size": cfg.database.queue_size,
        },
        "tags": [
            {
                "name": t.name,
                "address": t.address,
                "type": t.type,
                "writable": t.writable,
                "scale": t.scale,
                "offset": t.offset,
                "swap_words": t.swap_words,
                "description": t.description,
            }
            for t in cfg.tags
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def find_config(path: str | None = None) -> str:
    if path:
        return path
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in (os.path.join(here, "config.yaml"), "config.yaml"):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(here, "config.yaml")


def deep_copy(cfg: AppConfig) -> AppConfig:
    return copy.deepcopy(cfg)