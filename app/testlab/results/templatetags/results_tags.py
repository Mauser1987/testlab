from django import template
from django.urls import reverse

from testlab.results import plots
from testlab.results.acceptance import format_number
from testlab.results.models import ResultPlot, TestResult

register = template.Library()


@register.filter
def number(value):
    """A value as entered or calculated: 1.250370 → 1.25037, 0.0000053 → 5.3E-6, None → ""."""
    return "" if value in (None, "") else format_number(value)


@register.filter
def signed(value):
    """A difference with its sign: +0.066, −0.047, 0."""
    if value in (None, ""):
        return ""
    text = format_number(abs(value))
    if value > 0:
        return f"+{text}"
    if value < 0:
        return f"−{text}"
    return text


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
        "recording_refused": context.get("recording_refused"),
        "csrf_token": context.get("csrf_token"),
    }
