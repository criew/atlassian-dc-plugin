#!/usr/bin/env python3
"""Fully automated first-run setup for Jira / Confluence / Bitbucket DC.

Walks the install wizard via HTTP (no Playwright needed for any of the three
8.x/9.x products tested), creates a Personal Access Token, writes
~/.config/atlassian/instances.json (or %APPDATA%\\atlassian\\instances.json) for
the chosen product under instances.local.<product>, then verifies with a
direct API call.

Usage:
    python dev/auto_setup.py jira       --base-url http://localhost:8080
    python dev/auto_setup.py confluence --base-url http://localhost:8090
    python dev/auto_setup.py bitbucket  --base-url http://localhost:7990

Admin credentials and metadata come from environment variables (with
sensible local-dev defaults):

    JIRA_ADMIN_USER / CONF_ADMIN_USER / BB_ADMIN_USER          (default: admin)
    JIRA_ADMIN_PASS / CONF_ADMIN_PASS / BB_ADMIN_PASS          (default: admin123)
    JIRA_ADMIN_EMAIL / CONF_ADMIN_EMAIL / BB_ADMIN_EMAIL       (default: admin@example.com)
    JIRA_ADMIN_FULLNAME / CONF_ADMIN_FULLNAME / BB_ADMIN_FULLNAME  (default: Local Admin)

Special behaviour:
  * If a base URL already serves a logged-in instance (no wizard), the wizard
    is skipped and we go straight to PAT creation.
  * Confluence is driven step-by-step through /setup/*.action pages.
  * Bitbucket is a single multi-step page at /setup with a `step` field.
  * Jira walks the four /secure/Setup*!default.jspa pages; the license input
    is JS-rendered, so we POST directly to /secure/SetupLicense.jspa.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

# --- shared helpers ---------------------------------------------------------

def log(msg: str) -> None:
    sys.stderr.write(f"[auto-setup] {msg}\n")
    sys.stderr.flush()


def env_default(*names: str, default: str) -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


def read_admin(product: str) -> dict:
    upper = {"jira": "JIRA", "confluence": "CONF", "bitbucket": "BB"}[product]
    return {
        "user":     env_default(f"{upper}_ADMIN_USER",     default="admin"),
        "pass":     env_default(f"{upper}_ADMIN_PASS",     default="admin123"),
        "email":    env_default(f"{upper}_ADMIN_EMAIL",    default="admin@example.com"),
        "fullname": env_default(f"{upper}_ADMIN_FULLNAME", default="Local Admin"),
    }


def fetch_license(product: str) -> str:
    """Use the existing fetch_license module to obtain a fresh time-bomb key."""
    # Import lazily so the script still works as a one-file thing if run with -m.
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from fetch_license import fetch_html, extract_licenses_by_section, pick_license  # type: ignore

    log(f"fetching time-bomb license for {product}")
    pairs = extract_licenses_by_section(fetch_html())
    key = pick_license(pairs, product)
    if not key:
        sys.exit(f"error: no license found for {product}")
    log(f"got license: {len(key)} chars, {key[:8]}...{key[-8:]}")
    return key


ATL_TOKEN_RE  = re.compile(r'name=["\']atl_token["\']\s+value=["\']([^"\']+)["\']')
ATL_TOKEN_RE2 = re.compile(r'name=["\']atl_token["\'][^>]*value=["\']([^"\']+)["\']')


def extract_atl_token(text: str) -> str | None:
    for r in (ATL_TOKEN_RE, ATL_TOKEN_RE2):
        m = r.search(text)
        if m:
            return html.unescape(m.group(1))
    return None


# --- readiness probe --------------------------------------------------------

def wait_until_ready(base: str, timeout: int = 600) -> str:
    """Poll until the product responds with something we can act on.

    Returns one of: "wizard", "ready", or exits.
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = requests.get(base + "/", timeout=10, allow_redirects=False)
            last = f"{r.status_code} {r.headers.get('Location', '')}"
            loc = (r.headers.get("Location") or "").lower()
            if r.status_code in (301, 302, 303):
                if "setup" in loc or "bootstrap" in loc:
                    return "wizard"
                if "login" in loc or "dashboard" in loc or "stash" in loc:
                    return "ready"
            elif r.status_code == 200:
                body_lower = ""
                try:
                    body_lower = r.text[:4000].lower()
                except Exception:
                    pass
                if "setup" in body_lower and ("wizard" in body_lower or "license" in body_lower):
                    return "wizard"
                # If we get HTML at root, treat as ready (Jira does this once configured).
                return "ready"
        except requests.RequestException as e:
            last = f"err={e!s}"
        time.sleep(3)
    sys.exit(f"error: {base} not ready after {timeout}s (last: {last})")


# --- Confluence wizard ------------------------------------------------------

def conf_run_wizard(s: requests.Session, base: str, admin: dict) -> bool:
    """Returns True if the wizard was needed and completed; False if already set up."""
    # Step 0: hit root, follow redirects to find current wizard step.
    r = s.get(base + "/", allow_redirects=True, timeout=30)
    log(f"confluence root -> {r.status_code} {r.url}")
    if "/setup/" not in r.url and "bootstrap" not in r.url:
        return False  # already set up

    # The redirect from / lands us on selectsetupstep, which auto-redirects to the right page.
    # Make sure we are starting at the type-selection step. Submit "custom" if needed.
    if "selectsetupstep" in r.url or "dosetupstart" in r.url:
        # Hit selectsetuptype to make sure we pick custom (not "trial install").
        r = s.get(base + "/setup/selectsetuptype.action", allow_redirects=True, timeout=30)
        log(f"confluence selectsetuptype -> {r.status_code} {r.url}")

    # Step 1: license. URL is /setup/setuplicense.action; POST to dosetuplicense.action.
    r = s.get(base + "/setup/setuplicense.action", allow_redirects=True, timeout=30)
    log(f"confluence setuplicense GET -> {r.status_code} {r.url}")
    token = extract_atl_token(r.text) or ""
    license_key = fetch_license("confluence")
    data = {
        "atl_token": token,
        "confLicenseString": license_key,
        "setupTypeCustom": "Next",
    }
    r = s.post(base + "/setup/dosetuplicense.action", data=data,
               allow_redirects=True, timeout=120)
    log(f"confluence dosetuplicense -> {r.status_code} {r.url}")
    if "setuplicense" in r.url and "do" not in r.url:
        snippet = re.findall(r'class="error[^"]*"[^>]*>([^<]+)', r.text)
        sys.exit(f"error: confluence license rejected. errors: {snippet[:3]}")

    # After license we land somewhere in the bundle/db/install pipeline.
    # Walk through whatever comes next; submit form on each page until we hit admin.
    return conf_walk_until_done(s, base, admin)


def conf_walk_until_done(s: requests.Session, base: str, admin: dict) -> bool:
    """After license is accepted, keep submitting the visible form on each
    setup page until the wizard is complete (URL leaves /setup/...)."""
    seen = set()
    for step in range(20):
        url = s.get(base + "/", allow_redirects=True, timeout=120).url
        log(f"confluence walk {step}: at {url}")
        if "/setup/" not in url:
            log("confluence wizard appears complete")
            return True
        if url in seen:
            time.sleep(5)
        seen.add(url)

        # Re-fetch the current page directly (we have its URL).
        r = s.get(url, timeout=120)
        token = extract_atl_token(r.text) or ""
        action_match = re.search(r'<form[^>]*action="([^"]+)"', r.text)
        if not action_match:
            log(f"  no form on {url}, body 200 chars: {r.text[:200]!r}")
            time.sleep(5)
            continue
        action = html.unescape(action_match.group(1))
        if not action.startswith("http"):
            action = base + "/setup/" + action.lstrip("/")
        log(f"  action -> {action}")

        # Build the right body per known step.
        body = conf_form_body(url, r.text, admin, token)
        log(f"  posting {len(body)} fields: {sorted(body.keys())}")
        r2 = s.post(action, data=body, allow_redirects=True, timeout=300)
        log(f"  -> {r2.status_code} {r2.url}")
        if "/setup/" not in r2.url:
            return True
        if r2.url == url:
            # Did not advance; print error hints.
            errs = re.findall(r'class="error[^"]*"[^>]*>([^<]+)', r2.text)
            log(f"  did not advance; errors: {errs[:5]}")
            time.sleep(5)
    sys.exit("error: confluence wizard did not complete after 20 iterations")


def conf_form_body(url: str, body_html: str, admin: dict, token: str) -> dict:
    u = url.lower()
    base = {"atl_token": token}
    if "setupcluster" in u or "setupchoosecluster" in u:
        # Standalone, not cluster.
        return {**base, "clusterSetup": "false", "submit": "Next"}
    if "setupdb" in u or "selectdatabase" in u or "setupdbtype" in u:
        # DB pre-configured by container env; just continue.
        # Try common field names.
        body = {**base}
        # Find the embedded button
        m = re.search(r'<input[^>]*type="submit"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', body_html)
        if m:
            body[m.group(1)] = m.group(2) or "Next"
        return body
    if "setupload" in u or "loaddata" in u or "setupstart" in u or "selectsetupstep" in u:
        # "Empty install" page — pick "install" / "Empty Site".
        body = {**base}
        # Look for radio with name="setupOption" and click the "blank" one.
        body["setupOption"] = "INSTALL"
        body["submit"] = "Next"
        return body
    if "setupadminuser" in u or "setupusermanagement" in u:
        # "Manage users and groups within Confluence" path is default.
        # If this page just asks Confluence-internal vs JIRA, click "Confluence".
        body = {**base}
        body["userManagementChoice"] = "Confluence"
        body["submit"] = "Next"
        # Admin form fields:
        body["fullName"]      = admin["fullname"]
        body["email"]         = admin["email"]
        body["username"]      = admin["user"]
        body["password"]      = admin["pass"]
        body["confirm"]       = admin["pass"]
        return body
    if "setupfinish" in u or "default.action" in u:
        return {**base, "submit": "Finish"}
    # Default: try to submit whatever submit button is present.
    body = {**base}
    for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', body_html):
        n, v = m.group(1), m.group(2)
        if n in ("atl_token", "submit") or "Setup" in v or "setup" in n.lower():
            body[n] = v
    body.setdefault("submit", "Next")
    return body


# --- Bitbucket wizard -------------------------------------------------------

def bb_run_wizard(s: requests.Session, base: str, admin: dict) -> bool:
    r = s.get(base + "/", allow_redirects=True, timeout=30)
    log(f"bitbucket root -> {r.status_code} {r.url}")
    if "/setup" not in r.url:
        return False  # already set up

    # Page 1: settings step (license + base URL + title).
    r = s.get(base + "/setup", allow_redirects=True, timeout=60)
    token = extract_atl_token(r.text) or ""
    license_key = fetch_license("bitbucket")
    data = {
        "step":              "settings",
        "applicationTitle":  "Bitbucket",
        "baseUrl":           base,
        "license-type":      "true",  # "I have a license key"
        "licenseDisplay":    license_key,
        "license":           license_key,
        "atl_token":         token,
        "submit":            "Next",
    }
    r = s.post(base + "/setup", data=data, allow_redirects=True, timeout=180)
    log(f"bitbucket POST settings -> {r.status_code} {r.url}")
    if "step=settings" in r.text and "error" in r.text.lower():
        errs = re.findall(r'class="error[^"]*"[^>]*>([^<]+)', r.text)
        log(f"  bitbucket settings errors: {errs[:3]}")

    # Page 2: usually account-creation (internal user directory) on same /setup URL.
    # But first there's a "user-directory" choice page in some versions; submit it.
    for step_idx in range(8):
        r = s.get(base + "/setup", allow_redirects=True, timeout=60)
        body = r.text
        # Detect what step we are on.
        step_match = re.search(r'<input[^>]*name=["\']step["\'][^>]*value=["\']([^"\']+)["\']', body)
        step = step_match.group(1) if step_match else ""
        token = extract_atl_token(body) or ""
        log(f"bitbucket step={step!r} url={r.url}")

        if "/setup" not in r.url and "setup" not in r.url:
            return True

        if step == "user-directory" or "userDirectory" in body or "Internal" in body and step != "settings":
            data = {"step": "user-directory", "userDirectory": "internal",
                    "atl_token": token, "submit": "Next"}
        elif step == "account":
            data = {
                "step":         "account",
                "username":     admin["user"],
                "fullname":     admin["fullname"],
                "displayName":  admin["fullname"],
                "emailAddress": admin["email"],
                "email":        admin["email"],
                "password":     admin["pass"],
                "confirmPassword": admin["pass"],
                "atl_token":    token,
                "submit":       "Submit",
            }
        else:
            # Try a generic submit.
            data = {"step": step or "settings", "atl_token": token, "submit": "Next"}

        r = s.post(base + "/setup", data=data, allow_redirects=True, timeout=180)
        log(f"  POST step={data.get('step')} -> {r.status_code} {r.url}")
        if "/setup" not in r.url:
            return True
        if "Setup is complete" in r.text or "successfully" in r.text.lower():
            return True
    return False


# --- Jira wizard ------------------------------------------------------------

def jira_run_wizard(s: requests.Session, base: str, admin: dict) -> bool:
    r = s.get(base + "/", allow_redirects=True, timeout=30)
    log(f"jira root -> {r.status_code} {r.url}")
    if "/secure/Setup" not in r.url and "secure/SetupMode" not in r.url:
        return False  # already set up

    # Step 1: SetupMode -> we want classic local install.
    s.get(base + "/secure/SetupMode!default.jspa", timeout=30)
    r = s.get(base + "/secure/SetupApplicationProperties!default.jspa", timeout=30)
    token = extract_atl_token(r.text) or ""
    data = {
        "title":     "Jira",
        "mode":      "private",
        "baseURL":   base,
        "atl_token": token,
        "next":      "Next",
    }
    r = s.post(base + "/secure/SetupApplicationProperties.jspa", data=data,
               allow_redirects=True, timeout=120)
    log(f"jira app-properties -> {r.status_code} {r.url}")

    # Step 2: License — POST directly with just the key.
    r = s.get(base + "/secure/SetupLicense!default.jspa", timeout=30)
    token = extract_atl_token(r.text) or ""
    license_key = fetch_license("jira")
    data = {
        "setupLicenseKey": license_key,
        "licenseKey":      license_key,
        "atl_token":       token,
        "next":            "Next",
    }
    r = s.post(base + "/secure/SetupLicense.jspa", data=data,
               allow_redirects=True, timeout=180)
    log(f"jira license -> {r.status_code} {r.url}")

    # Step 3: Admin account.
    r = s.get(base + "/secure/SetupAdminAccount!default.jspa", timeout=30)
    token = extract_atl_token(r.text) or ""
    data = {
        "fullname":  admin["fullname"],
        "email":     admin["email"],
        "username":  admin["user"],
        "password":  admin["pass"],
        "confirm":   admin["pass"],
        "atl_token": token,
        "next":      "Next",
    }
    r = s.post(base + "/secure/SetupAdminAccount.jspa", data=data,
               allow_redirects=True, timeout=300)
    log(f"jira admin-account -> {r.status_code} {r.url}")

    # Step 4: Mail (skip).
    r = s.get(base + "/secure/SetupMailNotifications!default.jspa", timeout=30)
    token = extract_atl_token(r.text) or ""
    data = {
        "noemail":   "true",
        "atl_token": token,
        "finish":    "Finish",
    }
    r = s.post(base + "/secure/SetupMailNotifications.jspa", data=data,
               allow_redirects=True, timeout=180)
    log(f"jira mail -> {r.status_code} {r.url}")
    return True


# --- login + PAT (re-implementation, also imports from get_pat work fine) ---

def login_for_pat(s: requests.Session, product: str, base: str, admin: dict) -> None:
    user, pw = admin["user"], admin["pass"]
    if product == "bitbucket":
        s.post(base + "/j_atl_security_check",
               data={"j_username": user, "j_password": pw,
                     "_atl_remember_me": "on", "submit": "Log in"},
               allow_redirects=True, timeout=60)
    elif product == "confluence":
        s.post(base + "/dologin.action",
               data={"os_username": user, "os_password": pw,
                     "login": "Log in", "os_destination": "/index.action"},
               allow_redirects=True, timeout=60)
    else:  # jira
        s.post(base + "/login.jsp",
               data={"os_username": user, "os_password": pw,
                     "os_destination": "", "user_role": "",
                     "atl_token": "", "login": "Log In"},
               allow_redirects=True, timeout=60)


def create_pat(s: requests.Session, product: str, base: str, user: str,
               name: str = "skill-test", days: int = 90) -> str:
    headers = {"Content-Type": "application/json", "X-Atlassian-Token": "no-check"}
    if product == "bitbucket":
        url = f"{base}/rest/access-tokens/latest/users/{user}"
        body = {"name": name, "permissions": ["PROJECT_ADMIN", "REPO_ADMIN"], "expiryDays": days}
    else:
        url = f"{base}/rest/pat/latest/tokens"
        body = {"name": name, "expirationDuration": days}
    r = s.post(url, json=body, headers=headers, timeout=60)
    log(f"create-pat {product} -> {r.status_code}")
    if r.status_code not in (200, 201):
        sys.exit(f"error: PAT creation failed: {r.status_code} {r.text[:300]!r}")
    j = r.json()
    return (j.get("rawToken") or j.get("token")
            or j.get("value") or j.get("secret") or "")


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


def verify_pat(product: str, base: str, user: str, token: str) -> int:
    if product == "bitbucket":
        url = f"{base}/rest/api/1.0/users/{user}"
    elif product == "confluence":
        url = f"{base}/rest/api/user/current"
    else:
        url = f"{base}/rest/api/2/myself"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    log(f"verify {product} {url} -> {r.status_code}")
    return r.status_code


# --- main -------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("product", choices=["jira", "confluence", "bitbucket"])
    p.add_argument("--base-url", required=True)
    p.add_argument("--alias", default=os.environ.get("ATLASSIAN_ALIAS", "local"))
    p.add_argument("--name", default="skill-test", help="PAT name")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--ready-timeout", type=int, default=600)
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    admin = read_admin(args.product)
    log(f"product={args.product} base={base} admin-user={admin['user']}")

    state = wait_until_ready(base, args.ready_timeout)
    log(f"ready state: {state}")

    s = requests.Session()
    s.headers.update({"User-Agent": "atlassian-dc-auto-setup/1.0"})

    if state == "wizard":
        if args.product == "confluence":
            conf_run_wizard(s, base, admin)
        elif args.product == "bitbucket":
            bb_run_wizard(s, base, admin)
        else:
            jira_run_wizard(s, base, admin)
        # After the wizard, give the app a moment to settle.
        time.sleep(2)
    else:
        log("skipping wizard (instance already configured)")

    # Fresh session for PAT login.
    s = requests.Session()
    s.headers.update({"User-Agent": "atlassian-dc-auto-setup/1.0"})
    login_for_pat(s, args.product, base, admin)
    token = create_pat(s, args.product, base, admin["user"], args.name, args.days)
    if not token:
        sys.exit("error: empty token returned")
    path = write_instances(args.product, base, args.alias, token)
    code = verify_pat(args.product, base, admin["user"], token)
    if code != 200:
        log(f"warning: PAT verify returned {code}")

    print(json.dumps({
        "instances_file": str(path),
        "alias":          args.alias,
        "product":        args.product,
        "base_url":       base,
        "user":           admin["user"],
        "token_length":   len(token),
        "token_preview":  token[:4] + "..." + token[-4:],
        "verify_status":  code,
    }, indent=2))


if __name__ == "__main__":
    main()
