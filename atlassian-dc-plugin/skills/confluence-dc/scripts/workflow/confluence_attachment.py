#!/usr/bin/env python3
"""Page attachments: list, add (multipart), get, delete."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, emit_dry_run, run, ValidationError  # noqa: E402
from _confluence import get_confluence  # noqa: E402


def cmd_list(args):
    client = get_confluence(args)
    params: dict = {"expand": "version,container"}
    if args.filename:
        params["filename"] = args.filename
    data = client.get(f"content/{args.id}/child/attachment", params=params)
    atts = (data or {}).get("results", [])
    if args.json:
        emit(data, args)
        return
    if not atts:
        emit([], args, human=f"no attachments on page {args.id}")
        return
    lines = []
    for a in atts:
        meta = a.get("metadata") or {}
        size = (meta.get("mediaType"), (a.get("extensions") or {}).get("fileSize"))
        lines.append(f"{a.get('id'):<12} {a.get('title'):<30} {size[1] if size[1] is not None else ''}")
    emit(atts, args, human="\n".join(lines) + f"\n\n{len(atts)} attachment(s) on page {args.id}")


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
                "path": f"/rest/api/content/{args.id}/child/attachment",
                "multipart_file": str(p),
                "size_bytes": p.stat().st_size,
                "comment": args.comment,
            },
            args,
            human=f"would attach {p.name} ({p.stat().st_size} bytes) to page {args.id}",
        )
        return

    client = get_confluence(args)

    # Multipart: do NOT pre-set Content-Type (requests sets the boundary).
    # X-Atlassian-Token: no-check is mandatory for Confluence file uploads.
    import requests
    url = f"{client.instance.url}/rest/api/content/{args.id}/child/attachment"
    headers = {
        "Authorization": f"Bearer {client.instance.token}",
        "X-Atlassian-Token": "no-check",
        "Accept": "application/json",
    }
    files = {"file": (p.name, None)}
    data_fields = {}
    if args.comment:
        data_fields["comment"] = args.comment
    with p.open("rb") as fh:
        files = {"file": (p.name, fh)}
        resp = requests.post(
            url,
            files=files,
            data=data_fields or None,
            headers=headers,
            timeout=120,
            verify=client.instance.ssl_verify,
        )
    client._handle(resp)
    data = resp.json()
    if isinstance(data, dict) and data.get("results"):
        first = data["results"][0]
        emit(data, args,
             human=f"attached {first.get('title')} (id={first.get('id')}) to page {args.id}")
    else:
        emit(data, args, human=f"attached {p.name} to page {args.id}")


def cmd_get(args):
    client = get_confluence(args)
    data = client.get(f"content/{args.attachment_id}", params={"expand": "version,container"})
    title = data.get("title")
    container = ((data.get("container") or {}).get("id")) or "?"
    emit(data, args,
         human=f"{title} (id={data.get('id')}) container_page={container} "
               f"version={(data.get('version') or {}).get('number')}")


def cmd_delete(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/content/{args.attachment_id}"},
            args,
            human=f"would delete attachment {args.attachment_id}",
        )
        return
    client = get_confluence(args)
    client.delete(f"content/{args.attachment_id}")
    emit({"deleted": args.attachment_id}, args,
         human=f"deleted attachment {args.attachment_id}")


def main():
    p = argparse.ArgumentParser(description="Confluence page attachments")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list attachments on a page")
    ls.add_argument("id", help="page id")
    ls.add_argument("--filename", help="filter by filename")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="upload a file as attachment")
    a.add_argument("id", help="page id")
    a.add_argument("--file", required=True, help="path to local file")
    a.add_argument("--comment", help="optional comment for the upload")
    add_common_args(a)
    a.set_defaults(func=cmd_add)

    g = sub.add_parser("get", help="attachment metadata by id")
    g.add_argument("attachment_id")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    d = sub.add_parser("delete", help="delete an attachment by id")
    d.add_argument("attachment_id")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
