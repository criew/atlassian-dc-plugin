#!/usr/bin/env python3
"""Bitbucket build status: list per commit, post build result.

Uses the Build Status API (separate base path /rest/build-status/1.0/).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import (  # noqa: E402
    add_common_args, emit, emit_dry_run, emit_list, run, ValidationError,
)
from _bitbucket import get_bitbucket  # noqa: E402


VALID_STATES = ("SUCCESSFUL", "INPROGRESS", "FAILED", "CANCELLED")


def cmd_list(args):
    client = get_bitbucket(args)
    data = client.get(f"/rest/build-status/1.0/commits/{args.commit}",
                      params={"start": args.start, "limit": args.limit})
    values = data.get("values", []) if isinstance(data, dict) else []
    if not values:
        emit({"returned": 0, "total": None, "truncated": False, "values": []},
             args, human=f"no build statuses for commit {args.commit}")
        return
    is_last_page = (not isinstance(data, dict)) or data.get("isLastPage", True)
    truncated = not is_last_page
    next_start = data.get("nextPageStart") if isinstance(data, dict) else None
    if next_start is None:
        next_start = args.start + len(values)
    hint = f"rerun with a higher --limit (or --start {next_start}) to fetch more" if truncated else None
    lines = []
    for b in values:
        when = (b.get("dateAdded") or b.get("date") or "")
        if isinstance(when, int):
            from datetime import datetime
            when = datetime.fromtimestamp(when / 1000).isoformat(timespec="seconds")
        lines.append(f"{b.get('state'):<11} {b.get('key'):<25} {b.get('name'):<30} {b.get('url')}")
    emit_list(values, args, lines, total=None, truncated=truncated, next_hint=hint,
              item_name="build status", key="values")


def cmd_post(args):
    if args.state not in VALID_STATES:
        raise ValidationError(f"state must be one of {VALID_STATES}")
    body = {
        "state":       args.state,
        "key":         args.key,
        "name":        args.name,
        "url":         args.url,
    }
    if args.description:
        body["description"] = args.description
    if args.dry_run:
        emit_dry_run(
            {"method": "POST",
             "path": f"/rest/build-status/1.0/commits/{args.commit}",
             "body": body},
            args,
            human=f"would post {args.state} build status {args.key!r} on commit {args.commit}",
        )
        return
    client = get_bitbucket(args)
    client.post(f"/rest/build-status/1.0/commits/{args.commit}", body)
    emit({"posted": True, "state": args.state, "commit": args.commit, "key": args.key},
         args, human=f"posted {args.state} status {args.key!r} on {args.commit}")


def main():
    p = argparse.ArgumentParser(description="Bitbucket build statuses (per-commit)")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list build statuses for a commit")
    ls.add_argument("commit", help="full commit SHA")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--start", type=int, default=0, help="initial pagination offset")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    po = sub.add_parser("post", help="post a build status to a commit")
    po.add_argument("commit", help="full commit SHA")
    po.add_argument("--state", required=True,
                    help="SUCCESSFUL, INPROGRESS, FAILED, or CANCELLED")
    po.add_argument("--key", required=True, help="unique build key (e.g. MY-PIPELINE-42)")
    po.add_argument("--name", required=True, help="human-readable name")
    po.add_argument("--url", required=True, help="link to the build run")
    po.add_argument("--description")
    add_common_args(po)
    po.set_defaults(func=cmd_post)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
