"""HTTP error mapping in BitbucketClient — clear errors, right exception type.

Mirrors test_client_errors.py for JiraClient. Bitbucket's error envelope is
``{"errors": [{"message": "...", "context": "..."}]}`` so the assertions
focus on extracting that and never leaking the PAT.
"""
import pytest
import responses

from _common import (
    APIError,
    AuthError,
    Instance,
    NotFoundError,
    ValidationError,
)
from _bitbucket import BitbucketClient


@pytest.fixture
def client():
    inst = Instance(alias="t", product="bitbucket", url="http://bb.test",
                    token="x", ssl_verify=False)
    return BitbucketClient(inst)


@responses.activate
def test_401_raises_auth_error(client):
    responses.add(responses.GET, "http://bb.test/rest/api/1.0/projects",
                  json={"errors": [{"message": "You are not authenticated."}]},
                  status=401)
    with pytest.raises(AuthError) as exc:
        client.get("projects")
    msg = str(exc.value).lower()
    assert "auth" in msg
    assert "pat" in msg or "token" in msg


@responses.activate
def test_403_raises_auth_error_about_permissions(client):
    responses.add(responses.GET, "http://bb.test/rest/api/1.0/projects/PRIV",
                  json={"errors": [{"message": "Forbidden."}]}, status=403)
    with pytest.raises(AuthError) as exc:
        client.get("projects/PRIV")
    msg = str(exc.value).lower()
    assert "forbidden" in msg or "permission" in msg


@responses.activate
def test_404_extracts_error_message(client):
    responses.add(
        responses.GET, "http://bb.test/rest/api/1.0/projects/NOPE",
        json={"errors": [{"context": "projectKey", "message": "Project NOPE does not exist."}]},
        status=404,
    )
    with pytest.raises(NotFoundError) as exc:
        client.get("projects/NOPE")
    s = str(exc.value)
    assert "NOPE" in s
    assert "does not exist" in s


@responses.activate
def test_400_lists_all_field_errors(client):
    responses.add(
        responses.POST, "http://bb.test/rest/api/1.0/projects",
        json={"errors": [
            {"context": "key", "message": "must be uppercase"},
            {"context": "name", "message": "is required"},
        ]},
        status=400,
    )
    with pytest.raises(ValidationError) as exc:
        client.post("projects", {"key": "x"})
    msg = str(exc.value)
    assert "key" in msg and "uppercase" in msg
    assert "name" in msg and "required" in msg


@responses.activate
def test_500_raises_api_error(client):
    responses.add(responses.GET, "http://bb.test/rest/api/1.0/projects",
                  body="Internal Server Error", status=500)
    with pytest.raises(APIError) as exc:
        client.get("projects")
    assert "500" in str(exc.value)


@responses.activate
def test_unparseable_error_body_still_reported(client):
    responses.add(responses.GET, "http://bb.test/rest/api/1.0/projects/X",
                  body="<html>oops</html>", status=400)
    with pytest.raises(ValidationError) as exc:
        client.get("projects/X")
    assert str(exc.value)
    assert len(str(exc.value)) > 5


@responses.activate
def test_success_returns_parsed_json(client):
    responses.add(responses.GET, "http://bb.test/rest/api/1.0/projects/X",
                  json={"key": "X", "name": "Project X"}, status=200)
    data = client.get("projects/X")
    assert data == {"key": "X", "name": "Project X"}


@responses.activate
def test_204_no_content_returns_none(client):
    responses.add(
        responses.DELETE,
        "http://bb.test/rest/api/1.0/projects/P/repos/R/pull-requests/1/approve",
        body="", status=204,
    )
    result = client.delete("projects/P/repos/R/pull-requests/1/approve")
    assert result is None


@responses.activate
def test_passthrough_for_explicit_rest_path(client):
    """Paths starting with /rest/ should NOT be re-prefixed."""
    responses.add(
        responses.POST,
        "http://bb.test/rest/branch-utils/1.0/projects/P/repos/R/branches",
        json={"id": "refs/heads/feature/x"}, status=200,
    )
    data = client.post("/rest/branch-utils/1.0/projects/P/repos/R/branches",
                       {"name": "feature/x"})
    assert data["id"] == "refs/heads/feature/x"


@responses.activate
def test_paginate_walks_all_pages_until_islastpage(client):
    """Pagination must follow nextPageStart until isLastPage=true."""
    responses.add(
        responses.GET, "http://bb.test/rest/api/1.0/projects",
        json={"values": [{"key": "A"}, {"key": "B"}],
              "isLastPage": False, "nextPageStart": 2, "size": 2, "limit": 2, "start": 0},
        status=200,
    )
    responses.add(
        responses.GET, "http://bb.test/rest/api/1.0/projects",
        json={"values": [{"key": "C"}],
              "isLastPage": True, "size": 1, "limit": 2, "start": 2},
        status=200,
    )
    out = client.paginate("projects", page_size=2)
    assert [p["key"] for p in out] == ["A", "B", "C"]


@responses.activate
def test_paginate_respects_limit_cap(client):
    responses.add(
        responses.GET, "http://bb.test/rest/api/1.0/projects",
        json={"values": [{"key": "A"}, {"key": "B"}, {"key": "C"}, {"key": "D"}, {"key": "E"}],
              "isLastPage": True, "size": 5, "limit": 50, "start": 0},
        status=200,
    )
    out = client.paginate("projects", limit=3, page_size=50)
    # limit=3 must cap even when the server returned more
    assert len(out) == 3


@responses.activate
def test_delete_can_send_body(client):
    """Branch deletion endpoint requires a JSON body — verify we send it."""
    captured: list = []

    def _cb(req):
        captured.append(req.body)
        return (204, {}, "")

    responses.add_callback(
        responses.DELETE,
        "http://bb.test/rest/branch-utils/1.0/projects/P/repos/R/branches",
        callback=_cb,
    )
    client.delete("/rest/branch-utils/1.0/projects/P/repos/R/branches",
                  body={"name": "refs/heads/x", "dryRun": False})
    assert captured, "DELETE was never sent"
    assert b"refs/heads/x" in (captured[0] if isinstance(captured[0], (bytes, bytearray))
                                else captured[0].encode())


@responses.activate
def test_fetch_default_reviewers_returns_names(client):
    from core.bitbucket_pr import _fetch_default_reviewers
    responses.add(
        responses.GET,
        "http://bb.test/rest/default-reviewers/1.0/projects/P/repos/R/reviewers",
        json=[{"name": "alice", "active": True}, {"name": "bob", "active": True}],
        status=200,
    )
    names = _fetch_default_reviewers(
        client, "P", "R", "refs/heads/feature/x", "refs/heads/main")
    assert names == ["alice", "bob"]
    assert "sourceRefId" in responses.calls[0].request.url
    assert "targetRefId" in responses.calls[0].request.url


@responses.activate
def test_fetch_default_reviewers_survives_404(client):
    from core.bitbucket_pr import _fetch_default_reviewers
    responses.add(
        responses.GET,
        "http://bb.test/rest/default-reviewers/1.0/projects/P/repos/R/reviewers",
        json={"errors": [{"message": "not found"}]},
        status=404,
    )
    names = _fetch_default_reviewers(
        client, "P", "R", "refs/heads/a", "refs/heads/b")
    assert names == []


@responses.activate
def test_create_pr_merges_default_reviewers(client):
    from core.bitbucket_pr import _fetch_default_reviewers, cmd_create
    import argparse

    responses.add(
        responses.GET,
        "http://bb.test/rest/default-reviewers/1.0/projects/P/repos/R/reviewers",
        json=[{"name": "default-user", "active": True}],
        status=200,
    )
    captured_body = {}

    def _cb(req):
        import json as _json
        captured_body.update(_json.loads(req.body))
        return (201, {}, _json.dumps({"id": 99, "version": 0, "title": "T",
                                       "timeSpent": None}))

    responses.add_callback(
        responses.POST,
        "http://bb.test/rest/api/1.0/projects/P/repos/R/pull-requests",
        callback=_cb,
    )

    args = argparse.Namespace(
        project="P", repo="R", title="T",
        from_branch="feature/x", to_branch="main",
        description=None, reviewer=["explicit-user"],
        dry_run=False, json=True, quiet=False,
        instance=None, debug=False,
    )
    # Monkey-patch get_bitbucket to return our test client
    import core.bitbucket_pr as pr_mod
    orig = pr_mod.get_bitbucket
    pr_mod.get_bitbucket = lambda _args: client
    try:
        pr_mod.cmd_create(args)
    finally:
        pr_mod.get_bitbucket = orig

    reviewer_names = [r["user"]["name"] for r in captured_body.get("reviewers", [])]
    assert "explicit-user" in reviewer_names
    assert "default-user" in reviewer_names


def test_pat_token_never_appears_in_real_error(client, monkeypatch):
    secret = "very-secret-bb-token-DO-NOT-LEAK-789"
    inst = Instance(alias="t", product="bitbucket", url="http://nonexistent.invalid",
                    token=secret, ssl_verify=False)
    real_client = BitbucketClient(inst)
    with pytest.raises(Exception) as exc:
        real_client.get("projects")
    assert secret not in str(exc.value)
