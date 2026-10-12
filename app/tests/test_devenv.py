"""scripts/devenv.py: the shared setup/startup logic behind setup.sh/.bat and run_app.sh/.bat."""

import importlib.util
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_DIR / "scripts"

spec = importlib.util.spec_from_file_location("devenv", SCRIPTS / "devenv.py")
devenv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(devenv)


def test_repository_located_from_the_script_not_the_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert devenv.ROOT == REPO_DIR
    assert (devenv.APP_DIR / "manage.py").is_file()
    assert devenv.VENV_DIR == REPO_DIR / ".venv"


def test_minimum_python_matches_pyproject():
    import tomllib

    requires = tomllib.loads((REPO_DIR / "pyproject.toml").read_text())["project"]["requires-python"]
    assert requires == ">={}.{}".format(*devenv.MIN_PYTHON)


@pytest.mark.parametrize(("version", "ok"), [((3, 11), False), ((3, 12), True), ((3, 13), True), ((3, 14), True)])
def test_python_version_check(version, ok):
    problem = devenv.python_problem(version)
    assert (problem is None) == ok
    if not ok:
        assert "3.12" in problem


def test_venv_python_path(monkeypatch):
    monkeypatch.setattr(devenv, "IS_WINDOWS", False)
    assert devenv.venv_python(Path("v")) == Path("v/bin/python")
    monkeypatch.setattr(devenv, "IS_WINDOWS", True)
    assert devenv.venv_python(Path("v")) == Path("v/Scripts/python.exe")


def test_existing_venv_version_absent(tmp_path):
    assert devenv.existing_venv_version(tmp_path / "missing") is None


def test_create_virtualenv_refuses_incomplete_venv(monkeypatch, tmp_path):
    monkeypatch.setattr(devenv, "VENV_DIR", tmp_path)
    with pytest.raises(devenv.SetupError, match="incomplete"):
        devenv.create_virtualenv()


def server(argv, environ):
    return devenv.server_settings(devenv.parse_args(["run", *argv]), environ)


def test_default_is_localhost_only():
    host, port, env, urls = server([], {})
    assert (host, port) == ("127.0.0.1", 8000)
    assert urls == ["http://127.0.0.1:8000/"]
    assert "TESTLAB_ALLOWED_HOSTS" not in env
    assert "TESTLAB_TCN_RENDERER" not in env  # one renderer: nothing to choose


def test_environment_configuration_is_preserved():
    environ = {"TESTLAB_DEBUG": "1", "TESTLAB_PORT": "8100"}
    host, port, env, _ = server([], environ)
    assert port == 8100
    assert env["TESTLAB_DEBUG"] == "1"


def test_port_option_wins_over_environment():
    assert server(["--port", "8001"], {"TESTLAB_PORT": "8100"})[1] == 8001


def test_invalid_port():
    with pytest.raises(devenv.SetupError):
        server(["--port", "70000"], {})


def test_lan_binds_all_interfaces_and_allows_this_machine(monkeypatch):
    monkeypatch.setattr(devenv, "lan_addresses", lambda: ["labpc", "10.1.2.3"])
    host, port, env, urls = server(["--lan"], {})
    assert host == "0.0.0.0"
    assert env["TESTLAB_ALLOWED_HOSTS"] == "localhost,127.0.0.1,labpc,10.1.2.3"
    assert urls == ["http://127.0.0.1:8000/", "http://labpc:8000/", "http://10.1.2.3:8000/"]


def test_lan_keeps_explicit_allowed_hosts(monkeypatch):
    monkeypatch.setattr(devenv, "lan_addresses", lambda: ["labpc"])
    _, _, env, _ = server(["--lan"], {"TESTLAB_ALLOWED_HOSTS": "testlab.example.com"})
    assert env["TESTLAB_ALLOWED_HOSTS"] == "testlab.example.com"


def test_lan_and_host_are_exclusive():
    with pytest.raises(SystemExit):
        devenv.parse_args(["run", "--lan", "--host", "127.0.0.1"])


def test_run_refuses_a_python_outside_the_venv(monkeypatch, tmp_path):
    monkeypatch.setattr(devenv, "VENV_DIR", tmp_path / ".venv")
    with pytest.raises(devenv.SetupError, match="setup"):
        devenv.check_environment()


def test_run_reports_missing_packages(monkeypatch):
    monkeypatch.setattr(devenv.sys, "prefix", str(devenv.VENV_DIR))
    monkeypatch.setattr(devenv, "REQUIRED_MODULES", ("django", "testlab_no_such_module"))
    with pytest.raises(devenv.SetupError, match="testlab_no_such_module"):
        devenv.check_environment()


def test_main_reports_setup_errors_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(devenv, "VENV_DIR", Path("/nonexistent/.venv"))
    assert devenv.main(["run"]) == 1
    assert "TestLab:" in capsys.readouterr().err


def test_wrappers_are_thin_and_call_the_shared_script():
    for name, command in [("setup.sh", "setup"), ("run_app.sh", "run"), ("setup.bat", "setup"), ("run_app.bat", "run")]:
        text = (SCRIPTS / name).read_text()
        assert f"devenv.py\" {command}" in text, name
        assert "0.0.0.0" not in text, name  # the LAN is opt-in (--lan), never the default


def test_batch_files_have_crlf_line_endings():
    for name in ("setup.bat", "run_app.bat"):
        data = (SCRIPTS / name).read_bytes()
        assert data.count(b"\n") == data.count(b"\r\n"), name
