"""Test cases, their frozen evidence packs, the picks that made them, and the one-time flag.

Cases, packs, failures and picks are kept per profile. The one-time research
flag is kept once for the whole workspace, because the budget it protects is shared.
"""

from datetime import datetime

from why_now.domain import CaseRecord, Company, EvidencePack
from why_now.workspace.base import WorkspaceBase

_FLAG = ("flags", "one_time_research")


class CasesArea(WorkspaceBase):
    def save_case(self, case: CaseRecord, company: Company | None = None) -> None:
        """Save a case. The company, with the ads it was picked with, is saved once at the pick."""
        if case.profile_id != self.require_profile():
            raise ValueError(f"case for {case.profile_id!r} saved in {self.profile_id!r}")
        self.put_model("cases", self._key(case.case_id), case)
        if company is not None:
            self.put_model("case_companies", self._key(case.case_id), company)

    def cases(self) -> list[CaseRecord]:
        return list(self.list_models("cases", CaseRecord, self.require_profile() + "/"))

    def case_company(self, case_id: str) -> Company | None:
        return self.get_model("case_companies", self._key(case_id), Company)

    def save_pack(self, pack: EvidencePack) -> None:
        """Save a frozen evidence pack. A saved pack is never changed."""
        if pack.profile_id != self.require_profile():
            raise ValueError(f"pack for {pack.profile_id!r} saved in {self.profile_id!r}")
        if self.store.get("packs", self._key(pack.pack_id)) is not None:
            raise ValueError(f"evidence pack {pack.pack_id} is frozen and already saved")
        self.put_model("packs", self._key(pack.pack_id), pack)

    def load_pack(self, pack_id: str) -> EvidencePack | None:
        return self.get_model("packs", self._key(pack_id), EvidencePack)

    def record_pack_failure(self, case_id: str, reason: str, at: datetime) -> None:
        doc = {"case_id": case_id, "reason": reason, "at": at.isoformat()}
        self.store.put("pack_failures", self._key(case_id), doc)

    def clear_pack_failure(self, case_id: str) -> None:
        self.store.delete("pack_failures", self._key(case_id))

    def pack_failures(self) -> dict[str, str]:
        """The reason research last failed, for each case still without a pack."""
        found = self.store.list("pack_failures", self.require_profile() + "/")
        return {doc["case_id"]: doc["reason"] for _, doc in found}

    def record_pick(self, seed: int, n: int, picked: list[str], at: datetime) -> None:
        """Add a pick to the profile's record of picks, so every seed used is kept."""
        key = self.require_profile()
        doc = self.store.get("picks", key) or {"picks": []}
        doc["picks"].append({"seed": seed, "n": n, "picked": picked, "at": at.isoformat()})
        self.store.put("picks", key, doc)

    def picks(self) -> list[dict]:
        doc = self.store.get("picks", self.require_profile())
        return [] if doc is None else doc["picks"]

    def one_time_research_active(self) -> bool:
        """True while one-time research, such as building test case packs, is running."""
        doc = self.store.get(*_FLAG)
        return bool(doc and doc["active"])

    def set_one_time_research(self, active: bool) -> None:
        self.store.put(*_FLAG, {"active": active})

    def _key(self, name: str) -> str:
        return f"{self.require_profile()}/{name}"
