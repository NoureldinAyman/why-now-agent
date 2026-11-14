"""Shared data shapes. Later tasks use these names, so this file is their source of truth."""

import hashlib
import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class JobAd(BaseModel):
    source: str
    board: str
    ad_id: str
    company_name: str
    title: str
    location: str
    country: str | None
    language: str | None
    text: str
    url: str
    published_at: datetime
    first_seen: date


class Company(BaseModel):
    key: str
    name: str
    ads: list[JobAd]
    total_open_jobs: int


class FitQuestion(BaseModel):
    id: str
    text: str
    kind: Literal["required", "supporting"] = "supporting"
    direction: Literal["for", "against"] = "for"
    yes_means: str | None = None
    no_means: str | None = None


class LearnedQuestion(FitQuestion):
    why: str


class RulesFile(BaseModel):
    profile_id: str
    version: int = 0
    questions: list[LearnedQuestion] = []


class Profile(BaseModel):
    id: str
    product_name: str
    product_description: str
    users: str
    search_words: list[str]
    countries: list[str] = []
    languages: list[str] = []
    # Optional. When empty, the quick look uses the required questions plus one built from
    # who uses the product (see `profile.quick_look_questions`).
    quick_look_questions: list[FitQuestion] = []
    fit_questions: list[FitQuestion]
    why_now: str
    public: bool = False

    @property
    def version(self) -> str:
        """A hash of what the profile says. Any edit to its fields gives a new version,
        while comments and layout in the file change nothing."""
        said = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(said.encode()).hexdigest()


class Source(BaseModel):
    id: str
    kind: Literal["job_ad", "page"]
    url: str
    text: str
    fetched_at: datetime


class EvidencePack(BaseModel):
    pack_id: str
    profile_id: str
    company_key: str
    company_name: str
    created_at: datetime
    sources: list[Source]
    relevant_ad_count: int
    total_open_jobs: int
    research_steps: int
    # Every relevant ad's title and the newest ad's publish date, kept so the marking card
    # can be built from the pack alone. Packs made before these were kept have neither.
    ad_titles: list[str] = []
    newest_ad_at: datetime | None = None


class Answer(BaseModel):
    question_id: str
    probability: float
    model: str


class Verdict(BaseModel):
    yes: bool
    strength: float
    answers: list[Answer]


class Claim(BaseModel):
    text: str
    quote: str
    source_id: str


class Brief(BaseModel):
    company_key: str
    why_now: Claim
    claims: list[Claim]


class Decision(BaseModel):
    profile_id: str
    company_key: str
    approved: bool
    reason: str  # may be empty when chips give the reason
    decided_at: datetime
    from_list: Literal["short", "more"]
    chips: list[str] = []  # the short reasons the reviewer tapped, as when marking
    profile_version: str | None = None  # the profile's version when it was decided


class Mark(BaseModel):
    case_id: str
    answer: Literal["yes", "no", "cant_tell"]
    reason: str  # may be empty when chips give the reason
    marked_at: datetime
    round: Literal["first", "repeat"] = "first"
    chips: list[str] = []  # the short reasons the reviewer tapped
    seen_on_list: bool = False  # the company was on a daily list before it was marked
    # The profile's version when it was marked, so scores from different versions are never
    # joined as one line. None for marks made before versions were kept.
    profile_version: str | None = None


class CaseRecord(BaseModel):
    case_id: str
    profile_id: str
    company_key: str
    pack_id: str | None = None  # None until its evidence pack is built
    seed: int
    pile: Literal["practice", "check", "final", "unsplit"] | None = None  # set at the pick


class PickRecord(BaseModel):
    """One random pick of test cases: its seed, what was asked for and what was picked."""

    seed: int
    n: int
    picked: list[str]
    at: datetime


type Moment = Literal["first", "after_loop", "publishing", "extra"]


class FinalOpening(BaseModel):
    """One time the final pile was opened. The log of these is public."""

    moment: Moment
    reason: str | None
    opened_at: datetime


class BoardHealth(BaseModel):
    """How reading one careers page has gone lately, so dead pages can be set aside."""

    failing_days: int = 0
    last_failed: date | None = None
    set_aside_on: date | None = None
    last_retry: date | None = None
