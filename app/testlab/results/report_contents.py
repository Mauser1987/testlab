"""What a report profile shows of a Result: the selectable items and the engineer's selection (M2F-B).

The items are the Result's measurement slots (component × kind with a reported measurement, Pre and Post
together), its pictures and its plots. The selection stored (ReportSelection) holds only the differences
from the profile defaults (documents/report_profiles.py), so an item added later starts with its profile
default and "Reset to the profile defaults" is deleting the row. Choosing never touches evidence: it is
allowed while the Result is a Draft and after it is final (a later document presents the frozen record).
"""

from dataclasses import dataclass, field

from django.db import transaction

from testlab.documents import report_profiles
from testlab.documents.report_profiles import FLAGS, figure_choices, resolve

from .inspection import MeasurementKind
from .models import ReportSelection, ResultImage


@dataclass
class Slot:
    key: str
    component: object
    kind: str
    label: str
    figures: dict = field(default_factory=dict)  # code → label

    @property
    def anchor(self):
        return f"slot-{self.component.pk}-{self.kind}"

    @property
    def detailed(self):
        return self.kind in (MeasurementKind.MAHR, MeasurementKind.ROUNDPAK)


def slots(components):
    """Measurement slots with a reported measurement, in component and kind order."""
    found = []
    for component in components:
        reported = {m.kind for m in component.face_measurements.all() if m.reported}
        for kind in component.applicable_kinds():
            if kind in reported:
                found.append(Slot(f"{component.pk}:{kind}", component, kind,
                                  f"{component.label} — {component.kind_label(kind)}", figure_choices(kind)))  # fmt: skip
    return found


def picture_label(picture):
    who = picture.component.label if picture.component_id else "Whole seal"
    text = picture.caption or picture.original_name
    if picture.category == ResultImage.Category.CROSS_SECTION:
        return f"Seal cross section · {text}"
    return f"{picture.get_category_display()} · {who} · {text}"


def items(result, components):
    pictures = list(result.images.select_related("component").order_by("category", "order", "pk"))
    plots = list(result.plots.order_by("order", "pk"))
    return slots(components), pictures, plots


def current(result, profile, components):
    """(resolved selection, stored overrides) of a profile over the Result's live items."""
    found_slots, pictures, plots = items(result, components)
    stored = ReportSelection.objects.filter(result=result, profile=profile).values_list("data", flat=True).first() or {}
    selection = resolve(profile, stored, [(s.key, s.kind) for s in found_slots], [p.pk for p in pictures],
                        [p.pk for p in plots])  # fmt: skip
    return selection, stored


def from_post(post, found_slots, pictures, plots):
    """The complete selection the contents form shows (an unticked box is a deliberate No)."""
    return {
        "flags": {f.key: f"flag:{f.key}" in post for f in FLAGS},
        "slots": {
            s.key: {
                "summary": f"slot:{s.key}:summary" in post,
                "detail": s.detailed and f"slot:{s.key}:detail" in post,
                "figures": [c for c in post.getlist(f"slot:{s.key}:figures") if c in s.figures] if s.detailed else [],
                "remark": s.detailed and f"slot:{s.key}:remark" in post,
            }
            for s in found_slots
        },
        "pictures": {str(p.pk): f"picture:{p.pk}" in post for p in pictures},
        "plots": {str(p.pk): f"plot:{p.pk}" in post for p in plots},
    }


def differences(profile, chosen, found_slots, pictures, plots):
    """The overrides to store: what differs from the profile default."""
    default = resolve(profile, {}, [(s.key, s.kind) for s in found_slots], [p.pk for p in pictures],
                      [p.pk for p in plots])  # fmt: skip
    data = {"flags": {k: v for k, v in chosen["flags"].items() if default["flags"][k] != v}, "slots": {},
            "pictures": {k: v for k, v in chosen["pictures"].items() if default["pictures"][k] != v},
            "plots": {k: v for k, v in chosen["plots"].items() if default["plots"][k] != v}}  # fmt: skip
    for key, value in chosen["slots"].items():
        changed = {part: v for part, v in value.items() if default["slots"][key][part] != v}
        if changed:
            data["slots"][key] = changed
    return report_profiles.clean({k: v for k, v in data.items() if v})


def save(result, profile, post, components, user):
    found_slots, pictures, plots = items(result, components)
    data = differences(profile, from_post(post, found_slots, pictures, plots), found_slots, pictures, plots)
    with transaction.atomic():
        found = ReportSelection.objects.select_for_update().filter(result=result, profile=profile).first()
        if found is None:
            if data:
                ReportSelection.objects.create(result=result, profile=profile, data=data, updated_by=user)
            return data
        kept = found.data or {}
        # Overrides of items this page does not show (e.g. a measurement no longer reported) are kept.
        for part in ("slots", "pictures", "plots"):
            shown = {s.key for s in found_slots} if part == "slots" else {
                str(p.pk) for p in (pictures if part == "pictures" else plots)}  # fmt: skip
            for key, value in (kept.get(part) or {}).items():
                if key not in shown:
                    data.setdefault(part, {})[key] = value
        found.data, found.updated_by = data, user
        found.save()
    return data


def reset(result, profile):
    ReportSelection.objects.filter(result=result, profile=profile).delete()

