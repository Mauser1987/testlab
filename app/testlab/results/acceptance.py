"""Acceptance assessment of a Result (M2B): no rules engine.

Each AcceptanceItem holds a criterion, a requirement and the engineer's
remark. Its actual is typed by the engineer or derived from structured
evidence (evidence.py):

    leakage_rate   average leakage rate of a seal [ml/h]   Σ volume / Σ period
    wear_rate      face wear rate of a component [in/h]    (Pre − Post face length) / period
    logged_hours   logged period, clock time [h]           reference only

Assessment, in this order:

1. the engineer's assessment, when set (Pass, Fail, Not evaluated, Not applicable);
2. otherwise Pass/Fail is derived — only when the actual is derived, the
   requirement is a numeric limit (≤ or ≥) in the actual's unit, and the
   basis allows it;
3. otherwise Not evaluated: the engineer has to assess it.

Logged hours are never assessed automatically: they are clock time, static
periods included, so they do not answer a running-time requirement such as
"≥ 72 h" by themselves. Nothing is ever derived from a graph.
"""

from dataclasses import dataclass

from .models import AcceptanceItem, Assessment

Basis = AcceptanceItem.Basis

BASIS_UNITS = {Basis.LEAKAGE_RATE: "ml/h", Basis.WEAR_RATE: "in/h", Basis.LOGGED_HOURS: "h"}
AUTO_ASSESSED = {Basis.LEAKAGE_RATE, Basis.WEAR_RATE}


@dataclass
class Evidence:
    """The derived figures an assessment can refer to."""

    leakage: list  # evidence.SealLeakage
    wear: list  # evidence.ComponentWear
    period: object  # evidence.LoggedPeriod


@dataclass
class Evaluation:
    item: AcceptanceItem
    actual: float | None  # derived actual
    actual_text: str  # as shown
    source: str  # where a derived actual comes from, or why there is none
    derived: str  # derived Pass/Fail, or ""
    effective: str  # Assessment value shown
    by: str  # "engineer", "calculated" or ""

    @property
    def effective_label(self):
        return Assessment(self.effective).label

    @property
    def requirement(self):
        item = self.item
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
    if basis == Basis.LOGGED_HOURS:
        return f"{value:.2f}"
    return format_number(value)


def derived_actual(item, evidence):
    """(value, source) of a derived basis; value None with the reason when the evidence does not give one."""
    if item.basis == Basis.LEAKAGE_RATE:
        seal = next((s for s in evidence.leakage if s.position == item.position), None)
        if seal is None:
            return None, "no leakage logged for this seal"
        if seal.average is None:
            return None, seal.reason
        return seal.average, f"{seal.rated_volume.normalize():f} ml / {seal.hours:.2f} h, manual log"
    if item.basis == Basis.WEAR_RATE:
        wear = next((w for w in evidence.wear if w.component.pk == item.component_id), None)
        if wear is None:
            return None, "no face length entered for this component"
        if wear.rate is None:
            return None, "Pre or Post face length missing" if wear.wear is None else wear.hours_source
        return wear.rate, f"{format_number(wear.wear)} in / {wear.hours:.2f} h ({wear.hours_source})"
    if item.basis == Basis.LOGGED_HOURS:
        if evidence.period.hours is None:
            return None, "no manual log or DCS recording"
        return evidence.period.hours, f"{evidence.period.start_source} → {evidence.period.end_source}"
    return None, ""


def _compare(actual, comparison, limit):
    limit = float(limit)
    ok = actual <= limit if comparison == AcceptanceItem.Comparison.AT_MOST else actual >= limit
    return Assessment.PASS if ok else Assessment.FAIL


def evaluate(item, evidence):
    if item.basis == Basis.MANUAL:
        actual, actual_text, source, derived = None, item.actual_text, "", ""
    else:
        actual, source = derived_actual(item, evidence)
        actual_text = f"{format_actual(item.basis, actual)} {BASIS_UNITS[item.basis]}" if actual is not None else ""
        derived = ""
        if (
            actual is not None
            and item.basis in AUTO_ASSESSED
            and item.comparison
            and item.limit is not None
            and item.unit == BASIS_UNITS[item.basis]
        ):
            derived = _compare(actual, item.comparison, item.limit)
    if item.assessment:
        effective, by = item.assessment, "engineer"
    elif derived:
        effective, by = derived, "calculated"
    else:
        effective, by = Assessment.NOT_EVALUATED, ""
    return Evaluation(item, actual, actual_text, source, derived, effective, by)


def evaluate_all(items, evidence):
    return [evaluate(item, evidence) for item in items]
