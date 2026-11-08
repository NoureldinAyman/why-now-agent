"""Invented data for the sample run: companies, job ads, a profile and scripted answers.

Everything here is made up. No company, product or ad is real. The sample run uses it
to show the whole daily flow with no keys, no network and no cost.
"""

import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import httpx
from pydantic import BaseModel

from why_now.ai import Models
from why_now.ai.budget import Meter
from why_now.day_result import DayResult
from why_now.domain import Answer, FitQuestion, JobAd, Profile
from why_now.pipeline.day import run_day
from why_now.pipeline.reader import PageReader
from why_now.run_context import RunContext
from why_now.sample.models import SCRIPTED, Script, ScriptedResearch
from why_now.settings import Settings
from why_now.sources.boards import BoardList
from why_now.store.local import LocalStore
from why_now.tracing import LocalLogTracer, UnitCounter
from why_now.workspace import Workspace

SOURCE = "sample"
SAMPLE_PROFILE_ID = "sample-profile"
# The sentence every strong sample ad contains, so the sample writer can quote it.
HIRING_SENTENCE = "We are hiring five sales reps to open our new regional office"
OFFICE_SENTENCE = "open our new regional office"


class SampleCompany(BaseModel):
    name: str
    level: float  # chance of yes the sample answerer gives, for every question
    ad_age_days: int = 1


def _company(name: str, level: float, age: int = 1) -> SampleCompany:
    return SampleCompany(name=name, level=level, ad_age_days=age)


# Twelve good companies, so the short list is full and two spill on to the more list;
# one weak company that only reaches the more list; one agency that is dropped at the
# quick look; and one whose only ad is too old to be new.
COMPANIES = [
    *(
        _company(name, round(0.95 - 0.03 * i, 2))
        for i, name in enumerate(
            [
                "Alder Works",
                "Birchwood Systems",
                "Cedar Quay",
                "Dunmore Supply",
                "Elmstead Tools",
                "Fernhill Labs",
                "Garnet Freight",
                "Hollis Print",
                "Ironbridge Foods",
                "Juniper Optics",
                "Kestrel Cabling",
                "Larkspur Textiles",
            ]
        )
    ),
    _company("Marlow Trading", 0.35),
    _company("Nettle Staffing Agency", 0.05),
    _company("Orchard Lane Press", 0.9, age=40),
]


def board_name(company: SampleCompany) -> str:
    return re.sub(r"[^a-z0-9]", "", company.name.casefold())


def sample_profile() -> Profile:
    return Profile(
        id=SAMPLE_PROFILE_ID,
        product_name="Sample Product",
        product_description="An invented tool that helps new salespeople practise.",
        users="Invented sales teams.",
        search_words=["account executive"],
        quick_look_questions=[
            FitQuestion(id="hires-for-itself", text="Is the company hiring salespeople for itself?")
        ],
        fit_questions=[
            FitQuestion(
                id="not-an-agency",
                text="Is the company hiring for itself and not for clients?",
                kind="required",
            ),
            FitQuestion(id="new-team", text="Is the company building a new sales team?"),
        ],
        why_now="A new sales team or office is being set up.",
    )


class SampleSource:
    """A job source whose ads are invented, dated relative to the day it is read."""

    name = SOURCE

    def __init__(self, companies: list[SampleCompany] = COMPANIES):
        self.companies = {board_name(c): c for c in companies}

    def fetch_ads(self, board: str, today: date) -> list[JobAd]:
        company = self.companies[board]
        published = datetime.combine(today - timedelta(days=company.ad_age_days), time(8), UTC)
        text = f"{company.name} is hiring. {HIRING_SENTENCE}. " + (
            "We place candidates with clients as a staffing agency."
            if "Agency" in company.name
            else ""
        )
        return [
            JobAd(
                source=SOURCE,
                board=board,
                ad_id="1",
                company_name=company.name,
                title="Account Executive",
                location="Invented City",
                country=None,
                language="en",
                text=text,
                url=f"https://sample.invalid/{board}/1",
                published_at=published,
                first_seen=today,
            )
        ]


class SampleAnswerer:
    """Gives every question the chance of yes set for the company whose name it finds."""

    model = f"{SCRIPTED}-answerer"
    answer_key = model

    def __init__(self, companies: list[SampleCompany] = COMPANIES):
        self.companies = companies

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        level = next((c.level for c in self.companies if c.name in state), 0.5)
        return [Answer(question_id=q.id, probability=level, model=self.model) for q in questions]


class SampleWriter:
    """Writes a brief that quotes the first job ad in the evidence it is given."""

    model = f"{SCRIPTED}-writer"
    answer_key = model

    def structured[M: BaseModel](
        self, *, system: str, untrusted: str, schema: type[M], category: str
    ) -> M:
        source = re.search(r"\[(ad-\w+)\]", untrusted)
        if source is None:
            raise ValueError("the sample writer needs a job ad in the evidence")
        draft = {
            "why_now": {
                "text": "The company is hiring a group of sales reps now.",
                "quote": HIRING_SENTENCE,
                "source_id": source.group(1),
            },
            "claims": [
                {
                    "text": "It is opening a new regional office.",
                    "quote": OFFICE_SENTENCE,
                    "source_id": source.group(1),
                }
            ],
        }
        return schema.model_validate(draft)


def sample_models() -> Models:
    answerer = SampleAnswerer()
    return Models(
        quick_look=answerer,
        judge=answerer,
        writer=SampleWriter(),
        research=ScriptedResearch(Script()),
    )


def run_sample(folder: Path, now: datetime) -> DayResult:
    """One whole daily run on invented data, kept in `folder`. Needs no keys and costs nothing."""
    # The two limits are set here so the story below holds whatever the defaults become.
    settings = Settings(
        workspace_path=folder, request_delay_seconds=0, short_list_size=10, research_per_day=12
    )
    store = LocalStore(folder)
    profile = sample_profile()
    source = SampleSource()
    names = [board_name(c) for c in COMPANIES]

    def clock() -> datetime:
        return now

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the sample run reads no web pages")

    ctx = RunContext(
        settings=settings,
        store=store,
        sources=[source],
        boards={SOURCE: BoardList(Workspace(store), SOURCE, names, settings)},
        models=sample_models(),
        reader=PageReader(
            httpx.Client(trust_env=False, transport=httpx.MockTransport(refuse)), settings
        ),
        meter=Meter(store, settings, clock),
        tracer=LocalLogTracer(folder / "traces", UnitCounter(store, settings, clock), clock),
        clock=clock,
    )
    return run_day(ctx, profile, now.date())
