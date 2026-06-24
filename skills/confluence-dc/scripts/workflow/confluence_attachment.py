#!/usr/bin/env python3
"""Page attachments: list, add (multipart), get, delete."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import (  # noqa: E402
    add_common_args,
    APIError,
    emit,
    emit_dry_run,
    run,
    ValidationError,
)
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


def cmd_download(args):
    import os

    client = get_confluence(args)
    meta = client.get(
        f"content/{args.attachment_id}",
        params={"expand": "version,container"},
    )
    title = meta.get("title") or args.attachment_id
    links = meta.get("_links") or {}
    download_path = links.get("download")
    if not download_path:
        raise ValidationError(
            f"{args.attachment_id} has no download link "
            f"(is it really an attachment? type={meta.get('type')})"
        )

    # _links.download is a server-relative path (e.g.
    # /download/attachments/<pageId>/<file>?version=1&...), not under /rest/api.
    base = links.get("base") or client.instance.url
    url = f"{base}{download_path}"

    # Resolve the output destination. --output may be a file or a directory.
    out = Path(args.output) if args.output else Path(title)
    if out.is_dir() or args.output in (".", "./"):
        out = out / title
    if out.exists() and not args.force:
        raise ValidationError(
            f"refusing to overwrite existing file: {out} (use --force)"
        )

    if args.dry_run:
        emit_dry_run(
            {"method": "GET", "url": url, "output": str(out)},
            args,
            human=f"would download {title} to {out}",
        )
        return

    import requests
    headers = {"Authorization": f"Bearer {client.instance.token}"}
    with requests.get(
        url,
        headers=headers,
        stream=True,
        timeout=120,
        verify=client.instance.ssl_verify,
    ) as resp:
        if resp.status_code >= 400:
            # Map to AuthError/NotFoundError/etc. via the shared handler.
            client._handle(resp)
        tmp = out.with_name(out.name + ".part")
        total = 0
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
                    total += len(chunk)
        os.replace(tmp, out)

    emit(
        {"downloaded": str(out), "bytes": total, "attachment_id": args.attachment_id,
         "title": title},
        args,
        human=f"downloaded {title} ({total} bytes) to {out}",
    )


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
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

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

    dl = sub.add_parser("download", help="download attachment binary content to a file")
    dl.add_argument("attachment_id")
    dl.add_argument("--output", "-o",
                    help="output file or directory (default: attachment filename in cwd)")
    dl.add_argument("--force", action="store_true", help="overwrite an existing file")
    add_common_args(dl)
    dl.set_defaults(func=cmd_download)

    d = sub.add_parser("delete", help="delete an attachment by id")
    d.add_argument("attachment_id")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
