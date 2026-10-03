"""DCS plots of the Result: a reproducible definition plus its report image.

The DCS viewer (static/testlab/dcs_plot.js) sends the definition of what is
on screen — signals and their axis, time window, axis ranges, caption — and
the report image it rendered from that definition with the same plot code.
The definition is checked here against the dataset; names and units are
taken from the dataset, not from the browser.

Storage (server file store, next to the Result pictures):

    projects/<project_no>/runs/<run_no>/result/plots/<time>-plot.png   report image (replaced on update)

"Open in DCS viewer" reads the definition back, so the plot can be redrawn
from the stored dataset, adjusted and updated.
"""

import hashlib
import io
import json
import math

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from testlab.execution import datasets

from .models import ResultPlot

AXES = ("y", "y2")
REPORT_POINTS = datasets.DEFAULT_PLOT_POINTS  # points per signal the viewer fetches for the report image


class PlotError(Exception):
    """The plot cannot be added; the message says why."""


def plot_dir(test_run):
    return f"projects/{test_run.project.project_no}/runs/{test_run.display_no}/result/plots"


def _storage():
    return ResultPlot._meta.get_field("image").storage


def _range(value, what):
    if value in (None, ""):
        return None, None
    try:
        low, high = (float(v) for v in value)
    except (TypeError, ValueError) as error:
        raise PlotError(f"The {what} is not a pair of numbers.") from error
    if not (math.isfinite(low) and math.isfinite(high)) or low >= high:
        raise PlotError(f"The {what} must run from a lower to a higher number.")
    return low, high


def parse_definition(dataset, raw):
    """The plot definition sent by the viewer (JSON text), checked against the dataset."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise PlotError("The plot definition could not be read.") from error
    if not isinstance(data, dict):
        raise PlotError("The plot definition could not be read.")
    by_column = {s["column"]: s for s in dataset.value_signals()}
    signals, seen = [], set()
    for item in data.get("signals") or []:
        column = item.get("column") if isinstance(item, dict) else None
        if column not in by_column or column in seen:
            raise PlotError(f"Column {column} is not a signal of {dataset}.")
        axis = item.get("axis")
        if axis not in AXES:
            raise PlotError("Each signal needs the left or right axis.")
        seen.add(column)
        signal = by_column[column]
        signals.append({"column": column, "name": signal["name"], "unit": signal["unit"], "axis": axis})
    if not signals:
        raise PlotError("Select at least one signal to plot.")
    time_range = _range(data.get("time_range"), "time range")
    y_range = _range(data.get("y_range"), "left axis range")
    y2_range = _range(data.get("y2_range"), "right axis range")
    caption = str(data.get("caption") or "").strip()
    if len(caption) > ResultPlot._meta.get_field("caption").max_length:
        raise PlotError("The caption is too long.")
    return {
        "signals": signals,
        "time_start_h": time_range[0], "time_end_h": time_range[1],
        "y_min": y_range[0], "y_max": y_range[1],
        "y2_min": y2_range[0], "y2_max": y2_range[1],
        "caption": caption,
    }  # fmt: skip


def _inspect_png(content):
    max_bytes = settings.TESTLAB_RESULT_IMAGE_MAX_MB * 1024 * 1024
    if not content or len(content) > max_bytes:
        raise PlotError("The rendered plot image is missing or too large.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            if image.format != "PNG":
                raise PlotError("The rendered plot image is not a PNG.")
            return image.size
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise PlotError("The rendered plot image could not be read.") from error


def _rendering(dataset, definition):
    """How the dataset was reduced for the image (same request the viewer makes)."""
    data = datasets.plot_data(
        dataset, {s["column"] for s in definition["signals"]},
        definition["time_start_h"], definition["time_end_h"], REPORT_POINTS,
    )  # fmt: skip
    return {
        "samples_in_window": data["samples_in_window"],
        "points_per_signal": data["points_per_signal"],
        "decimated": data["decimated"],
    }


def _save_image(test_run, content):
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    return _storage().save(f"{plot_dir(test_run)}/{stamp}-plot.png", ContentFile(content))


def _image_fields(content):
    width, height = _inspect_png(content)
    return {"image_sha256": hashlib.sha256(content).hexdigest(), "image_width": width, "image_height": height}


def next_order(result):
    highest = result.plots.aggregate(m=Max("order"))["m"]
    return 0 if highest is None else highest + 1


def add_plot(result, dataset, raw_definition, image_content, user):
    if dataset.test_run_id != result.test_run_id:
        raise PlotError(f"{dataset} belongs to another run.")
    definition = parse_definition(dataset, raw_definition)
    fields = _image_fields(image_content)
    rendering = _rendering(dataset, definition)
    name = _save_image(result.test_run, image_content)
    try:
        with transaction.atomic():
            return ResultPlot.objects.create(
                result=result, dataset=dataset, order=next_order(result), image=name, rendering=rendering,
                created_by=user, updated_by=user, **definition, **fields,
            )  # fmt: skip
    except Exception:
        _storage().delete(name)
        raise


def update_plot(plot, raw_definition, image_content, user):
    """Replace the definition and image of a plot (redrawn in the viewer); the old image is removed."""
    definition = parse_definition(plot.dataset, raw_definition)
    fields = _image_fields(image_content)
    rendering = _rendering(plot.dataset, definition)
    old = plot.image.name
    name = _save_image(plot.result.test_run, image_content)
    try:
        with transaction.atomic():
            for field, value in {**definition, **fields}.items():
                setattr(plot, field, value)
            plot.image, plot.rendering, plot.updated_by = name, rendering, user
            plot.save()
            transaction.on_commit(lambda: _storage().delete(old) if old and _storage().exists(old) else None)
    except Exception:
        _storage().delete(name)
        raise
    return plot


def move(plot, step):
    """Swap the plot with its neighbour (step -1: earlier, +1: later)."""
    siblings = list(plot.result.plots.order_by("order", "pk"))
    index = next(i for i, sibling in enumerate(siblings) if sibling.pk == plot.pk)
    target = index + step
    if not 0 <= target < len(siblings):
        return
    siblings[index], siblings[target] = siblings[target], siblings[index]
    with transaction.atomic():
        for order, sibling in enumerate(siblings):
            if sibling.order != order:
                ResultPlot.objects.filter(pk=sibling.pk).update(order=order)


def delete_plot(plot):
    """Remove a plot of a draft Result: the record and its image. The dataset stays."""
    name = plot.image.name
    with transaction.atomic():
        plot.delete()
        transaction.on_commit(lambda: _storage().delete(name) if name and _storage().exists(name) else None)


def signal_label(signal):
    return f"{signal['name']} [{signal['unit']}]" if signal["unit"] else signal["name"]


def describe(plot):
    """One line per part of the definition, for the Result page."""
    axis_name = {"y": "left", "y2": "right"}
    signals = ", ".join(f"{signal_label(s)} ({axis_name[s['axis']]})" for s in plot.signals)
    window = (
        f"{plot.time_start_h:.3f} – {plot.time_end_h:.3f} h" if plot.time_start_h is not None else "whole recording"
    )
    ranges = []
    for label, low, high in (("left", plot.y_min, plot.y_max), ("right", plot.y2_min, plot.y2_max)):
        if low is not None:
            ranges.append(f"{label} {low:.4g} – {high:.4g}")
    return {"signals": signals, "window": window, "ranges": ", ".join(ranges) or "automatic"}
