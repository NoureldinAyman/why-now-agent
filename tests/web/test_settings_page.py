"""The settings page: a form for the everyday limits, and the rest shown read-only."""

import re

import pytest
from fastapi.testclient import TestClient

from why_now.web.app import create_app
from why_now.web.auth import LocalAuth
from why_now.workspace.settings_doc import effective_settings

from .conftest import LOCAL


def token(client: TestClient) -> str:
    found = re.search(r'name="form_token" value="([^"]+)"', client.get("/settings").text)
    assert found, "the settings page has no form token"
    return found.group(1)


def save(client: TestClient, **fields):
    data = {"form_token": token(client), **{k: str(v) for k, v in fields.items()}}
    return client.post("/settings", data=data, follow_redirects=False)


def shown(client: TestClient, ctx):
    return effective_settings(ctx.settings, ctx.store)


def test_the_page_has_a_form_for_the_everyday_limits_with_their_current_values(client, settings):
    page = client.get("/settings").text
    for name in ("short_list_size", "hide_days", "judged_no_shown", "prepare_batch"):
        assert f'name="{name}"' in page, name
    assert f'name="short_list_size" value="{settings.short_list_size}"' in page


def test_every_other_setting_is_shown_with_no_input(client):
    page = client.get("/settings").text
    for name in ("budget_limit_usd", "loop_budget_usd", "new_ad_days", "tries_per_run"):
        assert f"<code>{name}</code>" in page
        assert f'name="{name}"' not in page


def test_a_saved_change_shows_on_the_page_and_in_the_settings(client, ctx):
    reply = save(client, short_list_size=4, hide_days=30, judged_no_shown=2, prepare_batch=15)

    assert reply.status_code == 303
    now = shown(client, ctx)
    assert (now.short_list_size, now.hide_days, now.judged_no_shown, now.prepare_batch) == (
        4, 30, 2, 15,
    )  # fmt: skip
    assert 'name="short_list_size" value="4"' in client.get("/settings").text
    assert ctx.settings.short_list_size == 10  # the file's own value is untouched


def test_saving_values_equal_to_the_files_stores_nothing(client, ctx, settings):
    save(client, short_list_size=settings.short_list_size)
    assert ctx.store.get("settings", "overrides") in (None, {})


@pytest.mark.parametrize(
    "name, value",
    [
        ("budget_limit_usd", 5000),
        ("budget_warning_usd", 4000),
        ("loop_budget_usd", 1000),
        ("new_ad_days", 365),
        ("tries_per_run", 40),
        ("research_per_day", 500),
        ("workspace_path", "elsewhere"),
        ("editable_limits", "{}"),
    ],
)
def test_a_setting_that_is_read_only_is_refused_whatever_is_posted(client, ctx, name, value):
    reply = save(client, short_list_size=5, **{name: value})

    assert reply.status_code == 422
    assert name in reply.text  # the page says which one
    assert shown(client, ctx) == ctx.settings  # nothing at all was stored, not even the valid part


@pytest.mark.parametrize(
    "name, value",
    [
        ("short_list_size", 0),
        ("short_list_size", 100_000),
        ("hide_days", -5),
        ("judged_no_shown", 100_000),
        ("prepare_batch", 0),
        ("short_list_size", "many"),
        ("short_list_size", ""),
    ],
)
def test_a_value_out_of_bounds_is_refused(client, ctx, name, value):
    reply = save(client, **{name: value})
    assert reply.status_code == 422
    assert shown(client, ctx) == ctx.settings


def test_reason_choices_are_one_per_line(client, ctx):
    save(client, reason_chips="too big\n  too small \n\nbad timing\n")
    assert shown(client, ctx).reason_chips == ["too big", "too small", "bad timing"]


def test_reason_choices_are_escaped_in_the_box(client, ctx):
    save(client, reason_chips="<script>alert(1)</script>")
    page = client.get("/settings").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_a_profile_is_switched_on_for_the_night_by_ticking_it(client, ctx, profile):
    page = client.get("/settings").text
    assert f'name="nightly_profiles" value="{profile.id}"' in page
    assert f'value="{profile.id}" checked' not in page

    save(client, nightly_listed=1, nightly_profiles=profile.id)
    assert shown(client, ctx).nightly_profiles == [profile.id]
    assert f'value="{profile.id}" checked' in client.get("/settings").text

    save(client, nightly_listed=1)  # nothing ticked: every profile is off
    assert shown(client, ctx).nightly_profiles == []


def test_a_profile_that_is_not_in_the_workspace_cannot_be_switched_on(client, ctx):
    reply = save(client, nightly_listed=1, nightly_profiles="nowhere")
    assert reply.status_code == 422
    assert shown(client, ctx).nightly_profiles == []


def test_posting_other_limits_leaves_the_night_list_alone(client, ctx, profile):
    save(client, nightly_listed=1, nightly_profiles=profile.id)
    save(client, short_list_size=6)
    assert shown(client, ctx).nightly_profiles == [profile.id]


def test_saving_needs_the_login_and_the_form_token(ctx):
    anonymous = TestClient(create_app(ctx, LocalAuth()), client=("203.0.113.9", 5000))
    assert anonymous.post("/settings", data={"short_list_size": "3"}).status_code == 401
    client = TestClient(create_app(ctx, LocalAuth()), client=LOCAL, base_url="http://localhost")
    assert client.post("/settings", data={"short_list_size": "3"}).status_code == 403
    assert effective_settings(ctx.settings, ctx.store) == ctx.settings


def test_the_form_works_on_aws_too(settings, make_ctx):
    from tests.web.test_workspace_profiles import SignedIn

    ctx = make_ctx(settings.model_copy(update={"deployment": "aws"}))
    client = TestClient(create_app(ctx, SignedIn()))
    assert save(client, short_list_size=3).status_code == 303
    assert effective_settings(ctx.settings, ctx.store).short_list_size == 3
