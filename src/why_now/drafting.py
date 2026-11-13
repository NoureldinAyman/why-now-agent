"""Draft a profile from a few sentences, and preview what it would find.

Drafting is one paid structured call. The person then reads and edits the draft, and
saving it is their approval, required questions included, since the loop can never change
those. The preview makes no paid call: it only searches the last saved read.
"""

from pydantic import BaseModel

from why_now.ai import Writer
from why_now.domain import FitQuestion, Profile
from why_now.pipeline.search import search_ads
from why_now.profile import parse_profile, profile_text
from why_now.settings import Settings
from why_now.workspace import Workspace

CATEGORY = "drafting"  # the budget category a draft is charged to

DRAFT_SYSTEM = """\
You draft a profile for an agent that reads public job ads and finds companies that may want
a product now. The person describes the product below. Write:

- id: a short lowercase name with hyphens, from the product's name.
- product_name, product_description and users (who uses the product), from the description.
- search_words: a few job titles, as whole words or phrases, whose ads suggest a company
  could need the product now.
- countries and languages: empty lists unless the description limits them. Countries are
  two-letter codes and languages are two-letter codes.
- fit_questions: several yes or no questions about the company, answerable from its job ads
  and website. Each question tests one exact condition and is read literally. Mark a
  question "required" only if a "no" truly rules the company out, such as a competitor or a
  recruitment agency. All others are "supporting". Use direction "against" for a question
  where yes counts against the company. Say what yes and no mean for each.
- why_now: what a good reason to contact the company now looks like, in one or two sentences.

Name no real company. Leave out quick look questions: the agent builds them from the
required questions and who uses the product.
"""


class DraftedProfile(BaseModel):
    """What the model writes. The quick look questions and `public` are left to their defaults."""

    id: str
    product_name: str
    product_description: str
    users: str
    search_words: list[str]
    countries: list[str]
    languages: list[str]
    fit_questions: list[FitQuestion]
    why_now: str


def draft_profile(description: str, writer: Writer) -> Profile:
    """A profile drafted from `description`, checked as a profile file is checked."""
    drafted = writer.structured(
        system=DRAFT_SYSTEM, untrusted=description, schema=DraftedProfile, category=CATEGORY
    )
    profile = Profile.model_validate(drafted.model_dump())
    # Written out and read back, so a draft is only offered if the loader accepts it.
    return parse_profile(profile_text(profile), "draft")


class PreviewCompany(BaseModel):
    name: str
    relevant_ads: int
    titles: list[str]


class Preview(BaseModel):
    ads_read: int  # ads in the last saved read
    company_count: int  # companies the search words find
    companies: list[PreviewCompany]  # the ones with the most relevant ads, up to the setting


def preview(workspace: Workspace, profile: Profile, settings: Settings) -> Preview:
    """The companies the last saved read gives for this profile's search words. No model is
    called, so it is free and can be run after every edit."""
    ads = workspace.all_board_ads()
    companies = search_ads(ads, profile, {})
    companies.sort(key=lambda c: (-len(c.ads), c.name.casefold()))
    return Preview(
        ads_read=len(ads),
        company_count=len(companies),
        companies=[
            PreviewCompany(
                name=c.name,
                relevant_ads=len(c.ads),
                titles=list(dict.fromkeys(ad.title for ad in c.ads)),
            )
            for c in companies[: settings.preview_companies]
        ],
    )
