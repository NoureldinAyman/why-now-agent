"""The review web app. Pages are built on the server, with every value escaped."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import Response

from why_now.ai.budget import Meter
from why_now.domain import Profile
from why_now.settings import Settings
from why_now.store import Store
from why_now.web.auth import Authenticator, LocalAuth

HERE = Path(__file__).parent

# Pages load nothing but our own style sheet, and run no script, so text from a job ad
# could not run even if it got past the escaping. Forms may only send to this app.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)


@dataclass
class AppContext:
    settings: Settings
    store: Store
    profiles: dict[str, Profile]
    meter: Meter
    clock: Callable[[], datetime]


def create_app(ctx: AppContext, auth: Authenticator) -> FastAPI:
    if isinstance(auth, LocalAuth) and ctx.settings.deployment != "local":
        raise ValueError("local login is for use on one's own machine, not when deployed")

    from why_now.web import routes_marking, routes_repeat

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx
    app.state.auth = auth
    app.state.templates = Environment(
        loader=FileSystemLoader(HERE / "templates"),
        autoescape=select_autoescape(["html"], default=True),
    )
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(routes_marking.router)
    app.include_router(routes_repeat.router)

    @app.middleware("http")
    async def private_headers(request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return app
