#!/usr/bin/env python3
"""Confluence space operations: list, get, create."""

import argparse
import sys
from pathlib import Path

# Make shared/ importable
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, emit_dry_run, run  # noqa: E402
from _confluence import get_confluence, paginate  # noqa: E402


def cmd_list(args):
    client = get_confluence(args)
    params: dict = {}
    if args.type:
        params["type"] = args.type
    spaces = paginate(client, "space", params=params, limit=args.limit, page_size=25)
    if args.json:
        emit({"results": spaces, "size": len(spaces)}, args)
        return
    if not spaces:
        emit([], args, human="no spaces found")
        return
    lines = [f"{s.get('key'):<12} {s.get('name')}  ({s.get('type')})" for s in spaces]
    emit(spaces, args, human="\n".join(lines) + f"\n\n{len(spaces)} space(s)")


def cmd_get(args):
    client = get_confluence(args)
    data = client.get(f"space/{args.key}", params={"expand": "description.plain,homepage"})
    descr = ((data.get("description") or {}).get("plain") or {}).get("value", "")
    emit(data, args, human=f"{data.get('key')}: {data.get('name')} ({data.get('type')})\n{descr}")


def cmd_create(args):
    body: dict = {
        "key": args.key,
        "name": args.name,
    }
    if args.description:
        body["description"] = {
            "plain": {"value": args.description, "representation": "plain"}
        }
    if args.type:
        body["type"] = args.type

    path = "space/_private" if args.type == "personal" else "space"

    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/{path}", "body": body},
            args,
            human=f"would create space {args.key} ({args.name})",
        )
        return
    client = get_confluence(args)
    data = client.post(path, body)
    emit(data, args, human=f"created space {data.get('key', args.key)} (id={data.get('id')})")


def main():
    p = argparse.ArgumentParser(description="Confluence space operations")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list spaces")
    ls.add_argument("--type", choices=["global", "personal"])
    ls.add_argument("--limit", type=int, default=100)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="fetch space metadata")
    g.add_argument("key")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create a new space")
    c.add_argument("--key", required=True, help="space key (e.g. DOCS)")
    c.add_argument("--name", required=True)
    c.add_argument("--description")
    c.add_argument("--type", choices=["global", "personal"], default="global")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
