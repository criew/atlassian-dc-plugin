"""HTTP error mapping in ConfluenceClient — same shape as JiraClient tests."""
from __future__ import annotations

import pytest
import responses

from _common import (
    APIError,
    AuthError,
    Instance,
    NotFoundError,
    ValidationError,
)
from _confluence import ConfluenceClient


@pytest.fixture
def client():
    inst = Instance(alias="t", product="confluence",
                    url="http://wiki.test", token="x", ssl_verify=False)
    return ConfluenceClient(inst)


@responses.activate
def test_url_joins_under_rest_api_without_v2(client):
    responses.add(responses.GET, "http://wiki.test/rest/api/user/current",
                  json={"username": "alice"}, status=200)
    data = client.get("user/current")
    assert data == {"username": "alice"}


@responses.activate
def test_url_passes_through_explicit_rest_path(client):
    responses.add(responses.GET, "http://wiki.test/rest/api/space/DOCS",
                  json={"key": "DOCS"}, status=200)
    data = client.get("/rest/api/space/DOCS")
    assert data == {"key": "DOCS"}


@responses.activate
def test_401_raises_auth_error(client):
    responses.add(responses.GET, "http://wiki.test/rest/api/user/current",
                  json={"message": "Not authenticated"}, status=401)
    with pytest.raises(AuthError) as exc:
        client.get("user/current")
    msg = str(exc.value).lower()
    assert "authentication" in msg or "authenticated" in msg
    assert "pat" in msg or "token" in msg


@responses.activate
def test_403_raises_auth_error_about_permissions(client):
    responses.add(responses.GET, "http://wiki.test/rest/api/content/12345",
                  json={"message": "forbidden"}, status=403)
    with pytest.raises(AuthError) as exc:
        client.get("content/12345")
    assert "forbidden" in str(exc.value).lower() or "permission" in str(exc.value).lower()


@responses.activate
def test_404_raises_not_found(client):
    responses.add(responses.GET, "http://wiki.test/rest/api/content/X",
                  json={"message": "no such content"}, status=404)
    with pytest.raises(NotFoundError) as exc:
        client.get("content/X")
    assert "no such content" in str(exc.value)


@responses.activate
def test_400_extracts_message(client):
    responses.add(responses.POST, "http://wiki.test/rest/api/content",
                  json={"message": "title must not be empty"}, status=400)
    with pytest.raises(ValidationError) as exc:
        client.post("content", {"type": "page"})
    assert "title must not be empty" in str(exc.value)


@responses.activate
def test_500_raises_api_error(client):
    responses.add(responses.GET, "http://wiki.test/rest/api/user/current",
                  body="Internal Server Error", status=500)
    with pytest.raises(APIError) as exc:
        client.get("user/current")
    assert "500" in str(exc.value)


@responses.activate
def test_unparseable_error_body_is_still_reported(client):
    responses.add(responses.GET, "http://wiki.test/rest/api/content/X",
                  body="<html>boom</html>", status=400)
    with pytest.raises(ValidationError) as exc:
        client.get("content/X")
    assert str(exc.value) and len(str(exc.value)) > 5


@responses.activate
def test_success_with_empty_body_returns_none(client):
    responses.add(responses.PUT, "http://wiki.test/rest/api/content/1",
                  body="", status=204)
    result = client.put("content/1", {"version": {"number": 2}})
    assert result is None


def test_pat_token_never_appears_in_error_messages():
    secret = "secret-pat-must-not-leak-67890"
    inst = Instance(alias="t", product="confluence",
                    url="http://nonexistent.invalid", token=secret, ssl_verify=False)
    real_client = ConfluenceClient(inst)
    with pytest.raises(Exception) as exc:
        real_client.get("user/current")
    assert secret not in str(exc.value)
