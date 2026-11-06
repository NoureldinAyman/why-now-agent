import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from why_now.web.app import create_app
from why_now.web.auth import LocalAuth


def request_from(client: tuple[str, int] | None, host: str = "localhost") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/mark",
            "headers": [(b"host", host.encode())],
            "client": client,
        }
    )


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_local_auth_accepts_this_machine(address):
    assert LocalAuth().current_user(request_from((address, 5000))) is not None


@pytest.mark.parametrize("address", ["192.168.1.20", "10.0.0.5", "203.0.113.9", "::ffff:10.0.0.5"])
def test_local_auth_refuses_other_machines(address):
    assert LocalAuth().current_user(request_from((address, 5000))) is None


def test_local_auth_refuses_a_request_with_no_known_sender():
    assert LocalAuth().current_user(request_from(None)) is None


def test_local_auth_refuses_a_page_reached_under_another_name():
    # A web page that makes the browser look up its own name as 127.0.0.1 gets here.
    assert LocalAuth().current_user(request_from(("127.0.0.1", 5000), host="evil.test")) is None
    assert LocalAuth().current_user(request_from(("127.0.0.1", 5000), host="127.0.0.1:8000"))
    assert LocalAuth().current_user(request_from(("::1", 5000), host="[::1]:8000"))


def test_every_page_is_closed_to_other_machines(ctx, case):
    far = TestClient(create_app(ctx, LocalAuth()), client=("203.0.113.9", 5000))
    assert far.get("/mark").status_code == 401
    assert far.get("/mark/progress").status_code == 401
    assert far.post(f"/mark/{case.case_id}", data={}).status_code == 401


def test_app_refuses_local_auth_when_deployed_on_aws(settings, make_ctx):
    deployed = settings.model_copy(update={"deployment": "aws"})
    with pytest.raises(ValueError, match="deployed"):
        create_app(make_ctx(deployed), LocalAuth())


def test_another_authenticator_can_be_used_when_deployed(settings, make_ctx, case):
    class Signed:
        def current_user(self, request: Request) -> str | None:
            return "reviewer" if request.headers.get("x-test-user") == "yes" else None

    deployed = settings.model_copy(update={"deployment": "aws"})
    client = TestClient(create_app(make_ctx(deployed), Signed()))
    assert client.get("/mark").status_code == 401
    assert client.get("/mark", headers={"x-test-user": "yes"}).status_code == 200
