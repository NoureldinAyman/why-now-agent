"""The practice, check and final piles: each test case's pile is decided when it is picked.

A fixed calculation (a hash) of the pick's seed and the company's key gives the pile, in the
ratio of the pile sizes in the settings. Nothing the reviewer does, not the order of marking
and not a can't tell, can move a company, and the same seed and key always give the same
pile, so the piles can be rebuilt and shown not to be hand picked. The piles fill together
as the reviewer marks.
"""

import hashlib
from typing import Literal

from pydantic import BaseModel

from why_now.domain import CaseRecord, Mark
from why_now.settings import Settings
from why_now.workspace import Workspace

type Pile = Literal["practice", "check", "final"]
PILES: tuple[Pile, ...] = ("practice", "check", "final")


def pile_for(seed: int, company_key: str, settings: Settings) -> Pile:
    """The pile for a company picked with `seed`. It depends on nothing else."""
    sizes = (settings.practice_size, settings.check_size, settings.final_size)
    digest = hashlib.sha256(f"{seed}|{company_key}".encode()).digest()
    # 64 bits taken modulo a few hundred: the bias is far too small to see.
    point = int.from_bytes(digest[:8], "big") % sum(sizes)
    for pile, size in zip(PILES, sizes, strict=True):
        if point < size:
            return pile
        point -= size
    raise AssertionError("unreachable: the point is below the sum of the sizes")


class PileCounts(BaseModel):
    cases: int
    marked: int
    yes: int
    no: int
    cant_tell: int


class PileReport(BaseModel):
    piles: dict[Pile, PileCounts]
    no_pile: int  # cases in none of the three piles, such as ones picked before piles were set


def pile_report(workspace: Workspace) -> PileReport:
    """How full each pile is: its cases, how many are marked, and the answers given.

    Only first marks count. A repeat mark is a second look at a case already counted.
    """
    first = {m.case_id: m.answer for m in workspace.marks("first")}
    rows: dict[Pile, list[CaseRecord]] = {p: [] for p in PILES}
    no_pile = 0
    for case in workspace.cases():
        if case.pile is None or case.pile == "unsplit":
            no_pile += 1
        else:
            rows[case.pile].append(case)
    piles: dict[Pile, PileCounts] = {}
    for pile, cases in rows.items():
        answers = [first[c.case_id] for c in cases if c.case_id in first]
        piles[pile] = PileCounts(
            cases=len(cases),
            marked=len(answers),
            yes=answers.count("yes"),
            no=answers.count("no"),
            cant_tell=answers.count("cant_tell"),
        )
    return PileReport(piles=piles, no_pile=no_pile)


def loop_ready(report: PileReport, settings: Settings) -> bool:
    """Whether the check pile has enough yes answers for the improvement loop to judge a try."""
    return report.piles["check"].yes >= settings.floor_yes_per_pile


def yes_share(marks: list[Mark]) -> float:
    """The share of yes among the yes and no answers. Can't tell is left out, as it is in the
    scores. Zero when nothing was answered yes or no."""
    answered = [m for m in marks if m.answer != "cant_tell"]
    return sum(m.answer == "yes" for m in answered) / len(answered) if answered else 0.0
