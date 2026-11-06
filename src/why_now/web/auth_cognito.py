"""Signing in through Cognito, Amazon's ready-made login, for the app deployed on AWS.

The app never sees a password. `/login` sends the browser to Cognito's sign-in page.
Cognito sends it back to `/auth/callback` with a one-time code, which the app swaps for
an ID token over a direct call to Cognito. The token's signature is checked against
Cognito's published keys, and its issuer, audience, expiry, use and nonce are checked
too. Only then does the app set its own session cookie, signed with the session secret.

Three values make a stolen or replayed step useless: `state` ties the callback to a
login started in this browser, `nonce` ties the ID token to that login, and the PKCE
code verifier means a code taken from the address bar can't be swapped by anyone else.
"""

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter
from httpx import USE_CLIENT_DEFAULT
from itsdangerous import BadData, TimestampSigner, URLSafeTimedSerializer
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from why_now.settings import Settings

SESSION_COOKIE = "why_now_session"
LOGIN_COOKIE = "why_now_login"
CALLBACK_PATH = "/auth/callback"
AFTER_SIGN_IN = "/mark"
_REQUIRED = ("aws_region", "cognito_domain", "cognito_user_pool_id", "cognito_client_id")


class CognitoAuth:
    """An Authenticator for the deployed app, with its own sign-in pages."""

    login_path = "/login"

    def __init__(
        self,
        settings: Settings,
        session_secret: str,
        *,
        client_secret: str | None = None,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ):
        if len(session_secret.strip()) < settings.session_secret_min_chars:
            raise ValueError(
                f"a session secret of at least {settings.session_secret_min_chars} "
                "characters is required on AWS"
            )
        for name in _REQUIRED:
            if not getattr(settings, name):
                raise ValueError(f"{name} must be set to sign in through Cognito")
        self.settings = settings
        self._client_secret = client_secret
        self._client = http
        self._clock = clock
        self._keys: KeySet | None = None
        signer = _signer_using(clock)
        self._sessions = URLSafeTimedSerializer(session_secret, "session", signer=signer)
        self._logins = URLSafeTimedSerializer(session_secret, "login", signer=signer)

        self.router = APIRouter()
        self.router.add_api_route(self.login_path, self.login, methods=["GET"])
        self.router.add_api_route(CALLBACK_PATH, self.callback, methods=["GET"])

    def current_user(self, request: Request) -> str | None:
        value = request.cookies.get(SESSION_COOKIE)
        if not value:
            return None
        try:
            data = self._sessions.loads(value, max_age=self.settings.session_hours * 3600)
        except BadData:
            return None
        user = data.get("user") if isinstance(data, dict) else None
        return user if isinstance(user, str) and user else None

    def session_value(self, user: str) -> str:
        """The signed cookie value that marks `user` as signed in."""
        return self._sessions.dumps({"user": user})

    def login(self, request: Request) -> Response:
        started = {k: secrets.token_urlsafe() for k in ("state", "nonce", "verifier")}
        params = {
            "response_type": "code",
            "client_id": self.settings.cognito_client_id,
            "redirect_uri": _callback_url(request),
            "scope": "openid",
            "state": started["state"],
            "nonce": started["nonce"],
            "code_challenge": _challenge(started["verifier"]),
            "code_challenge_method": "S256",
        }
        response = RedirectResponse(
            f"{self._domain}/oauth2/authorize?{urlencode(params)}", status_code=303
        )
        _set_cookie(
            response,
            LOGIN_COOKIE,
            self._logins.dumps(started),
            self.settings.login_minutes * 60,
            path=CALLBACK_PATH,
        )
        return response

    def callback(self, request: Request, code: str = "", state: str = "") -> Response:
        try:
            started = self._logins.loads(
                request.cookies.get(LOGIN_COOKIE, ""), max_age=self.settings.login_minutes * 60
            )
        except BadData:
            return _refused()
        if not code or not hmac.compare_digest(state.encode(), started["state"].encode()):
            return _refused()
        try:
            user = self._user_from(code, started, _callback_url(request))
        except (httpx.HTTPError, JoseError, KeyError, TypeError, ValueError):
            return _refused()
        response = RedirectResponse(AFTER_SIGN_IN, status_code=303)
        _set_cookie(
            response,
            SESSION_COOKIE,
            self.session_value(user),
            self.settings.session_hours * 3600,
            path="/",
        )
        response.delete_cookie(
            LOGIN_COOKIE, path=CALLBACK_PATH, secure=True, httponly=True, samesite="lax"
        )
        return response

    def _user_from(self, code: str, started: dict[str, str], callback_url: str) -> str:
        client_id = self.settings.cognito_client_id
        reply = self._http().post(
            f"{self._domain}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": callback_url,
                "code_verifier": started["verifier"],
            },
            auth=(client_id, self._client_secret) if self._client_secret else USE_CLIENT_DEFAULT,
        )
        reply.raise_for_status()
        token = self._verified(reply.json()["id_token"])
        checks: dict[str, Any] = {
            "iss": {"essential": True, "value": self._issuer},
            "aud": {"essential": True, "value": client_id},
            "exp": {"essential": True},
            "token_use": {"essential": True, "value": "id"},
            "nonce": {"essential": True, "value": started["nonce"]},
            "cognito:username": {"essential": True},
        }
        jwt.JWTClaimsRegistry(now=lambda: int(self._clock()), **checks).validate(token.claims)
        user = token.claims["cognito:username"]
        if not isinstance(user, str) or not user:
            raise ValueError("the token names no user")
        return user

    def _verified(self, id_token: str) -> jwt.Token:
        """The token, if Cognito signed it. Its claims are checked separately."""
        had_keys = self._keys is not None
        try:
            return jwt.decode(id_token, self._public_keys(), algorithms=["RS256"])
        except (JoseError, KeyError, ValueError):
            if not had_keys:
                raise
            # Cognito may have changed its keys since they were saved. Fetch them again.
            self._keys = None
            return jwt.decode(id_token, self._public_keys(), algorithms=["RS256"])

    def _public_keys(self) -> KeySet:
        if self._keys is None:
            reply = self._http().get(f"{self._issuer}/.well-known/jwks.json")
            reply.raise_for_status()
            self._keys = KeySet.import_key_set(reply.json())
        return self._keys

    def _http(self) -> httpx.Client:
        # Made on first use: setting up a network client is slow, and most requests
        # only read the session cookie.
        if self._client is None:
            self._client = httpx.Client(timeout=self.settings.page_timeout_seconds)
        return self._client

    @property
    def _domain(self) -> str:
        return self.settings.cognito_domain.rstrip("/")

    @property
    def _issuer(self) -> str:
        s = self.settings
        return f"https://cognito-idp.{s.aws_region}.amazonaws.com/{s.cognito_user_pool_id}"


def _signer_using(clock: Callable[[], float]) -> type[TimestampSigner]:
    class ClockSigner(TimestampSigner):
        def get_timestamp(self) -> int:
            return int(clock())

    return ClockSigner


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _callback_url(request: Request) -> str:
    # Always https: Lambda's web address is https, and Cognito only sends codes back
    # to the addresses registered with it, so a forged Host header gains nothing.
    return str(request.url.replace(scheme="https", path=CALLBACK_PATH, query="", fragment=""))


def _set_cookie(response: Response, name: str, value: str, max_age: int, path: str) -> None:
    response.set_cookie(
        name, value, max_age=max_age, path=path, secure=True, httponly=True, samesite="lax"
    )


def _refused() -> Response:
    return PlainTextResponse("Sign-in failed. Start again from /login.", status_code=401)
