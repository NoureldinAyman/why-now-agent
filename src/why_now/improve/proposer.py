"""Asking the AI for one change to the rules, given the mistakes found."""

from collections.abc import Sequence

from why_now.ai import Writer
from why_now.ai.budget import LOOP
from why_now.domain import Profile, RulesFile
from why_now.improve.mistakes import Mistake
from why_now.improve.screen import RuleChange

PROPOSER_SYSTEM = """\
You improve how a company-finding agent decides. The agent judges each company with a list of
fit questions. You are shown companies where it disagreed with the human reviewer. Propose
exactly one change to the agent's learned questions: add one, edit one, or remove one.

Rules for the change:
- Change only learned questions. Never change a profile question.
- A new or edited question is one general sentence that fits many companies, with a short
  why clause saying why it exists.
- Never name a company and never copy words from a job ad.
- A learned question is a supporting question. Set `direction` to "for" when a yes makes a
  company a better fit, and to "against" when a yes makes it a worse fit.
- For an edit or a removal, give the id of the learned question. For an add, leave
  `question_id` empty and give the new question a new id.
- In `based_on`, list the ids of the mistakes the change is meant to fix.
- Do not repeat anything listed as already tried.
- The reasons given for right yes answers show what makes a company count. A question may be
  built on them as well as on the mistakes.
"""


def propose_change(
    mistakes: list[Mistake],
    profile: Profile,
    rules: RulesFile,
    tried_summaries: list[str],
    writer: Writer,
    *,
    yes_reasons: Sequence[str] = (),
) -> RuleChange:
    """One change to the learned questions, asked of the AI. Costs money, charged to the loop."""
    if not mistakes:
        raise ValueError("no mistakes to learn from")
    return writer.structured(
        system=PROPOSER_SYSTEM,
        untrusted=_briefing(mistakes, profile, rules, tried_summaries, yes_reasons),
        schema=RuleChange,
        category=LOOP,
    )


def _briefing(
    mistakes: list[Mistake],
    profile: Profile,
    rules: RulesFile,
    tried_summaries: list[str],
    yes_reasons: Sequence[str],
) -> str:
    """Everything the AI is shown. It is all passed as untrusted text, because the reviewer's
    reasons are free text that may hold words copied from a job ad."""
    # Built field by field, so the marking guide and anything added to the profile later
    # reach the AI only on purpose.
    lines = [
        f"Product: {profile.product_name}. {profile.product_description}",
        f"Used by: {profile.users}",
        f"Why now: {profile.why_now}",
        "",
        "Profile questions (cannot be changed):",
        *[f"- {q.id} ({q.kind}): {q.text}" for q in profile.fit_questions],
        "",
        "Learned questions (can be edited or removed):",
        *([f"- {q.id}: {q.text} (why: {q.why})" for q in rules.questions] or ["- none yet"]),
        "",
        "Already tried:",
        *([f"- {t}" for t in tried_summaries] or ["- nothing yet"]),
        "",
        "Reasons the reviewer gave for companies the agent rightly said yes to:",
        *([f"- {r}" for r in yes_reasons] or ["- none yet"]),
        "",
        "Mistakes:",
        *[_mistake_line(m) for m in mistakes],
    ]
    return "\n".join(lines)


def _mistake_line(m: Mistake) -> str:
    said = "yes" if m.agent_yes else "no"
    should = "yes" if m.reviewer_yes else "no"
    answers = ", ".join(f"{a.question_id}={a.probability:.2f}" for a in m.answers) or "none kept"
    head = (
        f"- {m.id}: the agent said {said}, the reviewer said {should}. "
        f"Reviewer's reason: {m.reason or 'none given'}. Answers: {answers}"
    )
    if not m.quotes:
        return head
    return "\n".join([head, "  Ads:", *[f"  - {q}" for q in m.quotes]])
