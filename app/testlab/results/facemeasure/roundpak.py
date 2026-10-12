"""ROUNDPAK flatness export (CSV) and the viewer's calculations (M2D, M2F-a).

Ported from the reference ROUNDPAK seal-face flatness viewer; engine
roundpak-2 adds the Roundpak tab of Seal_Face_Flatness_Claude_v5.html:
classified radial taper, setup tilt and the waviness harmonics (UPR).

An export holds one or more "Output text data of Measurement" blocks, each
with its metadata (file and date, Title, Sub Title, Created By), the
instrument's result ("Parameter …" header + values row), the scan settings
("Extracted line" header + values row) and a measurement table found by its
column names ("Curve No.", "Point No.", Angle(°) or XPos (mm), Extracted
line, Profile, LFD or LSD, Delete Flag). Circular sections use the angle in
degrees and LFD, radial sections XPos in mm and LSD; heights are µm.
Points with a nonzero Delete Flag are excluded from calculations.

Two kinds of results are kept strictly apart:

* instrument results, exactly as exported: Flatness(FLTt), tolerance
  limits, Check Result, peak/valley, measurement radius, inclinations;
* values this viewer calculates from the exported traces: the circular LFD
  peak-to-valley, the radial least-squares slopes, the radial taper and the
  harmonics. They never overwrite an instrument result.

    circular LFD P–V   = max(LFD) − min(LFD) over the complete selected circular scan
    radial fit         height = slope × radius + intercept over the evaluation interval
    mean outward slope = (left slope + right slope) / 2      (traces 180° apart: a tilt of the ring cancels)
    setup tilt         = (right slope − left slope) / 2      (the tilt that cancels)
    radial taper       = mean outward slope × (OD − ID) / 2   [µm]; needs the face OD and ID
    classification     taper / light band below −limit: Convex (ID high); above +limit: Concave (OD high); else Flat
    harmonic k (UPR)   amplitude = 2/n · |Σ (h − mean) · e^(i·k·θ)|, k = 1…30, over the selected circular
                       scan's non-deleted points (half the peak-to-valley of that sine component)

Sign as in v5 and the Mahr taper: negative = ID high (Convex), positive =
OD high (Concave); the Excel template showed the opposite sign. A circular
trace is one radius, not a map of the whole sealing face. LFD/LSD are the
instrument's exported reference deviations; their reference algorithm is
not rebuilt here.
"""

import math
import re
from dataclasses import dataclass, field

from . import BOM, DEFAULT_FLAT_LIMIT_HLB, DEFAULT_LIGHT_BAND_UM, CalculationError, InstrumentFileError, classify

NUMBER = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(.*)$", re.S)
DECIMAL = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")

SOURCES = {
    "deviation": "LFD / LSD · template view",
    "profile": "Filtered Profile",
    "extracted": "Extracted line",
}
UNITS = {"mm": "Millimetres", "in": "Inches"}
HARMONICS = 30  # undulations per revolution analysed
FLATNESS_PARAMETER = "Flatness(FLTt)"


def _clean(text):
    return re.sub(r"\s+", " ", str(text).strip().lower())


def csv_rows(text):
    """Rows of trimmed fields; blank rows dropped. Delimiter: ';' when the 'Curve No.' header uses it, else ','."""
    text = text.removeprefix(BOM)
    header = next((line for line in re.split(r"\r?\n", text) if line.strip().startswith("Curve No.")), None)
    delim = ";" if header is not None and ";" in header else ","
    rows = []
    if '"' not in text:  # fast path, same result as the character scanner below
        for line in re.split(r"\r\n|\n|\r", text):
            row = [f.strip() for f in line.split(delim)]
            if any(row):
                rows.append(row)
        return rows
    row, buf, quoted, i = [], [], False, 0
    while i < len(text):
        ch = text[i]
        if quoted:
            if ch == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    buf.append('"')
                    i += 1
                else:
                    quoted = False
            else:
                buf.append(ch)
        elif ch == '"':
            if "".join(buf).strip():
                raise InstrumentFileError("Unexpected quote in CSV field.")
            quoted = True
        elif ch == delim:
            row.append("".join(buf).strip())
            buf = []
        elif ch in "\n\r":
            if ch == "\r" and i + 1 < len(text) and text[i + 1] == "\n":
                i += 1
            row.append("".join(buf).strip())
            if any(row):
                rows.append(row)
            row, buf = [], []
        else:
            buf.append(ch)
        i += 1
    if quoted:
        raise InstrumentFileError("Unclosed quoted CSV field.")
    row.append("".join(buf).strip())
    if any(row):
        rows.append(row)
    return rows


def unit_number(text, target="um"):
    """A value with its unit as exported (e.g. '0.296µm', '62.00 mm', '89.27 °') in the target unit, else None."""
    t = str(text if text is not None else "").strip().replace("µ", "u").replace("μ", "u")
    match = NUMBER.match(t)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).strip().lower()
    if not math.isfinite(value):
        return None
    if target == "mm":
        if unit == "um":
            value /= 1000
        elif unit and unit != "mm":
            return None
    elif target == "um":
        if unit == "mm":
            value *= 1000
        elif unit and unit != "um":
            return None
    elif target == "deg" and unit and unit not in ("°", "deg", "degrees"):
        return None
    return value


def _numeric(text, label):
    t = str(text).strip()
    if t == "" or not DECIMAL.match(t) or not math.isfinite(float(t)):
        raise InstrumentFileError(f"Invalid {label} in measurement table.")
    return float(t)


@dataclass(frozen=True)
class Point:
    point: int
    x: float  # angle [°] or radius [mm]
    extracted: float  # µm
    profile: float
    deviation: float  # LFD (circular) or LSD (radial)
    flag: int  # Delete Flag; nonzero: excluded


@dataclass
class Scan:
    id: str
    kind: str  # circular | radial
    name: str
    curve: int
    headers: list
    meta: dict  # date, title, subtitle, operator
    params: dict  # instrument result, header → value as exported
    line: dict  # scan settings, header → value as exported
    points: list  # sorted by x
    min: float
    max: float
    complete: bool  # circular and covering the full revolution

    @property
    def flagged(self):
        return sum(1 for p in self.points if p.flag != 0)


@dataclass
class File:
    name: str
    scans: list
    meta: dict

    def of_kind(self, kind):
        return [s for s in self.scans if s.kind == kind]

    def scan(self, scan_id, kind):
        found = next((s for s in self.scans if s.id == str(scan_id)), None)
        if found is None or found.kind != kind:
            raise CalculationError(f"Choose a valid {kind} scan.")
        return found


def parse(text, name=""):
    rows = csv_rows(text)
    blocks = []
    meta, params, line, current, pending = {}, {}, {}, None, None
    i = 0
    while i < len(rows):
        r = rows[i]
        first = _clean(r[0])
        if first == "output text data of measurement":
            current, meta, params, line, pending = None, {}, {}, {}, "file"
        elif re.fullmatch(r"-+", first):
            current = None
        elif pending == "file":
            meta["date"] = r[1] if len(r) > 1 else ""
            pending = None
        elif first == "title":
            meta["title"] = ", ".join(r[1:])
        elif first == "sub title":
            meta["subtitle"] = ", ".join(r[1:])
        elif first == "created by":
            meta["operator"] = ", ".join(r[1:])
        elif first.startswith("parameter ") or first == "extracted line":
            i += 1
            values = rows[i] if i < len(rows) else None
            if values is None or len(values) < len(r):
                raise InstrumentFileError(
                    "Incomplete instrument result section." if first != "extracted line" else "Incomplete scan settings."
                )
            pairs = dict(zip(r, values))
            if first == "extracted line":
                line = pairs
            else:
                params = pairs
        elif first == "curve no.":
            headers = r

            def find(prefix):
                return next((k for k, h in enumerate(headers) if _clean(h).startswith(prefix)), -1)

            circular = find("angle(") >= 0
            x = find("angle(") if circular else find("xpos")
            kind = "circular" if circular else "radial"
            indexes = {
                "curve": find("curve no."), "point": find("point no."), "x": x,
                "extracted": find("extracted line ("), "profile": find("profile ("),
                "deviation": find("lfd (") if circular else find("lsd ("), "flag": find("delete flag"),
            }  # fmt: skip
            if any(k < 0 for k in indexes.values()):
                raise InstrumentFileError("Unsupported measurement table columns.")
            for key in ("extracted", "profile", "deviation"):
                if not re.search(r"[µμu]m", headers[indexes[key]], re.I):
                    raise InstrumentFileError("Expected micrometre height columns.")
            if kind == "radial" and not re.search(r"\(mm\)", headers[x], re.I):
                raise InstrumentFileError("Expected millimetre XPos coordinates.")
            current = {
                "kind": kind, "headers": headers, "indexes": indexes, "meta": dict(meta), "params": dict(params),
                "line": dict(line), "rows": [], "name": line.get("Extracted line") or f"Scan {len(blocks) + 1}",
            }  # fmt: skip
            blocks.append(current)
        elif current is not None:
            ix = current["indexes"]
            if len(r) <= max(ix.values()):
                raise InstrumentFileError("Truncated measurement row.")
            curve = _numeric(r[ix["curve"]], "curve number")
            point = _numeric(r[ix["point"]], "point number")
            flag = _numeric(r[ix["flag"]], "delete flag")
            if not curve.is_integer() or curve < 1 or not point.is_integer() or point < 1 \
                    or not flag.is_integer() or flag < 0:  # fmt: skip
                raise InstrumentFileError("Invalid curve, point number or Delete Flag.")
            current["rows"].append((int(curve), Point(
                int(point), _numeric(r[ix["x"]], "coordinate"), _numeric(r[ix["extracted"]], "extracted height"),
                _numeric(r[ix["profile"]], "profile height"), _numeric(r[ix["deviation"]], "deviation height"),
                int(flag),
            )))  # fmt: skip
        i += 1

    scans = []
    for block in blocks:
        groups = {}
        for curve, p in block["rows"]:
            groups.setdefault(curve, []).append(p)
        for curve, points in groups.items():
            if len(points) < 3:
                raise InstrumentFileError("Measurement scan needs at least three points.")
            for k in range(1, len(points)):
                if points[k].point != points[k - 1].point + 1:
                    raise InstrumentFileError("Point numbers have a gap or duplicate.")
            ordered = sorted(points, key=lambda p: p.x)
            for k in range(1, len(ordered)):
                if ordered[k].x == ordered[k - 1].x:
                    raise InstrumentFileError("Duplicate measurement coordinates.")
            if block["kind"] == "circular" and (ordered[0].x < 0 or ordered[-1].x > 360):
                raise InstrumentFileError("Angle coordinates must be within 0–360°.")
            gaps = sorted(ordered[k + 1].x - ordered[k].x for k in range(len(ordered) - 1))
            step = gaps[len(gaps) // 2]
            lo, hi = ordered[0].x, ordered[-1].x
            complete = block["kind"] == "circular" and lo <= step * 2 and hi >= 360 - step * 2 and gaps[-1] <= step * 3
            scans.append(Scan(
                id=str(len(scans)), kind=block["kind"],
                name=block["name"] + (f" · curve {curve}" if len(groups) > 1 else ""), curve=curve,
                headers=block["headers"], meta=block["meta"], params=block["params"], line=block["line"],
                points=ordered, min=lo, max=hi, complete=complete,
            ))  # fmt: skip
    if not scans:
        raise InstrumentFileError("No ROUNDPAK measurement tables found.")
    return File(name, scans, scans[0].meta)


@dataclass(frozen=True)
class Evaluation:
    scan: Scan
    source: str
    start: float
    end: float
    selected: list  # points in the interval
    used: list  # of those, not deleted
    lo: float
    hi: float
    m: float  # slope [µm/mm or µm/°]
    b: float
    min_point: Point
    max_point: Point

    @property
    def pv(self):
        return self.hi - self.lo


def evaluate_scan(scan, source, start=None, end=None):
    start = scan.min if start is None else start
    end = scan.max if end is None else end
    if source not in SOURCES:
        raise CalculationError("Choose a valid source column.")
    if not (math.isfinite(start) and math.isfinite(end)) or start < scan.min - 1e-8 or end > scan.max + 1e-8 \
            or end <= start:  # fmt: skip
        raise CalculationError(f"Evaluation interval must be within {_num(scan.min)}–{_num(scan.max)}.")
    selected = [p for p in scan.points if start - 1e-8 <= p.x <= end + 1e-8]
    used = [p for p in selected if p.flag == 0]
    if len(used) < 3:
        raise CalculationError("At least three non-deleted points are required.")
    mean_x = mean_y = 0.0
    lo, hi, min_point, max_point = math.inf, -math.inf, None, None
    for p in used:
        y = getattr(p, source)
        mean_x += p.x
        mean_y += y
        if y < lo:
            lo, min_point = y, p
        if y > hi:
            hi, max_point = y, p
    mean_x /= len(used)
    mean_y /= len(used)
    xx = xy = 0.0
    for p in used:
        dx = p.x - mean_x
        xx += dx * dx
        xy += dx * (getattr(p, source) - mean_y)
    m = xy / xx
    return Evaluation(scan, source, start, end, selected, used, lo, hi, m, mean_y - m * mean_x, min_point, max_point)


def _num(value):
    return str(int(value)) if float(value).is_integer() else repr(value)


@dataclass(frozen=True)
class Settings:
    od: float | None = None  # face dimensions are not in the CSV: optional, both or neither
    id: float | None = None
    units: str = "mm"
    light_band_um: float = DEFAULT_LIGHT_BAND_UM
    circle_scan: str | None = None  # scan ids; None: the reference tool's default choice
    circle_source: str = "deviation"
    left_scan: str | None = None
    right_scan: str | None = None
    radial_source: str = "deviation"
    left_start: float | None = None  # evaluation intervals [mm radius]; None: whole scan
    left_end: float | None = None
    right_start: float | None = None
    right_end: float | None = None
    flat_limit_hlb: float = DEFAULT_FLAT_LIMIT_HLB


def harmonics(evaluation, count=HARMONICS):
    """[(k, amplitude µm, phase °)] of the evaluated circular trace, k = 1…count (v5: harmonics())."""
    points = evaluation.used
    n = len(points)
    heights = [getattr(p, evaluation.source) for p in points]
    mean = sum(heights) / n
    angles = [math.radians(p.x) for p in points]
    found = []
    for k in range(1, count + 1):
        c = s = 0.0
        for h, theta in zip(heights, angles):
            d = h - mean
            c += d * math.cos(k * theta)
            s += d * math.sin(k * theta)
        found.append((k, 2 / n * math.hypot(c, s), math.degrees(math.atan2(s, c))))
    return found


def default_scans(file):
    """The reference tool's initial choice: first circular; left = second radial block, right = first."""
    circles, radial = file.of_kind("circular"), file.of_kind("radial")
    return {
        "circle_scan": circles[0].id if circles else None,
        "left_scan": (radial[1] if len(radial) > 1 else radial[0]).id if radial else None,
        "right_scan": radial[0].id if radial else None,
    }


@dataclass(frozen=True)
class Result:
    settings: Settings  # with the scan choice resolved
    circular: Evaluation | None  # selected circular scan in the chosen source (display)
    lfd: Evaluation | None  # the same scan's LFD, complete: the circular LFD P–V
    left: Evaluation | None
    right: Evaluation | None
    face_width_mm: float | None
    mean_slope: float | None  # µm/mm
    taper_um: float | None  # radial taper, signed: negative ID high (Convex), positive OD high (Concave)
    reported_flatness_um: float | None  # instrument Flatness(FLTt), as exported
    separation_deg: float | None  # angular separation of the two radial scans
    instrument: dict = field(default_factory=dict)  # instrument result of the circular scan, as exported
    tilt_slope: float | None = None  # setup tilt between the radial traces [µm/mm]
    classification: str = ""  # Flat / Convex / Concave; blank without a taper
    harmonics: list = field(default_factory=list)  # [(k, amplitude µm, phase °)] of the circular scan

    @property
    def light_band_um(self):
        return self.settings.light_band_um

    @property
    def taper_hlb(self):
        return None if self.taper_um is None else self.taper_um / self.settings.light_band_um


def calculate(file, settings):
    from dataclasses import replace

    if file is None:
        raise CalculationError("Import a valid CSV.")
    s = settings
    if s.units not in UNITS or s.light_band_um is None or not s.light_band_um > 0:
        raise CalculationError("Choose valid diameter units and a positive light-band height.")
    if s.flat_limit_hlb is None or not math.isfinite(s.flat_limit_hlb) or s.flat_limit_hlb < 0:
        raise CalculationError("Enter a flat limit of at least 0 HLB.")
    width = None
    if (s.od is None) != (s.id is None):
        raise CalculationError("Enter both OD and ID, or leave both blank.")
    if s.od is not None:
        if not (math.isfinite(s.od) and math.isfinite(s.id)) or s.od <= s.id or s.id < 0:
            raise CalculationError("Enter OD > ID ≥ 0.")
        width = (s.od - s.id) / 2 * (25.4 if s.units == "in" else 1)

    defaults = default_scans(file)
    s = replace(s, **{k: getattr(s, k) if getattr(s, k) is not None else v for k, v in defaults.items()})

    circular = lfd = None
    if file.of_kind("circular"):
        circular = evaluate_scan(file.scan(s.circle_scan, "circular"), s.circle_source)
        lfd = evaluate_scan(circular.scan, "deviation")
    left = right = None
    if len(file.of_kind("radial")) >= 2:
        if s.left_scan == s.right_scan:
            raise CalculationError("Select two different radial scans.")
        lscan, rscan = file.scan(s.left_scan, "radial"), file.scan(s.right_scan, "radial")
        s = replace(
            s,
            left_start=lscan.min if s.left_start is None else s.left_start,
            left_end=lscan.max if s.left_end is None else s.left_end,
            right_start=rscan.min if s.right_start is None else s.right_start,
            right_end=rscan.max if s.right_end is None else s.right_end,
        )
        left = evaluate_scan(lscan, s.radial_source, s.left_start, s.left_end)
        right = evaluate_scan(rscan, s.radial_source, s.right_start, s.right_end)
    mean_slope = (left.m + right.m) / 2 if left and right else None
    tilt = (right.m - left.m) / 2 if left and right else None
    taper = width * mean_slope if width is not None and mean_slope is not None else None
    classification = classify(taper / s.light_band_um, s.flat_limit_hlb) if taper is not None else ""
    reported = unit_number(circular.scan.params.get(FLATNESS_PARAMETER)) if circular else None
    separation = None
    if left and right:
        a = unit_number(left.scan.line.get("Angle Pos"), "deg")
        b = unit_number(right.scan.line.get("Angle Pos"), "deg")
        if a is not None and b is not None:
            raw = abs(a - b) % 360
            separation = min(raw, 360 - raw)
    return Result(s, circular, lfd, left, right, width, mean_slope, taper, reported, separation,
                  dict(circular.scan.params) if circular else {}, tilt, classification,
                  harmonics(circular) if circular else [])  # fmt: skip
