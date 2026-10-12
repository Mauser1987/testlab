"""Shown precision, shared by the Result page and the report.

Seal-face values (M2D): instrument values keep the instrument's precision
(FLTt, Ra: 3 decimals); calculated values the reference viewers' (taper,
LFD P–V: 4).

Operating values in the report's Test Conditions & Results (report_number):
by unit — speed in whole rpm; pressure, temperature, flow, torque and
leakage rate to 1 decimal; hours to 2. Other units as recorded.

Display only: stored and compared values are never rounded.
"""

import re

from .acceptance import format_number

QUANTITY_DIGITS = {"face_flatness": 3, "face_taper": 4, "face_taper_roundpak": 4, "roughness_ra": 3}
SIGNED_QUANTITIES = {"face_taper", "face_taper_roundpak"}


def fixed(value, digits=3):
    """0.2958 (digits 4); None → ""."""
    if value in (None, ""):
        return ""
    return f"{float(value):.{int(digits)}f}"


def signed_fixed(value, digits=3):
    """+0.0661, −0.0186; zero without a sign."""
    if value in (None, ""):
        return ""
    text = f"{abs(float(value)):.{int(digits)}f}"
    if float(text) == 0:
        return text
    return f"+{text}" if value > 0 else f"−{text}"


def signed(value):
    """A difference with its sign at its own precision: +0.066, −0.00012."""
    if value in (None, ""):
        return ""
    text = format_number(abs(value))
    if value > 0:
        return f"+{text}"
    if value < 0:
        return f"−{text}"
    return text


def quantity_value(value, code):
    if value in (None, ""):
        return ""
    if code in QUANTITY_DIGITS:
        digits = QUANTITY_DIGITS[code]
        return signed_fixed(value, digits) if code in SIGNED_QUANTITIES else fixed(value, digits)
    return format_number(value)


def quantity_delta(value, code):
    if value in (None, ""):
        return ""
    return signed_fixed(value, QUANTITY_DIGITS[code]) if code in QUANTITY_DIGITS else signed(value)


# Decimals of an operating value in the report, by unit (lower case, spaces removed).
REPORT_DIGITS = {
    "rpm": 0,
    "barg": 1, "bar": 1, "bara": 1, "°c": 1, "l/min": 1, "nm": 1, "ml/h": 1,
    "h": 2,
}  # fmt: skip


def report_digits(unit):
    return REPORT_DIGITS.get(re.sub(r"\s+", "", (unit or "").lower()))


def report_number(value, unit):
    """47.682 barg → "47.7", 2987.4 rpm → "2987"; a unit without a rule: as recorded. None → ""."""
    if value in (None, ""):
        return ""
    digits = report_digits(unit)
    if digits is None:
        return format_number(value)
    text = f"{float(value):.{digits}f}"
    return text.lstrip("-") if float(text) == 0 else text  # no "-0.0"


def report_range(low, high, unit):
    """"29.8 – 31.0"; one value when both show the same."""
    a, b = report_number(low, unit), report_number(high, unit)
    return a if a == b else f"{a} – {b}"
