"""The Environment Doctor: checks and provisions everything needed to simulate.

Checks performed:
1. A Python >= 3.12 interpreter is available (never QGIS's own).
2. The managed virtualenv exists and has Epigrass installed.
3. A Redis server answers on the configured host/port (started if possible).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from ..defs import (
    DEFAULT_ENV_DIR,
    DEFAULT_REDIS_HOST,
    DEFAULT_REDIS_PORT,
    MIN_PYTHON,
    SETTING_ENV_DIR,
    SETTING_PYTHON_PATH,
    SETTING_REDIS_BINARY,
    SETTING_REDIS_HOST,
    SETTING_REDIS_PORT,
    SETTING_STOP_REDIS_ON_EXIT,
)
from . import python_env, redis_service

log = logging.getLogger(__name__)


@dataclass
class CheckResult:
    key: str
    ok: bool
    status: str  # short status, e.g. "Python 3.12.7"
    detail: str = ""
    fixable: bool = False  # can the doctor fix it automatically?

    def __str__(self) -> str:
        mark = "OK" if self.ok else "!!"
        out = f"[{mark}] {self.key}: {self.status}"
        if self.detail:
            out += f"\n      {self.detail}"
        return out


@dataclass
class DoctorConfig:
    python_path: str = ""
    env_dir: str = os.path.join("~", *DEFAULT_ENV_DIR.split("/"))
    redis_host: str = DEFAULT_REDIS_HOST
    redis_port: int = DEFAULT_REDIS_PORT
    redis_binary: str = ""
    stop_redis_on_exit: bool = True

    @classmethod
    def from_settings(cls, settings) -> DoctorConfig:
        """Build from a QSettings-like object (has .value(key, default, type))."""
        return cls(
            python_path=str(settings.value(SETTING_PYTHON_PATH, "", str) or ""),
            env_dir=str(settings.value(SETTING_ENV_DIR, cls.env_dir_default(), str)),
            redis_host=str(settings.value(SETTING_REDIS_HOST, DEFAULT_REDIS_HOST, str)),
            redis_port=int(settings.value(SETTING_REDIS_PORT, DEFAULT_REDIS_PORT, int) or 6379),
            redis_binary=str(settings.value(SETTING_REDIS_BINARY, "", str) or ""),
            stop_redis_on_exit=bool(
                settings.value(SETTING_STOP_REDIS_ON_EXIT, True, bool)),
        )

    @staticmethod
    def env_dir_default() -> str:
        return os.path.join(str(Path.home()), DEFAULT_ENV_DIR)


class Doctor:
    """Runs environment checks and applies automatic fixes."""

    def __init__(self, config: DoctorConfig):
        self.config = config
        self.redis: redis_service.ManagedRedis = None
        self.python_cmd: list = None
        self.python_version = None

    # ------------------------------------------------------------- checks
    def check_python(self) -> CheckResult:
        cmd, version = python_env.find_python(self.config.python_path)
        self.python_cmd, self.python_version = cmd, version
        if cmd is None:
            probed = ", ".join(" ".join(c) for c in python_env.candidate_interpreters())
            return CheckResult(
                "python", False,
                f"No Python >= {self._min_str()} found",
                f"Probed: {probed}. Install Python 3.12+ or point the plugin to an "
                "interpreter in Preferences (search for 'Epigrass').",
                fixable=False,
            )
        return CheckResult("python", True,
                           f"Python {version[0]}.{version[1]} found",
                           detail=" ".join(cmd))

    def check_venv(self) -> CheckResult:
        venv_dir = Path(os.path.expanduser(self.config.env_dir))
        python = python_env.venv_python_path(venv_dir)
        if not Path(python).exists():
            return CheckResult(
                "venv", False, "Managed environment not created yet",
                detail=str(venv_dir), fixable=True,
            )
        version = python_env.epigrass_version(venv_dir)
        if not version:
            return CheckResult(
                "epigrass", False, "Epigrass is not installed in the managed environment",
                detail=str(venv_dir), fixable=True,
            )
        return CheckResult("epigrass", True, f"Epigrass {version} installed",
                           detail=str(venv_dir))

    def check_redis(self) -> CheckResult:
        if redis_service.ping(self.config.redis_host, self.config.redis_port):
            return CheckResult("redis", True,
                               f"Redis reachable at {self.config.redis_host}:{self.config.redis_port}")
        binary = redis_service.find_server(self.config.redis_binary)
        if binary:
            return CheckResult(
                "redis", False, "Redis not running (redis-server found)",
                detail=f"Binary: {binary}. The doctor can start it for you.", fixable=True,
            )
        detail = redis_service.WINDOWS_HINT if os.name == "nt" else (
            "Install redis-server (e.g. 'sudo apt install redis-server' or "
            "'brew install redis') or run it in Docker: docker run -d -p "
            f"{self.config.redis_port}:6379 redis")
        return CheckResult("redis", False, "Redis not reachable and no redis-server found",
                           detail=detail, fixable=False)

    def check_all(self) -> list:
        return [self.check_python(), self.check_venv(), self.check_redis()]

    # ------------------------------------------------------------ actions
    def provision(self, on_line=None) -> list:
        """Apply every automatic fix. Returns the new check results."""
        python_check = self.check_python()
        if python_check.ok:
            venv_dir = os.path.expanduser(self.config.env_dir)
            if python_env.create_venv(self.python_cmd, venv_dir, on_line) != 0:
                log.error("venv creation failed")
            elif not python_env.epigrass_version(venv_dir):
                rc = python_env.pip_install(venv_dir, ("epigrass",), on_line=on_line)
                if rc != 0 and self._venv_python_mismatch(venv_dir):
                    # The existing venv was built with an interpreter whose
                    # dependency wheels are unavailable (e.g. fiona on a very
                    # new Python). Rebuild with the preferred one and retry.
                    if on_line:
                        on_line("Rebuilding the managed environment with a more "
                                "compatible interpreter...")
                    python_env.remove_venv(venv_dir)
                    python_env.create_venv(self.python_cmd, venv_dir, on_line)
                    python_env.pip_install(venv_dir, ("epigrass",), on_line=on_line)
        self._ensure_redis(on_line)
        return self.check_all()

    def _venv_python_mismatch(self, venv_dir) -> bool:
        """True when the venv's Python differs from the preferred interpreter."""
        venv_version = python_env.interpreter_version(
            python_env.venv_python_path(venv_dir))
        return bool(venv_version) and venv_version != self.python_version

    def install_epigrass(self, on_line=None) -> int:
        """(Re)install Epigrass in the managed venv. Returns pip exit code."""
        venv_dir = os.path.expanduser(self.config.env_dir)
        if not Path(python_env.venv_python_path(venv_dir)).exists():
            if self.python_cmd is None:
                self.check_python()
            if self.python_cmd is None:
                raise RuntimeError("No suitable Python interpreter found")
            python_env.create_venv(self.python_cmd, venv_dir, on_line)
        return python_env.pip_install(venv_dir, ("epigrass",), on_line=on_line)

    def _ensure_redis(self, on_line=None) -> bool:
        if redis_service.ping(self.config.redis_host, self.config.redis_port):
            return True
        binary = redis_service.find_server(self.config.redis_binary)
        if not binary:
            return False
        if on_line:
            on_line(f"Starting redis-server ({binary})...")
        self.redis = redis_service.ManagedRedis(
            binary, self.config.redis_host, self.config.redis_port)
        started = self.redis.start()
        if not started and on_line:
            on_line(f"Failed to start redis-server. Log: {self.redis.log_path}")
        return started

    def ensure_ready(self, on_line=None) -> bool:
        """True when a simulation can run (provisioning anything missing first)."""
        results = self.provision(on_line=on_line)
        return all(r.ok for r in results)

    def epirunner_command(self, epg_path: str) -> list:
        """Full command line to run *epg_path* with the managed environment."""
        venv_dir = os.path.expanduser(self.config.env_dir)
        runner = python_env.epirunner_path(venv_dir)
        if not Path(runner).exists():
            raise RuntimeError(
                "epirunner is not installed in the managed environment "
                f"({venv_dir}). Run the Environment Doctor first.")
        # sqlite backend writes Epigrass.sqlite, used for the temporal layer
        return [runner, str(epg_path), "--backend", "sqlite"]

    def venv_python(self) -> str:
        return python_env.venv_python_path(os.path.expanduser(self.config.env_dir))

    def shutdown(self) -> None:
        if self.redis and self.config.stop_redis_on_exit:
            self.redis.stop()

    @staticmethod
    def _min_str() -> str:
        return f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"


SETTINGS_KEYS = (
    SETTING_PYTHON_PATH, SETTING_ENV_DIR, SETTING_REDIS_HOST, SETTING_REDIS_PORT,
    SETTING_REDIS_BINARY, SETTING_STOP_REDIS_ON_EXIT,
)
