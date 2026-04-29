#!/usr/bin/env python3
"""Bitbucket tag operations: list, create, delete."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, emit_dry_run, run  # noqa: E402
from _bitbucket import get_bitbucket  # noqa: E402


def cmd_list(args):
    client = get_bitbucket(args)
    params = {}
    if args.filter:
        params["filterText"] = args.filter
    if args.order:
        params["orderBy"] = args.order
    path = f"projects/{args.project}/repos/{args.repo}/tags"
    values = client.paginate(path, params=params, limit=args.limit)
    if args.json:
        emit({"size": len(values), "values": values}, args)
        return
    lines = [
        f"{t.get('displayId', ''):<30} {t.get('latestCommit', '')[:10]} "
        f"({t.get('type', '')})"
        for t in values
    ]
    emit(values, args, human="\n".join(lines) + f"\n\n{len(values)} tag(s)")


def cmd_create(args):
    body = {"name": args.name}
    if args.start_point:
        body["startPoint"] = args.start_point
    if args.message:
        body["message"] = args.message
    path = f"projects/{args.project}/repos/{args.repo}/tags"
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/1.0/{path}", "body": body},
            args,
            human=f"would create tag {args.name} on {args.project}/{args.repo}"
                  + (f" at {args.start_point}" if args.start_point else ""),
        )
        return
    client = get_bitbucket(args)
    data = client.post(path, body)
    emit(data, args, human=f"created tag {data.get('displayId') or args.name}")


def cmd_delete(args):
    path = f"/rest/git/1.0/projects/{args.project}/repos/{args.repo}/tags/{args.name}"
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": path},
            args,
            human=f"would delete tag {args.name} on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    client.delete(path)
    emit({"deleted": args.name}, args, human=f"deleted tag {args.name}")


def main():
    p = argparse.ArgumentParser(description="Bitbucket tags")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list tags")
    ls.add_argument("--project", required=True)
    ls.add_argument("--repo", required=True)
    ls.add_argument("--filter", help="filter by name substring")
    ls.add_argument("--order", choices=["ALPHABETICAL", "MODIFICATION"])
    ls.add_argument("--limit", type=int, default=100)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    c = sub.add_parser("create", help="create a tag")
    c.add_argument("--project", required=True)
    c.add_argument("--repo", required=True)
    c.add_argument("--name", required=True, help="tag name, e.g. v1.0.0")
    c.add_argument("--start-point", help="commit or ref")
    c.add_argument("--message")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    d = sub.add_parser("delete", help="delete a tag")
    d.add_argument("--project", required=True)
    d.add_argument("--repo", required=True)
    d.add_argument("--name", required=True)
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
