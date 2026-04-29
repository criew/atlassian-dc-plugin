"""Confluence Data Center HTTP client.

Mirrors the structure of `JiraClient` in `_common.py` but talks to
`/rest/api/` (no `/2`) and exposes a `ConfluenceClient` class plus a
`get_confluence` argparse helper.

Re-uses the generic config loader, error types, and output helpers from
`_common.py` — those stay product-agnostic.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

import requests

from _common import (  # noqa: E402  (sibling import via shared/ on sys.path)
    APIError,
    AuthError,
    Instance,
    NotFoundError,
    ValidationError,
    _extract_error,
    load_instance,
)


class ConfluenceClient:
    """Thin Confluence Server / DC REST API client.

    All paths starting with `/rest/` are used as-is; bare paths are joined
    under `/rest/api/`.
    """

    def __init__(self, instance: Instance, debug: bool = False):
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

    def _url(self, path: str) -> str:
        if path.startswith("/rest/"):
            return f"{self.instance.url}{path}"
        path = path.lstrip("/")
        return f"{self.instance.url}/rest/api/{path}"

    def _log(self, method: str, url: str, **kw):
        if not self.debug:
            return
        body = kw.get("json")
        params = kw.get("params")
        sys.stderr.write(f"[debug] {method} {url}\n")
        if params:
            sys.stderr.write(f"[debug] params: {json.dumps(params)}\n")
        if body is not None:
            sys.stderr.write(f"[debug] body: {json.dumps(body)}\n")

    def _handle(self, resp: requests.Response) -> Any:
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
            raise APIError(f"Confluence server error ({resp.status_code}): {_extract_error(resp)}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        url = self._url(path)
        self._log("GET", url, params=params)
        return self._handle(self.session.get(url, params=params, timeout=30))

    def post(self, path: str, body: Optional[dict] = None) -> Any:
        url = self._url(path)
        self._log("POST", url, json=body)
        return self._handle(self.session.post(url, json=body, timeout=30))

    def put(self, path: str, body: Optional[dict] = None) -> Any:
        url = self._url(path)
        self._log("PUT", url, json=body)
        return self._handle(self.session.put(url, json=body, timeout=30))

    def delete(self, path: str, params: Optional[dict] = None) -> Any:
        url = self._url(path)
        self._log("DELETE", url, params=params)
        return self._handle(self.session.delete(url, params=params, timeout=30))


def get_confluence(args: argparse.Namespace) -> ConfluenceClient:
    inst = load_instance("confluence", args.instance)
    return ConfluenceClient(inst, debug=args.debug)


def paginate(client: ConfluenceClient, path: str, params: Optional[dict] = None,
             limit: int = 50, page_size: int = 50) -> list[dict]:
    """Walk `_links.next` pages up to `limit` results.

    Yields the merged `results` list. Used by spaces/search/comments/labels.
    """
    collected: list[dict] = []
    params = dict(params or {})
    params.setdefault("start", 0)
    params["limit"] = min(page_size, limit)

    next_path: Optional[str] = path
    next_params: Optional[dict] = params

    while next_path is not None and len(collected) < limit:
        # Re-cap page size against remaining budget
        if next_params is not None:
            next_params["limit"] = min(page_size, limit - len(collected))
        data = client.get(next_path, params=next_params)
        results = data.get("results", []) if isinstance(data, dict) else []
        if not results:
            break
        collected.extend(results)
        # Honor explicit _links.next when present, else manual start advance
        links = (data.get("_links") or {}) if isinstance(data, dict) else {}
        nxt = links.get("next")
        if nxt:
            # `_links.next` is typically `/rest/api/content/search?...&start=N`
            next_path = nxt
            next_params = None
        else:
            size = data.get("size", len(results)) if isinstance(data, dict) else len(results)
            start = (next_params or {}).get("start", 0) if next_params else 0
            # Advance manually
            next_params = dict(next_params or params)
            next_params["start"] = start + size
            # Stop if fewer results than requested -> last page
            if size < (params.get("limit") or page_size):
                break

    return collected[:limit]
