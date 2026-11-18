"""The review web app. Pages are built on the server, with every value escaped."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import Response

from why_now.ai.budget import Meter
from why_now.domain import Profile
from why_now.profile import ProfileError
from why_now.settings import Settings
from why_now.store import Store
from why_now.testset.packs import BuildResult
from why_now.web.auth import Authenticator, LocalAuth, SignInPages
from why_now.web.run_now import RunNow
from why_now.workspace import Workspace
from why_now.workspace.settings_doc import effective_settings

HERE = Path(__file__).parent

# Pages load nothing but our own style sheet, and run no script, so text from a job ad
# could not run even if it got past the escaping. Forms may only send to this app.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)


@dataclass
class AppContext:
    # The settings file and the environment. A page uses `current()`, which puts the settings
    # stored in the workspace on top.
    settings: Settings
    store: Store
    meter: Meter
    clock: Callable[[], datetime]
    # The workspace's profiles, by id. Filled by `current()` on each visit, never kept.
    profiles: dict[str, Profile] = field(default_factory=dict)
    # Prepares companies for a profile: (profile, how many, seed). Only given on one's own
    # computer, where the keys and the budget are the reviewer's own.
    prepare: Callable[[Profile, int, int], BuildResult] | None = None
    # The file a profile was started from, by profile id. Saving the profile page also writes it.
    profile_files: dict[str, Path] = field(default_factory=dict)
    # Drafts a profile from a description, with one paid call. Only on one's own computer.
    draft: Callable[[str], Profile] | None = None
    # Starts runs from the Run now page. Only on one's own computer.
    runner: RunNow | None = None
    # Where the setup page looks for keys. None means this process's environment.
    env: Mapping[str, str] | None = None

    def current(self) -> "AppContext":
        """This context as it is for one visit: the profiles and the stored settings are
        read from the workspace now, so an upload or a change shows without a restart."""
        workspace = Workspace(self.store)
        profiles: dict[str, Profile] = {}
        for profile_id in workspace.profile_ids():
            try:
                profile = workspace.profile(profile_id)
            except ProfileError:
                continue  # a profile that cannot be read is left out, not a page that fails
            if profile is not None:
                profiles[profile_id] = profile
        return replace(
            self, settings=effective_settings(self.settings, self.store), profiles=profiles
        )


def create_app(ctx: AppContext, auth: Authenticator) -> FastAPI:
    if isinstance(auth, LocalAuth) and ctx.settings.deployment != "local":
        raise ValueError("local login is for use on one's own machine, not when deployed")

    from why_now.web import routes_control, routes_marking, routes_repeat, routes_review

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx
    app.state.auth = auth
    app.state.templates = Environment(
        loader=FileSystemLoader(HERE / "templates"),
        autoescape=select_autoescape(["html"], default=True),
    )
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(routes_review.router)
    app.include_router(routes_marking.router)
    app.include_router(routes_repeat.router)
    app.include_router(routes_control.router)
    if isinstance(auth, SignInPages):
        app.include_router(auth.router)

    @app.middleware("http")
    async def private_headers(request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return app
