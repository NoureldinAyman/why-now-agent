"""The judge's documents: saved answers, the rules file and the recorded cut-off."""

import hashlib
import json

from why_now.domain import FitQuestion, RulesFile
from why_now.workspace.base import WorkspaceBase


class JudgeArea(WorkspaceBase):
    def saved_answer(self, pack_id: str, question: FitQuestion, model: str) -> float | None:
        """The probability `model` gave for `question` on this evidence pack, if asked before.

        Only what the model is shown counts: the question's id, its text, and what
        yes and no mean. Its kind and direction can change without asking again.
        """
        doc = self.store.get("answers", _answer_key(pack_id, question, model))
        return None if doc is None else float(doc["probability"])

    def save_answer(
        self, pack_id: str, question: FitQuestion, model: str, probability: float
    ) -> None:
        doc = {
            "pack_id": pack_id,
            "model": model,
            "question_id": question.id,
            "question": question.text,
            "yes_means": question.yes_means,
            "no_means": question.no_means,
            "probability": probability,
        }
        self.store.put("answers", _answer_key(pack_id, question, model), doc)

    def load_rules(self) -> RulesFile:
        """The profile's rules file, or an empty one before anything is learned."""
        profile_id = self.require_profile()
        rules = self.get_model("rules", profile_id, RulesFile)
        return rules if rules is not None else RulesFile(profile_id=profile_id)

    def save_rules(self, rules: RulesFile) -> None:
        if rules.profile_id != self.require_profile():
            raise ValueError(f"rules for {rules.profile_id!r} saved in {self.profile_id!r}")
        self.put_model("rules", rules.profile_id, rules)

    def save_cutoff(self, model: str, cutoff: float) -> None:
        """Record the cut-off chosen for this profile's judge model on the practice pile."""
        self.store.put("cutoffs", self._cutoff_key(model), {"model": model, "cutoff": cutoff})

    def cutoff(self, model: str) -> float | None:
        doc = self.store.get("cutoffs", self._cutoff_key(model))
        return None if doc is None else float(doc["cutoff"])

    def _cutoff_key(self, model: str) -> str:
        return f"{self.require_profile()}/{model}"


def _answer_key(pack_id: str, question: FitQuestion, model: str) -> str:
    shown = json.dumps([question.id, question.text, question.yes_means, question.no_means])
    return f"{pack_id}/{model}/{hashlib.sha256(shown.encode()).hexdigest()[:32]}"
