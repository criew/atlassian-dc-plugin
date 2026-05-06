#!/usr/bin/env python3
"""Issue worklogs: list, add, update, delete."""

import argparse
import re
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


_UNITS = {"w": 7 * 24 * 3600, "d": 24 * 3600, "h": 3600, "m": 60, "s": 1}


def _normalize_jira_timestamp(ts: str) -> str:
    """Normalize ISO 8601 timestamp to Jira DC format (milliseconds, no colon in tz)."""
    # Add milliseconds if missing
    if re.match(r".*T\d{2}:\d{2}:\d{2}[+\-Z]", ts):
        ts = re.sub(r"(T\d{2}:\d{2}:\d{2})([+\-Z])", r"\1.000\2", ts)
    # Remove colon from timezone offset: +02:00 -> +0200
    ts = re.sub(r"([+\-]\d{2}):(\d{2})$", r"\1\2", ts)
    return ts


def parse_time_spent(s: str) -> int:
    """Parse '1w 2d 3h 30m' style strings into seconds."""
    if not s or not s.strip():
        raise ValidationError("time_spent is required")
    s = s.strip().lower()
    total = 0
    for value, unit in re.findall(r"(\d+)\s*([wdhms])", s):
        total += int(value) * _UNITS[unit]
    if total == 0:
        raise ValidationError(
            f"invalid time format: {s!r}. Use '1h 30m', '2d', '1w', '45m', or seconds with 's'."
        )
    return total


def cmd_list(args):
    client = get_jira(args)
    data = client.get(f"issue/{args.key}/worklog")
    worklogs = data.get("worklogs", [])
    if args.json:
        emit(data, args)
        return
    if not worklogs:
        emit({"worklogs": []}, args, human=f"no worklogs on {args.key}")
        return
    lines = []
    for w in worklogs:
        author = (w.get("author") or {}).get("name", "?")
        when = w.get("started", "")[:10]
        spent = w.get("timeSpent", "?")
        body = (w.get("comment") or "").strip()
        lines.append(f"{w.get('id'):<8} {when} {author:<15} {spent:<12} {body}")
    emit(worklogs, args,
         human="\n".join(lines) + f"\n\n{len(worklogs)} worklog(s)")


def cmd_add(args):
    seconds = parse_time_spent(args.time_spent)
    body: dict = {"timeSpentSeconds": seconds}
    if args.comment:
        body["comment"] = args.comment
    if args.started:
        body["started"] = _normalize_jira_timestamp(args.started)

    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/2/issue/{args.key}/worklog", "body": body},
            args,
            human=f"would log {args.time_spent} on {args.key}",
        )
        return
    client = get_jira(args)
    data = client.post(f"issue/{args.key}/worklog", body)
    emit(data, args, human=f"logged {data.get('timeSpent')} on {args.key} (id={data.get('id')})")


def cmd_update(args):
    body: dict = {}
    if args.time_spent is not None:
        body["timeSpentSeconds"] = parse_time_spent(args.time_spent)
    if args.comment is not None:
        body["comment"] = args.comment
    if not body:
        raise ValidationError("no field to update (--time-spent or --comment required)")
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/2/issue/{args.key}/worklog/{args.id}", "body": body},
            args,
            human=f"would update worklog {args.id} on {args.key}",
        )
        return
    client = get_jira(args)
    data = client.put(f"issue/{args.key}/worklog/{args.id}", body)
    emit(data, args, human=f"updated worklog {args.id} on {args.key}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/2/issue/{args.key}/worklog/{args.id}"},
            args,
            human=f"would delete worklog {args.id} on {args.key}",
        )
        return
    client = get_jira(args)
    client.delete(f"issue/{args.key}/worklog/{args.id}")
    emit({"deleted": args.id, "issue": args.key}, args,
         human=f"deleted worklog {args.id} on {args.key}")


def main():
    p = argparse.ArgumentParser(description="Jira issue worklogs")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list worklogs of an issue")
    ls.add_argument("key")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="log work")
    a.add_argument("key")
    a.add_argument("--time-spent", required=True, help="e.g. '2h 30m', '1d', '1w'")
    a.add_argument("--comment")
    a.add_argument("--started", help="ISO 8601 timestamp; default: now")
    add_common_args(a)
    a.set_defaults(func=cmd_add)

    u = sub.add_parser("update", help="update an existing worklog")
    u.add_argument("key")
    u.add_argument("id")
    u.add_argument("--time-spent")
    u.add_argument("--comment")
    add_common_args(u)
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("delete", help="delete a worklog")
    d.add_argument("key")
    d.add_argument("id")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
