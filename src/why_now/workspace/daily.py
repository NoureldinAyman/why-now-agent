"""The daily run's documents: decisions, the two lists, seen ads and saved steps.

Everything here is kept per profile, because each profile has its own reviewer's
decisions, its own lists, and its own idea of which ads are worth a second look.
"""

import hashlib
from datetime import date, datetime, timedelta

from why_now.day_result import DayResult, ListEntry
from why_now.domain import Decision, JobAd, ListName
from why_now.workspace.base import WorkspaceBase

_LISTS = "daily_lists"


def ad_ref(ad: JobAd) -> tuple[str, str, str]:
    """What names one ad: its job source, its careers page (lower case) and its id."""
    return (ad.source, ad.board.lower(), ad.ad_id)


def closest_to_yes(entries: list[ListEntry]) -> list[ListEntry]:
    """Strongest first. On equal strength the company key decides the order."""
    return sorted(entries, key=lambda e: (-(e.strength or 0), e.company_key))


class DailyArea(WorkspaceBase):
    # Decisions

    def save_decision(self, decision: Decision) -> bool:
        """Save a decision. Returns False, writing nothing, if this exact one is already saved."""
        if decision.profile_id != self.require_profile():
            raise ValueError(f"decision for {decision.profile_id!r} saved in {self.profile_id!r}")
        key = f"{self.profile_id}/{decision.company_key}/{decision.decided_at:%Y%m%dT%H%M%S%f}"
        if self.store.get("decisions", key) is not None:
            return False
        self.put_model("decisions", key, decision)
        return True

    def decisions(self) -> list[Decision]:
        return list(self.list_models("decisions", Decision, self.require_profile() + "/"))

    def hidden_until(self, company_key: str, hide_days: int) -> date | None:
        """The day a company comes back after its latest decision, or None if it has none.

        The company is hidden on every day before the one returned. A date in the
        past means it is no longer hidden. Marks never count, only decisions.
        """
        found = self.list_models("decisions", Decision, f"{self.require_profile()}/{company_key}/")
        latest = max((d.decided_at for d in found), default=None)
        return None if latest is None else latest.date() + timedelta(days=hide_days)

    # The two lists

    def was_listed(self, company_key: str, by: datetime) -> bool:
        """Whether the company was on the short list or the more list on a day up to and
        including the day of `by`. Every saved day is looked at, not only the current lists."""
        days = self.list_models("days", DayResult, self.require_profile() + "/")
        return any(
            day.day <= by.date()
            and any(
                e.company_key == company_key
                for e in [*day.short_list, *day.more_list, *day.judged_no]
            )
            for day in days
        )

    def short_list(self) -> list[ListEntry]:
        """Companies on the short list that nobody has decided yet, strongest first."""
        return self._waiting("short")

    def more_list(self) -> list[ListEntry]:
        """Companies on the more list that nobody has decided yet."""
        return self._waiting("more")

    def judged_no_list(self, limit: int | None = None) -> list[ListEntry]:
        """Researched companies the judge said no to that nobody has decided yet, closest to a
        yes first, at most `limit` of them."""
        return closest_to_yes(self._waiting("judged_no"))[:limit]

    def awaiting_decision(
        self, company_key: str, preferred: ListName
    ) -> tuple[ListName, ListEntry] | None:
        """The company on the `preferred` list or, failing that, another list, if it awaits a
        decision. A company can be on more than one list, and where it was decided from says
        which list the decision counts for."""
        names: list[ListName] = ["short", "more", "judged_no"]
        names.sort(key=lambda name: name != preferred)
        for name in names:
            for entry in self._waiting(name):
                if entry.company_key == company_key:
                    return name, entry
        return None

    def save_day(self, result: DayResult) -> None:
        """Keep the day, and make its two lists the current ones."""
        profile = self.require_profile()
        self.put_model("days", f"{profile}/{result.day.isoformat()}", result)
        doc = {
            "short": [e.model_dump(mode="json") for e in result.short_list],
            "more": [e.model_dump(mode="json") for e in result.more_list],
            "judged_no": [e.model_dump(mode="json") for e in result.judged_no],
        }
        self.store.put(_LISTS, profile, doc)

    def day_result(self, day: date) -> DayResult | None:
        return self.get_model("days", f"{self.require_profile()}/{day.isoformat()}", DayResult)

    def latest_day(self) -> DayResult | None:
        """The most recent saved day, or None if the daily run has never been saved."""
        days = self.list_models("days", DayResult, self.require_profile() + "/")
        return max(days, key=lambda d: d.day, default=None)

    def _waiting(self, which: ListName) -> list[ListEntry]:
        doc = self.store.get(_LISTS, self.require_profile())
        # Lists saved before the judged-no list existed have none.
        saved = [] if doc is None else doc.get(which, [])
        entries = [ListEntry.model_validate(e) for e in saved]
        decided: dict[str, date] = {}
        for d in self.decisions():
            day = d.decided_at.date()
            decided[d.company_key] = max(decided.get(d.company_key, day), day)
        # A decision made on or after the day a company was listed answers that listing.
        return [
            e
            for e in entries
            if e.company_key not in decided or decided[e.company_key] < e.first_listed
        ]

    # Ads the daily run has already looked at

    def seen_ads(self) -> set[tuple[str, str, str]]:
        """Every ad the daily run has finished with, as (source, careers page, ad id)."""
        found = self.store.list("seen_ads", self.require_profile() + "/")
        return {(doc["source"], doc["board"], ad_id) for _, doc in found for ad_id in doc["ad_ids"]}

    def mark_ads_seen(self, ads: list[JobAd]) -> None:
        by_page: dict[tuple[str, str], set[str]] = {}
        for source, board, ad_id in map(ad_ref, ads):
            by_page.setdefault((source, board), set()).add(ad_id)
        for (source, board), ids in by_page.items():
            # A hash of the page, so any page name is safe as a file name.
            page = hashlib.sha256(f"{source}|{board}".encode()).hexdigest()[:32]
            key = f"{self.require_profile()}/{page}"
            doc = self.store.get("seen_ads", key) or {
                "source": source,
                "board": board,
                "ad_ids": [],
            }
            merged = sorted(set(doc["ad_ids"]) | ids)
            if merged != doc["ad_ids"]:  # each write costs money on AWS
                self.store.put("seen_ads", key, doc | {"ad_ids": merged})

    # Saved steps, so a rerun after a crash does not pay twice

    def step_result(self, run: str, step: str, key: str) -> dict | None:
        return self.store.get("step_results", self._step_key(run, step, key))

    def save_step_result(self, run: str, step: str, key: str, doc: dict) -> None:
        self.store.put("step_results", self._step_key(run, step, key), doc)

    def _step_key(self, run: str, step: str, key: str) -> str:
        return f"{self.require_profile()}/{run}/{step}/{key}"
