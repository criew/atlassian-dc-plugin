#!/usr/bin/env python3
"""Automate Jira DC first-run setup + PAT creation.

Reads the license key from $JIRA_LICENSE (so it does not appear in logs/argv).
Takes screenshots into ./setup-screenshots/ for debugging.

Output: writes instances.json into one of the standard locations and prints
the resolved path. The PAT itself is masked in stdout.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

JIRA_URL = os.environ.get("JIRA_URL", "http://localhost:8080")
LICENSE = os.environ.get("JIRA_LICENSE")
ADMIN_USER = os.environ.get("JIRA_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("JIRA_ADMIN_PASS", "admin123")
ADMIN_EMAIL = os.environ.get("JIRA_ADMIN_EMAIL", "admin@example.com")
ADMIN_FULL = os.environ.get("JIRA_ADMIN_FULL", "Local Admin")
INSTANCE_ALIAS = os.environ.get("JIRA_ALIAS", "local")

SCREENSHOTS = Path("setup-screenshots")
SCREENSHOTS.mkdir(exist_ok=True)


def shot(page, name: str):
    path = SCREENSHOTS / f"{int(time.time())}-{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        sys.stderr.write(f"[shot] {path}\n")
    except Exception as e:
        sys.stderr.write(f"[shot] failed: {e}\n")


def wait_any(page, selectors: list[str], timeout: int = 60000) -> str:
    """Wait for any of the given selectors to appear, return the first that matches."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                    return sel
            except Exception:
                pass
        page.wait_for_timeout(500)
    raise PWTimeout(f"none of {selectors} appeared within {timeout}ms")


def run_wizard(page):
    sys.stderr.write(f"[wizard] navigating to {JIRA_URL}\n")
    page.goto(JIRA_URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_load_state("networkidle", timeout=120000)
    shot(page, "01-landed")

    # Step 1: Setup mode (choose "I'll set it up myself")
    # Newer Jira: a card-style picker; older: radio + Next button.
    try:
        page.wait_for_selector("text=I'll set it up myself", timeout=30000)
        page.click("text=I'll set it up myself")
        sys.stderr.write("[wizard] selected 'I'll set it up myself'\n")
    except PWTimeout:
        sys.stderr.write("[wizard] no setup-mode picker, continuing\n")
    shot(page, "02-mode-selected")
    try:
        page.click("button:has-text('Next')", timeout=10000)
    except PWTimeout:
        pass
    page.wait_for_load_state("networkidle", timeout=120000)
    shot(page, "03-after-mode-next")

    # Step 2: Application properties (title, mode, base URL).
    # Detect by the presence of a 'Title' input.
    try:
        title_input = page.locator("input[name='title']")
        if title_input.count() > 0:
            sys.stderr.write("[wizard] filling application properties\n")
            title_input.fill("Local Jira DC")
            shot(page, "04-properties")
            page.click("input[type='submit'], button:has-text('Next')")
            page.wait_for_load_state("networkidle", timeout=120000)
    except PWTimeout:
        pass

    # Step 3: License — #setupLicenseKey is a hidden input synced by JS from a
    # visible textarea. Fill the hidden field directly via JS and submit the form.
    sys.stderr.write("[wizard] waiting for license form to exist in DOM\n")
    page.wait_for_selector("#setupLicenseKey", state="attached", timeout=120000)
    sys.stderr.write("[wizard] setting license value via JS and submitting form\n")
    page.evaluate(
        """(license) => {
            const inp = document.getElementById('setupLicenseKey');
            inp.value = license;
            // Try the visible textarea inside #license-input-container too,
            // in case Jira's submit handler reads from there.
            const container = document.getElementById('license-input-container');
            if (container) {
                const t = container.querySelector('textarea, input');
                if (t) t.value = license;
            }
            document.getElementById('setupLicenseForm').submit();
        }""",
        LICENSE,
    )
    shot(page, "05-license-submitted")
    sys.stderr.write("[wizard] submitted license, waiting for next step (can take 30-60s)\n")
    page.wait_for_load_state("networkidle", timeout=180000)
    shot(page, "06-after-license")

    # Step 4: Admin account creation.
    page.wait_for_selector("input[name='fullname'], input[name='username']", timeout=120000)
    sys.stderr.write("[wizard] filling admin account\n")
    if page.locator("input[name='fullname']").count() > 0:
        page.fill("input[name='fullname']", ADMIN_FULL)
    if page.locator("input[name='email']").count() > 0:
        page.fill("input[name='email']", ADMIN_EMAIL)
    if page.locator("input[name='username']").count() > 0:
        page.fill("input[name='username']", ADMIN_USER)
    if page.locator("input[name='password']").count() > 0:
        page.fill("input[name='password']", ADMIN_PASS)
    if page.locator("input[name='confirm']").count() > 0:
        page.fill("input[name='confirm']", ADMIN_PASS)
    shot(page, "07-admin-filled")
    page.click("input[type='submit'], button:has-text('Next')")
    page.wait_for_load_state("networkidle", timeout=180000)
    shot(page, "08-after-admin")

    # Step 5: Email config — skip if it appears.
    try:
        page.wait_for_selector("text=Email Notifications", timeout=10000)
        sys.stderr.write("[wizard] skipping email config\n")
        # Try "Later" or "Finish" link/button.
        for sel in ["a:has-text('Later')", "button:has-text('Later')",
                    "button:has-text('Finish')", "input[type='submit']"]:
            try:
                page.click(sel, timeout=2000)
                break
            except PWTimeout:
                pass
        page.wait_for_load_state("networkidle", timeout=120000)
    except PWTimeout:
        pass
    shot(page, "09-after-email")

    # Step 6: Welcome / Pick language etc. Try to skip everything to dashboard.
    for sel in ["button:has-text('Continue')",
                "a:has-text('Continue')",
                "button:has-text('Next')",
                "a:has-text('Next')"]:
        for _ in range(5):
            try:
                if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                    page.locator(sel).first.click()
                    page.wait_for_load_state("networkidle", timeout=60000)
                else:
                    break
            except Exception:
                break
    shot(page, "10-welcome-handled")

    # Try to dismiss any avatar/onboarding modal by going straight to dashboard.
    page.goto(f"{JIRA_URL}/secure/Dashboard.jspa", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_load_state("networkidle", timeout=60000)
    shot(page, "11-dashboard")
    sys.stderr.write("[wizard] reached dashboard\n")


def login_if_needed(page):
    if "/login" in page.url or page.locator("input[name='os_username']").count() > 0:
        sys.stderr.write("[login] login form present, signing in\n")
        page.fill("input[name='os_username']", ADMIN_USER)
        page.fill("input[name='os_password']", ADMIN_PASS)
        page.click("input[id='login-form-submit'], button:has-text('Log In'), button:has-text('Anmelden')")
        page.wait_for_load_state("networkidle", timeout=60000)
        shot(page, "12-after-login")


def create_pat(page) -> str:
    pat_url = f"{JIRA_URL}/plugins/servlet/access-tokens/manage/usertokens"
    sys.stderr.write(f"[pat] navigating to {pat_url}\n")
    page.goto(pat_url, wait_until="domcontentloaded", timeout=60000)
    login_if_needed(page)
    page.wait_for_load_state("networkidle", timeout=60000)
    shot(page, "20-pat-page")

    # Look for create button (varies)
    for sel in [
        "button:has-text('Create token')",
        "a:has-text('Create token')",
        "button:has-text('Create access token')",
        "button:has-text('Create a token')",
        "button:has-text('Create')",
    ]:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                break
        except Exception:
            pass
    page.wait_for_load_state("networkidle", timeout=10000)
    shot(page, "21-create-form")

    # Fill name field
    name_field = page.locator("input[name='name'], input#tokenName, input[placeholder*='Token name' i], input[placeholder*='name' i]")
    name_field.first.fill("skill-test")
    # Submit
    for sel in ["button:has-text('Create')",
                "button:has-text('Save')",
                "input[type='submit']"]:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                break
        except Exception:
            pass
    page.wait_for_load_state("networkidle", timeout=30000)
    shot(page, "22-pat-created")

    # The token is shown once. Find it: usually in a code/input element near 'Copy'.
    # Try multiple strategies.
    candidates = []
    for sel in ["input[readonly]", "code", "pre", "textarea[readonly]"]:
        for el in page.locator(sel).all():
            try:
                v = el.input_value() if "input" in sel or "textarea" in sel else el.text_content()
                if v and len(v) >= 24 and " " not in v.strip():
                    candidates.append(v.strip())
            except Exception:
                pass
    if not candidates:
        raise RuntimeError("could not find PAT value on the page; see screenshots")
    # Heuristic: longest candidate is the token
    token = max(candidates, key=len)
    sys.stderr.write(f"[pat] captured token of length {len(token)}\n")
    return token


def write_instances_file(token: str) -> Path:
    """Write instances.json into AppData (Windows) or ~/.config/atlassian/ (Linux)."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / "atlassian" / "instances.json"
    else:
        path = Path.home() / ".config" / "atlassian" / "instances.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8"))
    else:
        cfg = {"default": INSTANCE_ALIAS, "instances": {}}

    cfg.setdefault("instances", {})
    cfg["instances"].setdefault(INSTANCE_ALIAS, {})
    cfg["instances"][INSTANCE_ALIAS]["jira"] = {
        "url": JIRA_URL,
        "token": token,
        "ssl_verify": False,
    }
    if "default" not in cfg:
        cfg["default"] = INSTANCE_ALIAS

    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def main():
    if not LICENSE:
        sys.exit("error: set $JIRA_LICENSE environment variable to the trial license key")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()
        page.set_default_timeout(60000)
        try:
            run_wizard(page)
            login_if_needed(page)
            token = create_pat(page)
        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass

    path = write_instances_file(token)
    print(json.dumps({
        "instances_file": str(path),
        "alias": INSTANCE_ALIAS,
        "jira_url": JIRA_URL,
        "admin_user": ADMIN_USER,
        "admin_pass_hint": "see $JIRA_ADMIN_PASS or default",
        "token_length": len(token),
        "token_preview": token[:4] + "..." + token[-4:],
    }, indent=2))


if __name__ == "__main__":
    main()
