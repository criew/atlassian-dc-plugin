#!/usr/bin/env python3
"""Issue attachments — list, add, get metadata, delete."""

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
    issue = client.get(f"issue/{args.key}", params={"fields": "attachment"})
    atts = (issue.get("fields") or {}).get("attachment") or []
    if args.json:
        emit(atts, args)
        return
    if not atts:
        emit([], args, human=f"no attachments on {args.key}")
        return
    lines = [f"{a.get('id'):<8} {a.get('filename'):<30} {a.get('size'):>10}  {(a.get('author') or {}).get('name')}"
             for a in atts]
    emit(atts, args, human="\n".join(lines) + f"\n\n{len(atts)} attachment(s) on {args.key}")


def cmd_add(args):
    p = Path(args.file)
    if not p.exists():
        raise ValidationError(f"file not found: {p}")
    if not p.is_file():
        raise ValidationError(f"not a file: {p}")

    if args.dry_run:
        emit_dry_run(
            {
                "method": "POST",
                "path": f"/rest/api/2/issue/{args.key}/attachments",
                "multipart_file": str(p),
                "size_bytes": p.stat().st_size,
            },
            args,
            human=f"would attach {p.name} ({p.stat().st_size} bytes) to {args.key}",
        )
        return

    client = get_jira(args)
    # For multipart we must NOT pre-set Content-Type — requests computes the
    # boundary itself. Build the request bypassing the JSON-defaulted session.
    import requests
    url = f"{client.instance.url}/rest/api/2/issue/{args.key}/attachments"
    headers = {
        "Authorization": f"Bearer {client.instance.token}",
        "X-Atlassian-Token": "no-check",
        "Accept": "application/json",
    }
    with p.open("rb") as fh:
        resp = requests.post(
            url,
            files={"file": (p.name, fh)},
            headers=headers,
            timeout=120,
            verify=client.instance.ssl_verify,
        )
    client._handle(resp)
    data = resp.json()
    if isinstance(data, list) and data:
        first = data[0]
        emit(data, args,
             human=f"attached {first.get('filename')} (id={first.get('id')}) to {args.key}")
    else:
        emit(data, args, human=f"attached {p.name} to {args.key}")


def cmd_get(args):
    client = get_jira(args)
    data = client.get(f"attachment/{args.id}")
    emit(data, args,
         human=f"{data.get('filename')} (id={data.get('id')}) size={data.get('size')} "
               f"author={(data.get('author') or {}).get('name')} url={data.get('content')}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/2/attachment/{args.id}"},
            args,
            human=f"would delete attachment {args.id}",
        )
        return
    client = get_jira(args)
    client.delete(f"attachment/{args.id}")
    emit({"deleted": args.id}, args, human=f"deleted attachment {args.id}")


def main():
    p = argparse.ArgumentParser(description="Jira issue attachments")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list attachments on an issue")
    ls.add_argument("key")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="upload a file as attachment")
    a.add_argument("key")
    a.add_argument("--file", required=True, help="path to local file")
    add_common_args(a)
    a.set_defaults(func=cmd_add)

    g = sub.add_parser("get", help="get attachment metadata by id")
    g.add_argument("id")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    d = sub.add_parser("delete", help="delete an attachment by id")
    d.add_argument("id")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
