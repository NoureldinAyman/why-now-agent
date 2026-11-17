"""A small fake world for evaluation tests: companies, packs, marks and a pretend AI.

Everything here is free and offline. Each test says what happens to a company by name,
for example `quick=0.9` means the quick look thinks Acme is a likely fit.
"""

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Literal

from why_now.ai import BadModelOutput
from why_now.domain import (
    Answer,
    CaseRecord,
    Company,
    EvidencePack,
    FitQuestion,
    JobAd,
    Mark,
    Profile,
    Source,
)
from why_now.evaluation.evaluate import EvalRun
from why_now.sample.models import Script, scripted_models
from why_now.settings import Settings
from why_now.workspace import Workspace

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


class ByCompany:
    """A pretend AI. It finds which company's name is in the text it is shown and answers every
    question with that company's number. A company set to `None` gets an unusable answer."""

    def __init__(self, by_company: Mapping[str, float | None], answer_key: str = "fake-1"):
        self.model = answer_key
        self.answer_key = answer_key
        self.by_company = by_company

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        for name, p in self.by_company.items():
            if name in state:
                if p is None:
                    raise BadModelOutput(f"no usable answer for {name}")
                return [
                    Answer(question_id=q.id, probability=p, model=self.model) for q in questions
                ]
        raise AssertionError(f"no company from {list(self.by_company)} is in the text shown")


class Sequence:
    """A pretend AI whose answer changes on every call. It gives each number in turn, the same
    number for every question, and starts again from the first when it runs out."""

    def __init__(self, numbers: list[float], answer_key: str = "wobbly-1"):
        self.model = answer_key
        self.answer_key = answer_key
        self.numbers = numbers
        self.calls = 0

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        p = self.numbers[self.calls % len(self.numbers)]
        self.calls += 1
        return [Answer(question_id=q.id, probability=p, model=self.model) for q in questions]


class Handle:
    def step(self, name, input, output):
        pass

    def score(self, name, value):
        pass


class Tracer:
    """A tracer that keeps nothing."""

    @contextmanager
    def trace(self, name, **kwargs):
        yield Handle()


def add_case(
    workspace: Workspace,
    name: str,
    pile: Literal["practice", "check", "final"],
    answer: Literal["yes", "no", "cant_tell"] | None,
) -> str:
    """Save one company as a test case in `pile`, with its frozen pack and the reviewer's mark.
    The company's key is `name`, and its text says `name`, so `ByCompany` can find it."""
    profile_id = workspace.require_profile()
    case_id = f"case-{name}"
    text = f"{name} is hiring salespeople."
    ad = JobAd(
        source="example-source",
        board=name,
        ad_id=name,
        company_name=name,
        title="Sales",
        location="Berlin",
        country=None,
        language=None,
        text=text,
        url="https://example.com/x",
        published_at=NOW,
        first_seen=date(2026, 11, 2),
    )
    company = Company(key=name, name=name, ads=[ad], total_open_jobs=10)
    pack_id = f"pack-{name}"
    workspace.save_case(
        CaseRecord(
            case_id=case_id,
            profile_id=profile_id,
            company_key=name,
            pack_id=pack_id,
            seed=1,
            pile=pile,
        ),
        company,
    )
    workspace.save_pack(
        EvidencePack(
            pack_id=pack_id,
            profile_id=profile_id,
            company_key=name,
            company_name=name,
            created_at=NOW,
            sources=[
                Source(
                    id="s1", kind="job_ad", text=text, url="https://example.com/x", fetched_at=NOW
                )
            ],
            relevant_ad_count=1,
            total_open_jobs=10,
            research_steps=1,
        )
    )
    if answer is not None:  # None leaves the case not yet marked
        workspace.save_mark(Mark(case_id=case_id, answer=answer, reason="r", marked_at=NOW))
    return case_id


def models_saying(*, quick: Mapping[str, float | None], judge: Mapping[str, float | None]):
    """The models for a test: the quick look and the judge answer from the given numbers."""
    return replace(
        scripted_models(Script()), quick_look=ByCompany(quick, "quick-1"), judge=ByCompany(judge)
    )


def make_run(
    workspace: Workspace,
    profile: Profile,
    settings: Settings,
    quick: Mapping[str, float | None],
    judge: Mapping[str, float | None],
) -> EvalRun:
    """An evaluation parcel with a pretend quick look and judge answering from the given numbers."""
    return EvalRun(
        workspace=workspace,
        profile=profile,
        models=models_saying(quick=quick, judge=judge),
        settings=settings,
        tracer=Tracer(),
    )
