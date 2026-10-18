from __future__ import annotations

import argparse
import logging
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from app import __version__
from app.config import find_config, load_config
from app.gateway import Gateway
from app.gui.main_window import MainWindow
from app.gui.theme import apply_theme
from app.logging_setup import setup_logging

log = logging.getLogger("opc_mitsu")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gateway PLC Mitsubishi ke MySQL")
    parser.add_argument("--config", default=None, help="Path file konfigurasi YAML")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    args = parse_args(argv)

    config_path = os.path.abspath(find_config(args.config))
    cfg = load_config(config_path)

    os.chdir(here)
    log_file = setup_logging(cfg.log_level, cfg.log_dir or "logs", console=True)

    log.info("=" * 60)
    log.info("opc_mitsu v%s", __version__)
    log.info("config : %s", config_path)
    log.info("log    : %s", log_file or "(console)")
    log.info("=" * 60)

    gateway = Gateway(cfg)

    # Keep fractional (125%/150%) DPI scaling crisp instead of rounding up.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow(gateway, cfg, config_path)
    win.show()
    try:
        gateway.start()
    except Exception as e:
        log.exception("Gateway gagal start: %s", e)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()