"""Base utilities for Atlassian Data Center skill scripts.

Provides:
- Multi-instance config loader (instances.json with aliases)
- Consistent argparse setup (--instance, --json, --quiet, --debug, --dry-run)
- Output helpers (emit, emit_dry_run)
- Error types and handler (run wrapper)
- Rules loader (per-instance markdown rules)
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

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

class Instance:
    def __init__(self, alias, product, url, token, ssl_verify=True):
        self.alias = alias
        self.product = product
        self.url = url
        self.token = token
        self.ssl_verify = ssl_verify


def _config_paths():
    # type: () -> List[Path]
    paths = []
    explicit = os.environ.get("ATLASSIAN_INSTANCES_FILE")
    if explicit:
        paths.append(Path(explicit))
    paths.append(Path.home() / ".config" / "atlassian" / "instances.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "atlassian" / "instances.json")
    return paths


def _load_config_file():
    # type: () -> dict
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


def load_instance(product, alias=None):
    # type: (str, Optional[str]) -> Instance
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


def _extract_error(resp):
    # type: (requests.Response) -> str
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

def add_common_args(p):
    # type: (argparse.ArgumentParser) -> None
    """Add the universal flags to a parser."""
    p.add_argument("--instance", "-i", help="Instance alias from instances.json")
    p.add_argument("--json", action="store_true", help="Raw JSON output")
    p.add_argument("--quiet", "-q", action="store_true", help="Errors only")
    p.add_argument("--debug", action="store_true", help="Verbose request logging on stderr")
    p.add_argument("--dry-run", action="store_true",
                   help="Print intended request without executing (write ops only)")


# =============================================================================
# Output helpers
# =============================================================================

def emit(data, args, human=None):
    # type: (Any, argparse.Namespace, Optional[str]) -> None
    """Print result respecting --json/--quiet."""
    if args.quiet:
        return
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif human is not None:
        print(human)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def emit_dry_run(intent, args, human):
    # type: (dict, argparse.Namespace, str) -> None
    """Always-visible marker for --dry-run, regardless of --quiet."""
    payload = {"dry_run": True, "executed": False, "intent": intent}
    sys.stderr.write(f"[DRY RUN] {human} — no request was sent.\n")
    if args.quiet:
        return
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"DRY RUN: {human}\n  (no request was sent)")


def die(err):
    # type: (Exception) -> None
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
        die(APIError(f"Connection failed: {e}"))
    except requests.exceptions.Timeout:
        die(APIError("Request timed out."))
    except KeyboardInterrupt:
        sys.exit(130)


# =============================================================================
# Rules loader (per-instance markdown rules)
# =============================================================================

def _rules_paths(alias):
    # type: (str) -> List[Path]
    paths = []
    explicit_dir = os.environ.get("ATLASSIAN_CONFIG_DIR")
    if explicit_dir:
        paths.append(Path(explicit_dir) / "rules" / f"{alias}.md")
    paths.append(Path.home() / ".config" / "atlassian" / "rules" / f"{alias}.md")
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "atlassian" / "rules" / f"{alias}.md")
    return paths


def load_rules(alias, project=None):
    # type: (str, Optional[str]) -> dict
    """Load per-instance rules from markdown."""
    chosen_path = None  # type: Optional[Path]
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

    lines = text.splitlines()
    keep = []
    current_kind = None  # type: Optional[str]
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
                current_kind = None
        elif stripped.startswith("# "):
            current_kind = None

        if current_kind in (None, "global", "project-match"):
            keep.append(line)

    return {
        "found": True,
        "path": str(chosen_path),
        "instance": alias,
        "project": project,
        "content": "\n".join(keep).strip() + "\n",
    }
