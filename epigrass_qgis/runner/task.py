"""Run epirunner as a subprocess inside a QGIS task (background thread)."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys

from qgis.core import QgsTask
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..env import redis_service

log = logging.getLogger(__name__)


class SimulationSignals(QObject):
    """Thread-safe signals emitted by the running :class:`SimulationTask`."""

    log_line = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, message


class SimulationTask(QgsTask):
    """Executes ``epirunner model.epg`` in the managed environment.

    Runs in a QgsTask worker thread; all UI updates must go through
    :attr:`signals`.  After success, ``self.outdir`` points to the directory
    with results (GeoPackages + SQLite).
    """

    def __init__(self, description: str, project_dir: str, command: list,
                 redis_config: redis_service.ManagedRedis | None = None):
        super().__init__(description, QgsTask.CanCancel)
        self.project_dir = project_dir
        self.command = command
        self.signals = SimulationSignals()
        self.outdir = ""
        self._proc: subprocess.Popen = None
        self._redis = redis_config

    # ------------------------------------------------------------------
    def run(self) -> bool:  # executed on the task thread
        model_epg = os.path.join(self.project_dir, "model.epg")
        if not os.path.isfile(model_epg):
            self._fail(f"model.epg not found in {self.project_dir}")
            return False
        if self._redis is not None and not redis_service.ping(
                self._redis.host, self._redis.port):
            self.signals.log_line.emit("Starting Redis server...")
            if not self._redis.start():
                self._fail(
                    "Could not start redis-server. See "
                    f"{self._redis.log_path}")
                return False
        self.signals.log_line.emit("$ " + " ".join(self.command))
        try:
            self._proc = subprocess.Popen(  # nosec B603 - argv list, no shell; epirunner from the plugin-managed venv
                self.command, cwd=self.project_dir,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, errors="replace", bufsize=1,
            )
        except OSError as exc:
            self._fail(f"Failed to launch epirunner: {exc}")
            return False
        for line in self._proc.stdout:
            if self.isCanceled():
                self._kill()
                self.signals.log_line.emit("Simulation cancelled by user.")
                self.signals.finished.emit(False, "cancelled")
                return False
            self.signals.log_line.emit(line.rstrip("\n"))
            self.setProgress(min(99, self.progress() + 1))
        returncode = self._proc.wait()
        if self.isCanceled():
            self.signals.finished.emit(False, "cancelled")
            return False
        if returncode != 0:
            self._fail(f"epirunner exited with code {returncode}")
            return False
        self.outdir = self._find_outdir()
        if not self.outdir:
            self._fail("Simulation produced no output directory.")
            return False
        self.signals.log_line.emit(f"Results written to {self.outdir}")
        self.setProgress(100)
        self.signals.finished.emit(True, self.outdir)
        return True

    # ------------------------------------------------------------------
    def _fail(self, message: str):
        log.error(message)
        self.signals.log_line.emit(f"ERROR: {message}")
        self.signals.finished.emit(False, message)

    def _kill(self):
        if self._proc and self._proc.poll() is None:
            try:
                if sys.platform == "win32":
                    self._proc.terminate()
                else:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    self._proc.terminate()
                except OSError:
                    pass

    def cancel(self):
        self._kill()
        super().cancel()

    def _find_outdir(self) -> str:
        """Locate the outdata-<model> directory (newest match wins)."""
        candidates = []
        for name in sorted(os.listdir(self.project_dir)):
            if name.startswith("outdata-"):
                path = os.path.join(self.project_dir, name)
                if os.path.isdir(path):
                    candidates.append(path)
        return candidates[-1] if candidates else ""
