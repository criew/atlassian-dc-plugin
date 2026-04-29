#!/usr/bin/env python3
"""Issue workflow transitions: list available, perform transition by name or id."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, get_jira, emit, emit_dry_run, run, ValidationError, NotFoundError  # noqa: E402


def cmd_list(args):
    client = get_jira(args)
    data = client.get(f"issue/{args.key}/transitions")
    transitions = data.get("transitions", [])
    if args.json:
        emit(data, args)
        return
    lines = [f"{t['id']:<6} {t['name']:<20} -> {t['to']['name']}" for t in transitions]
    emit(transitions, args, human="\n".join(lines) or "no transitions available")


def cmd_do(args):
    client = get_jira(args)

    # Resolve transition: id or name
    transition_id = args.to if args.to.isdigit() else None
    if not transition_id:
        avail = client.get(f"issue/{args.key}/transitions").get("transitions", [])
        for t in avail:
            if t["name"].lower() == args.to.lower() or t["to"]["name"].lower() == args.to.lower():
                transition_id = t["id"]
                break
        if not transition_id:
            names = ", ".join(f"{t['name']} -> {t['to']['name']}" for t in avail)
            raise NotFoundError(f"transition '{args.to}' not available on {args.key}. "
                                f"Available: {names or '(none)'}")

    body = {"transition": {"id": transition_id}}
    if args.comment:
        body["update"] = {"comment": [{"add": {"body": args.comment}}]}

    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/2/issue/{args.key}/transitions", "body": body},
            args,
            human=f"would transition {args.key} via transition id {transition_id}",
        )
        return

    client.post(f"issue/{args.key}/transitions", body)
    emit({"transitioned": args.key, "transition_id": transition_id}, args,
         human=f"transitioned {args.key} via {transition_id}")


def main():
    p = argparse.ArgumentParser(description="Jira workflow transitions")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="show available transitions for an issue")
    ls.add_argument("key")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    do = sub.add_parser("do", help="perform a transition")
    do.add_argument("key")
    do.add_argument("--to", required=True, help="transition id, transition name, or target status name")
    do.add_argument("--comment", help="add a comment with the transition")
    add_common_args(do)
    do.set_defaults(func=cmd_do)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
