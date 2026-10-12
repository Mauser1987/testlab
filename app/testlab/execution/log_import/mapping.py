"""Which manual-log field each workbook column is (M2F).

A column is described by its group heading, its heading and its unit
(xlsx.SourceColumn). A target is one of:

* a measurement code of the run's manual log (measurements.py: the run's
  configuration and its TCN "Parameters to log");
* "interval:<leakage code>": the collection period typed for that leakage
  ("Over [hours]"); a formula there is the workbook's own default, not an
  entered period;
* "date", "time", "datetime", "operator" (who took the reading, kept as
  source information), "note";
* "derived": calculated by the workbook (running hours, leakage rates) —
  kept in the import record, never imported: TestLab calculates its own;
* "ignore".

Proposals come from the words of the heading and group, the unit and the
configuration. A proposal TestLab cannot know for sure is marked Review
required and must be confirmed by the engineer: above all which circuit a
flow, temperature or pressure column belongs to when the heading does not
say Process, Barrier, Buffer or Flush (a "Job" or "Plug" circuit, "Seal
Press"). The confirmed mapping is saved for the layout (fingerprint of the
headings in column order) and the configuration, and proposed again for
the next workbook with the same layout; the engineer still reviews it.
"""

import hashlib
import json
import re
from dataclasses import dataclass

from django.utils import timezone

from testlab.projects.arrangements import (
    DIFF_PRESSURE_PARAMETER,
    SealRole,
    applicable_roles,
    seal_support_label,
    seal_under_test_roles,
)

from .. import manual_log
from ..models import ManualLogLayoutMap
from ..signal_mapping import normalized_unit

DATE, TIME, DATETIME, OPERATOR, NOTE, DERIVED, IGNORE = "date", "time", "datetime", "operator", "note", "derived", "ignore"
INTERVAL = "interval:"
STRUCTURAL = [
    (DATE, "Date"),
    (TIME, "Time"),
    (DATETIME, "Date and time"),
    (OPERATOR, "Operator (as written, kept as source)"),
    (NOTE, "Note / event"),
    (DERIVED, "Calculated in the workbook – not imported"),
    (IGNORE, "Not imported"),
]
SINGLE_USE = {DATE, TIME, DATETIME, OPERATOR, NOTE}

# Statuses of a column's mapping.
CONFIRMED = "confirmed"  # from the reviewed layout map
PROPOSED = "proposed"
REVIEW = "review"  # Review required: the engineer confirms it
NOT_IMPORTED = "not_imported"  # derived or empty column, not imported

STATUS_LABELS = {CONFIRMED: "Reviewed layout", PROPOSED: "Proposed", REVIEW: "Review required",
                 NOT_IMPORTED: "Not imported"}  # fmt: skip

_ROLE_WORDS = {"plug": SealRole.PLUG, "ib": SealRole.INBOARD, "ibs": SealRole.INBOARD, "inboard": SealRole.INBOARD,
               "ob": SealRole.OUTBOARD, "obs": SealRole.OUTBOARD, "outboard": SealRole.OUTBOARD}  # fmt: skip
_UNDER_TEST_WORDS = {"job", "test"}
_SUPPORT_WORDS = {"barrier", "buffer", "flush", "support"}
_NOTE_WORDS = {"note", "notes", "remark", "remarks", "comment", "comments", "event", "events", "observation",
               "observations"}  # fmt: skip
_OPERATOR_WORDS = {"by", "operator", "initials", "technician", "name"}


@dataclass
class Proposal:
    letter: str
    target: str
    status: str
    reason: str = ""

    def as_dict(self, reviewed=False):
        return {"letter": self.letter, "target": self.target, "status": self.status, "reason": self.reason,
                "reviewed": reviewed}  # fmt: skip


def _words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def fingerprint(columns):
    """Identifies a log layout: the headings (group, heading, unit) in column order."""
    key = [[c["letter"], _norm(c["group"]), _norm(c["label"]), _norm(c["unit"])] for c in columns]
    return hashlib.sha256(json.dumps(key, ensure_ascii=False).encode("utf-8")).hexdigest()


def catalogue(test_run):
    """{code: Measurement} the run's manual log offers (its configuration and TCN parameters to log)."""
    return {m.code: m for m in manual_log.log_columns(test_run)}


def target_choices(test_run):
    """[(value, label)] for the mapping form: structural targets, measurements, leakage periods."""
    measurements = list(catalogue(test_run).values())
    return (
        STRUCTURAL
        + [(m.code, m.full_label) for m in measurements]
        + [(INTERVAL + m.code, f"{m.group} leakage collected over [h]") for m in measurements if m.is_leakage]
    )


def target_label(test_run, target):
    return dict(target_choices(test_run)).get(target, target)


def _role(words, group_words, setup):
    """(role, reason, sure) of a seal-position column (face temp., leakage)."""
    roles = applicable_roles(setup.arrangement, setup.plug_seal_present)
    for source in (words, group_words):
        for word in source:
            if word in _ROLE_WORDS and _ROLE_WORDS[word] in roles:
                return _ROLE_WORDS[word], "", True
        if _UNDER_TEST_WORDS & set(source):
            under_test = seal_under_test_roles(setup.arrangement)
            if len(under_test) == 1:
                return under_test[0], "“Job”/“Test” is the seal under test.", True
            return None, "Which seal of the arrangement (no IB/OB in the heading).", False
    under_test = seal_under_test_roles(setup.arrangement)
    if len(under_test) == 1:
        return under_test[0], "No seal named in the heading: the seal under test assumed.", False
    return None, "No seal named in the heading.", False


def _circuit(words, group_words, setup, quantity):
    """(code prefix, reason, sure) of a circuit column (flow, inlet/outlet temp., pressure)."""
    support = seal_support_label(setup.arrangement)
    process = "process_" if setup.plug_seal_present else None
    all_words = set(words) | set(group_words)
    if "process" in all_words and process:
        return process, "", True
    named = _SUPPORT_WORDS & all_words
    if named:
        if named <= {"support"} or support.lower() in named:
            return "seal_support_", "", True
        return "seal_support_", (f"The heading says {'/'.join(sorted(named)).title()}; this run's seal-support "
                                 f"circuit is {support}."), False  # fmt: skip
    for source in (words, group_words):
        if "plug" in source and process:
            return process, ("“Plug” circuit assumed to be the Process Conditions (established with the Plug "
                             "Seal): confirm."), False  # fmt: skip
        if (_UNDER_TEST_WORDS | {"ib", "ob", "inboard", "outboard"}) & set(source):
            return "seal_support_", f"“{_first(source)}” circuit assumed to be the {support} circuit: confirm.", False
    if quantity == "pressure" and "seal" in all_words:
        prefix = process or "seal_support_"
        name = "Process pressure" if process else f"{support} pressure"
        return prefix, f"“Seal press.” assumed to be the {name}: confirm.", False
    prefix = process or "seal_support_"
    return prefix, "No circuit named in the heading: confirm.", False


def _first(words):
    return next(w for w in words if w in _UNDER_TEST_WORDS | {"ib", "ob", "inboard", "outboard"}).title()


def _propose_one(column, setup):
    """(target, sure, reason) for one column from its words and unit, before checks against the catalogue."""
    words, group_words = _words(column["label"]), _words(column["group"])
    word_set = set(words)
    unit = normalized_unit(column["unit"])
    if not words:
        return IGNORE, True, ""
    if "date" in word_set and "time" in word_set:
        return DATETIME, True, ""
    if "date" in word_set:
        return DATE, True, ""
    if word_set == {"time"} or (words[0] == "time" and not unit):
        return TIME, True, ""
    if word_set & _NOTE_WORDS and not unit:
        return NOTE, True, ""
    if word_set & _OPERATOR_WORDS and not unit and len(words) <= 3:
        return OPERATOR, True, ""
    if "rate" in word_set or unit in ("ml/hr", "ml/h", "cc/h", "cc/hr"):
        return DERIVED, True, "Leakage rate: calculated by TestLab."
    if "over" in word_set and (unit in ("hours", "hour", "h", "hrs", "hr") or "hours" in word_set):
        return INTERVAL, True, ""
    if word_set & {"running", "runned", "elapsed", "hours", "hrs"}:
        return DERIVED, True, "Running/elapsed hours: calculated by TestLab."
    if unit == "rpm" or word_set & {"rpm", "speed"}:
        return "speed", True, ""
    if unit == "nm" or "torque" in word_set:
        return "torque", True, ""
    if word_set & {"leakage", "leak"} or unit == "ml":
        role, reason, sure = _role(words, group_words, setup)
        return (f"{role}_leakage" if role else IGNORE), sure, reason
    temperature = word_set & {"temp", "temperature"} or unit == "°c"
    if temperature and "face" in word_set:
        role, reason, sure = _role(words, group_words, setup)
        return (f"{role}_face_temp" if role else IGNORE), sure, reason
    if temperature:
        if word_set & {"fi", "fi1", "fi2", "inlet", "in"}:
            suffix = "inlet_temp"
        elif word_set & {"fo", "fo1", "fo2", "outlet", "out"}:
            suffix = "outlet_temp"
        else:
            return IGNORE, False, "Temperature: inlet, outlet or face not named in the heading."
        prefix, reason, sure = _circuit(words, group_words, setup, "temperature")
        return prefix + suffix, sure, reason
    if word_set & {"flow"} or unit == "l/min":
        prefix, reason, sure = _circuit(words, group_words, setup, "flow")
        return prefix + "flow", sure, reason
    if word_set & {"press", "pressure", "pres"} or unit in ("barg", "bar"):
        if "diff" in word_set or "differential" in word_set:
            return DIFF_PRESSURE_PARAMETER, True, ""
        prefix, reason, sure = _circuit(words, group_words, setup, "pressure")
        return prefix + "pressure", sure, reason
    return IGNORE, False, "Not recognised."


def propose(test_run, columns, columns_with_values=()):
    """[Proposal] per column; from the reviewed layout map when there is one for this layout and configuration."""
    setup = manual_log.run_setup(test_run)
    codes = catalogue(test_run)
    layout = find_layout_map(test_run, columns)
    if layout:
        return _from_layout(layout, columns, codes, columns_with_values)
    proposals, last_leakage = [], None
    for column in columns:
        target, sure, reason = _propose_one(column, setup)
        if target == INTERVAL:
            if last_leakage:
                target = INTERVAL + last_leakage
            else:
                target, sure, reason = IGNORE, False, "Collection period without a leakage column before it."
        elif target not in (DATE, TIME, DATETIME, OPERATOR, NOTE, DERIVED, IGNORE) and target not in codes:
            name = target.replace("_", " ")
            target, sure, reason = IGNORE, False, f"Proposed {name}: not in this run's configuration or TCN " \
                                                  "parameters to log."  # fmt: skip
        if target in codes:
            measurement = codes[target]
            if measurement.is_leakage:
                last_leakage = target
            if column["unit"] and normalized_unit(column["unit"]) != normalized_unit(measurement.unit):
                sure = False
                reason = (reason + " " if reason else "") + (f"Unit in the workbook {column['unit']}, TestLab "
                                                             f"{measurement.unit}: nothing is converted.")  # fmt: skip
        if target == IGNORE:
            # Unrecognised: only a question when the column holds something that would be left out.
            if column["letter"] in columns_with_values:
                sure, reason = False, reason or "The column has values."
            else:
                sure = True
        if target in (DERIVED, IGNORE) and sure:
            status = NOT_IMPORTED
        else:
            status = PROPOSED if sure else REVIEW
        proposals.append(Proposal(column["letter"], target, status, reason))
    _mark_duplicates(proposals)
    return proposals


def _from_layout(layout, columns, codes, columns_with_values):
    reviewed = f"Reviewed by {layout.reviewed_by.get_full_name() or layout.reviewed_by.username} " \
               f"on {timezone.localtime(layout.reviewed_at):%d-%b-%Y}."  # fmt: skip
    targets = {c["letter"]: c["target"] for c in layout.columns}
    proposals = []
    for column in columns:
        target = targets.get(column["letter"], IGNORE)
        code = target[len(INTERVAL):] if target.startswith(INTERVAL) else target
        if target not in dict(STRUCTURAL) and code not in codes:
            proposals.append(Proposal(column["letter"], IGNORE, REVIEW,
                                      f"Reviewed as {code}, which is not in this run's configuration."))
        elif target in (DERIVED, IGNORE):
            status = REVIEW if target == IGNORE and column["letter"] in columns_with_values else NOT_IMPORTED
            proposals.append(Proposal(column["letter"], target, status, reviewed if status == REVIEW else ""))
        else:
            proposals.append(Proposal(column["letter"], target, CONFIRMED, reviewed))
    return proposals


def _mark_duplicates(proposals):
    seen = {}
    for proposal in proposals:
        if proposal.target in (DERIVED, IGNORE):
            continue
        seen.setdefault(proposal.target, []).append(proposal)
    for same in seen.values():
        if len(same) > 1:
            for proposal in same:
                proposal.status = REVIEW
                letters = ", ".join(p.letter for p in same)
                proposal.reason = (proposal.reason + " " if proposal.reason else "") + \
                    f"Proposed for more than one column ({letters}): choose one."  # fmt: skip


def validate(test_run, columns, chosen, reviewed, proposals):
    """Problems of a chosen mapping ({letter: target}), [] when it can be confirmed.

    reviewed: letters whose Review-required proposal the engineer confirmed.
    """
    problems = []
    codes = catalogue(test_run)
    valid = {value for value, _ in target_choices(test_run)}
    by_target = {}
    for column in columns:
        target = chosen.get(column["letter"], IGNORE)
        if target not in valid:
            problems.append(f"Column {column['letter']}: “{target}” is not a field of this run's manual log.")
            continue
        if target not in (DERIVED, IGNORE):
            by_target.setdefault(target, []).append(column["letter"])
    for target, letters in by_target.items():
        if len(letters) > 1:
            problems.append(f"{target_label(test_run, target)} is chosen for more than one column "
                            f"({', '.join(letters)}).")  # fmt: skip
    if DATETIME in by_target and (DATE in by_target or TIME in by_target):
        problems.append("Choose either one Date and time column or separate Date and Time columns.")
    elif DATETIME not in by_target and DATE not in by_target:
        problems.append("No column is mapped to the date (Date, or Date and time).")
    elif DATE in by_target and TIME not in by_target:
        problems.append("A Date column needs a Time column (or map one Date and time column).")
    for target in by_target:
        if target.startswith(INTERVAL) and target[len(INTERVAL):] not in by_target:
            code = target[len(INTERVAL):]
            problems.append(f"A collection period for {codes[code].full_label} needs that leakage column mapped too.")
    for proposal in proposals:
        if proposal.status == REVIEW and proposal.letter not in reviewed and \
                chosen.get(proposal.letter) == proposal.target:  # fmt: skip
            problems.append(f"Column {proposal.letter}: review required — confirm or change the mapping.")
    return problems


def find_layout_map(test_run, columns):
    setup = manual_log.run_setup(test_run)
    return (
        ManualLogLayoutMap.objects.select_related("reviewed_by")
        .filter(fingerprint=fingerprint(columns), arrangement=setup.arrangement,
                plug_seal_present=setup.plug_seal_present)  # fmt: skip
        .first()
    )


def save_layout_map(batch, columns, chosen, user):
    setup = manual_log.run_setup(batch.test_run)
    layout, _ = ManualLogLayoutMap.objects.update_or_create(
        fingerprint=fingerprint(columns),
        arrangement=setup.arrangement,
        plug_seal_present=setup.plug_seal_present,
        defaults={
            "columns": [{"letter": c["letter"], "header": c["header"], "target": chosen.get(c["letter"], IGNORE)}
                        for c in columns],  # fmt: skip
            "reviewed_by": user,
            "reviewed_at": timezone.now(),
            "source_batch": batch,
        },
    )
    return layout
