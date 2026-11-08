"""Saved quick look answers, one per company text, question and answer key."""

import hashlib

from why_now.workspace.base import WorkspaceBase

_COLLECTION = "quick_look_answers"


class QuickLookArea(WorkspaceBase):
    def saved_quick_answer(
        self, company_key: str, state: str, question_text: str, answer_key: str
    ) -> float | None:
        """The saved probability of yes, or None if this exact question was not asked yet.

        `answer_key` names the model, effort and prompt version, so a change to any
        of them asks again.
        """
        doc = self.store.get(_COLLECTION, _key(company_key, state, question_text, answer_key))
        return None if doc is None else float(doc["probability"])

    def save_quick_answer(
        self,
        company_key: str,
        state: str,
        question_text: str,
        answer_key: str,
        probability: float,
    ) -> None:
        key = _key(company_key, state, question_text, answer_key)
        self.store.put(_COLLECTION, key, {"answer_key": answer_key, "probability": probability})


def _key(company_key: str, state: str, question_text: str, answer_key: str) -> str:
    # A hash, so the key is safe as a file name. Any change to the text, question, model,
    # effort or prompt version gives a new key, so all of them are asked again.
    raw = "\x1f".join([company_key, state, question_text, answer_key])
    return hashlib.sha256(raw.encode()).hexdigest()
