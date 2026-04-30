#!/usr/bin/env python3
"""Page comments: list, add, delete."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import add_common_args, emit, emit_dry_run, run  # noqa: E402
from _confluence import get_confluence  # noqa: E402


def cmd_list(args):
    client = get_confluence(args)
    params = {"expand": "body.storage,history,version", "depth": args.depth}
    data = client.get(f"content/{args.id}/child/comment", params=params)
    comments = (data or {}).get("results", [])
    if args.json:
        emit(data, args)
        return
    if not comments:
        emit([], args, human=f"no comments on page {args.id}")
        return
    lines = []
    for c in comments:
        author = ((c.get("history") or {}).get("createdBy") or {}).get("displayName", "?")
        when = ((c.get("history") or {}).get("createdDate") or "")[:19]
        body_text = (((c.get("body") or {}).get("storage") or {}).get("value") or "").strip()
        lines.append(f"[{when}] {author} (id={c.get('id')}): {body_text}")
    emit(comments, args, human="\n\n".join(lines) + f"\n\n{len(comments)} comment(s)")


def cmd_add(args):
    payload: dict = {
        "type": "comment",
        "container": {"id": args.id, "type": "page"},
        "body": {
            "storage": {"value": args.body, "representation": "storage"}
        },
    }
    if args.parent:
        payload["ancestors"] = [{"id": args.parent}]
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/content", "body": payload},
            args,
            human=f"would add comment to page {args.id}"
                  + (f" (reply to {args.parent})" if args.parent else ""),
        )
        return
    client = get_confluence(args)
    data = client.post("content", payload)
    emit(data, args, human=f"comment {data.get('id')} added to page {args.id}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/content/{args.comment_id}"},
            args,
            human=f"would delete comment {args.comment_id}",
        )
        return
    client = get_confluence(args)
    client.delete(f"content/{args.comment_id}")
    emit({"deleted": args.comment_id}, args, human=f"deleted comment {args.comment_id}")


def main():
    p = argparse.ArgumentParser(description="Confluence page comments")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list comments on a page")
    ls.add_argument("id", help="page id")
    ls.add_argument("--depth", choices=["all", "root"], default="all")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="add a comment to a page")
    a.add_argument("id", help="page id")
    a.add_argument("--body", required=True, help="storage-format XHTML")
    a.add_argument("--parent", help="parent comment id (reply)")
    add_common_args(a)
    a.set_defaults(func=cmd_add)

    d = sub.add_parser("delete", help="delete a comment by id")
    d.add_argument("comment_id")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
