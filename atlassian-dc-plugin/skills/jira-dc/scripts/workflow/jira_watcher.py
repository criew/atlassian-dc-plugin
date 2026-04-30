#!/usr/bin/env python3
"""Issue watchers — list, add (subscribe), remove (unsubscribe).

Common workflow: subscribe yourself to an issue → `add KEY --user $(whoami)`.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    add_common_args, get_jira, emit, emit_dry_run, run, ValidationError,
)


def cmd_list(args):
    client = get_jira(args)
    data = client.get(f"issue/{args.key}/watchers")
    watchers = data.get("watchers", [])
    if args.json:
        emit(data, args)
        return
    if not watchers:
        emit({"watchers": [], "watchCount": data.get("watchCount", 0)}, args,
             human=f"no watchers on {args.key}")
        return
    lines = [f"{w.get('name'):<20} {w.get('displayName'):<25} <{w.get('emailAddress', '')}>"
             for w in watchers]
    emit(watchers, args,
         human="\n".join(lines) + f"\n\n{len(watchers)} watcher(s) on {args.key}")


def cmd_add(args):
    """Subscribe a user to an issue.

    Jira's POST body for this endpoint is the username as a JSON STRING (not
    an object). With omitted user it subscribes the authenticated PAT owner.
    """
    if args.user is None:
        # Resolve current user (the PAT owner) so the action is visible.
        client = get_jira(args)
        me = client.get("myself")
        target = me.get("name")
    else:
        target = args.user

    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/2/issue/{args.key}/watchers",
             "body_string": target},
            args,
            human=f"would add {target} as watcher of {args.key}",
        )
        return

    client = get_jira(args)
    # Manually post a JSON string body — JiraClient.post accepts dict, so use raw.
    url = client._url(f"issue/{args.key}/watchers")
    resp = client.session.post(
        url, data=f'"{target}"',
        headers={"Content-Type": "application/json", "X-Atlassian-Token": "no-check"},
        timeout=30, verify=client.instance.ssl_verify,
    )
    client._handle(resp)
    emit({"key": args.key, "added": target}, args,
         human=f"added {target} as watcher of {args.key}")


def cmd_remove(args):
    if not args.user:
        # Resolve current user as default
        client = get_jira(args)
        target = client.get("myself").get("name")
    else:
        target = args.user

    path = f"issue/{args.key}/watchers?username={target}"
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/2/{path}"},
            args,
            human=f"would remove {target} from watchers of {args.key}",
        )
        return
    client = get_jira(args)
    client.delete(path)
    emit({"key": args.key, "removed": target}, args,
         human=f"removed {target} from watchers of {args.key}")


def main():
    p = argparse.ArgumentParser(description="Jira issue watchers")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list watchers of an issue")
    ls.add_argument("key")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="subscribe a user (default: yourself) to an issue")
    a.add_argument("key")
    a.add_argument("--user", help="username; omit to use the PAT owner")
    add_common_args(a)
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("remove", help="unsubscribe a user (default: yourself)")
    r.add_argument("key")
    r.add_argument("--user", help="username; omit to use the PAT owner")
    add_common_args(r)
    r.set_defaults(func=cmd_remove)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
