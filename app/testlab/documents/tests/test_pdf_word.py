"""Microsoft Word PDF backend (TESTLAB_PDF_CONVERTER=word), with a stand-in for pywin32.

The real conversion is covered by the test marked `word` in test_pdf.py
(Windows with Word only).
"""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from testlab.documents import pdf, pdf_word

REAL_DOCX_TO_PDF = pdf.docx_to_pdf  # before conftest replaces it with the stand-in

PDF = b"%PDF-1.7\nword output\n%%EOF\n"


class ComError(Exception):
    """Stands in for pywintypes.com_error."""


class FakeDocument:
    def __init__(self, word):
        self.word = word

    def ExportAsFixedFormat(self, OutputFileName, ExportFormat, **options):
        self.word.log.append("export")
        assert ExportFormat == pdf_word.WD_EXPORT_FORMAT_PDF and not options["OpenAfterExport"]
        if self.word.export_error:
            raise self.word.export_error
        if self.word.export_waits:
            assert self.word.killed.wait(5), "the watchdog did not terminate Word"
            raise ComError("The RPC server is unavailable.")
        Path(OutputFileName).write_bytes(self.word.output)

    def Close(self, SaveChanges):
        self.word.log.append(("close", SaveChanges))
        if self.word.close_error:
            raise ComError("close failed")


class FakeWord:
    def __init__(self):
        self.log = []
        self.output = PDF
        self.open_error = self.export_error = self.close_error = self.quit_error = None
        self.export_waits = False
        self.killed = threading.Event()
        self.Visible = True
        self.DisplayAlerts = -1
        self.Caption = "Word"
        self.Documents = SimpleNamespace(Open=self.open)

    def open(self, FileName, **options):
        self.log.append("open")
        assert Path(FileName).read_bytes() == b"docx" and options["ReadOnly"]
        assert not self.Visible and self.DisplayAlerts == pdf_word.WD_ALERTS_NONE, "Word must run invisibly"
        if self.open_error:
            raise self.open_error
        return FakeDocument(self)

    def Quit(self, SaveChanges):
        self.log.append(("quit", SaveChanges))
        if self.quit_error:
            raise self.quit_error


@pytest.fixture
def word(monkeypatch):
    """A fake Word; `word.com` records COM initialisation and `word.kills` terminated process ids."""
    fake = FakeWord()
    fake.com = []
    fake.kills = []
    fake.dispatch_error = None

    def dispatch(prog_id):
        assert prog_id == "Word.Application"
        if fake.dispatch_error:
            raise fake.dispatch_error
        return fake

    def kill(pid):
        fake.kills.append(pid)
        fake.killed.set()

    win = SimpleNamespace(
        pythoncom=SimpleNamespace(CoInitialize=lambda: fake.com.append("init"),
                                  CoUninitialize=lambda: fake.com.append("uninit")),
        client=SimpleNamespace(DispatchEx=dispatch),
        gui=SimpleNamespace(FindWindow=lambda cls, caption: 77 if cls == "OpusApp" and caption.startswith("testlab-pdf-") else 0),
        process=SimpleNamespace(GetWindowThreadProcessId=lambda window: (1, 4242)),
    )  # fmt: skip
    monkeypatch.setattr(pdf_word, "_pywin32", lambda: win)
    monkeypatch.setattr(pdf_word, "_kill_process", kill)
    return fake


CLOSED = [("close", pdf_word.WD_DO_NOT_SAVE_CHANGES), ("quit", pdf_word.WD_DO_NOT_SAVE_CHANGES)]


def test_word_exports_the_pdf_and_closes_word(word):
    assert pdf_word.word_docx_to_pdf(b"docx", 60) == PDF
    assert word.log == ["open", "export", *CLOSED]
    assert word.com == ["init", "uninit"] and word.kills == []


def test_word_is_reached_through_docx_to_pdf(word, settings):
    settings.TESTLAB_PDF_CONVERTER = "word"
    assert REAL_DOCX_TO_PDF(b"docx") == PDF


def test_export_failure_still_closes_document_and_word(word):
    word.export_error = ComError("Command failed")
    with pytest.raises(pdf.PdfConversionError, match="could not convert the document: Command failed"):
        pdf_word.word_docx_to_pdf(b"docx", 60)
    assert word.log == ["open", "export", *CLOSED]
    assert word.com == ["init", "uninit"]


def test_open_failure_still_quits_word(word):
    word.open_error = ComError("file is corrupt")
    with pytest.raises(pdf.PdfConversionError, match="file is corrupt"):
        pdf_word.word_docx_to_pdf(b"docx", 60)
    assert word.log == ["open", ("quit", pdf_word.WD_DO_NOT_SAVE_CHANGES)]
    assert word.com == ["init", "uninit"]


def test_word_that_cannot_start_fails_clearly(word):
    word.dispatch_error = ComError("Invalid class string")
    with pytest.raises(pdf.PdfConversionError, match="could not be started: Invalid class string"):
        pdf_word.word_docx_to_pdf(b"docx", 60)
    assert word.log == [] and word.com == ["init", "uninit"]


def test_word_that_does_not_quit_is_terminated(word):
    word.close_error = ComError("close failed")
    word.quit_error = ComError("quit failed")
    assert pdf_word.word_docx_to_pdf(b"docx", 60) == PDF
    assert word.kills == [4242]


def test_output_that_is_not_a_pdf_is_refused(word):
    word.output = b"not a pdf"
    with pytest.raises(pdf.PdfConversionError, match="did not produce a PDF"):
        pdf_word.word_docx_to_pdf(b"docx", 60)


def test_timeout_terminates_word(word):
    word.export_waits = True
    with pytest.raises(pdf.PdfConversionError, match="did not finish within 0.1 seconds"):
        pdf_word.word_docx_to_pdf(b"docx", 0.1)
    assert word.kills[0] == 4242
    assert word.com == ["init", "uninit"]


def test_missing_pywin32_fails_clearly(monkeypatch):
    monkeypatch.setitem(sys.modules, "pythoncom", None)  # import raises ImportError
    with pytest.raises(pdf.PdfConversionError, match=r"needs pywin32.*\[word\]"):
        pdf_word.word_docx_to_pdf(b"docx", 60)
