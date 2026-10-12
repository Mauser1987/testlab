"""SVG figures of seal-face measurements (M2D, M2F-a).

Deterministic: the same file, settings and engine version give the same
SVG text, so a figure can be regenerated and checked against its stored
SHA-256. Every sample is represented: when a panel holds more samples than
pixel columns, each column keeps its first, lowest, highest and last
sample (as the reference viewers draw), so peaks and valleys stay visible.

The SVG is inline markup (Result page and report), so it uses the page's
fonts. Heights are plotted as calculated; nothing is filtered here.
"""

import hashlib
import math
from xml.sax.saxutils import escape

from . import CONCAVE, CONVEX, mahr

BLUE = "#087fa8"  # left scan / circular trace (reference viewers' colours)
ORANGE = "#c56327"  # right scan
INK = "#183443"
MUTED = "#536b79"
GRID = "#e0e8ec"
FRAME = "#aebfc9"
AMBER = "#d98a0b"  # helium light (v5 accent)
OK_FILL = "#e3f2e9"
OK_LINE = "#2e7d4f"
BAD = "#b3261e"

WIDTH = 520
HEIGHT = 230
MARGIN = {"left": 58, "right": 12, "top": 22, "bottom": 40}


def ticks(lo, hi, target):
    raw = (hi - lo) / target
    power = 10 ** math.floor(math.log10(raw))
    norm = raw / power
    step = (1 if norm <= 1 else 2 if norm <= 2 else 5 if norm <= 5 else 10) * power
    values, k = [], math.ceil(lo / step)
    while k * step <= hi + step * 1e-8:
        x = k * step
        values.append(0.0 if abs(x) < step * 1e-8 else x)
        k += 1
    return values, step


def _decimals(step, minimum):
    return max(minimum, -math.floor(math.log10(step)))


def padded(lo, hi, include_zero=False):
    if include_zero:
        lo, hi = min(0.0, lo), max(0.0, hi)
    pad = max((hi - lo) * 0.08, 0.001)
    return lo - pad, hi + pad


def _signed(v, digits):
    """+0.123 / −0.123 (typographic minus), as the reference tool prints signed values."""
    return f"{v:+.{digits}f}".replace("-", "−")


def _f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def decimate(points, sx):
    """Points [(x, y)] of one unbroken segment → those drawn: first, min, max, last of each pixel column."""
    out, column, bin_ = [], None, []

    def flush():
        if not bin_:
            return
        lo = min(bin_, key=lambda p: p[1])
        hi = max(bin_, key=lambda p: p[1])
        keep = {id(p): p for p in (bin_[0], lo, hi, bin_[-1])}
        out.extend(sorted(keep.values(), key=lambda p: p[0]))
        bin_.clear()

    for p in points:
        c = math.floor(sx(p[0]))
        if c != column:
            flush()
            column = c
        bin_.append(p)
    flush()
    return out


def panel(*, title, x_label, y_label, x_range, y_range, segments, color, fits=(), markers=(), note="",
          width=WIDTH, height=HEIGHT, zero_line=False, layers=(), guides=(), fit_color=MUTED):  # fmt: skip
    """One x–y panel. segments: lists of (x, y) without gaps; fits: ((x0, y0), (x1, y1)) dashed lines;
    layers: further (segments, colour) drawn over the first; guides: (x, colour, label) dashed verticals."""
    left, right = MARGIN["left"], width - MARGIN["right"]
    top, bottom = MARGIN["top"], height - MARGIN["bottom"]
    x0, x1 = x_range
    y0, y1 = y_range

    def sx(x):
        return left + (x - x0) / (x1 - x0) * (right - left)

    def sy(y):
        return bottom - (y - y0) / (y1 - y0) * (bottom - top)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" class="measure-figure" '
        f'role="img" aria-label="{escape(title, {chr(34): "&quot;"})}">',
        f'<rect width="{width}" height="{height}" fill="#fff"/>',
        f'<text x="{left}" y="14" font-size="11" font-weight="bold" fill="{INK}">{escape(title)}</text>',
    ]
    if note:
        out.append(f'<text x="{right}" y="14" font-size="9.5" fill="{MUTED}" text-anchor="end">{escape(note)}</text>')
    yt, ystep = ticks(y0, y1, 4)
    for y in yt:
        py = _f(sy(y))
        out.append(f'<line x1="{left}" x2="{right}" y1="{py}" y2="{py}" stroke="{GRID}" stroke-width="0.6"/>')
        out.append(f'<text x="{left - 6}" y="{_f(sy(y) + 3.5)}" font-size="9.5" fill="{MUTED}" text-anchor="end">'
                   f'{y:.{_decimals(ystep, 1)}f}</text>')  # fmt: skip
    xt, xstep = ticks(x0, x1, 3 if width < 300 else 5 if width < 450 else 6)
    for x in xt:
        px = _f(sx(x))
        out.append(f'<line x1="{px}" x2="{px}" y1="{top}" y2="{bottom}" stroke="{GRID}" stroke-width="0.6"/>')
        out.append(f'<text x="{px}" y="{bottom + 13}" font-size="9.5" fill="{MUTED}" text-anchor="middle">'
                   f'{x:.{_decimals(xstep, 0)}f}</text>')  # fmt: skip
    out.append(f'<rect x="{left}" y="{top}" width="{right - left}" height="{bottom - top}" fill="none" '
               f'stroke="{FRAME}" stroke-width="0.8"/>')  # fmt: skip
    clip = "clip" + hashlib.sha1(repr((title, note, x_range, y_range, width, height)).encode()).hexdigest()[:10]
    out.append(f'<clipPath id="{clip}"><rect x="{left}" y="{top}" width="{right - left}" height="{bottom - top}"/>'
               f'</clipPath><g clip-path="url(#{clip})">')  # fmt: skip
    if zero_line and y0 < 0 < y1:
        out.append(f'<line x1="{left}" x2="{right}" y1="{_f(sy(0))}" y2="{_f(sy(0))}" stroke="#bac9d1" stroke-width="0.8"/>')
    for gx, gcolor, glabel in guides:
        if x0 <= gx <= x1:
            out.append(f'<line x1="{_f(sx(gx))}" x2="{_f(sx(gx))}" y1="{top}" y2="{bottom}" stroke="{gcolor}" '
                       f'stroke-width="1.1" stroke-dasharray="5 4"/>')  # fmt: skip
            if glabel:
                out.append(f'<text x="{_f(sx(gx) + 3)}" y="{top + 10}" font-size="9" fill="{gcolor}">{escape(glabel)}</text>')
    for layer_segments, layer_color in ((segments, color), *layers):
        for segment in layer_segments:
            drawn = decimate(segment, sx)
            if len(drawn) < 2:
                continue
            path = " ".join(f"{_f(sx(x))},{_f(sy(y))}" for x, y in drawn)
            out.append(f'<polyline points="{path}" fill="none" stroke="{layer_color}" stroke-width="0.9" '
                       f'stroke-linejoin="round"/>')  # fmt: skip
    for (fx0, fy0), (fx1, fy1) in fits:
        out.append(f'<line x1="{_f(sx(fx0))}" y1="{_f(sy(fy0))}" x2="{_f(sx(fx1))}" y2="{_f(sy(fy1))}" '
                   f'stroke="{fit_color}" stroke-width="1.2" stroke-dasharray="5 4"/>')  # fmt: skip
    for mx, my in markers:
        if x0 <= mx <= x1:
            out.append(f'<circle cx="{_f(sx(mx))}" cy="{_f(sy(my))}" r="2.6" fill="{color}"/>')
    out.append("</g>")
    out.append(f'<text x="{_f((left + right) / 2)}" y="{height - 6}" font-size="10.5" fill="{INK}" '
               f'text-anchor="middle">{escape(x_label)}</text>')  # fmt: skip
    out.append(f'<text transform="translate(13 {_f((top + bottom) / 2)}) rotate(-90)" font-size="10.5" fill="{INK}" '
               f'text-anchor="middle">{escape(y_label)}</text>')  # fmt: skip
    out.append("</svg>")
    return "".join(out)


# ---- Mahr -----------------------------------------------------------------------------------


def mahr_series(fit, view, common):
    """(points, y range, fitted line) of one scan in a view, over its evaluation interval."""
    points = [(i * fit.step, fit.height(i, view, common)) for i in range(fit.first, fit.last + 1)]
    lo, hi = fit.range(view, common)
    start, end = max(fit.start, fit.first * fit.step), min(fit.end, fit.last * fit.step)
    line = ((start, fit.fitted(start, view, common)), (end, fit.fitted(end, view, common)))
    return points, (lo, hi), line


def mahr_y_range(results, view):
    """Shared y range of several Mahr results (one measurement, or Pre and Post together)."""
    lows, highs = [], []
    for result in results:
        for fit in (result.left, result.right):
            lo, hi = fit.range(view, result.common_slope)
            lows.append(lo)
            highs.append(hi)
    return padded(min(lows), max(highs), include_zero=True)


def mahr_x_range(results):
    return 0.0, max(max(r.left.profile.travel, r.right.profile.travel) for r in results)


def mahr_panel(result, side, view, x_range, y_range, title=None, width=WIDTH, height=HEIGHT):
    fit = result.left if side == "left" else result.right
    points, _, line = mahr_series(fit, view, result.common_slope)
    direction = mahr.DIRECTIONS[fit.direction]
    return panel(
        title=title or f"{'Left' if side == 'left' else 'Right'} scan · {fit.profile.name}",
        note=f"{direction} · P–V {fit.pv(view, result.common_slope):.4f} µm",
        x_label="Distance from scan start (mm)", y_label="Relative height (µm)",
        x_range=x_range, y_range=y_range, segments=[points],
        color=BLUE if side == "left" else ORANGE, fits=[line], width=width, height=height,
    )  # fmt: skip


def mahr_figures(result):
    """{figure code: SVG} of one Mahr measurement, in its P–V view."""
    view = result.settings.pv_view
    x_range, y_range = mahr_x_range([result]), mahr_y_range([result], view)
    return {
        "mahr_left": mahr_panel(result, "left", view, x_range, y_range),
        "mahr_right": mahr_panel(result, "right", view, x_range, y_range),
        "mahr_gauge": taper_gauge(result.taper_hlb, result.settings.flat_limit_hlb, result.taper_um,
                                  result.classification),
    }


# ---- taper in light bands (both instruments) -----------------------------------------------


def taper_gauge(hlb, limit_hlb, taper_um, classification, title="Taper in helium light bands", width=WIDTH):
    """v5's light-band gauge: Convex (ID high) left, Concave (OD high) right, the flat band ± the limit."""
    height = 80
    span = max(1, math.ceil(max(abs(hlb), limit_hlb) + 0.25))
    x0, x1 = 16, width - 16

    def sx(v):
        return (x0 + x1) / 2 + v / span * (x1 - x0) / 2

    colour = {CONVEX: BAD, CONCAVE: BAD}.get(classification, OK_LINE)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" class="measure-figure gauge" '
        f'role="img" aria-label="{escape(title)}">',
        f'<rect width="{width}" height="{height}" fill="#fff"/>',
        f'<text x="{x0}" y="14" font-size="11" font-weight="bold" fill="{INK}">{escape(title)}</text>',
        f'<text x="{x1}" y="14" font-size="10.5" fill="{colour}" text-anchor="end" font-weight="bold">'
        f'{_signed(taper_um, 3)} µm · {_signed(hlb, 2)} HLB · {escape(classification)}</text>',
        f'<text x="{x0}" y="{height - 4}" font-size="9" font-weight="bold" fill="{MUTED}" letter-spacing="0.6">'
        f'← CONVEX · ID high</text>',
        f'<text x="{x1}" y="{height - 4}" font-size="9" font-weight="bold" fill="{MUTED}" letter-spacing="0.6" '
        f'text-anchor="end">OD high · CONCAVE →</text>',
        f'<rect x="{x0}" y="34" width="{x1 - x0}" height="10" rx="2" fill="#f5f7f9" stroke="{FRAME}" stroke-width="0.8"/>',
        f'<rect x="{_f(sx(-limit_hlb))}" y="34" width="{_f(sx(limit_hlb) - sx(-limit_hlb))}" height="10" '
        f'fill="{OK_FILL}" stroke="{OK_LINE}" stroke-width="0.8"/>',
    ]  # fmt: skip
    step = 1 if span > 2 else 0.5
    k = 0
    while -span + k * step <= span + 1e-9:
        v = -span + k * step
        out.append(f'<line x1="{_f(sx(v))}" x2="{_f(sx(v))}" y1="44" y2="49" stroke="{MUTED}" stroke-width="0.8"/>')
        label = f"{v:+g}".replace("-", "−") if v else "0"
        out.append(f'<text x="{_f(sx(v))}" y="61" font-size="9.5" fill="{MUTED}" text-anchor="middle">{label}</text>')
        k += 1
    p = sx(max(-span, min(span, hlb)))
    out.append(f'<path d="M{_f(p - 6)} 25 L{_f(p + 6)} 25 L{_f(p)} 34 Z" fill="{AMBER}"/>'
               f'<line x1="{_f(p)}" x2="{_f(p)}" y1="33" y2="45" stroke="{AMBER}" stroke-width="2.5"/>')  # fmt: skip
    out.append(f'<text x="{_f((x0 + x1) / 2)}" y="{height - 4}" font-size="9" fill="{OK_LINE}" text-anchor="middle">'
               f'Flat band ± {limit_hlb:g} HLB</text>')  # fmt: skip
    out.append("</svg>")
    return "".join(out)


# ---- ROUNDPAK -------------------------------------------------------------------------------


def _segments(evaluation, source=None):
    """Unbroken runs of non-deleted points of the evaluated interval (deleted points are gaps)."""
    source = source or evaluation.source
    segments, current = [], []
    for p in evaluation.selected:
        if p.flag != 0:
            if current:
                segments.append(current)
            current = []
            continue
        current.append((p.x, getattr(p, source)))
    if current:
        segments.append(current)
    return segments


def circular_x_range(evaluation):
    return evaluation.scan.min, 360.0 if evaluation.scan.complete else evaluation.scan.max


def radial_guides(result):
    """Dashed markers at the angles of the radial scans (v5: where the radial traces were taken)."""
    found = []
    for evaluation, colour, side in ((result.left, BLUE, "L"), (result.right, ORANGE, "R")):
        if evaluation is None:
            continue
        angle = _angle(evaluation.scan)
        if angle is not None:
            found.append((angle, colour, f"{side} radial {angle:g}°"))
    return found


def _angle(scan):
    from .roundpak import unit_number

    angle = unit_number(scan.line.get("Angle Pos"), "deg")
    return None if angle is None else angle % 360


def roundpak_circular(evaluation, y_range=None, title=None, width=WIDTH, height=HEIGHT, guides=()):
    scan = evaluation.scan
    source_label = {"deviation": "LFD", "profile": "Filtered profile", "extracted": "Extracted line"}[evaluation.source]
    y_range = y_range or padded(evaluation.lo, evaluation.hi)
    markers = [(evaluation.min_point.x, evaluation.lo), (evaluation.max_point.x, evaluation.hi)]
    return panel(
        title=title or f"Circular trace · {scan.name} · {scan.line.get('X Position', 'radius not exported')}",
        note=f"{source_label} · P–V {evaluation.pv:.4f} µm",
        x_label="Angle (degrees)", y_label="Height (µm)",
        x_range=circular_x_range(evaluation), y_range=y_range, segments=_segments(evaluation),
        color=BLUE, markers=markers, width=width, height=height, zero_line=True, guides=guides,
    )  # fmt: skip


def roundpak_radial(result, side, x_range=None, y_range=None, width=WIDTH, height=HEIGHT):
    evaluation = result.left if side == "left" else result.right
    other = result.right if side == "left" else result.left
    x_range = x_range or (min(evaluation.start, other.start), max(evaluation.end, other.end))
    y_range = y_range or padded(min(evaluation.lo, other.lo), max(evaluation.hi, other.hi))
    line = ((evaluation.start, evaluation.m * evaluation.start + evaluation.b),
            (evaluation.end, evaluation.m * evaluation.end + evaluation.b))  # fmt: skip
    angle = evaluation.scan.line.get("Angle Pos", "angle not exported")
    return panel(
        title=f"{'L' if side == 'left' else 'R'} · {evaluation.scan.name} · {angle}",
        note=f"slope {evaluation.m:.5f} µm/mm",
        x_label="Radius / XPos (mm)", y_label="Height (µm)",
        x_range=x_range, y_range=y_range, segments=_segments(evaluation),
        color=BLUE if side == "left" else ORANGE, fits=[line],
        markers=[(evaluation.min_point.x, evaluation.lo), (evaluation.max_point.x, evaluation.hi)],
        width=width, height=height, zero_line=True,
    )  # fmt: skip


def radial_taper_view(result):
    """v5's "setup tilt removed" view: each radial trace minus its share of the setup tilt and zeroed at its
    inner end, so both rise with the mean slope; [(segments, line), …] for left and right, and the taper line."""
    cone = result.mean_slope
    found = []
    for evaluation in (result.left, result.right):
        r0, m, b = evaluation.start, evaluation.m, evaluation.b
        at_r0 = m * r0 + b
        segments = [[(x, y - (m - cone) * (x - r0) - at_r0) for x, y in segment] for segment in _segments(evaluation)]
        found.append(segments)
    return found


def roundpak_radial_taper(result, x_range=None, y_range=None, width=WIDTH, height=HEIGHT, title=None):
    left, right = radial_taper_view(result)
    r0 = result.left.start
    x_range = x_range or (min(result.left.start, result.right.start), max(result.left.end, result.right.end))
    line = ((x_range[0], result.mean_slope * (x_range[0] - r0)), (x_range[1], result.mean_slope * (x_range[1] - r0)))
    heights = [y for seg in (*left, *right) for _, y in seg] + [line[0][1], line[1][1]]
    y_range = y_range or padded(min(heights), max(heights), include_zero=True)
    if result.taper_um is not None:
        note = f"taper {_signed(result.taper_um, 3)} µm · {result.classification}"
    else:
        note = f"mean slope {_signed(result.mean_slope, 5)} µm/mm"
    return panel(
        title=title or "Radial traces · setup tilt removed",
        note=note, x_label="Radius (mm) · ID side left, OD side right", y_label="Height (µm)",
        x_range=x_range, y_range=y_range, segments=left, color=BLUE, layers=[(right, ORANGE)],
        fits=[line], fit_color=AMBER, width=width, height=height, zero_line=True,
    )  # fmt: skip


def radial_taper_y_range(results):
    heights = []
    for result in results:
        r0 = result.left.start
        for segments in radial_taper_view(result):
            heights += [y for seg in segments for _, y in seg]
        heights += [result.mean_slope * (x - r0) for x in (result.left.start, result.left.end, result.right.end)]
    return padded(min(heights), max(heights), include_zero=True)


def roundpak_harmonics(harmonics, title="Waviness by undulations per revolution (UPR)", width=WIDTH, height=170):
    """Bar chart of the harmonic amplitudes [(k, amplitude, phase)]; the three strongest highlighted."""
    left, right, top, bottom = MARGIN["left"], width - MARGIN["right"], 22, height - 30
    peak = max((a for _, a, _ in harmonics), default=0) or 0.001
    yt, ystep = ticks(0, peak * 1.08, 4)
    y1 = max(yt[-1], peak * 1.08)
    strongest = {k for k, _, _ in sorted(harmonics, key=lambda h: -h[1])[:3]}
    bar = (right - left) / max(len(harmonics), 1)

    def sy(v):
        return bottom - v / y1 * (bottom - top)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" class="measure-figure harmonics" '
        f'role="img" aria-label="{escape(title)}">',
        f'<rect width="{width}" height="{height}" fill="#fff"/>',
        f'<text x="{left}" y="14" font-size="11" font-weight="bold" fill="{INK}">{escape(title)}</text>',
    ]  # fmt: skip
    for y in yt:
        out.append(f'<line x1="{left}" x2="{right}" y1="{_f(sy(y))}" y2="{_f(sy(y))}" stroke="{GRID}" stroke-width="0.6"/>')
        out.append(f'<text x="{left - 6}" y="{_f(sy(y) + 3.5)}" font-size="9.5" fill="{MUTED}" text-anchor="end">'
                   f'{y:.{_decimals(ystep, 2)}f}</text>')  # fmt: skip
    for i, (k, amp, _) in enumerate(harmonics):
        x = left + i * bar
        colour, opacity = (AMBER, "1") if k in strongest else (BLUE, "0.55")
        out.append(f'<rect x="{_f(x + bar * 0.15)}" y="{_f(sy(amp))}" width="{_f(bar * 0.7)}" '
                   f'height="{_f(max(0.0, bottom - sy(amp)))}" fill="{colour}" opacity="{opacity}">'
                   f'<title>{k} UPR: {amp:.4f} µm</title></rect>')  # fmt: skip
        if k == 1 or k % 2 == 0 or k in strongest:
            out.append(f'<text x="{_f(x + bar / 2)}" y="{bottom + 12}" font-size="9" fill="{MUTED}" '
                       f'text-anchor="middle">{k}</text>')  # fmt: skip
    out.append(f'<line x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}" stroke="{FRAME}" stroke-width="0.8"/>')
    out.append(f'<text x="{_f((left + right) / 2)}" y="{height - 4}" font-size="10" fill="{INK}" text-anchor="middle">'
               f'{"Undulations per revolution (UPR) · amplitude = half the P–V of each sine component" if width >= 450 else "Undulations per revolution (UPR)"}</text>')  # fmt: skip
    out.append(f'<text transform="translate(13 {_f((top + bottom) / 2)}) rotate(-90)" font-size="10.5" fill="{INK}" '
               f'text-anchor="middle">Amplitude (µm)</text>')  # fmt: skip
    out.append("</svg>")
    return "".join(out)


def strongest_harmonics(harmonics, count=3):
    return sorted(harmonics, key=lambda h: -h[1])[:count]


def roundpak_polar(evaluation, size=260, title=None, guides=()):
    """Polar view of the circular trace: 0° at right, counterclockwise, height exaggerated (not physical)."""
    cx = cy = size / 2
    base = size * 0.29
    amp = max(abs(evaluation.lo), abs(evaluation.hi), 0.0001)
    scale = base * 0.32 / amp
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size + 30}" class="measure-figure polar" role="img" '
        f'aria-label="Polar profile">',
        f'<rect width="{size}" height="{size + 30}" fill="#fff"/>',
        f'<text x="6" y="13" font-size="11" font-weight="bold" fill="{INK}">{escape(title or "Polar profile")}</text>',
        f'<circle cx="{_f(cx)}" cy="{_f(cy + 8)}" r="{_f(base)}" fill="none" stroke="#cbd7df" stroke-width="0.8" '
        f'stroke-dasharray="4 4"/>',
    ]  # fmt: skip
    for angle in (0, 90, 180, 270):
        th = math.radians(angle)
        r = base * 1.5
        out.append(f'<text x="{_f(cx + r * math.cos(th))}" y="{_f(cy + 8 - r * math.sin(th) + 4)}" font-size="9.5" '
                   f'fill="{MUTED}" text-anchor="middle">{angle}°</text>')  # fmt: skip
    for angle, colour, _ in guides:
        th = math.radians(angle)
        out.append(f'<line x1="{_f(cx + base * 0.35 * math.cos(th))}" y1="{_f(cy + 8 - base * 0.35 * math.sin(th))}" '
                   f'x2="{_f(cx + base * 1.38 * math.cos(th))}" y2="{_f(cy + 8 - base * 1.38 * math.sin(th))}" '
                   f'stroke="{colour}" stroke-width="1.1" stroke-dasharray="5 4"/>')  # fmt: skip
    for segment in _segments(evaluation):
        pts = []
        for x, y in decimate(segment, lambda angle: angle * 4):  # quarter-degree columns
            th = math.radians(x)
            r = base + y * scale
            pts.append(f"{_f(cx + r * math.cos(th))},{_f(cy + 8 - r * math.sin(th))}")
        closed = evaluation.scan.complete and all(p.flag == 0 for p in evaluation.selected)
        tag = "polygon" if closed else "polyline"
        out.append(f'<{tag} points="{" ".join(pts)}" fill="none" stroke="{BLUE}" stroke-width="1.1"/>')
    out.append(f'<text x="{_f(cx)}" y="{_f(cy + 6)}" font-size="9.5" fill="{INK}" text-anchor="middle">P–V</text>')
    out.append(f'<text x="{_f(cx)}" y="{_f(cy + 21)}" font-size="12" font-weight="bold" fill="{INK}" '
               f'text-anchor="middle">{evaluation.pv:.4f} µm</text>')  # fmt: skip
    for k, text in enumerate(("0° at right · counterclockwise", "dashed circle = zero · height exaggerated")):
        out.append(f'<text x="{_f(cx)}" y="{size + 12 + 12 * k}" font-size="9" fill="{MUTED}" '
                   f'text-anchor="middle">{text}</text>')
    out.append("</svg>")
    return "".join(out)


def roundpak_figures(result):
    """{figure code: SVG} of one ROUNDPAK measurement."""
    figures = {}
    guides = radial_guides(result)
    if result.circular:
        figures["roundpak_circular"] = roundpak_circular(result.circular, guides=guides)
        figures["roundpak_polar"] = roundpak_polar(result.circular, guides=guides)
    if result.harmonics:
        figures["roundpak_harmonics"] = roundpak_harmonics(result.harmonics)
    if result.left and result.right:
        figures["roundpak_radial_taper"] = roundpak_radial_taper(result)
        figures["roundpak_radial_left"] = roundpak_radial(result, "left")
        figures["roundpak_radial_right"] = roundpak_radial(result, "right")
    if result.taper_um is not None:
        figures["roundpak_gauge"] = taper_gauge(result.taper_hlb, result.settings.flat_limit_hlb, result.taper_um,
                                                result.classification)  # fmt: skip
    return figures
