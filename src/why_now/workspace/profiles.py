"""Profiles kept in the workspace, so a run or the review page finds one by its id.

The newest text of each profile is kept under its id. Every version is also kept under its
hash, so the version recorded on a mark or a decision can always be read again.
"""

from why_now.domain import Profile
from why_now.profile import parse_profile
from why_now.store import split_name
from why_now.workspace.base import WorkspaceBase

_CURRENT = "profiles"
_VERSIONS = "profile_versions"


def is_safe_id(name: str) -> bool:
    """Whether `name` is one safe name, so it can name where a profile is kept."""
    try:
        return len(split_name(name)) == 1
    except ValueError:
        return False


class ProfilesArea(WorkspaceBase):
    def save_profile(self, profile: Profile, text: str) -> None:
        """Keep `text` as the newest text of this profile, and as its version. A version
        already kept is never rewritten. The id must be one safe name, because it names
        where the profile is kept."""
        if not is_safe_id(profile.id):
            raise ValueError(f"profile id {profile.id!r} must be a single safe name")
        version_key = f"{profile.id}/{profile.version}"
        if self.store.get(_VERSIONS, version_key) is None:
            self.store.put(_VERSIONS, version_key, {"text": text})
        self.store.put(_CURRENT, profile.id, {"version": profile.version, "text": text})

    def profile(self, profile_id: str) -> Profile | None:
        """The newest saved profile with this id, or None if there is none."""
        text = self.profile_text(profile_id)
        return None if text is None else parse_profile(text, f"workspace profile {profile_id}")

    def profile_text(self, profile_id: str) -> str | None:
        """The newest text saved for this profile, as it was written."""
        doc = self.store.get(_CURRENT, profile_id) if is_safe_id(profile_id) else None
        return None if doc is None else str(doc["text"])

    def profile_ids(self) -> list[str]:
        return sorted(key for key, _ in self.store.list(_CURRENT))

    def profile_version(self, profile_id: str, version: str) -> Profile | None:
        """This profile as it was at `version`, or None if that version was never saved."""
        doc = (
            self.store.get(_VERSIONS, f"{profile_id}/{version}") if is_safe_id(profile_id) else None
        )
        if doc is None:
            return None
        return parse_profile(str(doc["text"]), f"workspace profile {profile_id} {version[:8]}")
