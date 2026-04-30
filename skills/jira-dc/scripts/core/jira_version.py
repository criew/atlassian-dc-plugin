#!/usr/bin/env python3
"""Jira project versions: list, create, release."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import (  # noqa: E402
    add_common_args,
    emit,
    emit_dry_run,
    run,
)
from _jira import get_jira  # noqa: E402

def cmd_list(args):
    client = get_jira(args)
    data = client.get(f"project/{args.project}/versions")
    if args.json:
        emit(data, args)
        return
    if not data:
        emit(data, args, human="no versions")
        return
    lines = []
    for v in data:
        marker = " (released)" if v.get("released") else ""
        rd = v.get("releaseDate", "")
        lines.append(f"{v.get('id'):<8} {v.get('name'):<20} {rd}{marker}")
    emit(data, args, human="\n".join(lines) + f"\n\n{len(data)} version(s)")


def cmd_create(args):
    body = {"name": args.name, "project": args.project}
    if args.description:
        body["description"] = args.description
    if args.release_date:
        body["releaseDate"] = args.release_date
    if args.start_date:
        body["startDate"] = args.start_date

    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/2/version", "body": body},
            args,
            human=f"would create version {args.name!r} in {args.project}",
        )
        return
    client = get_jira(args)
    data = client.post("version", body)
    emit(data, args, human=f"created version {data.get('name')} (id={data.get('id')})")


def cmd_release(args):
    body = {"released": True}
    if args.release_date:
        body["releaseDate"] = args.release_date
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/2/version/{args.id}", "body": body},
            args,
            human=f"would release version id={args.id}",
        )
        return
    client = get_jira(args)
    data = client.put(f"version/{args.id}", body)
    emit(data, args, human=f"released version {data.get('name')} (id={data.get('id')})")


def main():
    p = argparse.ArgumentParser(description="Jira project versions")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list versions of a project")
    ls.add_argument("--project", required=True, help="project key")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    c = sub.add_parser("create", help="create a new version")
    c.add_argument("--project", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--description")
    c.add_argument("--release-date", help="YYYY-MM-DD")
    c.add_argument("--start-date", help="YYYY-MM-DD")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    r = sub.add_parser("release", help="mark a version as released")
    r.add_argument("id", help="version id from list")
    r.add_argument("--release-date", help="YYYY-MM-DD (default today on server)")
    add_common_args(r)
    r.set_defaults(func=cmd_release)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
