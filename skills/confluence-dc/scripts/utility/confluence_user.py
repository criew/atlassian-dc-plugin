#!/usr/bin/env python3
"""User helpers: whoami (verify PAT), search."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import add_common_args, emit, run  # noqa: E402
from _confluence import get_confluence  # noqa: E402


def cmd_whoami(args):
    client = get_confluence(args)
    # Confluence DC: /rest/api/user/current
    data = client.get("user/current")
    name = data.get("username") or data.get("name") or data.get("userKey")
    email = data.get("email") or data.get("emailAddress") or ""
    emit(data, args,
         human=f"{name} <{email}> on {client.instance.url} "
               f"(alias={client.instance.alias})")


def cmd_search(args):
    client = get_confluence(args)
    # /rest/api/search?cql=user.fullname~"X" OR user.username~"X"
    cql = (f'user.fullname ~ "{args.query}" '
           f'OR user.username ~ "{args.query}" '
           f'OR user.email ~ "{args.query}"')
    data = client.get("search", params={"cql": cql, "limit": args.limit})
    results = (data or {}).get("results", [])
    if args.json:
        emit(data, args)
        return
    if not results:
        emit([], args, human="no users found")
        return
    lines = []
    for r in results:
        u = r.get("user") or {}
        lines.append(f"{u.get('username', '?'):<20} {u.get('displayName', '')} "
                     f"<{u.get('email', '')}>")
    emit(results, args, human="\n".join(lines) + f"\n\n{len(results)} user(s)")


def main():
    p = argparse.ArgumentParser(description="Confluence user operations")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    w = sub.add_parser("whoami", help="verify PAT, show authenticated user")
    add_common_args(w)
    w.set_defaults(func=cmd_whoami)

    s = sub.add_parser("search", help="search users")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    add_common_args(s)
    s.set_defaults(func=cmd_search)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
