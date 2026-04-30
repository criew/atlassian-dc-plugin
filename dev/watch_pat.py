#!/usr/bin/env python3
"""Open the PAT-creation UI in a real browser, you click, I record.

Logs every navigation, every POST/PUT body, and a HTML snapshot of each
visible form before and after submission. The captured selectors + payloads
become the recipe for fully-unattended PAT creation in get_pat_browser.py.

When you successfully create a token (a value of length >= 24 appears in a
readable input/code element), the script extracts it, writes instances.json,
and prints a summary.

Usage:
    JIRA_PASS=admin123 python dev/watch_pat.py jira       --user admin --base-url http://localhost:8080
    CONF_PASS=admin123 python dev/watch_pat.py confluence --user admin --base-url http://localhost:8090
    BB_PASS=admin123   python dev/watch_pat.py bitbucket  --user admin --base-url http://localhost:7990
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / "dev" / "watch-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

PAT_URLS = {
    "jira":       "/plugins/servlet/access-tokens/manage/usertokens",
    "confluence": "/plugins/servlet/access-tokens/manage/usertokens",
    "bitbucket":  "/plugins/servlet/access-tokens/users/manage",
}


def log(msg: str, fh) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
    fh.write(line + "\n")
    fh.flush()


def snapshot_forms(page, label: str, fh):
    """Dump every visible <form>, <input>, <button> on the current page."""
    js = """
        () => {
          const out = [];
          for (const f of document.querySelectorAll('form')) {
            const fields = [];
            for (const el of f.querySelectorAll('input, textarea, select, button')) {
              fields.push({
                tag: el.tagName.toLowerCase(),
                type: el.type || null,
                name: el.name || null,
                id: el.id || null,
                placeholder: el.placeholder || null,
                'aria-label': el.getAttribute('aria-label') || null,
                value: (el.tagName === 'BUTTON' || el.type === 'submit') ?
                       (el.textContent || el.value || '').trim().slice(0, 80) :
                       null,
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
              });
            }
            out.push({
              action: f.action || null, method: f.method || null,
              id: f.id || null, name: f.getAttribute('name') || null,
              fields,
            });
          }
          // Also describe top-level buttons / links not inside a form.
          const bare = [];
          for (const el of document.querySelectorAll('body > * button, body > * a.aui-button')) {
            const text = (el.textContent || '').trim().slice(0, 80);
            if (text) bare.push({tag: el.tagName.toLowerCase(), text,
                                  id: el.id || null,
                                  classes: el.className || null});
          }
          return {forms: out, top_buttons: bare.slice(0, 20)};
        }
    """
    try:
        snap = page.evaluate(js)
    except Exception as e:
        snap = {"error": str(e)}
    log(f"--- DOM SNAPSHOT [{label}] @ {page.url} ---", fh)
    fh.write(json.dumps(snap, indent=2, ensure_ascii=False) + "\n")
    fh.flush()


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


def find_token_in_dom(page) -> Optional[str]:
    """Return the longest plausible PAT-shaped string visible on the page."""
    try:
        candidates = page.evaluate(
            """() => {
              const out = [];
              for (const sel of ['input[readonly]', 'textarea[readonly]', 'code', 'pre']) {
                for (const el of document.querySelectorAll(sel)) {
                  const v = (el.value !== undefined ? el.value : el.textContent) || '';
                  const t = v.trim();
                  if (t.length >= 24 && !/\\s/.test(t)) out.push(t);
                }
              }
              return out;
            }"""
        )
    except Exception:
        return None
    return max(candidates, key=len) if candidates else None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("product", choices=["jira", "confluence", "bitbucket"])
    p.add_argument("--base-url", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--alias", default="local")
    args = p.parse_args()

    pass_env = {"jira": "JIRA_PASS", "confluence": "CONF_PASS", "bitbucket": "BB_PASS"}[args.product]
    pw = os.environ.get(pass_env)
    if not pw:
        sys.exit(f"error: set ${pass_env} env var")

    base = args.base_url.rstrip("/")
    log_path = LOG_DIR / f"{args.product}-pat-{int(time.time())}.log"
    fh = open(log_path, "w", encoding="utf-8")

    print()
    print("=" * 72)
    print(f"  Browser opens at the {args.product.upper()} login + PAT-create page.")
    print(f"  I will log in as {args.user} automatically. Then YOU click")
    print(f"  'Create token', enter a name (e.g. 'skill-test'), and submit.")
    print(f"  When the token is shown, I capture it and write instances.json.")
    print(f"  Recording: {log_path}")
    print("=" * 72)
    print()

    with sync_playwright() as pp:
        browser = pp.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        page = ctx.new_page()

        page.on("framenavigated",
                lambda f: log(f"NAV {f.url}", fh) if f == page.main_frame else None)

        def on_request(req):
            if req.method in ("POST", "PUT", "DELETE", "PATCH"):
                pdata = req.post_data
                if pdata and len(pdata) > 1500:
                    pdata = pdata[:1500] + "...(truncated)"
                log(f"{req.method} {req.url}\n   body: {pdata!r}", fh)
        page.on("request", on_request)

        # Step 1: login.
        if args.product == "jira":
            page.goto(f"{base}/login.jsp", wait_until="domcontentloaded", timeout=60000)
            snapshot_forms(page, "jira-login", fh)
            page.fill("input[name='os_username']", args.user)
            page.fill("input[name='os_password']", pw)
            page.click("input#login-form-submit, input[name='login'], button:has-text('Log In')")
        elif args.product == "confluence":
            page.goto(f"{base}/login.action", wait_until="domcontentloaded", timeout=60000)
            snapshot_forms(page, "confluence-login", fh)
            page.fill("input[name='os_username']", args.user)
            page.fill("input[name='os_password']", pw)
            page.click("input[name='login'], button:has-text('Log in')")
        else:  # bitbucket
            page.goto(f"{base}/login", wait_until="domcontentloaded", timeout=60000)
            snapshot_forms(page, "bitbucket-login", fh)
            page.fill("input[name='j_username']", args.user)
            page.fill("input[name='j_password']", pw)
            page.click("button[type='submit']")
        page.wait_for_load_state("networkidle", timeout=60000)
        log("login posted; waiting for redirect", fh)

        # Step 2: navigate to PAT page.
        pat_url = base + PAT_URLS[args.product]
        log(f"navigating to PAT page: {pat_url}", fh)
        page.goto(pat_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
        snapshot_forms(page, "pat-landing", fh)

        # Now hand over to user. Poll DOM for token; also re-snapshot when URL changes.
        last_url = page.url
        last_snap_at = 0
        deadline = time.time() + 30 * 60
        token = None
        while time.time() < deadline:
            try:
                if page.url != last_url:
                    log(f"url changed -> {page.url}", fh)
                    last_url = page.url
                    page.wait_for_load_state("networkidle", timeout=10000)
                    snapshot_forms(page, f"on-{int(time.time())}", fh)
                    last_snap_at = time.time()
                elif time.time() - last_snap_at > 8:
                    snapshot_forms(page, f"poll-{int(time.time())}", fh)
                    last_snap_at = time.time()
                tok = find_token_in_dom(page)
                if tok:
                    token = tok
                    log(f"token detected in DOM: {len(tok)} chars, "
                        f"preview {tok[:4]}...{tok[-4:]}", fh)
                    snapshot_forms(page, "token-visible", fh)
                    break
                page.wait_for_timeout(1500)
            except Exception as e:
                log(f"poll error: {e}", fh)
                break

        try:
            ctx.close(); browser.close()
        except Exception:
            pass

    if not token:
        sys.exit("error: no token detected before timeout")
    out = write_instances(args.product, base, args.alias, token)
    print(json.dumps({
        "instances_file": str(out),
        "alias": args.alias,
        "product": args.product,
        "user": args.user,
        "token_length": len(token),
        "token_preview": token[:4] + "..." + token[-4:],
        "log_file": str(log_path),
    }, indent=2))


if __name__ == "__main__":
    main()
