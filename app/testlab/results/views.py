"""Result tab of a Test Run (M2B): one page, six sections.

    Summary · Plots · Measurements · Pictures · Acceptance · Conclusion

Each section saves on its own and returns to its place on the page, so the
engineer never fills one enormous form. Every change goes through the same
lifecycle/authorization check as the manual log (recording_refusal).
"""

import mimetypes

from django.contrib import messages
from django.db.models import Prefetch
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from testlab.documents.pdf import PdfConversionError
from testlab.documents.render import run_report_template
from testlab.documents.run_report_context import build_run_report_context, report_assets, run_report_file_name
from testlab.execution import manual_log
from testlab.execution.views import get_dataset, get_run, recording_refusal, run_context

from . import acceptance, evidence, images, plots, services
from .forms import (
    AcceptanceItemForm,
    AddComponentForm,
    ComponentFormSet,
    ImageEditForm,
    ImageUploadForm,
    MeasurementsForm,
    NarrativeForm,
)
from .models import AcceptanceItem, InspectionMeasurement, ResultComponent, ResultImage, ResultPlot, TestResult


def get_result(test_run):
    return (
        TestResult.objects.filter(test_run=test_run)
        .prefetch_related(
            Prefetch("components", queryset=ResultComponent.objects.prefetch_related(
                Prefetch("measurements", queryset=InspectionMeasurement.objects.all()))),
            Prefetch("images", queryset=ResultImage.objects.select_related("uploaded_by", "component")),
            Prefetch("acceptance_items", queryset=AcceptanceItem.objects.select_related("component")),
            Prefetch("plots", queryset=ResultPlot.objects.select_related("dataset", "updated_by")),
        )
        .first()
    )  # fmt: skip


def section_url(test_run, section):
    return reverse("results:result", args=[test_run.pk]) + f"#{section}"


def refused(request, test_run, section="summary"):
    """Redirect with the reason when the run's Result may not be changed yet, else None."""
    if recording_refusal(test_run):
        messages.error(
            request, f"TCN{test_run.display_no} has not been issued yet: the Result can be recorded once it is issued."
        )
        return redirect(section_url(test_run, section))
    return None


def seal_positions(test_run, leakage):
    """Seals whose leakage can be assessed: those of the configuration plus any logged."""
    setup = manual_log.run_setup(test_run)
    positions = list(setup.applicable_roles())
    positions += [seal.position for seal in leakage if seal.position not in positions]
    return positions


def render_result(request, test_run, result, **forms):
    context = {**run_context(test_run, "result"), "result": result}
    if result is None:
        return render(request, "results/result_start.html", context)
    found = evidence.collect(test_run, result)
    components = found["components"]
    items = list(result.acceptance_items.all())
    evaluations = acceptance.evaluate_all(items, acceptance.Evidence(found["leakage"], found["wear"], found["period"]))
    positions = seal_positions(test_run, found["leakage"])
    addable = services.addable_components(result)
    context.update(found)
    context.update(
        {
            "identity_formset": forms.get("identity_formset")
            or ComponentFormSet(queryset=result.components.order_by("pk")),
            "add_component_form": AddComponentForm(addable=addable) if addable else None,
            "measurements_form": forms.get("measurements_form") or MeasurementsForm(components=components),
            "upload_form": forms.get("upload_form") or ImageUploadForm(components=components),
            "pictures": images.picture_groups(result, components),
            "plots": [(plot, plots.describe(plot)) for plot in result.plots.all()],
            "evaluations": evaluations,
            "acceptance_form": forms.get("acceptance_form")
            or AcceptanceItemForm(result=result, positions=positions),
            "narrative_form": forms.get("narrative_form") or NarrativeForm(instance=result),
            "wear_by_measurement": {w.measurement.pk: w for w in found["wear"]},
        }
    )
    context["identity_rows"] = sorted(context["identity_formset"].forms, key=lambda form: form.instance.sort_key)
    return render(request, "results/result.html", context)


class ResultView(View):
    def get(self, request, run_pk):
        test_run = get_run(run_pk)
        return render_result(request, test_run, get_result(test_run))


class ResultStartView(View):
    def post(self, request, run_pk):
        test_run = get_run(run_pk)
        if response := refused(request, test_run):
            return response
        try:
            services.create_result(test_run, request.user)
        except services.ResultRuleError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Result of Run {test_run.display_no} started (Draft).")
        return redirect("results:result", test_run.pk)


class ResultSectionView(View):
    """POST handler of one section of an existing Result."""

    section = "summary"

    def post(self, request, run_pk):
        test_run = get_run(run_pk)
        if response := refused(request, test_run, self.section):
            return response
        result = get_result(test_run)
        if result is None:
            return redirect("results:result", test_run.pk)
        return self.handle(request, test_run, result)


class ComponentsView(ResultSectionView):
    section = "measurements"

    def handle(self, request, test_run, result):
        formset = ComponentFormSet(request.POST, queryset=result.components.order_by("pk"))
        if formset.is_valid():
            formset.save()
            services.touch(result, request.user)
            messages.success(request, "Components saved.")
            return redirect(section_url(test_run, self.section))
        return render_result(request, test_run, result, identity_formset=formset)


class ComponentAddView(ResultSectionView):
    section = "measurements"

    def handle(self, request, test_run, result):
        form = AddComponentForm(request.POST, addable=services.addable_components(result))
        if form.is_valid():
            try:
                component = services.add_component(result, *form.pair(), request.user)
            except services.ResultRuleError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, f"{component} added.")
        else:
            messages.error(request, "That component cannot be added.")
        return redirect(section_url(test_run, self.section))


class ComponentRemoveView(View):
    def post(self, request, pk):
        component = get_object_or_404(ResultComponent.objects.select_related("result__test_run"), pk=pk)
        test_run = component.result.test_run
        if response := refused(request, test_run, "measurements"):
            return response
        try:
            services.remove_component(component, request.user)
        except services.ResultRuleError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"{component} removed.")
        return redirect(section_url(test_run, "measurements"))


class MeasurementsView(ResultSectionView):
    section = "measurements"

    def handle(self, request, test_run, result):
        form = MeasurementsForm(request.POST, components=services.sorted_components(result))
        if form.is_valid():
            services.save_measurements(result, form.values(), request.user)
            messages.success(request, "Measurements saved.")
            return redirect(section_url(test_run, self.section))
        return render_result(request, test_run, result, measurements_form=form)


class ImageUploadView(ResultSectionView):
    section = "pictures"

    def handle(self, request, test_run, result):
        form = ImageUploadForm(request.POST, request.FILES, components=services.sorted_components(result))
        if form.is_valid():
            added, errors = 0, []
            for uploaded in form.cleaned_data["files"]:
                try:
                    images.add_image(
                        result, uploaded, request.user, form.cleaned_data["category"],
                        form.cleaned_data["component"], form.cleaned_data["caption"],
                    )
                    added += 1
                except images.ImageUploadError as error:
                    errors.append(str(error))
            if added:
                services.touch(result, request.user)
                messages.success(request, f"{added} picture{'s' if added != 1 else ''} added.")
            for error in errors:
                messages.error(request, error)
            return redirect(section_url(test_run, self.section))
        return render_result(request, test_run, result, upload_form=form)


def get_image(pk):
    return get_object_or_404(ResultImage.objects.select_related("result__test_run__project", "component"), pk=pk)


class ImageEditView(View):
    template_name = "results/image_edit.html"

    def get(self, request, pk):
        image = get_image(pk)
        form = ImageEditForm(
            components=services.sorted_components(image.result),
            initial={"category": image.category, "component": image.component_id or "", "caption": image.caption},
        )
        return self.render(request, image, form)

    def post(self, request, pk):
        image = get_image(pk)
        test_run = image.result.test_run
        if response := refused(request, test_run, "pictures"):
            return response
        form = ImageEditForm(request.POST, components=services.sorted_components(image.result))
        if form.is_valid():
            category, component = form.cleaned_data["category"], form.cleaned_data["component"]
            if (category, component) != (image.category, image.component):
                image.order = images.next_order(image.result, category, component)
            image.category, image.component, image.caption = category, component, form.cleaned_data["caption"]
            image.save()
            services.touch(image.result, request.user)
            messages.success(request, f"{image.original_name} saved.")
            return redirect(section_url(test_run, "pictures"))
        return self.render(request, image, form)

    def render(self, request, image, form):
        context = {**run_context(image.result.test_run, "result"), "image": image, "form": form}
        return render(request, self.template_name, context)


class ImageDeleteView(View):
    template_name = "results/image_delete.html"

    def get(self, request, pk):
        image = get_image(pk)
        return render(request, self.template_name, {**run_context(image.result.test_run, "result"), "image": image})

    def post(self, request, pk):
        image = get_image(pk)
        test_run = image.result.test_run
        if response := refused(request, test_run, "pictures"):
            return response
        name = image.original_name
        images.delete_image(image)
        services.touch(image.result, request.user)
        messages.success(request, f"{name} deleted.")
        return redirect(section_url(test_run, "pictures"))


class ImageMoveView(View):
    def post(self, request, pk):
        image = get_image(pk)
        test_run = image.result.test_run
        if response := refused(request, test_run, "pictures"):
            return response
        images.move(image, -1 if request.POST.get("direction") == "up" else 1)
        return redirect(section_url(test_run, "pictures"))


class ImageFileView(View):
    """The original picture, byte for byte (inline), or its display copy."""

    preview = False

    def get(self, request, pk):
        image = get_image(pk)
        if self.preview:
            name = images.preview_name(image)
            return FileResponse(image.file.storage.open(name, "rb"), content_type="image/jpeg")
        content_type = mimetypes.guess_type(image.original_name)[0] or "application/octet-stream"
        return FileResponse(
            image.file.open("rb"), filename=image.original_name, content_type=content_type,
            as_attachment=request.GET.get("download") == "1",
        )


class CompareView(View):
    """Pre and Post pictures of one component side by side, large."""

    template_name = "results/compare.html"

    def get(self, request, run_pk, component_pk):
        test_run = get_run(run_pk)
        result = get_result(test_run)
        component = get_object_or_404(ResultComponent, pk=component_pk, result=result)
        groups = images.picture_groups(result, [component])
        comparison = next((c for c in groups["comparisons"] if c["component"] == component), None)
        measurements = list(component.measurements.all())
        context = {
            **run_context(test_run, "result"), "result": result, "component": component,
            "pre": comparison["pre"] if comparison else [], "post": comparison["post"] if comparison else [],
            "measurements": measurements,
        }  # fmt: skip
        return render(request, self.template_name, context)


class AcceptanceAddView(ResultSectionView):
    section = "acceptance"

    def handle(self, request, test_run, result):
        found = evidence.collect(test_run, result)
        item = AcceptanceItem(result=result, order=services.next_acceptance_order(result), updated_by=request.user)
        form = AcceptanceItemForm(
            request.POST, instance=item, result=result, positions=seal_positions(test_run, found["leakage"])
        )
        if form.is_valid():
            form.save()
            services.touch(result, request.user)
            messages.success(request, f"Criterion “{item.criterion}” added.")
            return redirect(section_url(test_run, self.section))
        return render_result(request, test_run, result, acceptance_form=form)


def get_item(pk):
    return get_object_or_404(AcceptanceItem.objects.select_related("result__test_run__project"), pk=pk)


class AcceptanceEditView(View):
    template_name = "results/acceptance_edit.html"

    def form(self, item, data=None):
        test_run = item.result.test_run
        leakage = evidence.leakage_summary(test_run)
        return AcceptanceItemForm(data, instance=item, result=item.result, positions=seal_positions(test_run, leakage))

    def get(self, request, pk):
        item = get_item(pk)
        return self.render(request, item, self.form(item))

    def post(self, request, pk):
        item = get_item(pk)
        test_run = item.result.test_run
        if response := refused(request, test_run, "acceptance"):
            return response
        if request.POST.get("delete"):
            criterion = item.criterion
            item.delete()
            services.touch(item.result, request.user)
            messages.success(request, f"Criterion “{criterion}” deleted.")
            return redirect(section_url(test_run, "acceptance"))
        form = self.form(item, request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.updated_by = request.user
            item.save()
            services.touch(item.result, request.user)
            messages.success(request, f"Criterion “{item.criterion}” saved.")
            return redirect(section_url(test_run, "acceptance"))
        return self.render(request, item, form)

    def render(self, request, item, form):
        context = {**run_context(item.result.test_run, "result"), "item": item, "form": form}
        return render(request, self.template_name, context)


class NarrativeView(ResultSectionView):
    section = "conclusion"

    def handle(self, request, test_run, result):
        form = NarrativeForm(request.POST, instance=result)
        if form.is_valid():
            result = form.save(commit=False)
            result.updated_by = request.user
            result.save()
            messages.success(request, "Observations and conclusion saved.")
            return redirect(section_url(test_run, self.section))
        return render_result(request, test_run, result, narrative_form=form)


# ---- Plots from the DCS viewer ----------------------------------------------------------


def plot_refusal(test_run):
    """JSON refusal for the DCS viewer, or None."""
    if recording_refusal(test_run):
        return JsonResponse(
            {"error": f"TCN{test_run.display_no} has not been issued yet: the Result can be recorded once it is issued."},
            status=403,
        )
    return None


def plot_saved(plot, message):
    return JsonResponse({
        "message": message,
        "plot": plot.definition(),
        "update_url": reverse("results:plot_update", args=[plot.pk]),
        "result_url": section_url(plot.result.test_run, f"plot-{plot.pk}"),
    })  # fmt: skip


class PlotAddView(View):
    """POST from the DCS viewer: definition (JSON) + image (PNG rendered from it)."""

    def post(self, request, dataset_pk):
        dataset = get_dataset(dataset_pk)
        test_run = dataset.test_run
        if response := plot_refusal(test_run):
            return response
        result = TestResult.objects.filter(test_run=test_run).first()
        if result is None:
            return JsonResponse({"error": f"Run {test_run.display_no} has no Result yet: start it first."}, status=400)
        image = request.FILES.get("image")
        try:
            plot = plots.add_plot(
                result, dataset, request.POST.get("definition"), image.read() if image else b"", request.user
            )
        except plots.PlotError as error:
            return JsonResponse({"error": str(error)}, status=400)
        services.touch(result, request.user)
        return plot_saved(plot, f"Plot {plot.order + 1} added to the Result of Run {test_run.display_no}.")


def get_plot(pk):
    return get_object_or_404(
        ResultPlot.objects.select_related("result__test_run__project", "dataset", "updated_by"), pk=pk
    )


class PlotUpdateView(View):
    """POST from the DCS viewer opened on a plot: replaces its definition and image."""

    def post(self, request, pk):
        plot = get_plot(pk)
        if response := plot_refusal(plot.result.test_run):
            return response
        image = request.FILES.get("image")
        try:
            plots.update_plot(plot, request.POST.get("definition"), image.read() if image else b"", request.user)
        except plots.PlotError as error:
            return JsonResponse({"error": str(error)}, status=400)
        services.touch(plot.result, request.user)
        return plot_saved(plot, "Plot updated in the Result.")


class PlotImageView(View):
    def get(self, request, pk):
        plot = get_plot(pk)
        return FileResponse(
            plot.image.open("rb"), content_type="image/png", filename=f"plot-{plot.pk}.png",
            as_attachment=request.GET.get("download") == "1",
        )  # fmt: skip


class PlotCaptionView(View):
    def post(self, request, pk):
        plot = get_plot(pk)
        test_run = plot.result.test_run
        if response := refused(request, test_run, "plots"):
            return response
        caption = request.POST.get("caption", "").strip()
        if len(caption) > ResultPlot._meta.get_field("caption").max_length:
            messages.error(request, "The caption is too long.")
        else:
            ResultPlot.objects.filter(pk=plot.pk).update(caption=caption)
            services.touch(plot.result, request.user)
            messages.success(request, "Caption saved.")
        return redirect(section_url(test_run, f"plot-{plot.pk}"))


class PlotMoveView(View):
    def post(self, request, pk):
        plot = get_plot(pk)
        test_run = plot.result.test_run
        if response := refused(request, test_run, "plots"):
            return response
        plots.move(plot, -1 if request.POST.get("direction") == "up" else 1)
        return redirect(section_url(test_run, "plots"))


class PlotDeleteView(View):
    template_name = "results/plot_delete.html"

    def get(self, request, pk):
        plot = get_plot(pk)
        return render(request, self.template_name, {**run_context(plot.result.test_run, "result"), "plot": plot})

    def post(self, request, pk):
        plot = get_plot(pk)
        test_run = plot.result.test_run
        if response := refused(request, test_run, "plots"):
            return response
        plots.delete_plot(plot)
        services.touch(plot.result, request.user)
        messages.success(request, "Plot removed from the Result.")
        return redirect(section_url(test_run, "plots"))


# ---- Test Run Report (M2C) ------------------------------------------------------------------


class ReportPreviewView(View):
    """Draft Test Run Report PDF, regenerated from the run's current data; marked DRAFT, never stored.

    Finalization (freeze the report context, render once, store the PDF with
    its SHA-256) is not part of M2C.
    """

    def get(self, request, run_pk):
        test_run = get_run(run_pk)
        context = build_run_report_context(test_run)
        try:
            content = run_report_template().render_pdf(context, report_assets(context))
        except PdfConversionError as error:
            messages.error(request, f"The report preview could not be generated. {error}")
            return redirect("results:result", test_run.pk)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{run_report_file_name(test_run, draft=True)}"'
        response["Cache-Control"] = "no-store"
        return response
