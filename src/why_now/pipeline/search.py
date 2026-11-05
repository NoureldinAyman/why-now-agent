"""Keep job ads whose titles match a profile's search words, and group them by company."""

import re

from why_now.domain import Company, JobAd, Profile


def company_key(board: str) -> str:
    """The same company on two job sources gets the same key: lowercase, letters and digits only."""
    key = "".join(c for c in board.casefold() if c.isalnum())
    if not key:
        raise ValueError(f"board name {board!r} has no letters or digits")
    return key


def _title_pattern(search_words: list[str]) -> re.Pattern[str] | None:
    words = [w.split() for w in search_words if w.strip()]
    if not words:
        return None
    # Whole words only. Lookarounds rather than \b, so words ending in a symbol still match.
    alternatives = "|".join(r"\s+".join(re.escape(part) for part in w) for w in words)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def _allowed(value: str | None, wanted: set[str]) -> bool:
    """An empty list allows everything, and an ad without the field is kept."""
    if not wanted or value is None:
        return True
    value = value.casefold()
    # A regional tag such as "en-GB" counts as its main language, "en".
    return value in wanted or value.split("-")[0] in wanted


def search_ads(
    ads: list[JobAd], profile: Profile, open_job_counts: dict[str, int]
) -> list[Company]:
    pattern = _title_pattern(profile.search_words)
    if pattern is None:
        return []
    countries = {c.casefold() for c in profile.countries}
    languages = {lang.casefold() for lang in profile.languages}
    all_counts: dict[str, int] = {}
    matched: dict[str, list[JobAd]] = {}
    for ad in ads:
        try:
            key = company_key(ad.board)
        except ValueError:
            continue  # no company can be named from it, and one odd page must not stop the day
        all_counts[key] = all_counts.get(key, 0) + 1
        if (
            pattern.search(ad.title)
            and _allowed(ad.country, countries)
            and _allowed(ad.language, languages)
        ):
            matched.setdefault(key, []).append(ad)
    # The read step's count covers every ad read today, so it wins when it has the company.
    return [
        Company(
            key=key,
            name=found[0].company_name,
            ads=found,
            total_open_jobs=open_job_counts.get(key, all_counts[key]),
        )
        for key, found in matched.items()
    ]
