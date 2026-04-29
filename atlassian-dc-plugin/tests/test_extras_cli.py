"""Reproducible CLI tests for the recently added scripts.

Covers:
  jira_component, jira_group, jira_user (update/delete/assignable),
  jira_issue bulk-create, confluence_restriction, confluence_page history+export,
  bitbucket_webhook, bitbucket_permission, bitbucket_build.
"""
from __future__ import annotations

import json
import sys


INST = {"default": "x", "instances": {
    "x": {
        "jira":       {"url": "http://127.0.0.1:1", "token": "t"},
        "confluence": {"url": "http://127.0.0.1:1", "token": "t"},
        "bitbucket":  {"url": "http://127.0.0.1:1", "token": "t"},
    }
}}


# -----------------------------------------------------------------------------
# Jira components
# -----------------------------------------------------------------------------

class TestJiraComponent:
    def test_help_lists_subs(self, script_runner):
        r = script_runner("core/jira_component.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "get", "create", "update", "delete"):
            assert sub in r.stdout

    def test_create_dry_run(self, script_runner):
        r = script_runner("core/jira_component.py", "create",
                          "--project", "TST", "--name", "Backend",
                          "--lead", "alice", "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["project"] == "TST"
        assert body["name"] == "Backend"
        assert body["leadUserName"] == "alice"

    def test_update_without_field_fails(self, script_runner):
        r = script_runner("core/jira_component.py", "update", "10000",
                          instances=INST)
        assert r.returncode != 0
        assert "no field" in r.stderr.lower()


# -----------------------------------------------------------------------------
# Jira groups
# -----------------------------------------------------------------------------

class TestJiraGroup:
    def test_help_lists_subs(self, script_runner):
        r = script_runner("utility/jira_group.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "members", "create", "delete", "add-user", "remove-user"):
            assert sub in r.stdout

    def test_create_dry_run(self, script_runner):
        r = script_runner("utility/jira_group.py", "create",
                          "--name", "qa", "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        assert json.loads(r.stdout)["intent"]["body"]["name"] == "qa"

    def test_add_user_dry_run(self, script_runner):
        r = script_runner("utility/jira_group.py", "add-user",
                          "--name", "qa", "--user", "alice",
                          "--dry-run", instances=INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "alice" in combined and "qa" in combined


# -----------------------------------------------------------------------------
# Jira user update / delete / assignable
# -----------------------------------------------------------------------------

class TestJiraUserExtensions:
    def test_update_dry_run(self, script_runner):
        r = script_runner("utility/jira_user.py", "update",
                          "--username", "alice", "--display-name", "Alice X",
                          "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["displayName"] == "Alice X"

    def test_update_without_field_fails(self, script_runner):
        r = script_runner("utility/jira_user.py", "update",
                          "--username", "alice", instances=INST)
        assert r.returncode != 0
        assert "no field" in r.stderr.lower()

    def test_delete_dry_run(self, script_runner):
        r = script_runner("utility/jira_user.py", "delete",
                          "--username", "bob", "--dry-run", instances=INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stdout + r.stderr
        assert "bob" in r.stdout + r.stderr

    def test_assignable_requires_scope(self, script_runner):
        r = script_runner("utility/jira_user.py", "assignable",
                          "--query", "alice", instances=INST)
        assert r.returncode != 0
        assert "issue-key" in r.stderr.lower() or "project" in r.stderr.lower()


# -----------------------------------------------------------------------------
# Jira bulk-create
# -----------------------------------------------------------------------------

class TestJiraBulkCreate:
    def test_help(self, script_runner):
        r = script_runner("core/jira_issue.py", "--help")
        assert r.returncode == 0
        assert "bulk-create" in r.stdout

    def test_missing_file(self, script_runner, tmp_path):
        r = script_runner("core/jira_issue.py", "bulk-create",
                          "--file", str(tmp_path / "nope.json"),
                          instances=INST)
        assert r.returncode != 0
        assert "file not found" in r.stderr.lower()

    def test_invalid_json_list_required(self, script_runner, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text('{"not": "a list"}', encoding="utf-8")
        r = script_runner("core/jira_issue.py", "bulk-create",
                          "--file", str(f), instances=INST)
        assert r.returncode != 0
        assert "list" in r.stderr.lower()

    def test_dry_run_counts(self, script_runner, tmp_path):
        f = tmp_path / "ok.json"
        f.write_text(json.dumps([
            {"project": "TST", "summary": "A", "issuetype": "Task"},
            {"project": "TST", "summary": "B", "issuetype": "Bug",
             "labels": ["urgent"], "fix_versions": ["1.0"]},
        ]), encoding="utf-8")
        r = script_runner("core/jira_issue.py", "bulk-create",
                          "--file", str(f), "--dry-run", "--json",
                          instances=INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["intent"]["count"] == 2
        assert payload["dry_run"] is True

    def test_required_field_missing(self, script_runner, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text(json.dumps([{"project": "TST", "summary": "A"}]), encoding="utf-8")
        r = script_runner("core/jira_issue.py", "bulk-create",
                          "--file", str(f), instances=INST)
        assert r.returncode != 0
        assert "issuetype" in r.stderr.lower()


# -----------------------------------------------------------------------------
# Confluence restrictions
# -----------------------------------------------------------------------------

class TestConfluenceRestriction:
    def test_help_lists_subs(self, script_runner):
        r = script_runner("workflow/confluence_restriction.py", "--help")
        assert r.returncode == 0
        for sub in ("get", "set", "clear"):
            assert sub in r.stdout

    def test_set_invalid_operation_fails(self, script_runner):
        r = script_runner("workflow/confluence_restriction.py", "set", "12345",
                          "--operation", "delete", "--user", "alice",
                          instances=INST)
        # argparse choices reject before our handler runs
        assert r.returncode != 0

    def test_set_requires_user_or_group(self, script_runner):
        r = script_runner("workflow/confluence_restriction.py", "set", "12345",
                          "--operation", "read", instances=INST)
        assert r.returncode != 0
        assert "user" in r.stderr.lower() or "group" in r.stderr.lower()

    def test_set_dry_run_payload(self, script_runner):
        r = script_runner("workflow/confluence_restriction.py", "set", "12345",
                          "--operation", "update", "--user", "alice",
                          "--group", "qa", "--dry-run", "--json",
                          instances=INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        body = payload["intent"]["body"][0]
        assert body["operation"] == "update"
        users = [u["username"] for u in body["restrictions"]["user"]["results"]]
        groups = [g["name"] for g in body["restrictions"]["group"]["results"]]
        assert "alice" in users and "qa" in groups


# -----------------------------------------------------------------------------
# Confluence page history + export
# -----------------------------------------------------------------------------

class TestConfluencePageExtras:
    def test_help_lists_history_and_export(self, script_runner):
        r = script_runner("core/confluence_page.py", "--help")
        assert r.returncode == 0
        assert "history" in r.stdout
        assert "export" in r.stdout

    def test_export_pdf_url(self, script_runner):
        # Export only needs the URL; no actual server call.
        r = script_runner("core/confluence_page.py", "export", "12345",
                          "--format", "pdf", "--json", instances=INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["page_id"] == "12345"
        assert payload["format"] == "pdf"
        assert "pdfpageexport" in payload["url"]


# -----------------------------------------------------------------------------
# Bitbucket webhooks
# -----------------------------------------------------------------------------

class TestBitbucketWebhook:
    def test_help_lists_subs(self, script_runner):
        r = script_runner("core/bitbucket_webhook.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "get", "create", "update", "delete", "test"):
            assert sub in r.stdout

    def test_create_requires_event(self, script_runner):
        r = script_runner("core/bitbucket_webhook.py", "create",
                          "--project", "TST", "--repo", "r",
                          "--name", "ci", "--url", "https://ci.example/wh",
                          instances=INST)
        # argparse marks --event required → failure
        assert r.returncode != 0

    def test_create_dry_run(self, script_runner):
        r = script_runner("core/bitbucket_webhook.py", "create",
                          "--project", "TST", "--repo", "r",
                          "--name", "ci", "--url", "https://ci.example/wh",
                          "--event", "repo:refs_changed", "--event", "pr:opened",
                          "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]
        assert body["events"] == ["repo:refs_changed", "pr:opened"]
        assert body["url"] == "https://ci.example/wh"


# -----------------------------------------------------------------------------
# Bitbucket permissions
# -----------------------------------------------------------------------------

class TestBitbucketPermission:
    def test_help_lists_subs(self, script_runner):
        r = script_runner("core/bitbucket_permission.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "grant-user", "grant-group", "revoke-user", "revoke-group"):
            assert sub in r.stdout

    def test_grant_user_invalid_perm_at_project_scope(self, script_runner):
        r = script_runner("core/bitbucket_permission.py", "grant-user",
                          "--project", "TST", "--user", "alice",
                          "--permission", "REPO_ADMIN",  # repo perm at project scope is invalid
                          instances=INST)
        assert r.returncode != 0
        assert "PROJECT_" in r.stderr or "permission" in r.stderr.lower()

    def test_grant_user_dry_run(self, script_runner):
        r = script_runner("core/bitbucket_permission.py", "grant-user",
                          "--project", "TST", "--user", "alice",
                          "--permission", "PROJECT_ADMIN",
                          "--dry-run", instances=INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "PROJECT_ADMIN" in combined and "alice" in combined


# -----------------------------------------------------------------------------
# Bitbucket build status
# -----------------------------------------------------------------------------

class TestBitbucketBuild:
    def test_help(self, script_runner):
        r = script_runner("core/bitbucket_build.py", "--help")
        assert r.returncode == 0
        assert "list" in r.stdout and "post" in r.stdout

    def test_post_invalid_state(self, script_runner):
        r = script_runner("core/bitbucket_build.py", "post", "abc123",
                          "--state", "GREEN", "--key", "K", "--name", "N",
                          "--url", "https://ci.example",
                          instances=INST)
        assert r.returncode != 0
        assert "state" in r.stderr.lower()

    def test_post_dry_run(self, script_runner):
        r = script_runner("core/bitbucket_build.py", "post",
                          "deadbeef" * 5, "--state", "SUCCESSFUL",
                          "--key", "MY-CI-42", "--name", "Build #42",
                          "--url", "https://ci.example/42",
                          "--dry-run", "--json", instances=INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["intent"]["body"]["state"] == "SUCCESSFUL"
        assert payload["intent"]["body"]["key"] == "MY-CI-42"
