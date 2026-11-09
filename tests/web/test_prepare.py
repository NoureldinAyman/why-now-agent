import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from why_now.domain import Profile
from why_now.testset.packs import BuildResult
from why_now.web.app import create_app
from why_now.web.auth import LocalAuth

from .conftest import LOCAL


class Preparer:
    """Stands in for the real step, which needs keys and costs money. Records what it is asked."""

    def __init__(self, result: BuildResult | None = None, error: Exception | None = None):
        self.calls: list[tuple[str, int, int]] = []
        self.result = result or BuildResult(built=3, picked=3, eligible=40)
        self.error = error

    def __call__(self, profile: Profile, n: int, seed: int) -> BuildResult:
        self.calls.append((profile.id, n, seed))
        if self.error:
            raise self.error
        return self.result


class SignedIn:
    def current_user(self, request: Request) -> str | None:
        return "someone"


def page_for(ctx, preparer, auth=None) -> TestClient:
    app = create_app(replace(ctx, prepare=preparer), auth or LocalAuth())
    return TestClient(app, client=LOCAL, base_url="http://localhost")


def form_of(client: TestClient) -> dict[str, str]:
    html = client.get("/mark").text
    seed = re.search(r'name="seed" value="(\d+)"', html)
    token = re.search(r'name="form_token" value="([^"]+)"', html)
    assert seed and token, "the page has no prepare form"
    return {"seed": seed.group(1), "form_token": token.group(1)}


def test_the_marking_page_offers_prepare_with_the_batch_size(ctx, case, settings):
    html = page_for(ctx, Preparer()).get("/mark").text
    assert f"Prepare {settings.prepare_batch}" in html
    assert 'action="/prepare"' in html


def test_prepare_is_also_offered_when_everything_is_marked(ctx, workspace):
    assert "Prepare 20" in page_for(ctx, Preparer()).get("/mark").text  # no cases at all


def test_no_button_without_a_prepare_step_or_on_the_repeat_page(ctx, client, case):
    assert "Prepare" not in client.get("/mark").text  # the context has none
    assert "Prepare" not in page_for(ctx, Preparer()).get("/repeat").text


def test_pressing_prepare_runs_it_with_the_batch_size_and_the_pages_seed(ctx, case, settings):
    preparer = Preparer(BuildResult(built=3, picked=3, eligible=40))
    client = page_for(ctx, preparer)
    form = form_of(client)
    reply = client.post("/prepare", data=form)
    assert reply.status_code == 200
    assert preparer.calls == [(case.profile_id, settings.prepare_batch, int(form["seed"]))]
    assert "3 companies were picked" in reply.text and "3 are ready" in reply.text
    assert 'href="/mark"' in reply.text


def test_a_stopped_or_failed_prepare_says_what_is_left(ctx, case):
    result = BuildResult(
        built=1, picked=3, eligible=9, failed={"case-x": "ValueError: no page"},
        stopped="Stopped: monthly limit of $70 reached. Packs built so far are saved.", left=2,
    )  # fmt: skip
    client = page_for(ctx, Preparer(result))
    reply = client.post("/prepare", data=form_of(client))
    assert "monthly limit of $70 reached" in reply.text
    assert "2 are left" in reply.text and "ValueError: no page" in reply.text


def test_an_error_while_preparing_is_shown_as_text_not_a_crash(ctx, case):
    client = page_for(ctx, Preparer(error=RuntimeError("no <b>key</b> set")))
    reply = client.post("/prepare", data=form_of(client))
    assert reply.status_code == 500
    assert "no &lt;b&gt;key&lt;/b&gt; set" in reply.text and "<b>key</b>" not in reply.text


def test_prepare_needs_the_form_token(ctx, case):
    preparer = Preparer()
    client = page_for(ctx, preparer)
    form = form_of(client)
    assert client.post("/prepare", data={**form, "form_token": "wrong"}).status_code == 403
    assert client.post("/prepare", data={"seed": form["seed"]}).status_code == 403
    assert preparer.calls == []


@pytest.mark.parametrize("seed", ["-1", "abc", str(2**31)])
def test_a_bad_seed_is_refused(ctx, case, seed):
    preparer = Preparer()
    client = page_for(ctx, preparer)
    reply = client.post("/prepare", data={**form_of(client), "seed": seed})
    assert reply.status_code == 422 and preparer.calls == []


def test_prepare_is_not_available_when_deployed(settings, make_ctx, case):
    deployed = make_ctx(settings.model_copy(update={"deployment": "aws"}))
    preparer = Preparer()
    client = page_for(deployed, preparer, SignedIn())
    assert "Prepare" not in client.get("/mark").text
    token = form_of_token(client)
    reply = client.post("/prepare", data={"seed": "1", "form_token": token})
    assert reply.status_code == 404 and preparer.calls == []


def form_of_token(client: TestClient) -> str:
    client.get("/mark")
    return client.cookies.get("form_token") or ""


def test_a_stopped_prepare_offers_to_finish_with_the_same_seed(ctx, case):
    stopped = BuildResult(built=1, picked=3, eligible=9, stopped="Stopped: out of money.", left=2)
    preparer = Preparer(stopped)
    client = page_for(ctx, preparer)
    form = form_of(client)
    reply = client.post("/prepare", data=form)
    assert re.search(rf'name="seed" value="{form["seed"]}"', reply.text)
    assert "Finish these" in reply.text
    # Pressing it asks for the same seed, which the step treats as the same pick.
    again = re.search(r'name="form_token" value="([^"]+)"', reply.text)
    assert again
    client.post("/prepare", data={"seed": form["seed"], "form_token": again.group(1)})
    assert [seed for _, _, seed in preparer.calls] == [int(form["seed"])] * 2


def test_a_finished_prepare_does_not_offer_to_finish(ctx, case):
    client = page_for(ctx, Preparer(BuildResult(built=3, picked=3, eligible=9)))
    assert "Finish these" not in client.post("/prepare", data=form_of(client)).text


def test_a_second_prepare_while_one_is_running_is_refused(ctx, case):
    seen: list[int] = []

    class Reentrant(Preparer):
        def __call__(self, profile, n, seed):
            seen.append(client.post("/prepare", data=form).status_code)  # a second press
            return super().__call__(profile, n, seed)

    preparer = Reentrant()
    client = page_for(ctx, preparer)
    form = form_of(client)
    assert client.post("/prepare", data=form).status_code == 200
    assert seen == [409] and len(preparer.calls) == 1
    # The lock is let go afterwards, so the next press runs.
    assert client.post("/prepare", data=form).status_code == 200
