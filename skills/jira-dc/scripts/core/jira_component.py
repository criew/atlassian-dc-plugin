#!/usr/bin/env python3
"""Jira project components: list, get, create, update, delete."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import (  # noqa: E402
    add_common_args,
    emit,
    emit_dry_run,
    run,
    ValidationError,
)
from _jira import get_jira  # noqa: E402


def cmd_list(args):
    client = get_jira(args)
    data = client.get(f"project/{args.project}/components")
    if args.json:
        emit(data, args)
        return
    if not data:
        emit(data, args, human=f"no components in {args.project}")
        return
    lines = []
    for c in data:
        lead = (c.get("lead") or {}).get("name", "")
        lines.append(f"{c.get('id'):<8} {c.get('name'):<25} lead={lead}")
    emit(data, args, human="\n".join(lines) + f"\n\n{len(data)} component(s)")


def cmd_get(args):
    client = get_jira(args)
    data = client.get(f"component/{args.id}")
    emit(data, args, human=f"{data.get('id')} {data.get('name')} "
                           f"(project={data.get('project')}, lead={(data.get('lead') or {}).get('name')})")


def cmd_create(args):
    body = {"name": args.name, "project": args.project}
    if args.description:
        body["description"] = args.description
    if args.lead:
        body["leadUserName"] = args.lead
    if args.assignee_type:
        body["assigneeType"] = args.assignee_type
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/2/component", "body": body},
            args,
            human=f"would create component {args.name!r} in {args.project}",
        )
        return
    client = get_jira(args)
    data = client.post("component", body)
    emit(data, args, human=f"created component {data.get('name')} (id={data.get('id')})")


def cmd_update(args):
    body: dict = {}
    if args.name is not None:
        body["name"] = args.name
    if args.description is not None:
        body["description"] = args.description
    if args.lead is not None:
        body["leadUserName"] = args.lead
    if args.assignee_type is not None:
        body["assigneeType"] = args.assignee_type
    if not body:
        raise ValidationError("no field given to update")
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/2/component/{args.id}", "body": body},
            args,
            human=f"would update component {args.id} fields: {', '.join(body.keys())}",
        )
        return
    client = get_jira(args)
    data = client.put(f"component/{args.id}", body)
    emit(data, args, human=f"updated component {args.id}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/2/component/{args.id}"},
            args,
            human=f"would delete component {args.id}",
        )
        return
    client = get_jira(args)
    client.delete(f"component/{args.id}")
    emit({"deleted": args.id}, args, human=f"deleted component {args.id}")


def main():
    p = argparse.ArgumentParser(description="Jira project components")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list components of a project")
    ls.add_argument("--project", required=True)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="get component details")
    g.add_argument("id")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create a component")
    c.add_argument("--project", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--description")
    c.add_argument("--lead", help="username of component lead")
    c.add_argument("--assignee-type",
                   choices=["PROJECT_DEFAULT", "COMPONENT_LEAD", "PROJECT_LEAD", "UNASSIGNED"])
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    u = sub.add_parser("update", help="update an existing component")
    u.add_argument("id")
    u.add_argument("--name")
    u.add_argument("--description")
    u.add_argument("--lead")
    u.add_argument("--assignee-type")
    add_common_args(u)
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("delete", help="delete a component")
    d.add_argument("id")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
