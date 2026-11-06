"""The fact check: a script, with no AI, that confirms a brief's quotes are real.

Each claim's quote must appear in the evidence pack source it names, starting and
ending on whole words. The why-now quote must come from a job ad. Both sides are
normalised first (see `normalise`), so typography never decides the result, but
every word must still match.

This file has no imports from `ai`, so nothing a model says can change how it checks.
"""

import re
import unicodedata

from pydantic import BaseModel

from why_now.domain import Brief, EvidencePack, Source
from why_now.settings import Settings

# Curly and other look-alike quotes and dashes become plain ones. NFKC already
# turns non-breaking spaces into spaces, but leaves these alone.
_PLAIN = str.maketrans(
    {
        **dict.fromkeys("\u2018\u2019\u201a\u201b\u2032\u00b4`", "'"),
        **dict.fromkeys("\u201c\u201d\u201e\u201f\u2033\u00ab\u00bb", '"'),
        **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63", "-"),
    }
)
_SPACES = re.compile(r"\s+")


class FactCheckResult(BaseModel):
    ok: bool
    problems: list[str]


def normalise(text: str) -> str:
    """NFKC, plain quotes and dashes, one space for any run of spacing, and lower case."""
    text = unicodedata.normalize("NFKC", text).translate(_PLAIN)
    return _SPACES.sub(" ", text).strip().casefold()


def fact_check(brief: Brief, pack: EvidencePack, settings: Settings) -> FactCheckResult:
    """Check every claim in `brief` against `pack`. The same input always gives the same result."""
    sources = {s.id: s for s in pack.sources}
    claims = [brief.why_now, *brief.claims]
    problems: list[str] = []
    length = sum(len(c.text) + len(c.quote) for c in claims)
    if length > settings.brief_max_chars:
        problems.append(
            f"the brief is {length} characters, over the limit of {settings.brief_max_chars}"
        )
    why_source = sources.get(brief.why_now.source_id)
    if why_source is not None and why_source.kind != "job_ad":
        problems.append(f"the why-now quote must come from a job ad, not {why_source.id}")
    for i, claim in enumerate(claims):
        name = "the why-now claim" if i == 0 else f"claim {i}"
        found = sources.get(claim.source_id)
        if not normalise(claim.text) or not normalise(claim.quote):
            problems.append(f"{name} is empty: it needs both text and a quote")
        elif found is None:
            problems.append(f"no source {claim.source_id!r} in the evidence pack")
        elif not _appears_in(claim.quote, found):
            problems.append(f"quote not found in {claim.source_id}: {claim.quote!r}")
    return FactCheckResult(ok=not problems, problems=problems)


def _appears_in(quote: str, source: Source) -> bool:
    """True if `quote` is in `source`, cutting no word in two at either end."""
    quote, text = normalise(quote), normalise(source.text)
    start = text.find(quote)
    while start != -1:
        end = start + len(quote)
        cuts_start = quote[0].isalnum() and start > 0 and text[start - 1].isalnum()
        cuts_end = quote[-1].isalnum() and end < len(text) and text[end].isalnum()
        if not cuts_start and not cuts_end:
            return True
        start = text.find(quote, start + 1)
    return False
