# AGENTS.md

Single Python 3.10+ desktop app (PyQt6 GUI): Mitsubishi PLC (MC protocol) -> MySQL.
Flat layout: `main.py` + `app/`, no packages, no build step. `README.md` (Indonesian) is accurate — trust it over prose here if they ever conflict.

## Commands

- Setup: `pip install -r requirements.txt`
- Run: `python main.py [--config <path>]` (GUI needs a display)
- **No tests, linter, formatter, typecheck, or CI exist.** Don't invent pytest/ruff commands.
  Verify with `python -m compileall main.py app`.

## Architecture

- Threads: GUI (main) + `plc-poller` (`app/gateway.py`) + DB writer (`app/database.py`).
  PLC and DB work must never block the GUI; DB talks through a queue.
- PLC drivers are selected by `plc.driver` in `config.yaml` via `create_plc_client()`
  (`app/plc_client.py`): `mitsubishi` (MC protocol), `modbus_tcp`/`modbus_rtu`
  (`app/modbus_client.py`), `omron_fins` (`app/fins_client.py`). All drivers implement
  `BasePlcClient` (connect/disconnected/read_tags/write_tag) and apply `scale`/`offset`
  internally. Address notation is driver-specific (README "Alamat tag per driver").
- `config.yaml` `tags:` is the single source of truth for tags; `t_reg_status` is only a value
  mirror. External writes go through `t_transmit`: insert row -> gateway writes PLC -> row
  deleted on success, kept for retry on failure. Non-`writable` tags drop the row.
- Tag list can change at runtime (`Gateway.set_tags`); read it via `active_tags()`, don't cache.

## Gotchas

- `main.py` does `os.chdir(<repo root>)` after loading config: relative paths (`log_dir`)
  resolve against the repo root regardless of where you launched from.
- The GUI Settings page rewrites `config.yaml` via `save_config()` — hand edits and YAML
  comments are lost while the app runs.
- `create_schema` defaults to `True` in code but is `false` in this repo's `config.yaml`.
- Schema is `latin1`/`MyISAM` on purpose; additive migrations (`uk_dev_tag`, `t_transmit.ID`)
  run automatically.
- `__pycache__/` and `logs/` are generated — don't edit them.
- Strings and log messages are Indonesian; match the existing tone in GUI/log changes.
