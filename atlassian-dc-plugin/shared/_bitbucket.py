"""Bitbucket Data Center HTTP client.

Mirrors the JiraClient design from `_common.py`, but speaks the Bitbucket
Server / Data Center REST API (default base path `/rest/api/1.0/`). The
universal flags, config loader, error mapping helpers, dry-run helpers,
and `run()` wrapper all live in `_common.py` — we re-use them here.

Why a separate module? `_common.py` must stay product-agnostic for the
loaders, but the HTTP client carries product-specific URL conventions
and error vocabulary, so each product gets its own client.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

import requests

from _common import (  # type: ignore
    APIError,
    AuthError,
    Instance,
    NotFoundError,
    ValidationError,
    load_instance,
)


class BitbucketClient:
    """Thin Bitbucket Server / DC REST client.

    Paths starting with ``/rest/`` are passed through as-is so callers can
    reach `/rest/branch-utils/1.0/...`, `/rest/build-status/1.0/...`,
    `/rest/search/1.0/...` etc. without a second client. Anything else is
    relative to ``/rest/api/1.0/``.
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

    # -- url plumbing ---------------------------------------------------------

    def _url(self, path: str) -> str:
        if path.startswith("/rest/"):
            return f"{self.instance.url}{path}"
        path = path.lstrip("/")
        return f"{self.instance.url}/rest/api/1.0/{path}"

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

    # -- response handling ----------------------------------------------------

    def _handle(self, resp: requests.Response) -> Any:
        if self.debug:
            sys.stderr.write(f"[debug] -> {resp.status_code}\n")
        if resp.status_code == 401:
            raise AuthError("Authentication failed. Check the PAT in instances.json.")
        if resp.status_code == 403:
            raise AuthError("Access forbidden. The PAT lacks permission for this operation.")
        if resp.status_code == 404:
            raise NotFoundError(_extract_bb_error(resp) or "Resource not found.")
        if 400 <= resp.status_code < 500:
            raise ValidationError(_extract_bb_error(resp) or f"Bad request ({resp.status_code}).")
        if resp.status_code >= 500:
            raise APIError(f"Bitbucket server error ({resp.status_code}): {_extract_bb_error(resp)}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # -- verbs ----------------------------------------------------------------

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        url = self._url(path)
        self._log("GET", url, params=params)
        return self._handle(self.session.get(url, params=params, timeout=30))

    def get_raw(self, path: str, params: Optional[dict] = None) -> requests.Response:
        """Return the raw Response — used for endpoints that return non-JSON
        (e.g. ``/raw/{path}`` or ``/diff`` in unified-diff form)."""
        url = self._url(path)
        self._log("GET", url, params=params)
        resp = self.session.get(url, params=params, timeout=30)
        if self.debug:
            sys.stderr.write(f"[debug] -> {resp.status_code}\n")
        if resp.status_code == 401:
            raise AuthError("Authentication failed. Check the PAT in instances.json.")
        if resp.status_code == 403:
            raise AuthError("Access forbidden. The PAT lacks permission for this operation.")
        if resp.status_code == 404:
            raise NotFoundError(_extract_bb_error(resp) or "Resource not found.")
        if 400 <= resp.status_code < 500:
            raise ValidationError(_extract_bb_error(resp) or f"Bad request ({resp.status_code}).")
        if resp.status_code >= 500:
            raise APIError(f"Bitbucket server error ({resp.status_code}): {_extract_bb_error(resp)}")
        return resp

    def post(self, path: str, body: Optional[dict] = None) -> Any:
        url = self._url(path)
        self._log("POST", url, json=body)
        return self._handle(self.session.post(url, json=body, timeout=30))

    def put(self, path: str, body: Optional[dict] = None) -> Any:
        url = self._url(path)
        self._log("PUT", url, json=body)
        return self._handle(self.session.put(url, json=body, timeout=30))

    def delete(self, path: str, body: Optional[dict] = None) -> Any:
        """Bitbucket DELETE often takes a JSON body (e.g. branch deletion,
        comment deletion with version)."""
        url = self._url(path)
        self._log("DELETE", url, json=body)
        return self._handle(self.session.delete(url, json=body, timeout=30))

    # -- pagination -----------------------------------------------------------

    def paginate(self, path: str, params: Optional[dict] = None,
                 limit: Optional[int] = None, page_size: int = 50) -> list:
        """Walk a Bitbucket paged response.

        Bitbucket pages use ``start`` + ``limit`` and signal completion via
        ``isLastPage`` / ``nextPageStart``. Returns the concatenated
        ``values`` list. ``limit`` caps the total number of items collected
        (``None`` = collect everything).
        """
        collected: list = []
        params = dict(params or {})
        start = int(params.pop("start", 0) or 0)
        while True:
            page_params = dict(params)
            remaining = (limit - len(collected)) if limit is not None else page_size
            this_size = min(page_size, remaining) if limit is not None else page_size
            if this_size <= 0:
                break
            page_params["start"] = start
            page_params["limit"] = this_size
            data = self.get(path, params=page_params)
            values = data.get("values", []) if isinstance(data, dict) else []
            collected.extend(values)
            if limit is not None and len(collected) >= limit:
                break
            if not isinstance(data, dict) or data.get("isLastPage", True):
                break
            next_start = data.get("nextPageStart")
            if next_start is None or next_start == start:
                break
            start = next_start
        return collected[:limit] if limit is not None else collected


def _extract_bb_error(resp: requests.Response) -> str:
    """Bitbucket errors look like ``{"errors": [{"message": "...", "context": "..."}]}``.

    Fall back to ``message`` / raw text when the shape doesn't match.
    """
    try:
        data = resp.json()
    except ValueError:
        return resp.text or ""
    if isinstance(data, dict):
        errs = data.get("errors") or []
        parts: list[str] = []
        if isinstance(errs, list):
            for e in errs:
                if isinstance(e, dict):
                    msg = e.get("message") or e.get("exceptionName") or ""
                    ctx = e.get("context")
                    if msg:
                        parts.append(f"{ctx}: {msg}" if ctx else msg)
                else:
                    parts.append(str(e))
        elif isinstance(errs, dict):
            for k, v in errs.items():
                parts.append(f"{k}: {v}")
        if parts:
            return " | ".join(parts)
        return data.get("message") or json.dumps(data)
    return str(data)


def get_bitbucket(args: argparse.Namespace) -> BitbucketClient:
    """Resolve the configured Bitbucket instance for the current CLI args."""
    inst = load_instance("bitbucket", args.instance)
    return BitbucketClient(inst, debug=args.debug)
