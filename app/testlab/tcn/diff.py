"""Differences between a TCN revision and its source TCN (M1 spec §6 S7/S8, §7).

A copied TCN or a new revision starts equal to its source; the engineer
changes only what differs. These functions list what now differs, for the
"changed — was: …" markers on the draft (S7) and the change list shown
before issue (S8, commit 9).

A TCN created from the project defaults has no comparison: the defaults
are edited over time and no snapshot of them is kept, so comparing with
their current values would be misleading.
"""

from dataclasses import dataclass

from testlab.projects import conditions
from testlab.projects.arrangements import (
    PROCESS_PARAMETERS,
    ROLE_SHORT_LABELS,
    SealRole,
    parameter_label,
    role_parameters,
    seal_support_label,
)
from testlab.projects.models import RunSetup, SealPosition

from .models import TcnRevision

HEADER_FIELDS = ["project_description", "prepared_by"]
SETUP_FIELDS = (
    ["run_description", "arrangement", "reference_drawing", "plug_seal_present"]
    + conditions.COMMON_FIELDS
    + conditions.PROCESS_FIELDS
    + conditions.SEAL_SUPPORT_FIELDS
    + ["monitored_parameters"]
)


@dataclass(frozen=True)
class Change:
    key: str  # name of the form input, e.g. "speed" or "inboard-stationary_face"
    label: str
    old: str  # display values
    new: str


def source_changes(tcn):
    """Changes of `tcn` against its source TCN, or None when it has none."""
    source = tcn.source_tcn
    if source is None:
        return None
    changes = []
    for field in HEADER_FIELDS:
        old, new = getattr(source, field), getattr(tcn, field)
        if old != new:
            changes.append(Change(field, str(TcnRevision._meta.get_field(field).verbose_name), old, new))
    return changes + setup_changes(source.setup, tcn.setup)


def setup_changes(old, new):
    """Changes between two run setups, in the order of the run setup form."""
    changes = []
    support_label = seal_support_label(new.arrangement)
    for field in SETUP_FIELDS:
        before, after = _display(old, field, support_label), _display(new, field, support_label)
        if before != after:
            label = str(RunSetup._meta.get_field(field).verbose_name).replace("Seal-support", support_label)
            changes.append(Change(field, label, before, after))
    old_positions = {p.role: p for p in old.positions.all()}
    new_positions = {p.role: p for p in new.positions.all()}
    for role in SealRole:
        for field in SealPosition.DESCRIPTIVE_FIELDS:
            # A position that does not exist on one side counts as empty.
            before = getattr(old_positions.get(role), field, "")
            after = getattr(new_positions.get(role), field, "")
            if before != after:
                label = f"{SealRole(role).label}: {SealPosition._meta.get_field(field).verbose_name}"
                changes.append(Change(f"{role}-{field}", label, before, after))
    return changes


def _display(setup, field, support_label):
    if field == "arrangement":
        return setup.get_arrangement_display()
    if field == "plug_seal_present":
        return "Installed" if setup.plug_seal_present else "Not installed"
    if field == "monitored_parameters":
        return ", ".join(_parameter_name(code, support_label) for code in setup.monitored_parameters)
    return getattr(setup, field)


def _parameter_name(code, support_label):
    """Parameter with its group, e.g. "IB Leakage [ml]", "Barrier Pressure [barg]"."""
    if code in PROCESS_PARAMETERS:
        group = "Process"
    elif code.startswith("seal_support_"):
        group = support_label
    else:
        group = next(ROLE_SHORT_LABELS[role] for role in SealRole if code in role_parameters(role))
    return f"{group} {parameter_label(code)}"
