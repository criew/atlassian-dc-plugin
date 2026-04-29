#!/usr/bin/env python3
"""User helpers: whoami (verify PAT), search."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, get_jira, emit, emit_dry_run, run  # noqa: E402


def cmd_whoami(args):
    client = get_jira(args)
    data = client.get("myself")
    emit(data, args, human=f"{data.get('name')} <{data.get('emailAddress', '')}> "
                           f"on {client.instance.url} (alias={client.instance.alias})")


def cmd_search(args):
    client = get_jira(args)
    data = client.get("user/search", params={"username": args.query, "maxResults": args.limit})
    if args.json:
        emit(data, args)
        return
    lines = [f"{u.get('name'):<20} {u.get('displayName')} <{u.get('emailAddress', '')}>" for u in data]
    emit(data, args, human="\n".join(lines) or "no users found")


def cmd_create(args):
    body = {
        "name": args.username,
        "password": args.password,
        "emailAddress": args.email,
        "displayName": args.display_name,
        "applicationKeys": ["jira-software"],
    }
    if args.dry_run:
        # Don't echo the password back to the LLM in dry-run.
        masked = {**body, "password": "***"}
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/2/user", "body": masked},
            args,
            human=f"would create user {args.username} <{args.email}>",
        )
        return
    client = get_jira(args)
    data = client.post("user", body)
    emit(data, args, human=f"created user {data.get('name')} <{data.get('emailAddress', '')}>")


def main():
    p = argparse.ArgumentParser(description="Jira user operations")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("whoami", help="verify PAT, show authenticated user")
    add_common_args(w)
    w.set_defaults(func=cmd_whoami)

    s = sub.add_parser("search", help="search users by name/email")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    add_common_args(s)
    s.set_defaults(func=cmd_search)

    c = sub.add_parser("create", help="create a new user (admin only)")
    c.add_argument("--username", required=True)
    c.add_argument("--password", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--display-name", required=True)
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
