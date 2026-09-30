"""Process Conditions and Plug Seal: data part of the domain correction.

The Plug Seal is the test equipment that establishes the process
conditions, so the former Plug Seal conditions (plug_*) described the same
physical conditions as the Process Conditions (process_*). This migration,
on every RunSetup (project defaults and TCN revisions of any status):

* moves each plug_* value into the empty process_* field of the same
  quantity (equal values: nothing to move);
* renames the monitoring codes plug_pressure / plug_inlet_temp / plug_flow
  to process_pressure / process_inlet_temp / process_flow (plug_face_temp
  and plug_leakage are measurements of the Plug Seal itself and stay);
* installs the Plug Seal (flag and empty position) on single setups: a
  single seal is only tested with the Plug Seal.

It changes nothing and stops with a report when a row needs an engineering
decision:

* a process and a Plug Seal value that are both filled and differ;
* process conditions (values or monitoring codes) on a setup without Plug
  Seal: process conditions exist only with the Plug Seal.

Issued, superseded and cancelled TCNs follow the same rules; only their
working RunSetup row changes. Their stored PDF, its SHA-256 and the issued
snapshot are the controlled record and are not touched.

Migration 0006 then removes the plug_* fields and adds the constraints.
Reverse: nothing to undo; merged values stay in the process_* fields.
"""

from django.db import migrations

# Frozen copies of the rules at the time of this migration.
FIELD_PAIRS = [
    ("process_medium", "plug_medium", "medium"),
    ("process_pressure", "plug_pressure", "pressure"),
    ("process_inlet_temperature", "plug_inlet_temperature", "inlet temperature"),
    ("process_flow", "plug_flow", "flow"),
]
PROCESS_FIELDS = [process for process, _, _ in FIELD_PAIRS]
CODE_RENAMES = {"plug_pressure": "process_pressure", "plug_inlet_temp": "process_inlet_temp", "plug_flow": "process_flow"}
PROCESS_CODES = ["process_pressure", "process_inlet_temp", "process_outlet_temp", "process_flow"]
CANONICAL_CODES = PROCESS_CODES + [
    "seal_support_pressure", "seal_support_inlet_temp", "seal_support_outlet_temp", "seal_support_flow",
    "plug_face_temp", "plug_leakage", "test_face_temp", "test_leakage",
    "inboard_face_temp", "inboard_leakage", "outboard_face_temp", "outboard_leakage",
]  # fmt: skip


class ProcessConditionsConflict(Exception):
    """Rows that need an engineering decision before the migration can run."""


def _owner(setup, Project, TcnRevision):
    project = Project.objects.filter(default_setup_id=setup.pk).first()
    if project:
        return f"project defaults of {project.project_no}"
    tcn = TcnRevision.objects.filter(setup_id=setup.pk).select_related("test_run__project").first()
    if tcn:
        run = tcn.test_run
        return f"{run.project.project_no} TCN{run.run_no:03d} rev {tcn.revision} ({tcn.status})"
    return "not used by a project or TCN"


def _renamed_codes(codes):
    renamed = list(dict.fromkeys(CODE_RENAMES.get(code, code) for code in codes))
    if set(renamed) <= set(CANONICAL_CODES):
        renamed.sort(key=CANONICAL_CODES.index)
    return renamed


def merge_plug_conditions(apps, schema_editor):
    RunSetup = apps.get_model("projects", "RunSetup")
    SealPosition = apps.get_model("projects", "SealPosition")
    Project = apps.get_model("projects", "Project")
    TcnRevision = apps.get_model("tcn", "TcnRevision")

    problems = []
    for setup in RunSetup.objects.order_by("pk"):
        where = f"RunSetup {setup.pk} ({_owner(setup, Project, TcnRevision)})"
        if setup.arrangement == "single" and not setup.plug_seal_present:
            setup.plug_seal_present = True
            if not SealPosition.objects.filter(setup=setup, role="plug").exists():
                SealPosition.objects.create(setup=setup, role="plug")
        for process_field, plug_field, quantity in FIELD_PAIRS:
            process, plug = getattr(setup, process_field), getattr(setup, plug_field)
            if not plug or plug == process:
                continue
            if process:
                problems.append(f"{where}: {quantity} differs — Process “{process}”, Plug Seal “{plug}”.")
            else:
                setattr(setup, process_field, plug)
            setattr(setup, plug_field, "")
        setup.monitored_parameters = _renamed_codes(setup.monitored_parameters or [])
        if not setup.plug_seal_present:
            filled = [f"{field} “{getattr(setup, field)}”" for field in PROCESS_FIELDS if getattr(setup, field)]
            ticked = [code for code in setup.monitored_parameters if code in PROCESS_CODES]
            if filled or ticked:
                problems.append(
                    f"{where}: process conditions without a Plug Seal — {', '.join(filled + ticked)}."
                )
        setup.save()

    if problems:
        raise ProcessConditionsConflict(
            "Process Conditions / Plug Seal migration stopped; nothing was changed. "
            "These rows need an engineering decision:\n  "
            + "\n  ".join(problems)
            + "\nResolve them with the previous TestLab version (install the Plug Seal, or clear or "
            "align the values), then run migrate again."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0004_project_default_setup_required"),
        ("tcn", "0001_initial"),  # to name the TCN that owns a setup in the report
    ]

    operations = [migrations.RunPython(merge_plug_conditions, migrations.RunPython.noop)]
