"""`why-now copy-workspace`: the local workspace goes to the AWS store once, so marks, piles and
cut-offs are there for the improvement run. It is complete and safe to run twice."""

import json

import pytest
from aws_fake import BUCKET, REGION, TABLE
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import copy_workspace as copy_command
from why_now.settings import load_settings
from why_now.store.aws import AwsStore
from why_now.store.local import LocalStore

DOCS = {
    ("marks", "acme/case-1"): {"answer": "yes", "reason": "Hiring."},
    ("marks", "acme/case-2"): {"answer": "no", "reason": "Too big."},
    ("cases", "acme/case-1"): {"company": "Acme"},
    ("cutoffs", "claude-1"): {"cutoff": 0.55},
    ("profiles", "acme"): {"version": "abc", "text": "id: acme"},
    ("board_ads", "greenhouse/acme"): {"ads": ["x" * 400_000]},  # too big for a record, so a file
}
NOT_COPIED = {
    ("run_lock", "current"): {"run_id": "acme/1-daily"},
    ("runs", "acme/1-daily"): {"run_id": "acme/1-daily"},
    ("settings", "overrides"): {"nightly_profiles": ["acme"]},
    ("one_time_research", "active"): {"active": True},
}


@pytest.fixture
def files(tmp_path, moto_aws):
    source = tmp_path / "local.toml"
    source.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n", encoding="utf-8")
    target = tmp_path / "aws.toml"
    target.write_text(
        f'deployment = "aws"\naws_region = "{REGION}"\n'
        f'aws_bucket = "{BUCKET}"\naws_table = "{TABLE}"\n',
        encoding="utf-8",
    )
    return source, target


@pytest.fixture
def local(tmp_path) -> LocalStore:
    store = LocalStore(tmp_path / "ws")
    for (collection, key), doc in (DOCS | NOT_COPIED).items():
        store.put(collection, key, doc)
    (tmp_path / "ws" / "traces").mkdir()
    (tmp_path / "ws" / "traces" / "log.jsonl").write_text("{}\n")  # not a document
    return store


@pytest.fixture
def aws(files) -> AwsStore:
    import boto3

    return AwsStore(
        BUCKET,
        TABLE,
        lambda service: boto3.client(service, region_name=REGION),
        inline_max_bytes=load_settings(None, env={}).aws_inline_max_bytes,
    )


def copy(files, *extra: str):
    source, target = files
    return CliRunner().invoke(
        app, ["copy-workspace", "--to", str(target), "--settings", str(source), *extra]
    )


def test_every_document_is_copied_and_the_counts_are_printed(files, local, aws):
    result = copy(files)

    assert result.exit_code == 0, result.output
    for (collection, key), doc in DOCS.items():
        assert aws.get(collection, key) == doc, (collection, key)
    assert f"Copied {len(DOCS)} documents" in result.output
    assert "0 were already there" in result.output
    assert "marks: 2" in result.output and "board_ads: 1" in result.output


def test_running_it_twice_changes_nothing_the_second_time(files, local, aws):
    copy(files)
    again = copy(files)

    assert again.exit_code == 0, again.output
    assert "Copied 0 documents" in again.output
    assert f"{len(DOCS)} were already there" in again.output
    assert {k: aws.get(*k) for k in DOCS} == DOCS


def test_a_document_already_there_is_left_alone_even_when_it_differs(files, local, aws):
    # The improvement run on AWS has moved on, so the older local copy must not overwrite it.
    aws.put("cutoffs", "claude-1", {"cutoff": 0.7})

    result = copy(files)

    assert aws.get("cutoffs", "claude-1") == {"cutoff": 0.7}
    assert "1 of them differ" in result.output and "cutoffs/claude-1" in result.output
    assert aws.get("marks", "acme/case-1") == DOCS[("marks", "acme/case-1")]


def test_what_belongs_to_one_place_is_not_copied(files, local, aws):
    result = copy(files)

    for collection, key in NOT_COPIED:
        assert aws.get(collection, key) is None, collection
    for collection in ("run_lock", "runs", "settings", "one_time_research"):
        assert collection in result.output.split("Not copied")[1]


def test_a_stop_part_way_is_finished_by_running_it_again(files, local, aws, monkeypatch):
    real = copy_command.open_store
    failing = {"left": 3}

    class Flaky:
        def __init__(self, inner):
            self.inner = inner

        def put(self, collection, key, doc):
            if failing["left"] == 0:
                raise ConnectionError("the network dropped")
            failing["left"] -= 1
            self.inner.put(collection, key, doc)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    def wrapped(settings):
        store = real(settings)
        return Flaky(store) if settings.deployment == "aws" else store

    monkeypatch.setattr(copy_command, "open_store", wrapped)
    stopped = copy(files)
    assert stopped.exit_code != 0
    assert "the network dropped" in stopped.output

    monkeypatch.setattr(copy_command, "open_store", real)
    finished = copy(files)

    assert finished.exit_code == 0, finished.output
    assert {k: aws.get(*k) for k in DOCS} == DOCS


def test_the_target_must_be_an_aws_settings_file(files, local, tmp_path):
    source, _ = files

    result = CliRunner().invoke(
        app, ["copy-workspace", "--to", str(source), "--settings", str(source)]
    )

    assert result.exit_code != 0
    assert "aws" in result.output


def test_the_source_must_be_a_local_workspace(files, local):
    _, target = files

    result = CliRunner().invoke(
        app, ["copy-workspace", "--to", str(target), "--settings", str(target)]
    )

    assert result.exit_code != 0
    assert "local" in result.output


def test_a_missing_settings_file_is_explained(files, local, tmp_path):
    source, _ = files
    result = CliRunner().invoke(
        app,
        ["copy-workspace", "--to", str(tmp_path / "none.toml"), "--settings", str(source)],
    )
    assert result.exit_code != 0
    assert "none.toml" in result.output
