"""Run now: start a run as a separate process, and tell the page how it is going.

The run is a separate process so the page stays quick while it works, and a run that
fails cannot take the page down with it. Its output goes to a log file, which the page
shows as the last result. One run at a time.
"""

import subprocess
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import IO, Literal, Protocol

from pydantic import BaseModel

Mode = Literal["saved", "sample", "improve"]
LOG_NAME = "run-now.log"


class Process(Protocol):
    def poll(self) -> int | None: ...


Launch = Callable[[list[str], IO[str]], Process]


def launch_process(args: list[str], stdout: IO[str]) -> Process:
    return subprocess.Popen(args, stdout=stdout, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


class AlreadyRunning(Exception):
    """A run started from the page has not finished yet."""


class RunState(BaseModel):
    running: bool
    mode: Mode | None = None
    started_at: datetime | None = None
    exit_code: int | None = None  # None while running, or for a run started before a restart
    output: str = ""  # the last run's output, empty if there has been none


class RunNow:
    def __init__(
        self,
        command: list[str],
        settings_file: Path | None,
        log_dir: Path,
        launch: Launch = launch_process,
        *,
        clock: Callable[[], datetime],
    ):
        self.command = command  # how to call `why-now`, such as [python, "-m", "why_now"]
        self.settings_file = settings_file
        self.log_path = log_dir / LOG_NAME
        self.launch = launch
        self.clock = clock
        self._lock = threading.Lock()
        self._process: Process | None = None
        self._mode: Mode | None = None
        self._started_at: datetime | None = None

    def args(self, mode: Mode, profile_file: Path, sample_boards: int) -> list[str]:
        if mode == "improve":
            args = [*self.command, "improve", "--profile", str(profile_file)]
        else:
            args = [*self.command, "daily", "--profile", str(profile_file)]
            args += ["--saved-read"] if mode == "saved" else ["--sample-boards", str(sample_boards)]
        if self.settings_file is not None:
            args += ["--settings", str(self.settings_file)]
        return args

    def start(self, mode: Mode, profile_file: Path, sample_boards: int) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise AlreadyRunning("a run is still going")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            # The process keeps its own copy of the file, so this one is closed straight away.
            with self.log_path.open("w", encoding="utf-8") as log:
                self._process = self.launch(self.args(mode, profile_file, sample_boards), log)
            self._mode = mode
            self._started_at = self.clock()

    def state(self) -> RunState:
        with self._lock:
            code = None if self._process is None else self._process.poll()
            running = self._process is not None and code is None
        output = (
            self.log_path.read_text(encoding="utf-8", errors="replace")
            if (self.log_path.is_file())
            else ""
        )
        return RunState(
            running=running,
            mode=self._mode,
            started_at=self._started_at,
            exit_code=code,
            output=output,
        )
