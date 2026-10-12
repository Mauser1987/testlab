"""Acceptance requirements in force for a run, and the Result's items kept in step with them (M2E).

    Test Program requirement (planned, baseline)        P1, P2, …
      └─ approved TCN change (issued revision of the run's TCN): replaces it, or makes it
         not applicable to this run, or adds a requirement
            └─ AcceptanceItem of the Result (actual, assessment, remark; source recorded)

Only the run's current issued TCN revision is an approved change; the
changes of a draft revision are pending and shown, not applied. A
requirement on leakage or wear without a seal applies to every seal of the
arrangement under test (one item per seal, or per seal face present in the
Result). Items entered on the Result itself have no source and are left
alone.

sync_requirements() runs while the Result is a Draft (Result page, report
preview, finalization): it creates the items of new requirements, updates
the requirement of existing ones (never the engineer's assessment or
remark), and removes the items of requirements no longer in force — or,
when the engineer already assessed or remarked on one, keeps it marked as
no longer in force for the engineer to decide. Finalization freezes the
items with their sources in the report snapshot.
"""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from testlab.documents.tcn_context import format_date
from testlab.projects.arrangements import SealRole, seal_under_test_roles
from testlab.projects.models import RequirementBasis, TestProgram
from testlab.tcn.models import TcnRequirementChange, TcnRevision

from .inspection import FACES
from .models import WITHDRAWN_PREFIX, AcceptanceItem, Assessment

Action = TcnRequirementChange.Action
WITHDRAWN = WITHDRAWN_PREFIX


@dataclass
class Effective:
    """A requirement in force for the run, with where it comes from."""

    values: dict  # AcceptanceRequirementFields values
    source: str
    program_requirement: object = None
    tcn_change: object = None
    not_applicable: bool = False
    reason: str = ""  # of a TCN change


def _issued(tcn):
    return f"{tcn}, issued {format_date(timezone.localtime(tcn.issued_at))}"


def program_of(project):
    return TestProgram.objects.filter(project=project).prefetch_related("requirements").first()


def approved_tcn(test_run):
    """The run's TCN revision whose requirement changes are in force: the current issued one, or None."""
    current = test_run.current_revision()
    return current if current is not None and current.status == TcnRevision.Status.ISSUED else None


def pending_changes(test_run):
    """Requirement changes of a draft revision of the run: not in force until it is issued."""
    draft = test_run.revisions.filter(status=TcnRevision.Status.DRAFT).first()
    return list(draft.requirement_changes.select_related("program_requirement")) if draft else []


def effective_requirements(test_run):
    program = program_of(test_run.project)
    tcn = approved_tcn(test_run)
    changes = list(tcn.requirement_changes.select_related("program_requirement")) if tcn else []
    by_target = {c.program_requirement_id: c for c in changes if c.program_requirement_id}
    found = []
    for requirement in program.requirements.all() if program else []:
        base = f"{program.reference} {requirement.ref}"
        change = by_target.get(requirement.pk)
        if change is None:
            found.append(Effective(requirement.requirement_values(), base, program_requirement=requirement))
        elif change.action == Action.REPLACE:
            found.append(Effective(change.requirement_values(), f"{_issued(tcn)}: replaces {base}",
                                   program_requirement=requirement, tcn_change=change, reason=change.reason))  # fmt: skip
        else:
            found.append(Effective(requirement.requirement_values(), f"{base}; not applicable to this run per {_issued(tcn)}",
                                   program_requirement=requirement, tcn_change=change, not_applicable=True,
                                   reason=change.reason))  # fmt: skip
    for change in changes:
        if change.action == Action.ADD:
            found.append(Effective(change.requirement_values(), f"{_issued(tcn)}: additional requirement",
                                   tcn_change=change, reason=change.reason))  # fmt: skip
    return found


def _criterion(values):
    text = values["criterion"] or values["requirement_text"] or RequirementBasis(values["basis"]).label
    return text[:120]


def expand(effective, test_run, components):
    """(position, component) targets of one requirement for this Result."""
    values = effective.values
    basis = values["basis"]
    roles = [values["position"]] if values["position"] else seal_under_test_roles(test_run.current_revision().setup.arrangement)
    if basis == RequirementBasis.LEAKAGE_RATE:
        return [(role, None) for role in roles]
    if basis == RequirementBasis.WEAR_RATE:
        faces = [values["face"]] if values["face"] else list(FACES)
        targets = [("", c) for c in components if c.position in roles and c.component in faces]
        return targets or [("", None)]  # no such face in the Result: the item says so
    return [("", None)]


def _key(item_or_values):
    get = item_or_values.get if isinstance(item_or_values, dict) else lambda name: getattr(item_or_values, name)
    return (get("program_requirement_id"), get("tcn_change_id"), get("position"), get("component_id"))


def desired_items(test_run, result):
    components = list(result.components.all())
    desired = []
    for effective in effective_requirements(test_run):
        for position, component in expand(effective, test_run, components):
            values = effective.values
            desired.append({
                "program_requirement_id": effective.program_requirement.pk if effective.program_requirement else None,
                "tcn_change_id": effective.tcn_change.pk if effective.tcn_change else None,
                "position": position,
                "component_id": component.pk if component else None,
                "criterion": _criterion(values),
                "basis": values["basis"],
                "comparison": values["comparison"],
                "limit": values["limit"],
                "unit": values["unit"],
                "requirement_text": values["requirement_text"],
                "source": effective.source[:300],
                "not_applicable": effective.not_applicable,
                "reason": effective.reason,
            })  # fmt: skip
    return desired


REQUIREMENT_FIELDS = ["criterion", "basis", "position", "component_id", "comparison", "limit", "unit",
                      "requirement_text", "source"]  # fmt: skip


def sync_requirements(result, user):
    """Bring the Result's items in step with the requirements in force (Draft only). Returns notices."""
    if result.is_final:
        return []
    notices = []
    with transaction.atomic():
        desired = desired_items(result.test_run, result)
        # From a requirement (its source may have been deleted since); not own items, not withdrawn ones.
        linked = [i for i in result.acceptance_items.all() if i.from_requirement]
        by_key = {_key(i): i for i in linked}
        order = (result.acceptance_items.aggregate(m=Max("order"))["m"] or 0) + 1
        wanted = set()
        for values in desired:
            key = _key(values)
            wanted.add(key)
            item = by_key.get(key)
            if item is None:
                item = AcceptanceItem(result=result, order=order, updated_by=user,
                                      program_requirement_id=key[0], tcn_change_id=key[1])  # fmt: skip
                order += 1
            changed = item.pk is None
            for name in REQUIREMENT_FIELDS:
                if getattr(item, name) != values[name]:
                    setattr(item, name, values[name])
                    changed = True
            if values["not_applicable"] and not item.assessment:
                item.assessment = Assessment.NOT_APPLICABLE
                item.remark = item.remark or f"Not applicable to this run: {values['reason']}"
                changed = True
            if changed:
                item.updated_by = user
                item.save()
        for item in linked:
            if _key(item) in wanted:
                continue
            if not item.assessment and not item.remark.strip():
                item.delete()
            else:
                item.program_requirement = item.tcn_change = None
                if not item.source.startswith(WITHDRAWN):
                    item.source = (WITHDRAWN + item.source)[:300]
                item.updated_by = user
                item.save()
                notices.append(f"“{item.criterion}” is no longer a requirement in force; it was kept because it "
                               "has an assessment or remark. Delete it or keep it as an own criterion.")  # fmt: skip
    return notices


def withdrawn(items):
    return [i for i in items if i.withdrawn]


def seal_label(position):
    return SealRole(position).label if position else ""
