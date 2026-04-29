#!/usr/bin/env python3
"""Drive the Jira DC setup wizard via plain HTTP POSTs.

Robuster als Playwright, weil keine JS-Render-Latenz. Nutzt eine requests.Session
für Cookies, scrapt das atl_token aus jeder Setup-Seite mit einem regex.

Anschließend: einloggen, PAT via POST erzeugen, instances.json schreiben.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests

JIRA_URL = os.environ.get("JIRA_URL", "http://localhost:8080").rstrip("/")
LICENSE = os.environ.get("JIRA_LICENSE")
ADMIN_USER = os.environ.get("JIRA_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("JIRA_ADMIN_PASS", "admin123")
ADMIN_EMAIL = os.environ.get("JIRA_ADMIN_EMAIL", "admin@example.com")
ADMIN_FULL = os.environ.get("JIRA_ADMIN_FULL", "Local Admin")
INSTANCE_ALIAS = os.environ.get("JIRA_ALIAS", "local")

ATL_TOKEN_RE = re.compile(r'name="atl_token"\s+value="([^"]+)"', re.IGNORECASE)
ALT_TOKEN_RE = re.compile(r'id="atl_token"\s+value="([^"]+)"', re.IGNORECASE)


def log(msg: str) -> None:
    sys.stderr.write(f"[setup] {msg}\n")
    sys.stderr.flush()


def grab_token(html: str, session: requests.Session) -> Optional[str]:
    # 1) Try HTML form field
    for r in (ATL_TOKEN_RE, ALT_TOKEN_RE):
        m = r.search(html)
        if m and m.group(1):
            return m.group(1)
    # 2) Fall back to cookie
    return session.cookies.get("atl_token")


def post(s: requests.Session, url: str, data: dict, **kw) -> requests.Response:
    """POST with X-Atlassian-Token bypass — required for Jira wizard endpoints."""
    headers = kw.pop("headers", {}) or {}
    headers.setdefault("X-Atlassian-Token", "no-check")
    return s.post(url, data=data, headers=headers, timeout=kw.pop("timeout", 120),
                  allow_redirects=kw.pop("allow_redirects", True), **kw)


def step_properties(s: requests.Session) -> None:
    log("step: Application Properties")
    r = s.get(f"{JIRA_URL}/secure/SetupApplicationProperties!default.jspa", timeout=60)
    r.raise_for_status()
    if "SetupApplicationProperties" not in r.url and "SetupApplicationProperties" not in r.text:
        log(f"  skipping: not on properties page (url={r.url})")
        return
    token = grab_token(r.text, s) or ""
    payload = {
        "title": "Local Jira DC",
        "mode": "private",
        "baseURL": JIRA_URL,
        "nextStep": "true",
        "atl_token": token,
    }
    r = post(s, f"{JIRA_URL}/secure/SetupApplicationProperties.jspa", payload, timeout=120)
    log(f"  -> {r.status_code} {r.url}")


def step_license(s: requests.Session) -> None:
    log("step: License")
    if not LICENSE:
        sys.exit("error: $JIRA_LICENSE not set")
    r = s.get(f"{JIRA_URL}/secure/SetupLicense!default.jspa", timeout=60)
    r.raise_for_status()
    token = grab_token(r.text, s) or ""
    payload = {
        "setupLicenseKey": LICENSE,
        "next": "true",
        "atl_token": token,
    }
    r = post(s, f"{JIRA_URL}/secure/SetupLicense.jspa", payload, timeout=300)
    log(f"  -> {r.status_code} {r.url}")
    if "License is invalid" in r.text or "license error" in r.text.lower():
        sys.exit("error: license rejected by Jira; check the key")


def step_admin(s: requests.Session) -> None:
    log("step: Admin Account")
    # Wait until SetupAdminAccount becomes available — Jira may still be reloading
    # plugins after the license.
    deadline = time.time() + 600
    while time.time() < deadline:
        r = s.get(f"{JIRA_URL}/secure/SetupAdminAccount!default.jspa",
                  timeout=60, allow_redirects=True)
        if r.status_code == 200 and "SetupAdminAccount" in r.url:
            break
        if r.status_code == 200 and "SetupAdminAccount" in r.text:
            break
        log(f"  waiting (admin step not ready, url={r.url})")
        time.sleep(5)
    else:
        sys.exit("error: timed out waiting for admin step")

    token = grab_token(r.text, s) or ""
    payload = {
        "fullname": ADMIN_FULL,
        "email": ADMIN_EMAIL,
        "username": ADMIN_USER,
        "password": ADMIN_PASS,
        "confirm": ADMIN_PASS,
        "next": "true",
        "atl_token": token,
    }
    r = post(s, f"{JIRA_URL}/secure/SetupAdminAccount.jspa", payload, timeout=120)
    log(f"  -> {r.status_code} {r.url}")


def step_mail(s: requests.Session) -> None:
    log("step: Mail (skip)")
    r = s.get(f"{JIRA_URL}/secure/SetupMailNotifications!default.jspa",
              timeout=60, allow_redirects=True)
    if "SetupMailNotifications" not in r.url:
        log(f"  not on mail step (url={r.url}), continuing")
        return
    token = grab_token(r.text, s) or ""
    # The "Finish" button posts noemail=true.
    payload = {"noemail": "true", "atl_token": token}
    r = post(s, f"{JIRA_URL}/secure/SetupMailNotifications.jspa", payload, timeout=60)
    log(f"  -> {r.status_code} {r.url}")


def login(s: requests.Session) -> None:
    log("login")
    r = s.post(f"{JIRA_URL}/login.jsp", data={
        "os_username": ADMIN_USER,
        "os_password": ADMIN_PASS,
        "os_destination": "",
        "user_role": "",
        "atl_token": "",
        "login": "Log In",
    }, timeout=60, allow_redirects=True)
    if "loginfailed=true" in r.url or "Sorry, your username and password are incorrect" in r.text:
        sys.exit("error: login failed")
    log(f"  -> {r.status_code} {r.url}")


def create_pat(s: requests.Session) -> str:
    """Create a Personal Access Token via the same REST endpoint the UI uses."""
    log("create PAT via /rest/pat/latest/tokens")
    # The PAT REST endpoint requires either basic auth or an existing session
    # AND an atl_token (XSRF). We have the session from login.
    r = s.get(f"{JIRA_URL}/plugins/servlet/access-tokens/manage/usertokens", timeout=60)
    if r.status_code != 200:
        log(f"  PAT page status {r.status_code} (continuing anyway)")
    # Try the JSON REST endpoint first (Jira 9.x ships an internal one).
    body = {"name": "skill-test", "expirationDuration": 90}
    headers = {
        "Content-Type": "application/json",
        "X-Atlassian-Token": "no-check",
    }
    r = s.post(f"{JIRA_URL}/rest/pat/latest/tokens", json=body,
               headers=headers, timeout=60)
    log(f"  POST /rest/pat/latest/tokens -> {r.status_code}")
    if r.status_code in (200, 201):
        data = r.json()
        token = data.get("rawToken") or data.get("token") or data.get("value")
        if token:
            return token
    # Fallback: JSP-based form (older Jira).
    log("  falling back to form-based create")
    r = s.get(f"{JIRA_URL}/secure/ViewProfile!default.jspa", timeout=60)
    raise RuntimeError(f"could not create PAT — last status {r.status_code}, "
                       f"response head: {r.text[:200]!r}")


def write_instances(token: str) -> Path:
    if os.name == "nt" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / "atlassian" / "instances.json"
    else:
        path = Path.home() / ".config" / "atlassian" / "instances.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8"))
    else:
        cfg = {"default": INSTANCE_ALIAS, "instances": {}}
    cfg.setdefault("instances", {}).setdefault(INSTANCE_ALIAS, {})
    cfg["instances"][INSTANCE_ALIAS]["jira"] = {
        "url": JIRA_URL,
        "token": token,
        "ssl_verify": False,
    }
    cfg.setdefault("default", INSTANCE_ALIAS)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def main():
    s = requests.Session()
    s.headers.update({"User-Agent": "atlassian-dc-setup/1.0"})

    # Order matters; each step is a no-op if Jira is past it.
    step_properties(s)
    step_license(s)
    step_admin(s)
    step_mail(s)
    login(s)
    token = create_pat(s)
    path = write_instances(token)

    print(json.dumps({
        "instances_file": str(path),
        "alias": INSTANCE_ALIAS,
        "jira_url": JIRA_URL,
        "admin_user": ADMIN_USER,
        "token_length": len(token),
        "token_preview": token[:4] + "..." + token[-4:],
    }, indent=2))


if __name__ == "__main__":
    main()
