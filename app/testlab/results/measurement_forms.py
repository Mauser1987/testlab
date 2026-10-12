"""Forms of the seal-face measurements (M2D): plan, add, settings, report options."""

from django import forms

from testlab.execution.forms import ReadingField, plain_number

from .facemeasure import mahr, roundpak
from .inspection import Stage
from .models import TestResult

UNIT_CHOICES = [("in", "in"), ("mm", "mm")]
TXT = {"accept": ".txt,.TXT,text/plain"}


def _float(value):
    return None if value is None else float(value)


class MeasurementPlanForm(forms.ModelForm):
    """Which measurement kinds the seal faces of this Result need; components may override."""

    class Meta:
        model = TestResult
        fields = ["dimensional_applicability", "mahr_applicability", "roundpak_applicability"]


class AddMeasurementChoiceForm(forms.Form):
    """Step 1 of "+ Add measurement": kind and stage (GET)."""

    kind = forms.ChoiceField(label="Measurement", widget=forms.RadioSelect)
    stage = forms.ChoiceField(label="Stage", choices=Stage.choices, widget=forms.RadioSelect)

    def __init__(self, *args, component, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [(k, component.kind_label(k)) for k in component.applicable_kinds()]


class FaceDimensionsMixin(forms.Form):
    od = ReadingField(label="Face OD", required=False, max_digits=10, decimal_places=4)
    id = ReadingField(label="Face ID", required=False, max_digits=10, decimal_places=4)
    units = forms.ChoiceField(label="Unit", choices=UNIT_CHOICES)

    def initial_from(self, component):
        self.initial.setdefault("units", component.diameter_unit)
        if component.face_od is not None:
            self.initial.setdefault("od", plain_number(component.face_od))
        if component.face_id is not None:
            self.initial.setdefault("id", plain_number(component.face_id))


class MahrUploadForm(FaceDimensionsMixin):
    left_file = forms.FileField(label="Left-side scan (Mahr TXT)", widget=forms.ClearableFileInput(attrs=TXT))
    right_file = forms.FileField(label="Right-side scan (Mahr TXT)", widget=forms.ClearableFileInput(attrs=TXT))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("od") is None or cleaned.get("id") is None:
            raise forms.ValidationError("Enter the face OD and ID: the taper needs the radial face width.")
        return cleaned


class RoundpakUploadForm(FaceDimensionsMixin):
    file = forms.FileField(label="ROUNDPAK CSV", widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}))

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get("od") is None) != (cleaned.get("id") is None):
            raise forms.ValidationError("Enter both OD and ID, or leave both blank.")
        return cleaned


class DimensionalForm(forms.Form):
    """Face length of a seal face [in]; on a sleeve or backing ring a named feature in in or mm."""

    feature = forms.CharField(label="Measured feature", max_length=100, help_text="e.g. OD at the seal seat, thickness")
    value = ReadingField(label="Face length [in]", max_digits=16, decimal_places=6)
    unit = forms.ChoiceField(label="Unit", choices=UNIT_CHOICES, initial="in")
    instrument = forms.CharField(label="Gauge / instrument", required=False, max_length=100)
    remark = forms.CharField(label="Remark", required=False, max_length=300)

    def __init__(self, *args, component, **kwargs):
        super().__init__(*args, **kwargs)
        if component.is_face:
            del self.fields["feature"]
            del self.fields["unit"]
        else:
            self.fields["value"].label = "Value"

    def cleaned_unit(self):
        return self.cleaned_data.get("unit", "in")


class DisplayMixin:
    def display_rows(self):
        """(label, value as shown) of the stored settings, choices by their label."""
        rows = []
        for name, field in self.fields.items():
            value = self.initial.get(name)
            if isinstance(field, forms.BooleanField):
                shown = "yes" if value else "no"
            elif isinstance(field, forms.ChoiceField):
                shown = dict(field.choices).get(value, value) or "—"
            else:
                shown = "—" if value in (None, "") else value
            rows.append((field.label, shown))
        return rows


class MahrSettingsForm(DisplayMixin, forms.Form):
    od = ReadingField(label="Face OD", max_digits=10, decimal_places=4)
    id = ReadingField(label="Face ID", max_digits=10, decimal_places=4)
    units = forms.ChoiceField(label="Unit", choices=UNIT_CHOICES)
    light_band_um = ReadingField(label="Light-band height [µm]", max_digits=8, decimal_places=4)
    left_direction = forms.ChoiceField(label="Left scan direction", choices=list(mahr.DIRECTIONS.items()))
    left_start = ReadingField(label="Left start [mm]", max_digits=10, decimal_places=4)
    left_end = ReadingField(label="Left end [mm]", max_digits=10, decimal_places=4)
    right_direction = forms.ChoiceField(label="Right scan direction", choices=list(mahr.DIRECTIONS.items()))
    right_start = ReadingField(label="Right start [mm]", max_digits=10, decimal_places=4)
    right_end = ReadingField(label="Right end [mm]", max_digits=10, decimal_places=4)
    pv_view = forms.ChoiceField(label="Profile view (P–V)", choices=list(mahr.VIEWS.items()))
    skip_points = forms.IntegerField(label="Skip first points", min_value=0, max_value=10000,
                                     help_text="Left out of each scan's fit and P–V (template: 5).")  # fmt: skip
    flat_limit_hlb = ReadingField(label="Flat limit [± HLB]", max_digits=6, decimal_places=3)

    @classmethod
    def for_analysis(cls, analysis, data=None):
        initial = {
            "od": analysis.od, "id": analysis.id, "units": analysis.diameter_unit,
            "light_band_um": analysis.light_band_um,
            "left_direction": analysis.left_direction, "right_direction": analysis.right_direction,
            "left_start": analysis.left_start_mm, "left_end": analysis.left_end_mm,
            "right_start": analysis.right_start_mm, "right_end": analysis.right_end_mm,
            "pv_view": analysis.pv_view, "skip_points": analysis.skip_points,
            "flat_limit_hlb": analysis.flat_limit_hlb,
        }  # fmt: skip
        return cls(data, initial={k: _plain(v) for k, v in initial.items()})

    def settings(self):
        c = self.cleaned_data
        return mahr.Settings(
            od=_float(c["od"]), id=_float(c["id"]), units=c["units"], light_band_um=_float(c["light_band_um"]),
            left_direction=c["left_direction"], right_direction=c["right_direction"],
            left_start=_float(c["left_start"]), left_end=_float(c["left_end"]),
            right_start=_float(c["right_start"]), right_end=_float(c["right_end"]), pv_view=c["pv_view"],
            skip_points=c["skip_points"], flat_limit_hlb=_float(c["flat_limit_hlb"]),
        )  # fmt: skip


class RoundpakSettingsForm(DisplayMixin, forms.Form):
    od = ReadingField(label="Face OD", required=False, max_digits=10, decimal_places=4)
    id = ReadingField(label="Face ID", required=False, max_digits=10, decimal_places=4)
    units = forms.ChoiceField(label="Unit", choices=UNIT_CHOICES)
    light_band_um = ReadingField(label="Light-band height [µm]", max_digits=8, decimal_places=4)
    circle_scan = forms.ChoiceField(label="Circular scan", required=False)
    circle_source = forms.ChoiceField(label="Circular plot source", choices=list(roundpak.SOURCES.items()))
    left_scan = forms.ChoiceField(label="Left radial scan", required=False)
    left_start = ReadingField(label="Left min radius [mm]", required=False, max_digits=10, decimal_places=4)
    left_end = ReadingField(label="Left max radius [mm]", required=False, max_digits=10, decimal_places=4)
    right_scan = forms.ChoiceField(label="Right radial scan", required=False)
    right_start = ReadingField(label="Right min radius [mm]", required=False, max_digits=10, decimal_places=4)
    right_end = ReadingField(label="Right max radius [mm]", required=False, max_digits=10, decimal_places=4)
    radial_source = forms.ChoiceField(label="Radial source", choices=list(roundpak.SOURCES.items()))
    flat_limit_hlb = ReadingField(label="Flat limit [± HLB]", max_digits=6, decimal_places=3)

    def __init__(self, *args, scans, **kwargs):
        super().__init__(*args, **kwargs)
        circular = [(s["id"], s["name"]) for s in scans if s["kind"] == "circular"]
        radial = [(s["id"], s["name"]) for s in scans if s["kind"] == "radial"]
        self.fields["circle_scan"].choices = circular or [("", "— none in this file —")]
        for side in ("left", "right"):
            self.fields[f"{side}_scan"].choices = radial or [("", "— none in this file —")]
        self.has_radial = len(radial) >= 2
        self.has_circular = bool(circular)

    @classmethod
    def for_analysis(cls, analysis, data=None):
        initial = {
            "od": analysis.od, "id": analysis.id, "units": analysis.diameter_unit,
            "light_band_um": analysis.light_band_um, "circle_scan": analysis.circle_scan,
            "circle_source": analysis.circle_source, "left_scan": analysis.left_scan,
            "right_scan": analysis.right_scan, "radial_source": analysis.radial_source,
            "left_start": analysis.left_start_mm, "left_end": analysis.left_end_mm,
            "right_start": analysis.right_start_mm, "right_end": analysis.right_end_mm,
            "flat_limit_hlb": analysis.flat_limit_hlb if analysis.flat_limit_hlb is not None
            else roundpak.DEFAULT_FLAT_LIMIT_HLB,
        }  # fmt: skip
        return cls(data, scans=analysis.detail.get("scans", []), initial={k: _plain(v) for k, v in initial.items()})

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get("od") is None) != (cleaned.get("id") is None):
            raise forms.ValidationError("Enter both OD and ID, or leave both blank.")
        return cleaned

    def settings(self):
        c = self.cleaned_data
        return roundpak.Settings(
            od=_float(c["od"]), id=_float(c["id"]), units=c["units"], light_band_um=_float(c["light_band_um"]),
            circle_scan=c["circle_scan"] or None, circle_source=c["circle_source"],
            left_scan=c["left_scan"] or None, right_scan=c["right_scan"] or None, radial_source=c["radial_source"],
            left_start=_float(c["left_start"]), left_end=_float(c["left_end"]),
            right_start=_float(c["right_start"]), right_end=_float(c["right_end"]),
            flat_limit_hlb=_float(c["flat_limit_hlb"]),
        )  # fmt: skip


class RemarkForm(forms.Form):
    remark = forms.CharField(label="Remark", required=False, max_length=300)

    def __init__(self, *args, measurement, **kwargs):
        kwargs.setdefault("initial", {"remark": measurement.remark})
        super().__init__(*args, **kwargs)


def _plain(value):
    """A stored float as a person would type it: 5.034, not 5.034000000000001."""
    if isinstance(value, float):
        return format(value, ".10g")
    return value

