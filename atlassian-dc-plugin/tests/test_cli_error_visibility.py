"""End-to-end CLI tests: scripts must signal success/failure unambiguously.

These tests use subprocess to call the actual scripts as a weak LLM would,
then check exit code, stdout, and stderr. The goal: make it impossible for an
LLM to mistake a failure for a success.
"""
from __future__ import annotations

import json
import sys


def _is_clean_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Missing config
# -----------------------------------------------------------------------------

def test_missing_config_exits_nonzero_with_clear_stderr(script_runner, isolated_config):
    # No instances.json present — script must fail loudly.
    r = script_runner("utility/jira_user.py", "whoami")
    assert r.returncode != 0, "expected failure exit code"
    # stdout MUST NOT look like JSON success
    assert "alice" not in r.stdout.lower()
    # stderr must contain a clear error keyword + actionable info
    assert "error" in r.stderr.lower()
    assert "instances.json" in r.stderr


def test_missing_config_does_not_print_silent_empty_success(script_runner):
    """A weak LLM must not see an empty stdout with exit 0 here."""
    r = script_runner("utility/jira_user.py", "whoami")
    assert not (r.returncode == 0 and r.stdout.strip() == "")


def test_unknown_alias_lists_available(script_runner):
    r = script_runner(
        "utility/jira_user.py", "whoami", "--instance", "ghost",
        instances={
            "default": "prod",
            "instances": {"prod": {"jira": {"url": "http://x", "token": "t"}}},
        },
    )
    assert r.returncode != 0
    assert "ghost" in r.stderr
    assert "prod" in r.stderr  # show what IS available


# -----------------------------------------------------------------------------
# Help text doesn't trigger error mode
# -----------------------------------------------------------------------------

def test_help_works_without_config(script_runner):
    r = script_runner("utility/jira_user.py", "--help")
    assert r.returncode == 0
    assert "whoami" in r.stdout


# -----------------------------------------------------------------------------
# Dry-run is unambiguous, even with --quiet
# -----------------------------------------------------------------------------

def test_dry_run_create_marks_as_not_executed(script_runner):
    r = script_runner(
        "core/jira_issue.py", "create",
        "--project", "TEST", "--type", "Task", "--summary", "hello",
        "--dry-run",
        instances={"default": "x", "instances": {"x": {"jira": {"url": "http://x", "token": "t"}}}},
    )
    assert r.returncode == 0
    combined = (r.stdout + r.stderr).lower()
    assert "dry run" in combined or "dry_run" in combined
    # explicit signal that nothing happened
    assert "no request was sent" in combined or "executed" in combined


def test_dry_run_quiet_still_emits_marker_to_stderr(script_runner):
    """Critical: --quiet must NOT silence the dry-run marker, or LLMs will
    assume success."""
    r = script_runner(
        "core/jira_issue.py", "create",
        "--project", "TEST", "--type", "Task", "--summary", "hello",
        "--dry-run", "--quiet",
        instances={"default": "x", "instances": {"x": {"jira": {"url": "http://x", "token": "t"}}}},
    )
    assert r.returncode == 0
    # stdout may be empty due to --quiet, but stderr must still announce dry-run
    assert "dry run" in r.stderr.lower()


def test_dry_run_json_payload_has_executed_false(script_runner):
    r = script_runner(
        "core/jira_issue.py", "delete", "TEST-1", "--dry-run", "--json",
        instances={"default": "x", "instances": {"x": {"jira": {"url": "http://x", "token": "t"}}}},
    )
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload.get("dry_run") is True
    assert payload.get("executed") is False


# -----------------------------------------------------------------------------
# Network failure to fake host produces clear error, not silent success
# -----------------------------------------------------------------------------

def test_unreachable_host_signals_failure(script_runner):
    r = script_runner(
        "utility/jira_user.py", "whoami",
        instances={"default": "x", "instances": {
            "x": {"jira": {"url": "http://127.0.0.1:1", "token": "t"}}
        }},
        timeout=20,
    )
    assert r.returncode != 0
    # stdout must not look like a successful user record
    assert "name" not in r.stdout or "error" in r.stdout.lower()
    assert r.stderr.strip() != ""


def test_unreachable_host_does_not_leak_token(script_runner):
    secret = "do-not-leak-this-token-please-1234"
    r = script_runner(
        "utility/jira_user.py", "whoami",
        instances={"default": "x", "instances": {
            "x": {"jira": {"url": "http://127.0.0.1:1", "token": secret}}
        }},
        timeout=20,
    )
    assert secret not in r.stdout
    assert secret not in r.stderr


# -----------------------------------------------------------------------------
# rules show: "no rules" is NOT an error, but is unambiguous
# -----------------------------------------------------------------------------

def test_rules_show_no_file_returns_zero_but_says_no_rules(script_runner):
    r = script_runner(
        "utility/jira_rules.py", "show",
        instances={"default": "x", "instances": {"x": {"jira": {"url": "http://x", "token": "t"}}}},
    )
    assert r.returncode == 0
    # Must clearly state absence; not silent.
    assert "NO RULES" in r.stdout or "no rules" in r.stdout.lower()


def test_rules_show_with_file_prints_content(script_runner, write_rules):
    write_rules("x", "# Rules\n## Global\n- never delete issues without confirmation\n")
    r = script_runner(
        "utility/jira_rules.py", "show",
        instances={"default": "x", "instances": {"x": {"jira": {"url": "http://x", "token": "t"}}}},
    )
    assert r.returncode == 0
    assert "never delete" in r.stdout


def test_rules_show_filters_to_project(script_runner, write_rules):
    write_rules("x",
                "# Rules\n"
                "## Global\n- glob-policy\n"
                "## Project HALLO\n- hallo-policy\n"
                "## Project OTHER\n- other-policy\n")
    r = script_runner(
        "utility/jira_rules.py", "show", "--project", "HALLO",
        instances={"default": "x", "instances": {"x": {"jira": {"url": "http://x", "token": "t"}}}},
    )
    assert r.returncode == 0
    assert "glob-policy" in r.stdout
    assert "hallo-policy" in r.stdout
    assert "other-policy" not in r.stdout
