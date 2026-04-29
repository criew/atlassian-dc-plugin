"""Reproducible CLI tests for the Confluence DC scripts.

These tests do NOT require a running Confluence — they exercise:
  - argparse / help output
  - dry-run markers (must show even with --quiet)
  - clear errors on missing inputs
  - error mapping when no config is present

For HTTP-side correctness see test_confluence_client.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CONFLUENCE_SCRIPTS = PLUGIN_ROOT / "skills" / "confluence-dc" / "scripts"


@pytest.fixture
def cf_runner(isolated_config, write_instances):
    """Subprocess runner pinned at the confluence-dc scripts root."""

    def _run(script_relpath: str, *args, instances: dict | None = None,
             extra_env: dict | None = None, timeout: int = 30):
        if instances is not None:
            write_instances(instances)
        env = os.environ.copy()
        env["ATLASSIAN_INSTANCES_FILE"] = str(isolated_config / "instances.json")
        env["ATLASSIAN_CONFIG_DIR"] = str(isolated_config)
        if extra_env:
            env.update(extra_env)
        script = CONFLUENCE_SCRIPTS / script_relpath
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, env=env, timeout=timeout,
        )
    return _run


INST = {
    "default": "x",
    "instances": {"x": {"confluence": {"url": "http://127.0.0.1:1", "token": "t"}}},
}


# -----------------------------------------------------------------------------
# whoami / config
# -----------------------------------------------------------------------------

class TestWhoamiAndConfig:
    def test_help_works_without_config(self, cf_runner):
        r = cf_runner("utility/confluence_user.py", "whoami", "--help")
        assert r.returncode == 0
        assert "whoami" in r.stdout

    def test_whoami_without_config_fails_clearly(self, cf_runner):
        r = cf_runner("utility/confluence_user.py", "whoami")
        assert r.returncode != 0
        assert "instances.json" in r.stderr
        assert "error" in r.stderr.lower()

    def test_user_help_lists_subcommands(self, cf_runner):
        r = cf_runner("utility/confluence_user.py", "--help")
        assert r.returncode == 0
        for sub in ("whoami", "search"):
            assert sub in r.stdout


# -----------------------------------------------------------------------------
# Space
# -----------------------------------------------------------------------------

class TestSpace:
    def test_help(self, cf_runner):
        r = cf_runner("core/confluence_space.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "get", "create"):
            assert sub in r.stdout

    def test_create_dry_run(self, cf_runner):
        r = cf_runner("core/confluence_space.py", "create",
                      "--key", "DOCS", "--name", "Docs Space",
                      "--description", "Space for docs",
                      "--dry-run", instances=INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "DOCS" in combined and "Docs Space" in combined

    def test_create_dry_run_quiet_still_visible_on_stderr(self, cf_runner):
        r = cf_runner("core/confluence_space.py", "create",
                      "--key", "DOCS", "--name", "Docs",
                      "--dry-run", "--quiet", instances=INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stderr  # critical — quiet must NOT silence dry-run


# -----------------------------------------------------------------------------
# Page
# -----------------------------------------------------------------------------

class TestPage:
    def test_help_lists_subcommands(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "--help")
        assert r.returncode == 0
        for sub in ("get", "create", "update", "delete", "children", "ancestors"):
            assert sub in r.stdout

    def test_create_dry_run_includes_storage_format_payload(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "create",
                      "--space", "DOCS", "--title", "My Page",
                      "--content", "<p>hello</p>",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        body = payload["intent"]["body"]
        assert body["type"] == "page"
        assert body["title"] == "My Page"
        assert body["space"] == {"key": "DOCS"}
        assert body["body"]["storage"]["value"] == "<p>hello</p>"
        assert body["body"]["storage"]["representation"] == "storage"

    def test_create_with_parent_includes_ancestors(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "create",
                      "--space", "DOCS", "--title", "Child",
                      "--content", "<p>hi</p>", "--parent", "12345",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["ancestors"] == [{"id": "12345"}]

    def test_blogpost_type(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "create",
                      "--space", "DOCS", "--title", "Recap",
                      "--content", "<p>recap</p>",
                      "--type", "blogpost",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["type"] == "blogpost"

    def test_get_without_id_or_title_fails(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "get", instances=INST)
        assert r.returncode != 0
        assert "id" in r.stderr.lower() and "title" in r.stderr.lower()

    def test_update_without_fields_fails(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "update", "12345",
                      instances=INST)
        assert r.returncode != 0
        assert "no field" in r.stderr.lower()

    def test_update_dry_run_announces_version_bump(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "update", "12345",
                      "--title", "New Title",
                      "--dry-run", instances=INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "version" in combined.lower()
        assert "12345" in combined

    def test_delete_dry_run(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "delete", "12345",
                      "--dry-run", instances=INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stdout + r.stderr

    def test_delete_purge_dry_run_passes_status_trashed(self, cf_runner):
        r = cf_runner("core/confluence_page.py", "delete", "12345",
                      "--purge", "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        params = payload["intent"].get("params") or {}
        assert params.get("status") == "trashed"


# -----------------------------------------------------------------------------
# Search
# -----------------------------------------------------------------------------

class TestSearch:
    def test_help(self, cf_runner):
        r = cf_runner("core/confluence_search.py", "--help")
        assert r.returncode == 0
        assert "CQL" in r.stdout or "cql" in r.stdout.lower()

    def test_missing_query_fails(self, cf_runner):
        r = cf_runner("core/confluence_search.py", instances=INST)
        assert r.returncode != 0


# -----------------------------------------------------------------------------
# Comment
# -----------------------------------------------------------------------------

class TestComment:
    def test_help(self, cf_runner):
        r = cf_runner("workflow/confluence_comment.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "add", "delete"):
            assert sub in r.stdout

    def test_add_dry_run(self, cf_runner):
        r = cf_runner("workflow/confluence_comment.py", "add", "12345",
                      "--body", "<p>nice</p>",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["type"] == "comment"
        assert body["container"] == {"id": "12345", "type": "page"}
        assert body["body"]["storage"]["value"] == "<p>nice</p>"

    def test_add_reply_includes_ancestors(self, cf_runner):
        r = cf_runner("workflow/confluence_comment.py", "add", "12345",
                      "--body", "<p>reply</p>", "--parent", "999",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["ancestors"] == [{"id": "999"}]

    def test_delete_dry_run_quiet_visible_on_stderr(self, cf_runner):
        r = cf_runner("workflow/confluence_comment.py", "delete", "999",
                      "--dry-run", "--quiet", instances=INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stderr


# -----------------------------------------------------------------------------
# Label
# -----------------------------------------------------------------------------

class TestLabel:
    def test_help(self, cf_runner):
        r = cf_runner("workflow/confluence_label.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "add", "remove"):
            assert sub in r.stdout

    def test_add_multiple_labels_dry_run(self, cf_runner):
        r = cf_runner("workflow/confluence_label.py", "add", "12345",
                      "--label", "alpha", "--label", "beta",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body == [
            {"prefix": "global", "name": "alpha"},
            {"prefix": "global", "name": "beta"},
        ]

    def test_remove_dry_run_uses_label_path(self, cf_runner):
        r = cf_runner("workflow/confluence_label.py", "remove", "12345",
                      "--label", "alpha",
                      "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        path = json.loads(r.stdout)["intent"]["path"]
        assert path == "/rest/api/content/12345/label/alpha"


# -----------------------------------------------------------------------------
# Attachment
# -----------------------------------------------------------------------------

class TestAttachment:
    def test_help(self, cf_runner):
        r = cf_runner("workflow/confluence_attachment.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "add", "get", "delete"):
            assert sub in r.stdout

    def test_add_missing_file_fails_clearly(self, cf_runner, tmp_path):
        nonexistent = tmp_path / "nope.txt"
        r = cf_runner("workflow/confluence_attachment.py", "add", "12345",
                      "--file", str(nonexistent), instances=INST)
        assert r.returncode != 0
        assert "file not found" in r.stderr.lower()
        assert str(nonexistent) in r.stderr

    def test_add_directory_rejected(self, cf_runner, tmp_path):
        d = tmp_path / "adir"
        d.mkdir()
        r = cf_runner("workflow/confluence_attachment.py", "add", "12345",
                      "--file", str(d), instances=INST)
        assert r.returncode != 0
        assert "not a file" in r.stderr.lower()

    def test_add_dry_run_with_real_file(self, cf_runner, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        r = cf_runner("workflow/confluence_attachment.py", "add", "12345",
                      "--file", str(f), "--dry-run", instances=INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "hello.txt" in combined
        assert "11" in combined  # size in bytes


# -----------------------------------------------------------------------------
# Unknown alias error message
# -----------------------------------------------------------------------------

class TestUnknownAlias:
    def test_unknown_alias_lists_available(self, cf_runner):
        r = cf_runner("utility/confluence_user.py", "whoami",
                      "--instance", "ghost",
                      instances={
                          "default": "prod",
                          "instances": {
                              "prod": {"confluence": {"url": "http://x", "token": "t"}}
                          },
                      })
        assert r.returncode != 0
        assert "ghost" in r.stderr
        assert "prod" in r.stderr
