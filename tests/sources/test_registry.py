"""Lever and Greenhouse read together through the registry and the unchanged read step."""

import json
from datetime import date
from pathlib import Path

import httpx

from why_now.pipeline.read import read_all
from why_now.settings import Settings
from why_now.sources.boards import BoardList
from why_now.sources.polite import PoliteClient
from why_now.sources.registry import SOURCES
from why_now.workspace import Workspace

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 5)


def answer(request: httpx.Request) -> httpx.Response:
    fixture = "greenhouse_jobs.json" if "greenhouse" in request.url.host else "lever_postings.json"
    return httpx.Response(200, json=json.loads((FIXTURES / fixture).read_text()))


def test_both_sources_are_known_by_name():
    assert {"greenhouse", "lever"} <= set(SOURCES)


def test_lever_and_greenhouse_read_side_by_side_with_their_own_clients(store):
    http = httpx.Client(transport=httpx.MockTransport(answer))
    clients = {
        name: PoliteClient(http, 0, sleep=lambda s: None, attempts=1, max_retry_wait_seconds=0)
        for name in ("greenhouse", "lever")
    }
    sources = [SOURCES[name](clients[name]) for name in clients]
    workspace = Workspace(store)
    boards = {
        "greenhouse": BoardList(workspace, "greenhouse", ["acme"], Settings()),
        "lever": BoardList(workspace, "lever", ["acme-inc"], Settings()),
    }
    result = read_all(sources, boards, workspace, TODAY, outage_share=0.9)
    assert {a.source for a in result.ads} == {"greenhouse", "lever"}
    assert len(result.ads) == 4 and result.failed_boards == {}
    # Acme on Greenhouse and acme-inc on Lever are different page names, so two companies here.
    assert sorted(result.open_job_counts) == ["acme", "acmeinc"]
