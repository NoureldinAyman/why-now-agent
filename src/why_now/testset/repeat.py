"""Repeat marking: the reviewer marks some companies again, about a week later and without
seeing the first answer. How often the two answers match shows about how high any agent
could score, because the agent is graded against one person's judgement."""

import random
from datetime import date, timedelta

from why_now.domain import Mark


def can_repeat(marks: list[Mark], today: date, after_days: int) -> list[str]:
    """The cases that could be marked again, sorted. Only first-round yes and no answers given
    at least `after_days` ago can be, because a fresh memory would flatter the reviewer and a
    can't-tell has nothing to compare."""
    cutoff = today - timedelta(days=after_days)
    return sorted(
        m.case_id
        for m in marks
        if m.round == "first" and m.answer != "cant_tell" and m.marked_at.date() <= cutoff
    )


def pick_repeats(marks: list[Mark], n: int, seed: int, today: date, after_days: int) -> list[str]:
    """Pick up to `n` cases to mark again, from those that `can_repeat`. Fewer than `n` come
    back if fewer are old enough."""
    old_enough = can_repeat(marks, today, after_days)
    return sorted(random.Random(seed).sample(old_enough, min(n, len(old_enough))))


def agreement_counts(first: list[Mark], repeat: list[Mark]) -> tuple[int, int]:
    """How many cases got the same answer twice, and how many cases were compared. A case
    is compared only if it has a yes or no in both rounds."""
    before = {m.case_id: m.answer for m in first if m.answer != "cant_tell"}
    agreed = compared = 0
    for m in repeat:
        if m.answer != "cant_tell" and m.case_id in before:
            compared += 1
            agreed += before[m.case_id] == m.answer
    return agreed, compared


def agreement(first: list[Mark], repeat: list[Mark]) -> float:
    """The share of compared cases that got the same answer both times."""
    agreed, compared = agreement_counts(first, repeat)
    if compared == 0:
        raise ValueError("There is nothing to compare: no case has a yes or no in both rounds.")
    return agreed / compared
