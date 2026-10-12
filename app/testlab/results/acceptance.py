"""Acceptance assessment of a Result (M2B, M2E): no rules engine.

Each AcceptanceItem holds a criterion, a requirement and the engineer's
remark. Its requirement comes from the Test Program, from an approved
(issued) TCN change that overrides it for the run, or is entered on the
Result (requirements.py keeps the first two in step and records the
source). Its actual is typed by the engineer or derived from structured
evidence (evidence.py, runtime.py):

    leakage_rate    average dynamic leakage of a seal [ml/h]   Σ dynamic volumes / Σ their running hours
    wear_rate       face wear rate of a component [in/h]       (Pre − Post face length) / running hours
    running_hours   shaft-running hours [h]                    test duration, unless the requirement
    logged_hours    elapsed clock time [h]                     explicitly asks for elapsed time

Assessment, in this order:

1. the engineer's assessment, when set (Pass, Fail, Not evaluated, Not applicable);
2. otherwise Pass/Fail is derived — only when the actual is derived, the
   requirement is a numeric limit (≤ or ≥), its unit is the actual's unit
   or converts to it unambiguously, and the evidence decides the comparison
   (for running hours: unknown periods could be running or not, so a
   shortfall is only a Fail when no period is unknown);
3. otherwise the item is not assessed: missing, which blocks finalization.
   An explicit Not evaluated or Not applicable is an assessment, not missing.

Nothing is ever derived from a graph or from an operating set point.
"""

import re
from dataclasses import dataclass

from .models import AcceptanceItem, Assessment

Basis = AcceptanceItem.Basis

BASIS_UNITS = {Basis.LEAKAGE_RATE: "ml/h", Basis.WEAR_RATE: "in/h", Basis.RUNNING_HOURS: "h", Basis.LOGGED_HOURS: "h"}
AUTO_ASSESSED = {Basis.LEAKAGE_RATE, Basis.WEAR_RATE, Basis.RUNNING_HOURS, Basis.LOGGED_HOURS}

NOT_ASSESSED = ""
NOT_ASSESSED_LABEL = "Not assessed"

# Units a requirement may be written in, as (dimension, factor to the base unit of the dimension).
# Mass rates (g/h) are not volume rates: not comparable without a density, so not listed.
_UNITS = {
    "ml/h": ("volume_rate", 1.0), "cc/h": ("volume_rate", 1.0), "cm3/h": ("volume_rate", 1.0),
    "cm³/h": ("volume_rate", 1.0), "ml/hr": ("volume_rate", 1.0), "cc/hr": ("volume_rate", 1.0),
    "ml/min": ("volume_rate", 60.0), "cc/min": ("volume_rate", 60.0), "l/h": ("volume_rate", 1000.0),
    "in/h": ("length_rate", 25.4), "in/hr": ("length_rate", 25.4), "mm/h": ("length_rate", 1.0),
    "mm/hr": ("length_rate", 1.0), "µm/h": ("length_rate", 0.001), "um/h": ("length_rate", 0.001),
    "h": ("time", 1.0), "hr": ("time", 1.0), "hrs": ("time", 1.0), "hours": ("time", 1.0), "hour": ("time", 1.0),
}  # fmt: skip


def _unit(text):
    return _UNITS.get(re.sub(r"\s+", "", (text or "").lower()))


def convert(value, from_unit, to_unit):
    """value in from_unit expressed in to_unit, or None when the units are not the same dimension."""
    a, b = _unit(from_unit), _unit(to_unit)
    if a is None or b is None or a[0] != b[0]:
        return None
    return value * a[1] / b[1]


@dataclass
class Evidence:
    """The derived figures an assessment can refer to."""

    leakage: list  # evidence.SealLeakage
    wear: list  # evidence.ComponentWear
    period: object  # evidence.LoggedPeriod
    timeline: object = None  # runtime.RunTimeline


@dataclass
class Evaluation:
    item: AcceptanceItem
    actual: float | None  # derived actual, in actual_unit
    actual_text: str  # as shown
    source: str  # where a derived actual comes from, or why there is none
    derived: str  # derived Pass/Fail, or ""
    effective: str  # Assessment value, or NOT_ASSESSED
    by: str  # "engineer", "calculated" or ""
    note: str = ""  # why Pass/Fail was not calculated
    actual_unit: str = ""

    @property
    def missing(self):
        return self.effective == NOT_ASSESSED

    @property
    def effective_label(self):
        return NOT_ASSESSED_LABEL if self.missing else Assessment(self.effective).label

    @property
    def requirement(self):
        return requirement_text(self.item)


def requirement_text(item):
    if item.comparison:
        limit = format_number(item.limit)
        text = f"{AcceptanceItem.Comparison(item.comparison).label} {limit} {item.unit}".strip()
        return f"{text} — {item.requirement_text}" if item.requirement_text else text
    return item.requirement_text


def format_number(value):
    """Plain decimal for ordinary numbers, scientific for very small ones (wear rates)."""
    if value is None:
        return ""
    number = float(value)
    if number != 0 and abs(number) < 0.0001:
        mantissa, exponent = f"{number:.2E}".split("E")
        return f"{mantissa.rstrip('0').rstrip('.')}E{int(exponent)}"
    text = format(value.normalize(), "f") if hasattr(value, "normalize") else f"{number:.6g}"
    return text


def format_actual(basis, value):
    """Shown precision of a derived actual; the comparison always uses the unrounded value."""
    if basis == Basis.LEAKAGE_RATE:
        return f"{value:.1f}"
    if basis in (Basis.LOGGED_HOURS, Basis.RUNNING_HOURS):
        return f"{value:.2f}"
    return format_number(value)


def derived_actual(item, evidence):
    """(value, unit, source) of a derived basis; value None with the reason when the evidence gives none."""
    if item.basis == Basis.LEAKAGE_RATE:
        seal = next((s for s in evidence.leakage if s.position == item.position), None)
        if seal is None:
            return None, "ml/h", "no leakage logged for this seal"
        if seal.average is None:
            return None, "ml/h", seal.reason
        return seal.average, "ml/h", (
            f"{format_number(seal.dynamic_volume)} ml / {seal.dynamic_hours:.2f} running h "
            f"({len(seal.dynamic)} dynamic collection{'s' if len(seal.dynamic) != 1 else ''}, manual log)"
        )
    if item.basis == Basis.WEAR_RATE:
        wear = next((w for w in evidence.wear if w.component.pk == item.component_id), None)
        if item.component_id is None:
            return None, "in/h", "no such component in the Result"
        if wear is None:
            return None, "in/h", "no face length entered for this component"
        unit = f"{wear.unit}/h"
        if wear.rate is None:
            return None, unit, wear.reason
        return wear.rate, unit, f"{format_number(wear.loss)} {wear.unit} / {wear.hours:.2f} running h"
    timeline = evidence.timeline
    if item.basis == Basis.RUNNING_HOURS:
        if timeline is None or not timeline.known:
            return None, "h", "no manual log or DCS recording"
        unknown = f"; {timeline.unknown_h:.2f} h unknown" if timeline.unknown_h > 1e-6 else ""
        source = "shaft-running hours" if timeline.sources else "no evidence of the shaft running"
        return timeline.running_h, "h", f"{source}{unknown}"
    if item.basis == Basis.LOGGED_HOURS:
        if evidence.period.hours is None:
            return None, "h", "no manual log or DCS recording"
        return evidence.period.hours, "h", f"elapsed: {evidence.period.start_source} → {evidence.period.end_source}"
    return None, "", ""


def _compare(actual, comparison, limit):
    ok = actual <= limit if comparison == AcceptanceItem.Comparison.AT_MOST else actual >= limit
    return Assessment.PASS if ok else Assessment.FAIL


def calculated_assessment(item, actual, actual_unit, evidence):
    """(Pass/Fail or "", note why not)."""
    if actual is None or item.basis not in AUTO_ASSESSED:
        return "", ""
    if not item.comparison or item.limit is None:
        return "", "no numeric limit"
    limit = convert(float(item.limit), item.unit, actual_unit)
    if limit is None:
        return "", f"requirement unit “{item.unit or 'none'}” is not comparable with {actual_unit}"
    if item.basis == Basis.RUNNING_HOURS:
        # Unknown periods may or may not have been running: the true running hours lie between the
        # known ones and known + unknown. Only a result both ends agree on is calculated.
        unknown = evidence.timeline.unknown_h if evidence.timeline and evidence.timeline.known else 0.0
        low, high = _compare(actual, item.comparison, limit), _compare(actual + unknown, item.comparison, limit)
        if low != high:
            return "", f"{unknown:.2f} h with unknown running state could change the result"
        return low, ""
    return _compare(actual, item.comparison, limit), ""


def evaluate(item, evidence):
    note, actual_unit = "", ""
    if item.basis == Basis.MANUAL:
        actual, actual_text, source, derived = None, item.actual_text, "", ""
    else:
        actual, actual_unit, source = derived_actual(item, evidence)
        actual_text = f"{format_actual(item.basis, actual)} {actual_unit}" if actual is not None else ""
        derived, note = calculated_assessment(item, actual, actual_unit, evidence)
    if item.assessment:
        effective, by = item.assessment, "engineer"
    elif derived:
        effective, by = derived, "calculated"
    else:
        effective, by = NOT_ASSESSED, ""
    return Evaluation(item, actual, actual_text, source, derived, effective, by, note, actual_unit)


def evaluate_all(items, evidence):
    return [evaluate(item, evidence) for item in items]
