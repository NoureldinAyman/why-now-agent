"""The workspace: everything a run produces, kept apart from the code.

Each area adds its methods in its own mixin file in this package, and is listed
once in `Workspace` below. Adding a method to an area only touches that area's file.
"""

from why_now.workspace.base import WorkspaceBase
from why_now.workspace.cases import CasesArea
from why_now.workspace.judge import JudgeArea
from why_now.workspace.quick_look import QuickLookArea
from why_now.workspace.read import ReadArea


class Workspace(CasesArea, QuickLookArea, ReadArea, JudgeArea, WorkspaceBase):
    """Add each area's mixin before `WorkspaceBase`."""


__all__ = ["Workspace"]
