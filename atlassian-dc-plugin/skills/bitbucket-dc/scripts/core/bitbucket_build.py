#!/usr/bin/env python3
"""Bitbucket build status: list per commit, post build result.

Uses the Build Status API (separate base path /rest/build-status/1.0/).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    add_common_args, emit, emit_dry_run, run, ValidationError,
)
from _bitbucket import get_bitbucket  # noqa: E402


VALID_STATES = ("SUCCESSFUL", "INPROGRESS", "FAILED", "CANCELLED")


def cmd_list(args):
    client = get_bitbucket(args)
    data = client.get(f"/rest/build-status/1.0/commits/{args.commit}",
                      params={"limit": args.limit})
    values = data.get("values", []) if isinstance(data, dict) else []
    if args.json:
        emit(data, args)
        return
    if not values:
        emit([], args, human=f"no build statuses for commit {args.commit}")
        return
    lines = []
    for b in values:
        when = (b.get("dateAdded") or b.get("date") or "")
        if isinstance(when, int):
            from datetime import datetime
            when = datetime.fromtimestamp(when / 1000).isoformat(timespec="seconds")
        lines.append(f"{b.get('state'):<11} {b.get('key'):<25} {b.get('name'):<30} {b.get('url')}")
    emit(values, args, human="\n".join(lines) + f"\n\n{len(values)} build status(es)")


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
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list build statuses for a commit")
    ls.add_argument("commit", help="full commit SHA")
    ls.add_argument("--limit", type=int, default=50)
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
