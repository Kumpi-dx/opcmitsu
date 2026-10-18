"""Reusable modern widgets: status cards, badges and a live trend chart."""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import C

STATUS_COLOR = {
    "ok": C["green"],
    "bad": C["red"],
    "warn": C["amber"],
    "idle": C["muted"],
    "off": C["border_light"],
}


class StatusDot(QLabel):
    def __init__(self, size: int = 12, state: str = "idle") -> None:
        super().__init__()
        self._size = size
        self.setFixedSize(size + 4, size + 4)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        color = STATUS_COLOR.get(state, STATUS_COLOR["idle"])
        self.setStyleSheet(
            f"background-color: {color}; border-radius: {max(3, self._size // 2 + 2)}px;"
        )


class StatusCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(84)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(QLabel(title))
        top.addStretch(1)
        self.dot = StatusDot(10, "idle")
        top.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        self.value = QLabel("-")
        self.value.setObjectName("cardValue")
        self.value.setWordWrap(True)
        lay.addWidget(self.value)

        self.detail = QLabel("")
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.detail)

    def set_status(self, state: str, value_text: str, detail: str = "") -> None:
        self.dot.set_state(state)
        self.value.setText(value_text)
        color = STATUS_COLOR.get(state, C["muted"])
        # keep text readable, green/red accent the value only via border
        self.setStyleSheet(
            f"QFrame#card {{ background-color: {C['card']}; border: 1px solid {color}40;"
            f" border-radius: 10px; border-left: 3px solid {color}; }}"
        )
        self.detail.setText(detail)


class MiniStat(QFrame):
    def __init__(self, title: str, unit: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(56)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        lay.addWidget(self.title)
        self.value = QLabel("-")
        self.value.setObjectName("cardValue")
        lay.addWidget(self.value)
        self.unit = unit

    def set_stat(self, value: Any) -> None:
        self.value.setText(f"{value}" + (f" {self.unit}" if self.unit else ""))


class Badge(QLabel):
    def __init__(self, text: str = "", kind: str = "neutral") -> None:
        super().__init__(text)
        self._kind = kind
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(42)
        self.repaint_style()

    def repaint_style(self) -> None:
        colors = {
            "on": C["green"],
            "off": C["red"],
            "good": C["green"],
            "bad": C["red"],
            "uncertain": C["amber"],
            "neutral": C["border_light"],
            "accent": C["accent"],
        }
        c = colors.get(self._kind, colors["neutral"])
        self.setStyleSheet(
            f"color: {c}; background-color: {c}22; border: 1px solid {c}55;"
            "border-radius: 9px; padding: 1px 8px; font-weight: 600;"
        )

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.repaint_style()


class TrendChart(QWidget):
    """Simple live line chart drawn with QPainter, stores max_samples per tag."""

    MAX_SAMPLES = 180

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._series: dict[str, deque] = {}
        self._current_tag: str | None = None
        self._min = 0.0
        self._max = 1.0
        self._gen = 0  # bump to force repaint

    def add_sample(self, tag: str, value: float, ts: float) -> None:
        dq = self._series.setdefault(tag, deque(maxlen=self.MAX_SAMPLES))
        dq.append((ts, float(value)))
        self._gen += 1
        self.update()

    def set_tag(self, tag: str | None) -> None:
        self._current_tag = tag
        self._gen += 1
        self.update()

    def current_tag(self) -> str | None:
        return self._current_tag

    def ensure_tag(self) -> None:
        if self._current_tag is None and self._series:
            self._current_tag = next(iter(self._series))

    def clear_data(self) -> None:
        self._series.clear()
        self._gen += 1

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 42, 12, 12, 24

        # grid lines
        painter.setPen(QPen(QColor(C["border"]), 1))
        for i in range(5):
            y = pad_t + (h - pad_t - pad_b) * i / 4
            painter.drawLine(pad_l, int(y), w - pad_r, int(y))

        self.ensure_tag()
        tag = self._current_tag
        dq = self._series.get(tag) if tag else None

        data = list(dq) if dq else []
        if not data:
            painter.setPen(QColor(C["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Menunggu data...")
            painter.end()
            return

        values = [v for _, v in data]
        lo, hi = min(values), max(values)
        if hi - lo < 1e-9:
            hi = lo + 1.0
        self._min, self._max = lo, hi
        lo, hi = self._min, self._max
        span = hi - lo

        def px(i: int) -> float:
            return pad_l + (w - pad_l - pad_r) * i / (self.MAX_SAMPLES - 1)

        def py(v: float) -> float:
            return pad_t + (h - pad_t - pad_b) * (1.0 - (v - lo) / span)

        # area fill
        pts = QPolygonF()
        pts.append(QPointF(pad_l, py(lo)))
        for i, (_, v) in enumerate(data):
            pts.append(QPointF(px(i), py(v)))
        pts.append(QPointF(pad_l + (w - pad_l - pad_r), py(lo)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C["accent"] + "40"))
        painter.drawPolygon(pts)

        # line
        path = QPolygonF()
        for i, (_, v) in enumerate(data):
            path.append(QPointF(px(i), py(v)))
        painter.setPen(QPen(QColor(C["accent"]), 2))
        painter.drawPolyline(path)

        # labels
        painter.setPen(QColor(C["muted"]))
        painter.drawText(2, int(py(hi)) + 4, _fmt(hi))
        painter.drawText(2, int(py(lo)) + 4, _fmt(lo))
        mid = (lo + hi) / 2
        painter.drawText(2, int(py(mid)) + 4, _fmt(mid))
        painter.drawText(pad_l, h - 6, tag or "")
        painter.end()


def _fmt(v: float) -> str:
    if abs(v) >= 10000:
        return f"{v:,.0f}"
    return f"{v:,.1f}"


def human_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}h {h}m {m}s"
    if h:
        return f"{h}j {m}m {s}d"
    if m:
        return f"{m}m {s}d"
    return f"{s}d"


def format_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))