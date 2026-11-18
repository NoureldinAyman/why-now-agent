"""Run now: start a run apart from the page, and tell the page how it is going.

On one's own computer the run is a separate process, so the page stays quick while it works,
and a run that fails cannot take the page down with it. Its output goes to a log file, which
the page shows as the last result. On AWS the page starts the night run's task and nothing
else. Either way the run writes its own notes, which the page reads. One run at a time.
"""

import subprocess
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Literal, Protocol

from pydantic import BaseModel

from why_now.settings import Settings

Mode = Literal["saved", "sample", "improve"]
LOG_NAME = "run-now.log"


class Process(Protocol):
    def poll(self) -> int | None: ...


Launch = Callable[[list[str], IO[str]], Process]


def launch_process(args: list[str], stdout: IO[str]) -> Process:
    return subprocess.Popen(args, stdout=stdout, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


class AlreadyRunning(Exception):
    """A run started from the page has not finished yet."""


class RunNotStarted(Exception):
    """The run could not be started. The message says why, in plain words."""


def run_args(mode: Mode, profile: str, sample_boards: int) -> list[str]:
    """The `why-now` arguments for a run. `profile` is the id of a profile in the workspace."""
    if mode == "improve":
        return ["improve", "--profile", profile]
    args = ["daily", "--profile", profile]
    return args + (["--saved-read"] if mode == "saved" else ["--sample-boards", str(sample_boards)])


class Runner(Protocol):
    def start(self, mode: Mode, profile: str, sample_boards: int) -> None: ...

    def state(self) -> "RunState | None": ...


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

    def args(self, mode: Mode, profile: str, sample_boards: int) -> list[str]:
        """The command for a run. `profile` is the id of a profile in the workspace."""
        args = [*self.command, *run_args(mode, profile, sample_boards)]
        if self.settings_file is not None:
            args += ["--settings", str(self.settings_file)]
        return args

    def start(self, mode: Mode, profile: str, sample_boards: int) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise AlreadyRunning("a run is still going")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            # The process keeps its own copy of the file, so this one is closed straight away.
            with self.log_path.open("w", encoding="utf-8") as log:
                self._process = self.launch(self.args(mode, profile, sample_boards), log)
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


class AwsRunNow:
    """Starts the task the schedule starts, with the command for the chosen run.

    The web function may start that one task and nothing else. The cluster, the task and the
    network come from the settings the AWS setup gave the function, never from the page, so a
    posted form cannot point it anywhere else.
    """

    def __init__(self, settings: Settings, ecs: Any):
        self.settings = settings
        self.ecs = ecs  # a boto3 ECS client, or a stand-in with `run_task`

    def start(self, mode: Mode, profile: str, sample_boards: int) -> None:
        s = self.settings
        try:
            reply = self.ecs.run_task(
                cluster=s.aws_run_cluster,
                taskDefinition=s.aws_run_task,
                launchType="FARGATE",
                count=1,
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": s.aws_run_subnets,
                        "securityGroups": s.aws_run_security_groups,
                        "assignPublicIp": "ENABLED",
                    }
                },
                overrides={
                    "containerOverrides": [
                        {
                            "name": s.aws_run_container,
                            "command": run_args(mode, profile, sample_boards),
                        }
                    ]
                },
            )
        except Exception as e:  # shown as text, so a refusal from AWS is not a blank page
            code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
            raise RunNotStarted(f"The run was not started: AWS answered {code}.") from e
        if reply.get("failures") or not reply.get("tasks"):
            reasons = ", ".join(f.get("reason", "unknown") for f in reply.get("failures", []))
            raise RunNotStarted(f"The run was not started: AWS had no room for it ({reasons}).")

    def state(self) -> None:
        """No log is kept here. The run's own notes tell how it went."""
        return None
