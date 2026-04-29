#!/usr/bin/env python3
"""Open the wizard in a real browser, you click, I record.

Spawns a visible Chromium window pointed at the chosen product's wizard.
Logs every navigation and form POST to a file (and stderr) so we can build
a working unattended auto-setup later. When the wizard is done (URL leaves
/setup/), uses the now-authenticated session cookies to create a PAT and
writes ~/.config/atlassian/instances.json (or %APPDATA%\\...).

The license for the chosen product is fetched ahead of time via
dev/fetch_license.py and copied to the system clipboard so you can paste it
into the license field with Ctrl+V.

Usage:
    python dev/watch_setup.py confluence --base-url http://localhost:8090
    python dev/watch_setup.py jira       --base-url http://localhost:8080
    python dev/watch_setup.py bitbucket  --base-url http://localhost:7990
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / "dev" / "watch-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str, fh=None) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
    if fh:
        fh.write(line + "\n")
        fh.flush()


def fetch_license_to_clipboard(product: str) -> str:
    """Run dev/fetch_license.py <product> --copy and return the key."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "dev" / "fetch_license.py"), product, "--copy"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        sys.exit(f"error: fetch_license failed: {proc.stderr}")
    return proc.stdout.strip()


def is_wizard_url(product: str, url: str) -> bool:
    p = urlparse(url).path.lower()
    if product == "jira":
        return "/secure/setup" in p or p.endswith("/setup") or p == "/"
    if product == "confluence":
        return "/setup/" in p or p == "/"
    if product == "bitbucket":
        return p.startswith("/setup") or p == "/"
    return False


def is_authenticated_url(product: str, url: str) -> bool:
    """The wizard finished when the URL points at a normal post-setup page.

    Strategy: any URL that is NOT in the wizard path and NOT a login screen
    counts as "logged in" — this covers dashboards, editor pages,
    onboarding-tour pages, individual spaces/projects, etc.
    """
    p = urlparse(url).path.lower()
    if "/login" in p:
        return False
    if product == "jira":
        return ("/secure/setup" not in p
                and not p.startswith("/setup")
                and (p.startswith("/secure/") or p == "/" or "welcome" in p
                     or p.startswith("/projects") or p.startswith("/issues")
                     or p.startswith("/jira/") or p.startswith("/browse/")))
    if product == "confluence":
        return "/setup/" not in p and (
            p.startswith("/index.action") or p.startswith("/dashboard")
            or p.startswith("/spaces") or p.startswith("/pages")
            or p.startswith("/welcome") or p.startswith("/admin"))
    if product == "bitbucket":
        return not p.startswith("/setup") and (
            p.startswith("/dashboard") or p.startswith("/projects")
            or p.startswith("/repos") or p.startswith("/users")
            or p.startswith("/admin") or p == "/")
    return False


def create_pat_from_cookies(product: str, base: str, user: str, cookies: list) -> tuple[str, int]:
    s = requests.Session()
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
    headers = {"Content-Type": "application/json", "X-Atlassian-Token": "no-check"}
    if product == "bitbucket":
        url = f"{base}/rest/access-tokens/latest/users/{user}"
        body = {"name": "skill-test", "permissions": ["PROJECT_ADMIN", "REPO_ADMIN"], "expiryDays": 90}
        r = s.put(url, json=body, headers=headers, timeout=60)
    else:
        url = f"{base}/rest/pat/latest/tokens"
        body = {"name": "skill-test", "expirationDuration": 90}
        r = s.post(url, json=body, headers=headers, timeout=60)
    if r.status_code not in (200, 201):
        sys.exit(f"error: PAT creation via session cookies failed: {r.status_code} {r.text[:300]!r}")
    j = r.json()
    return (j.get("rawToken") or j.get("token") or j.get("value") or j.get("secret") or ""), r.status_code


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
    p.add_argument("product", choices=["jira", "confluence", "bitbucket"])
    p.add_argument("--base-url", required=True)
    p.add_argument("--user", default=os.environ.get("ADMIN_USER", "admin"),
                   help="admin username you create in the wizard (for PAT scope)")
    p.add_argument("--alias", default="local")
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    log_path = LOG_DIR / f"{args.product}-{int(time.time())}.log"
    log_fh = open(log_path, "w", encoding="utf-8")

    # 1. Stage the license in the clipboard so the user can paste it.
    license_key = fetch_license_to_clipboard(args.product)
    log(f"license fetched: {len(license_key)} chars; first 8: {license_key[:8]} — copied to clipboard", log_fh)

    print()
    print("=" * 72)
    print(f"  Browser opens — click through the {args.product.upper()} wizard.")
    print(f"  License key is on your clipboard (Ctrl+V into the license field).")
    print(f"  Use these admin credentials when the wizard asks:")
    print(f"     username: {args.user}")
    print(f"     password: admin123  (or set $ADMIN_PASS)")
    print(f"     email:    admin@example.com")
    print(f"  When you reach the dashboard, this script will auto-create a PAT.")
    print(f"  Recording POSTs to: {log_path}")
    print("=" * 72)
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        page = ctx.new_page()

        # Log every navigation
        def on_nav(frame):
            if frame == page.main_frame:
                log(f"NAV {frame.url}", log_fh)
        page.on("framenavigated", on_nav)

        # Log POST/PUT/DELETE bodies — the recipe for unattended setup.
        def on_request(req):
            if req.method in ("POST", "PUT", "DELETE"):
                pdata = req.post_data
                if pdata and len(pdata) > 1500:
                    pdata = pdata[:1500] + "...(truncated)"
                log(f"{req.method} {req.url}\n   body: {pdata!r}", log_fh)
        page.on("request", on_request)

        page.goto(base, wait_until="domcontentloaded", timeout=60000)
        log(f"opened {base}", log_fh)

        # Poll URL until authenticated.
        deadline = time.time() + 30 * 60  # 30 minutes max
        while time.time() < deadline:
            try:
                url = page.url
            except Exception:
                break
            if is_authenticated_url(args.product, url):
                log(f"detected authenticated URL: {url}", log_fh)
                break
            try:
                page.wait_for_timeout(1500)
            except Exception:
                break
        else:
            sys.exit("error: timed out waiting for wizard to complete")

        cookies = ctx.cookies()
        log(f"captured {len(cookies)} cookies for PAT creation", log_fh)

        token, status = create_pat_from_cookies(args.product, base, args.user, cookies)

        try:
            ctx.close()
            browser.close()
        except Exception:
            pass

    if not token:
        sys.exit("error: empty token returned")
    out_path = write_instances(args.product, base, args.alias, token)

    print(json.dumps({
        "instances_file": str(out_path),
        "alias": args.alias,
        "product": args.product,
        "base_url": base,
        "user": args.user,
        "token_length": len(token),
        "token_preview": token[:4] + "..." + token[-4:],
        "pat_status": status,
        "log_file": str(log_path),
    }, indent=2))


if __name__ == "__main__":
    main()
