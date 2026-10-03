"""Render context of the Test Run Report (M2C).

The report is a renderer: everything comes from what TestLab already holds,
nothing is entered for it.

    Project / TCN revision        identification, instructed conditions, seal information
    Manual log (execution)        actual readings, events, leakage volumes
    DCS datasets (execution)      t = 0 of the run, end of the logged period, saved plots
    Test Result (results)         components as fitted, Pre/Post, pictures, plots, acceptance, narrative

Calculations are not made here: leakage, logged period, ranges, wear and
acceptance come from results.evidence and results.acceptance — the same
code as the Result page — so the report and the page cannot disagree.
This module only selects and formats.

build_run_report_context() returns plain data (str, int, float, bool,
None, list, dict) and nothing else: the template only renders, and the
context can later be frozen as the report snapshot of a finalized Result
(JSON) and rendered again from it. Pictures and plots are named in
context["assets"] with the SHA-256 of their stored source file;
report_assets() reads their bytes for the renderer.
"""

from itertools import zip_longest

from django.utils import timezone

from testlab.execution.measurements import COMMON_GROUP, LEAKAGE
from testlab.projects import conditions
from testlab.projects.arrangements import Arrangement, seal_support_label
from testlab.results import acceptance, evidence, images, plots
from testlab.results.acceptance import format_number
from testlab.results.models import AcceptanceItem, ResultImage, ResultPlot, TestResult

from .tcn_context import format_date, run_description_lines, seal_columns

DASH = "—"
# Value columns of one manual-log table on portrait A4 (besides date/time and elapsed hours).
LOG_COLUMNS_PER_TABLE = 16

Basis = AcceptanceItem.Basis


def build_run_report_context(test_run, generated_at=None):
    tcn = test_run.current_revision()
    setup = tcn.setup
    project = test_run.project
    result = _result(test_run)
    found = evidence.collect(test_run, result)
    items = list(result.acceptance_items.all()) if result else []
    evaluations = acceptance.evaluate_all(
        items, acceptance.Evidence(found["leakage"], found["wear"], found["period"])
    )
    events = _events(found["rows"])
    context = {
        "is_draft": True,  # previews only in M2C; finalization will set it from the Result status
        "generated": _datetime(generated_at or timezone.now()),
        "identification": _identification(test_run, tcn, setup, project, found),
        "description": {
            "project": tcn.project_description,
            "run_lines": run_description_lines(setup.run_description),
        },
        "configuration": _configuration(setup, found["components"]),
        "conditions": _conditions(setup, found, evaluations),
        "leakage": _leakage(found["leakage"], evaluations),
        "plots": [],
        "events": events,
        "measurements": _measurements(found["components"]),
        "wear": _wear(found["wear"], evaluations),
        "pictures": {"cross_sections": [], "comparisons": [], "single_stage": [], "other": []},
        "acceptance": [_acceptance_row(e) for e in evaluations],
        "narrative": _narrative(result),
        "log": _log(found, events),
        "has_result": result is not None,
        "assets": [],
    }
    if result is not None:
        _pictures(context, result, found["components"])
        _plots(context, result)
    context["sections"] = _section_numbers(context)
    return context


def report_assets(context):
    """{asset path: bytes} of the pictures and plots the context names."""
    wanted = {(a["kind"], a["id"]): a["path"] for a in context["assets"]}
    files = {}
    picture_ids = [pk for kind, pk in wanted if kind == "picture"]
    for picture in ResultImage.objects.filter(pk__in=picture_ids):
        with picture.file.storage.open(images.preview_name(picture), "rb") as stored:
            files[wanted[("picture", picture.pk)]] = stored.read()
    for plot in ResultPlot.objects.filter(pk__in=[pk for kind, pk in wanted if kind == "plot"]):
        with plot.image.open("rb") as stored:
            files[wanted[("plot", plot.pk)]] = stored.read()
    return files


def run_report_file_name(test_run, draft=True):
    """e.g. 2026RSD03TL-Run002-TestRunReport-DRAFT.pdf."""
    suffix = "-DRAFT" if draft else ""
    return f"{test_run.project.project_no}-Run{test_run.display_no}-TestRunReport{suffix}.pdf"


# ---- helpers ------------------------------------------------------------------------------


def _result(test_run):
    return (
        TestResult.objects.filter(test_run=test_run)
        .prefetch_related("components__measurements", "images__component", "acceptance_items__component")
        .first()
    )


def _datetime(value):
    return format_date(timezone.localtime(value)) + timezone.localtime(value).strftime(" %H:%M")


def _hours(value, digits=2):
    return DASH if value is None else f"{value:.{digits}f}"


def _reading(value):
    return DASH if value is None else format_number(value)


def _with_unit(text, unit):
    return f"{text} {unit}" if text and text != DASH and unit else text


def _identification(test_run, tcn, setup, project, found):
    period = found["period"]
    seals = [
        {"heading": column["heading"], "seal_type_size": column["seal_type_size"] or DASH}
        for column in seal_columns(setup)
    ]
    dates = ""
    if period.start and period.end:
        first, last = format_date(timezone.localtime(period.start)), format_date(timezone.localtime(period.end))
        dates = first if first == last else f"{first} – {last}"
    return {
        "project_no": project.project_no,
        "customer": project.customer,
        "run_no": test_run.display_no,
        "tcn_no": f"TCN{test_run.display_no}",
        "tcn_revision": tcn.revision,
        "tcn_status": tcn.get_status_display(),
        "tcn_issued": format_date(timezone.localtime(tcn.issued_at)) if tcn.issued_at else "",
        "test_unit": setup.test_unit,
        "arrangement": setup.configuration_display,
        "reference_drawing": setup.reference_drawing,
        "seals": seals,
        "dates": dates,
        "start": _datetime(period.start) if period.start else "",
        "start_source": period.start_source,
        "end": _datetime(period.end) if period.end else "",
        "end_source": period.end_source,
        "logged_hours": _hours(period.hours) if period.hours is not None else "",
        "provisional": period.provisional,
        "datasets": [d.original_name for d in found["datasets"]],
    }


def _configuration(setup, components):
    seals = [
        {"heading": c["heading"], "seal_type_size": c["seal_type_size"], "springs": c["springs"]}
        for c in seal_columns(setup)
    ]
    show_seals = any(s["seal_type_size"] or s["springs"] for s in seals)
    return {
        "reference_drawing": setup.reference_drawing,
        "seals": seals if show_seals else [],
        "components": [
            {
                "label": c.label,
                "description": c.description,
                "part_no": c.part_no or DASH,
                "material": c.material or DASH,
                "condition": c.condition or DASH,
            }
            for c in components
        ],
    }


def _criteria(evaluations, basis, position=None, component_id=None):
    """Requirement / assessment of the acceptance criteria that refer to one row."""
    found = []
    for e in evaluations:
        if e.item.basis != basis:
            continue
        if position is not None and e.item.position != position:
            continue
        if component_id is not None and e.item.component_id != component_id:
            continue
        found.append({"requirement": e.requirement or DASH, "assessment": str(e.effective), "label": str(e.effective_label)})
    return found


def _actual_range(found, code):
    values = [row.values[code].value for row in found["rows"] if code in row.values]
    if not values:
        return {"text": DASH, "count": 0}
    low, high = min(values), max(values)
    text = format_number(low) if low == high else f"{format_number(low)} – {format_number(high)}"
    return {"text": text, "count": len(values)}


def _conditions(setup, found, evaluations):
    """Test conditions: TCN (instructed) beside the manual log (actual) and the criteria that refer to them.

    Rows follow the manual-log catalogue of the run (the same codes as the
    TCN's "Parameters to log"), plus the TCN fields that have no reading
    (test unit, duration, media). A row is shown when it has an instructed
    or an actual value. Actual = min – max of the manual readings: spot
    readings, so no average is given.
    """
    groups = []

    def group(heading):
        groups.append({"heading": heading, "rows": []})
        return groups[-1]["rows"]

    def add(rows, parameter, unit, instructed, actual=None, criteria=()):
        actual = actual or {"text": DASH, "count": 0}
        if not instructed and actual["text"] == DASH and not criteria:
            return
        rows.append({
            "parameter": parameter, "unit": unit, "instructed": instructed or DASH,
            "actual": actual["text"], "count": actual["count"], "note": actual.get("note", ""),
            "criteria": list(criteria),
        })  # fmt: skip

    period = found["period"]
    by_group = {}
    for column in found["columns"]:
        if column.kind != LEAKAGE:
            by_group.setdefault(column.group, []).append(column)

    rows = group("Test run")
    add(rows, "Test unit", "", setup.test_unit)
    add(
        rows, "Duration", "h", setup.duration,
        {"text": _hours(period.hours), "count": 0, "note": "logged period, clock time"} if period.hours else None,
        _criteria(evaluations, Basis.LOGGED_HOURS),
    )  # fmt: skip
    for column in by_group.pop(COMMON_GROUP, []):
        add(rows, column.label, column.unit, evidence.instructed_value(setup, column.code), _actual_range(found, column.code))

    circuits = []
    if setup.plug_seal_present:
        circuits.append(("Process", "process_medium"))
    if setup.arrangement != Arrangement.SINGLE or any(getattr(setup, f) for f in conditions.SEAL_SUPPORT_FIELDS):
        circuits.append((seal_support_label(setup.arrangement), "seal_support_medium"))
    for heading, medium_field in circuits:
        rows = group(f"{heading} fluid" if heading == "Process" else heading)
        add(rows, "Medium", "", getattr(setup, medium_field))
        for column in by_group.pop(heading, []):
            add(rows, column.label, column.unit, evidence.instructed_value(setup, column.code), _actual_range(found, column.code))

    for seal in found["leakage"]:  # per seal position: its readings, then its average leakage
        by_group.setdefault(seal.label, [])
    for heading, columns in by_group.items():
        rows = group(heading)
        for column in columns:
            add(rows, column.label, column.unit, evidence.instructed_value(setup, column.code), _actual_range(found, column.code))
        seal = next((s for s in found["leakage"] if s.label == heading), None)
        if seal is not None:
            add(
                rows, "Leakage, average", "ml/h", "",
                {"text": _hours(seal.average, 1), "count": 0, "note": "Σ volume / Σ collection period"}
                if seal.average is not None else None,
                _criteria(evaluations, Basis.LEAKAGE_RATE, position=seal.position),
            )  # fmt: skip
    return [g for g in groups if g["rows"]]


def _leakage(leakage, evaluations):
    return [
        {
            "seal": seal.label,
            "total": _reading(seal.total_volume),
            "rated": _reading(seal.rated_volume) if seal.intervals else DASH,
            "hours": _hours(seal.hours) if seal.intervals else DASH,
            "average": _hours(seal.average, 1),
            "reason": seal.reason,
            "unrated": _reading(seal.unrated_volume) if seal.unrated_volume else "",
            "unrated_notes": seal.unrated_notes,
            "criteria": _criteria(evaluations, Basis.LEAKAGE_RATE, position=seal.position),
        }
        for seal in leakage
        if seal.total_volume is not None
    ]


def _events(rows):
    found = []
    for number, row in enumerate(evidence.events(rows), start=1):
        found.append({
            "ref": f"E{number}",
            "entry_id": row.entry.pk,
            "at": _datetime(row.entry.observed_at),
            "elapsed": _hours(row.elapsed_h),
            "category": row.entry.get_category_display() if row.entry.category else "",
            "note": row.entry.note.strip(),
        })  # fmt: skip
    return found


def _measurements(components):
    found = []
    for component in components:
        stored = {m.quantity: m for m in component.measurements.all()}
        rows = []
        for quantity in component.quantities():
            m = stored.get(quantity.code)
            if m is None:
                continue
            delta = m.delta
            rows.append({
                "quantity": quantity.label,
                "unit": m.unit,
                "pre": _reading(m.pre_value),
                "post": _reading(m.post_value),
                "delta": DASH if delta is None else _signed(delta),
            })  # fmt: skip
        if rows:
            found.append({"component": component.label, "rows": rows})
    return found


def _signed(value):
    text = format_number(abs(value))
    return f"+{text}" if value > 0 else f"−{text}" if value < 0 else text


def _wear(wear, evaluations):
    return [
        {
            "component": w.component.label,
            "quantity": w.measurement.definition.label,
            "unit": w.measurement.unit,
            "pre": _reading(w.measurement.pre_value),
            "post": _reading(w.measurement.post_value),
            "wear": _reading(w.wear),
            "hours": _hours(w.hours),
            "hours_source": w.hours_source,
            "rate": DASH if w.rate is None else format_number(w.rate),
            "criteria": _criteria(evaluations, Basis.WEAR_RATE, component_id=w.component.pk),
        }
        for w in wear
    ]


def _acceptance_row(e):
    item = e.item
    basis = ""
    if item.basis != Basis.MANUAL:
        basis = item.get_basis_display()
        if item.position:
            basis += f" · {item.get_position_display()}"
        if item.component_id:
            basis += f" · {item.component.label}"
    return {
        "criterion": item.criterion,
        "basis": basis,
        "requirement": e.requirement or DASH,
        "actual": e.actual_text or DASH,
        "source": e.source if item.basis != Basis.MANUAL else "",
        "assessment": str(e.effective),
        "label": str(e.effective_label),
        "by": {"engineer": "engineer", "calculated": "calculated"}.get(e.by, "to be assessed"),
        "remark": item.remark,
    }


def _paragraphs(text):
    """Blank-line separated paragraphs, each a list of lines."""
    blocks = [block.strip() for block in text.replace("\r\n", "\n").split("\n\n")]
    return [[line.strip() for line in block.splitlines()] for block in blocks if block]


def _narrative(result):
    if result is None:
        return {"observations": [], "conclusion": [], "recommendation": []}
    return {
        "observations": _paragraphs(result.observations),
        "conclusion": _paragraphs(result.conclusion),
        "recommendation": _paragraphs(result.recommendation),
    }


def _picture(context, picture):
    path = f"assets/picture-{picture.pk}.jpg"
    context["assets"].append({"path": path, "kind": "picture", "id": picture.pk, "sha256": picture.sha256})
    width, height = picture.width, picture.height
    return {
        "src": path,
        "caption": picture.caption,
        "name": picture.original_name,
        "orientation": "portrait" if height > width else "landscape",
    }


def _pictures(context, result, components):
    groups = images.picture_groups(result, components)
    pictures = context["pictures"]
    pictures["cross_sections"] = [_picture(context, p) for p in groups["cross_sections"]]
    single = {"Pre-test": [], "Post-test": []}
    for comparison in groups["comparisons"]:
        component = comparison["component"]
        label = component.label if component else "Whole seal"
        if comparison["pre"] and comparison["post"]:  # side by side, Pre ↔ Post
            pairs = [
                {"pre": _picture(context, pre) if pre else None, "post": _picture(context, post) if post else None}
                for pre, post in zip_longest(comparison["pre"], comparison["post"])
            ]
            pictures["comparisons"].append({"label": label, "pairs": pairs})
        else:  # only one stage photographed: no empty half-page placeholders
            stage = "Pre-test" if comparison["pre"] else "Post-test"
            for picture in comparison["pre"] or comparison["post"]:
                single[stage].append({"label": label, "picture": _picture(context, picture)})
    for stage, items in single.items():
        if items:
            rows = [items[i : i + 2] for i in range(0, len(items), 2)]
            pictures["single_stage"].append({"stage": stage, "rows": rows})
    pictures["other"] = [_picture(context, p) for p in groups["other"]]


def _plots(context, result):
    for number, plot in enumerate(result.plots.select_related("dataset").order_by("order", "pk"), start=1):
        path = f"assets/plot-{plot.pk}.png"
        context["assets"].append({"path": path, "kind": "plot", "id": plot.pk, "sha256": plot.image_sha256})
        about = plots.describe(plot)
        rendering = plot.rendering or {}
        if rendering.get("decimated"):
            data = (f"{rendering['samples_in_window']} samples per signal, drawn as min/max of time buckets "
                    f"({rendering['points_per_signal']} points)")  # fmt: skip
        elif rendering:
            data = f"all {rendering.get('samples_in_window', 0)} samples per signal"
        else:
            data = ""
        context["plots"].append({
            "number": number,
            "src": path,
            "caption": plot.caption,
            "dataset": plot.dataset.original_name,
            "dataset_sha256": plot.dataset.sha256,
            "signals": about["signals"],
            "window": about["window"],
            "ranges": about["ranges"],
            "data": data,
            "landscape": plot.image_width >= plot.image_height,
        })  # fmt: skip


def _log(found, events):
    """The manual log as report tables: only the measurements that hold a reading.

    Leakage: one collection-period column (it is per entry, the same for
    every seal), then per seal the collected volume and the calculated rate.
    More columns than fit portrait A4 are split into consecutive tables, at
    column-group boundaries, each repeating date/time and elapsed hours.
    """
    rows = found["rows"]
    if not rows:
        return {"tables": [], "count": 0, "provisional": found["origin"].provisional}
    event_refs = {e["entry_id"]: e["ref"] for e in events}
    columns = []
    used = lambda code: any(code in row.values for row in rows)  # noqa: E731
    value_columns = [c for c in found["columns"] if c.kind != LEAKAGE and used(c.code)]
    leakage_columns = [c for c in found["columns"] if c.kind == LEAKAGE and (used(c.code) or any(c.code in r.leakage for r in rows))]
    for c in value_columns:
        columns.append({"group": c.group if c.group != COMMON_GROUP else "", "label": c.label, "unit": c.unit,
                        "kind": "value", "code": c.code})  # fmt: skip
    if leakage_columns:
        columns.append({"group": "Leakage", "label": "Period", "unit": "h", "kind": "period", "code": ""})
        for c in leakage_columns:
            seal = c.group.replace(" Seal", "")
            columns.append({"group": "Leakage", "label": seal, "unit": "ml", "kind": "volume", "code": c.code})
            columns.append({"group": "Leakage", "label": f"{seal} rate", "unit": "ml/h", "kind": "rate", "code": c.code})

    def cell(row, column):
        if column["kind"] == "value":
            value = row.values.get(column["code"])
            return "" if value is None else format_number(value.value)
        leak = row.leakage
        if column["kind"] == "period":
            hours = next((l.hours for l in leak.values() if l.hours is not None), None)  # noqa: E741
            return "" if hours is None else f"{hours:.2f}"
        found_leak = leak.get(column["code"])
        if found_leak is None:
            return ""
        if column["kind"] == "volume":
            return "" if found_leak.volume is None else format_number(found_leak.volume)
        return "" if found_leak.rate is None else f"{found_leak.rate:.1f}"

    tables = []
    for chunk in _chunks(columns, LOG_COLUMNS_PER_TABLE):
        groups = []
        for column in chunk:
            if groups and groups[-1]["heading"] == column["group"]:
                groups[-1]["span"] += 1
            else:
                groups.append({"heading": column["group"], "span": 1})
        tables.append({
            "groups": groups,
            "columns": [{k: c[k] for k in ("label", "unit", "kind")} for c in chunk],
            "rows": [
                {
                    "date": format_date(timezone.localtime(row.entry.observed_at)),
                    "time": timezone.localtime(row.entry.observed_at).strftime("%H:%M"),
                    "elapsed": _hours(row.elapsed_h),
                    "cells": [cell(row, c) for c in chunk],
                    "event": event_refs.get(row.entry.pk, ""),
                }
                for row in rows
            ],
        })  # fmt: skip
    return {"tables": tables, "count": len(rows), "provisional": found["origin"].provisional}


def _chunks(columns, size):
    """Split columns into tables of at most `size`, preferring a split between groups."""
    chunks, current = [], []
    for column in columns:
        if len(current) >= size:
            cut = len(current)
            for i in range(len(current) - 1, 0, -1):
                if current[i]["group"] != current[i - 1]["group"]:
                    cut = i
                    break
            chunks.append(current[:cut])
            current = current[cut:]
        current.append(column)
    if current:
        chunks.append(current)
    return chunks


def _section_numbers(context):
    """Numbers of the sections that have content, in report order (empty sections are omitted)."""
    present = [
        ("description", bool(context["description"]["project"] or context["description"]["run_lines"])),
        ("configuration", bool(context["configuration"]["components"] or context["configuration"]["seals"]
                               or context["configuration"]["reference_drawing"] or context["pictures"]["cross_sections"])),
        ("conditions", bool(context["conditions"])),
        ("leakage", bool(context["leakage"])),
        ("plots", bool(context["plots"])),
        ("events", bool(context["events"] or context["narrative"]["observations"])),
        ("measurements", bool(context["measurements"] or context["wear"])),
        ("pictures", bool(context["pictures"]["comparisons"] or context["pictures"]["single_stage"]
                          or context["pictures"]["other"])),
        ("acceptance", bool(context["acceptance"])),
        ("conclusion", bool(context["narrative"]["conclusion"] or context["narrative"]["recommendation"])),
    ]  # fmt: skip
    numbers, n = {}, 0
    for name, shown in present:
        if shown:
            n += 1
            numbers[name] = n
    return numbers
