"""Own the single worker process used by the Blender add-on."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess

from .worker_protocol import ProtocolError, decode_result


@dataclass(frozen=True)
class WorkerCompletion:
    """Validated result and request metadata returned by the worker."""

    source: str
    requested_channel: str
    result: dict[str, object]


class WorkerProcess:
    """Own worker startup, polling, decoding, and shutdown for one add-on."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._source = ""
        self._channel = ""

    @property
    def active(self) -> bool:
        return self._process is not None

    @property
    def source(self) -> str:
        return self._source

    def start(
        self,
        command: list[str],
        *,
        source: str,
        channel: str,
        creationflags: int = 0,
    ) -> None:
        if self.active:
            raise RuntimeError("An update check is already running")
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        self._process = process
        self._source = source
        self._channel = channel

    def poll(self) -> WorkerCompletion | None:
        """Return completion if the child exited; return None while it runs."""

        process = self._process
        if process is None or process.poll() is None:
            return None

        source = self._source
        channel = self._channel
        stdout, stderr = process.communicate()
        self._clear()
        try:
            result = decode_result(stdout, stderr)
        except ProtocolError as exc:
            detail = stderr.strip() or str(exc)
            result = {"ok": False, "error": f"The update checker failed: {detail}"}
        return WorkerCompletion(source, channel, result)

    def terminate(self) -> None:
        process = self._process
        self._clear()
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _clear(self) -> None:
        self._process = None
        self._source = ""
        self._channel = ""
