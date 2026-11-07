"""Splitting marked test cases into the practice, check and final piles.

The split is fixed by a seed, so it can be repeated and shown not to be hand picked. Yes
and no answers are shuffled apart and dealt out in step, so every pile gets its share of
yes answers. Cases the reviewer could not judge, and cases not yet marked, are in no pile.
"""

import random

from pydantic import BaseModel

from why_now.domain import CaseRecord, Mark
from why_now.settings import Settings
from why_now.workspace import Workspace

PILES = ("practice", "check", "final")
# The piles whose yes answers decide a result, so a shortfall there matters.
MEASURED = ("check", "final")


class PilesFrozen(Exception):
    """The improvement loop has started, so the piles can no longer be split again."""


class PileReport(BaseModel):
    counts: dict[str, int]
    yes_counts: dict[str, int]
    short_piles: list[str]
    yes_share: float


def yes_share(marks: list[Mark]) -> float:
    """The share of yes among the yes and no answers. Can't tell is left out, as it is in the
    piles. Zero when nothing was answered yes or no."""
    answered = [m for m in marks if m.answer != "cant_tell"]
    return sum(m.answer == "yes" for m in answered) / len(answered) if answered else 0.0


def assign_piles(
    cases: list[CaseRecord], marks: dict[str, Mark], seed: int, settings: Settings
) -> tuple[list[CaseRecord], PileReport]:
    """Give each usable case a pile, and return every case, in the order given.

    A usable case has a yes or no mark, and is the only one piled for its company. When more
    are marked than the piles hold, the extra are left out at random but in proportion, so the
    share of yes does not move. When fewer are marked, the piles keep their proportions at a
    smaller size.
    """
    sizes = {
        "practice": settings.practice_size,
        "check": settings.check_size,
        "final": settings.final_size,
    }
    usable: list[CaseRecord] = []
    companies: set[str] = set()
    for c in sorted(cases, key=lambda c: c.case_id):  # one case per company, the same one each time
        answered = c.case_id in marks and marks[c.case_id].answer != "cant_tell"
        if answered and c.company_key not in companies:
            companies.add(c.company_key)
            usable.append(c)
    yes = sorted(c.case_id for c in usable if marks[c.case_id].answer == "yes")
    no = sorted(c.case_id for c in usable if marks[c.case_id].answer == "no")
    rng = random.Random(seed)
    rng.shuffle(yes)
    rng.shuffle(no)

    capacity = sum(sizes.values())
    take_yes, take_no = len(yes), len(no)
    if take_yes + take_no > capacity:
        take_yes = (capacity * len(yes) * 2 + len(usable)) // (len(usable) * 2)  # rounded
        take_yes = max(take_yes, capacity - len(no))
        take_yes = min(take_yes, len(yes))
        take_no = capacity - take_yes
    pile_sizes = _share_out(take_yes + take_no, sizes)
    yes_quota = _share_out(take_yes, pile_sizes)

    pile_of: dict[str, str] = {}
    next_yes = next_no = 0
    for pile in PILES:
        for case_id in yes[next_yes : next_yes + yes_quota[pile]]:
            pile_of[case_id] = pile
        next_yes += yes_quota[pile]
        no_here = pile_sizes[pile] - yes_quota[pile]
        for case_id in no[next_no : next_no + no_here]:
            pile_of[case_id] = pile
        next_no += no_here

    result = [
        c.model_copy(
            update={
                "pile": pile_of.get(c.case_id),
                "check_version": 1 if pile_of.get(c.case_id) == "check" else None,
            }
        )
        for c in cases
    ]
    counts: dict[str, int] = dict.fromkeys(PILES, 0)
    yes_counts: dict[str, int] = dict.fromkeys(PILES, 0)
    for c in result:
        if c.pile in counts:
            counts[c.pile] += 1
            yes_counts[c.pile] += marks[c.case_id].answer == "yes"
    short = [p for p in MEASURED if yes_counts[p] < settings.target_yes_per_pile]
    given = [marks[c.case_id] for c in result if c.case_id in marks]
    return result, PileReport(
        counts=counts, yes_counts=yes_counts, short_piles=short, yes_share=yes_share(given)
    )


def _share_out(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Split `total` in proportion to `weights` using whole numbers, with the biggest
    leftovers rounded up, so the parts always add up to `total`."""
    whole = sum(weights.values())
    parts = {k: total * w // whole for k, w in weights.items()}
    by_leftover = sorted(
        weights, key=lambda k: (-(total * weights[k] % whole), list(weights).index(k))
    )
    for k in by_leftover[: total - sum(parts.values())]:
        parts[k] += 1
    return parts


def split_piles(workspace: Workspace, seed: int, settings: Settings) -> PileReport:
    """Split this profile's first-round marked cases into piles and save the result."""
    if workspace.loop_started():
        raise PilesFrozen("The improvement loop has started, so the piles are frozen.")
    marks = {m.case_id: m for m in workspace.marks("first")}
    result, report = assign_piles(workspace.cases(), marks, seed, settings)
    for case in result:
        workspace.save_case(case)
    return report


def refresh_check_pile(workspace: Workspace, new_cases: list[CaseRecord]) -> int:
    """Move the old check pile to practice and make `new_cases` the next version of the check
    pile. Returns the new version number. It is the one change allowed once the loop has
    started, and it never touches the final pile."""
    cases = workspace.cases()
    in_a_pile = {c.company_key for c in cases if c.pile is not None}
    clashes = sorted(c.company_key for c in new_cases if c.company_key in in_a_pile)
    if clashes:
        raise ValueError(
            f"{len(clashes)} companies are already in a pile, for example {clashes[0]}"
        )
    version = max((c.check_version or 0 for c in cases if c.pile == "check"), default=0) + 1
    for old in (c for c in cases if c.pile == "check"):
        workspace.save_case(old.model_copy(update={"pile": "practice", "check_version": None}))
    for new in new_cases:
        workspace.save_case(new.model_copy(update={"pile": "check", "check_version": version}))
    return version
