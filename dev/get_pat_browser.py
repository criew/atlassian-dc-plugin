#!/usr/bin/env python3
"""Login + create PAT through the actual UI when REST refuses.

Used as a fallback for products whose PAT REST endpoint rejects basic auth
or session cookies set up via plain login.jsp POSTs (Jira does this when
captcha or XSRF cookies are not in the right combination).

The browser visit puts every required cookie in place, then we click the
"Create token" button and read the disclosed token straight from the DOM.

Usage:
    JIRA_PASS=admin123 python dev/get_pat_browser.py jira       --user admin --base-url http://localhost:8080
    CONF_PASS=admin123 python dev/get_pat_browser.py confluence --user admin --base-url http://localhost:8090
    BB_PASS=admin123   python dev/get_pat_browser.py bitbucket  --user admin --base-url http://localhost:7990
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PAT_PAGE = {
    "jira":       "/plugins/servlet/access-tokens/manage/usertokens",
    "confluence": "/plugins/servlet/access-tokens/manage/usertokens",
    "bitbucket":  "/account",  # bitbucket access tokens live under user account
}


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


def login_jira(page, base, user, pw):
    page.goto(f"{base}/login.jsp", wait_until="domcontentloaded", timeout=60000)
    page.fill("input[name='os_username']", user)
    page.fill("input[name='os_password']", pw)
    page.click("input#login-form-submit, button:has-text('Log In')")
    page.wait_for_load_state("networkidle", timeout=60000)


def login_confluence(page, base, user, pw):
    page.goto(f"{base}/login.action", wait_until="domcontentloaded", timeout=60000)
    page.fill("input[name='os_username']", user)
    page.fill("input[name='os_password']", pw)
    page.click("input[name='login'], button:has-text('Log in')")
    page.wait_for_load_state("networkidle", timeout=60000)


def login_bitbucket(page, base, user, pw):
    page.goto(f"{base}/login", wait_until="domcontentloaded", timeout=60000)
    page.fill("input[name='j_username']", user)
    page.fill("input[name='j_password']", pw)
    page.click("button[type='submit'], input[type='submit']")
    page.wait_for_load_state("networkidle", timeout=60000)


def create_pat_jira_confluence(page, base, name="skill-test"):
    page.goto(f"{base}/plugins/servlet/access-tokens/manage/usertokens",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)

    # Click "Create token" — multiple possible labels.
    for sel in ["button:has-text('Create token')",
                "a:has-text('Create token')",
                "button:has-text('Create access token')"]:
        if page.locator(sel).count():
            page.locator(sel).first.click()
            break

    page.wait_for_load_state("networkidle", timeout=10000)
    name_input = page.locator(
        "input[name='name'], input#tokenName, "
        "input[placeholder*='name' i], input[aria-label*='name' i]"
    )
    name_input.first.fill(name)

    for sel in ["button:has-text('Create')", "button:has-text('Save')",
                "input[type='submit'][value*='Create']"]:
        if page.locator(sel).count():
            page.locator(sel).first.click()
            break
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    # The token appears in a code/input element on the success view.
    candidates: list[str] = []
    for sel in ["input[readonly]", "code", "pre", "textarea[readonly]"]:
        for el in page.locator(sel).all():
            try:
                if "input" in sel or "textarea" in sel:
                    v = el.input_value()
                else:
                    v = el.text_content()
                if v and len(v.strip()) >= 24 and " " not in v.strip():
                    candidates.append(v.strip())
            except Exception:
                pass
    if not candidates:
        sys.exit("error: could not find generated token on the success page")
    return max(candidates, key=len)


def create_pat_bitbucket(page, base, name="skill-test"):
    # Bitbucket: account → personal access tokens → create
    page.goto(f"{base}/plugins/servlet/access-tokens/users/manage",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    for sel in ["button:has-text('Create a token')",
                "button:has-text('Create token')",
                "a:has-text('Create')"]:
        if page.locator(sel).count():
            page.locator(sel).first.click()
            break
    page.wait_for_load_state("networkidle", timeout=10000)

    page.locator("input[name='name'], input#tokenName").first.fill(name)
    # Pick all permissions checkboxes if any.
    for box in page.locator("input[type='checkbox']").all():
        try:
            if not box.is_checked():
                box.check()
        except Exception:
            pass
    for sel in ["button:has-text('Create')", "input[type='submit'][value*='Create']"]:
        if page.locator(sel).count():
            page.locator(sel).first.click()
            break
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    candidates: list[str] = []
    for sel in ["input[readonly]", "code", "pre"]:
        for el in page.locator(sel).all():
            try:
                v = el.input_value() if "input" in sel else el.text_content()
                if v and len(v.strip()) >= 24:
                    candidates.append(v.strip())
            except Exception:
                pass
    if not candidates:
        sys.exit("error: could not find token in Bitbucket UI")
    return max(candidates, key=len)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("product", choices=["jira", "confluence", "bitbucket"])
    p.add_argument("--base-url", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--alias", default="local")
    p.add_argument("--name", default="skill-test")
    p.add_argument("--headed", action="store_true",
                   help="show the browser (default headless)")
    args = p.parse_args()

    pass_env = {"jira": "JIRA_PASS", "confluence": "CONF_PASS", "bitbucket": "BB_PASS"}[args.product]
    pw = os.environ.get(pass_env)
    if not pw:
        sys.exit(f"error: set ${pass_env} env var")
    base = args.base_url.rstrip("/")

    with sync_playwright() as pp:
        browser = pp.chromium.launch(headless=not args.headed)
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            if args.product == "jira":
                login_jira(page, base, args.user, pw)
                token = create_pat_jira_confluence(page, base, args.name)
            elif args.product == "confluence":
                login_confluence(page, base, args.user, pw)
                token = create_pat_jira_confluence(page, base, args.name)
            else:
                login_bitbucket(page, base, args.user, pw)
                token = create_pat_bitbucket(page, base, args.name)
        finally:
            ctx.close()
            browser.close()

    out = write_instances(args.product, base, args.alias, token)
    print(json.dumps({
        "instances_file": str(out),
        "alias": args.alias,
        "product": args.product,
        "user": args.user,
        "token_length": len(token),
        "token_preview": token[:4] + "..." + token[-4:],
    }, indent=2))


if __name__ == "__main__":
    main()
