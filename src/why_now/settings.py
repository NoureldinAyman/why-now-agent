"""All settings, loaded from one TOML file plus `WHY_NOW_` environment variables.

Every number here is listed in the design's "Every number, and why" table.
Order of precedence: defaults, then the settings file, then the environment.
"""

import json
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ENV_PREFIX = "WHY_NOW_"

# How much a Claude model thinks before answering, from least to most. The design
# allows low, medium or high per job.
Effort = Literal["low", "medium", "high"]


class ModelPrice(BaseModel):
    """Prices in US dollars, per million tokens, plus the cost of one web search."""

    model_config = ConfigDict(extra="forbid")

    input_per_million_usd: float
    output_per_million_usd: float
    per_search_usd: float = 0


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment: Literal["local", "aws"] = Field(
        default="local",
        description=(
            "Where the app runs: local on one's own computer, or aws. Run now and Prepare work "
            "only locally, where the keys and the budget are the person's own."
        ),
    )
    workspace_path: Path = Field(
        default=Path("workspace"),
        description=(
            "The folder for everything a run produces. It stays outside Git, so no run data is "
            "ever committed."
        ),
    )
    daily_profiles: list[Path] = Field(
        default_factory=list,
        description=(
            "The profile files the daily run uses and the review page shows. A product works by "
            "adding a file."
        ),
    )
    board_lists: dict[str, Path] = Field(
        default_factory=dict,
        description=(
            "One list of careers pages per job source, as a JSON file. The read step reads only "
            "these pages."
        ),
    )
    public_results_enabled: bool = Field(
        default=False,
        description="Whether public results are published. Off until the owner says yes.",
    )

    short_list_size: int = Field(
        default=10,
        description="The reviewer's time. Starting guess, at 1 to 2 minutes per company.",
    )
    hide_days: int = Field(
        default=90,
        description=(
            "Against repeat reviews. A decided company stays hidden this many days. Starting guess."
        ),
    )
    new_ad_days: int = Field(
        default=14,
        description=(
            "The why-now reason staying current. An ad counts as new for this many days. Starting "
            "guess."
        ),
    )
    research_per_day: int = Field(
        default=12,
        description=(
            "The budget. At most this many companies are researched in a day. Worked out from the "
            "monthly limit."
        ),
    )
    research_steps: int = Field(
        default=5,
        description=(
            "Cost, and how far a hostile page can lead the agent. Starting guess, checked in "
            "traces."
        ),
    )
    newest_ads_read: int = Field(
        default=5,
        description=(
            "Cost, and the size of each evidence pack. Only the newest ads are read in full. "
            "Starting guess."
        ),
    )
    keep_min_gain: int = Field(
        default=2,
        description=(
            "Against keeping changes that were luck. A change must get this many more companies "
            "right. A judgement, not proof."
        ),
    )
    tries_per_check_pile: int = Field(
        default=50,
        description=(
            "Against wearing out the check pile. Starting guess, lowered if final pile scores fall"
            " behind."
        ),
    )

    practice_size: int = Field(
        default=150,
        description=(
            "Measurement quality within the reviewer's time. The practice pile is largest, because"
            " the loop learns from it."
        ),
    )
    check_size: int = Field(
        default=75,
        description=(
            "Measurement quality within the reviewer's time. Equal to the final pile, so their "
            "numbers are about as reliable."
        ),
    )
    final_size: int = Field(
        default=75,
        description=(
            "Measurement quality within the reviewer's time. Equal to the check pile, so their "
            "numbers are about as reliable."
        ),
    )
    pilot_size: int = Field(
        default=40,
        description="Knowing the share of yes answers early. Enough to tell 1 in 3 from 1 in 10.",
    )
    prepare_batch: int = Field(
        default=20,
        gt=0,
        description=(
            "Marking sittings having companies ready, without paying for research nobody marks. "
            "About one short sitting."
        ),
    )
    card_page_chars: int = Field(
        default=400,
        gt=0,
        description=(
            "A marking card short enough to read in seconds. The full pack is one tap away. "
            "Starting guess."
        ),
    )
    preview_companies: int = Field(
        default=20,
        gt=0,
        description=(
            "A profile preview short enough to scan after each edit. The total count is always "
            "shown. Starting guess."
        ),
    )
    run_now_sample_boards: int = Field(
        default=50,
        gt=0,
        description=(
            "A run started with Run now ending in minutes, not hours. It reads this many careers "
            "pages per job source, at random. Starting guess."
        ),
    )
    # Short reasons the reviewer can tap in place of writing a sentence.
    reason_chips: list[str] = Field(
        description=(
            "Short reasons the reviewer can tap in place of writing a sentence, when marking and "
            "deciding."
        ),
        default_factory=lambda: [
            "recruitment agency",
            "competitor",
            "not hiring the right people",
            "too big",
            "too small",
            "good timing",
        ],
    )
    marking_ceiling: int = Field(
        default=500,
        description=(
            "The reviewer's time. At most this many companies are marked. The owner's choice."
        ),
    )
    remark_size: int = Field(
        default=30,
        description=(
            "A rough measure of consistency. This many companies are marked again. Optional."
        ),
    )
    consistency_asks: int = Field(
        default=5,
        gt=1,
        description=(
            "How many times each question is asked again, with no saved answers, to see how much "
            "a model's answers move. Two asks are the least that can show any difference."
        ),
    )
    consistency_packs: int = Field(
        default=20,
        gt=0,
        description=(
            "How many practice packs the consistency check asks about. Practice only, so no "
            "check or final pile company is read."
        ),
    )
    remark_after_days: int = Field(
        default=7,
        description=(
            "Against remembering the first answers. The 'about a week later' in the marking steps."
        ),
    )
    target_yes_per_pile: int = Field(
        default=25,
        description=(
            "Against precision that swings too much. With 25, one company moves precision by about"
            " 4 points."
        ),
    )
    floor_yes_per_pile: int = Field(
        default=15,
        description=(
            "Against keeping changes on a pile too small to judge. The loop waits for this many "
            "yes answers in the check pile."
        ),
    )

    request_delay_seconds: float = Field(
        default=1.0,
        description="The job sources. Seconds between requests, from Lever's robots file.",
    )
    outage_share: float = Field(
        default=0.9,
        description=(
            "Pages being set aside because a whole source was down. This share failing at once is "
            "an outage. Starting guess."
        ),
    )
    dead_after_days: int = Field(
        default=7,
        description=(
            "Against dropping a page for a short outage. Days of failing before a page is set "
            "aside. Starting guess."
        ),
    )
    retry_dead_after_days: int = Field(
        default=30,
        description=(
            "Pages that come back. Days before a set-aside page is tried again. Starting guess."
        ),
    )
    request_attempts: int = Field(
        default=3,
        description=(
            "A short rate limit costing a page its day. Tries when a job source is busy. Starting "
            "guess."
        ),
    )
    max_retry_wait_seconds: float = Field(
        default=60,
        description="One page asking for a long pause stalling the whole read. Starting guess.",
    )
    source_timeout_seconds: float = Field(
        default=30,
        description=(
            "A hung connection stalling the read. Longer than for web pages, because careers pages"
            " arrive as one big reply."
        ),
    )

    budget_limit_usd: float = Field(
        default=70, description="Money. Paid work stops at this monthly total. The owner's choice."
    )
    budget_warning_usd: float = Field(
        default=50, description="Money. The pages warn at this monthly total. The owner's choice."
    )
    loop_budget_usd: float = Field(
        default=25,
        description=(
            "The money research needs. The improvement loop's monthly share. Worked out from the "
            "monthly limit."
        ),
    )
    fixed_monthly_costs_usd: float = Field(
        default=0,
        description=(
            "Counting AWS and Langfuse, which have no per-call meter, towards the monthly limit. "
            "Set by each person."
        ),
    )
    langfuse_thin_at_units: int = Field(
        default=40_000,
        description=(
            "The Langfuse free plan's limit of 50,000 units. Traces thin out from here, as a "
            "safety margin."
        ),
    )

    quick_look_pass: float = Field(
        default=0.3,
        description=(
            "Good companies being dropped before research. Low on purpose, because the quick look "
            "only decides what gets researched."
        ),
    )
    required_pass: float = Field(
        default=0.5,
        description=(
            "A yes needing each required question to be more likely yes than no. Even odds."
        ),
    )
    cutoff_step: float = Field(
        default=0.05,
        gt=0,
        le=1,
        description=(
            "Against a cut-off fitted too closely to the practice pile. Cut-offs are tried this "
            "far apart. Starting guess."
        ),
    )
    default_cutoff: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description=(
            "The daily list working before anyone has marked. Even odds, replaced by the cut-off "
            "chosen on the practice pile."
        ),
    )
    score_beta: float = Field(
        default=1,
        gt=0,
        description=(
            "Weighing a missed company the same as a wrong one (F1). See "
            "docs/decisions/0006-f1-replaces-f05.md."
        ),
    )

    max_page_bytes: int = Field(
        default=2_000_000, description="The page reader, against huge pages. Starting guess."
    )
    page_timeout_seconds: float = Field(
        default=15,
        description=(
            "The page reader, against slow pages. Also limits each call the login makes. Starting "
            "guess."
        ),
    )
    max_redirects: int = Field(
        default=5,
        description="The page reader, against redirect loops. The robots standard's number.",
    )
    max_ad_chars: int = Field(
        default=20_000,
        description="The cost of each model call. Each ad is cut to this length. Starting guess.",
    )
    max_pack_chars: int = Field(
        default=60_000,
        description=(
            "The cost of each model call. Each evidence pack is cut to this length. Starting guess."
        ),
    )
    brief_max_chars: int = Field(
        default=1_200, description="The reviewer's time. The longest brief allowed. Starting guess."
    )
    screen_max_copied_words: int = Field(
        default=8, description="Learned rules that copy ad text. Starting guess."
    )
    screen_max_why_words: int = Field(
        default=20, description="Learned rules that cannot be explained briefly. Starting guess."
    )

    # Only used when `deployment = "aws"`. The names come from the AWS setup.
    aws_region: str = Field(
        default="", description="The AWS region the app's parts are in. Only used on AWS."
    )
    aws_bucket: str = Field(
        default="", description="The S3 bucket for large documents. Only used on AWS."
    )
    aws_table: str = Field(
        default="", description="The DynamoDB table for documents. Only used on AWS."
    )
    aws_parameter_prefix: str = Field(
        default="/why-now",
        description="Where secrets are kept in Parameter Store. No secret is ever a setting.",
    )  # where secrets are kept in Parameter Store
    aws_inline_max_bytes: int = Field(
        default=350_000,
        description=(
            "A record being refused. DynamoDB refuses records over 400 KB, so larger ones go to S3."
        ),
    )
    cognito_domain: str = Field(
        default="", description="The login page's address on AWS."
    )  # the login page's address, such as https://name.auth.<region>...
    cognito_user_pool_id: str = Field(
        default="", description="The Cognito user pool that holds the login. Only used on AWS."
    )
    cognito_client_id: str = Field(
        default="", description="The login client. Read from Parameter Store when left empty."
    )  # read from Parameter Store when left empty
    session_hours: int = Field(
        default=12,
        description="Someone else using a forgotten open session. One working day. Starting guess.",
    )
    login_minutes: int = Field(
        default=10,
        description=(
            "A stolen half-finished sign-in being used later. Long enough to type a password and a"
            " code."
        ),
    )
    session_secret_min_chars: int = Field(
        default=32,
        description=(
            "Someone guessing the session secret. 32 random characters are far too many to guess."
        ),
    )

    research_model: str = Field(
        default="claude-sonnet-5-5",
        description=(
            "The model that researches a company. Locked to one version, so scores do not shift "
            "without a reason."
        ),
    )
    writer_model: str = Field(
        default="claude-sonnet-5-5",
        description="The model that writes briefs and drafts profiles. Locked to one version.",
    )
    quick_look_model: str = Field(
        default="jev-1.14.0",
        description="The cheap model for the quick look. Locked to one version.",
    )
    quick_look_fallback_model: str = Field(
        default="claude-haiku-5-5", description="The quick look's model when there is no Jev key."
    )  # used when there is no Jev key
    judge_model: str = Field(
        default="claude-sonnet-5-5",
        description="The model that answers the fit questions. Locked to one version.",
    )
    judge_candidates: list[str] = Field(
        default_factory=lambda: ["jev-1.14.0", "claude-sonnet-5-5"],
        description=(
            "The two judge setups the comparison runs on the check pile. Only two, because "
            "comparing many and keeping the best would fit the score to that pile. With no Jev "
            "key, a Jev entry is replaced by the quick look's Claude fallback model."
        ),
    )
    # Effort per Claude job. Jev has no effort, so `quick_look_effort` is used only
    # when the quick look falls back to Claude.
    quick_look_effort: Effort = Field(
        default="low",
        description=(
            "Cost, against thinking too little. Used only when the quick look falls back to Claude."
        ),
    )
    research_effort: Effort = Field(
        default="medium",
        description=(
            "Cost, against thinking too little on research. Tuned on the practice pile only."
        ),
    )
    judge_effort: Effort = Field(
        default="medium",
        description=(
            "Cost, against thinking too little on judging. Tuned on the practice pile only."
        ),
    )
    writer_effort: Effort = Field(
        default="medium",
        description=(
            "Cost, against thinking too little on briefs and drafts. Tuned on the practice pile "
            "only."
        ),
    )
    proposer_effort: Effort = Field(
        default="high", description="Cost, against thinking too little on proposing rule changes."
    )
    model_max_output_tokens: int = Field(
        default=16_000,
        description=(
            "A call finishing inside the Claude library's time limit. Calls are charged for what "
            "they use."
        ),
    )
    # Checked on 6 Nov 2026: Claude from Anthropic's model table, Jev from TypeSafe's
    # models page (it charges for input tokens only). A model with no price is refused.
    prices: dict[str, ModelPrice] = Field(
        description=(
            "Charging each call at its real cost. Published prices, checked on 6 Nov 2026. A model"
            " with no price is refused."
        ),
        default_factory=lambda: {
            "claude-sonnet-5-5": ModelPrice(
                input_per_million_usd=2, output_per_million_usd=10, per_search_usd=0.01
            ),
            "claude-haiku-5-5": ModelPrice(input_per_million_usd=0.1, output_per_million_usd=0.5),
            "jev-1.14.0": ModelPrice(input_per_million_usd=0.042, output_per_million_usd=0),
        },
    )


def load_settings(path: Path | None = None, env: Mapping[str, str] | None = None) -> Settings:
    """Read `path` (TOML) if given, then apply `WHY_NOW_` overrides from `env`.

    `env` defaults to the process environment. Lists and tables in the
    environment are written as JSON, for example `WHY_NOW_DAILY_PROFILES='["a.yaml"]'`.
    """
    values: dict[str, Any] = {}
    if path is not None:
        with path.open("rb") as f:
            values.update(tomllib.load(f))
    for name, raw in (os.environ if env is None else env).items():
        if name.startswith(ENV_PREFIX):
            values[name.removeprefix(ENV_PREFIX).lower()] = _env_value(raw)
    return Settings.model_validate(values)


def _env_value(raw: str) -> Any:
    """JSON lists and tables are parsed, everything else is left for pydantic to convert."""
    if raw.lstrip().startswith(("[", "{")):
        return json.loads(raw)
    return raw
