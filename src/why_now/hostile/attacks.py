"""The attack set: invented hostile packs, each with a clean twin.

`attacks.yaml` holds the entries in a short form. Each lists its sources, and the
hostile text to add to some of them. `attack_from_entry` builds the two packs from
that, so the twins differ only by the hostile text and nothing else can drift apart.
All names, addresses and sentences are invented.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from why_now.domain import EvidencePack, Source

ATTACKS_FILE = Path(__file__).with_name("attacks.yaml")
# A fixed time, so a pack is the same every run.
_MADE_AT = datetime(2026, 1, 1, tzinfo=UTC)
PROFILE_ID = "hostile-tests"


class Attack(BaseModel):
    id: str
    kind: Literal["change_decision", "add_rule", "blocked_address", "plant_text"]
    hostile_pack: EvidencePack
    clean_pack: EvidencePack
    planted_text: str
    blocked_url: str | None = None

    @model_validator(mode="after")
    def _blocked_url_only_for_blocked_address(self) -> "Attack":
        if (self.kind == "blocked_address") != (self.blocked_url is not None):
            raise ValueError(f"attack {self.id}: a blocked address belongs to blocked_address only")
        return self


class _EntrySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["job_ad", "page"]
    text: str
    hostile: str | None = None


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["change_decision", "add_rule", "blocked_address", "plant_text"]
    company: str
    planted_text: str
    blocked_url: str | None = None
    sources: list[_EntrySource]


def attack_from_entry(entry: dict[str, Any]) -> Attack:
    """Build an attack from one short-form entry."""
    e = _Entry.model_validate(entry)
    if not e.sources or e.sources[0].kind != "job_ad":
        raise ValueError(f"attack {e.id}: the first source must be a job ad")

    def pack(hostile: bool) -> EvidencePack:
        sources = []
        for n, s in enumerate(e.sources, start=1):
            text = f"{s.text}\n{s.hostile}" if hostile and s.hostile else s.text
            sources.append(
                Source(
                    id=f"{'ad' if s.kind == 'job_ad' else 'page'}-{e.id}-{n}",
                    kind=s.kind,
                    url=f"https://attacks.example.test/{e.id}/{n}",
                    text=text,
                    fetched_at=_MADE_AT,
                )
            )
        return EvidencePack(
            pack_id=f"attack-{e.id}-{'hostile' if hostile else 'clean'}",
            profile_id=PROFILE_ID,
            company_key=e.id,
            company_name=e.company,
            created_at=_MADE_AT,
            sources=sources,
            relevant_ad_count=sum(s.kind == "job_ad" for s in sources),
            total_open_jobs=sum(s.kind == "job_ad" for s in sources),
            research_steps=0,
        )

    return Attack(
        id=e.id,
        kind=e.kind,
        hostile_pack=pack(True),
        clean_pack=pack(False),
        planted_text=e.planted_text.strip(),
        blocked_url=e.blocked_url,
    )


def load_attacks(path: Path = ATTACKS_FILE) -> list[Attack]:
    """The attack set, in the order the file lists it. Ids must be different from each other."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    attacks = [attack_from_entry(entry) for entry in entries]
    ids = [a.id for a in attacks]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise ValueError(f"attack ids used twice: {repeated}")
    return attacks
