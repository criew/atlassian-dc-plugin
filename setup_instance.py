#!/usr/bin/env python3
"""Interactive instance + PAT setup for the Atlassian DC skills.

Walks the user through:
  1. choosing/creating an alias (default: 'local')
  2. picking which products (jira / confluence / bitbucket) to configure
  3. for each: base URL + Personal Access Token (PAT)
  4. verifying the PAT works
  5. writing the result into instances.json

Idempotent: running again with the same alias overwrites only the products
named on this run; other products + other aliases stay untouched. Adding a
new alias 'staging' later does not affect 'local'.

Usage:
    python setup_instance.py                              # fully interactive
    python setup_instance.py --alias prod --product jira --product confluence
    python setup_instance.py --alias local --product all --non-interactive \\
        --jira-url http://localhost:8080 --jira-token ABCD1234 \\
        --confluence-url http://localhost:8090 --confluence-token EFGH5678

Advanced (auto-create PATs via login — useful for dev/docker setups):
    python setup_instance.py --create-pat --alias local --product all --non-interactive \\
        --jira-url http://localhost:8080 --jira-user admin --jira-pass admin123 \\
        --confluence-url http://localhost:8090 --confluence-user admin --confluence-pass admin123 \\
        --bitbucket-url http://localhost:7990 --bitbucket-user admin --bitbucket-pass admin123
"""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests

PRODUCTS = ("jira", "confluence", "bitbucket")

VERIFY_URLS = {
    "jira":       "{base}/rest/api/2/myself",
    "confluence": "{base}/rest/api/user/current",
    "bitbucket":  "{base}/rest/api/1.0/application-properties",
}

# Login + PAT-creation config (only used with --create-pat)
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

def _instances_file():
    # type: () -> Path
    explicit = os.environ.get("ATLASSIAN_INSTANCES_FILE")
    if explicit:
        return Path(explicit)
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "atlassian" / "instances.json"
    return Path.home() / ".config" / "atlassian" / "instances.json"


def _load_instances():
    # type: () -> dict
    path = _instances_file()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"default": "local", "instances": {}}


def _save_instances(cfg):
    # type: (dict) -> Path
    path = _instances_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


# -----------------------------------------------------------------------------
# PAT verification
# -----------------------------------------------------------------------------

def verify_pat(product, base, token):
    # type: (str, str, str) -> int
    url = VERIFY_URLS[product].format(base=base.rstrip("/"))
    r = requests.get(url, headers={"Authorization": "Bearer " + token}, timeout=30)
    return r.status_code


# -----------------------------------------------------------------------------
# PAT auto-creation (--create-pat mode)
# -----------------------------------------------------------------------------

def _create_pat_via_session(s, product, base, user, pw, name, days):
    # type: (requests.Session, str, str, str, str, str, int) -> Optional[str]
    cfg = PRODUCT_LOGIN[product]
    r = s.post(cfg["login_url"].format(base=base, user=user),
               data=cfg["login_form"](user, pw),
               allow_redirects=True, timeout=30)
    if "loginfailed" in r.url or cfg["fail_signal"] in r.text:
        return None
    v = s.get(cfg["verify_url"].format(base=base, user=user), timeout=30)
    if v.status_code != 200:
        return None
    return _post_pat(s, product, base, user, name, days, basic_auth=None)


def _post_pat(s, product, base, user, name, days, basic_auth=None):
    # type: (requests.Session, str, str, str, str, int, Optional[tuple]) -> Optional[str]
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
        sys.stderr.write("  PAT call returned %d: %s\n" % (r.status_code, r.text[:200]))
        return None
    j = r.json()
    return (j.get("rawToken") or j.get("token")
            or j.get("value") or j.get("secret"))


def create_pat(product, base, user, pw, name="skill-token", days=90):
    # type: (str, str, str, str, str, int) -> str
    base = base.rstrip("/")
    s = requests.Session()
    s.headers.update({"User-Agent": "atlassian-dc-setup/1.0"})
    token = _create_pat_via_session(s, product, base, user, pw, name, days)
    if token:
        return token
    sys.stderr.write("  cookie login failed, trying basic auth on PAT endpoint...\n")
    s2 = requests.Session()
    s2.headers.update({"User-Agent": "atlassian-dc-setup/1.0"})
    token = _post_pat(s2, product, base, user, name, days, basic_auth=(user, pw))
    if token:
        return token
    sys.exit("error: could not create PAT for %s — check user/pass and "
             "that %s is reachable" % (product, base))


# -----------------------------------------------------------------------------
# Interactive prompts
# -----------------------------------------------------------------------------

def prompt(question, default=None):
    # type: (str, Optional[str]) -> str
    suffix = " [%s]" % default if default else ""
    while True:
        ans = input("%s%s: " % (question, suffix)).strip()
        if ans:
            return ans
        if default is not None:
            return default


def prompt_secret(question):
    # type: (str,) -> str
    return getpass.getpass("%s: " % question).strip()


def prompt_yes(question, default=True):
    # type: (str, bool) -> bool
    suffix = "[Y/n]" if default else "[y/N]"
    ans = input("%s %s: " % (question, suffix)).strip().lower()
    if not ans:
        return default
    return ans.startswith("y")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    # type: () -> None
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--alias", help="instance alias (default: prompt)")
    p.add_argument("--product", action="append",
                   help="product(s) to configure; repeat. Use 'all' for jira+confluence+bitbucket")
    p.add_argument("--non-interactive", action="store_true",
                   help="fail if any required input is missing instead of prompting")
    p.add_argument("--make-default", action="store_true",
                   help="set this alias as the default in instances.json")
    p.add_argument("--ssl-verify", action="store_true", default=False,
                   help="enable SSL certificate verification (default: off)")
    p.add_argument("--create-pat", action="store_true",
                   help="auto-create PATs by logging in with user/password "
                        "(for dev setups; default is to enter an existing PAT)")
    for prod in PRODUCTS:
        p.add_argument("--%s-url" % prod)
        p.add_argument("--%s-token" % prod,
                       help="Personal Access Token (default mode)")
        p.add_argument("--%s-user" % prod,
                       help="admin username (only with --create-pat)")
        p.add_argument("--%s-pass" % prod,
                       help="admin password (only with --create-pat)")
    args = p.parse_args()

    cfg = _load_instances()
    existing_aliases = list(cfg.get("instances", {}).keys())

    # Alias
    alias = args.alias
    if not alias:
        if args.non_interactive:
            sys.exit("error: --alias required in --non-interactive mode")
        if existing_aliases:
            print("existing aliases: %s" % ", ".join(existing_aliases))
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
            if prompt_yes("Configure %s?" % prod, default=True):
                wanted.append(prod)
        products = wanted
    if not products:
        sys.exit("error: no products selected")

    # Collect per-product config
    per_product = {}
    for prod in products:
        url = getattr(args, "%s_url" % prod)
        if not url:
            if args.non_interactive:
                sys.exit("error: --%s-url required" % prod)
            url = prompt("%s base URL" % prod)
        url = url.rstrip("/")

        if args.create_pat:
            user = getattr(args, "%s_user" % prod)
            pw = getattr(args, "%s_pass" % prod)
            if not user:
                if args.non_interactive:
                    sys.exit("error: --%s-user required with --create-pat" % prod)
                user = prompt("%s admin username" % prod, default="admin")
            if not pw:
                if args.non_interactive:
                    sys.exit("error: --%s-pass required with --create-pat" % prod)
                pw = prompt_secret("%s password for %s" % (prod, user))
            per_product[prod] = {"url": url, "mode": "create", "user": user, "pass": pw}
        else:
            token = getattr(args, "%s_token" % prod)
            if not token:
                if args.non_interactive:
                    sys.exit("error: --%s-token required" % prod)
                print()
                print("  Create a PAT in %s:" % prod)
                print("    %s/plugins/servlet/access-tokens/manage/usertokens" % url
                      if prod != "bitbucket" else
                      "    %s/plugins/servlet/access-tokens/users/manage" % url)
                print("  Grant read+write permissions, then paste the token below.")
                print()
                token = prompt_secret("%s Personal Access Token (PAT)" % prod)
            if not token:
                sys.exit("error: empty PAT for %s" % prod)
            per_product[prod] = {"url": url, "mode": "token", "token": token}

    # Process each product
    cfg.setdefault("instances", {}).setdefault(alias, {})
    print()
    for prod, c in per_product.items():
        if c["mode"] == "create":
            print("[%s] login + PAT create at %s as %s" % (prod, c["url"], c["user"]))
            token = create_pat(prod, c["url"], c["user"], c["pass"])
        else:
            token = c["token"]
            print("[%s] verifying PAT at %s" % (prod, c["url"]))

        code = verify_pat(prod, c["url"], token)
        if code == 200:
            print("  -> PAT verified OK")
        elif code == 401:
            sys.stderr.write("  error: PAT rejected (401 Unauthorized). "
                             "Check that the token is correct and not expired.\n")
            sys.exit(1)
        elif code == 403:
            sys.stderr.write("  warning: PAT returned 403 Forbidden — token may "
                             "lack permissions, but saving anyway.\n")
        else:
            sys.stderr.write("  warning: verify returned %d — saving anyway, "
                             "but check connectivity and token.\n" % code)

        cfg["instances"][alias][prod] = {
            "url": c["url"],
            "token": token,
            "ssl_verify": args.ssl_verify,
        }

    if args.make_default or "default" not in cfg or not cfg.get("default"):
        cfg["default"] = alias

    out = _save_instances(cfg)
    print()
    print("wrote %s" % out)
    print("alias '%s' now has products: %s" % (alias, sorted(cfg["instances"][alias].keys())))
    if cfg.get("default") == alias:
        print("alias '%s' is the default" % alias)
    else:
        print("default remains '%s' "
              "(use --make-default to change, or edit instances.json manually)"
              % cfg.get("default"))


if __name__ == "__main__":
    main()
