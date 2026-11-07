"""Signing in through Cognito, Amazon's ready-made login, with a fake Cognito.

The fake answers the two addresses the app calls: the token address, which swaps a
one-time code for a signed ID token, and the address that lists Cognito's public keys.
"""

import base64
import hashlib
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from why_now.settings import Settings
from why_now.web.app import create_app
from why_now.web.auth_cognito import SESSION_COOKIE, CognitoAuth

SECRET = "s" * 40
APP = "https://app.test"
LOGIN = "https://login.test"
REGION = "eu-central-1"
POOL = "eu-central-1_test"
CLIENT_ID = "client-123"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"


@pytest.fixture(scope="module")
def cognito_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": "cognito-1"}, private=True)


@pytest.fixture(scope="module")
def other_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": "cognito-1"}, private=True)


@pytest.fixture(scope="module")
def next_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": "cognito-2"}, private=True)


class FakeCognito:
    """Hands out one ID token per code, signed with its key unless told otherwise."""

    def __init__(self, key: RSAKey):
        self.key = key
        self.codes: dict[str, tuple[str, dict[str, Any], RSAKey]] = {}

    def issue(self, challenge: str, claims: dict[str, Any], key: RSAKey | None = None) -> str:
        code = secrets.token_urlsafe(8)
        self.codes[code] = (challenge, claims, key or self.key)
        return code

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url == f"{ISSUER}/.well-known/jwks.json":
            return httpx.Response(200, json=KeySet([self.key]).as_dict(private=False))
        if request.url == f"{LOGIN}/oauth2/token" and request.method == "POST":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            found = self.codes.pop(form.get("code", ""), None)
            if (
                found is None
                or form.get("grant_type") != "authorization_code"
                or form.get("client_id") != CLIENT_ID
                or form.get("redirect_uri") != f"{APP}/auth/callback"
                or _challenge(form.get("code_verifier", "")) != found[0]
            ):
                return httpx.Response(400, json={"error": "invalid_grant"})
            _, claims, key = found
            token = jwt.encode({"alg": "RS256", "kid": key.kid}, claims, key)
            return httpx.Response(200, json={"id_token": token, "token_type": "Bearer"})
        return httpx.Response(404)


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@pytest.fixture
def settings_aws(settings) -> Settings:
    return settings.model_copy(
        update={
            "deployment": "aws",
            "aws_region": REGION,
            "cognito_domain": LOGIN,
            "cognito_user_pool_id": POOL,
            "cognito_client_id": CLIENT_ID,
        }
    )


@pytest.fixture
def fake(cognito_key) -> FakeCognito:
    return FakeCognito(cognito_key)


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def anonymous_client_cognito(settings_aws, make_ctx, fake, clock) -> TestClient:
    http = httpx.Client(transport=httpx.MockTransport(fake.handle))
    auth = CognitoAuth(settings_aws, SECRET, http=http, clock=clock)
    return TestClient(create_app(make_ctx(settings_aws), auth), base_url=APP)


def claims(clock: Clock, **overrides: Any) -> dict[str, Any]:
    now = int(clock())
    return {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "token_use": "id",
        "sub": "user-1",
        "cognito:username": "reviewer",
        "iat": now,
        "exp": now + 3600,
    } | overrides


def start_login(client: TestClient) -> dict[str, str]:
    """Visit /login the way a browser does, and read what it sends to Cognito."""
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 303
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


SignIn = Callable[..., httpx.Response]


@pytest.fixture
def sign_in(anonymous_client_cognito, fake, clock) -> SignIn:
    def go(key: RSAKey | None = None, state: str | None = None, **overrides: Any):
        sent = start_login(anonymous_client_cognito)
        token_claims = claims(clock, nonce=sent["nonce"]) | overrides
        code = fake.issue(sent["code_challenge"], token_claims, key)
        return anonymous_client_cognito.get(
            "/auth/callback",
            params={"code": code, "state": state or sent["state"]},
            follow_redirects=False,
        )

    return go


@pytest.fixture
def client_cognito(anonymous_client_cognito, sign_in) -> TestClient:
    assert sign_in().status_code == 303
    return anonymous_client_cognito


def test_login_redirects_to_cognito(anonymous_client_cognito):
    page = anonymous_client_cognito.get("/mark", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/login"

    response = anonymous_client_cognito.get("/login", follow_redirects=False)
    target = urlsplit(response.headers["location"])
    sent = parse_qs(target.query)
    assert f"{target.scheme}://{target.netloc}{target.path}" == f"{LOGIN}/oauth2/authorize"
    assert sent["response_type"] == ["code"]
    assert sent["client_id"] == [CLIENT_ID]
    assert sent["redirect_uri"] == [f"{APP}/auth/callback"]
    assert "openid" in sent["scope"][0].split()
    assert sent["code_challenge_method"] == ["S256"]
    assert sent["state"][0] and sent["nonce"][0] and sent["code_challenge"][0]


def test_sending_a_form_while_signed_out_is_refused_not_redirected(anonymous_client_cognito):
    response = anonymous_client_cognito.post("/mark/case-1", data={}, follow_redirects=False)
    assert response.status_code == 401


def test_signing_in_opens_the_marking_page(client_cognito, case):
    page = client_cognito.get("/mark")
    assert page.status_code == 200
    assert "We are hiring sales staff." in page.text


def test_session_cookie_is_secure_and_same_site(sign_in):
    cookie = sign_in().headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "Secure" in cookie and "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()


@pytest.mark.parametrize(
    "bad",
    [
        {"key": "other"},
        {"aud": "another-client"},
        {"iss": "https://cognito-idp.eu-central-1.amazonaws.com/another-pool"},
        {"exp": 1},
        {"nonce": "not-the-one-sent"},
        {"token_use": "access"},
    ],
    ids=["wrong-key", "wrong-client", "wrong-pool", "expired", "wrong-nonce", "access-token"],
)
def test_bad_token_is_refused(anonymous_client_cognito, sign_in, other_key, bad):
    response = sign_in(key=other_key) if bad.get("key") == "other" else sign_in(**bad)
    assert response.status_code == 401
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")
    assert anonymous_client_cognito.get("/mark", follow_redirects=False).status_code == 303


def test_sign_in_still_works_after_cognito_changes_its_keys(sign_in, fake, next_key):
    assert sign_in().status_code == 303
    fake.key = next_key  # the app has the old keys saved by now
    assert sign_in().status_code == 303


def test_a_callback_with_the_wrong_state_is_refused(sign_in):
    response = sign_in(state="made-up")
    assert response.status_code == 401
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")


def test_a_callback_without_a_login_started_here_is_refused(anonymous_client_cognito):
    response = anonymous_client_cognito.get(
        "/auth/callback", params={"code": "c", "state": "s"}, follow_redirects=False
    )
    assert response.status_code == 401


def test_a_forged_session_cookie_is_refused(anonymous_client_cognito, settings_aws):
    forger = CognitoAuth(settings_aws, "f" * 40)
    anonymous_client_cognito.cookies.set(SESSION_COOKIE, forger.session_value("reviewer"))
    assert anonymous_client_cognito.get("/mark", follow_redirects=False).status_code == 303


def test_session_ends_after_the_set_hours(client_cognito, settings_aws, clock):
    assert client_cognito.get("/mark", follow_redirects=False).status_code == 200
    clock.now += settings_aws.session_hours * 3600 + 1
    assert client_cognito.get("/mark", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("secret", ["", " " * 40, "short"])
def test_session_secret_is_required(settings_aws, secret):
    with pytest.raises(ValueError, match="session secret"):
        CognitoAuth(settings_aws, secret)


def test_login_settings_are_required(settings_aws):
    with pytest.raises(ValueError, match="cognito_domain"):
        CognitoAuth(settings_aws.model_copy(update={"cognito_domain": ""}), SECRET)
