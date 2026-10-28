"""Redis detection and management.

The Epigrass engine hard-requires a reachable Redis server at import time
(``assert redisclient.ping()`` in ``Epigrass.simobj``).  The plugin pings the
server with a raw RESP command (no external dependencies) and can start a
``redis-server`` child process when a binary is available.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

WINDOWS_HINT = (
    "Redis has no official Windows build. Options:\n"
    "  - Install Memurai (https://www.memurai.com/), a Redis-compatible server for Windows;\n"
    "  - Run Redis inside WSL2:  wsl -d Ubuntu sudo service redis-server start;\n"
    "  - Run Redis in Docker:    docker run -d -p 6379:6379 redis"
)


def ping(host: str = "localhost", port: int = 6379, timeout: float = 1.0) -> bool:
    """Check that a Redis server answers PING (raw RESP, no dependencies)."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            return sock.recv(16).startswith(b"+")
    except OSError:
        return False


def find_server(configured: str = "") -> str:
    """Locate a ``redis-server`` binary (configured path first, then PATH/known spots)."""
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("redis-server")
    if found:
        return found
    prefixes = ["/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/local/bin"]
    if sys.platform == "darwin":
        prefixes += [os.path.expanduser("~/homebrew/bin")]
    for prefix in prefixes:
        candidate = Path(prefix) / "redis-server"
        if candidate.exists():
            return str(candidate)
    return ""


class ManagedRedis:
    """A redis-server child process owned by the plugin."""

    def __init__(self, binary: str, host: str = "localhost", port: int = 6379,
                 data_dir: str | None = None):
        self.binary = binary
        self.host = host
        self.port = port
        self.data_dir = data_dir or tempfile.mkdtemp(prefix="epigrass-redis-")
        self.proc: subprocess.Popen = None
        self.log_path = str(Path(self.data_dir) / "redis.log")

    def start(self, wait_seconds: float = 10.0) -> bool:
        if self.is_running():
            return True
        cmd = [
            self.binary,
            "--port", str(self.port),
            "--bind", "127.0.0.1" if self.host in ("localhost", "127.0.0.1") else self.host,
            "--dir", self.data_dir,
            "--save", "",           # no snapshots: ephemeral simulation state only
            "--appendonly", "no",
            "--daemonize", "no",
        ]
        log.info("Starting redis: %s", " ".join(cmd))
        log_file = open(self.log_path, "ab")
        self.proc = subprocess.Popen(  # nosec B603 - argv list, no shell; redis-server from configured/auto-discovered absolute path
            cmd, stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        # Wait for the server to accept connections
        for _ in range(int(wait_seconds * 4)):
            if self.proc.poll() is not None:
                log.error("redis-server exited early (see %s)", self.log_path)
                return False
            if ping(self.host, self.port):
                return True
            import time

            time.sleep(0.25)
        return False

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            log.info("Stopping managed redis-server")
            try:
                if sys.platform == "win32":
                    self.proc.terminate()
                else:
                    self.proc.send_signal(signal.SIGTERM)
                self.proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                try:
                    self.proc.kill()
                except OSError:
                    pass
        self.proc = None
