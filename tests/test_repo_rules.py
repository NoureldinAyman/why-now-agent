"""Guards for the rules that apply to the whole repo, not to one feature."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from why_now.profile import load_profile

ROOT = Path(__file__).parents[1]
PROFILES = ROOT / "examples" / "profiles"
# Code and settings. Example profiles are the only files allowed to name a product.
RUN_FILES = ("settings.toml", ".env")
CODE_PREFIXES = ("src/", "tests/", "infra/", ".github/", "examples/settings", "examples/boards")


def tracked_files(*prefixes: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a Git checkout")
    return [f for f in out.splitlines() if f.startswith(prefixes)]


def product_names() -> list[str]:
    return [load_profile(p).product_name for p in sorted(PROFILES.glob("*.yaml"))]


def test_the_main_example_profile_loads_and_is_not_public():
    profiles = [load_profile(p) for p in sorted(PROFILES.glob("*.yaml"))]
    assert profiles, "the main example profile is missing"
    assert not any(p.public for p in profiles)


def test_no_product_name_appears_in_code():
    names = [n.lower() for n in product_names()]
    for name in tracked_files(*CODE_PREFIXES):
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore").lower()
        assert not any(n in text for n in names), name


def test_no_run_data_is_tracked():
    tracked = tracked_files("workspace/", "private/", "settings.toml", ".env")
    assert not [f for f in tracked if f.startswith(("workspace/", "private/")) or f in RUN_FILES]


def test_deleting_the_example_profiles_breaks_nothing(tmp_path):
    copy = tmp_path / "repo"
    skip = shutil.ignore_patterns("__pycache__", "profiles")
    shutil.copytree(ROOT / "src", copy / "src", ignore=skip)
    shutil.copytree(ROOT / "tests", copy / "tests", ignore=skip)
    shutil.copytree(ROOT / "examples", copy / "examples", ignore=skip)
    for name in ("pyproject.toml", "README.md"):
        shutil.copy(ROOT / name, copy / name)
    assert not (copy / "examples" / "profiles").exists()
    env = os.environ | {"PYTHONPATH": str(copy / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "not live",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp={tmp_path / 'inner'}",
            "--ignore=tests/test_repo_rules.py",
        ],
        cwd=copy,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
