#!/usr/bin/env python3
"""Bitbucket commit operations: list, get."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, run  # noqa: E402
from _bitbucket import get_bitbucket  # noqa: E402


def _summary(c: dict) -> dict:
    author = c.get("author") or {}
    return {
        "id": c.get("id"),
        "displayId": c.get("displayId"),
        "message": (c.get("message") or "").splitlines()[0] if c.get("message") else "",
        "author": author.get("name"),
        "author_email": author.get("emailAddress"),
        "committerTimestamp": c.get("committerTimestamp"),
        "parents": [p.get("id") for p in c.get("parents", [])],
    }


def cmd_list(args):
    client = get_bitbucket(args)
    params: dict = {}
    until = args.until or args.branch
    if until:
        params["until"] = until
    if args.since:
        params["since"] = args.since
    if args.path:
        params["path"] = args.path
    if args.merges:
        params["merges"] = args.merges
    path = f"projects/{args.project}/repos/{args.repo}/commits"
    values = client.paginate(path, params=params, limit=args.limit)
    if args.json:
        emit({"size": len(values), "values": values}, args)
        return
    lines = []
    for c in values:
        s = _summary(c)
        lines.append(f"{(s['displayId'] or '')[:10]:<11} {s['author'] or '?':<20} {s['message']}")
    emit([_summary(c) for c in values], args,
         human="\n".join(lines) + f"\n\n{len(values)} commit(s)")


def cmd_get(args):
    client = get_bitbucket(args)
    data = client.get(f"projects/{args.project}/repos/{args.repo}/commits/{args.id}")
    s = _summary(data)
    emit(data, args,
         human=f"{s['displayId']} {s['author']}: {s['message']}")


def main():
    p = argparse.ArgumentParser(description="Bitbucket commits")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list commits")
    ls.add_argument("--project", required=True)
    ls.add_argument("--repo", required=True)
    ls.add_argument("--branch", help="alias for --until refs/heads/<branch> or commit hash")
    ls.add_argument("--until", help="upper bound ref/commit (alias of --branch)")
    ls.add_argument("--since", help="lower bound ref/commit (exclusive)")
    ls.add_argument("--path", help="filter to commits touching this path")
    ls.add_argument("--merges", choices=["include", "exclude", "only"])
    ls.add_argument("--limit", type=int, default=25)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="get a commit by id")
    g.add_argument("--project", required=True)
    g.add_argument("--repo", required=True)
    g.add_argument("--id", required=True, help="commit hash")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
