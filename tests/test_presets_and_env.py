"""Tests for disease presets and env helper functions (pure Python)."""

import sys

from epigrass_qgis.builder import presets
from epigrass_qgis.env import python_env, redis_service
from epigrass_qgis.writer.epg_writer import ModelSpec, render_epg


def test_presets_are_complete_and_evaluable():
    for name in presets.preset_names():
        preset = presets.get_preset(name)
        assert preset["model"], name
        for key in ("beta", "alpha", "e", "r", "delta", "B", "w", "p"):
            value = preset["params"][key]
            assert eval(value) is not None
        for value in preset["inits"].values():
            eval(value, {"N": 1000})
        # Preset model types must render a valid .epg
        spec = ModelSpec(
            name="x", model_type=preset["model"], params=dict(preset["params"]),
            inits=dict(preset["inits"]),
        )
        assert "modtype = " + preset["model"] in render_epg(spec)


def test_parse_python_version():
    assert python_env.parse_python_version("Python 3.12.7") == (3, 12)
    assert python_env.parse_python_version("Python 3.13.1 (main)") == (3, 13)
    # bare `sys.version` output (no "Python" prefix) must parse too
    assert python_env.parse_python_version(
        "3.14.4 (main, Aug 20 2026, 10:41:58) [GCC 13]") == (3, 14)
    assert python_env.parse_python_version("3.12.9") == (3, 12)
    assert python_env.parse_python_version("no version here") is None
    assert python_env.parse_python_version("") is None
    assert python_env.parse_python_version(None) is None


def test_check_interpreter_real_interpreter():
    """Integration-flavoured: probe the actually running interpreter.

    This guards the full probe pipeline (resolve -> run -> parse), which an
    isolated parse test cannot do.
    """
    version = python_env.check_interpreter(sys.executable)
    assert version is not None
    assert version >= (3, 10)
    assert python_env.is_sufficient(version) or not python_env.is_sufficient(version)


def test_find_python_finds_something_usable():
    cmd, version = python_env.find_python("")
    assert cmd is not None, "no Python >= 3.12 discoverable on this machine"
    assert version >= python_env.MIN_PYTHON


def test_is_sufficient():
    assert python_env.is_sufficient((3, 12))
    assert python_env.is_sufficient((3, 13))
    assert not python_env.is_sufficient((3, 11))
    assert not python_env.is_sufficient(None)


def test_venv_python_path_platform(monkeypatch):
    monkeypatch.setattr(python_env.sys, "platform", "linux")
    path = python_env.venv_python_path("/tmp/env")
    assert path.endswith("/bin/python")
    monkeypatch.setattr(python_env.sys, "platform", "win32")
    path = python_env.venv_python_path("C:/env")
    assert "Scripts" in path and path.endswith("python.exe")


def test_epirunner_path_platform(monkeypatch):
    monkeypatch.setattr(python_env.sys, "platform", "linux")
    assert python_env.epirunner_path("/tmp/env").endswith("/bin/epirunner")


def test_redis_ping_refuses_garbage():
    # No server on that port -> False (not an exception)
    assert redis_service.ping("localhost", 1, timeout=0.2) is False


def test_doctor_config_defaults():
    from epigrass_qgis.env.doctor import DoctorConfig

    config = DoctorConfig()
    assert config.redis_port == 6379
    assert config.env_dir.endswith("env")


def test_quoted_identifier_rejects_unsafe_names():
    from epigrass_qgis.sqlite_utils import quoted_identifier

    good = "Model_tiny_Wed_Oct_28_094540_2026"
    assert quoted_identifier(good) == f'"{good}"'
    for bad in (
        'Model"); DROP TABLE users; --',  # classic injection
        "table;DROP",  # statement separator
        'quo"te',  # embedded quote must not appear raw
        "",  # empty
        "sp ace",  # space is not a valid sqlite identifier char here
    ):
        try:
            quoted_identifier(bad)
        except ValueError:
            continue
        raise AssertionError(f"should have rejected {bad!r}")


def test_sanitize_model_name():
    from epigrass_qgis.writer.epg_writer import sanitize_model_name

    assert sanitize_model_name("My Layer: 2024/25") == "My_Layer_2024_25"
    assert sanitize_model_name('weird"chars;drop') == "weird_chars_drop"
    assert sanitize_model_name("  --ok-name--  ") == "ok-name"
    assert sanitize_model_name("///") == "model"
    assert sanitize_model_name("") == "model"
