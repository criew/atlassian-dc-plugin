#!/usr/bin/env python3
"""Bitbucket repository webhooks: list, get, create, update, delete, test.

Webhooks are scoped to a single repository. Common events:
  repo:refs_changed  pr:opened  pr:merged  pr:declined  pr:comment:added
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    add_common_args, emit, emit_dry_run, run, ValidationError,
)
from _bitbucket import get_bitbucket  # noqa: E402


def _path(args, suffix: str = "") -> str:
    return f"projects/{args.project}/repos/{args.repo}/webhooks{suffix}"


def cmd_list(args):
    client = get_bitbucket(args)
    items = client.paginate(_path(args), limit=args.limit)
    if args.json:
        emit({"size": len(items), "values": items}, args)
        return
    if not items:
        emit([], args, human=f"no webhooks on {args.project}/{args.repo}")
        return
    lines = []
    for w in items:
        active = "ON" if w.get("active") else "off"
        events = ",".join(w.get("events", []))
        lines.append(f"{w.get('id'):<6} {active:<3} {w.get('name'):<25} {w.get('url')} [{events}]")
    emit(items, args, human="\n".join(lines) + f"\n\n{len(items)} webhook(s)")


def cmd_get(args):
    client = get_bitbucket(args)
    data = client.get(_path(args, f"/{args.id}"))
    emit(data, args, human=f"{data.get('id')} {data.get('name')} -> {data.get('url')} "
                           f"events={data.get('events')}")


def _make_body(args) -> dict:
    body = {
        "name": args.name,
        "url": args.url,
        "events": args.event,
        "active": args.active.lower() == "true" if args.active else True,
    }
    if args.secret:
        body["configuration"] = {"secret": args.secret}
    return body


def cmd_create(args):
    if not args.event:
        raise ValidationError("at least one --event is required")
    body = _make_body(args)
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/1.0/" + _path(args), "body": body},
            args,
            human=f"would create webhook {args.name!r} -> {args.url} on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    data = client.post(_path(args), body)
    emit(data, args, human=f"created webhook {data.get('id')} ({data.get('name')})")


def cmd_update(args):
    body = _make_body(args)
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": "/rest/api/1.0/" + _path(args, f"/{args.id}"), "body": body},
            args,
            human=f"would update webhook {args.id} on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    data = client.put(_path(args, f"/{args.id}"), body)
    emit(data, args, human=f"updated webhook {args.id}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": "/rest/api/1.0/" + _path(args, f"/{args.id}")},
            args,
            human=f"would delete webhook {args.id} on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    client.delete(_path(args, f"/{args.id}"))
    emit({"deleted": args.id}, args, human=f"deleted webhook {args.id}")


def cmd_test(args):
    """Trigger a test ping of the webhook URL."""
    body: dict = {"url": args.url} if args.url else {}
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/1.0/" + _path(args, "/test"), "body": body},
            args,
            human=f"would test-ping webhook on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    data = client.post(_path(args, "/test"), body)
    emit(data, args, human=f"test ping result: {data}")


def main():
    p = argparse.ArgumentParser(description="Bitbucket repo webhooks")
    sub = p.add_subparsers(dest="cmd", required=True)

    common_repo = ["--project", "--repo"]

    def repo_args(parser):
        parser.add_argument("--project", required=True)
        parser.add_argument("--repo", required=True)

    ls = sub.add_parser("list", help="list webhooks of a repo")
    repo_args(ls)
    ls.add_argument("--limit", type=int, default=50)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="get webhook by id")
    repo_args(g)
    g.add_argument("id")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create a webhook")
    repo_args(c)
    c.add_argument("--name", required=True)
    c.add_argument("--url", required=True, help="target URL receiving the event POST")
    c.add_argument("--event", action="append", required=True,
                   help="event id (repeat); e.g. repo:refs_changed pr:opened pr:merged")
    c.add_argument("--secret", help="HMAC secret for signed payloads")
    c.add_argument("--active", default="true", choices=["true", "false"])
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    u = sub.add_parser("update", help="update an existing webhook")
    repo_args(u)
    u.add_argument("id")
    u.add_argument("--name", required=True)
    u.add_argument("--url", required=True)
    u.add_argument("--event", action="append", required=True)
    u.add_argument("--secret")
    u.add_argument("--active", choices=["true", "false"])
    add_common_args(u)
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("delete", help="delete a webhook")
    repo_args(d)
    d.add_argument("id")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    t = sub.add_parser("test", help="trigger a test ping")
    repo_args(t)
    t.add_argument("--url", help="optional override URL to ping (default: stored url)")
    add_common_args(t)
    t.set_defaults(func=cmd_test)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
