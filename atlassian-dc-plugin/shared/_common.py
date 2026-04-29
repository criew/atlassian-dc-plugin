"""Shared utilities for Atlassian Data Center skill scripts.

Provides:
- Multi-instance config loader (instances.json with aliases)
- HTTP client with PAT auth
- Consistent argparse setup (--instance, --json, --quiet, --debug, --dry-run)
- Error formatting
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests


# =============================================================================
# Errors
# =============================================================================

class SkillError(Exception):
    """Base for all skill errors. exit_code is the CLI exit status."""
    exit_code = 1


class ConfigError(SkillError):
    exit_code = 2


class AuthError(SkillError):
    exit_code = 3


class NotFoundError(SkillError):
    exit_code = 4


class ValidationError(SkillError):
    exit_code = 5


class APIError(SkillError):
    exit_code = 6


# =============================================================================
# Instance configuration
# =============================================================================

@dataclass
class Instance:
    alias: str
    product: str
    url: str
    token: str
    ssl_verify: bool = True


def _config_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("ATLASSIAN_INSTANCES_FILE")
    if explicit:
        paths.append(Path(explicit))
    paths.append(Path.home() / ".config" / "atlassian" / "instances.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "atlassian" / "instances.json")
    return paths


def _load_config_file() -> dict:
    for p in _config_paths():
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ConfigError(f"Invalid JSON in {p}: {e}")
    tried = "\n  ".join(str(p) for p in _config_paths())
    raise ConfigError(
        "instances.json not found. Tried:\n  " + tried +
        "\nCopy instances.json.example to one of these locations and fill in your PAT."
    )


def load_instance(product: str, alias: Optional[str] = None) -> Instance:
    """Resolve an instance for a given product.

    Resolution order for alias:
      1. explicit `alias` arg (from --instance CLI flag)
      2. ATLASSIAN_INSTANCE env var
      3. config "default" field
    """
    cfg = _load_config_file()

    chosen = alias or os.environ.get("ATLASSIAN_INSTANCE") or cfg.get("default")
    if not chosen:
        raise ConfigError("No instance alias given and no 'default' set in instances.json.")

    instances = cfg.get("instances", {})
    if chosen not in instances:
        available = ", ".join(instances.keys()) or "(none)"
        raise ConfigError(f"Instance '{chosen}' not found. Available: {available}")

    entry = instances[chosen]
    if product not in entry:
        raise ConfigError(
            f"Instance '{chosen}' has no '{product}' configuration. "
            f"Available products: {', '.join(entry.keys()) or '(none)'}"
        )

    pdata = entry[product]
    url = pdata.get("url", "").rstrip("/")
    token = pdata.get("token", "")
    if not url or not token:
        raise ConfigError(f"Instance '{chosen}' {product} entry missing url or token.")

    return Instance(
        alias=chosen,
        product=product,
        url=url,
        token=token,
        ssl_verify=pdata.get("ssl_verify", True),
    )


# =============================================================================
# HTTP client
# =============================================================================

class JiraClient:
    """Thin Jira REST API v2 client.

    All paths are relative to /rest/api/2 unless they start with /rest/.
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
        return f"{self.instance.url}/rest/api/2/{path}"

    def _log(self, method: str, url: str, **kw):
        if not self.debug:
            return
        masked_url = url
        body = kw.get("json")
        params = kw.get("params")
        sys.stderr.write(f"[debug] {method} {masked_url}\n")
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
            raise APIError(f"Jira server error ({resp.status_code}): {_extract_error(resp)}")
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

    def delete(self, path: str) -> Any:
        url = self._url(path)
        self._log("DELETE", url)
        return self._handle(self.session.delete(url, timeout=30))


def _extract_error(resp: requests.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text or ""
    if isinstance(data, dict):
        msgs = data.get("errorMessages") or []
        errs = data.get("errors") or {}
        parts = list(msgs)
        for k, v in errs.items():
            parts.append(f"{k}: {v}")
        if parts:
            return " | ".join(parts)
        return data.get("message", "") or json.dumps(data)
    return str(data)


# =============================================================================
# Argparse helpers
# =============================================================================

def add_common_args(p: argparse.ArgumentParser) -> None:
    """Add the universal flags to a parser."""
    p.add_argument("--instance", "-i", help="Instance alias from instances.json")
    p.add_argument("--json", action="store_true", help="Raw JSON output")
    p.add_argument("--quiet", "-q", action="store_true", help="Errors only")
    p.add_argument("--debug", action="store_true", help="Verbose request logging on stderr")
    p.add_argument("--dry-run", action="store_true",
                   help="Print intended request without executing (write ops only)")


def get_jira(args: argparse.Namespace) -> JiraClient:
    inst = load_instance("jira", args.instance)
    return JiraClient(inst, debug=args.debug)


# =============================================================================
# Output helpers
# =============================================================================

def emit(data: Any, args: argparse.Namespace, human: Optional[str] = None) -> None:
    """Print result respecting --json/--quiet."""
    if args.quiet:
        return
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif human is not None:
        print(human)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def emit_dry_run(intent: dict, args: argparse.Namespace, human: str) -> None:
    """Always-visible marker for --dry-run, regardless of --quiet.

    Weak LLMs must not mistake dry-run for actual success. We:
      - prefix human output with 'DRY RUN:'
      - always print to stderr too, even with --quiet, so it cannot be missed
      - tag JSON with `"dry_run": true` and `"executed": false`
    """
    payload = {"dry_run": True, "executed": False, "intent": intent}
    sys.stderr.write(f"[DRY RUN] {human} — no request was sent.\n")
    if args.quiet:
        return
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"DRY RUN: {human}\n  (no request was sent)")


def die(err: Exception) -> None:
    """Print error to stderr and exit with proper code."""
    if isinstance(err, SkillError):
        sys.stderr.write(f"error: {err}\n")
        sys.exit(err.exit_code)
    sys.stderr.write(f"error: {err}\n")
    sys.exit(1)


def run(main_fn):
    """Wrap main() with consistent error handling."""
    try:
        main_fn()
    except SkillError as e:
        die(e)
    except requests.exceptions.ConnectionError as e:
        die(APIError(f"Cannot reach Jira: {e}"))
    except requests.exceptions.Timeout:
        die(APIError("Request timed out."))
    except KeyboardInterrupt:
        sys.exit(130)


# =============================================================================
# Field simplification (optional helper)
# =============================================================================

# =============================================================================
# Rules loader (per-instance markdown rules)
# =============================================================================

def _rules_paths(alias: str) -> list[Path]:
    paths: list[Path] = []
    explicit_dir = os.environ.get("ATLASSIAN_CONFIG_DIR")
    if explicit_dir:
        paths.append(Path(explicit_dir) / "rules" / f"{alias}.md")
    paths.append(Path.home() / ".config" / "atlassian" / "rules" / f"{alias}.md")
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "atlassian" / "rules" / f"{alias}.md")
    return paths


def load_rules(alias: str, project: Optional[str] = None) -> dict:
    """Load per-instance rules from markdown.

    Returns a dict:
      {
        "found": bool,
        "path": "<resolved path or None>",
        "instance": alias,
        "project": project,
        "content": "<filtered markdown text>",
      }

    If `project` is given, only the `## Global` section and the matching
    `## Project <KEY>` section are returned (case-sensitive on KEY). Without
    `project`, the whole file is returned.

    `found=False` is NOT an error — instances may simply have no rules. The
    caller decides whether to nag the user.
    """
    chosen_path: Optional[Path] = None
    for p in _rules_paths(alias):
        if p.exists():
            chosen_path = p
            break

    if not chosen_path:
        return {
            "found": False,
            "path": None,
            "instance": alias,
            "project": project,
            "content": "",
            "searched": [str(p) for p in _rules_paths(alias)],
        }

    text = chosen_path.read_text(encoding="utf-8")
    if not project:
        return {
            "found": True,
            "path": str(chosen_path),
            "instance": alias,
            "project": None,
            "content": text,
        }

    # Filter to Global + matching Project section.
    lines = text.splitlines()
    keep: list[str] = []
    current_kind: Optional[str] = None  # "global", "project-match", "skip", None
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            hl = heading.lower()
            if hl == "global":
                current_kind = "global"
            elif hl.startswith("project "):
                key = heading[len("Project "):].strip()
                current_kind = "project-match" if key == project else "skip"
            else:
                current_kind = None  # top-level non-section, keep as-is
        elif stripped.startswith("# "):
            current_kind = None  # title line, always keep

        if current_kind in (None, "global", "project-match"):
            keep.append(line)

    return {
        "found": True,
        "path": str(chosen_path),
        "instance": alias,
        "project": project,
        "content": "\n".join(keep).strip() + "\n",
    }


def simplify_issue(raw: dict) -> dict:
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
