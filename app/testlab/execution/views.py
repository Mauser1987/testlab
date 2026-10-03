"""Test execution pages of a Test Run (M2A): Manual log and DCS data."""

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from testlab.tcn.models import TestRun

from . import datasets, manual_log
from .forms import DcsUploadForm, ManualLogEntryForm, plain_number
from .models import DcsDataset, ManualLogEntry


def get_run(pk):
    return get_object_or_404(TestRun.objects.select_related("project"), pk=pk)


def run_context(test_run, tab):
    return {
        "run": test_run,
        "project": test_run.project,
        "tcn": test_run.current_revision(),
        "tab": tab,
        "recording_refused": recording_refusal(test_run),
    }


def recording_refusal(test_run):
    """Why new evidence cannot be recorded for the run yet, or "".

    The single lifecycle/authorization check for recording execution evidence.
    Intentional temporary policy: during development and validation evidence
    may be recorded for a Draft TCN (TESTLAB_EXECUTION_REQUIRES_ISSUED_TCN off,
    the default). TODO(production): switch the setting on so that only an
    issued TCN permits execution. The models stay as they are.
    """
    if settings.TESTLAB_EXECUTION_REQUIRES_ISSUED_TCN and not test_run.has_issued_revision():
        return f"TCN{test_run.display_no} has not been issued yet: readings and DCS data are recorded once it is issued."
    return ""


class ManualLogView(View):
    """The log of a run: quick entry form on top, readings below (newest first)."""

    template_name = "execution/manual_log.html"

    def get(self, request, run_pk):
        test_run = get_run(run_pk)
        return self.render(request, test_run)

    def post(self, request, run_pk):
        test_run = get_run(run_pk)
        if recording_refusal(test_run):
            messages.error(request, recording_refusal(test_run))
            return redirect("execution:log", test_run.pk)
        entries = list(test_run.manual_log_entries.prefetch_related("measurements"))
        columns = manual_log.log_columns(test_run, entries)
        form = ManualLogEntryForm(request.POST, columns=columns)
        if form.is_valid():
            entry = manual_log.save_entry(test_run, form.cleaned_data, columns, request.user)
            messages.success(request, f"Reading of {entry.observed_at:%d-%b-%Y %H:%M} added.")
            return redirect(reverse("execution:log", args=[test_run.pk]) + "#add")
        return self.render(request, test_run, form)

    def render(self, request, test_run, form=None):
        entries = list(test_run.manual_log_entries.prefetch_related("measurements"))
        columns = manual_log.log_columns(test_run, entries)
        origin = manual_log.timeline_origin(test_run)
        rows = manual_log.log_rows(test_run, columns, origin)
        if form is None:
            form = ManualLogEntryForm(columns=columns, previous=rows[-1] if rows else None)
        return render(
            request,
            self.template_name,
            {
                **run_context(test_run, "log"),
                "form": form,
                "columns": columns,
                "groups": [
                    (name, [(column, form[column.code]) for column in group])
                    for name, group in manual_log.column_groups(columns)
                ],
                # The table shows only what has been logged; the form offers every measurement.
                "table_groups": [
                    (name, group, sum(3 if column.is_leakage else 1 for column in group))
                    for name, group in manual_log.column_groups(
                        [c for c in columns if any(c.code in row.values for row in rows)]
                    )
                ],
                "instructed": manual_log.instructed_codes(test_run),
                "rows": list(reversed(rows)),
                "has_leakage": any(c.is_leakage for c in columns),
                "origin": origin,
            },
        )


class EntryMixin:
    def get_entry(self, pk):
        return get_object_or_404(ManualLogEntry.objects.select_related("test_run__project"), pk=pk)


class EntryEditView(EntryMixin, View):
    template_name = "execution/entry_edit.html"

    def form(self, entry, columns, data=None):
        initial = {
            "observed_at": entry.observed_at,
            "note": entry.note,
            "category": entry.category,
            "leakage_hours": entry.leakage_hours,
            **{value.code: plain_number(value.value) for value in entry.measurements.all()},
        }
        return ManualLogEntryForm(data, columns=columns, initial=initial)

    def get(self, request, pk):
        entry = self.get_entry(pk)
        columns = manual_log.log_columns(entry.test_run, [entry])
        return self.render(request, entry, self.form(entry, columns))

    def post(self, request, pk):
        entry = self.get_entry(pk)
        columns = manual_log.log_columns(entry.test_run, [entry])
        form = self.form(entry, columns, request.POST)
        if form.is_valid():
            manual_log.save_entry(entry.test_run, form.cleaned_data, columns, request.user, entry=entry)
            messages.success(request, f"Reading of {entry.observed_at:%d-%b-%Y %H:%M} saved.")
            return redirect("execution:log", entry.test_run.pk)
        return self.render(request, entry, form)

    def render(self, request, entry, form):
        groups = [
            (name, [(column, form[column.code]) for column in group])
            for name, group in manual_log.column_groups(form.columns)
        ]
        return render(
            request,
            self.template_name,
            {**run_context(entry.test_run, "log"), "entry": entry, "form": form, "groups": groups,
             "instructed": manual_log.instructed_codes(entry.test_run)},
        )


class EntryDeleteView(EntryMixin, View):
    template_name = "execution/entry_delete.html"

    def get(self, request, pk):
        entry = self.get_entry(pk)
        return render(request, self.template_name, {**run_context(entry.test_run, "log"), "entry": entry})

    def post(self, request, pk):
        entry = self.get_entry(pk)
        run_pk = entry.test_run.pk
        when = f"{entry.observed_at:%d-%b-%Y %H:%M}"
        entry.delete()
        messages.success(request, f"Reading of {when} deleted.")
        return redirect("execution:log", run_pk)


class DcsListView(View):
    """Datasets of a run, with the import form."""

    template_name = "execution/dcs_list.html"

    def get(self, request, run_pk):
        return self.render(request, get_run(run_pk), DcsUploadForm())

    def post(self, request, run_pk):
        test_run = get_run(run_pk)
        if recording_refusal(test_run):
            messages.error(request, recording_refusal(test_run))
            return redirect("execution:dcs", test_run.pk)
        form = DcsUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                dataset = datasets.import_dataset(test_run, form.cleaned_data["file"], request.user)
            except datasets.DatasetImportError as error:
                form.add_error("file", str(error))
            else:
                messages.success(request, f"{dataset.original_name} imported: {dataset.sample_count} samples.")
                return redirect("execution:dcs_detail", dataset.pk)
        return self.render(request, test_run, form)

    def render(self, request, test_run, form):
        return render(
            request,
            self.template_name,
            {**run_context(test_run, "dcs"), "form": form, "datasets": test_run.dcs_datasets.select_related("imported_by")},
        )


def get_dataset(pk):
    return get_object_or_404(DcsDataset.objects.select_related("test_run__project", "imported_by"), pk=pk)


class DcsDetailView(View):
    template_name = "execution/dcs_detail.html"

    def get(self, request, pk):
        dataset = get_dataset(pk)
        signals = [
            {**signal, "label": f"{signal['name']} [{signal['unit']}]" if signal["unit"] else signal["name"]}
            for signal in dataset.value_signals()
        ]
        return render(
            request,
            self.template_name,
            {
                **run_context(dataset.test_run, "dcs"),
                "dataset": dataset,
                "signals": signals,
                "time_signal": dataset.signals[dataset.time_column],
                "origin": manual_log.timeline_origin(dataset.test_run),
            },
        )


def _float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError as error:
        raise Http404("Invalid number") from error


class DcsDataView(View):
    """Plot data as JSON: ?columns=1,2&start=0.5&end=3.0&points=4000 (hours)."""

    def get(self, request, pk):
        dataset = get_dataset(pk)
        columns = request.GET.get("columns")
        try:
            wanted = None if columns in (None, "") else {int(c) for c in columns.split(",")}
            points = min(max(int(request.GET.get("points", datasets.DEFAULT_PLOT_POINTS)), 100), 20000)
        except ValueError as error:
            raise Http404("Invalid parameter") from error
        data = datasets.plot_data(
            dataset, wanted, _float(request.GET.get("start")), _float(request.GET.get("end")), points
        )
        return JsonResponse(data)


class DcsRawView(View):
    """The imported file, byte for byte, under its original name."""

    def get(self, request, pk):
        dataset = get_dataset(pk)
        return FileResponse(
            dataset.raw_file.open("rb"), as_attachment=True, filename=dataset.original_name,
            content_type="application/octet-stream",
        )
