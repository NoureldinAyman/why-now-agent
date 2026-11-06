"""Saved quick look answers, one per company text, question and model version."""

import hashlib

from why_now.workspace.base import WorkspaceBase

_COLLECTION = "quick_look_answers"


class QuickLookArea(WorkspaceBase):
    def saved_quick_answer(
        self, company_key: str, state: str, question_text: str, model: str
    ) -> float | None:
        """The saved probability of yes, or None if this exact question was not asked yet."""
        doc = self.store.get(_COLLECTION, _key(company_key, state, question_text, model))
        return None if doc is None else float(doc["probability"])

    def save_quick_answer(
        self, company_key: str, state: str, question_text: str, model: str, probability: float
    ) -> None:
        key = _key(company_key, state, question_text, model)
        self.store.put(_COLLECTION, key, {"model": model, "probability": probability})


def _key(company_key: str, state: str, question_text: str, model: str) -> str:
    # A hash, so the key is safe as a file name. Any change to the text, question or model
    # gives a new key, so changed ads and edited questions are asked again.
    raw = "\x1f".join([company_key, state, question_text, model])
    return hashlib.sha256(raw.encode()).hexdigest()
