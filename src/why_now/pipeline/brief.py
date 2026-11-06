"""Briefs: Claude writes a short brief as claims with quotes, then the fact check tests it.

A brief that fails the fact check gets one more attempt, and the writer is told
exactly what failed. If the second attempt fails too, `write_brief` returns None:
the company is dropped and never reaches the reviewer. A writer reply that does
not fit the brief's shape counts as a failed attempt in the same way.

Every attempt and its fact check result go in the trace, so a dropped company's
failure is recorded.
"""

from pydantic import BaseModel

from why_now.ai import BadModelOutput, Writer
from why_now.domain import Brief, Claim, EvidencePack, Profile, Verdict
from why_now.pipeline.fact_check import FactCheckResult, fact_check
from why_now.pipeline.judge import pack_state
from why_now.settings import Settings
from why_now.tracing import Tracer

BRIEF_CATEGORY = "brief"  # the budget category briefs are charged to

BRIEF_SYSTEM = """\
You write a short brief about one company for a person who sells {product_name}: \
{product_description} Its users are {users}.

The company has been judged a good fit. Write the brief from the evidence pack only.

- `why_now` is the claim that says why the company needs the product now. \
What counts as a reason: {why_now}. Its quote must come from a job ad.
- `claims` are the other facts the person should know, most useful first.
- Each claim has a short `text` in your own words, a `quote` copied word for word \
from one source, and that source's id in `source_id`. Source ids are in square \
brackets before each source.
- Keep the whole brief, texts and quotes together, under {max_chars} characters.
- Never state a fact that has no quote.\
"""

RETRY_NOTE = """

Your last brief failed the fact check. The problems are listed after the evidence, \
under "Fact check problems". Write the brief again and fix every one: copy each \
quote exactly as it appears in its source.\
"""


class BriefDraft(BaseModel):
    """What the writer returns. The company key is added by code."""

    why_now: Claim
    claims: list[Claim]


def write_brief(
    pack: EvidencePack,
    verdict: Verdict,
    profile: Profile,
    writer: Writer,
    settings: Settings,
    tracer: Tracer,
    *,
    category: str = BRIEF_CATEGORY,
) -> Brief | None:
    """A brief for `pack` that passes the fact check, or None after a second failure.

    A spent budget is not caught: the caller stops the run.
    """
    system = BRIEF_SYSTEM.format(
        product_name=profile.product_name,
        product_description=profile.product_description,
        users=profile.users,
        why_now=profile.why_now,
        max_chars=settings.brief_max_chars,
    )
    evidence = pack_state(pack)
    problems: list[str] = []
    with tracer.trace(
        "brief", profile_id=profile.id, rules_version=None, models={"writer": writer.model}
    ) as trace:
        # The first attempt, then one more if it fails.
        for attempt in (1, 2):
            if problems:
                prompt_system = system + RETRY_NOTE
                untrusted = evidence + "\n\nFact check problems:\n" + _listed(problems)
            else:
                prompt_system, untrusted = system, evidence
            try:
                draft = writer.structured(
                    system=prompt_system, untrusted=untrusted, schema=BriefDraft, category=category
                )
            except BadModelOutput as e:
                result = FactCheckResult(
                    ok=False, problems=[f"the writer gave no usable brief: {e}"]
                )
                trace.step(f"brief_attempt_{attempt}", {"strength": verdict.strength}, None)
            else:
                brief = Brief(company_key=pack.company_key, **draft.model_dump())
                result = fact_check(brief, pack, settings)
                trace.step(
                    f"brief_attempt_{attempt}", {"strength": verdict.strength}, brief.model_dump()
                )
                if result.ok:
                    trace.step("fact_check", attempt, result.model_dump())
                    trace.score("fact_check_passed", 1)
                    return brief
            trace.step("fact_check", attempt, result.model_dump())
            problems = result.problems
        trace.score("fact_check_passed", 0)
        return None


def _listed(problems: list[str]) -> str:
    return "\n".join(f"- {p}" for p in problems)
