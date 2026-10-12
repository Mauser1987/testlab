"""Cumulative collected leakage volume per seal, as an SVG for the report (M2E).

Drawn from the stored collection records of the manual log (evidence.py),
never from a plot image: one marker per measured collection at its
collection time, at the running total of the volumes measured up to then.
Markers only, no connecting line — nothing was measured between two
collections. Collections that were not measured (blank) add nothing and
have no marker. Pure function of its input: the same records give the same
bytes.
"""

import math
from xml.sax.saxutils import escape

WIDTH, HEIGHT = 640, 250
LEFT, RIGHT, TOP, BOTTOM = 62, 14, 30, 42
COLORS = ["#1f4e79", "#c55a11", "#548235", "#7030a0"]
MARKERS = ["circle", "square", "triangle", "diamond"]


def series(leakage, origin):
    """[(seal label, [(elapsed h, cumulative ml)])] of the seals with a measured collection."""
    found = []
    for seal in leakage:
        total, points = 0.0, []
        for collection in seal.collections:
            if collection.volume is None:
                continue
            total += float(collection.volume)
            points.append(((collection.end - origin).total_seconds() / 3600, total))
        if points:
            found.append((seal.label, points))
    return found


def _nice_step(span, ticks=5):
    if span <= 0:
        return 1.0
    raw = span / ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def _ticks(low, high):
    step = _nice_step(high - low)
    first = math.floor(low / step) * step
    values, value = [], first
    while value <= high + step * 1e-9:
        values.append(round(value, 10))
        value += step
    if values[-1] < high:
        values.append(round(values[-1] + step, 10))
    return values


def _label(value):
    return f"{value:g}"


def _marker(shape, x, y, color):
    if shape == "circle":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{color}"/>'
    if shape == "square":
        return f'<rect x="{x - 3:.1f}" y="{y - 3:.1f}" width="6" height="6" fill="{color}"/>'
    if shape == "triangle":
        return f'<path d="M{x:.1f} {y - 3.6:.1f} L{x + 3.6:.1f} {y + 3:.1f} L{x - 3.6:.1f} {y + 3:.1f} Z" fill="{color}"/>'
    return f'<path d="M{x:.1f} {y - 4:.1f} L{x + 4:.1f} {y:.1f} L{x:.1f} {y + 4:.1f} L{x - 4:.1f} {y:.1f} Z" fill="{color}"/>'


def svg(leakage, origin):
    """The chart as SVG text, or "" when there is nothing measured or no time origin."""
    if origin is None:
        return ""
    data = series(leakage, origin)
    if not data:
        return ""
    xs = [x for _, points in data for x, _ in points]
    ys = [y for _, points in data for _, y in points]
    # A little room above the largest values, so no marker sits on the frame.
    x_ticks = _ticks(min(0.0, min(xs)), max(xs) * 1.04 if max(xs) > 0 else 1.0)
    y_ticks = _ticks(0.0, max(ys) * 1.05 if max(ys) > 0 else 1.0)
    x0, x1, y0, y1 = x_ticks[0], x_ticks[-1], y_ticks[0], y_ticks[-1]
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM

    def px(x):
        return LEFT + (x - x0) / (x1 - x0) * plot_w

    def py(y):
        return TOP + plot_h - (y - y0) / (y1 - y0) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
        'font-family="Carlito, sans-serif" font-size="10" role="img" '
        'aria-label="Cumulative collected leakage volume at each collection">',
        f'<rect x="{LEFT}" y="{TOP}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#808080" stroke-width="0.8"/>',
    ]
    for value in x_ticks:
        x = px(value)
        parts.append(f'<line x1="{x:.1f}" y1="{TOP}" x2="{x:.1f}" y2="{TOP + plot_h}" stroke="#e0e0e0" stroke-width="0.6"/>')
        parts.append(f'<text x="{x:.1f}" y="{TOP + plot_h + 13}" text-anchor="middle">{_label(value)}</text>')
    for value in y_ticks:
        y = py(value)
        parts.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{LEFT + plot_w}" y2="{y:.1f}" stroke="#e0e0e0" stroke-width="0.6"/>')
        parts.append(f'<text x="{LEFT - 5}" y="{y + 3:.1f}" text-anchor="end">{_label(value)}</text>')
    parts.append(f'<text x="{LEFT + plot_w / 2:.1f}" y="{HEIGHT - 8}" text-anchor="middle">'
                 "Elapsed time since t = 0 [h] (collection times)</text>")  # fmt: skip
    parts.append(f'<text transform="translate(14 {TOP + plot_h / 2:.1f}) rotate(-90)" text-anchor="middle">'
                 "Cumulative collected volume [ml]</text>")  # fmt: skip
    legend_x = LEFT
    for index, (label, points) in enumerate(data):
        color, shape = COLORS[index % len(COLORS)], MARKERS[index % len(MARKERS)]
        for x, y in points:
            parts.append(_marker(shape, px(x), py(y), color))
        parts.append(_marker(shape, legend_x + 4, 14, color))
        parts.append(f'<text x="{legend_x + 12}" y="17">{escape(label)}</text>')
        legend_x += 24 + 6 * len(label)
    parts.append("</svg>")
    return "".join(parts)
