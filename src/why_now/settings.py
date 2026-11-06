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


class ModelPrice(BaseModel):
    """Prices in US dollars, per million tokens, plus the cost of one web search."""

    model_config = ConfigDict(extra="forbid")

    input_per_million_usd: float
    output_per_million_usd: float
    per_search_usd: float = 0


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment: Literal["local", "aws"] = "local"
    workspace_path: Path = Path("workspace")
    daily_profiles: list[Path] = Field(default_factory=list)
    board_lists: dict[str, Path] = Field(default_factory=dict)
    public_results_enabled: bool = False

    short_list_size: int = 10
    hide_days: int = 90
    new_ad_days: int = 14
    research_per_day: int = 12
    research_steps: int = 5
    newest_ads_read: int = 5
    keep_min_gain: int = 2
    tries_per_check_pile: int = 50

    practice_size: int = 150
    check_size: int = 75
    final_size: int = 75
    pilot_size: int = 40
    marking_ceiling: int = 500
    remark_size: int = 30
    remark_after_days: int = 7
    target_yes_per_pile: int = 25
    floor_yes_per_pile: int = 15

    request_delay_seconds: float = 1.0
    outage_share: float = 0.9
    dead_after_days: int = 7
    retry_dead_after_days: int = 30
    request_attempts: int = 3
    max_retry_wait_seconds: float = 60
    source_timeout_seconds: float = 30

    budget_limit_usd: float = 70
    budget_warning_usd: float = 50
    loop_budget_usd: float = 25
    fixed_monthly_costs_usd: float = 0
    langfuse_thin_at_units: int = 40_000

    quick_look_pass: float = 0.3
    required_pass: float = 0.5
    cutoff_step: float = Field(default=0.05, gt=0, le=1)

    max_page_bytes: int = 2_000_000
    page_timeout_seconds: float = 15
    max_ad_chars: int = 20_000
    max_pack_chars: int = 60_000
    brief_max_chars: int = 1_200
    screen_max_copied_words: int = 8
    screen_max_why_words: int = 20

    research_model: str = "claude-sonnet-5-5"
    writer_model: str = "claude-sonnet-5-5"
    quick_look_model: str = "jev-1.14.0"
    quick_look_fallback_model: str = "claude-haiku-5-5"  # used when there is no Jev key
    judge_model: str = "claude-sonnet-5-5"
    model_max_output_tokens: int = 16_000
    # Checked on 6 Nov 2026: Claude from Anthropic's model table, Jev from TypeSafe's
    # models page (it charges for input tokens only). A model with no price is refused.
    prices: dict[str, ModelPrice] = Field(
        default_factory=lambda: {
            "claude-sonnet-5-5": ModelPrice(
                input_per_million_usd=2, output_per_million_usd=10, per_search_usd=0.01
            ),
            "claude-haiku-5-5": ModelPrice(input_per_million_usd=0.1, output_per_million_usd=0.5),
            "jev-1.14.0": ModelPrice(input_per_million_usd=0.042, output_per_million_usd=0),
        }
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
