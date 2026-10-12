"""Mahr profile export (TXT) and the opposing-scan taper (M2D, M2F-a).

Ported from the reference Seal Face Profile Viewer; engine mahr-2 follows
the Mahr tab of Seal_Face_Flatness_Claude_v5.html (first points skipped,
Flat/Convex/Concave with a flat limit, lenient file reading).

File: header lines KEY=VALUE, then [PROFILE] with CNT samples, then
[VALUES] with the instrument's own evaluation (Ra;…;…;…;value). Only the
[PROFILE] values are read as the profile. Decimal commas are read as
points. As in v5, a file is still read, with a warning, when the point
count differs from CNT (positions keep the CNT spacing), when CNT is
missing (spacing from the points found) or when a [PROFILE] line is not a
number (skipped). LT and RES must be positive.

    height   z = sample × RES                [µm]
    position t = i × LT / (CNT − 1)          [mm from scan start]

No roughness or waviness filter is applied here. Ra and Rz are read as
exported: they refer to the instrument's evaluation, not to the interval
selected here.

Opposing-scan model (legacy Excel template). The left OD → ID scan is
placed at x = t − LT, the right ID → OD scan at x = t; reversing a scan's
direction reverses its coordinate. A least-squares line z = m·x + b is
fitted over each evaluation interval; the first skip_points samples of
each scan are left out (Excel template: from point 6 onward).

    common setup slope   = (mL + mR) / 2                     [µm/mm]
    radial taper         = −(mL − mR) × radial face width / 2   [µm], signed
    taper in HLB         = taper / light-band height
    classification       below −limit: Convex; above +limit: Concave; else Flat (limit 0.25 HLB)

The taper assumes opposing radial scans. Scan travel is not rescaled to the
face width.

Profile P–V is max − min of the heights in a view over the evaluation
interval. It is a profile range, NOT whole-face flatness. Views:

    raw        each interval's mean removed
    common     estimated common setup tilt removed, each trace independently zeroed
    residual   each trace's own fitted line removed (removes its taper component too)
"""

import math
import re
from dataclasses import dataclass, field

from . import BOM, DEFAULT_FLAT_LIMIT_HLB, DEFAULT_LIGHT_BAND_UM, CalculationError, InstrumentFileError, classify

NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?$")

DIRECTIONS = {"in": "OD → ID", "out": "ID → OD"}
UNITS = {"in": "Inches", "mm": "Millimetres"}
VIEWS = {
    "common": "Common tilt removed",
    "raw": "Raw · mean centred",
    "residual": "Individual line residuals",
}
DEFAULT_DIRECTIONS = {"left": "in", "right": "out"}
DEFAULT_SKIP_POINTS = 5


def _js_number(text):
    """A finite number as JavaScript Number() reads a decimal string, else None ('' reads as 0)."""
    text = text.strip()
    if text == "":
        return 0.0
    if not NUMBER.match(text):
        return None
    value = float(text)
    return value if math.isfinite(value) else None


def _decimal(text):
    """A number as v5 reads it: Number(text.replace(",", ".")), else None."""
    return _js_number(text.replace(",", ".", 1))


def _num(value):
    """A number as JavaScript prints it in a message: 9, not 9.0."""
    return str(int(value)) if float(value).is_integer() else repr(value)


@dataclass(frozen=True)
class Profile:
    name: str
    headers: dict  # KEY → value as written, keys upper case
    samples: tuple  # raw [PROFILE] integers (floats)
    reported: dict  # {"Ra": µm, "Rz": µm} as exported, when present
    count: int  # samples read
    length: float  # LT [mm]
    resolution: float  # RES [µm per sample unit]
    spacing_count: float = 0  # CNT of the header (else count): positions are LT / (spacing_count − 1) apart
    warnings: tuple = ()

    @property
    def step(self):
        return self.length / ((self.spacing_count or self.count) - 1)

    @property
    def travel(self):
        """Position of the last sample [mm]: LT, unless the file holds more or fewer points than CNT."""
        return (self.count - 1) * self.step


def parse(text, name=""):
    headers, samples, reported = {}, [], {}
    section, skipped = "", 0
    for raw in re.split(r"\r?\n", text.removeprefix(BOM)):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.upper()
            continue
        if section == "[PROFILE]":
            value = _decimal(line)
            if value is None:
                skipped += 1
                continue
            samples.append(value)
        elif section == "[VALUES]":
            fields = line.split(";")
            if len(fields) > 4 and fields[0].strip() in ("Ra", "Rz"):
                value = _decimal(fields[4])
                if fields[4].strip() != "" and value is not None:
                    reported[fields[0].strip()] = value
        elif "=" in line:
            key, _, value = line.partition("=")
            headers[key.strip().upper()] = value.strip()

    if not samples:
        raise InstrumentFileError("No [PROFILE] section with numbers found. Is this a Mahr TXT export?")
    length = _decimal(headers.get("LT", ""))
    resolution = _decimal(headers.get("RES", ""))
    if length is None or not length > 0:
        raise InstrumentFileError("Header is missing the trace length (LT=).")
    if resolution is None or not resolution > 0:
        raise InstrumentFileError("Header is missing the resolution (RES=).")
    warnings = []
    if skipped:
        warnings.append(f"{skipped} non-numeric [PROFILE] line{'s' if skipped > 1 else ''} skipped.")
    header_count = _decimal(headers["CNT"]) if "CNT" in headers else None
    if header_count is not None and header_count > 1:
        spacing = header_count
        if header_count != len(samples):
            warnings.append(f"Header says {_num(header_count)} points, file holds {len(samples)}.")
    else:
        spacing = len(samples)
        warnings.append(f"No usable point count (CNT=) in the header: spacing from the {len(samples)} points found.")
    if spacing < 2:
        raise InstrumentFileError("At least two profile points are needed.")
    return Profile(name, headers, tuple(samples), reported, len(samples), length, resolution, spacing, tuple(warnings))


def coordinate(side, direction, t, length):
    if side == "left":
        return t - length if direction == "in" else -t
    return t if direction == "out" else length - t


@dataclass(frozen=True)
class Fit:
    profile: Profile
    side: str  # left | right
    direction: str  # in | out
    first: int  # sample indexes of the evaluation interval, inclusive
    last: int
    count: int
    start: float  # interval as entered [mm]
    end: float
    m: float  # fitted slope [µm/mm]
    b: float  # intercept [µm]
    mean_z: float

    @property
    def step(self):
        return self.profile.step

    def x(self, i):
        return coordinate(self.side, self.direction, i * self.step, self.profile.length)

    def height(self, i, view, common):
        z = self.profile.samples[i] * self.profile.resolution
        if view == "raw":
            return z - self.mean_z
        if view == "common":
            return z - common * self.x(i) - self.b
        return z - self.m * self.x(i) - self.b

    def range(self, view, common):
        lo, hi = math.inf, -math.inf
        for i in range(self.first, self.last + 1):
            y = self.height(i, view, common)
            lo = min(lo, y)
            hi = max(hi, y)
        return lo, hi

    def pv(self, view, common):
        lo, hi = self.range(view, common)
        return hi - lo

    def fitted(self, t, view, common):
        """The dashed line of the reference plot at scan distance t, in a view."""
        x = coordinate(self.side, self.direction, t, self.profile.length)
        if view == "raw":
            return self.m * x + self.b - self.mean_z
        if view == "common":
            return (self.m - common) * x
        return 0.0


def fit_profile(profile, side, direction, start, end, skip=0):
    """Least-squares line over the interval [start, end] of scan travel, without the first `skip` samples."""
    limit = max(profile.length, profile.travel)
    if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end > limit + 1e-9 or end <= start:
        raise CalculationError(f"Choose an interval within 0–{_num(limit)} mm, with end greater than start.")
    step = profile.step
    first = max(skip, math.ceil(start / step - 1e-9))
    last = min(profile.count - 1, math.floor(end / step + 1e-9))
    count = last - first + 1
    if count < 3:
        raise CalculationError("Selected interval needs at least three samples.")
    mean_x = mean_z = 0.0
    for i in range(first, last + 1):
        mean_x += coordinate(side, direction, i * step, profile.length)
        mean_z += profile.samples[i] * profile.resolution
    mean_x /= count
    mean_z /= count
    xx = xz = 0.0
    for i in range(first, last + 1):
        dx = coordinate(side, direction, i * step, profile.length) - mean_x
        xx += dx * dx
        xz += dx * (profile.samples[i] * profile.resolution - mean_z)
    m = xz / xx
    return Fit(profile, side, direction, first, last, count, start, end, m, mean_z - m * mean_x, mean_z)


@dataclass(frozen=True)
class Settings:
    od: float
    id: float
    units: str = "in"  # diameter units: in | mm
    light_band_um: float = DEFAULT_LIGHT_BAND_UM
    left_direction: str = DEFAULT_DIRECTIONS["left"]
    right_direction: str = DEFAULT_DIRECTIONS["right"]
    left_start: float = 0.0  # evaluation intervals [mm of scan travel]; None end: whole scan
    left_end: float | None = None
    right_start: float = 0.0
    right_end: float | None = None
    pv_view: str = "common"
    skip_points: int = DEFAULT_SKIP_POINTS  # first samples of each scan left out of fit and P–V
    flat_limit_hlb: float = DEFAULT_FLAT_LIMIT_HLB


@dataclass(frozen=True)
class Result:
    left: Fit
    right: Fit
    settings: Settings
    face_width_mm: float
    common_slope: float  # µm/mm
    taper_um: float  # signed
    taper_hlb: float
    classification: str
    pv: dict = field(default_factory=dict)  # {view: {"left": µm, "right": µm}}

    @property
    def scan_longer_than_face(self):
        """Scan travel exceeds the radial face width: the path is not a full-width radial path."""
        return max(self.left.profile.length, self.right.profile.length) > self.face_width_mm + 0.01

    @property
    def warnings(self):
        """File-reading notices of both scans, each prefixed with its file name."""
        return [f"{fit.profile.name}: {w}" for fit in (self.left, self.right) for w in fit.profile.warnings]


def calculate(left, right, settings):
    if left is None or right is None:
        raise CalculationError("Load both left and right profiles.")
    s = settings
    if s.units not in UNITS or s.left_direction not in DIRECTIONS or s.right_direction not in DIRECTIONS:
        raise CalculationError("Choose valid diameter units and scan directions.")
    if s.pv_view not in VIEWS:
        raise CalculationError("Choose a valid profile view.")
    if not (isinstance(s.skip_points, int) and s.skip_points >= 0):
        raise CalculationError("Skip first points must be a whole number of at least 0.")
    if s.flat_limit_hlb is None or not math.isfinite(s.flat_limit_hlb) or s.flat_limit_hlb < 0:
        raise CalculationError("Enter a flat limit of at least 0 HLB.")
    od, id_, band = s.od, s.id, s.light_band_um
    if any(v is None or not math.isfinite(v) for v in (od, id_, band)) or not (od > id_ >= 0 and band > 0):
        raise CalculationError("Enter OD > ID ≥ 0 and a positive light-band height.")
    width = (od - id_) / 2 * (25.4 if s.units == "in" else 1)
    lfit = fit_profile(left, "left", s.left_direction, s.left_start,
                       max(left.length, left.travel) if s.left_end is None else s.left_end, s.skip_points)  # fmt: skip
    rfit = fit_profile(right, "right", s.right_direction, s.right_start,
                       max(right.length, right.travel) if s.right_end is None else s.right_end, s.skip_points)  # fmt: skip
    common = (lfit.m + rfit.m) / 2
    taper = -(lfit.m - rfit.m) * width / 2
    hlb = taper / band
    pv = {view: {"left": lfit.pv(view, common), "right": rfit.pv(view, common)} for view in VIEWS}
    return Result(lfit, rfit, s, width, common, taper, hlb, classify(hlb, s.flat_limit_hlb), pv)
