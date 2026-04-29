#!/usr/bin/env python3
"""Confluence page restrictions: get, set-user, set-group, clear.

Restrictions limit who can read or edit a page. Two operations: `read` and
`update`. Each can be granted to specific users and/or groups.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    add_common_args, emit, emit_dry_run, run, ValidationError,
)
from _confluence import get_confluence  # noqa: E402


OPERATIONS = ("read", "update")


def cmd_get(args):
    client = get_confluence(args)
    data = client.get(f"content/{args.id}/restriction", params={"expand": "restrictions.user,restrictions.group"})
    if args.json:
        emit(data, args)
        return
    out = []
    for entry in data.get("results", []):
        op = entry.get("operation")
        users = [u.get("username") or u.get("displayName") for u in
                 (entry.get("restrictions", {}).get("user", {}).get("results") or [])]
        groups = [g.get("name") for g in
                  (entry.get("restrictions", {}).get("group", {}).get("results") or [])]
        line = f"{op:<8} users={users or '∅'} groups={groups or '∅'}"
        out.append(line)
    emit(data, args, human="\n".join(out) or f"no restrictions on {args.id}")


def _build_payload(operation: str, users: list[str], groups: list[str]) -> list[dict]:
    return [{
        "operation": operation,
        "restrictions": {
            "user":  {"results": [{"type": "known", "username": u} for u in users]},
            "group": {"results": [{"type": "group", "name": g} for g in groups]},
        },
    }]


def cmd_set(args):
    if args.operation not in OPERATIONS:
        raise ValidationError(f"operation must be one of {OPERATIONS}")
    if not args.user and not args.group:
        raise ValidationError("provide at least one --user or --group")
    payload = _build_payload(args.operation, args.user or [], args.group or [])
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/content/{args.id}/restriction",
             "body": payload},
            args,
            human=f"would set {args.operation} restriction on {args.id} "
                  f"users={args.user or '∅'} groups={args.group or '∅'}",
        )
        return
    client = get_confluence(args)
    data = client.put(f"content/{args.id}/restriction", payload)
    emit(data, args, human=f"set {args.operation} restriction on {args.id}")


def cmd_clear(args):
    """Remove all restrictions for an operation (or all)."""
    if args.dry_run:
        path = (f"/rest/api/content/{args.id}/restriction/byOperation/{args.operation}"
                if args.operation else f"/rest/api/content/{args.id}/restriction")
        emit_dry_run(
            {"method": "DELETE", "path": path},
            args,
            human=f"would clear {args.operation or 'all'} restrictions on {args.id}",
        )
        return
    client = get_confluence(args)
    if args.operation:
        client.delete(f"content/{args.id}/restriction/byOperation/{args.operation}")
    else:
        client.delete(f"content/{args.id}/restriction")
    emit({"cleared": args.operation or "all", "page": args.id}, args,
         human=f"cleared {args.operation or 'all'} restrictions on {args.id}")


def main():
    p = argparse.ArgumentParser(description="Confluence page restrictions")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="show restrictions on a page")
    g.add_argument("id", help="page id")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("set", help="set users/groups for an operation")
    s.add_argument("id", help="page id")
    s.add_argument("--operation", required=True, choices=OPERATIONS)
    s.add_argument("--user", action="append", help="username (repeat for multiple)")
    s.add_argument("--group", action="append", help="group name (repeat for multiple)")
    add_common_args(s)
    s.set_defaults(func=cmd_set)

    c = sub.add_parser("clear", help="remove restrictions")
    c.add_argument("id", help="page id")
    c.add_argument("--operation", choices=OPERATIONS,
                   help="clear only this operation; omit to clear all")
    add_common_args(c)
    c.set_defaults(func=cmd_clear)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
