"""Frozen records of final Results (M2F-B): the record context and its assets, independent of live data.

    projects/<project_no>/runs/<run_no>/result/records/r<n>/record.json.gz     the record context (gzip JSON)
    projects/<project_no>/runs/<run_no>/result/records/r<n>/assets/<name>      every picture and plot it shows

The record is the complete report context of the revision (run_report_context, schema 2), written as
canonical JSON (sorted keys, no whitespace); record_sha256 is the SHA-256 of that JSON. Each asset is
copied byte for byte as the renderer uses it (the picture's display copy, the plot image) and stored
with its own SHA-256 next to the SHA-256 of its source the record names. Reading either back checks
the SHA-256: an altered record or asset is refused, never rendered.

Nothing here reads a live picture, plot or measurement after freezing: documents issued later from a
final revision depend only on these files.
"""

import gzip
import hashlib
import json
import posixpath

from django.core.files.base import ContentFile

from .models import RecordIntegrityError, ResultRevision


def storage():
    return ResultRevision._meta.get_field("record_file").storage


def result_dir(test_run):
    return f"projects/{test_run.project.project_no}/runs/{test_run.display_no}/result"


def revision_dir(test_run, number):
    return f"{result_dir(test_run)}/records/r{number}"


def canonical(record):
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def _save_new(name, content, written):
    """Store content under exactly `name` (never next to or over another file) and check it reads back."""
    store = storage()
    if store.exists(name):
        raise RecordIntegrityError(f"{name} already exists; nothing was written.")
    saved = store.save(name, ContentFile(content))
    written.append(saved)
    if saved != name:
        raise RecordIntegrityError(f"{name} already exists; nothing was written.")
    with store.open(saved, "rb") as stored:
        if stored.read() != content:
            raise RecordIntegrityError(f"{name} was not stored correctly; nothing was written.")
    return saved


def write_record(test_run, number, record, written):
    """(file name, SHA-256 of the canonical JSON) of the record written for revision `number`."""
    content = canonical(record)
    name = _save_new(f"{revision_dir(test_run, number)}/record.json.gz", gzip.compress(content, mtime=0), written)
    return name, sha256(content)


def freeze_assets(test_run, number, record, files, written):
    """Copy the assets the record names ({path: bytes} as rendered); the manifest stored with the revision."""
    manifest = []
    for asset in record.get("assets", []):
        content = files.get(asset["path"])
        if content is None:
            raise RecordIntegrityError(f"{asset['path']} of the record could not be read; nothing was written.")
        name = _save_new(f"{revision_dir(test_run, number)}/assets/{posixpath.basename(asset['path'])}", content,
                         written)  # fmt: skip
        manifest.append({"path": asset["path"], "kind": asset["kind"], "id": asset["id"],
                         "source_sha256": asset["sha256"], "file": name, "sha256": sha256(content)})  # fmt: skip
    return manifest


def read_record(revision):
    """The record context of a revision; refused when it does not match its SHA-256."""
    with revision.record_file.open("rb") as stored:
        content = gzip.decompress(stored.read())
    if sha256(content) != revision.record_sha256:
        raise RecordIntegrityError(f"The record of {revision} does not match its SHA-256; it is not used.")
    return json.loads(content)


def read_assets(revision, paths=None):
    """{asset path: bytes} of the frozen assets (all, or `paths`); refused when one does not match its SHA-256."""
    store = storage()
    files = {}
    for asset in revision.assets:
        if paths is not None and asset["path"] not in paths:
            continue
        with store.open(asset["file"], "rb") as stored:
            content = stored.read()
        if sha256(content) != asset["sha256"]:
            raise RecordIntegrityError(f"{asset['path']} of {revision} does not match its SHA-256; it is not used.")
        files[asset["path"]] = content
    return files
