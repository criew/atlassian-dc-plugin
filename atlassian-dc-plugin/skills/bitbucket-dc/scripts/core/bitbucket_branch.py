#!/usr/bin/env python3
"""Bitbucket branch operations: list, get-default, create, delete.

Branch create/delete uses /rest/branch-utils/1.0/, NOT /rest/api/1.0/.
"""
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
    if args.details:
        params["details"] = "true"
    path = f"projects/{args.project}/repos/{args.repo}/branches"
    values = client.paginate(path, params=params, limit=args.limit)
    if args.json:
        emit({"size": len(values), "values": values}, args)
        return
    lines = [
        f"{b.get('displayId', ''):<40} {b.get('latestCommit', '')[:10]} "
        f"{'(default)' if b.get('isDefault') else ''}"
        for b in values
    ]
    emit(values, args, human="\n".join(lines) + f"\n\n{len(values)} branch(es)")


def cmd_default(args):
    client = get_bitbucket(args)
    data = client.get(f"projects/{args.project}/repos/{args.repo}/default-branch")
    emit(data, args,
         human=f"default: {data.get('displayId') or data.get('id')} "
               f"(latestCommit={data.get('latestCommit', '')[:10]})")


def cmd_create(args):
    body: dict = {"name": args.name}
    if args.start_point:
        body["startPoint"] = args.start_point
    if args.message:
        body["message"] = args.message
    path = f"/rest/branch-utils/1.0/projects/{args.project}/repos/{args.repo}/branches"
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": path, "body": body},
            args,
            human=f"would create branch {args.name} on {args.project}/{args.repo}"
                  + (f" from {args.start_point}" if args.start_point else ""),
        )
        return
    client = get_bitbucket(args)
    data = client.post(path, body)
    emit(data, args, human=f"created branch {data.get('displayId') or args.name}")


def cmd_delete(args):
    name = args.name
    if not name.startswith("refs/heads/"):
        ref = f"refs/heads/{name}"
    else:
        ref = name
    body = {"name": ref, "dryRun": False}
    path = f"/rest/branch-utils/1.0/projects/{args.project}/repos/{args.repo}/branches"
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": path, "body": {**body, "dryRun": True}},
            args,
            human=f"would delete branch {ref} on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    client.delete(path, body=body)
    emit({"deleted": ref}, args, human=f"deleted branch {ref}")


def main():
    p = argparse.ArgumentParser(description="Bitbucket branches")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list branches")
    ls.add_argument("--project", required=True)
    ls.add_argument("--repo", required=True)
    ls.add_argument("--filter", help="filter by name substring")
    ls.add_argument("--order", choices=["ALPHABETICAL", "MODIFICATION"])
    ls.add_argument("--details", action="store_true",
                    help="include latest commit info")
    ls.add_argument("--limit", type=int, default=100)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    gd = sub.add_parser("get-default", help="get the default branch")
    gd.add_argument("--project", required=True)
    gd.add_argument("--repo", required=True)
    add_common_args(gd)
    gd.set_defaults(func=cmd_default)

    c = sub.add_parser("create", help="create a branch")
    c.add_argument("--project", required=True)
    c.add_argument("--repo", required=True)
    c.add_argument("--name", required=True, help="branch name (e.g. feature/X)")
    c.add_argument("--start-point", help="ref or commit to branch from "
                                          "(e.g. refs/heads/main)")
    c.add_argument("--message", help="branch creation message")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    d = sub.add_parser("delete", help="delete a branch")
    d.add_argument("--project", required=True)
    d.add_argument("--repo", required=True)
    d.add_argument("--name", required=True,
                   help="branch name (refs/heads/ prefix added if missing)")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
