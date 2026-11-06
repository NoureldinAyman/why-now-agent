"""Shared data shapes. Later tasks use these names, so this file is their source of truth."""

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
    quick_look_questions: list[FitQuestion]
    fit_questions: list[FitQuestion]
    why_now: str
    public: bool = False


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
    reason: str
    decided_at: datetime
    from_list: Literal["short", "more"]


class Mark(BaseModel):
    case_id: str
    answer: Literal["yes", "no", "cant_tell"]
    reason: str
    marked_at: datetime
    round: Literal["first", "repeat"] = "first"


class CaseRecord(BaseModel):
    case_id: str
    profile_id: str
    company_key: str
    pack_id: str | None = None  # None until its evidence pack is built
    seed: int
    pile: Literal["practice", "check", "final", "unsplit"] | None = None
    check_version: int | None = None


class BoardHealth(BaseModel):
    """How reading one careers page has gone lately, so dead pages can be set aside."""

    failing_days: int = 0
    last_failed: date | None = None
    set_aside_on: date | None = None
    last_retry: date | None = None
