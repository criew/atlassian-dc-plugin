#!/usr/bin/env python3
"""Bitbucket user helpers: whoami (verify PAT), search."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, run  # noqa: E402
from _bitbucket import get_bitbucket  # noqa: E402


def cmd_whoami(args):
    """Bitbucket has no /myself endpoint — derive the user via /application-properties
    plus the PAT-owning user reachable from /rest/api/1.0/users by name. Cleanest
    portable signal is the dedicated /rest/api/1.0/inbox/pull-requests/count's
    existence; we use the documented PAT-introspection at /rest/access-tokens
    which any PAT owner can read for themselves.

    Pragmatically: just call /rest/api/1.0/application-properties to confirm the
    server can be reached and the PAT is accepted, then fall back to a 'users'
    search if the user wants to know who they are.
    """
    client = get_bitbucket(args)
    # First confirm the PAT works against an authenticated endpoint.
    info = client.get("/rest/api/1.0/application-properties")
    # Bitbucket's "current user" is best resolved via /plugins/servlet/applinks/whoami
    # which is not available in DC. Instead, look up dashboard info — every authed
    # user can read their own dashboard PRs and the response's userSlug-ish hints.
    # We expose the application-properties payload which always works as a PAT
    # health check and includes server version info.
    emit(info, args,
         human=f"connected to {client.instance.url} (alias={client.instance.alias}) "
               f"version={info.get('version')}")


def cmd_search(args):
    client = get_bitbucket(args)
    params = {"filter": args.query, "limit": args.limit}
    data = client.get("users", params=params)
    values = data.get("values", []) if isinstance(data, dict) else []
    if args.json:
        emit(data, args)
        return
    if not values:
        emit(data, args, human="no users found")
        return
    lines = [
        f"{u.get('name', ''):<20} {u.get('displayName', '')} <{u.get('emailAddress', '')}>"
        for u in values
    ]
    emit(values, args, human="\n".join(lines) + f"\n\n{len(values)} user(s)")


def main():
    p = argparse.ArgumentParser(description="Bitbucket user operations")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    w = sub.add_parser("whoami", help="verify PAT, show server info")
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
