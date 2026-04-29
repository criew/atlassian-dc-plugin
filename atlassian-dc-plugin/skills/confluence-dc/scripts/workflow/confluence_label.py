#!/usr/bin/env python3
"""Page labels: list, add, remove."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, emit_dry_run, run  # noqa: E402
from _confluence import get_confluence  # noqa: E402


def cmd_list(args):
    client = get_confluence(args)
    data = client.get(f"content/{args.id}/label")
    labels = (data or {}).get("results", [])
    if args.json:
        emit(data, args)
        return
    if not labels:
        emit([], args, human=f"no labels on page {args.id}")
        return
    lines = [f"{l.get('prefix', 'global'):<8} {l.get('name')}" for l in labels]
    emit(labels, args, human="\n".join(lines) + f"\n\n{len(labels)} label(s)")


def cmd_add(args):
    payload = [{"prefix": args.prefix, "name": name} for name in args.label]
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/content/{args.id}/label", "body": payload},
            args,
            human=f"would add label(s) {', '.join(args.label)} to page {args.id}",
        )
        return
    client = get_confluence(args)
    data = client.post(f"content/{args.id}/label", payload)
    emit(data, args, human=f"added label(s) {', '.join(args.label)} to page {args.id}")


def cmd_remove(args):
    if args.dry_run:
        emit_dry_run(
            {
                "method": "DELETE",
                "path": f"/rest/api/content/{args.id}/label/{args.label}",
            },
            args,
            human=f"would remove label {args.label!r} from page {args.id}",
        )
        return
    client = get_confluence(args)
    client.delete(f"content/{args.id}/label/{args.label}")
    emit({"removed": args.label, "page_id": args.id}, args,
         human=f"removed label {args.label!r} from page {args.id}")


def main():
    p = argparse.ArgumentParser(description="Confluence page labels")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list labels on a page")
    ls.add_argument("id", help="page id")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="add label(s) to a page")
    a.add_argument("id", help="page id")
    a.add_argument("--label", action="append", required=True,
                   help="label name (repeat for multiple)")
    a.add_argument("--prefix", choices=["global", "my", "team"], default="global")
    add_common_args(a)
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("remove", help="remove a label from a page")
    r.add_argument("id", help="page id")
    r.add_argument("--label", required=True, help="label name to remove")
    add_common_args(r)
    r.set_defaults(func=cmd_remove)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
