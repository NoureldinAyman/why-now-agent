"""Run now, Improve now and the Runs page on AWS, and the notes every run writes."""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from starlette.requests import Request

from why_now.settings import Settings
from why_now.web.app import AppContext, create_app
from why_now.web.auth import LocalAuth
from why_now.web.run_now import AwsRunNow
from why_now.web.runs_view import next_run_at, until
from why_now.workspace import Workspace
from why_now.workspace.runs import RunSummary

from .conftest import NOW

STALE = timedelta(hours=12)


class SignedIn:
    def current_user(self, request: Request) -> str | None:
        return "reviewer"


class FakeEcs:
    """Stands in for the ECS service. Records each task it is asked to start."""

    def __init__(self, error: Exception | None = None, failures: list[dict] | None = None):
        self.calls: list[dict] = []
        self.error = error
        self.failures = failures or []

    def run_task(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {
            "tasks": [{"taskArn": "arn:task/1"}] if not self.failures else [],
            "failures": self.failures,
        }


@pytest.fixture
def aws_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "deployment": "aws",
            "aws_run_cluster": "arn:cluster/main",
            "aws_run_task": "arn:task-definition/night:3",
            "aws_run_subnets": ["subnet-1", "subnet-2"],
            "aws_run_security_groups": ["sg-1"],
            "display_timezone": "Europe/Berlin",
            "aws_run_hour_utc": 2,
        }
    )


@pytest.fixture
def ecs() -> FakeEcs:
    return FakeEcs()


class Clock:
    """The runner's clock, which a test can move on."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def aws_ctx(aws_settings, make_ctx, ecs, store, clock) -> AppContext:
    ctx = make_ctx(aws_settings)
    ctx.runner = AwsRunNow(aws_settings, ecs, store, clock)
    return ctx


@pytest.fixture
def aws(aws_ctx) -> TestClient:
    return TestClient(create_app(aws_ctx, SignedIn()))


def token(client: TestClient, path: str = "/run") -> str:
    found = re.search(r'name="form_token" value="([^"]+)"', client.get(path).text)
    assert found, f"{path} has no form token"
    return found.group(1)


def press(client: TestClient, mode: str, form_token: str | None = None):
    data = {"mode": mode, "form_token": form_token or token(client)}
    return client.post("/run", data=data, follow_redirects=False)


# Starting a run on AWS


def test_run_now_starts_the_night_runs_task_with_the_daily_command(aws, ecs, profile):
    assert press(aws, "saved").status_code == 303
    assert ecs.calls == [
        {
            "cluster": "arn:cluster/main",
            "taskDefinition": "arn:task-definition/night:3",
            "launchType": "FARGATE",
            "count": 1,
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": ["subnet-1", "subnet-2"],
                    "securityGroups": ["sg-1"],
                    "assignPublicIp": "ENABLED",
                }
            },
            "overrides": {
                "containerOverrides": [
                    {"name": "Run", "command": ["daily", "--profile", profile.id, "--saved-read"]}
                ]
            },
        }
    ]


def test_run_now_can_read_a_sample_of_careers_pages_on_aws(aws, ecs, profile, aws_settings):
    press(aws, "sample")
    (command,) = [c["overrides"]["containerOverrides"][0]["command"] for c in ecs.calls]
    assert command == [
        "daily", "--profile", profile.id,
        "--sample-boards", str(aws_settings.run_now_sample_boards),
    ]  # fmt: skip


def test_improve_now_starts_the_improvement_run_on_aws(aws, ecs, profile):
    assert press(aws, "improve").status_code == 303
    (command,) = [c["overrides"]["containerOverrides"][0]["command"] for c in ecs.calls]
    assert command == ["improve", "--profile", profile.id]


def test_a_second_press_while_a_run_is_going_is_refused(aws, ecs, store):
    form_token = token(aws)  # the page has no form while a run is going
    Workspace(store).start_run("anyone", "night", NOW - timedelta(minutes=20), STALE)

    reply = press(aws, "saved", form_token)

    assert reply.status_code == 409
    assert "still going" in reply.text
    assert ecs.calls == []


def test_a_second_press_before_the_first_task_has_started_is_refused(aws, ecs):
    form_token = token(aws)
    assert press(aws, "saved", form_token).status_code == 303

    again = press(aws, "improve", form_token)

    assert again.status_code == 409
    assert "just started" in again.text
    assert len(ecs.calls) == 1


def test_the_press_is_allowed_again_once_the_start_wait_has_passed(aws, ecs, clock, aws_settings):
    form_token = token(aws)
    press(aws, "saved", form_token)

    clock.now = NOW + timedelta(seconds=aws_settings.run_start_wait_seconds)

    assert press(aws, "saved", form_token).status_code == 303
    assert len(ecs.calls) == 2


def test_a_task_that_would_not_start_does_not_hold_up_the_next_press(aws_ctx, aws, ecs):
    form_token = token(aws)
    ecs.error = ClientError({"Error": {"Code": "ThrottlingException"}}, "RunTask")
    assert press(aws, "saved", form_token).status_code == 502

    ecs.error = None
    assert press(aws, "saved", form_token).status_code == 303
    assert len(ecs.calls) == 2


def test_the_page_shows_the_run_that_is_going_and_no_start_form(aws, store, profile):
    Workspace(store).start_run(profile.id, "night", NOW - timedelta(minutes=20), STALE)

    page = aws.get("/run").text

    assert "A run is going" in page
    assert 'name="mode"' not in page


def test_a_run_that_stopped_does_not_block_the_next_press(aws, ecs, store, profile):
    Workspace(store).start_run(profile.id, "night", NOW - timedelta(hours=13), STALE)

    assert press(aws, "saved").status_code == 303
    assert len(ecs.calls) == 1


def test_an_unknown_mode_starts_nothing(aws, ecs):
    assert press(aws, "everything").status_code == 422
    assert ecs.calls == []


@pytest.mark.parametrize(
    "ecs",
    [
        FakeEcs(error=ClientError({"Error": {"Code": "AccessDeniedException"}}, "RunTask")),
        FakeEcs(failures=[{"reason": "RESOURCE:FARGATE"}]),
    ],
)
def test_a_task_that_would_not_start_is_explained_and_not_a_crash(aws, ecs):
    reply = press(aws, "saved")
    assert reply.status_code == 502
    assert "was not started" in reply.text


def test_without_the_run_task_set_up_the_page_says_so_and_starts_nothing(aws_settings, make_ctx):
    ctx = make_ctx(aws_settings)
    client = TestClient(create_app(ctx, SignedIn()))
    page = client.get("/run").text
    assert 'name="mode"' not in page
    data = {"mode": "saved", "form_token": "any"}
    assert client.post("/run", data=data).status_code in (403, 404)


def test_the_settings_a_run_starts_with_cannot_be_changed_from_the_page(aws, ecs, profile):
    response = aws.post(
        "/run",
        data={"mode": "saved", "form_token": token(aws), "aws_run_task": "evil", "profile": "x"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert ecs.calls[0]["taskDefinition"] == "arn:task-definition/night:3"


# The Runs page


def note(
    store,
    profile,
    mode,
    start,
    summary,
    ended: Literal["finished", "failed"] | None = "finished",
    minutes=10,
):
    workspace = Workspace(store)
    started = workspace.start_run(profile.id, mode, start, STALE)
    if ended is not None:
        workspace.finish_run(started, start + timedelta(minutes=minutes), summary, ended)


def test_the_runs_page_lists_the_last_runs_with_their_summaries(aws, store, profile):
    note(store, profile, "daily", NOW - timedelta(days=2), RunSummary(short_list=4, more_list=30))
    note(store, profile, "night", NOW - timedelta(hours=7), RunSummary(short_list=5, more_list=22))

    page = aws.get("/run").text

    assert page.index("5 on the short list") < page.index("4 on the short list")  # newest first
    assert "22 on the more list" in page
    assert "Night run" in page and "Daily list" in page


def test_the_runs_page_shows_times_in_the_display_time_zone(aws, store, profile):
    note(store, profile, "daily", datetime(2026, 11, 6, 2, 0, tzinfo=UTC), RunSummary())
    assert "06 Nov 2026 03:00" in aws.get("/run").text  # Berlin is an hour ahead in November


def test_a_start_with_no_finish_shows_as_a_run_that_stopped(aws, store, profile):
    note(store, profile, "night", NOW - timedelta(hours=13), RunSummary(), ended=None)
    page = aws.get("/run").text
    assert "Stopped without finishing" in page
    assert "A run is going" not in page


def test_a_failed_run_shows_why(aws, store, profile):
    note(
        store, profile, "daily", NOW - timedelta(hours=3),
        RunSummary(problem="RuntimeError: <b>no board lists</b>"), ended="failed",
    )  # fmt: skip
    page = aws.get("/run").text
    assert "Failed" in page
    assert "RuntimeError: &lt;b&gt;no board lists&lt;/b&gt;" in page


def test_the_runs_page_shows_what_each_try_of_the_last_improvement_run_did(aws, store, profile):
    note(
        store, profile, "improve", NOW - timedelta(hours=5),
        RunSummary(tries=["Try 1: discarded. Add: a question", "Try 2: kept. Remove q2."],
                   stop="Stopped: no mistakes are left to learn from."),
    )  # fmt: skip
    page = aws.get("/run").text
    assert "Try 1: discarded" in page and "Try 2: kept" in page
    assert "no mistakes are left to learn from" in page


def test_the_runs_page_lists_no_more_than_runs_shown(aws, aws_ctx, store, profile):
    aws_ctx.settings = aws_ctx.settings.model_copy(update={"runs_shown": 2})
    for i in range(4):
        note(store, profile, "daily", NOW - timedelta(days=i + 1), RunSummary(short_list=i))
    page = aws.get("/run").text
    assert page.count("on the short list") == 2


def test_the_next_run_and_the_time_until_it_are_written_by_the_server(aws):
    page = aws.get("/run").text
    # 09:00 UTC on the 6th. The schedule is at 02:00 UTC, so 03:00 in Berlin on the 7th.
    assert "07 Nov 2026 03:00" in page
    assert "in 17 hours" in page
    assert "Europe/Berlin" in page


def test_nothing_is_said_about_a_schedule_on_ones_own_computer(client):
    assert "Next run" not in client.get("/run").text


def test_the_local_runs_page_lists_run_notes_too(client, store, profile):
    note(store, profile, "daily", NOW - timedelta(hours=3), RunSummary(short_list=2))
    assert "2 on the short list" in client.get("/run").text


# Which profiles run each night


def test_the_page_says_which_profiles_run_each_night(aws, aws_ctx, profile):
    aws_ctx.settings = aws_ctx.settings.model_copy(update={"nightly_profiles": [profile.id]})
    page = aws.get("/run").text
    assert profile.product_name in page
    assert "checked" in page


def test_switching_every_profile_off_says_the_night_run_does_nothing(aws, aws_ctx, profile):
    aws_ctx.settings = aws_ctx.settings.model_copy(update={"nightly_profiles": [profile.id]})
    reply = aws.post(
        "/run/nightly",
        data={"nightly_listed": "1", "form_token": token(aws)},
        follow_redirects=False,
    )
    assert reply.status_code == 303
    assert "no profile is switched on" in aws.get("/run").text.lower()


def test_a_profile_can_be_switched_on_for_the_night_from_the_runs_page(aws, profile):
    aws.post(
        "/run/nightly",
        data={"nightly_listed": "1", "nightly_profiles": profile.id, "form_token": token(aws)},
    )
    page = aws.get("/run").text
    assert "checked" in page and "no profile is switched on" not in page.lower()


def test_the_night_switch_stores_nothing_but_the_night_list(aws, aws_ctx):
    reply = aws.post(
        "/run/nightly",
        data={"nightly_listed": "1", "form_token": token(aws), "research_per_day": "500"},
    )
    assert reply.status_code == 422
    assert aws_ctx.store.get("settings", "overrides") is None


def test_the_night_switch_needs_the_login(ctx):
    anonymous = TestClient(create_app(ctx, LocalAuth()), client=("203.0.113.9", 5000))
    assert anonymous.post("/run/nightly", data={}).status_code in (401, 403)


# The schedule


def test_the_next_run_follows_the_hour_setting():
    morning = datetime(2026, 11, 6, 1, 30, tzinfo=UTC)
    assert next_run_at(morning, 2) == datetime(2026, 11, 6, 2, 0, tzinfo=UTC)
    assert next_run_at(datetime(2026, 11, 6, 2, 0, tzinfo=UTC), 2) == datetime(
        2026, 11, 7, 2, 0, tzinfo=UTC
    )
    assert next_run_at(datetime(2026, 11, 6, 23, 59, tzinfo=UTC), 0) == datetime(
        2026, 11, 7, 0, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("delta", "words"),
    [
        (timedelta(seconds=20), "in under a minute"),
        (timedelta(minutes=45), "in 45 minutes"),
        (timedelta(hours=1, minutes=1), "in 1 hour 1 minute"),
        (timedelta(hours=17), "in 17 hours"),
        (timedelta(hours=5, minutes=12), "in 5 hours 12 minutes"),
    ],
)
def test_the_time_until_the_next_run_is_in_plain_words(delta, words):
    assert until(delta) == words
