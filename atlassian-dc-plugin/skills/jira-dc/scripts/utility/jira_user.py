#!/usr/bin/env python3
"""User helpers: whoami (verify PAT), search."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, get_jira, emit, emit_dry_run, run  # noqa: E402


def cmd_whoami(args):
    client = get_jira(args)
    data = client.get("myself")
    emit(data, args, human=f"{data.get('name')} <{data.get('emailAddress', '')}> "
                           f"on {client.instance.url} (alias={client.instance.alias})")


def cmd_search(args):
    client = get_jira(args)
    data = client.get("user/search", params={"username": args.query, "maxResults": args.limit})
    if args.json:
        emit(data, args)
        return
    lines = [f"{u.get('name'):<20} {u.get('displayName')} <{u.get('emailAddress', '')}>" for u in data]
    emit(data, args, human="\n".join(lines) or "no users found")


def cmd_create(args):
    body = {
        "name": args.username,
        "password": args.password,
        "emailAddress": args.email,
        "displayName": args.display_name,
        "applicationKeys": ["jira-software"],
    }
    if args.dry_run:
        # Don't echo the password back to the LLM in dry-run.
        masked = {**body, "password": "***"}
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/2/user", "body": masked},
            args,
            human=f"would create user {args.username} <{args.email}>",
        )
        return
    client = get_jira(args)
    data = client.post("user", body)
    emit(data, args, human=f"created user {data.get('name')} <{data.get('emailAddress', '')}>")


def cmd_update(args):
    body: dict = {}
    if args.email is not None:
        body["emailAddress"] = args.email
    if args.display_name is not None:
        body["displayName"] = args.display_name
    if args.active is not None:
        body["active"] = args.active.lower() == "true"
    if not body:
        from _common import ValidationError as _VE
        raise _VE("no field given to update")
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/2/user?username={args.username}", "body": body},
            args,
            human=f"would update user {args.username} fields: {', '.join(body.keys())}",
        )
        return
    client = get_jira(args)
    data = client.put(f"user?username={args.username}", body)
    emit(data, args, human=f"updated user {args.username}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/2/user?username={args.username}"},
            args,
            human=f"would delete user {args.username}",
        )
        return
    client = get_jira(args)
    client.delete(f"user?username={args.username}")
    emit({"deleted": args.username}, args, human=f"deleted user {args.username}")


def cmd_assignable(args):
    client = get_jira(args)
    params = {"maxResults": args.limit}
    if args.issue_key:
        params["issueKey"] = args.issue_key
    elif args.project:
        params["project"] = args.project
    else:
        from _common import ValidationError as _VE
        raise _VE("need --issue-key or --project")
    if args.query:
        params["username"] = args.query
    data = client.get("user/assignable/search", params=params)
    if args.json:
        emit(data, args)
        return
    lines = [f"{u.get('name'):<20} {u.get('displayName'):<25} <{u.get('emailAddress', '')}>"
             for u in data]
    emit(data, args, human="\n".join(lines) or "no assignable users found")


def main():
    p = argparse.ArgumentParser(description="Jira user operations")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("whoami", help="verify PAT, show authenticated user")
    add_common_args(w)
    w.set_defaults(func=cmd_whoami)

    s = sub.add_parser("search", help="search users by name/email")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    add_common_args(s)
    s.set_defaults(func=cmd_search)

    c = sub.add_parser("create", help="create a new user (admin only)")
    c.add_argument("--username", required=True)
    c.add_argument("--password", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--display-name", required=True)
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    u = sub.add_parser("update", help="update user fields (admin only)")
    u.add_argument("--username", required=True)
    u.add_argument("--email")
    u.add_argument("--display-name")
    u.add_argument("--active", choices=["true", "false"])
    add_common_args(u)
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("delete", help="delete a user (admin only)")
    d.add_argument("--username", required=True)
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    a = sub.add_parser("assignable",
                       help="list users assignable to an issue or in a project")
    grp = a.add_mutually_exclusive_group()
    grp.add_argument("--issue-key", help="restrict to users assignable to this issue")
    grp.add_argument("--project", help="users assignable in this project")
    a.add_argument("--query", help="username substring filter")
    a.add_argument("--limit", type=int, default=50)
    add_common_args(a)
    a.set_defaults(func=cmd_assignable)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
