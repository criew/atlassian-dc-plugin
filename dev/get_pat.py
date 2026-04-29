#!/usr/bin/env python3
"""Generic PAT bootstrapper for Jira / Confluence / Bitbucket DC.

Run this AFTER you have manually clicked through each product's first-run
wizard (admin user created, license accepted, login works). It will:
  1. log in via username + password
  2. create a Personal Access Token via the product's REST endpoint
  3. write the token into ~/.config/atlassian/instances.json (or %APPDATA%)
     under the chosen alias and product key

Why no automation of the wizard? In every product the wizard renders some
fields via JS, has strict XSRF, and may require an Atlassian.com round-trip
for the license. Manual click-through takes 60 seconds and is reliable.

Usage:
    JIRA_PASS=...  python dev/get_pat.py jira       --user admin --base-url http://localhost:8080
    CONF_PASS=...  python dev/get_pat.py confluence --user admin --base-url http://localhost:8090
    BB_PASS=...    python dev/get_pat.py bitbucket  --user admin --base-url http://localhost:7990

Defaults: alias=local, token name=skill-test, expiration 90 days.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

PRODUCTS = {
    "jira": {
        "login_url":  "{base}/login.jsp",
        "verify_url": "{base}/rest/api/2/myself",
        "pat_url":    "{base}/rest/pat/latest/tokens",
        "pass_env":   "JIRA_PASS",
    },
    "confluence": {
        "login_url":  "{base}/dologin.action",
        "verify_url": "{base}/rest/api/user/current",
        "pat_url":    "{base}/rest/pat/latest/tokens",
        "pass_env":   "CONF_PASS",
    },
    "bitbucket": {
        "login_url":  "{base}/j_atl_security_check",
        "verify_url": "{base}/rest/api/1.0/users/{user}",
        # Bitbucket's PAT REST endpoint differs.
        "pat_url":    "{base}/rest/access-tokens/latest/users/{user}",
        "pass_env":   "BB_PASS",
        "permissions": ["PROJECT_ADMIN", "REPO_ADMIN"],
    },
}


def log(msg: str) -> None:
    sys.stderr.write(f"[get-pat] {msg}\n")
    sys.stderr.flush()


def login(s: requests.Session, product: str, base: str, user: str, pw: str) -> None:
    cfg = PRODUCTS[product]
    url = cfg["login_url"].format(base=base, user=user)
    if product == "bitbucket":
        # Bitbucket uses j_atl_security_check with j_username/j_password
        r = s.post(url, data={
            "j_username": user, "j_password": pw,
            "_atl_remember_me": "on", "submit": "Log in",
        }, allow_redirects=True, timeout=60)
    elif product == "confluence":
        r = s.post(url, data={
            "os_username": user, "os_password": pw,
            "login": "Log in", "os_destination": "/index.action",
        }, allow_redirects=True, timeout=60)
    else:  # jira
        r = s.post(url, data={
            "os_username": user, "os_password": pw,
            "os_destination": "", "user_role": "", "atl_token": "", "login": "Log In",
        }, allow_redirects=True, timeout=60)
    log(f"login {product} -> {r.status_code} {r.url}")
    if "loginfailed" in r.url or "Sorry, your username and password are incorrect" in r.text:
        sys.exit(f"error: {product} login failed (check user/password)")


def verify(s: requests.Session, product: str, base: str, user: str) -> None:
    cfg = PRODUCTS[product]
    url = cfg["verify_url"].format(base=base, user=user)
    r = s.get(url, timeout=30)
    if r.status_code != 200:
        # Fall back to basic auth so the next call works.
        log(f"session-cookie verify failed ({r.status_code}); will use basic auth")
        return
    log(f"verify {product} -> 200 OK")


def create_pat(s: requests.Session, product: str, base: str, user: str, name: str, days: int,
               basic_auth: tuple[str, str] | None = None) -> str:
    cfg = PRODUCTS[product]
    url = cfg["pat_url"].format(base=base, user=user)
    headers = {"Content-Type": "application/json", "X-Atlassian-Token": "no-check"}
    body = {"name": name, "expirationDuration": days}
    if product == "bitbucket":
        body["permissions"] = cfg["permissions"]
    auth = basic_auth  # falls back to session cookies if None
    if product == "bitbucket":
        # Bitbucket uses PUT
        r = s.put(url, json=body, headers=headers, auth=auth, timeout=60)
    else:
        r = s.post(url, json=body, headers=headers, auth=auth, timeout=60)
    log(f"create-pat {product} -> {r.status_code}")
    if r.status_code not in (200, 201):
        sys.exit(f"error: {product} PAT creation failed: {r.status_code} {r.text[:300]!r}")
    data = r.json()
    return data.get("rawToken") or data.get("token") or data.get("value") or data.get("secret")


def write_instances(product: str, base: str, alias: str, token: str) -> Path:
    if os.name == "nt" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / "atlassian" / "instances.json"
    else:
        path = Path.home() / ".config" / "atlassian" / "instances.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"default": alias, "instances": {}}
    cfg.setdefault("instances", {}).setdefault(alias, {})
    cfg["instances"][alias][product] = {"url": base, "token": token, "ssl_verify": False}
    cfg.setdefault("default", alias)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("product", choices=list(PRODUCTS.keys()))
    p.add_argument("--user", required=True, help="admin username (e.g. 'admin')")
    p.add_argument("--base-url", required=True, help="e.g. http://localhost:8080")
    p.add_argument("--alias", default=os.environ.get("ATLASSIAN_ALIAS", "local"))
    p.add_argument("--name", default="skill-test", help="PAT name shown in Jira UI")
    p.add_argument("--days", type=int, default=90)
    args = p.parse_args()

    pass_env = PRODUCTS[args.product]["pass_env"]
    pw = os.environ.get(pass_env)
    if not pw:
        sys.exit(f"error: set ${pass_env} env var (admin password)")

    base = args.base_url.rstrip("/")
    s = requests.Session()
    s.headers.update({"User-Agent": "atlassian-dc-get-pat/1.0"})

    # Try cookie-based login; if it fails, fall back to basic auth for the PAT call.
    try:
        login(s, args.product, base, args.user, pw)
        verify(s, args.product, base, args.user)
        token = create_pat(s, args.product, base, args.user, args.name, args.days)
    except SystemExit:
        log("cookie login failed; retrying with basic auth on the PAT endpoint")
        s2 = requests.Session()
        s2.headers.update({"User-Agent": "atlassian-dc-get-pat/1.0"})
        token = create_pat(s2, args.product, base, args.user, args.name, args.days,
                           basic_auth=(args.user, pw))
    if not token:
        sys.exit("error: token missing in API response")
    path = write_instances(args.product, base, args.alias, token)

    print(json.dumps({
        "instances_file": str(path),
        "alias": args.alias,
        "product": args.product,
        "base_url": base,
        "user": args.user,
        "token_length": len(token),
        "token_preview": token[:4] + "..." + token[-4:],
    }, indent=2))


if __name__ == "__main__":
    main()
