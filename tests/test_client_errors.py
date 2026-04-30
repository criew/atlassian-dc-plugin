"""HTTP error mapping in JiraClient — clear error messages, right exception type."""
import pytest
import responses

from _common import (
    APIError,
    AuthError,
    Instance,
    NotFoundError,
    ValidationError,
)
from _jira import JiraClient


@pytest.fixture
def client():
    inst = Instance(alias="t", product="jira", url="http://jira.test", token="x", ssl_verify=False)
    return JiraClient(inst)


@responses.activate
def test_401_raises_auth_error_with_helpful_message(client):
    responses.add(responses.GET, "http://jira.test/rest/api/2/myself",
                  json={"errorMessages": ["You are not authenticated."]}, status=401)
    with pytest.raises(AuthError) as exc:
        client.get("myself")
    msg = str(exc.value)
    assert "Authentication" in msg or "authenticated" in msg.lower()
    assert "PAT" in msg or "token" in msg.lower()


@responses.activate
def test_403_raises_auth_error_about_permissions(client):
    responses.add(responses.GET, "http://jira.test/rest/api/2/issue/X-1",
                  json={"errorMessages": ["Permission denied."]}, status=403)
    with pytest.raises(AuthError) as exc:
        client.get("issue/X-1")
    msg = str(exc.value).lower()
    assert "forbidden" in msg or "permission" in msg


@responses.activate
def test_404_raises_not_found_with_jira_message(client):
    responses.add(responses.GET, "http://jira.test/rest/api/2/issue/X-1",
                  json={"errorMessages": ["Issue Does Not Exist"]}, status=404)
    with pytest.raises(NotFoundError) as exc:
        client.get("issue/X-1")
    assert "Issue Does Not Exist" in str(exc.value)


@responses.activate
def test_400_extracts_field_level_errors(client):
    responses.add(responses.POST, "http://jira.test/rest/api/2/issue",
                  json={"errors": {"summary": "must not be empty",
                                   "issuetype": "is required"}},
                  status=400)
    with pytest.raises(ValidationError) as exc:
        client.post("issue", {"fields": {}})
    msg = str(exc.value)
    # both fields should be visible — LLM needs to know what to fix
    assert "summary" in msg and "must not be empty" in msg
    assert "issuetype" in msg and "is required" in msg


@responses.activate
def test_500_raises_api_error(client):
    responses.add(responses.GET, "http://jira.test/rest/api/2/myself",
                  body="Internal Server Error", status=500)
    with pytest.raises(APIError) as exc:
        client.get("myself")
    assert "500" in str(exc.value)


@responses.activate
def test_unparseable_error_body_is_still_reported(client):
    responses.add(responses.GET, "http://jira.test/rest/api/2/issue/X-1",
                  body="<html>some HTML</html>", status=400)
    with pytest.raises(ValidationError) as exc:
        client.get("issue/X-1")
    # We must produce *something* — never raise empty/None
    assert str(exc.value)
    assert len(str(exc.value)) > 5


@responses.activate
def test_success_returns_parsed_json(client):
    responses.add(responses.GET, "http://jira.test/rest/api/2/myself",
                  json={"name": "alice"}, status=200)
    data = client.get("myself")
    assert data == {"name": "alice"}


@responses.activate
def test_success_with_empty_body_returns_none(client):
    responses.add(responses.PUT, "http://jira.test/rest/api/2/issue/X-1",
                  body="", status=204)
    result = client.put("issue/X-1", {"fields": {}})
    # 204 No Content → None is fine, but caller can distinguish from error by no exception
    assert result is None


def test_pat_token_never_appears_in_error_messages(client, monkeypatch):
    """A real PAT token must never leak into stringified errors."""
    secret = "secret-token-must-not-leak-12345"
    inst = Instance(alias="t", product="jira", url="http://nonexistent.invalid",
                    token=secret, ssl_verify=False)
    real_client = JiraClient(inst)
    with pytest.raises(Exception) as exc:
        real_client.get("myself")
    assert secret not in str(exc.value)
