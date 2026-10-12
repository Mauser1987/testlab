"""The workbook's header information against the target run (M2F).

The header above the log table (project number, run, test unit, speed,
pressure, medium, seal type, face serial numbers…) is context: it is shown
next to what TestLab holds for the run and its TCN, and mismatches are
shown prominently and must be acknowledged before importing. Nothing in
the run or its TCN is ever changed from the workbook. Items TestLab has no
field for (torques, "Aligned", "Data not Logged"…) are kept and shown as
they are, without meaning.
"""

import re

from .. import manual_log

MATCH, MISMATCH, NO_VALUE, INFO = "match", "mismatch", "no_value", "info"


def _words(text):
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def _first_number(text):
    match = re.search(r"-?\d+(?:[.,]\d+)?", text or "")
    return float(match.group(0).replace(",", ".")) if match else None


def _squash(text):
    return re.sub(r"\s+", "", (text or "")).casefold()


def _numbers_equal(value, testlab):
    a, b = _first_number(value), _first_number(testlab)
    if a is None or b is None:
        return _squash(value) == _squash(testlab)
    return a == b


def _text_equal(value, testlab):
    return _squash(value) == _squash(testlab) or (_squash(testlab) and _squash(testlab) in _squash(value)) or (
        _squash(value) and _squash(value) in _squash(testlab))


def _rules(test_run):
    setup = manual_log.run_setup(test_run)
    positions = list(setup.positions.all())

    def position_values(field):
        return [(p.get_role_display(), getattr(p, field)) for p in positions if getattr(p, field)]

    def any_position(field):
        def compare(value):
            found = position_values(field)
            if not found:
                return NO_VALUE, ""
            shown = "; ".join(f"{role}: {text}" for role, text in found)
            return (MATCH if any(_text_equal(value, text) for _, text in found) else MISMATCH), shown
        return compare

    def single(testlab, equal):
        def compare(value):
            if not testlab:
                return NO_VALUE, ""
            return (MATCH if equal(value, testlab) else MISMATCH), testlab
        return compare

    def run_no(value):
        digits = re.findall(r"\d+", value or "")
        if not digits:
            return MISMATCH, f"Run {test_run.display_no}"
        return (MATCH if int(digits[-1]) == test_run.run_no else MISMATCH), f"Run {test_run.display_no}"

    def medium(words):
        if words & {"process"}:
            return setup.process_medium
        if words & {"barrier", "buffer", "flush", "support"}:
            return setup.seal_support_medium
        return setup.seal_support_medium or setup.process_medium

    pressure = setup.process_pressure if setup.plug_seal_present else setup.seal_support_pressure
    return [
        ("Project number", lambda w: "project" in w,
         single(test_run.project.project_no, lambda a, b: _squash(a) == _squash(b))),
        ("Run / TCN", lambda w: "run" in w or "tcn" in w, run_no),
        ("Test unit", lambda w: "unit" in w and "test" in w, single(setup.test_unit, lambda a, b: _squash(a) == _squash(b))),
        ("Speed", lambda w: "speed" in w, single(setup.speed, _numbers_equal)),
        ("Pressure", lambda w: bool(w & {"pres", "press", "pressure"}), single(pressure, _numbers_equal)),
        ("Medium", lambda w: "medium" in w, None),  # needs the label's words: see check()
        ("Seal type", lambda w: "seal" in w and "type" in w, any_position("seal_type_size")),
        ("Stationary face", lambda w: "face" in w and bool(w & {"stat", "stationary", "stator"}),
         any_position("stationary_face")),
        ("Rotating face", lambda w: "face" in w and bool(w & {"rot", "rotating", "rotor"}),
         any_position("rotating_face")),
    ], medium  # fmt: skip


def check(test_run, header_items):
    """[{"cell", "label", "value", "field", "testlab", "status"}] for the header items, in sheet order."""
    rules, medium = _rules(test_run)
    checked = []
    for item in header_items:
        entry = {"cell": item["cell"], "label": item["label"].strip(), "value": item["value"].strip(),
                 "value_cell": item.get("value_cell", ""), "role": item.get("role", ""), "field": "",
                 "testlab": "", "status": INFO}  # fmt: skip
        words = _words(item["label"])
        if item["label"] and item["value"].strip() and item.get("role") != "list":
            for name, applies, compare in rules:
                if applies(words):
                    entry["field"] = name
                    if compare is None:  # medium
                        testlab = medium(words)
                        entry["status"], entry["testlab"] = (
                            (MATCH if _text_equal(item["value"], testlab) else MISMATCH, testlab) if testlab
                            else (NO_VALUE, ""))  # fmt: skip
                    else:
                        entry["status"], entry["testlab"] = compare(item["value"])
                    break
        checked.append(entry)
    return checked


def mismatches(checked):
    return [item for item in checked if item["status"] == MISMATCH]
