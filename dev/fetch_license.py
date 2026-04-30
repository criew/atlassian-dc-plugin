#!/usr/bin/env python3
"""Fetch a current Atlassian Time-Bomb license for a Data Center product.

Source page (publicly readable, no login):
  https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/

Each license is valid for 3 hours from when the page was last regenerated.
The licenses are baked into the rendered HTML; we extract them per product.

Usage:
    python dev/fetch_license.py jira
    python dev/fetch_license.py confluence
    python dev/fetch_license.py bitbucket
    python dev/fetch_license.py jira --copy           # also copy to clipboard
    python dev/fetch_license.py jira --json           # structured output

This script has no third-party deps beyond `requests`. Clipboard support uses
the OS-native tool when present (`clip` on Windows, `pbcopy` on macOS,
`xclip` or `xsel` on Linux). Without one available, --copy is a no-op warning.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

import requests

PAGE_URL = (
    "https://developer.atlassian.com/platform/marketplace/"
    "timebomb-licenses-for-testing-server-apps/"
)

# Map CLI product names to the heading text that anchors each license block.
# We accept several aliases; the matcher is case-insensitive substring.
PRODUCT_HEADINGS = {
    "jira":       ["jira software", "jira data center"],
    "confluence": ["confluence"],
    "bitbucket":  ["bitbucket"],
}

# Atlassian DC license keys begin with "AAAB" (base64 of a binary blob),
# contain only base64-safe chars, and run for hundreds of characters.
LICENSE_RE = re.compile(r"AAAB[A-Za-z0-9+/=\s]{200,}")


def fetch_html(url: str = PAGE_URL, timeout: int = 30) -> str:
    headers = {
        "User-Agent": "atlassian-dc-fetch-license/1.0",
        "Accept": "text/html",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    if r.status_code != 200:
        sys.exit(f"error: fetching {url} returned HTTP {r.status_code}")
    return r.text


def extract_licenses_by_section(html: str) -> List[Tuple[str, str]]:
    """For every license blob in the HTML, capture a generous preceding text
    window (cleaned of tags) so product matching can find names like
    'Jira Software', 'Confluence', 'Bitbucket' wherever they appear in
    headings, paragraphs, or list items.
    """
    cleaned = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html,
                     flags=re.IGNORECASE | re.DOTALL)
    out = []
    for m in LICENSE_RE.finditer(cleaned):
        blob = re.sub(r"\s+", "", m.group(0))
        # Collect the 800 chars before this license, strip tags, normalise space.
        window_html = cleaned[max(0, m.start() - 800):m.start()]
        window_text = re.sub(r"<[^>]+>", " ", window_html)
        window_text = re.sub(r"\s+", " ", window_text).strip()
        # Use the LAST 200 chars of the window as the immediate context label.
        out.append((window_text[-200:], blob))
    return out


def pick_license(pairs: List[Tuple[str, str]], product: str) -> Optional[str]:
    needles = [n.lower() for n in PRODUCT_HEADINGS[product]]
    for heading, blob in pairs:
        h = heading.lower()
        if any(n in h for n in needles):
            return blob
    return None


def to_clipboard(text: str) -> bool:
    """Best-effort copy. Returns True on success, False with a warning."""
    candidates = []
    if shutil.which("clip"):
        candidates.append(["clip"])
    if shutil.which("pbcopy"):
        candidates.append(["pbcopy"])
    if shutil.which("xclip"):
        candidates.append(["xclip", "-selection", "clipboard"])
    if shutil.which("xsel"):
        candidates.append(["xsel", "--clipboard", "--input"])
    for cmd in candidates:
        try:
            p = subprocess.run(cmd, input=text, universal_newlines=True, timeout=5,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode == 0:
                return True
        except Exception:
            continue
    sys.stderr.write("warning: no clipboard tool found (clip/pbcopy/xclip/xsel)\n")
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("product", choices=list(PRODUCT_HEADINGS.keys()))
    p.add_argument("--copy", action="store_true",
                   help="copy the license to the system clipboard as well")
    p.add_argument("--json", action="store_true", help="structured output")
    p.add_argument("--all", action="store_true",
                   help="ignore --product and dump every license keyed by heading")
    p.add_argument("--url", default=PAGE_URL,
                   help="override the source page (for testing/mirrors)")
    args = p.parse_args()

    html = fetch_html(args.url)
    pairs = extract_licenses_by_section(html)
    if not pairs:
        sys.exit("error: no licenses found on page (HTML structure may have changed)")

    if args.all:
        out = [{"heading": h, "license": l, "length": len(l)} for h, l in pairs]
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            for h, l in pairs:
                print(f"# {h} ({len(l)} chars)\n{l}\n")
        return

    key = pick_license(pairs, args.product)
    if not key:
        sys.exit(f"error: no license found for {args.product!r}. "
                 f"Available headings: {[h for h, _ in pairs]}")

    if args.copy:
        ok = to_clipboard(key)
        sys.stderr.write(f"[fetch] copied to clipboard: {ok}\n")

    if args.json:
        print(json.dumps({
            "product": args.product,
            "license": key,
            "length": len(key),
            "preview": key[:8] + "..." + key[-8:],
        }, indent=2))
    else:
        print(key)


if __name__ == "__main__":
    main()
