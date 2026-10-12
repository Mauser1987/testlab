from django import template
from django.urls import reverse

from testlab.results import formatting, measurement_summary, plots
from testlab.results.acceptance import format_number
from testlab.results.facemeasure import mahr
from testlab.results.formatting import fixed, signed_fixed
from testlab.results.models import ResultPlot, TestResult

register = template.Library()


@register.filter
def number(value):
    """A value as entered or calculated: 1.250370 → 1.25037, 0.0000053 → 5.3E-6, None → ""."""
    return "" if value in (None, "") else format_number(value)


register.filter("signed", formatting.signed)


@register.inclusion_tag("results/_plot_to_result.html", takes_context=True)
def plot_to_result(context, dataset):
    """The "Add plot to Result" panel of the DCS viewer; ?plot=<id> opens a Result plot for redrawing."""
    request = context["request"]
    result = TestResult.objects.filter(test_run=dataset.test_run_id).first()
    plot = None
    if result is not None and request.GET.get("plot", "").isdigit():
        plot = ResultPlot.objects.filter(pk=int(request.GET["plot"]), result=result, dataset=dataset).first()
    config = {
        "reportPoints": plots.REPORT_POINTS,
        "addUrl": reverse("results:plot_add", args=[dataset.pk]),
        "plot": plot.definition() if plot else None,
        "updateUrl": reverse("results:plot_update", args=[plot.pk]) if plot else None,
    }
    return {
        "dataset": dataset,
        "run": context["run"],
        "result": result,
        "plot": plot,
        "config": config,
        "recording_refused": context.get("result_refused"),  # the plot is added to the Result, not to the DCS data
        "csrf_token": context.get("csrf_token"),
    }


register.filter("fixed", formatting.fixed)
register.filter("signed_fixed", formatting.signed_fixed)
register.filter("quantity_value", formatting.quantity_value)
register.filter("quantity_delta", formatting.quantity_delta)


@register.filter
def slot_label(status):
    return measurement_summary.STATUS_LABELS.get(status, status)


@register.filter
def measurement_brief(measurement):
    """The headline values of a measurement, one line."""
    analysis = measurement.analysis
    if analysis is None:
        return ""
    if measurement.kind == "dimensional":
        return f"{format_number(analysis.value)} {analysis.unit}"
    if measurement.kind == "mahr":
        parts = [f"taper {signed_fixed(analysis.taper_um, 4)} µm ({signed_fixed(analysis.taper_hlb, 3)} HLB)",
                 analysis.classification]  # fmt: skip
        if analysis.mean_ra_um is not None:
            parts.append(f"Ra {fixed(analysis.mean_ra_um, 3)} µm")
        return " · ".join(parts)
    parts = []
    if analysis.flatness_um is not None:
        parts.append(f"FLTt {fixed(analysis.flatness_um, 3)} µm")
    if analysis.check_result:
        parts.append(analysis.check_result)
    if analysis.lfd_pv_um is not None:
        parts.append(f"LFD P–V {fixed(analysis.lfd_pv_um, 4)} µm")
    if analysis.taper_um is not None:
        parts.append(f"taper {signed_fixed(analysis.taper_um, 4)} µm" +
                     (f" {analysis.classification}" if analysis.classification else ""))  # fmt: skip
    return " · ".join(parts)


@register.filter
def mahr_direction(code):
    return mahr.DIRECTIONS.get(code, code)


@register.filter
def mahr_view(code):
    return mahr.VIEWS.get(code, code)


@register.filter
def subtract(value, other):
    if value in (None, "") or other in (None, ""):
        return None
    return value - other
