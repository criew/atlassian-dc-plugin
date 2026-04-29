#!/usr/bin/env python3
"""Interactive instance + PAT setup for the Atlassian DC plugin.

Walks the user through:
  1. choosing/creating an alias (default: 'local')
  2. picking which products (jira / confluence / bitbucket) to configure
  3. for each: base URL, username, password
  4. logging in + creating a Personal Access Token via REST
     (with basic-auth fallback if cookie login refuses)
  5. writing the result into instances.json

Idempotent: running again with the same alias overwrites only the products
named on this run; other products + other aliases stay untouched. Adding a
new alias 'staging' later does not affect 'local'.

Usage:
    python setup_instance.py                              # fully interactive
    python setup_instance.py --alias prod --product jira --product confluence
    python setup_instance.py --alias local --product all --non-interactive \\
        --jira-url http://localhost:8080 --jira-user admin --jira-pass admin123 \\
        --confluence-url http://localhost:8090 --confluence-user admin --confluence-pass admin123 \\
        --bitbucket-url http://localhost:7990 --bitbucket-user admin --bitbucket-pass admin123
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import requests

PRODUCTS = ("jira", "confluence", "bitbucket")

# Token endpoints + auth flows are the same as dev/get_pat.py — kept in sync.
PRODUCT_LOGIN = {
    "jira": {
        "login_url":  "{base}/login.jsp",
        "verify_url": "{base}/rest/api/2/myself",
        "pat_url":    "{base}/rest/pat/latest/tokens",
        "login_form": lambda u, p: {"os_username": u, "os_password": p,
                                     "os_destination": "", "user_role": "",
                                     "atl_token": "", "login": "Log In"},
        "fail_signal": "Sorry, your username and password are incorrect",
    },
    "confluence": {
        "login_url":  "{base}/dologin.action",
        "verify_url": "{base}/rest/api/user/current",
        "pat_url":    "{base}/rest/pat/latest/tokens",
        "login_form": lambda u, p: {"os_username": u, "os_password": p,
                                     "login": "Log in",
                                     "os_destination": "/index.action"},
        "fail_signal": "incorrect",
    },
    "bitbucket": {
        "login_url":  "{base}/j_atl_security_check",
        "verify_url": "{base}/rest/api/1.0/users/{user}",
        "pat_url":    "{base}/rest/access-tokens/latest/users/{user}",
        "login_form": lambda u, p: {"j_username": u, "j_password": p,
                                     "_atl_remember_me": "on", "submit": "Log in"},
        "fail_signal": "Unable to log in",
    },
}


# -----------------------------------------------------------------------------
# Instance file IO
# -----------------------------------------------------------------------------

def _instances_file() -> Path:
    explicit = os.environ.get("ATLASSIAN_INSTANCES_FILE")
    if explicit:
        return Path(explicit)
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "atlassian" / "instances.json"
    return Path.home() / ".config" / "atlassian" / "instances.json"


def _load_instances() -> dict:
    path = _instances_file()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"default": "local", "instances": {}}


def _save_instances(cfg: dict) -> Path:
    path = _instances_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


# -----------------------------------------------------------------------------
# PAT creation
# -----------------------------------------------------------------------------

def _create_pat_via_session(s: requests.Session, product: str, base: str,
                            user: str, pw: str, name: str, days: int) -> str | None:
    cfg = PRODUCT_LOGIN[product]
    # Login
    r = s.post(cfg["login_url"].format(base=base, user=user),
               data=cfg["login_form"](user, pw),
               allow_redirects=True, timeout=30)
    if "loginfailed" in r.url or cfg["fail_signal"] in r.text:
        return None
    # Sanity-check via verify endpoint
    v = s.get(cfg["verify_url"].format(base=base, user=user), timeout=30)
    if v.status_code != 200:
        return None
    return _post_pat(s, product, base, user, name, days, basic_auth=None)


def _post_pat(s: requests.Session, product: str, base: str, user: str,
              name: str, days: int, basic_auth=None) -> str | None:
    headers = {"Content-Type": "application/json", "X-Atlassian-Token": "no-check"}
    body = {"name": name, "expirationDuration": days}
    if product == "bitbucket":
        body["permissions"] = ["PROJECT_ADMIN", "REPO_ADMIN"]
        url = PRODUCT_LOGIN[product]["pat_url"].format(base=base, user=user)
        r = s.put(url, json=body, headers=headers, auth=basic_auth, timeout=60)
    else:
        url = PRODUCT_LOGIN[product]["pat_url"].format(base=base, user=user)
        r = s.post(url, json=body, headers=headers, auth=basic_auth, timeout=60)
    if r.status_code not in (200, 201):
        sys.stderr.write(f"  PAT call returned {r.status_code}: {r.text[:200]}\n")
        return None
    j = r.json()
    return (j.get("rawToken") or j.get("token")
            or j.get("value") or j.get("secret"))


def get_pat(product: str, base: str, user: str, pw: str,
            name: str = "skill-test", days: int = 90) -> str:
    """Try cookie-based session first, then fall back to basic auth."""
    base = base.rstrip("/")
    s = requests.Session()
    s.headers.update({"User-Agent": "atlassian-dc-setup-instance/1.0"})
    token = _create_pat_via_session(s, product, base, user, pw, name, days)
    if token:
        return token
    sys.stderr.write("  cookie login failed, trying basic auth on PAT endpoint…\n")
    s2 = requests.Session()
    s2.headers.update({"User-Agent": "atlassian-dc-setup-instance/1.0"})
    token = _post_pat(s2, product, base, user, name, days, basic_auth=(user, pw))
    if token:
        return token
    sys.exit(f"error: could not obtain PAT for {product} — check user/pass and "
             f"that {base} is reachable")


def verify_pat(product: str, base: str, user: str, token: str) -> int:
    if product == "bitbucket":
        url = f"{base.rstrip('/')}/rest/api/1.0/users/{user}"
    elif product == "confluence":
        url = f"{base.rstrip('/')}/rest/api/user/current"
    else:
        url = f"{base.rstrip('/')}/rest/api/2/myself"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return r.status_code


# -----------------------------------------------------------------------------
# Interactive prompts
# -----------------------------------------------------------------------------

def prompt(question: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        ans = input(f"{question}{suffix}: ").strip()
        if ans:
            return ans
        if default is not None:
            return default


def prompt_secret(question: str) -> str:
    return getpass.getpass(f"{question}: ").strip()


def prompt_yes(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    ans = input(f"{question} {suffix}: ").strip().lower()
    if not ans:
        return default
    return ans.startswith("y")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--alias", help="instance alias (default: prompt)")
    p.add_argument("--product", action="append",
                   help="product(s) to configure; repeat. Use 'all' to mean jira+confluence+bitbucket")
    p.add_argument("--non-interactive", action="store_true",
                   help="fail if any required input is missing instead of prompting")
    p.add_argument("--make-default", action="store_true",
                   help="set this alias as the default in instances.json")
    # Per-product flags for non-interactive use.
    for prod in PRODUCTS:
        p.add_argument(f"--{prod}-url")
        p.add_argument(f"--{prod}-user")
        p.add_argument(f"--{prod}-pass")
    args = p.parse_args()

    cfg = _load_instances()
    existing_aliases = list(cfg.get("instances", {}).keys())

    # Alias
    alias = args.alias
    if not alias:
        if args.non_interactive:
            sys.exit("error: --alias required in --non-interactive mode")
        if existing_aliases:
            print(f"existing aliases: {', '.join(existing_aliases)}")
        alias = prompt("Alias for this instance", default=cfg.get("default", "local"))

    # Products
    products = args.product or []
    if "all" in products:
        products = list(PRODUCTS)
    if not products:
        if args.non_interactive:
            sys.exit("error: --product required in --non-interactive mode")
        wanted = []
        for prod in PRODUCTS:
            if prompt_yes(f"Configure {prod}?", default=True):
                wanted.append(prod)
        products = wanted
    if not products:
        sys.exit("error: no products selected")

    # Per-product credentials
    per_product: dict[str, dict[str, str]] = {}
    for prod in products:
        url = getattr(args, f"{prod}_url")
        user = getattr(args, f"{prod}_user")
        pw = getattr(args, f"{prod}_pass")
        if not url:
            if args.non_interactive:
                sys.exit(f"error: --{prod}-url required")
            url = prompt(f"{prod} base URL")
        if not user:
            if args.non_interactive:
                sys.exit(f"error: --{prod}-user required")
            user = prompt(f"{prod} admin username", default="admin")
        if not pw:
            if args.non_interactive:
                sys.exit(f"error: --{prod}-pass required")
            pw = prompt_secret(f"{prod} password for {user}")
        per_product[prod] = {"url": url.rstrip("/"), "user": user, "pass": pw}

    # Create PATs and write
    cfg.setdefault("instances", {}).setdefault(alias, {})
    print()
    for prod, c in per_product.items():
        print(f"[{prod}] login + PAT create at {c['url']} as {c['user']}")
        token = get_pat(prod, c["url"], c["user"], c["pass"])
        code = verify_pat(prod, c["url"], c["user"], token)
        if code != 200:
            sys.stderr.write(f"  warning: PAT verify returned {code}\n")
        cfg["instances"][alias][prod] = {
            "url": c["url"], "token": token, "ssl_verify": False,
        }
        print(f"  -> token captured (length {len(token)}, "
              f"preview {token[:4]}...{token[-4:]}, verify {code})")

    if args.make_default or "default" not in cfg or not cfg.get("default"):
        cfg["default"] = alias

    out = _save_instances(cfg)
    print()
    print(f"wrote {out}")
    print(f"alias '{alias}' now has products: {sorted(cfg['instances'][alias].keys())}")
    if cfg.get("default") == alias:
        print(f"alias '{alias}' is the default")
    else:
        print(f"default remains '{cfg.get('default')}' "
              f"(use --make-default to change, or edit instances.json manually)")


if __name__ == "__main__":
    main()
