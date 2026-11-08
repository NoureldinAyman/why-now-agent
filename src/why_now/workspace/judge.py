"""The judge's documents: saved answers, the rules file and the recorded cut-off."""

import hashlib
import json

from why_now.domain import FitQuestion, RulesFile
from why_now.workspace.base import WorkspaceBase


class JudgeArea(WorkspaceBase):
    def saved_answer(self, pack_id: str, question: FitQuestion, answer_key: str) -> float | None:
        """The probability saved for `question` on this evidence pack, if asked before.

        `answer_key` names the model, effort and prompt version, so a change to any
        of them asks again. Only what the model is shown counts as the question: its
        id, its text, and what yes and no mean. Its kind and direction can change
        without asking again.
        """
        doc = self.store.get("answers", _answer_doc_id(pack_id, question, answer_key))
        return None if doc is None else float(doc["probability"])

    def save_answer(
        self, pack_id: str, question: FitQuestion, answer_key: str, probability: float
    ) -> None:
        doc = {
            "pack_id": pack_id,
            "answer_key": answer_key,
            "question_id": question.id,
            "question": question.text,
            "yes_means": question.yes_means,
            "no_means": question.no_means,
            "probability": probability,
        }
        self.store.put("answers", _answer_doc_id(pack_id, question, answer_key), doc)

    def load_rules(self) -> RulesFile:
        """The profile's rules file, or an empty one before anything is learned."""
        profile_id = self.require_profile()
        rules = self.get_model("rules", profile_id, RulesFile)
        return rules if rules is not None else RulesFile(profile_id=profile_id)

    def save_rules(self, rules: RulesFile) -> None:
        if rules.profile_id != self.require_profile():
            raise ValueError(f"rules for {rules.profile_id!r} saved in {self.profile_id!r}")
        self.put_model("rules", rules.profile_id, rules)

    def save_cutoff(self, answer_key: str, cutoff: float) -> None:
        """Record the cut-off chosen on the practice pile for this profile's judge.

        Kept per `answer_key`, the judge's model, effort and prompt version, because
        a cut-off fits the probabilities of the setup it was chosen for.
        """
        doc = {"answer_key": answer_key, "cutoff": cutoff}
        self.store.put("cutoffs", self._cutoff_key(answer_key), doc)

    def cutoff(self, answer_key: str) -> float | None:
        doc = self.store.get("cutoffs", self._cutoff_key(answer_key))
        return None if doc is None else float(doc["cutoff"])

    def _cutoff_key(self, answer_key: str) -> str:
        return f"{self.require_profile()}/{answer_key}"


def _answer_doc_id(pack_id: str, question: FitQuestion, answer_key: str) -> str:
    shown = json.dumps([question.id, question.text, question.yes_means, question.no_means])
    return f"{pack_id}/{answer_key}/{hashlib.sha256(shown.encode()).hexdigest()[:32]}"
