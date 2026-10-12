#!/usr/bin/env python3
"""TestLab development environment: first-time setup and startup.

    python scripts/devenv.py setup          # create/update .venv, Chromium, database
    python scripts/devenv.py run [--lan]    # start the Django development server

Normally called through the thin platform wrappers:

    Linux:    ./scripts/setup.sh       ./scripts/run_app.sh
    Windows:  scripts\\setup.bat        scripts\\run_app.bat

All logic lives here so that Windows and Linux follow one procedure. Only
the Python standard library is used: `setup` runs before the virtualenv
exists. Django configuration stays environment-driven (TESTLAB_* variables,
see README); this script only adds defaults for variables that are unset.

Developer/test machines only: this is not a production deployment.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
VENV_DIR = ROOT / ".venv"
IS_WINDOWS = os.name == "nt"

MIN_PYTHON = (3, 12)  # pyproject.toml requires-python
TESTED_PYTHON = {(3, 12), (3, 13)}

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# Imported by `run` to tell an incomplete virtualenv from a working one.
REQUIRED_MODULES = ("django", "dj_database_url", "playwright", "PIL", "openpyxl")  # PIL: Pillow

SETUP_COMMAND = r"scripts\setup.bat" if IS_WINDOWS else "./scripts/setup.sh"
RUN_COMMAND = r"scripts\run_app.bat" if IS_WINDOWS else "./scripts/run_app.sh"


class SetupError(Exception):
    """A step failed; the message says what to do about it."""


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def info(message: str) -> None:
    print(f"    {message}", flush=True)


def venv_python(venv_dir: Path | None = None) -> Path:
    venv_dir = VENV_DIR if venv_dir is None else venv_dir
    if IS_WINDOWS:
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def python_problem(version: tuple[int, int]) -> str | None:
    """Why this Python cannot run TestLab, or None when it can."""
    if version < MIN_PYTHON:
        return (
            f"TestLab needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer; this is Python "
            f"{version[0]}.{version[1]}.\n"
            + (
                "Install Python 3.12 from https://www.python.org/downloads/ and run scripts\\setup.bat again."
                if IS_WINDOWS
                else "Install Python 3.12 (e.g. apt install python3.12 python3.12-venv) and run ./scripts/setup.sh again."
            )
        )
    return None


def run(command: list[str], *, env: dict[str, str] | None = None, what: str) -> None:
    """Run a command from the repository root; SetupError when it fails."""
    try:
        result = subprocess.run([str(part) for part in command], cwd=ROOT, env=env)
    except OSError as error:
        raise SetupError(f"{what} could not be started: {error}") from error
    if result.returncode != 0:
        raise SetupError(f"{what} failed (exit code {result.returncode}); see the messages above.")


def django_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for manage.py: the caller's, with its TESTLAB_* settings."""
    return dict(os.environ if base is None else base)


def manage(python: Path, *args: str, env: dict[str, str], what: str) -> None:
    run([python, APP_DIR / "manage.py", *args], env=env, what=what)


# --- setup ----------------------------------------------------------------


def check_python() -> None:
    step("Checking Python")
    version = sys.version_info[:2]
    info(f"Python {version[0]}.{version[1]} at {sys.executable}")
    problem = python_problem(version)
    if problem:
        raise SetupError(problem)
    if version not in TESTED_PYTHON:
        info("Note: TestLab is tested with Python 3.12 and 3.13. If installing the dependencies fails,")
        info("install Python 3.12, delete .venv and run setup again with it.")


def existing_venv_version(venv_dir: Path | None = None) -> tuple[int, int] | None:
    python = venv_python(venv_dir)
    if not python.exists():
        return None
    result = subprocess.run(
        [str(python), "-c", "import sys; print(*sys.version_info[:2])"], capture_output=True, text=True
    )
    try:
        major, minor = result.stdout.split()
        return int(major), int(minor)
    except ValueError:
        return None


def create_virtualenv() -> Path:
    step("Virtual environment (.venv)")
    python = venv_python()
    if VENV_DIR.exists() and not python.exists():
        raise SetupError(
            f"{VENV_DIR} exists but contains no Python ({python}).\n"
            "It is incomplete or was made on another operating system. Delete the .venv folder and run setup again."
        )
    existing = existing_venv_version()
    if python.exists() and existing is None:
        raise SetupError(
            f"The Python in {VENV_DIR} does not start (moved, or its base Python was uninstalled).\n"
            "Delete the .venv folder and run setup again."
        )
    if existing is not None:
        if existing != sys.version_info[:2]:
            raise SetupError(
                f"{VENV_DIR} was made with Python {existing[0]}.{existing[1]}, but setup now runs with Python "
                f"{sys.version_info[0]}.{sys.version_info[1]}.\n"
                "Running setup with another Python does not rebuild it. Either run setup with "
                f"Python {existing[0]}.{existing[1]}, or delete the .venv folder and run setup again."
            )
        info(f"Present (Python {existing[0]}.{existing[1]}); kept.")
        return python
    venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    info(f"Created with Python {sys.version_info[0]}.{sys.version_info[1]}.")
    return python


def install_dependencies(python: Path) -> None:
    step("Installing TestLab's dependencies (pyproject.toml, with the development tools)")
    run(
        [python, "-m", "pip", "install", "--disable-pip-version-check", "-e", ".[dev]"],
        what="pip install",
    )


CHROMIUM_PROBE = (
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p: p.chromium.launch().close()\n"
)


def chromium_starts(python: Path) -> tuple[bool, str]:
    result = subprocess.run([str(python), "-c", CHROMIUM_PROBE], cwd=ROOT, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


def install_chromium(python: Path) -> str | None:
    """Install Playwright's Chromium (the PDF renderer). Returns a warning instead of failing:
    everything except the PDFs works without it, and the download is the step most likely to be
    blocked on a corporate network."""
    step("Chromium for the TCN and report PDFs (Playwright; about 150 MB, downloaded once)")
    ok, _ = chromium_starts(python)
    if ok:
        info("Already installed and starts.")
        return None
    result = subprocess.run([str(python), "-m", "playwright", "install", "chromium"], cwd=ROOT)
    if result.returncode != 0:
        return (
            "Chromium could not be downloaded: TCN and Test Run Report PDFs will fail; everything else works.\n"
            "  Behind HTTPS inspection the download usually needs the company root certificate (ask IT;\n"
            "  it can be passed with NODE_EXTRA_CA_CERTS=<file.pem>). Then run setup again, or:\n"
            f'    "{python}" -m playwright install chromium'
        )
    ok, error = chromium_starts(python)
    if ok:
        info("Installed and starts.")
        return None
    if "missing dependencies" in error or "shared libraries" in error:
        # Installing system packages needs administrator rights: report, never do it silently.
        return (
            "Chromium is downloaded but cannot start: system libraries are missing. Installing them needs\n"
            "  administrator rights, so setup does not do it. Debian/Ubuntu:\n"
            f'    sudo "{python}" -m playwright install-deps chromium\n'
            "  Other distributions: install the libraries named in this message:\n    "
            + "\n    ".join(error.strip().splitlines()[:8])
        )
    lines = error.strip().splitlines()
    return f"Chromium is downloaded but does not start: {lines[-1] if lines else 'no reason given'}"


DIRECTORIES_SCRIPT = """
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "app"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from pathlib import Path
from django.conf import settings
db = settings.DATABASES["default"]
dirs = [Path(settings.TESTLAB_FILE_ROOT)]
if db["ENGINE"].endswith("sqlite3") and str(db["NAME"]) != ":memory:":
    dirs.insert(0, Path(db["NAME"]).parent)
for d in dirs:
    d.mkdir(parents=True, exist_ok=True)
    print(f"    {d}")
"""


def create_directories(python: Path, env: dict[str, str]) -> None:
    step("Local data directories (database, issued documents)")
    run([python, "-c", DIRECTORIES_SCRIPT], env=env, what="Creating the data directories")


def migrate(python: Path, env: dict[str, str]) -> None:
    step("Database migrations")
    manage(python, "migrate", "--noinput", env=env, what="manage.py migrate")


def system_check(python: Path, env: dict[str, str]) -> None:
    step("Django system checks")
    manage(python, "check", env=env, what="manage.py check")


def finish(warnings: list[str]) -> None:
    python = venv_python()
    print("\n" + "=" * 72)
    if warnings:
        print("  Setup finished with warnings:\n")
        for warning in warnings:
            print(f"  ! {warning}\n")
    else:
        print("  Setup complete.\n")
    print("  First administrator (once; later users register and are approved in admin):")
    print(f'    "{python}" app{os.sep}manage.py createsuperuser\n')
    print("  Start TestLab:")
    print(f"    {RUN_COMMAND}            http://127.0.0.1:8000/")
    print(f"    {RUN_COMMAND} --lan      also reachable from other machines on the network")
    print("=" * 72)


def setup() -> int:
    print("TestLab - development setup")
    print(f"Repository: {ROOT}")
    check_python()
    python = create_virtualenv()
    install_dependencies(python)
    warnings = [w for w in [install_chromium(python)] if w]
    env = django_env()
    create_directories(python, env)
    migrate(python, env)
    system_check(python, env)
    finish(warnings)
    return 0


# --- run ------------------------------------------------------------------


def missing_modules() -> list[str]:
    import importlib.util

    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def check_environment() -> None:
    """`run` must be started with the .venv Python and a complete installation."""
    expected = VENV_DIR.resolve()
    if Path(sys.prefix).resolve() != expected:
        raise SetupError(
            f"TestLab must run with the Python of {VENV_DIR} (this is {sys.executable}).\n"
            f"Start it with {RUN_COMMAND}; if .venv does not exist yet, run {SETUP_COMMAND} first."
        )
    missing = missing_modules()
    if missing:
        raise SetupError(
            f"The virtualenv is missing required packages ({', '.join(missing)}). Run {SETUP_COMMAND} again."
        )


def lan_addresses() -> list[str]:
    """Host names and IPv4 addresses other machines may use to reach this one."""
    names: list[str] = []
    hostname = socket.gethostname()
    for name in (hostname, socket.getfqdn()):
        if name and name not in names:
            names.append(name)
    try:
        # No packet is sent: connecting a UDP socket only selects the outgoing interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))
            address = probe.getsockname()[0]
        if address not in names and not address.startswith("127."):
            names.append(address)
    except OSError:
        pass
    return names


def server_settings(args: argparse.Namespace, environ: dict[str, str]) -> tuple[str, int, dict[str, str], list[str]]:
    """Bind address, port, environment for Django and the URLs to show.

    Default: localhost only. --lan (or TESTLAB_HOST=0.0.0.0) binds all interfaces; the machine's names
    are then added to TESTLAB_ALLOWED_HOSTS unless that variable is set explicitly.
    """
    env = django_env(environ)
    host = "0.0.0.0" if args.lan else (args.host or environ.get("TESTLAB_HOST") or DEFAULT_HOST)
    port = args.port or int(environ.get("TESTLAB_PORT") or DEFAULT_PORT)
    if not 0 < port < 65536:
        raise SetupError(f"Invalid port {port}.")
    urls = [f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}/"]
    if host == "0.0.0.0":
        others = lan_addresses()
        urls += [f"http://{name}:{port}/" for name in others]
        if "TESTLAB_ALLOWED_HOSTS" not in environ:
            env["TESTLAB_ALLOWED_HOSTS"] = ",".join(["localhost", "127.0.0.1", *others])
    return host, port, env, urls


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1" if host == "0.0.0.0" else host, port)) == 0


def run_app(args: argparse.Namespace) -> int:
    check_environment()
    host, port, env, urls = server_settings(args, dict(os.environ))
    if port_in_use(host, port):
        raise SetupError(
            f"Port {port} is already in use (TestLab already running?). Open {urls[0]}, or choose another "
            "port with --port or TESTLAB_PORT."
        )
    python = Path(sys.executable)
    create_directories(python, env)
    step("Applying pending database migrations (the database is never reset)")
    manage(python, "migrate", "--noinput", env=env, what="manage.py migrate")

    print()
    print(f"  TestLab (development server) at:  {urls[0]}")
    for url in urls[1:]:
        print(f"                                    {url}")
    if host == "0.0.0.0":
        print("  Listening on all network interfaces (--lan): anyone on the network can reach the login page.")
    print("  Stop with Ctrl+C.")
    print(flush=True)
    command = [str(python), str(APP_DIR / "manage.py"), "runserver", f"{host}:{port}"]
    try:
        return subprocess.call(command, cwd=ROOT, env=env)
    except KeyboardInterrupt:
        return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="devenv.py", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="create or update the development environment (safe to rerun)")
    run_parser = commands.add_parser("run", help="start the development server")
    where = run_parser.add_mutually_exclusive_group()
    where.add_argument("--lan", action="store_true", help="listen on all interfaces (reachable from the network)")
    where.add_argument("--host", help=f"address to bind (default TESTLAB_HOST or {DEFAULT_HOST})")
    run_parser.add_argument("--port", type=int, help=f"port (default TESTLAB_PORT or {DEFAULT_PORT})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return setup() if args.command == "setup" else run_app(args)
    except SetupError as error:
        print(f"\nTestLab: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
