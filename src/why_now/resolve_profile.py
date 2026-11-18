"""Find the profile a command was asked to use: a file, or an id kept in the workspace."""

from pathlib import Path

from why_now.domain import Profile
from why_now.profile import ProfileError, load_profile
from why_now.store import Store
from why_now.workspace import Workspace


def upload_profile_file(path: Path, store: Store) -> Profile:
    """Check the profile file and save it in the workspace, keeping older versions. Raises
    ProfileError for a file the loader refuses, and ValueError for an id that cannot name a
    place in the workspace."""
    profile = load_profile(path)
    Workspace(store).save_profile(profile, path.read_text(encoding="utf-8"))
    return profile


def resolve_profile(arg: str | Path, store: Store) -> Profile:
    """The profile in the file `arg`, if there is such a file. Anything else is the id of a
    profile in the workspace, so a file in the working folder named like an id wins."""
    if Path(arg).is_file():
        return load_profile(Path(arg))
    profile = Workspace(store).profile(str(arg))
    if profile is None:
        raise ProfileError(
            f"no profile file or workspace profile named {arg}. "
            "Upload one with: why-now profile upload FILE"
        )
    return profile
