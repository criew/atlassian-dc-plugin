"""Truncation-contract tests: emit_list() + the wired-up list/search subcommands.

Mirrors the in-process pattern used by test_bitbucket_client.py — build a real
client against a fake host, mock the HTTP layer with `responses`, monkeypatch
the module's get_<product>() to return that client, then drive main()/cmd_*
directly so we can assert on stdout/stderr instead of going through a real
subprocess (which `responses` cannot intercept).
"""
import json

import pytest
import responses

from _common import Instance, emit_list


# -----------------------------------------------------------------------------
# emit_list() unit tests (shape of the contract itself)
# -----------------------------------------------------------------------------

class _Args:
    def __init__(self, json=False, quiet=False):
        self.json = json
        self.quiet = quiet


class TestEmitListContract:
    def test_truncated_json_shape(self, capsys):
        args = _Args(json=True)
        emit_list(
            [{"key": "A"}], args, ["A line"],
            total=234, next_hint="rerun with --limit 234 (or --start-at 50)",
            item_name="issue", key="issues",
        )
        out = json.loads(capsys.readouterr().out)
        assert out["returned"] == 1
        assert out["total"] == 234
        assert out["truncated"] is True
        assert out["hint"] == "rerun with --limit 234 (or --start-at 50)"
        assert out["issues"] == [{"key": "A"}]

    def test_complete_json_shape(self, capsys):
        args = _Args(json=True)
        emit_list([{"key": "A"}, {"key": "B"}], args, ["a", "b"],
                   total=2, item_name="issue", key="issues")
        out = json.loads(capsys.readouterr().out)
        assert out["returned"] == 2
        assert out["total"] == 2
        assert out["truncated"] is False
        assert "hint" not in out

    def test_truncated_human_summary(self, capsys):
        args = _Args(json=False)
        emit_list(
            [{"key": "A"}] * 50, args, ["line"] * 50,
            total=234, next_hint="rerun with --limit 234 (or --start-at 50) to fetch the rest",
            item_name="issue", key="issues",
        )
        text = capsys.readouterr().out
        assert "50 of 234 issue(s) shown" in text
        assert "MORE RESULTS EXIST" in text
        assert "rerun with --limit 234" in text.lower() or "Rerun with --limit 234" in text

    def test_complete_human_summary(self, capsys):
        args = _Args(json=False)
        emit_list([{"key": "A"}] * 12, args, ["line"] * 12,
                   total=12, item_name="issue", key="issues")
        text = capsys.readouterr().out
        assert "12 issue(s) (complete)" in text

    def test_stderr_notice_present_when_truncated(self, capsys):
        args = _Args(json=True)
        emit_list([{"key": "A"}], args, ["A"], total=5,
                   next_hint="rerun with --limit 5", item_name="issue", key="issues")
        err = capsys.readouterr().err
        assert "notice: output truncated" in err
        assert "1 of 5" in err

    def test_no_stderr_notice_when_complete(self, capsys):
        args = _Args(json=True)
        emit_list([{"key": "A"}], args, ["A"], total=1, item_name="issue", key="issues")
        err = capsys.readouterr().err
        assert err == ""

    def test_stderr_notice_present_even_with_quiet(self, capsys):
        args = _Args(json=True, quiet=True)
        emit_list([{"key": "A"}], args, ["A"], total=5,
                   next_hint="rerun with --limit 5", item_name="issue", key="issues")
        captured = capsys.readouterr()
        assert captured.out == ""  # quiet suppresses stdout
        assert "notice: output truncated" in captured.err


# -----------------------------------------------------------------------------
# jira_search: real bug from the task description (total discarded)
# -----------------------------------------------------------------------------

@pytest.fixture
def jira_client():
    from _jira import JiraClient
    inst = Instance(alias="t", product="jira", url="http://jira.test", token="x", ssl_verify=False)
    return JiraClient(inst)


class TestJiraSearchTruncation:
    @responses.activate
    def test_search_truncated_reports_real_total_and_hint(self, jira_client, capsys, monkeypatch):
        import core.jira_search as mod

        issues = [{"key": f"T-{i}", "fields": {"summary": "s", "status": {"name": "Open"},
                                                "issuetype": {"name": "Bug"}}} for i in range(5)]
        responses.add(
            responses.GET, "http://jira.test/rest/api/2/search",
            json={"issues": issues, "total": 234}, status=200,
        )

        monkeypatch.setattr(mod, "get_jira", lambda _args: jira_client)
        monkeypatch.setattr(
            "sys.argv",
            ["jira_search.py", "project = TEST", "--limit", "5", "--json"],
        )
        mod.main()

        out = json.loads(capsys.readouterr().out)
        assert out["returned"] == 5
        assert out["total"] == 234
        assert out["truncated"] is True
        assert "--limit 234" in out["hint"]
        assert "--start-at 5" in out["hint"]
        assert len(out["issues"]) == 5

    @responses.activate
    def test_search_complete_not_flagged_truncated(self, jira_client, capsys, monkeypatch):
        import core.jira_search as mod

        issues = [{"key": "T-1", "fields": {"summary": "s", "status": {"name": "Open"},
                                             "issuetype": {"name": "Bug"}}}]
        responses.add(
            responses.GET, "http://jira.test/rest/api/2/search",
            json={"issues": issues, "total": 1}, status=200,
        )

        monkeypatch.setattr(mod, "get_jira", lambda _args: jira_client)
        monkeypatch.setattr(
            "sys.argv",
            ["jira_search.py", "project = TEST", "--json"],
        )
        mod.main()

        out = json.loads(capsys.readouterr().out)
        assert out["returned"] == 1
        assert out["total"] == 1
        assert out["truncated"] is False
        assert "hint" not in out

    @responses.activate
    def test_search_truncated_stderr_notice_with_quiet(self, jira_client, capsys, monkeypatch):
        import core.jira_search as mod

        issues = [{"key": "T-1", "fields": {"summary": "s", "status": {"name": "Open"},
                                             "issuetype": {"name": "Bug"}}}]
        responses.add(
            responses.GET, "http://jira.test/rest/api/2/search",
            json={"issues": issues, "total": 50}, status=200,
        )

        monkeypatch.setattr(mod, "get_jira", lambda _args: jira_client)
        monkeypatch.setattr(
            "sys.argv",
            ["jira_search.py", "project = TEST", "--limit", "1", "--json", "--quiet"],
        )
        mod.main()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "notice: output truncated" in captured.err
        assert "1 of 50" in captured.err


# -----------------------------------------------------------------------------
# confluence_search: CQL search, totalSize-based truncation
# -----------------------------------------------------------------------------

@pytest.fixture
def confluence_client():
    from _confluence import ConfluenceClient
    inst = Instance(alias="t", product="confluence", url="http://wiki.test",
                    token="x", ssl_verify=False)
    return ConfluenceClient(inst)


class TestConfluenceSearchTruncation:
    @responses.activate
    def test_search_truncated_reports_total_and_hint(self, confluence_client, capsys, monkeypatch):
        import core.confluence_search as mod

        results = [{"content": {"id": str(i), "title": f"Page {i}", "type": "page",
                                 "space": {"key": "DOCS"}}} for i in range(3)]
        responses.add(
            responses.GET, "http://wiki.test/rest/api/content/search",
            json={"results": results, "totalSize": 99, "size": 3, "_links": {}},
            status=200,
        )

        monkeypatch.setattr(mod, "get_confluence", lambda _args: confluence_client)
        monkeypatch.setattr(
            "sys.argv",
            ["confluence_search.py", "title ~ \"x\"", "--limit", "3", "--json"],
        )
        mod.main()

        out = json.loads(capsys.readouterr().out)
        assert out["returned"] == 3
        assert out["total"] == 99
        assert out["truncated"] is True
        assert "--start 3" in out["hint"]

    @responses.activate
    def test_search_complete_not_flagged_truncated(self, confluence_client, capsys, monkeypatch):
        import core.confluence_search as mod

        results = [{"content": {"id": "1", "title": "Page 1", "type": "page",
                                 "space": {"key": "DOCS"}}}]
        responses.add(
            responses.GET, "http://wiki.test/rest/api/content/search",
            json={"results": results, "totalSize": 1, "size": 1, "_links": {}},
            status=200,
        )

        monkeypatch.setattr(mod, "get_confluence", lambda _args: confluence_client)
        monkeypatch.setattr(
            "sys.argv",
            ["confluence_search.py", "title ~ \"x\"", "--json"],
        )
        mod.main()

        out = json.loads(capsys.readouterr().out)
        assert out["truncated"] is False
        assert out["total"] == 1


# -----------------------------------------------------------------------------
# bitbucket paginate_meta: isLastPage=false -> truncated
# -----------------------------------------------------------------------------

@pytest.fixture
def bitbucket_client():
    from _bitbucket import BitbucketClient
    inst = Instance(alias="t", product="bitbucket", url="http://bb.test",
                    token="x", ssl_verify=False)
    return BitbucketClient(inst)


class TestBitbucketPaginateTruncation:
    @responses.activate
    def test_paginate_meta_flags_truncated_when_not_last_page(self, bitbucket_client):
        responses.add(
            responses.GET, "http://bb.test/rest/api/1.0/projects",
            json={"values": [{"key": "A"}, {"key": "B"}],
                  "isLastPage": False, "nextPageStart": 2, "size": 2, "limit": 2, "start": 0},
            status=200,
        )
        items, truncated, next_start = bitbucket_client.paginate_meta(
            "projects", limit=2, page_size=2)
        assert [i["key"] for i in items] == ["A", "B"]
        assert truncated is True
        assert next_start == 2

    @responses.activate
    def test_paginate_meta_not_truncated_when_last_page(self, bitbucket_client):
        responses.add(
            responses.GET, "http://bb.test/rest/api/1.0/projects",
            json={"values": [{"key": "A"}], "isLastPage": True, "size": 1, "limit": 50, "start": 0},
            status=200,
        )
        items, truncated, next_start = bitbucket_client.paginate_meta("projects", limit=50)
        assert truncated is False

    @responses.activate
    def test_repo_list_cli_reports_truncation(self, bitbucket_client, capsys, monkeypatch):
        import core.bitbucket_repo as mod

        responses.add(
            responses.GET, "http://bb.test/rest/api/1.0/repos",
            json={"values": [{"slug": "r1", "project": {"key": "P"}}],
                  "isLastPage": False, "nextPageStart": 1, "size": 1, "limit": 1, "start": 0},
            status=200,
        )

        monkeypatch.setattr(mod, "get_bitbucket", lambda _args: bitbucket_client)
        monkeypatch.setattr(
            "sys.argv",
            ["bitbucket_repo.py", "list", "--limit", "1", "--json"],
        )
        mod.main()

        out = json.loads(capsys.readouterr().out)
        assert out["returned"] == 1
        assert out["total"] is None
        assert out["truncated"] is True
        assert "--start 1" in out["hint"]
