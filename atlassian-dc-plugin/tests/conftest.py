"""Shared pytest fixtures for the test suite."""
import json
import os
import sys
from pathlib import Path
from typing import Optional

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = PLUGIN_ROOT / "shared"
SCRIPTS_ROOT = PLUGIN_ROOT / "skills" / "jira-dc" / "scripts"
SKILLS_DIR = PLUGIN_ROOT / "skills"

sys.path.insert(0, str(SHARED_DIR))


def _resolve_script_path(relpath: str) -> Path:
    """Map 'core/jira_x.py' -> jira-dc; 'core/confluence_x.py' -> confluence-dc;
    'core/bitbucket_x.py' -> bitbucket-dc. The fallback (no product prefix in
    the filename) keeps the legacy jira-dc default so old tests still work.
    """
    name = Path(relpath).name
    if name.startswith("confluence_"):
        return SKILLS_DIR / "confluence-dc" / "scripts" / relpath
    if name.startswith("bitbucket_"):
        return SKILLS_DIR / "bitbucket-dc" / "scripts" / relpath
    return SCRIPTS_ROOT / relpath


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point ATLASSIAN_INSTANCES_FILE / ATLASSIAN_CONFIG_DIR at a tmp dir.

    Also clears ATLASSIAN_INSTANCE so tests don't see env leakage from the
    developer's shell.
    """
    cfg_dir = tmp_path / "atlassian"
    cfg_dir.mkdir()
    monkeypatch.setenv("ATLASSIAN_INSTANCES_FILE", str(cfg_dir / "instances.json"))
    monkeypatch.setenv("ATLASSIAN_CONFIG_DIR", str(cfg_dir))
    monkeypatch.delenv("ATLASSIAN_INSTANCE", raising=False)
    # Make sure HOME/APPDATA fallback paths cannot match.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return cfg_dir


@pytest.fixture
def write_instances(isolated_config):
    """Helper: write an instances.json with the given dict."""
    def _write(data: dict) -> Path:
        path = isolated_config / "instances.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path
    return _write


@pytest.fixture
def write_rules(isolated_config):
    """Helper: write rules/<alias>.md with the given content."""
    def _write(alias: str, content: str) -> Path:
        rules_dir = isolated_config / "rules"
        rules_dir.mkdir(exist_ok=True)
        path = rules_dir / f"{alias}.md"
        path.write_text(content, encoding="utf-8")
        return path
    return _write


@pytest.fixture
def script_runner(isolated_config, write_instances):
    """Run a plugin script in a subprocess with the test config in scope.

    Returns a callable: runner(script_relpath, *args, instances=...) -> CompletedProcess
    """
    import subprocess

    def _run(script_relpath: str, *args, instances: Optional[dict] = None,
             extra_env: Optional[dict] = None, timeout: int = 30):
        if instances is not None:
            write_instances(instances)
        env = os.environ.copy()
        env["ATLASSIAN_INSTANCES_FILE"] = str(isolated_config / "instances.json")
        env["ATLASSIAN_CONFIG_DIR"] = str(isolated_config)
        if extra_env:
            env.update(extra_env)
        script = _resolve_script_path(script_relpath)
        return subprocess.run(
            [sys.executable, str(script), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env, timeout=timeout,
        )
    return _run
