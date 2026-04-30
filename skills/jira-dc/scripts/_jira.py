"""Jira Data Center HTTP client."""

import json
import sys
from typing import Any, Optional

import requests

from _common import (
    APIError,
    AuthError,
    Instance,
    NotFoundError,
    ValidationError,
    _extract_error,
    load_instance,
)


class JiraClient:
    """Thin Jira REST API v2 client.

    All paths are relative to /rest/api/2 unless they start with /rest/.
    """

    def __init__(self, instance, debug=False):
        # type: (Instance, bool) -> None
        self.instance = instance
        self.debug = debug
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {instance.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Atlassian-Token": "no-check",
        })
        self.session.verify = instance.ssl_verify

    def _url(self, path):
        # type: (str) -> str
        if path.startswith("/rest/"):
            return f"{self.instance.url}{path}"
        path = path.lstrip("/")
        return f"{self.instance.url}/rest/api/2/{path}"

    def _log(self, method, url, **kw):
        if not self.debug:
            return
        body = kw.get("json")
        params = kw.get("params")
        sys.stderr.write(f"[debug] {method} {url}\n")
        if params:
            sys.stderr.write(f"[debug] params: {json.dumps(params)}\n")
        if body is not None:
            sys.stderr.write(f"[debug] body: {json.dumps(body)}\n")

    def _handle(self, resp):
        # type: (requests.Response) -> Any
        if self.debug:
            sys.stderr.write(f"[debug] -> {resp.status_code}\n")
        if resp.status_code == 401:
            raise AuthError("Authentication failed. Check the PAT in instances.json.")
        if resp.status_code == 403:
            raise AuthError("Access forbidden. The PAT lacks permission for this operation.")
        if resp.status_code == 404:
            raise NotFoundError(_extract_error(resp) or "Resource not found.")
        if 400 <= resp.status_code < 500:
            raise ValidationError(_extract_error(resp) or f"Bad request ({resp.status_code}).")
        if resp.status_code >= 500:
            raise APIError(f"Jira server error ({resp.status_code}): {_extract_error(resp)}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def get(self, path, params=None):
        # type: (str, Optional[dict]) -> Any
        url = self._url(path)
        self._log("GET", url, params=params)
        return self._handle(self.session.get(url, params=params, timeout=30))

    def post(self, path, body=None):
        # type: (str, Optional[dict]) -> Any
        url = self._url(path)
        self._log("POST", url, json=body)
        return self._handle(self.session.post(url, json=body, timeout=30))

    def put(self, path, body=None):
        # type: (str, Optional[dict]) -> Any
        url = self._url(path)
        self._log("PUT", url, json=body)
        return self._handle(self.session.put(url, json=body, timeout=30))

    def delete(self, path):
        # type: (str,) -> Any
        url = self._url(path)
        self._log("DELETE", url)
        return self._handle(self.session.delete(url, timeout=30))


def get_jira(args):
    """Resolve the configured Jira instance for the current CLI args."""
    inst = load_instance("jira", args.instance)
    return JiraClient(inst, debug=args.debug)


def simplify_issue(raw):
    # type: (dict) -> dict
    """Flatten common Jira issue fields for compact human output."""
    f = raw.get("fields", {})
    return {
        "key": raw.get("key"),
        "id": raw.get("id"),
        "summary": f.get("summary"),
        "status": (f.get("status") or {}).get("name"),
        "issuetype": (f.get("issuetype") or {}).get("name"),
        "priority": (f.get("priority") or {}).get("name"),
        "assignee": (f.get("assignee") or {}).get("name"),
        "reporter": (f.get("reporter") or {}).get("name"),
        "created": f.get("created"),
        "updated": f.get("updated"),
        "labels": f.get("labels") or [],
    }
