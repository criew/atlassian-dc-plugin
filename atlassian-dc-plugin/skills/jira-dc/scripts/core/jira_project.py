#!/usr/bin/env python3
"""Jira project operations: list, get, create."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, get_jira, emit, emit_dry_run, run  # noqa: E402


# Common project type templates for Jira DC
TEMPLATES = {
    "software": "com.pyxis.greenhopper.jira:gh-scrum-template",
    "kanban": "com.pyxis.greenhopper.jira:gh-kanban-template",
    "business": "com.atlassian.jira-core-project-templates:jira-core-project-management",
    "basic": "com.atlassian.jira-core-project-templates:jira-core-simplified-task-tracking",
}


def cmd_list(args):
    client = get_jira(args)
    data = client.get("project")
    if args.json:
        emit(data, args)
        return
    lines = [f"{p['key']:<12} {p['name']}  (id={p['id']})" for p in data]
    emit(data, args, human="\n".join(lines) + f"\n\n{len(data)} project(s)")


def cmd_get(args):
    client = get_jira(args)
    data = client.get(f"project/{args.key}")
    emit(data, args, human=f"{data['key']}: {data['name']} (lead={data.get('lead', {}).get('name')})")


def cmd_create(args):
    type_key = args.type or "software"
    body = {
        "key": args.key,
        "name": args.name,
        "projectTypeKey": "software" if type_key in ("software", "kanban") else "business",
        "lead": args.lead,
    }
    template = args.template or TEMPLATES.get(type_key)
    if template:
        body["projectTemplateKey"] = template
    if args.description:
        body["description"] = args.description
    if args.url:
        body["url"] = args.url
    if args.assignee_type:
        body["assigneeType"] = args.assignee_type

    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/2/project", "body": body},
            args,
            human=f"would create project {args.key} ({args.name})",
        )
        return

    client = get_jira(args)
    data = client.post("project", body)
    emit(data, args, human=f"created project {data.get('key', args.key)} (id={data.get('id')})")


def main():
    p = argparse.ArgumentParser(description="Jira project operations")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list all projects")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="fetch project details")
    g.add_argument("key")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create a new project")
    c.add_argument("--key", required=True, help="project key (e.g. TEST)")
    c.add_argument("--name", required=True)
    c.add_argument("--lead", required=True, help="username of project lead")
    c.add_argument("--type", choices=list(TEMPLATES.keys()), help="project flavor")
    c.add_argument("--template", help="exact projectTemplateKey (overrides --type)")
    c.add_argument("--description")
    c.add_argument("--url")
    c.add_argument("--assignee-type", choices=["PROJECT_LEAD", "UNASSIGNED"])
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
