"""Reproducible CLI tests for the newly added scripts.

These tests do NOT require a running Jira — they exercise:
  - argparse / help output
  - dry-run markers (must show even with --quiet)
  - clear errors on missing inputs
  - error mapping when the (unreachable) host fails

For HTTP-side correctness see test_client_errors.py — that path is shared.
"""
import json
import sys


# -----------------------------------------------------------------------------
# Worklog
# -----------------------------------------------------------------------------

class TestWorklog:
    INST = {"default": "x", "instances": {"x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}}}

    def test_help_works(self, script_runner):
        r = script_runner("workflow/jira_worklog.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "add", "update", "delete"):
            assert sub in r.stdout

    def test_add_dry_run_shows_marker(self, script_runner):
        r = script_runner("workflow/jira_worklog.py", "add", "TEST-1",
                          "--time-spent", "2h 30m", "--dry-run",
                          instances=self.INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stdout + r.stderr
        assert "no request was sent" in (r.stdout + r.stderr).lower()

    def test_add_dry_run_quiet_still_visible_on_stderr(self, script_runner):
        r = script_runner("workflow/jira_worklog.py", "add", "TEST-1",
                          "--time-spent", "1h", "--dry-run", "--quiet",
                          instances=self.INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stderr  # critical — quiet must NOT silence dry-run

    def test_invalid_time_format_fails_clearly(self, script_runner):
        r = script_runner("workflow/jira_worklog.py", "add", "TEST-1",
                          "--time-spent", "garbage", instances=self.INST)
        assert r.returncode != 0
        assert "invalid time format" in r.stderr.lower()
        assert "garbage" in r.stderr

    def test_update_without_field_fails(self, script_runner):
        r = script_runner("workflow/jira_worklog.py", "update", "TEST-1", "1234",
                          instances=self.INST)
        assert r.returncode != 0
        assert "no field" in r.stderr.lower()


# -----------------------------------------------------------------------------
# Links
# -----------------------------------------------------------------------------

class TestLinks:
    INST = {"default": "x", "instances": {"x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}}}

    def test_help(self, script_runner):
        r = script_runner("workflow/jira_link.py", "--help")
        assert r.returncode == 0
        for sub in ("types", "add", "remove", "link-epic", "unlink-epic"):
            assert sub in r.stdout

    def test_add_dry_run(self, script_runner):
        r = script_runner("workflow/jira_link.py", "add",
                          "--type", "Blocks", "--outward", "TEST-1", "--inward", "TEST-2",
                          "--dry-run", instances=self.INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "TEST-1" in combined and "TEST-2" in combined and "Blocks" in combined

    def test_link_epic_dry_run_json(self, script_runner):
        r = script_runner("workflow/jira_link.py", "link-epic", "TEST-1",
                          "--epic", "TEST-100", "--dry-run", "--json",
                          instances=self.INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["dry_run"] is True and payload["executed"] is False
        # Epic field should default to customfield_10008 since we can't reach Jira.
        assert "customfield" in payload["intent"]["epic_field"].lower()


# -----------------------------------------------------------------------------
# Agile
# -----------------------------------------------------------------------------

class TestAgile:
    INST = {"default": "x", "instances": {"x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}}}

    def test_help_lists_subcommands(self, script_runner):
        r = script_runner("core/jira_agile.py", "--help")
        assert r.returncode == 0
        for sub in ("boards", "sprints", "sprint-create", "sprint-move", "backlog-move", "epic-issues"):
            assert sub in r.stdout

    def test_sprint_create_dry_run(self, script_runner):
        r = script_runner("core/jira_agile.py", "sprint-create",
                          "--board", "1", "--name", "Sprint 1",
                          "--start-date", "2026-04-29T08:00:00.000Z",
                          "--dry-run", instances=self.INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stdout + r.stderr
        assert "Sprint 1" in r.stdout + r.stderr

    def test_sprint_move_dry_run_includes_all_issues(self, script_runner):
        r = script_runner("core/jira_agile.py", "sprint-move", "5",
                          "--issue", "TEST-1", "--issue", "TEST-2", "--issue", "TEST-3",
                          "--dry-run", "--json", instances=self.INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["intent"]["body"]["issues"] == ["TEST-1", "TEST-2", "TEST-3"]

    def test_sprint_update_without_fields_fails(self, script_runner):
        r = script_runner("core/jira_agile.py", "sprint-update", "5",
                          instances=self.INST)
        assert r.returncode != 0
        assert "no field" in r.stderr.lower()


# -----------------------------------------------------------------------------
# Attachment
# -----------------------------------------------------------------------------

class TestAttachment:
    INST = {"default": "x", "instances": {"x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}}}

    def test_help(self, script_runner):
        r = script_runner("core/jira_attachment.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "add", "get", "delete"):
            assert sub in r.stdout

    def test_add_missing_file_fails_clearly(self, script_runner, tmp_path):
        nonexistent = tmp_path / "nope.txt"
        r = script_runner("core/jira_attachment.py", "add", "TEST-1",
                          "--file", str(nonexistent), instances=self.INST)
        assert r.returncode != 0
        assert "file not found" in r.stderr.lower()
        assert str(nonexistent) in r.stderr

    def test_add_directory_rejected(self, script_runner, tmp_path):
        d = tmp_path / "adir"
        d.mkdir()
        r = script_runner("core/jira_attachment.py", "add", "TEST-1",
                          "--file", str(d), instances=self.INST)
        assert r.returncode != 0
        assert "not a file" in r.stderr.lower()

    def test_add_dry_run_with_real_file(self, script_runner, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        r = script_runner("core/jira_attachment.py", "add", "TEST-1",
                          "--file", str(f), "--dry-run",
                          instances=self.INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "hello.txt" in combined
        assert "11" in combined  # size in bytes


# -----------------------------------------------------------------------------
# Watcher
# -----------------------------------------------------------------------------

class TestWatcher:
    INST = {"default": "x", "instances": {"x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}}}

    def test_help(self, script_runner):
        r = script_runner("workflow/jira_watcher.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "add", "remove"):
            assert sub in r.stdout

    def test_add_with_explicit_user_dry_run(self, script_runner):
        r = script_runner("workflow/jira_watcher.py", "add", "TEST-1",
                          "--user", "alice", "--dry-run",
                          instances=self.INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined
        assert "alice" in combined and "TEST-1" in combined

    def test_remove_dry_run_quiet_emits_marker_to_stderr(self, script_runner):
        r = script_runner("workflow/jira_watcher.py", "remove", "TEST-1",
                          "--user", "bob", "--dry-run", "--quiet",
                          instances=self.INST)
        assert r.returncode == 0
        assert "DRY RUN" in r.stderr


# -----------------------------------------------------------------------------
# Version
# -----------------------------------------------------------------------------

class TestVersion:
    INST = {"default": "x", "instances": {"x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}}}

    def test_help(self, script_runner):
        r = script_runner("core/jira_version.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "create", "release"):
            assert sub in r.stdout

    def test_create_dry_run(self, script_runner):
        r = script_runner("core/jira_version.py", "create",
                          "--project", "TEST", "--name", "1.0",
                          "--release-date", "2026-04-29",
                          "--dry-run", instances=self.INST)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "DRY RUN" in combined and "1.0" in combined and "TEST" in combined

    def test_release_dry_run_json(self, script_runner):
        r = script_runner("core/jira_version.py", "release", "10000",
                          "--release-date", "2026-04-29", "--dry-run", "--json",
                          instances=self.INST)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["dry_run"] is True
        assert payload["intent"]["body"]["released"] is True
        assert payload["intent"]["body"]["releaseDate"] == "2026-04-29"


# -----------------------------------------------------------------------------
# User create
# -----------------------------------------------------------------------------

class TestUserCreate:
    INST = {"default": "x", "instances": {"x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}}}

    def test_create_dry_run_does_not_leak_password(self, script_runner):
        secret = "supersecret-pw-1234"
        r = script_runner("utility/jira_user.py", "create",
                          "--username", "alice", "--password", secret,
                          "--email", "a@example.com", "--display-name", "Alice",
                          "--dry-run", "--json", instances=self.INST)
        assert r.returncode == 0
        # Password must be masked in dry-run output
        assert secret not in r.stdout
        assert secret not in r.stderr
        payload = json.loads(r.stdout)
        assert payload["intent"]["body"]["password"] == "***"


# -----------------------------------------------------------------------------
# Issue create extensions
# -----------------------------------------------------------------------------

class TestIssueExtensions:
    INST = {"default": "x", "instances": {"x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}}}

    def test_create_with_parent_for_subtask(self, script_runner):
        r = script_runner("core/jira_issue.py", "create",
                          "--project", "TEST", "--type", "Sub-Task",
                          "--summary", "child", "--parent", "TEST-1",
                          "--dry-run", "--json", instances=self.INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]["fields"]
        assert body["parent"] == {"key": "TEST-1"}
        assert body["issuetype"] == {"name": "Sub-Task"}

    def test_create_with_multiple_fix_versions(self, script_runner):
        r = script_runner("core/jira_issue.py", "create",
                          "--project", "TEST", "--type", "Task",
                          "--summary", "v",
                          "--fix-version", "1.0", "--fix-version", "2.0",
                          "--dry-run", "--json", instances=self.INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]["fields"]
        assert body["fixVersions"] == [{"name": "1.0"}, {"name": "2.0"}]

    def test_update_unassign_via_empty_string(self, script_runner):
        r = script_runner("core/jira_issue.py", "update", "TEST-1",
                          "--assignee", "", "--dry-run", "--json",
                          instances=self.INST)
        assert r.returncode == 0
        body = json.loads(r.stdout)["intent"]["body"]["fields"]
        assert body["assignee"] is None


# -----------------------------------------------------------------------------
# Field discovery
# -----------------------------------------------------------------------------

class TestFieldsHelp:
    def test_help_lists_three_subcommands(self, script_runner):
        r = script_runner("utility/jira_fields.py", "--help")
        assert r.returncode == 0
        for sub in ("list", "editmeta", "createmeta"):
            assert sub in r.stdout
