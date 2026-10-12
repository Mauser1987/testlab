"""Engines mahr-2 / roundpak-2 reproduce Seal_Face_Flatness_Claude_v5.html (M2F-a).

golden_v5.json holds v5's own results for the fixtures, read from the page
driven in Chromium (fixtures/facemeasure/make_golden_v5.py). v5 sums the
least-squares terms in another order (n·Σxy − Σx·Σy), so fitted values
agree to 1e-9 relative, not to the last bit; classifications and file
refusals agree exactly.
"""

import json
import math

import pytest

from testlab.results.facemeasure import InstrumentFileError, mahr, roundpak

from .facemeasure_variants import (
    FIXTURES, MAHR_LEFT, MAHR_RIGHT, ROUNDPAK_CSV, V5_ROUNDPAK_COLUMNS, fixture_text, flagged_roundpak, lenient_mahr,
)

GOLDEN = json.loads((FIXTURES / "golden_v5.json").read_text(encoding="utf-8"))
TOL = 1e-9
V5_VIEWS = {"common": "common", "raw": "raw", "resid": "residual"}


def close(a, b, tol=TOL):
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=tol, abs_tol=1e-12)


def mahr_settings(o):
    return mahr.Settings(od=float(o["od"]), id=float(o["id"]), units=o["unit"], light_band_um=float(o["hlb"]),
                         skip_points=int(o["skip"]), flat_limit_hlb=float(o["lim"]))  # fmt: skip


def roundpak_settings(o):
    blank = lambda v: None if v.strip() == "" else float(v)  # noqa: E731
    source = V5_ROUNDPAK_COLUMNS[o["col"]]
    return roundpak.Settings(od=blank(o["od"]), id=blank(o["id"]), units=o["unit"], light_band_um=float(o["hlb"]),
                             circle_source=source, radial_source=source, flat_limit_hlb=float(o["lim"]))  # fmt: skip


@pytest.fixture(scope="module")
def profiles():
    return mahr.parse(fixture_text(MAHR_LEFT), MAHR_LEFT), mahr.parse(fixture_text(MAHR_RIGHT), MAHR_RIGHT)


def assert_mahr(result, expected):
    for side, fit in (("left", result.left), ("right", result.right)):
        assert fit.count == expected[side]["n"]
        assert close(fit.m, expected[side]["m"]) and close(fit.b, expected[side]["b"])
        assert close(fit.mean_z, expected[side]["mean"])
    assert close(result.common_slope, expected["common"])
    assert close(result.face_width_mm, expected["width"])
    assert close(result.taper_um, expected["taper"]) and close(result.taper_hlb, expected["hlb"])
    assert result.classification == expected["verdict"]
    for v5_view, view in V5_VIEWS.items():
        assert close(result.pv[view]["left"], expected["pv"][v5_view]["L"])
        assert close(result.pv[view]["right"], expected["pv"][v5_view]["R"])


@pytest.mark.parametrize("case", range(len(GOLDEN["mahr"]["cases"])))
def test_mahr_matches_v5(profiles, case):
    expected = GOLDEN["mahr"]["cases"][case]
    left, right = profiles[::-1] if expected["options"].get("swap") else profiles
    assert_mahr(mahr.calculate(left, right, mahr_settings(expected["options"])), expected)


def test_mahr_defaults_are_v5_defaults(profiles):
    """Skip 5 points, ±0.25 HLB, 0.29 µm light band, common view: v5's sample settings."""
    expected = GOLDEN["mahr"]["cases"][0]
    assert expected["options"] | {"od": "", "id": ""} == {
        "od": "", "id": "", "unit": "in", "skip": "5", "hlb": "0.29", "lim": "0.25"}
    result = mahr.calculate(*profiles, mahr.Settings(od=5.084, id=4.634))
    assert result.settings.pv_view == "common"
    assert_mahr(result, expected)


@pytest.mark.parametrize("variant", lenient_mahr(fixture_text(MAHR_LEFT)), ids=lambda v: v["label"])
def test_mahr_lenient_reading_matches_v5(profiles, variant):
    expected = next(e for e in GOLDEN["mahr"]["lenient"] if e["label"] == variant["label"])
    if expected["error"]:
        with pytest.raises(InstrumentFileError) as error:
            mahr.parse(variant["text"], "x")
        assert str(error.value) == expected["error"]
        return
    left = mahr.parse(variant["text"], "x")
    assert left.count == expected["count"] and left.spacing_count == expected["spacing"]
    if expected["warning"]:
        assert expected["warning"] in left.warnings
    assert_mahr(mahr.calculate(left, profiles[1], mahr.Settings(od=5.084, id=4.634)), expected)


@pytest.fixture(scope="module")
def roundpak_files():
    text = fixture_text(ROUNDPAK_CSV)
    return roundpak.parse(text, ROUNDPAK_CSV), roundpak.parse(flagged_roundpak(text), ROUNDPAK_CSV)


@pytest.mark.parametrize("case", range(len(GOLDEN["roundpak"]["cases"])))
def test_roundpak_matches_v5(roundpak_files, case):
    expected = GOLDEN["roundpak"]["cases"][case]
    file = roundpak_files[1] if expected["options"].get("flagged") else roundpak_files[0]
    result = roundpak.calculate(file, roundpak_settings(expected["options"]))
    circular = result.circular
    assert close(circular.pv, expected["wav"]) and close(circular.hi, expected["hi"]) and close(circular.lo, expected["lo"])
    assert circular.max_point.x == expected["angHi"] and circular.min_point.x == expected["angLo"]
    # v5 trace 1 is the first radial block (TestLab's default right scan), trace 2 the second (left).
    first, second = expected["traces"]
    assert close(result.right.m, first["m"]) and len(result.right.used) == first["n"]
    assert close(result.left.m, second["m"]) and len(result.left.used) == second["n"]
    assert close(result.mean_slope, expected["cone"]) and close(result.tilt_slope, expected["tilt"])
    assert close(result.face_width_mm, expected["width"])
    assert close(result.taper_um, expected["taper"]) and close(result.taper_hlb, expected["hlb"])
    assert (result.classification or None) == expected["verdict"]
    assert len(result.harmonics) == len(expected["harm"]) == 30
    for (k, amp, phase), (ek, eamp, ephase) in zip(result.harmonics, expected["harm"]):
        assert k == ek and close(amp, eamp, 1e-7) and math.isclose(phase, ephase, abs_tol=1e-5)
