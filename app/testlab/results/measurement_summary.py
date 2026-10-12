"""Pre/Post measurement summary and completeness of a Result (M2D).

Nothing here is stored or typed: every value comes from the reported
measurement of its slot (component, stage, kind), the reviewed measurement
the engineer accepted (seal_faces.py).

    Face flatness (circular trace)   ROUNDPAK   instrument flatness FLTt, as exported         µm (HLB)
    Face taper (Mahr)                Mahr       signed opposing-scan taper + classification   µm (HLB)
    Face taper (ROUNDPAK)            ROUNDPAK   signed radial-trace taper + classification    µm (HLB)
    Face length                      Manual     dimensional reading; wear = Pre − Post         in
    Roughness Ra                     Mahr       mean of the left and right scans' Ra           µm

Both tapers are shown (M2F-a); the Mahr one is the more accurate. Profile
P–V (Mahr) is a detail result, never a summary quantity. Δ = Post − Pre
for every quantity; only face length has a wear meaning.

A sleeve or backing ring has a plain dimension instead of the face length
(named by the reading's measured feature; Δ only, no wear).

Completeness of every slot (finalization.py):

    completed        a reviewed measurement is reported (required or optional)
    in_review        only Draft measurements so far
    missing          required, nothing measured — blocks finalization
    optional         optional, not measured — never missing, no row in the summary or report
    not_applicable   nothing expected; no row in the summary or the report

A component that was never added (an optional part not inspected) has no
slots at all.
"""

from dataclasses import dataclass, field

from . import inspection
from .inspection import Applicability, MeasurementKind, Stage

COMPLETED = "completed"
IN_REVIEW = "in_review"
MISSING = "missing"
OPTIONAL = "optional"
NOT_APPLICABLE = "not_applicable"

STATUS_LABELS = {
    COMPLETED: "measured",
    IN_REVIEW: "in review",
    MISSING: "missing",
    OPTIONAL: "optional — not measured",
    NOT_APPLICABLE: "not applicable",
}


def measurements_of(component):
    """The component's measurements (uses a prefetch when there is one)."""
    return list(component.face_measurements.all())


def reported(measurements, stage, kind):
    return next((m for m in measurements if m.stage == stage and m.kind == kind and m.reported), None)


def slot_status(component, kind, stage, measurements=None):
    applicability = component.applicability(kind)
    if applicability == Applicability.NOT_APPLICABLE:
        return NOT_APPLICABLE
    measurements = measurements_of(component) if measurements is None else measurements
    if reported(measurements, stage, kind):
        return COMPLETED
    if any(m.stage == stage and m.kind == kind for m in measurements):
        return IN_REVIEW
    return MISSING if applicability == Applicability.REQUIRED else OPTIONAL


@dataclass
class Value:
    measurement: object  # the reported FaceMeasurement, or None
    status: str
    value: object = None  # Decimal (face length) or float; None when missing or not exported
    hlb: float | None = None
    classification: str = ""
    note: str = ""  # e.g. "not exported", "Ra of one scan only"


def quantity_value(measurement, code, status):
    if measurement is None:
        return Value(None, status)
    found = Value(measurement, status)
    if code == "face_flatness":
        analysis = measurement.roundpak
        found.value, found.hlb = analysis.flatness_um, analysis.flatness_hlb
        if analysis.flatness_um is None:
            found.note = "flatness not exported"
    elif code == "face_taper":
        analysis = measurement.mahr
        found.value, found.hlb = analysis.taper_um, analysis.taper_hlb
        found.classification = analysis.classification
    elif code == "face_taper_roundpak":
        analysis = measurement.roundpak
        found.value, found.hlb = analysis.taper_um, analysis.taper_hlb
        found.classification = analysis.classification
        if analysis.taper_um is None:
            found.note = "two radial traces needed" if analysis.mean_slope is None else "face OD/ID not entered"
        elif not analysis.classification:
            found.note = f"not classified ({measurement.engine})"
    elif code == "roughness_ra":
        analysis = measurement.mahr
        found.value = analysis.mean_ra_um
        exported = [v for v in (analysis.left_ra_um, analysis.right_ra_um) if v is not None]
        if not exported:
            found.note = "Ra not exported"
        elif len(exported) == 1:
            found.note = "Ra of one scan only"
    elif code in ("face_length", "dimension"):
        found.value = measurement.dimensional.value
    return found


@dataclass
class SummaryRow:
    component: object  # ResultComponent
    quantity: inspection.Quantity
    pre: Value
    post: Value
    unit: str
    source: str
    delta: object = None
    wear: object = None
    feature: str = ""  # measured feature of a plain dimension (sleeve, backing ring)

    @property
    def label(self):
        return f"{self.quantity.label}: {self.feature}" if self.feature else self.quantity.label

    @property
    def complete(self):
        return self.pre.status == COMPLETED and self.post.status == COMPLETED


@dataclass
class ComponentSummary:
    component: object
    rows: list = field(default_factory=list)


def summary(components):
    """Pre/Post rows of every component, in component and quantity order: required quantities always
    (missing shown as missing), optional ones only when measured, not applicable ones never."""
    found = []
    for component in components:
        measurements = measurements_of(component)
        rows = []
        for quantity in inspection.quantities_for(component.component):
            applicability = component.applicability(quantity.kind)
            if applicability == Applicability.NOT_APPLICABLE:
                continue
            if applicability == Applicability.OPTIONAL and not any(
                m.kind == quantity.kind and m.reported for m in measurements
            ):
                continue
            values = {}
            for stage in Stage.values:
                status = slot_status(component, quantity.kind, stage, measurements)
                values[stage] = quantity_value(reported(measurements, stage, quantity.kind), quantity.code, status)
            pre, post = values[Stage.PRE], values[Stage.POST]
            unit, feature = quantity.unit, ""
            if quantity.kind == MeasurementKind.DIMENSIONAL:
                readings = [v.measurement.dimensional for v in (pre, post) if v.measurement]
                units = {r.unit for r in readings}
                unit = units.pop() if len(units) == 1 else unit
                if quantity.code == "dimension":
                    feature = next((r.feature for r in readings if r.feature), "")
            delta = inspection.delta(pre.value, post.value)
            if len({v.measurement.dimensional.unit for v in (pre, post)
                    if v.measurement and quantity.kind == MeasurementKind.DIMENSIONAL}) > 1:
                delta = None  # Pre and Post in different units: not subtracted
            rows.append(SummaryRow(
                component, quantity, pre, post, unit, inspection.KIND_SOURCES[MeasurementKind(quantity.kind)],
                delta=delta, wear=inspection.wear(quantity.code, pre.value, post.value) if delta is not None else None,
                feature=feature,
            ))  # fmt: skip
        if rows:
            found.append(ComponentSummary(component, rows))
    return found


@dataclass
class Completeness:
    slots: list  # [(component, kind, stage, status)] of the required slots
    counts: dict  # of the required slots, plus "optional_measured"

    @property
    def complete(self):
        return all(status == COMPLETED for *_, status in self.slots)


def completeness(components):
    """Required slots and their state; optional measurements are counted, never missing."""
    slots, counts = [], {COMPLETED: 0, IN_REVIEW: 0, MISSING: 0, "optional_measured": 0}
    for component in components:
        measurements = measurements_of(component)
        for kind in MeasurementKind.values:
            applicability = component.applicability(kind)
            for stage in Stage.values:
                status = slot_status(component, kind, stage, measurements)
                if applicability == Applicability.REQUIRED:
                    slots.append((component, kind, stage, status))
                    counts[status] += 1
                elif applicability == Applicability.OPTIONAL and status == COMPLETED:
                    counts["optional_measured"] += 1
    return Completeness(slots, counts)


def reported_dimensional(component, measurements=None):
    """(Pre, Post) reported face-length readings of a component, None where missing."""
    measurements = measurements_of(component) if measurements is None else measurements
    pair = []
    for stage in Stage.values:
        m = reported(measurements, stage, MeasurementKind.DIMENSIONAL)
        pair.append(m.dimensional if m else None)
    return tuple(pair)


def component_cards(components):
    """The Measurements section: per component, per stage, one row per applicable kind with its slot."""
    cards = []
    for component in components:
        measurements = measurements_of(component)
        kinds = component.applicable_kinds()
        stages = []
        for stage in Stage:
            rows = []
            for kind in kinds:
                in_slot = [m for m in measurements if m.stage == stage and m.kind == kind]
                rows.append({
                    "kind": kind,
                    "label": component.kind_label(kind),
                    "status": slot_status(component, kind, stage, measurements),
                    "reported": next((m for m in in_slot if m.reported), None),
                    "others": [m for m in in_slot if not m.reported],
                })  # fmt: skip
            stages.append({"stage": stage, "label": stage.label, "rows": rows})
        cards.append({
            "component": component,
            "kinds": kinds,
            "stages": stages,
            # kept on record although the kind is now not applicable: not in the summary or report
            "not_applicable": [m for m in measurements if m.kind not in kinds],
        })  # fmt: skip
    return cards
