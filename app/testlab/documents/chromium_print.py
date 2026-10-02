"""Print one document to PDF with headless Chromium (Playwright). Worker process of chromium.py.

Run as a separate process (`python chromium_print.py`) so the caller can
enforce its timeout by ending the process: Playwright's page.pdf() has no
timeout of its own. Standalone: imports only the standard library and
Playwright, never Django.

stdin: JSON {"base_url", "document" (path of the page in "files"),
"files" ({bundle path: base64}), "header", "footer" (HTML of Chromium's
header/footer templates), "timeout_ms"}.
stdout: the PDF bytes. On failure: exit status 2 and one line of
explanation on stderr (exit status 3: Chromium is not installed).

Every request of the page is answered from "files" or refused; any refused
or failed request, console error, unloaded font or broken image stops the
printing, so a PDF is only produced from exactly the given files.
"""

import base64
import json
import sys

EXIT_FAILED = 2
EXIT_NOT_INSTALLED = 3

# Fixed, not from the mimetypes module: on Windows that reads the registry, which varies per machine.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

# Background services of Chromium that may contact the network on their own; the page itself is routed.
LAUNCH_ARGS = [
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    "--no-pings",
    "--metrics-recording-only",
]

# Loads every declared font face (rejects if one cannot be loaded) and reports images that did not load.
CHECK_RESOURCES = """async () => {
    const faces = [...document.fonts];
    await Promise.all(faces.map((face) => face.load()));
    await document.fonts.ready;
    const unloaded = faces.filter((face) => face.status !== "loaded").map((face) => face.family);
    const broken = [...document.images].filter((img) => !img.complete || img.naturalWidth === 0)
        .map((img) => img.getAttribute("src"));
    return {faces: faces.length, unloaded, broken};
}"""


def content_type(path):
    suffix = path[path.rfind(".") :].lower() if "." in path else ""
    return CONTENT_TYPES.get(suffix, "application/octet-stream")


class Failed(Exception):
    pass


def print_pdf(job):
    from playwright.sync_api import Error, sync_playwright

    base_url = job["base_url"]
    files = {path: base64.b64decode(data) for path, data in job["files"].items()}
    timeout = job["timeout_ms"]
    problems = []

    def route(route):
        url = route.request.url
        path = url.removeprefix(base_url)
        if url.startswith(base_url) and path in files:
            route.fulfill(status=200, body=files[path], headers={"Content-Type": content_type(path)})
        else:
            problems.append(f"{url} is not a file of the document template")
            route.abort("blockedbyclient")

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(args=LAUNCH_ARGS, timeout=timeout)
        except Error as error:
            raise Failed(str(error).strip()) from error
        try:
            context = browser.new_context(service_workers="block", java_script_enabled=True)
            page = context.new_page()
            page.set_default_timeout(timeout)
            page.route("**/*", route)
            page.on("requestfailed", lambda request: problems.append(f"{request.url} could not be loaded"))
            page.on("console", lambda message: message.type == "error" and problems.append(message.text))
            page.on("pageerror", lambda error: problems.append(str(error)))

            page.goto(base_url + job["document"], wait_until="load")
            result = page.evaluate(CHECK_RESOURCES)
            if result["unloaded"]:
                problems.append(f"font(s) not loaded: {', '.join(result['unloaded'])}")
            if result["broken"]:
                problems.append(f"image(s) not loaded: {', '.join(result['broken'])}")
            if problems:
                raise Failed("; ".join(dict.fromkeys(problems)))

            pdf = page.pdf(
                prefer_css_page_size=True,  # @page size 210mm 297mm: Chromium's format="A4" is rounded
                print_background=True,
                display_header_footer=True,
                header_template=job["header"],
                footer_template=job["footer"],
            )
            if problems:  # requests made while printing
                raise Failed("; ".join(dict.fromkeys(problems)))
            return pdf
        except Error as error:
            raise Failed(str(error).strip().splitlines()[0]) from error
        finally:
            browser.close()


def main():
    try:
        job = json.load(sys.stdin)
        pdf = print_pdf(job)
    except ImportError as error:
        print(f"Playwright is not installed: {error}", file=sys.stderr)
        return EXIT_NOT_INSTALLED
    except Failed as error:
        message = str(error)
        if "Executable doesn't exist" in message:
            print("Chromium for Playwright is not installed.", file=sys.stderr)
            return EXIT_NOT_INSTALLED
        print(message, file=sys.stderr)
        return EXIT_FAILED
    sys.stdout.buffer.write(pdf)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
