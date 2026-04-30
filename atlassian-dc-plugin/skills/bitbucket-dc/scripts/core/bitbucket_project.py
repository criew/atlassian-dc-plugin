#!/usr/bin/env python3
"""Bitbucket project operations: list, get, create."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, emit_dry_run, run  # noqa: E402
from _bitbucket import get_bitbucket  # noqa: E402


def cmd_list(args):
    client = get_bitbucket(args)
    params = {}
    if args.name:
        params["name"] = args.name
    values = client.paginate("projects", params=params, limit=args.limit)
    if args.json:
        emit({"size": len(values), "values": values}, args)
        return
    lines = [f"{p.get('key', ''):<14} {p.get('name', '')}" for p in values]
    emit(values, args, human="\n".join(lines) + f"\n\n{len(values)} project(s)")


def cmd_get(args):
    client = get_bitbucket(args)
    data = client.get(f"projects/{args.key}")
    emit(data, args,
         human=f"{data.get('key')}: {data.get('name')} (id={data.get('id')})")


def cmd_create(args):
    body = {"key": args.key, "name": args.name}
    if args.description:
        body["description"] = args.description
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/1.0/projects", "body": body},
            args,
            human=f"would create project {args.key} ({args.name})",
        )
        return
    client = get_bitbucket(args)
    data = client.post("projects", body)
    emit(data, args, human=f"created project {data.get('key')} (id={data.get('id')})")


def main():
    p = argparse.ArgumentParser(description="Bitbucket projects")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list projects")
    ls.add_argument("--name", help="filter by name substring")
    ls.add_argument("--limit", type=int, default=100)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="get a project by key")
    g.add_argument("key")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create a project")
    c.add_argument("--key", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--description")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
