"""Copying the local workspace into another store, once, so the AWS run has what the person made
on their own computer: marks, piles, cut-offs, rules and the job ads they were judged on.

It is safe to run twice. A document already in the target is never overwritten, because the
AWS copy may have moved on since (an improvement run there changes rules, tries and cut-offs).
A stop part way is finished by running it again. Documents that belong to one place are left
out, each for a reason given below.
"""

from dataclasses import dataclass, field

from why_now.store import Store
from why_now.store.local import LocalStore

# Each place keeps its own of these, so copying them would do harm.
NOT_COPIED = {
    "run_lock": "a lock held by a run on this computer would block the runs on AWS",
    "runs": "the notes of runs on this computer are not runs on AWS",
    "settings": "the settings stored on this computer would change the night list on AWS",
    "one_time_research": "a flag left set here would make research on AWS wait",
}


@dataclass
class CopyReport:
    copied: dict[str, int] = field(default_factory=dict)  # documents copied, by collection
    already_there: int = 0
    differing: list[str] = field(default_factory=list)  # "collection/key" left alone
    not_copied: dict[str, int] = field(default_factory=dict)  # documents left out, by collection


class CopyStopped(Exception):
    """The copy stopped at one document. Running it again carries on from there."""

    def __init__(self, where: str, cause: Exception):
        super().__init__(f"stopped at {where}: {cause}")
        self.where = where


def copy_workspace(
    source: LocalStore, target: Store, report: CopyReport | None = None
) -> CopyReport:
    """Copy every document of `source` that `target` does not have yet. `report` is filled in as
    it goes, so a stop still says how far it got."""
    report = report if report is not None else CopyReport()
    for collection in source.collections():
        if collection in NOT_COPIED:
            report.not_copied[collection] = sum(1 for _ in source.list(collection))
            continue
        for key, doc in source.list(collection):
            where = f"{collection}/{key}"
            try:
                there = target.get(collection, key)
                if there is None:
                    target.put(collection, key, doc)
                    report.copied[collection] = report.copied.get(collection, 0) + 1
                    continue
            except Exception as e:
                raise CopyStopped(where, e) from e
            report.already_there += 1
            if there != doc:
                report.differing.append(where)
    return report
