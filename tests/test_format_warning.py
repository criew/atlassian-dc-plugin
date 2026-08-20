"""Tests for the Markdown-vs-native-markup advisory warning.

Two layers:
1. subprocess-level (mirrors tests/test_cli_error_visibility.py): the CLI
   scripts must print a one-line stderr warning when a description/comment/
   worklog/page body looks like Markdown, must NOT print it for legitimate
   wiki markup, must still print it under --quiet, and must never change the
   exit code. --dry-run is enough, no live server needed.
2. unit-level: import looks_like_markdown()/warn_if_wrong_markup() directly
   and check the conservative edge cases (single '#'/'*' must NOT trigger).
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JIRA_COMMON = REPO_ROOT / "skills" / "jira-dc" / "scripts"
CONF_COMMON = REPO_ROOT / "skills" / "confluence-dc" / "scripts"

_INSTANCES = {
    "default": "x",
    "instances": {"x": {
        "jira": {"url": "http://x", "token": "t"},
        "confluence": {"url": "http://x", "token": "t"},
    }},
}

MARKDOWN_DESCRIPTION = "## Heading\n\n**bold** text and a [link](http://example.com)\n"
WIKI_DESCRIPTION = "h2. Heading\n\n*bold* text and a [link|http://example.com]\n"


# -----------------------------------------------------------------------------
# CLI / subprocess level
# -----------------------------------------------------------------------------

def test_jira_create_warns_on_markdown_description(script_runner):
    r = script_runner(
        "core/jira_issue.py", "create",
        "--project", "TEST", "--type", "Task", "--summary", "hello",
        "--description", MARKDOWN_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr
    assert "wiki markup" in r.stderr.lower()


def test_jira_create_no_warning_on_wiki_markup(script_runner):
    r = script_runner(
        "core/jira_issue.py", "create",
        "--project", "TEST", "--type", "Task", "--summary", "hello",
        "--description", WIKI_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" not in r.stderr


def test_jira_update_warns_on_markdown_description(script_runner):
    r = script_runner(
        "core/jira_issue.py", "update", "TEST-1",
        "--description", MARKDOWN_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr


def test_jira_comment_add_warns_on_markdown(script_runner):
    r = script_runner(
        "workflow/jira_comment.py", "add", "TEST-1",
        "--body", MARKDOWN_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr


def test_jira_worklog_add_warns_on_markdown_comment(script_runner):
    r = script_runner(
        "workflow/jira_worklog.py", "add", "TEST-1",
        "--time-spent", "1h",
        "--comment", MARKDOWN_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr


def test_jira_worklog_update_warns_on_markdown_comment(script_runner):
    r = script_runner(
        "workflow/jira_worklog.py", "update", "TEST-1", "10001",
        "--comment", MARKDOWN_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr


def test_warning_survives_quiet_flag(script_runner):
    """Critical: --quiet must not silence the advisory warning."""
    r = script_runner(
        "core/jira_issue.py", "create",
        "--project", "TEST", "--type", "Task", "--summary", "hello",
        "--description", MARKDOWN_DESCRIPTION,
        "--dry-run", "--quiet",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr


def test_warning_does_not_change_exit_code(script_runner):
    r_bad = script_runner(
        "core/jira_issue.py", "create",
        "--project", "TEST", "--type", "Task", "--summary", "hello",
        "--description", MARKDOWN_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    r_good = script_runner(
        "core/jira_issue.py", "create",
        "--project", "TEST", "--type", "Task", "--summary", "hello",
        "--description", WIKI_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r_bad.returncode == 0 == r_good.returncode


def test_confluence_create_warns_on_markdown_storage_body(script_runner):
    r = script_runner(
        "core/confluence_page.py", "create",
        "--space", "TST", "--title", "hello",
        "--content", MARKDOWN_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr


def test_confluence_create_warns_on_body_with_no_tags(script_runner):
    """Even plain non-Markdown text with zero '<' should warn for --format
    storage — it cannot possibly be valid storage XHTML."""
    r = script_runner(
        "core/confluence_page.py", "create",
        "--space", "TST", "--title", "hello",
        "--content", "just plain text, no tags here",
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr


def test_confluence_create_no_warning_on_storage_xhtml(script_runner):
    r = script_runner(
        "core/confluence_page.py", "create",
        "--space", "TST", "--title", "hello",
        "--content", "<h2>Titel</h2><p><strong>fett</strong></p>",
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" not in r.stderr


def test_confluence_create_no_warning_with_format_wiki(script_runner):
    """--format wiki content is expected to be wiki markup, not storage
    XHTML — the storage-only heuristic must not fire."""
    r = script_runner(
        "core/confluence_page.py", "create",
        "--space", "TST", "--title", "hello",
        "--content", "h1. Titel\n\n*fett* und _kursiv_",
        "--format", "wiki",
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" not in r.stderr


def test_confluence_update_warns_on_markdown_storage_body(script_runner):
    r = script_runner(
        "core/confluence_page.py", "update", "12345",
        "--content", MARKDOWN_DESCRIPTION,
        "--dry-run",
        instances=_INSTANCES,
    )
    assert r.returncode == 0
    assert "looks like Markdown" in r.stderr


# -----------------------------------------------------------------------------
# Unit level: direct import, conservative edge cases
# -----------------------------------------------------------------------------

def _import_common(scripts_dir):
    sys.path.insert(0, str(scripts_dir))
    import importlib
    if "_common" in sys.modules:
        del sys.modules["_common"]
    mod = importlib.import_module("_common")
    return mod


def test_looks_like_markdown_single_hash_is_not_a_trigger():
    common = _import_common(JIRA_COMMON)
    assert common.looks_like_markdown("# Liste\nerster Punkt") is False


def test_looks_like_markdown_single_asterisk_bold_is_not_a_trigger():
    common = _import_common(JIRA_COMMON)
    assert common.looks_like_markdown("Dies ist *bold* Text") is False


def test_looks_like_markdown_fenced_code_is_a_trigger():
    common = _import_common(JIRA_COMMON)
    assert common.looks_like_markdown("some text\n```\ncode\n```\n") is True


def test_looks_like_markdown_double_asterisk_is_a_trigger():
    common = _import_common(JIRA_COMMON)
    assert common.looks_like_markdown("**bold**") is True


def test_looks_like_markdown_md_link_is_a_trigger():
    common = _import_common(JIRA_COMMON)
    assert common.looks_like_markdown("[text](http://example.com)") is True


def test_looks_like_markdown_h2_heading_is_a_trigger():
    common = _import_common(JIRA_COMMON)
    assert common.looks_like_markdown("## Heading\n") is True


def test_looks_like_markdown_empty_text_is_not_a_trigger():
    common = _import_common(JIRA_COMMON)
    assert common.looks_like_markdown("") is False
    assert common.looks_like_markdown(None) is False


def test_warn_if_wrong_markup_writes_to_stderr(capsys):
    common = _import_common(JIRA_COMMON)
    common.warn_if_wrong_markup("**bold**", "jira")
    captured = capsys.readouterr()
    assert "looks like Markdown" in captured.err
    assert captured.out == ""


def test_warn_if_wrong_markup_silent_for_legit_markup(capsys):
    common = _import_common(JIRA_COMMON)
    common.warn_if_wrong_markup("*bold* and # not a heading", "jira")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_warn_if_wrong_markup_force_bypasses_pattern_gate(capsys):
    common = _import_common(CONF_COMMON)
    common.warn_if_wrong_markup("plain text, no markdown patterns", "confluence", force=True)
    captured = capsys.readouterr()
    assert "looks like Markdown" in captured.err


def test_confluence_common_identical_helper_present():
    """Both _common.py copies must expose the same helper names (per task
    spec: identical helper across jira-dc and confluence-dc)."""
    jira_common = _import_common(JIRA_COMMON)
    conf_common = _import_common(CONF_COMMON)
    assert hasattr(jira_common, "warn_if_wrong_markup")
    assert hasattr(conf_common, "warn_if_wrong_markup")
    assert hasattr(jira_common, "looks_like_markdown")
    assert hasattr(conf_common, "looks_like_markdown")
