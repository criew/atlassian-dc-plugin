"""End-to-end CLI tests for the Bitbucket DC scripts.

Subprocess-driven, so they exercise the same code paths a weak LLM hits:
help text, dry-run markers, missing-config clarity, unknown-alias guidance,
and token-leak prevention.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BB_SCRIPTS = REPO_ROOT / "skills" / "bitbucket-dc" / "scripts"


@pytest.fixture
def bb_runner(isolated_config, write_instances):
    """Run a Bitbucket skill script in a subprocess with isolated config."""

    def _run(script_relpath: str, *args, instances: Optional[dict] = None,
             extra_env: Optional[dict] = None, timeout: int = 30):
        if instances is not None:
            write_instances(instances)
        env = os.environ.copy()
        env["ATLASSIAN_INSTANCES_FILE"] = str(isolated_config / "instances.json")
        env["ATLASSIAN_CONFIG_DIR"] = str(isolated_config)
        # Force HOME/APPDATA into the isolated tree so the loader's fallback
        # paths can't reach the developer's real instances.json.
        env["HOME"] = str(isolated_config.parent / "home")
        env["APPDATA"] = str(isolated_config.parent / "appdata")
        if extra_env:
            env.update(extra_env)
        script = BB_SCRIPTS / script_relpath
        return subprocess.run(
            [sys.executable, str(script), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env, timeout=timeout,
        )

    return _run


INST = {"default": "x", "instances": {
    "x": {"bitbucket": {"url": "http://127.0.0.1:1", "token": "t"}},
}}


# -----------------------------------------------------------------------------
# whoami / global behaviour
# -----------------------------------------------------------------------------

class TestWhoami:
    def test_help_works_without_config(self, bb_runner):
        r = bb_runner("utility/bitbucket_user.py", "--help")
        assert r.returncode == 0
        assert "whoami" in r.stdout
        assert "search" in r.stdout

    def test_missing_config_exits_nonzero_with_clear_stderr(self, bb_runner):
        r = bb_runner("utility/bitbucket_user.py", "whoami")
        assert r.returncode != 0
        assert "error" in r.stderr.lower()
        assert "instances.json" in r.stderr

    def test_unknown_alias_lists_available(self, bb_runner):
        r = bb_runner(
            "utility/bitbucket_user.py", "whoami", "--instance", "ghost",
            instances={"default": "prod", "instances": {
                "prod": {"bitbucket": {"url": "http://x", "token": "t"}}
            }},
        )
        assert r.returncode != 0
        assert "ghost" in r.stderr
        assert "prod" in r.stderr  # show what IS available

    def test_unreachable_host_signals_failure(self, bb_runner):
        r = bb_runner("utility/bitbucket_user.py", "whoami",
                      instances=INST, timeout=20)
        assert r.returncode != 0
        assert r.stderr.strip() != ""

    def test_unreachable_host_does_not_leak_token(self, bb_runner):
        secret = "do-not-leak-this-bb-token-9z8y7"
        r = bb_runner(
            "utility/bitbucket_user.py", "whoami",
            instances={"default": "x", "instances": {
                "x": {"bitbucket": {"url": "http://127.0.0.1:1", "token": secret}}
            }},
            timeout=20,
        )
        assert secret not in r.stdout
        assert secret not in r.stderr


# -----------------------------------------------------------------------------
# Project
# -----------------------------------------------------------------------------

class TestProject:
    def test_help_lists_subcommands(self, bb_runner):
        r = bb_runner("core/bitbucket_project.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "get", "create"):
            assert sub in r.stdout

    def test_create_dry_run(self, bb_runner):
        r = bb_runner("core/bitbucket_project.py", "create",
                      "--key", "PROJ", "--name", "My Project",
                      "--description", "a test",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["dry_run"] is True and payload["executed"] is False
        assert payload["intent"]["body"]["key"] == "PROJ"
        assert payload["intent"]["body"]["name"] == "My Project"

    def test_create_dry_run_quiet_marker_on_stderr(self, bb_runner):
        r = bb_runner("core/bitbucket_project.py", "create",
                      "--key", "P", "--name", "X",
                      "--dry-run", "--quiet", instances=INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stderr


# -----------------------------------------------------------------------------
# Repo
# -----------------------------------------------------------------------------

class TestRepo:
    def test_help(self, bb_runner):
        r = bb_runner("core/bitbucket_repo.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "get", "create", "fork", "delete"):
            assert sub in r.stdout

    def test_create_dry_run_carries_default_branch(self, bb_runner):
        r = bb_runner("core/bitbucket_repo.py", "create",
                      "--project", "P", "--name", "my-repo",
                      "--default-branch", "main", "--no-forkable",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["name"] == "my-repo"
        assert body["scmId"] == "git"
        assert body["defaultBranch"] == "main"
        assert body["forkable"] is False

    def test_fork_to_personal_project_dry_run(self, bb_runner):
        r = bb_runner("core/bitbucket_repo.py", "fork",
                      "--project", "P", "--repo", "src",
                      "--target-project", "~jsmith",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["intent"]["body"]["project"]["key"] == "~jsmith"

    def test_delete_dry_run_quiet_marker(self, bb_runner):
        r = bb_runner("core/bitbucket_repo.py", "delete",
                      "--project", "P", "--repo", "r",
                      "--dry-run", "--quiet", instances=INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stderr


# -----------------------------------------------------------------------------
# Branch
# -----------------------------------------------------------------------------

class TestBranch:
    def test_help(self, bb_runner):
        r = bb_runner("core/bitbucket_branch.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "get-default", "create", "delete"):
            assert sub in r.stdout

    def test_create_uses_branch_utils_path(self, bb_runner):
        r = bb_runner("core/bitbucket_branch.py", "create",
                      "--project", "P", "--repo", "r",
                      "--name", "feature/X", "--start-point", "refs/heads/main",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        intent = json.loads(r.stdout)["intent"]
        assert "/rest/branch-utils/1.0/" in intent["path"]
        assert intent["body"]["name"] == "feature/X"
        assert intent["body"]["startPoint"] == "refs/heads/main"

    def test_delete_normalizes_to_full_ref(self, bb_runner):
        r = bb_runner("core/bitbucket_branch.py", "delete",
                      "--project", "P", "--repo", "r", "--name", "feature/X",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["name"] == "refs/heads/feature/X"


# -----------------------------------------------------------------------------
# Tag
# -----------------------------------------------------------------------------

class TestTag:
    def test_help(self, bb_runner):
        r = bb_runner("core/bitbucket_tag.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "create", "delete"):
            assert sub in r.stdout

    def test_create_dry_run(self, bb_runner):
        r = bb_runner("core/bitbucket_tag.py", "create",
                      "--project", "P", "--repo", "r",
                      "--name", "v1.0.0", "--start-point", "abc1234",
                      "--message", "Release 1.0.0",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["name"] == "v1.0.0"
        assert body["startPoint"] == "abc1234"
        assert body["message"] == "Release 1.0.0"


# -----------------------------------------------------------------------------
# Commit
# -----------------------------------------------------------------------------

class TestCommit:
    def test_help(self, bb_runner):
        r = bb_runner("core/bitbucket_commit.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "get"):
            assert sub in r.stdout


# -----------------------------------------------------------------------------
# File
# -----------------------------------------------------------------------------

class TestFile:
    def test_help(self, bb_runner):
        r = bb_runner("core/bitbucket_file.py", "--help")
        assert r.returncode == 0
        for sub in ("get-content", "list-dir", "search"):
            assert sub in r.stdout

    def test_search_rejects_invalid_type(self, bb_runner):
        r = bb_runner("core/bitbucket_file.py", "search", "TODO",
                      "--type", "nonsense", instances=INST)
        # argparse rejects pre-script with non-zero exit
        assert r.returncode != 0

    def test_search_builds_correct_post_body(self, bb_runner):
        """Verify search sends POST with nested entities structure."""
        r = bb_runner("core/bitbucket_file.py", "search", "myQuery",
                      "--type", "code", "--project", "PROJ", "--repo", "myrepo",
                      "--limit", "50", "--debug",
                      instances=INST, timeout=15)
        # Will fail to connect but debug output shows the request body
        combined = r.stdout + r.stderr
        assert '"query": "myQuery"' in combined or '"query":"myQuery"' in combined
        assert "entities" in combined
        assert "searchQuery" not in combined


# -----------------------------------------------------------------------------
# Pull request
# -----------------------------------------------------------------------------

class TestPR:
    def test_help_lists_all_subcommands(self, bb_runner):
        r = bb_runner("core/bitbucket_pr.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "get", "create", "update", "decline", "merge",
                    "diff", "add-comment", "list-comments", "approve", "unapprove"):
            assert sub in r.stdout

    def test_create_dry_run_normalizes_branch_refs(self, bb_runner):
        r = bb_runner(
            "core/bitbucket_pr.py", "create",
            "--project", "P", "--repo", "r",
            "--title", "Hello", "--from-branch", "feature/x", "--to-branch", "main",
            "--reviewer", "alice", "--reviewer", "bob",
            "--description", "body",
            "--dry-run", "--json", instances=INST,
        )
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["title"] == "Hello"
        assert body["fromRef"]["id"] == "refs/heads/feature/x"
        assert body["toRef"]["id"] == "refs/heads/main"
        assert [r["user"]["name"] for r in body["reviewers"]] == ["alice", "bob"]
        assert body["description"] == "body"

    def test_create_dry_run_quiet_marker(self, bb_runner):
        r = bb_runner(
            "core/bitbucket_pr.py", "create",
            "--project", "P", "--repo", "r",
            "--title", "x", "--from-branch", "f", "--to-branch", "main",
            "--dry-run", "--quiet", instances=INST,
        )
        assert r.returncode == 0
        assert "DRY RUN" in r.stderr

    def test_update_without_field_fails(self, bb_runner):
        r = bb_runner(
            "core/bitbucket_pr.py", "update",
            "--project", "P", "--repo", "r", "--id", "1", "--version", "0",
            instances=INST,
        )
        assert r.returncode != 0
        assert "no field" in r.stderr.lower()

    def test_merge_dry_run_carries_strategy(self, bb_runner):
        r = bb_runner(
            "core/bitbucket_pr.py", "merge",
            "--project", "P", "--repo", "r", "--id", "42", "--version", "3",
            "--strategy", "squash", "--message", "merged",
            "--dry-run", "--json", instances=INST,
        )
        assert r.returncode == 0
        intent = json.loads(r.stdout)["intent"]
        assert intent["path"].endswith("/pull-requests/42/merge")
        assert intent["body"] == {"version": 3, "message": "merged", "strategyId": "squash"}

    def test_decline_dry_run(self, bb_runner):
        r = bb_runner(
            "core/bitbucket_pr.py", "decline",
            "--project", "P", "--repo", "r", "--id", "5", "--version", "1",
            "--dry-run", "--json", instances=INST,
        )
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["intent"]["body"] == {"version": 1}
        assert "/pull-requests/5/decline" in payload["intent"]["path"]

    def test_approve_dry_run(self, bb_runner):
        r = bb_runner(
            "core/bitbucket_pr.py", "approve",
            "--project", "P", "--repo", "r", "--id", "5",
            "--dry-run", instances=INST,
        )
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "#5" in combined or " 5" in combined

    def test_add_comment_dry_run_includes_text(self, bb_runner):
        r = bb_runner(
            "core/bitbucket_pr.py", "add-comment",
            "--project", "P", "--repo", "r", "--id", "5",
            "--text", "looks good",
            "--dry-run", "--json", instances=INST,
        )
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["text"] == "looks good"


# -----------------------------------------------------------------------------
# Cross-cutting
# -----------------------------------------------------------------------------

class TestCrossCutting:
    def test_no_token_leak_in_dry_run(self, bb_runner):
        secret = "leaky-pat-DO-NOT-PRINT-555"
        r = bb_runner(
            "core/bitbucket_project.py", "create",
            "--key", "P", "--name", "X",
            "--dry-run", "--json",
            instances={"default": "x", "instances": {
                "x": {"bitbucket": {"url": "http://127.0.0.1:1", "token": secret}}
            }},
        )
        assert r.returncode == 0
        assert secret not in r.stdout
        assert secret not in r.stderr
