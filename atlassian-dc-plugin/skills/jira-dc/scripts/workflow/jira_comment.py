#!/usr/bin/env python3
"""Issue comments: list, add."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, get_jira, emit, emit_dry_run, run  # noqa: E402


def cmd_list(args):
    client = get_jira(args)
    data = client.get(f"issue/{args.key}/comment")
    comments = data.get("comments", [])
    if args.json:
        emit(data, args)
        return
    lines = []
    for c in comments:
        author = (c.get("author") or {}).get("name", "?")
        when = c.get("created", "")[:19]
        body = (c.get("body") or "").strip()
        lines.append(f"[{when}] {author}: {body}")
    emit(comments, args, human="\n\n".join(lines) or "no comments")


def cmd_add(args):
    body = {"body": args.body}
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/2/issue/{args.key}/comment", "body": body},
            args,
            human=f"would add comment to {args.key}",
        )
        return
    client = get_jira(args)
    data = client.post(f"issue/{args.key}/comment", body)
    emit(data, args, human=f"comment {data.get('id')} added to {args.key}")


def main():
    p = argparse.ArgumentParser(description="Jira issue comments")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list comments on an issue")
    ls.add_argument("key")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="add a comment")
    a.add_argument("key")
    a.add_argument("--body", required=True)
    add_common_args(a)
    a.set_defaults(func=cmd_add)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
