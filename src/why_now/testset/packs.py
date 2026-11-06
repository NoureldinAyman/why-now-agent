"""Building test case packs: research runs once per picked company, and the pack is frozen.

- Packs are saved one at a time, so a stop loses at most the company in progress.
- A case that already has a saved pack is skipped, so a rerun never pays twice.
- While the build runs, the workspace's one-time research flag is set, so daily
  research waits rather than spending the same month's budget.
- A spent budget stops the build. What was built is kept, and the result says so.
- Any other failure is recorded against the case, which stays in the list and is
  tried again on the next run.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from why_now.ai import ResearchModel
from why_now.ai.budget import TEST_CASES, BudgetExceeded
from why_now.domain import CaseRecord, Company, Profile
from why_now.pipeline.reader import PageReader
from why_now.pipeline.research import research_company
from why_now.settings import Settings
from why_now.tracing import Tracer
from why_now.workspace import Workspace


@dataclass
class BuildResult:
    built: int = 0
    already_built: int = 0
    failed: dict[str, str] = field(default_factory=dict)  # case id to reason
    stopped: str | None = None  # why the build stopped early, if it did
    left: int = 0  # cases not tried because the build stopped


def new_case(profile_id: str, company: Company, seed: int) -> CaseRecord:
    """A case for a newly picked company. One company has one case per profile."""
    digest = hashlib.sha256(f"{profile_id}|{company.key}".encode()).hexdigest()[:16]
    return CaseRecord(
        case_id=f"case-{digest}", profile_id=profile_id, company_key=company.key, seed=seed
    )


def build_packs(
    cases: list[CaseRecord],
    workspace: Workspace,
    profile: Profile,
    model: ResearchModel,
    reader: PageReader,
    settings: Settings,
    tracer: Tracer,
    *,
    clock: Callable[[], datetime],
) -> BuildResult:
    """Build and save an evidence pack for each case that has none yet."""
    result = BuildResult()
    workspace.set_one_time_research(True)
    try:
        for i, case in enumerate(cases):
            if _has_pack(workspace, case):
                result.already_built += 1
                continue
            company = workspace.case_company(case.case_id)
            if company is None:
                _fail(workspace, result, case, "the picked company was not saved", clock)
                continue
            try:
                pack = research_company(
                    company,
                    profile,
                    model,
                    reader,
                    settings,
                    tracer,
                    category=TEST_CASES,
                    now=clock(),
                )
            except BudgetExceeded as e:
                result.stopped = f"Stopped: {e}. Packs built so far are saved."
                result.left = sum(not _has_pack(workspace, c) for c in cases[i:])
                break
            except Exception as e:
                # Recorded and tried again next run, so one company never stops the build.
                _fail(workspace, result, case, f"{type(e).__name__}: {e}", clock)
                continue
            workspace.save_pack(pack)
            workspace.save_case(case.model_copy(update={"pack_id": pack.pack_id}))
            workspace.clear_pack_failure(case.case_id)
            result.built += 1
    finally:
        workspace.set_one_time_research(False)
    return result


def _has_pack(workspace: Workspace, case: CaseRecord) -> bool:
    return case.pack_id is not None and workspace.load_pack(case.pack_id) is not None


def _fail(
    workspace: Workspace,
    result: BuildResult,
    case: CaseRecord,
    reason: str,
    clock: Callable[[], datetime],
) -> None:
    workspace.record_pack_failure(case.case_id, reason, clock())
    result.failed[case.case_id] = reason
