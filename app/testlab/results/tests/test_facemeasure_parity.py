"""The Python port reproduces the first reference tool (M2D, engine version 1 settings).

golden.json holds the results of Seal_Face_Measurement_Tools.html for the
fixtures, computed by its JavaScript (fixtures/facemeasure/make_golden.py).
Same formulas, same summation order: numbers agree to floating-point noise,
refusals word for word. Version 2 keeps these calculations: with no points
skipped they are reproduced exactly; only the class names changed (Flat /
Convex / Concave) and Mahr files are read leniently, as v5 does
(test_facemeasure_parity_v5.py).
"""

import json
import math

import pytest

from testlab.results.facemeasure import CONCAVE, CONVEX, FLAT, CalculationError, InstrumentFileError, mahr, roundpak

from .facemeasure_variants import (
    FIXTURES, MAHR_LEFT, MAHR_RIGHT, ROUNDPAK_CSV, bad_mahr, bad_roundpak, fixture_text, flagged_roundpak,
)

GOLDEN = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))
TOL = 1e-12
V1_CLASSES = {"Within taper band": FLAT, "Convex taper": CONVEX, "Concave taper": CONCAVE}


def close(a, b):
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=TOL, abs_tol=TOL)


def mahr_settings(o):
    return mahr.Settings(
        od=float(o["od"]), id=float(o["id"]), units=o["units"], light_band_um=float(o["band"]),
        left_direction=o["leftDir"], right_direction=o["rightDir"],
        left_start=float(o["leftStart"]), left_end=float(o["leftEnd"]),
        right_start=float(o["rightStart"]), right_end=float(o["rightEnd"]), skip_points=0,
    )  # fmt: skip


def roundpak_settings(o):
    blank = lambda v: None if v.strip() == "" else float(v)  # noqa: E731
    return roundpak.Settings(
        od=blank(o["od"]), id=blank(o["id"]), units=o["units"], light_band_um=float(o["band"]),
        circle_scan=o["circleSelect"], circle_source=o["circleSource"],
        left_scan=o["leftSelect"], right_scan=o["rightSelect"], radial_source=o["radialSource"],
        left_start=float(o["leftStart"]), left_end=float(o["leftEnd"]),
        right_start=float(o["rightStart"]), right_end=float(o["rightEnd"]),
    )  # fmt: skip


@pytest.fixture(scope="module")
def profiles():
    return mahr.parse(fixture_text(MAHR_LEFT), MAHR_LEFT), mahr.parse(fixture_text(MAHR_RIGHT), MAHR_RIGHT)


@pytest.fixture(scope="module")
def roundpak_files():
    text = fixture_text(ROUNDPAK_CSV)
    return roundpak.parse(text, ROUNDPAK_CSV), roundpak.parse(flagged_roundpak(text), ROUNDPAK_CSV)


def test_mahr_parse_matches(profiles):
    for profile, expected in zip(profiles, GOLDEN["mahr"]["profiles"]):
        assert profile.count == expected["count"] and profile.spacing_count == expected["count"]
        assert profile.length == expected["length"]
        assert profile.resolution == expected["resolution"]
        assert profile.reported == expected["reported"]
        assert profile.headers == expected["headers"]


@pytest.mark.parametrize("case", range(len(GOLDEN["mahr"]["cases"])))
def test_mahr_calculation_matches(profiles, case):
    expected = GOLDEN["mahr"]["cases"][case]
    left, right = profiles[::-1] if expected["options"].get("swap") else profiles
    result = mahr.calculate(left, right, mahr_settings(expected["options"]))
    assert close(result.face_width_mm, expected["width"])
    assert close(result.common_slope, expected["common"])
    assert close(result.taper_um, expected["taper"])
    assert close(result.taper_hlb, expected["hlb"])
    assert result.classification == V1_CLASSES[expected["classification"]]
    for side, fit in (("left", result.left), ("right", result.right)):
        assert (fit.first, fit.last) == (expected[side]["first"], expected[side]["last"])
        assert close(fit.m, expected[side]["m"]) and close(fit.b, expected[side]["b"])
        assert close(fit.mean_z, expected[side]["meanZ"])
        for view in mahr.VIEWS:
            assert close(result.pv[view][side], expected["pv"][view][side])


@pytest.mark.parametrize("case", range(len(GOLDEN["mahr"]["errors"])))
def test_mahr_refusals_match(profiles, case):
    expected = GOLDEN["mahr"]["errors"][case]
    with pytest.raises(CalculationError) as error:
        mahr.calculate(*profiles, mahr_settings(expected["options"]))
    assert str(error.value) == expected["error"]


def test_mahr_files_v1_refused_are_read_with_a_warning_or_refused_as_v5():
    """v1 refused all four files; v5 (and mahr-2) reads three of them with a warning."""
    bad = {b["label"]: b["text"] for b in bad_mahr(fixture_text(MAHR_LEFT))}
    assert {e["label"] for e in GOLDEN["mahr"]["parse_errors"]} == set(bad)
    for label in ("count_mismatch", "non_numeric", "no_cnt"):
        assert mahr.parse(bad[label]).warnings, label
    with pytest.raises(InstrumentFileError, match=r"resolution \(RES=\)"):
        mahr.parse(bad["zero_res"])


def test_roundpak_parse_matches(roundpak_files):
    for file, expected_scans in zip(roundpak_files, (GOLDEN["roundpak"]["scans"], GOLDEN["roundpak"]["flagged_scans"])):
        assert len(file.scans) == len(expected_scans)
        for scan, expected in zip(file.scans, expected_scans):
            assert (scan.id, scan.kind, scan.name, scan.curve) == (
                expected["id"], expected["kind"], expected["name"], expected["curve"])
            assert len(scan.points) == expected["points"] and scan.flagged == expected["flagged"]
            assert (scan.min, scan.max, scan.complete) == (expected["min"], expected["max"], expected["complete"])
            assert scan.params == expected["params"] and scan.line == expected["line"]
            assert scan.meta == expected["meta"]


def _evaluation_matches(evaluation, expected):
    if expected is None:
        return evaluation is None
    return (
        evaluation.source == expected["source"]
        and close(evaluation.start, expected["start"]) and close(evaluation.end, expected["end"])
        and len(evaluation.selected) == expected["selected"] and len(evaluation.used) == expected["used"]
        and close(evaluation.lo, expected["lo"]) and close(evaluation.hi, expected["hi"])
        and close(evaluation.pv, expected["pv"])
        and close(evaluation.m, expected["m"]) and close(evaluation.b, expected["b"])
        and evaluation.min_point.x == expected["min_x"] and evaluation.max_point.x == expected["max_x"]
    )


@pytest.mark.parametrize("case", range(len(GOLDEN["roundpak"]["cases"])))
def test_roundpak_calculation_matches(roundpak_files, case):
    expected = GOLDEN["roundpak"]["cases"][case]
    file = roundpak_files[1] if expected["options"].get("flagged") else roundpak_files[0]
    result = roundpak.calculate(file, roundpak_settings(expected["options"]))
    for name in ("circular", "lfd", "left", "right"):
        assert _evaluation_matches(getattr(result, name), expected[name]), name
    assert close(result.reported_flatness_um, expected["reported"])
    assert close(result.face_width_mm, expected["width"])
    assert close(result.mean_slope, expected["meanSlope"])
    assert close(result.taper_um, expected["taper"])
    assert close(result.separation_deg, expected["separation"])


@pytest.mark.parametrize("case", range(len(GOLDEN["roundpak"]["errors"])))
def test_roundpak_refusals_match(roundpak_files, case):
    expected = GOLDEN["roundpak"]["errors"][case]
    with pytest.raises(CalculationError) as error:
        roundpak.calculate(roundpak_files[0], roundpak_settings(expected["options"]))
    assert str(error.value) == expected["error"]


def test_roundpak_file_refusals_match():
    bad = {b["label"]: b["text"] for b in bad_roundpak(fixture_text(ROUNDPAK_CSV))}
    for expected in GOLDEN["roundpak"]["parse_errors"]:
        with pytest.raises(InstrumentFileError) as error:
            roundpak.parse(bad[expected["label"]])
        assert str(error.value) == expected["error"], expected["label"]


def test_roundpak_default_scan_choice_follows_the_reference_tool(roundpak_files):
    """Left = second radial block, right = first (Excel template assignment)."""
    result = roundpak.calculate(roundpak_files[0], roundpak.Settings())
    first_case = GOLDEN["roundpak"]["cases"][0]["options"]
    assert (result.settings.left_scan, result.settings.right_scan) == (first_case["leftSelect"], first_case["rightSelect"])
    assert close(result.lfd.pv, GOLDEN["roundpak"]["cases"][0]["lfd"]["pv"])


def test_instrument_flatness_is_never_replaced_by_the_viewer_value(roundpak_files):
    result = roundpak.calculate(roundpak_files[1], roundpak.Settings())
    assert result.reported_flatness_um == 0.296  # exported FLTt, unchanged by deleted points
    assert result.lfd.pv != result.reported_flatness_um
