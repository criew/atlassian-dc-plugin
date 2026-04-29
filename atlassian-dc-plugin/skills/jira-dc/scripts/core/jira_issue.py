#!/usr/bin/env python3
"""Jira issue CRUD: get, create, update, delete."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make shared/ importable
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    add_common_args, get_jira, emit, emit_dry_run, run, simplify_issue, ValidationError,
)


def cmd_get(args):
    client = get_jira(args)
    data = client.get(f"issue/{args.key}")
    emit(
        data if args.json else simplify_issue(data),
        args,
        human=f"{data['key']}: {data['fields'].get('summary', '')} "
              f"[{(data['fields'].get('status') or {}).get('name', '?')}]"
    )


def cmd_create(args):
    fields = {
        "project": {"key": args.project},
        "summary": args.summary,
        "issuetype": {"name": args.type},
    }
    if args.description:
        fields["description"] = args.description
    if args.priority:
        fields["priority"] = {"name": args.priority}
    if args.assignee:
        fields["assignee"] = {"name": args.assignee}
    if args.label:
        fields["labels"] = args.label
    if args.fix_version:
        fields["fixVersions"] = [{"name": v} for v in args.fix_version]
    if args.parent:
        fields["parent"] = {"key": args.parent}
    body = {"fields": fields}

    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/2/issue", "body": body},
            args,
            human=f"would create {args.type} in {args.project}: {args.summary!r}",
        )
        return

    client = get_jira(args)
    data = client.post("issue", body)
    emit(data, args, human=f"created {data.get('key')}")


def cmd_update(args):
    fields: dict = {}
    if args.summary is not None:
        fields["summary"] = args.summary
    if args.description is not None:
        fields["description"] = args.description
    if args.priority is not None:
        fields["priority"] = {"name": args.priority}
    if args.assignee is not None:
        # Empty string → unassign (set to None)
        fields["assignee"] = {"name": args.assignee} if args.assignee else None
    if args.fix_version is not None:
        # Note: this REPLACES the list. Empty arg list clears it.
        fields["fixVersions"] = [{"name": v} for v in args.fix_version]
    if not fields:
        raise ValidationError("no field given to update")
    body = {"fields": fields}

    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/2/issue/{args.key}", "body": body},
            args,
            human=f"would update {args.key} fields: {', '.join(fields.keys())}",
        )
        return

    client = get_jira(args)
    client.put(f"issue/{args.key}", body)
    emit({"updated": args.key}, args, human=f"updated {args.key}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/2/issue/{args.key}"},
            args,
            human=f"would delete issue {args.key}",
        )
        return
    client = get_jira(args)
    client.delete(f"issue/{args.key}")
    emit({"deleted": args.key}, args, human=f"deleted {args.key}")


def main():
    p = argparse.ArgumentParser(description="Jira issue CRUD")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="fetch an issue")
    g.add_argument("key")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create an issue")
    c.add_argument("--project", required=True, help="project key")
    c.add_argument("--type", required=True, help="issue type name (Bug, Task, ...)")
    c.add_argument("--summary", required=True)
    c.add_argument("--description")
    c.add_argument("--priority")
    c.add_argument("--assignee", help="username")
    c.add_argument("--label", action="append", default=[])
    c.add_argument("--fix-version", action="append", default=[],
                   help="fixVersion name (repeat for multiple)")
    c.add_argument("--parent", help="parent issue key (for Sub-task type)")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    u = sub.add_parser("update", help="update fields on an issue")
    u.add_argument("key")
    u.add_argument("--summary")
    u.add_argument("--description")
    u.add_argument("--priority")
    u.add_argument("--assignee", help="empty string '' unassigns")
    u.add_argument("--fix-version", action="append",
                   help="REPLACES the fixVersions list (repeat). Pass once with empty to clear.")
    add_common_args(u)
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("delete", help="delete an issue")
    d.add_argument("key")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
