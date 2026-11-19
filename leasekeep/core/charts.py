"""Tiny server-side SVG chart geometry (no JavaScript charting library needed).

Marks follow a consistent spec: columns at most 24px wide with a 4px rounded
data end and a square baseline, a 2px gap between touching columns, hairline
gridlines, and a hit target per category that is larger than the marks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from math import floor, log10

BAR_MAX = 24
GAP = 2
RADIUS = 4


def nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1.0
    exponent = floor(log10(value))
    base = 10**exponent
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * base:
            return step * base
    return 10 * base  # pragma: no cover


def compact(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 10_000:
        return f"${value / 1000:.0f}K"
    return f"${value:,.0f}"


def rounded_column(x: float, y: float, w: float, h: float) -> str:
    """Path for a column with rounded top corners and a square baseline."""
    r = min(RADIUS, h, w / 2)
    return (
        f"M{x:.2f},{y + h:.2f} V{y + r:.2f} Q{x:.2f},{y:.2f} {x + r:.2f},{y:.2f} "
        f"H{x + w - r:.2f} Q{x + w:.2f},{y:.2f} {x + w:.2f},{y + r:.2f} V{y + h:.2f} Z"
    )


@dataclass
class Bar:
    key: str
    value: Decimal
    path: str
    x: float
    y: float


@dataclass
class Group:
    label: str
    x: float
    width: float
    center: float
    bars: list[Bar] = field(default_factory=list)
    tip: str = ""


@dataclass
class Tick:
    y: float
    label: str


@dataclass
class ColumnChart:
    width: int
    height: int
    top: int
    bottom: int
    left: int
    groups: list[Group]
    ticks: list[Tick]

    @property
    def baseline(self) -> int:
        return self.height - self.bottom

    @property
    def plot_height(self) -> int:
        return self.baseline - self.top


def grouped_columns(
    rows: list[dict],
    keys: list[str],
    *,
    label_key: str,
    label_format=lambda v: str(v),
    tip_names: dict[str, str] | None = None,
    money_format=lambda v: f"${v:,.2f}",
    width: int = 720,
    height: int = 240,
) -> ColumnChart:
    top, bottom, left = 12, 28, 52
    plot_w = width - left
    plot_h = height - top - bottom
    peak = max((float(row[k]) for row in rows for k in keys), default=0.0)
    ceiling = nice_ceiling(peak)
    ticks = [Tick(y=top + plot_h - plot_h * i / 4, label=compact(ceiling * i / 4)) for i in range(5)]
    band = plot_w / max(len(rows), 1)
    bar_w = min(BAR_MAX, (band * 0.7 - GAP * (len(keys) - 1)) / len(keys))
    cluster = bar_w * len(keys) + GAP * (len(keys) - 1)
    groups = []
    for i, row in enumerate(rows):
        x0 = left + band * i
        start = x0 + (band - cluster) / 2
        group = Group(label=label_format(row[label_key]), x=x0, width=band, center=x0 + band / 2)
        tip = [group.label]
        for j, key in enumerate(keys):
            value = Decimal(row[key])
            h = plot_h * float(value) / ceiling if ceiling else 0
            bx = start + j * (bar_w + GAP)
            by = top + plot_h - h
            path = rounded_column(bx, by, bar_w, h) if h > 0.5 else ""
            group.bars.append(Bar(key=key, value=value, path=path, x=bx, y=by))
            name = (tip_names or {}).get(key, key)
            tip.append(f"{money_format(value)} {name}")
        group.tip = "|".join(tip)
        groups.append(group)
    return ColumnChart(width, height, top, bottom, left, groups, ticks)
