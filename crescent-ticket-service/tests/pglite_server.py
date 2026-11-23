"""Start and stop real PGlite socket servers for the test suite.

Each server is a separate `node database/start-db.mjs` process with its own data
directory and an OS-assigned free port, so tests can never touch the
application database (database/pgdata/app on port 55432).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = PROJECT_ROOT / "database"
START_SCRIPT = DATABASE_DIR / "start-db.mjs"
READY_PATTERN = re.compile(r"\[pglite\] READY host=(?P<host>\S+) port=(?P<port>\d+)")


class PGliteStartError(RuntimeError):
    pass


class PGliteServer:
    def __init__(self, data_dir: Path | str, *, port: int = 0, max_connections: int = 4) -> None:
        self.data_dir = str(data_dir)
        self.requested_port = port
        self.max_connections = max_connections
        self.port: int | None = None
        self.process: subprocess.Popen[str] | None = None
        self.output: list[str] = []
        self._ready = threading.Event()
        self._reader: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------------

    def start(self, timeout: float = 90.0) -> PGliteServer:
        node = shutil.which("node")
        if node is None:
            raise PGliteStartError("Node.js 22 is required to run the PGlite test database ('node' not found)")
        if not (DATABASE_DIR / "node_modules" / "@electric-sql" / "pglite-socket").is_dir():
            raise PGliteStartError("PGlite packages are not installed. Run: cd database && npm ci")

        self.process = subprocess.Popen(
            [
                node,
                str(START_SCRIPT),
                "--data-dir",
                self.data_dir,
                "--port",
                str(self.requested_port),
                "--max-connections",
                str(self.max_connections),
                "--exit-on-stdin-close",
            ],
            cwd=DATABASE_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PGLITE_HOST": "127.0.0.1"},
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

        deadline = time.monotonic() + timeout
        while not self._ready.wait(0.1):
            if self.process.poll() is not None:
                raise PGliteStartError(f"PGlite exited with code {self.process.returncode}:\n{self.log}")
            if time.monotonic() > deadline:
                self.kill()
                raise PGliteStartError(f"PGlite did not become ready within {timeout}s:\n{self.log}")
        return self

    def stop(self, timeout: float = 30.0) -> int:
        """Graceful shutdown (closes stdin, PGlite flushes and closes the database)."""
        if self.process is None:
            return 0
        if self.process.poll() is None:
            try:
                assert self.process.stdin is not None
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout)
            except subprocess.TimeoutExpired:
                self.kill()
        if self._reader is not None:
            self._reader.join(5)
        return self.process.returncode

    def kill(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(10)

    # -- helpers -----------------------------------------------------------------

    def _read_output(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            self.output.append(line.rstrip())
            match = READY_PATTERN.search(line)
            if match:
                self.port = int(match.group("port"))
                self._ready.set()

    @property
    def log(self) -> str:
        return "\n".join(self.output)

    @property
    def url(self) -> str:
        if self.port is None:
            raise RuntimeError("server not started")
        return f"postgresql+psycopg2://postgres:postgres@127.0.0.1:{self.port}/postgres?sslmode=disable"

    def __enter__(self) -> PGliteServer:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()
