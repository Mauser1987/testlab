"""Which TestLab/TCN parameter a DCS signal is (M2E).

A LabVIEW/DCS export names its signals freely ("LBI", "Speed", "T04"…).
Before TestLab uses a signal as an actual value — shaft speed for the
running hours, or a min–max of a logged parameter — the engineer maps it
to a parameter of the run's manual-log catalogue (measurements.py, the
codes of the TCN's "Parameters to log") and reviews the mapping:

    signal "Speed" [RPM]   →  speed [rpm]                  units equal: nothing to confirm
    signal "PT01"  [bar]   →  seal_support_pressure [barg] units differ: the engineer confirms
                                                           that the values are in barg

Nothing is converted: a confirmed unit means the values are already in
the parameter's unit. Unmapped signals stay plottable but are never used
as actual values.

A reviewed mapping is kept per export format (DcsSignalMap, identified by
the signal names and units in column order) and applied to later imports
of exactly the same format, as long as its parameters exist in the run's
configuration. Any difference in signals or units needs a new review;
suggestions from earlier formats only prefill the form.
"""

import hashlib
import json
import re

from django.db import transaction
from django.utils import timezone

from . import manual_log
from .measurements import LEAKAGE
from .models import DcsSignalMap

# Unit spellings that mean the same unit (lower case, spaces removed). Different units are never
# aliased, e.g. bar is not barg.
_UNIT_ALIASES = {
    "rpm": "rpm", "1/min": "rpm", "min-1": "rpm", "min^-1": "rpm", "u/min": "rpm", "r/min": "rpm",
    "°c": "°c", "degc": "°c", "deg.c": "°c", "ºc": "°c", "c": "°c", "celsius": "°c",
    "barg": "barg", "bar(g)": "barg", "barg.": "barg",
    "bar": "bar",
    "l/min": "l/min", "lpm": "l/min", "l/m": "l/min",
    "nm": "nm", "n.m": "nm", "n·m": "nm", "n*m": "nm",
    "ml": "ml", "cc": "ml", "cm3": "ml", "cm³": "ml",
}  # fmt: skip


def normalized_unit(unit):
    text = re.sub(r"\s+", "", (unit or "").lower()).strip("[]()")
    return _UNIT_ALIASES.get(text, text)


def units_match(signal_unit, parameter_unit):
    return normalized_unit(signal_unit) == normalized_unit(parameter_unit)


def format_signature(dataset):
    """Identifies an export format: the value signals' names and units, in column order."""
    signals = [[s["name"], s["unit"]] for s in dataset.value_signals()]
    return hashlib.sha256(json.dumps(signals, ensure_ascii=False).encode("utf-8")).hexdigest()


def parameters(test_run):
    """{code: Measurement} a signal can be mapped to: the run's logged parameters, not leakage volumes."""
    return {m.code: m for m in manual_log.log_columns(test_run) if m.kind != LEAKAGE}


def _signal_key(signal):
    return str(signal["column"])


def mapped_column(dataset, code):
    """The column of a reviewed mapping that holds `code`, or None."""
    if not dataset.mapping_reviewed:
        return None
    for column, entry in dataset.mapping.items():
        if entry.get("code") == code:
            return int(column)
    return None


def mapped_signal(dataset, code):
    column = mapped_column(dataset, code)
    if column is None:
        return None
    return next((s for s in dataset.signals if s["column"] == column), None)


def known_map(dataset):
    return DcsSignalMap.objects.filter(signature=format_signature(dataset)).first()


def apply_known_mapping(dataset):
    """On import: take over the reviewed mapping of the same format, when every parameter fits the run.

    Returns the DcsSignalMap applied, or None (then the dataset needs a review).
    """
    found = known_map(dataset)
    if found is None:
        return None
    offered = parameters(dataset.test_run)
    values = dataset.value_signals()
    if len(values) != len(found.signals):
        return None
    mapping = {}
    for signal, entry in zip(values, found.signals):
        code = entry.get("code") or ""
        if not code:
            continue
        if code not in offered:
            return None  # e.g. a mapping made for another arrangement: review again
        mapping[_signal_key(signal)] = {"code": code, "unit_confirmed": bool(entry.get("unit_confirmed"))}
    dataset.mapping = mapping
    dataset.mapping_from = found
    dataset.mapping_reviewed_at = found.reviewed_at
    dataset.mapping_reviewed_by = found.reviewed_by
    dataset.save(update_fields=["mapping", "mapping_from", "mapping_reviewed_at", "mapping_reviewed_by"])
    return found


def suggestions(dataset):
    """{column: code} prefilled for the review: the dataset's own mapping, else matching names and units
    of earlier reviewed formats (most recent first), else a speed signal in rpm."""
    if dataset.mapping:
        return {int(column): entry["code"] for column, entry in dataset.mapping.items()}
    offered = parameters(dataset.test_run)
    found = {}
    earlier = {}
    for signal_map in DcsSignalMap.objects.order_by("-reviewed_at"):
        for entry in signal_map.signals:
            if entry.get("code") in offered:
                earlier.setdefault((entry["name"].strip().lower(), normalized_unit(entry["unit"])), entry["code"])
    for signal in dataset.value_signals():
        code = earlier.get((signal["name"].strip().lower(), normalized_unit(signal["unit"])))
        if code is None and "speed" in signal["name"].lower() and normalized_unit(signal["unit"]) == "rpm":
            code = "speed" if "speed" in offered else None  # e.g. "Motor Speed [RPM]": a suggestion only
        if code and code not in found.values():
            found[signal["column"]] = code
    return found


class MappingError(Exception):
    """The mapping cannot be saved; the message says why."""


def review_mapping(dataset, chosen, confirmed, user):
    """Save the engineer's mapping and remember it for the format.

    chosen: {column: code or ""}; confirmed: columns whose unit differs from the parameter's and
    whose values the engineer confirms are in the parameter's unit.
    """
    offered = parameters(dataset.test_run)
    signals = {s["column"]: s for s in dataset.value_signals()}
    mapping, used, problems = {}, {}, []
    for column, code in chosen.items():
        if not code:
            continue
        if column not in signals:
            problems.append(f"Column {column} is not a signal of {dataset}.")
            continue
        if code not in offered:
            problems.append(f"{code} is not a parameter of this run.")
            continue
        if code in used:
            problems.append(f"{offered[code].full_label} is chosen for two signals ({used[code]}, {signals[column]['name']}).")
            continue
        used[code] = signals[column]["name"]
        matches = units_match(signals[column]["unit"], offered[code].unit)
        if not matches and column not in confirmed:
            problems.append(
                f"{signals[column]['name']} is in [{signals[column]['unit'] or 'no unit'}], "
                f"{offered[code].full_label} in [{offered[code].unit}]: confirm that the values are in "
                f"{offered[code].unit}, or leave the signal unmapped (nothing is converted)."
            )
            continue
        mapping[str(column)] = {"code": code, "unit_confirmed": not matches}
    if problems:
        raise MappingError(" ".join(problems))
    now = timezone.now()
    with transaction.atomic():
        signature = format_signature(dataset)
        entries = []
        for signal in dataset.value_signals():
            entry = mapping.get(_signal_key(signal), {})
            entries.append({"name": signal["name"], "unit": signal["unit"], "code": entry.get("code", ""),
                            "unit_confirmed": entry.get("unit_confirmed", False)})  # fmt: skip
        signal_map, _ = DcsSignalMap.objects.update_or_create(
            signature=signature,
            defaults={"signals": entries, "reviewed_at": now, "reviewed_by": user, "source_dataset": dataset},
        )
        dataset.mapping = mapping
        dataset.mapping_from = None
        dataset.mapping_reviewed_at = now
        dataset.mapping_reviewed_by = user
        dataset.save(update_fields=["mapping", "mapping_from", "mapping_reviewed_at", "mapping_reviewed_by"])
    return signal_map


def describe(dataset, code):
    """e.g. "TestRun_04.txt › Speed [RPM]" for the source of an actual value."""
    signal = mapped_signal(dataset, code)
    if signal is None:
        return ""
    unit = f" [{signal['unit']}]" if signal["unit"] else ""
    return f"{dataset.original_name} › {signal['name']}{unit}"


def short_name(dataset, code):
    """The signal's name for a compact source, its tag unbracketed: "(X22) Process Syst Press" → "X22 Process
    Syst Press", "Motor Speed" unchanged. The full source is describe()."""
    signal = mapped_signal(dataset, code)
    if signal is None:
        return ""
    return re.sub(r"^\s*[(\[]\s*([^)\]]+?)\s*[)\]]\s*", r"\1 ", signal["name"]).strip()
