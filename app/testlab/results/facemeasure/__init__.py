"""Seal-face measurements from instrument files (M2D, M2F-a).

Pure Python, no Django: parsers and engineering calculations ported from the
lab's offline tools in reference/measurement-tools. Engine version 1 follows
Seal_Face_Measurement_Tools.html; version 2 (M2F-a) follows
Seal_Face_Flatness_Claude_v5.html, with the same formulas and sign conventions:

    mahr.py       Mahr profile TXT (left + right scan): profile P–V, radial taper, roughness as exported
    roundpak.py   ROUNDPAK CSV: instrument flatness result, circular LFD P–V, radial taper, UPR harmonics
    figures.py    deterministic SVG figures of a stored measurement

Taper sign (both instruments): negative = ID high = Convex, positive = OD
high = Concave; within ± the flat limit (default 0.25 helium light bands)
it is Flat.

TestLab stores the original files unchanged and the results calculated
from them at review (results.models.MahrAnalysis / RoundpakAnalysis).
ENGINE names the calculation version a stored result comes from; a change
of a formula changes the version, never a stored result.
"""

BOM = chr(0xFEFF)
MAHR_ENGINE = "mahr-2"
ROUNDPAK_ENGINE = "roundpak-2"

DEFAULT_LIGHT_BAND_UM = 0.29  # template convention: µm per helium light band
DEFAULT_FLAT_LIMIT_HLB = 0.25

FLAT = "Flat"
CONVEX = "Convex"
CONCAVE = "Concave"


class InstrumentFileError(Exception):
    """An instrument file cannot be read; the message says why."""


class CalculationError(Exception):
    """The settings do not allow a result; the message says what to correct."""


def decode(content):
    """Instrument text: UTF-8 when valid (BOM removed), else Windows-1252, as the reference tool reads it."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    return text.removeprefix(BOM)


def classify(hlb, limit_hlb=DEFAULT_FLAT_LIMIT_HLB):
    """Flat within ± the limit [HLB]; below it Convex (ID high), above it Concave (OD high)."""
    if hlb < -limit_hlb:
        return CONVEX
    if hlb > limit_hlb:
        return CONCAVE
    return FLAT
