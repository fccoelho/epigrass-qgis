"""Discovery and management of the isolated Python environment used to run Epigrass.

QGIS's own interpreter is never touched: the plugin looks for a Python >= 3.12
(system, uv-managed or user configured), creates a dedicated virtualenv and
installs Epigrass into it.  Simulations are then executed with the ``epirunner``
binary from that environment.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from ..defs import MIN_PYTHON

log = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"Python (\d+)\.(\d+)(?:\.(\d+))?")


class StreamedCommand:
    """Run *cmd* streaming stdout/stderr lines to a callback. Thread-safe."""

    def __init__(self, cmd: list, cwd: str | None = None, env: dict | None = None):
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.returncode = None
        self._proc = None
        self._cancelled = threading.Event()

    def run(self, on_line=None, timeout: float | None = None) -> int:
        log.debug("Running: %s", self.cmd)
        self._proc = subprocess.Popen(  # nosec B603 - argv list, no shell; interpreter/path resolved locally
            self.cmd, cwd=self.cwd, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, errors="replace", bufsize=1,
        )
        reader = threading.Thread(target=self._pump, args=(on_line,), daemon=True)
        reader.start()
        reader.join(timeout)
        if reader.is_alive():  # timeout hit
            self.cancel()
            reader.join(5)
        self.returncode = self._proc.wait()
        log.debug("Command finished with %s", self.returncode)
        return self.returncode

    def _pump(self, on_line):
        if not (self._proc and self._proc.stdout):
            return
        for line in self._proc.stdout:
            if self._cancelled.is_set():
                break
            if on_line:
                try:
                    on_line(line.rstrip("\n"))
                except Exception:
                    log.exception("Output callback failed")
            else:
                log.debug("pip: %s", line.rstrip())

    def cancel(self) -> None:
        self._cancelled.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass


def parse_python_version(text: str):
    """Extract a (major, minor) tuple from *text* (e.g. 'Python 3.12.7')."""
    m = _VERSION_RE.search(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def resolve_executable(name: str) -> str:
    """Return the absolute path of *name* on PATH (empty string if not found).

    Pinning the resolved absolute path protects against PATH hijacking
    between discovery and execution.
    """
    return shutil.which(name) or (name if os.path.isabs(name) and
                                  os.path.isfile(name) else "")


def check_interpreter(path: str, timeout: float = 15.0):
    """Return (major, minor) if *path* is a working Python interpreter, else None."""
    resolved = resolve_executable(path)
    if not resolved:
        return None
    try:
        out = subprocess.run(  # nosec B603 - fixed argv, resolved absolute path
            [resolved, "-c", "import sys; print(sys.version)"],
            capture_output=True, text=True, timeout=timeout, errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return parse_python_version(out.stdout)


def is_sufficient(version) -> bool:
    return bool(version) and version >= MIN_PYTHON


def candidate_interpreters() -> list:
    """Interpreter command lines worth probing, most preferred first."""
    cands = []
    if sys.platform == "win32":
        # Windows: py launcher supports explicit versions
        for minor in (13, 12):
            cands.append(["py", f"-{MIN_PYTHON[0]}.{minor}"])
        cands.append(["python"])
    else:
        for minor in (14, 13, 12):
            cands.append([f"python{MIN_PYTHON[0]}.{minor}"])
        cands.append(["python3"])
        cands.append(["python"])
    for uv in ("uv",):
        if shutil.which(uv):
            cands.append([uv, "run", "python"])
    return cands


def find_python(configured: str = ""):
    """Return the first command line that runs a Python >= MIN_PYTHON.

    Returns ``(cmd_list, version)`` or ``(None, None)``.
    """
    candidates = []
    if configured:
        candidates.append(shlex_split(configured))
    candidates += candidate_interpreters()
    for cmd in candidates:
        version = _check_cmd(cmd)
        if is_sufficient(version):
            return cmd, version
    return None, None


def _check_cmd(cmd: list):
    resolved_cmd = [resolve_executable(cmd[0]), *cmd[1:]]
    if not resolved_cmd[0]:
        return None
    try:
        out = subprocess.run(  # nosec B603 - fixed argv, resolved absolute path
            [*resolved_cmd, "-c", "import sys; print(sys.version)"],
            capture_output=True, text=True, timeout=15, errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_python_version(out.stdout) if out.returncode == 0 else None


def shlex_split(text: str) -> list:
    import shlex

    try:
        return shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        return [text]


def venv_python_path(venv_dir) -> str:
    venv_dir = Path(venv_dir)
    if sys.platform == "win32":
        return str(venv_dir / "Scripts" / "python.exe")
    return str(venv_dir / "bin" / "python")


def create_venv(python_cmd: list, venv_dir, on_line=None) -> int:
    """Create a virtualenv at *venv_dir* using *python_cmd*. Returns exit code."""
    venv_dir = Path(venv_dir)
    if venv_dir.exists() and (Path(venv_python_path(venv_dir)).exists()):
        return 0
    return StreamedCommand([*python_cmd, "-m", "venv", str(venv_dir)]).run(on_line)


def pip_install(venv_dir, packages=("epigrass",), upgrade: bool = True,
                on_line=None) -> int:
    """pip install *packages* into the venv. Returns exit code."""
    python = venv_python_path(venv_dir)
    cmd = [python, "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd += list(packages)
    return StreamedCommand(cmd, env=_pip_env()).run(on_line)


def _pip_env() -> dict:
    """Environment for pip runs (ensure user site-packages do not leak)."""
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def epirunner_path(venv_dir) -> str:
    venv_dir = Path(venv_dir)
    if sys.platform == "win32":
        return str(venv_dir / "Scripts" / "epirunner.exe")
    return str(venv_dir / "bin" / "epirunner")


def epigrass_version(venv_dir) -> str:
    """Return the installed Epigrass version, or '' if not installed."""
    python = venv_python_path(venv_dir)
    try:
        out = subprocess.run(  # nosec B603 - fixed argv against the managed venv's interpreter
            [python, "-c",
             "from importlib.metadata import version; print(version('epigrass'))"],
            capture_output=True, text=True, timeout=30, errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""
