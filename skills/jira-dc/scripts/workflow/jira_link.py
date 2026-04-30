#!/usr/bin/env python3
"""Issue links — between issues (blocks/relates/etc.) and to epics."""

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import (  # noqa: E402
    add_common_args,
    emit,
    emit_dry_run,
    run,
    ValidationError,
    NotFoundError,
)
from _jira import get_jira  # noqa: E402

# Epic Link is a custom field. The id varies per Jira; default for typical
# DC installs is customfield_10008. We auto-discover when --epic-field is not
# given by querying /rest/api/2/field.
DEFAULT_EPIC_FIELD = "customfield_10008"


def _resolve_epic_field(client, override: Optional[str]) -> str:
    if override:
        return override
    try:
        for f in client.get("field"):
            if f.get("name") == "Epic Link":
                return f["id"]
    except Exception:
        pass
    return DEFAULT_EPIC_FIELD


def cmd_types(args):
    client = get_jira(args)
    data = client.get("issueLinkType")
    types = data.get("issueLinkTypes", [])
    if args.json:
        emit(data, args)
        return
    lines = [f"{t.get('id'):<6} {t.get('name'):<20} inward={t.get('inward'):<20} outward={t.get('outward')}"
             for t in types]
    emit(types, args, human="\n".join(lines) + f"\n\n{len(types)} link type(s)")


def cmd_add(args):
    body = {
        "type": {"name": args.type},
        "inwardIssue": {"key": args.inward},
        "outwardIssue": {"key": args.outward},
    }
    if args.comment:
        body["comment"] = {"body": args.comment}
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/2/issueLink", "body": body},
            args,
            human=f"would link {args.outward} -> [{args.type}] -> {args.inward}",
        )
        return
    client = get_jira(args)
    client.post("issueLink", body)
    emit({"linked": True, "type": args.type,
          "outward": args.outward, "inward": args.inward}, args,
         human=f"linked {args.outward} ({args.type}) {args.inward}")


def cmd_remove(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/2/issueLink/{args.id}"},
            args,
            human=f"would remove link {args.id}",
        )
        return
    client = get_jira(args)
    client.delete(f"issueLink/{args.id}")
    emit({"removed": args.id}, args, human=f"removed link {args.id}")


def cmd_link_epic(args):
    client = get_jira(args)
    field = _resolve_epic_field(client, args.epic_field)
    body = {"fields": {field: args.epic}}
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/2/issue/{args.key}", "body": body,
             "epic_field": field},
            args,
            human=f"would set Epic Link of {args.key} to {args.epic} (field={field})",
        )
        return
    client.put(f"issue/{args.key}", body)
    emit({"key": args.key, "epic": args.epic, "field": field}, args,
         human=f"linked {args.key} to epic {args.epic}")


def cmd_unlink_epic(args):
    client = get_jira(args)
    field = _resolve_epic_field(client, args.epic_field)
    body = {"fields": {field: None}}
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/2/issue/{args.key}", "body": body,
             "epic_field": field},
            args,
            human=f"would remove Epic Link from {args.key}",
        )
        return
    client.put(f"issue/{args.key}", body)
    emit({"key": args.key, "field": field, "epic": None}, args,
         human=f"removed epic link from {args.key}")


def main():
    p = argparse.ArgumentParser(description="Jira issue links")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    t = sub.add_parser("types", help="list available link types")
    add_common_args(t)
    t.set_defaults(func=cmd_types)

    a = sub.add_parser("add", help="link two issues")
    a.add_argument("--type", required=True, help="link type name (Blocks, Relates, ...)")
    a.add_argument("--outward", required=True, help="key of the outward issue (the source)")
    a.add_argument("--inward", required=True, help="key of the inward issue (the target)")
    a.add_argument("--comment", help="optional comment added to outward issue")
    add_common_args(a)
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("remove", help="remove a link by id")
    r.add_argument("id")
    add_common_args(r)
    r.set_defaults(func=cmd_remove)

    le = sub.add_parser("link-epic", help="set the Epic Link of an issue")
    le.add_argument("key", help="issue key (the child)")
    le.add_argument("--epic", required=True, help="epic key")
    le.add_argument("--epic-field", help="override Epic Link customfield id")
    add_common_args(le)
    le.set_defaults(func=cmd_link_epic)

    ue = sub.add_parser("unlink-epic", help="clear Epic Link of an issue")
    ue.add_argument("key")
    ue.add_argument("--epic-field", help="override Epic Link customfield id")
    add_common_args(ue)
    ue.set_defaults(func=cmd_unlink_epic)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
