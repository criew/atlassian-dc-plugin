#!/usr/bin/env python3
"""Jira groups: list, members, create, delete, add-user, remove-user."""

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
    params = {"maxResults": args.limit}
    if args.query:
        params["query"] = args.query
    data = client.get("groups/picker", params=params)
    groups = data.get("groups", [])
    if args.json:
        emit(data, args)
        return
    lines = [g.get("name", "") for g in groups]
    emit(groups, args, human="\n".join(lines) + f"\n\n{len(groups)} group(s)")


def cmd_members(args):
    client = get_jira(args)
    params = {"groupname": args.name, "maxResults": args.limit, "includeInactiveUsers": "false"}
    data = client.get("group/member", params=params)
    members = data.get("values", [])
    if args.json:
        emit(data, args)
        return
    lines = [f"{u.get('name'):<20} {u.get('displayName'):<25} <{u.get('emailAddress', '')}>"
             for u in members]
    emit(members, args, human="\n".join(lines) + f"\n\n{len(members)} member(s) of {args.name}")


def cmd_create(args):
    body = {"name": args.name}
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/2/group", "body": body},
            args,
            human=f"would create group {args.name!r}",
        )
        return
    client = get_jira(args)
    data = client.post("group", body)
    emit(data, args, human=f"created group {data.get('name')}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/2/group?groupname={args.name}"},
            args,
            human=f"would delete group {args.name}",
        )
        return
    client = get_jira(args)
    client.delete(f"group?groupname={args.name}")
    emit({"deleted": args.name}, args, human=f"deleted group {args.name}")


def cmd_add_user(args):
    body = {"name": args.user}
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/2/group/user?groupname={args.name}", "body": body},
            args,
            human=f"would add {args.user} to group {args.name}",
        )
        return
    client = get_jira(args)
    data = client.post(f"group/user?groupname={args.name}", body)
    emit(data, args, human=f"added {args.user} to {args.name}")


def cmd_remove_user(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE",
             "path": f"/rest/api/2/group/user?groupname={args.name}&username={args.user}"},
            args,
            human=f"would remove {args.user} from group {args.name}",
        )
        return
    client = get_jira(args)
    client.delete(f"group/user?groupname={args.name}&username={args.user}")
    emit({"removed": args.user, "from": args.name}, args,
         human=f"removed {args.user} from {args.name}")


def main():
    p = argparse.ArgumentParser(description="Jira group operations")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="search/list groups")
    ls.add_argument("--query", help="filter by name substring")
    ls.add_argument("--limit", type=int, default=50)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    m = sub.add_parser("members", help="list members of a group")
    m.add_argument("--name", required=True)
    m.add_argument("--limit", type=int, default=50)
    add_common_args(m)
    m.set_defaults(func=cmd_members)

    c = sub.add_parser("create", help="create a group")
    c.add_argument("--name", required=True)
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    d = sub.add_parser("delete", help="delete a group")
    d.add_argument("--name", required=True)
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    a = sub.add_parser("add-user", help="add a user to a group")
    a.add_argument("--name", required=True, help="group name")
    a.add_argument("--user", required=True, help="username")
    add_common_args(a)
    a.set_defaults(func=cmd_add_user)

    r = sub.add_parser("remove-user", help="remove a user from a group")
    r.add_argument("--name", required=True, help="group name")
    r.add_argument("--user", required=True, help="username")
    add_common_args(r)
    r.set_defaults(func=cmd_remove_user)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
