"""Assemble the Final Report of a project (rough version).

    cover block and numbers      the project
    summary table                one row per included run, from its frozen record
    texts                        written by the engineer (models.FinalReport)
    one section per run          the Customer presentation of the run's latest final revision

A run's section is rendered by the Test Run Report template from the frozen
record and assets of the revision (results/records.py), with the run's
Customer report contents: the same data and the same selection as its
Customer Test Run Report, so the two cannot differ. Nothing is read from
live Result data. The report is a draft: rendered on request, never stored.
"""

import re

from django.utils import timezone

from testlab.documents import pdf
from testlab.documents.render import ChromiumTemplate, run_report_template, template_path
from testlab.documents.report_profiles import present
from testlab.documents.run_report_context import _datetime, _paragraphs
from testlab.documents.tcn_context import format_date
from testlab.results import publication, records
from testlab.results.models import ReportDocument, TestResult

from .models import FinalReport

PROFILE = "customer"
DASH = "—"
RESULTS_SECTION = 5  # 1 Introduction … 4 Test conditions, 5 Test results, 6 Conclusion
_MAIN = re.compile(r"<main>(.*)</main>", re.DOTALL)


class AssemblyError(Exception):
    """The report cannot be assembled; the message says why."""


def candidates(project):
    """The project's Results that have a final revision, in run order, each with `.revision` (the latest)."""
    found = []
    for result in TestResult.objects.filter(test_run__project=project).select_related("test_run__project").order_by(
            "test_run__run_no"):  # fmt: skip
        revision = publication.latest_revision(result)
        if revision is not None:
            result.revision = revision
            found.append(result)
    return found


def included(report):
    """The included Results in report order, each with `.revision`."""
    if report is None:
        return []
    by_id = {result.pk: result for result in candidates(report.project)}
    return [by_id[item.result_id] for item in report.runs.all() if item.result_id in by_id]


def final_report_template():
    """The Final Report bundle: the Test Run Report bundle (styles, fonts, logo — the run sections are
    rendered with it) with the files of doc_templates/final_report/ on top."""
    files = dict(run_report_template().files)
    root = template_path("final_report")
    own = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    for part in ("final_report.html", "header.html", "footer.html"):
        if part not in own:
            raise pdf.PdfConversionError(f"The document template {root / part} was not found.")
    files.update(own)
    return ChromiumTemplate("final_report", files, document="final_report.html")


def _document(revision):
    """How the run section names its source: the issued Customer document of the revision, when there is one."""
    issued = ReportDocument.objects.filter(revision=revision, profile=PROFILE,
                                           status=ReportDocument.Status.ISSUED).first()  # fmt: skip
    if issued is None:
        return {"revision": revision.number}
    return {"identity": issued.identity, "revision": revision.number, "status": "Issued",
            "issued_on": format_date(timezone.localtime(issued.issued_at))}  # fmt: skip


def _value(row):
    return row["actual"] if row["actual"] not in ("", DASH) else row["instructed"]


def _condition(ctx, parameter):
    """Every row of the conditions table named `parameter`: [(group heading, value, unit)]."""
    return [(group["heading"], _value(row), row["unit"]) for group in ctx["conditions"]["groups"]
            for row in group["rows"] if row["parameter"] == parameter]  # fmt: skip


def summary_row(ctx, number):
    """One row of the summary table, from a run's presented record. Facts only: the acceptance column counts
    the assessments on record, it draws no overall verdict."""
    ident = ctx["identification"]
    speed = [value for heading, value, _ in _condition(ctx, "Speed")]
    counts = {}
    for item in ctx.get("acceptance", []):
        counts[item["label"]] = counts.get(item["label"], 0) + 1
    return {
        "section": number,
        "run_no": ident["run_no"],
        "tcn_no": ident["tcn_no"],
        "dates": ident.get("dates") or DASH,
        "speed": speed[0] if speed else DASH,
        "media": [f"{heading}: {value}" for heading, value, _ in _condition(ctx, "Medium")],
        "pressures": [f"{heading}: {value} {unit}".strip() for heading, value, unit in _condition(ctx, "Pressure")],
        "running_hours": ident.get("running_hours") or DASH,
        "leakage": [f"{seal['seal']}: {seal['average']}" for seal in ctx.get("leakage", [])],
        "wear": [f"{w['component']}: {w['wear']} {w['unit']}".strip() for w in ctx.get("wear", [])
                 if w.get("wear") not in (None, "", DASH)],  # fmt: skip
        "acceptance": [f"{count} {label}" for label, count in counts.items()],
    }


def _run_section(template, result, index, assets):
    revision = result.revision
    record = records.read_record(revision)
    ctx = present(record, PROFILE, publication.stored_selection(result, PROFILE), document=_document(revision))
    number = f"{RESULTS_SECTION}.{index}"
    # Section numbers of the run become 5.<n>.<m>: headings and the references to them stay consistent.
    ctx["sections"] = {name: f"{number}.{value}" for name, value in ctx["sections"].items() if value}
    for path, content in records.read_assets(revision, {a["path"] for a in ctx["assets"]}).items():
        if assets.get(path, content) != content:
            raise AssemblyError(f"Two runs name different files {path}; the report was not generated.")
        assets[path] = content
    body = _MAIN.search(template.render_parts(ctx)[0])
    if body is None:
        raise AssemblyError("The Test Run Report template has no <main> part; the report was not generated.")
    html = body.group(1).replace("<h1>Run ", f"<h1>{number} Run ", 1)
    return {"html": html, "summary": summary_row(ctx, number), "revision": revision.number,
            "document": ctx["document"].get("identity", "")}  # fmt: skip


def build(project):
    """(context, assets, template) of the project's Final Report draft."""
    report = FinalReport.objects.filter(project=project).first()
    results = included(report)
    if not results:
        raise AssemblyError("No run is included yet: tick the final Results the report covers and save.")
    template = final_report_template()
    run_template = run_report_template()
    assets = {}
    runs = [_run_section(run_template, result, index, assets) for index, result in enumerate(results, start=1)]
    context = {
        "is_draft": True,
        "generated": _datetime(timezone.now()),
        "report_no": report.report_no,
        "project": {"project_no": project.project_no, "description": project.description,
                    "customer": project.customer},  # fmt: skip
        "texts": {name: _paragraphs(getattr(report, name)) for name in FinalReport.TEXT_FIELDS},
        "summary": [run["summary"] for run in runs],
        "runs": runs,
        "results_section": RESULTS_SECTION,
    }
    return context, assets, template


def render_pdf(project):
    context, assets, template = build(project)
    return template.render_pdf(context, assets)
