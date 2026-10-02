"""DOCX → PDF with Microsoft Word (optional backend, TESTLAB_PDF_CONVERTER=word).

For Windows development and corporate workstations where LibreOffice cannot
be installed. LibreOffice headless (pdf.py) stays the backend of the Linux
server.

Word is driven through COM automation with pywin32 (the optional `word`
extra, Windows only). Each conversion starts its own invisible Word
instance (DispatchEx: a Word the user has open is never used or closed),
opens the temporary DOCX read-only, exports it as PDF, and always closes
the document without saving and quits Word, also when a step fails. A
watchdog terminates the instance when the conversion does not finish within
TESTLAB_PDF_TIMEOUT.
"""

import os
import signal
import tempfile
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

from . import pdf

# Constants of the Word object model.
WD_DO_NOT_SAVE_CHANGES = 0
WD_ALERTS_NONE = 0
WD_EXPORT_FORMAT_PDF = 17
WD_EXPORT_OPTIMIZE_FOR_PRINT = 0


def _pywin32():
    """The pywin32 modules; PdfConversionError when they are not installed."""
    try:
        import pythoncom
        import win32com.client
        import win32gui
        import win32process
    except ImportError as error:
        raise pdf.PdfConversionError(
            'Microsoft Word conversion needs pywin32 on Windows: pip install -e ".[word]".'
        ) from error
    return SimpleNamespace(pythoncom=pythoncom, client=win32com.client, gui=win32gui, process=win32process)


def word_available():
    """True on Windows with pywin32 installed and Word registered for automation (Word is not started)."""
    if os.name != "nt":
        return False
    try:
        _pywin32()
        import winreg

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"))
    except (pdf.PdfConversionError, OSError):
        return False
    return True


def word_docx_to_pdf(docx, timeout):
    """Convert DOCX bytes to PDF bytes with Word; raises PdfConversionError on any failure."""
    win = _pywin32()
    # Word may hold the files briefly after quitting; a leftover temporary file must not hide the result.
    with tempfile.TemporaryDirectory(prefix="testlab-pdf-", ignore_cleanup_errors=True) as work:
        source = Path(work) / "document.docx"
        target = Path(work) / "document.pdf"
        source.write_bytes(docx)
        _convert(win, source, target, timeout)
        if not target.is_file():
            raise pdf.PdfConversionError("Microsoft Word did not produce a PDF file.")
        data = target.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise pdf.PdfConversionError("Microsoft Word did not produce a PDF file.")
    return data


def _convert(win, source, target, timeout):
    # COM is initialised per thread: Django serves requests from several threads.
    win.pythoncom.CoInitialize()
    word = document = watchdog = pid = None
    try:
        try:
            word = win.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = WD_ALERTS_NONE
        except Exception as error:
            raise pdf.PdfConversionError(f"Microsoft Word could not be started: {error}") from error
        pid = _process_id(win, word)
        timed_out = threading.Event()
        if pid:

            def expire():
                timed_out.set()
                _kill_process(pid)

            watchdog = threading.Timer(timeout, expire)
            watchdog.daemon = True
            watchdog.start()
        try:
            document = word.Documents.Open(
                FileName=str(source),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
                Visible=False,
                NoEncodingDialog=True,
            )
            document.ExportAsFixedFormat(
                OutputFileName=str(target),
                ExportFormat=WD_EXPORT_FORMAT_PDF,
                OpenAfterExport=False,
                OptimizeFor=WD_EXPORT_OPTIMIZE_FOR_PRINT,
            )
        except Exception as error:
            if timed_out.is_set():
                raise pdf.PdfConversionError(f"Microsoft Word did not finish within {timeout} seconds.") from error
            raise pdf.PdfConversionError(f"Microsoft Word could not convert the document: {error}") from error
    finally:
        if watchdog:
            watchdog.cancel()
        _close(document, word, pid)
        document = word = None  # release the COM references before CoUninitialize
        win.pythoncom.CoUninitialize()


def _process_id(win, word):
    """Process id of this Word instance, found by a unique window caption; None when not found."""
    try:
        word.Caption = f"testlab-pdf-{uuid.uuid4().hex}"
        window = win.gui.FindWindow("OpusApp", word.Caption)
        return win.process.GetWindowThreadProcessId(window)[1] if window else None
    except Exception:
        return None


def _close(document, word, pid):
    """Close the document and quit Word without saving; terminate the process when Word does not quit."""
    if document is not None:
        try:
            document.Close(SaveChanges=WD_DO_NOT_SAVE_CHANGES)
        except Exception:
            pass  # quitting Word below also discards the document
    if word is not None:
        try:
            word.Quit(SaveChanges=WD_DO_NOT_SAVE_CHANGES)
        except Exception:
            if pid:
                _kill_process(pid)


def _kill_process(pid):
    try:
        os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows
    except OSError:
        pass
