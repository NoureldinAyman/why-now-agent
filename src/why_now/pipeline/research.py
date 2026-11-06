"""Research: one company becomes a frozen evidence pack.

A pack starts with the company's newest relevant job ads. Then the research model
may search the web and ask for pages, which our own page reader fetches, in a
small loop with a hard limit:

- A step is one web search or one page read, whether the page was read or refused.
  A model reply that does neither still counts as one step, so the loop always ends.
- Research stops when the model says it is done, at `research_steps`, or when the
  pack is full (`max_pack_chars`).
- A refused or failed page is not saved, and the model is told why.
- The model sees page text exactly as it is saved, marked as untrusted, so every
  fact it could use is in the pack for the fact check.

Searching and reading are the model's only tools, and neither can change anything.
See docs/decisions/0003-frozen-evidence-packs.md.
"""

import hashlib
from datetime import datetime
from typing import Protocol

from why_now.ai import BadModelOutput, ResearchModel, ResearchStep, mark_untrusted
from why_now.domain import Company, EvidencePack, JobAd, Profile, Source
from why_now.pipeline.reader import PageRefused, remove_contacts
from why_now.settings import Settings
from why_now.tracing import Tracer


class PageSource(Protocol):
    """What research needs from a page reader: read one page, or raise `PageRefused`."""

    def read(self, url: str) -> Source: ...


def research_company(
    company: Company,
    profile: Profile,
    model: ResearchModel,
    reader: PageSource,
    settings: Settings,
    tracer: Tracer,
    *,
    category: str,
    now: datetime,
) -> EvidencePack:
    """Research `company` for `profile` and return its evidence pack.

    The model's errors, and a spent budget, are not caught: the caller records
    the company as failed or stops the run.
    """
    with tracer.trace(
        "research", profile_id=profile.id, rules_version=None, models={"research": model.model}
    ) as trace:
        pack = _PackBuilder(settings.max_pack_chars)
        for job_ad in _newest(company.ads, settings.newest_ads_read):
            pack.add(_ad_source(job_ad, settings.max_ad_chars, now))
        prompt = _research_prompt(company, profile, pack, settings.research_steps)
        conversation: list[dict] = [{"role": "user", "content": prompt}]
        steps = 0
        while steps < settings.research_steps and pack.room > 0:
            step = model.step(conversation, category)
            steps += step.searches_used
            if step.done:
                trace.step("research_step", step.model_dump(), "done")
                break
            results = []
            for tool_use_id, url in zip(_tool_use_ids(step), step.read_urls, strict=True):
                if steps >= settings.research_steps:
                    results.append(_refusal(tool_use_id, "Not read: the step limit is reached."))
                elif pack.room <= 0:
                    results.append(_refusal(tool_use_id, "Not read: the evidence pack is full."))
                else:
                    steps += 1
                    results.append(_read(tool_use_id, url, reader, pack))
            if not step.read_urls and not step.searches_used:
                steps += 1
            trace.step("research_step", step.model_dump(), [r["content"] for r in results])
            if results:
                conversation.append({"role": "user", "content": results})
        trace.step("evidence_pack", company.key, {"sources": len(pack.sources), "steps": steps})
        return EvidencePack(
            pack_id=_pack_id(company.key, profile.id, now),
            profile_id=profile.id,
            company_key=company.key,
            company_name=company.name,
            created_at=now,
            sources=pack.sources,
            relevant_ad_count=len(company.ads),
            total_open_jobs=company.total_open_jobs,
            research_steps=steps,
        )


class _PackBuilder:
    """The sources so far, kept within `max_chars` of text in all."""

    def __init__(self, max_chars: int):
        self.sources: list[Source] = []
        self.room = max_chars

    def add(self, source: Source) -> Source | None:
        """Add `source`, cut to the room left. None if the pack is already full."""
        if self.room <= 0:
            return None
        source = source.model_copy(update={"text": source.text[: self.room]})
        self.room -= len(source.text)
        self.sources.append(source)
        return source

    def get(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)


def _newest(ads: list[JobAd], n: int) -> list[JobAd]:
    # The ad id breaks ties, so ads published at the same moment come in a fixed order.
    return sorted(ads, key=lambda a: (a.published_at, a.ad_id), reverse=True)[:n]


def _ad_source(job_ad: JobAd, max_chars: int, now: datetime) -> Source:
    key = f"{job_ad.source}|{job_ad.board}|{job_ad.ad_id}"
    return Source(
        id="ad-" + hashlib.sha256(key.encode()).hexdigest()[:16],
        kind="job_ad",
        url=job_ad.url,
        # The whole saved text, title included, keeps within the setting.
        text=remove_contacts(f"{job_ad.title} ({job_ad.location})\n{job_ad.text}")[:max_chars],
        fetched_at=now,
    )


def _research_prompt(company: Company, profile: Profile, pack: _PackBuilder, steps: int) -> str:
    ads = "\n\n".join(f"[{s.id}] {s.url}\n{mark_untrusted(s.text)}" for s in pack.sources)
    return (
        f"Research the company {company.name} for someone deciding whether to offer it "
        f"this product: {profile.product_description} Its users: {profile.users}\n\n"
        f"It has {len(company.ads)} relevant job ads and {company.total_open_jobs} open jobs "
        f"in all. The newest are below.\n\n{ads}\n\n"
        f"Find facts about the company, not about people. You may take at most {steps} "
        "steps, where each web search or page read is one step."
    )


def _read(tool_use_id: str, url: str, reader: PageSource, pack: _PackBuilder) -> dict:
    """Read `url` into the pack, and answer the request with what happened."""
    try:
        page = reader.read(url)
    except PageRefused as e:
        # The reader turns every failure into a refusal, a site that is down included.
        return _refusal(tool_use_id, f"Refused, not saved ({e.reason}). Don't try to get round it.")
    saved = pack.get(page.id) or pack.add(page)
    if saved is None:
        return _refusal(tool_use_id, "Not saved: the evidence pack is full.")
    return _result(tool_use_id, f"[{saved.id}] {saved.url}\n{mark_untrusted(saved.text)}")


def _tool_use_ids(step: ResearchStep) -> list[str]:
    """Ids to answer each read with. Scripted models give none, so stand-ins are made."""
    if not step.tool_use_ids:
        return [f"read-{i}" for i in range(len(step.read_urls))]
    if len(step.tool_use_ids) != len(step.read_urls):
        raise BadModelOutput("research step has a different number of reads and ids")
    return step.tool_use_ids


def _result(tool_use_id: str, content: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


def _refusal(tool_use_id: str, content: str) -> dict:
    return _result(tool_use_id, content) | {"is_error": True}


def _pack_id(company_key: str, profile_id: str, created_at: datetime) -> str:
    key = f"{company_key}|{profile_id}|{created_at.isoformat()}"
    return "pack-" + hashlib.sha256(key.encode()).hexdigest()[:16]
