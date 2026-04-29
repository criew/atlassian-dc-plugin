#!/usr/bin/env python3
"""Confluence page CRUD: get, create, update (auto version-bump), delete, children, ancestors."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    NotFoundError,
    ValidationError,
    add_common_args,
    emit,
    emit_dry_run,
    run,
)
from _confluence import get_confluence, paginate  # noqa: E402


def _simplify_page(p: dict) -> dict:
    body = p.get("body") or {}
    storage = (body.get("storage") or {})
    return {
        "id": p.get("id"),
        "title": p.get("title"),
        "type": p.get("type"),
        "space_key": (p.get("space") or {}).get("key"),
        "version": (p.get("version") or {}).get("number"),
        "url": ((p.get("_links") or {}).get("webui") or ""),
        "content": storage.get("value", ""),
    }


def cmd_get(args):
    client = get_confluence(args)
    if args.id:
        data = client.get(
            f"content/{args.id}",
            params={"expand": "body.storage,version,space,history,ancestors"},
        )
    else:
        if not args.title or not args.space:
            raise ValidationError("get requires either --id, or both --title and --space")
        resp = client.get(
            "content",
            params={
                "title": args.title,
                "spaceKey": args.space,
                "expand": "body.storage,version,space,history",
            },
        )
        results = (resp or {}).get("results", [])
        if not results:
            raise NotFoundError(f"page not found: {args.title!r} in space {args.space}")
        data = results[0]
    if args.json:
        emit(data, args)
        return
    s = _simplify_page(data)
    emit(s, args, human=f"{s['id']}: {s['title']}  (space={s['space_key']}, v{s['version']})")


def cmd_create(args):
    page_type = args.type or "page"
    payload: dict = {
        "type": page_type,
        "title": args.title,
        "space": {"key": args.space},
        "body": {
            "storage": {
                "value": args.content,
                "representation": "storage",
            }
        },
    }
    if args.parent:
        payload["ancestors"] = [{"id": args.parent}]

    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/api/content", "body": payload},
            args,
            human=f"would create {page_type} {args.title!r} in space {args.space}",
        )
        return

    client = get_confluence(args)
    data = client.post("content", payload)
    emit(data, args,
         human=f"created {page_type} {data.get('id')}: {data.get('title')} "
               f"(space={(data.get('space') or {}).get('key')})")


def cmd_update(args):
    if args.title is None and args.content is None:
        raise ValidationError("no field given to update (need --title and/or --content)")

    if args.dry_run:
        # In dry-run we cannot read current version; show planned envelope shape.
        intent_body = {
            "type": "page",
            "title": args.title if args.title is not None else "<unchanged — fetched at run time>",
            "version": {"number": "<current+1 — fetched at run time>"},
        }
        if args.content is not None:
            intent_body["body"] = {
                "storage": {"value": args.content, "representation": "storage"}
            }
        fields = [k for k, v in (("title", args.title), ("content", args.content)) if v is not None]
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/content/{args.id}", "body": intent_body},
            args,
            human=f"would update page {args.id} fields: {', '.join(fields)} "
                  f"(version bumped from current+1)",
        )
        return

    client = get_confluence(args)
    current = client.get(f"content/{args.id}", params={"expand": "version,body.storage,space"})
    current_version = ((current.get("version") or {}).get("number")) or 0
    payload: dict = {
        "type": current.get("type", "page"),
        "title": args.title if args.title is not None else current.get("title"),
        "version": {"number": current_version + 1},
    }
    if args.content is not None:
        payload["body"] = {"storage": {"value": args.content, "representation": "storage"}}
    else:
        # Re-send current body so the PUT does not blank the page.
        existing_body = ((current.get("body") or {}).get("storage") or {}).get("value")
        if existing_body is not None:
            payload["body"] = {
                "storage": {"value": existing_body, "representation": "storage"}
            }

    data = client.put(f"content/{args.id}", payload)
    emit(data, args,
         human=f"updated page {data.get('id')}: {data.get('title')} "
               f"(now v{(data.get('version') or {}).get('number')})")


def cmd_delete(args):
    params: dict = {}
    human_extra = ""
    if args.purge:
        params["status"] = "trashed"
        human_extra = " permanently"
    if args.dry_run:
        emit_dry_run(
            {
                "method": "DELETE",
                "path": f"/rest/api/content/{args.id}",
                "params": params or None,
            },
            args,
            human=f"would{human_extra} delete page {args.id}",
        )
        return
    client = get_confluence(args)
    client.delete(f"content/{args.id}", params=params or None)
    emit({"deleted": args.id, "purged": bool(args.purge)}, args,
         human=f"{'purged' if args.purge else 'trashed'} page {args.id}")


def cmd_children(args):
    client = get_confluence(args)
    children = paginate(
        client,
        f"content/{args.id}/child/page",
        params={"expand": "version"},
        limit=args.limit,
        page_size=25,
    )
    if args.json:
        emit({"results": children, "size": len(children)}, args)
        return
    if not children:
        emit([], args, human=f"no child pages on {args.id}")
        return
    lines = [f"{c.get('id'):<10} {c.get('title')}" for c in children]
    emit(children, args, human="\n".join(lines) + f"\n\n{len(children)} child page(s)")


def cmd_ancestors(args):
    client = get_confluence(args)
    data = client.get(f"content/{args.id}", params={"expand": "ancestors"})
    ancestors = data.get("ancestors") or []
    if args.json:
        emit({"results": ancestors, "size": len(ancestors)}, args)
        return
    if not ancestors:
        emit([], args, human=f"page {args.id} has no ancestors (top-level)")
        return
    lines = [f"{a.get('id'):<10} {a.get('title')}" for a in ancestors]
    emit(ancestors, args, human="\n".join(lines) + f"\n\n{len(ancestors)} ancestor(s)")


def cmd_history(args):
    """List all versions of a page (number, when, author, message)."""
    client = get_confluence(args)
    data = client.get(f"content/{args.id}/version", params={"limit": args.limit})
    versions = data.get("results", [])
    if args.json:
        emit(data, args)
        return
    if not versions:
        emit([], args, human=f"no version history for {args.id}")
        return
    lines = []
    for v in versions:
        when = (v.get("when") or "")[:19]
        by = ((v.get("by") or {}).get("displayName") or
              (v.get("by") or {}).get("username") or "?")
        msg = (v.get("message") or "").strip()
        lines.append(f"v{v.get('number'):<4} {when}  {by:<20} {msg}")
    emit(versions, args, human="\n".join(lines) + f"\n\n{len(versions)} version(s)")


def cmd_export(args):
    """Print the URL the browser would use to download an export.

    The Confluence DC export endpoints (`/exportword`, `/spaces/exportallpages`)
    require a logged-in browser session because they stream the file from a
    UI servlet, not a REST endpoint. This command outputs the URL so the user
    (or LLM, via curl with the PAT cookie session) can fetch it.
    """
    base = get_confluence(args).instance.url
    if args.format == "pdf":
        url = f"{base}/spaces/flyingpdf/pdfpageexport.action?pageId={args.id}"
    elif args.format == "word":
        url = f"{base}/exportword?pageId={args.id}"
    else:
        raise ValidationError(f"unknown format: {args.format}")
    payload = {"page_id": args.id, "format": args.format, "url": url}
    emit(payload, args, human=f"export URL ({args.format}): {url}\n"
                              f"(open in browser while logged in, or curl with session cookie)")


def main():
    p = argparse.ArgumentParser(description="Confluence page CRUD")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="fetch a page by id, or by title+space")
    g.add_argument("--id")
    g.add_argument("--title")
    g.add_argument("--space", help="space key (required with --title)")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create a page or blogpost")
    c.add_argument("--space", required=True, help="space key")
    c.add_argument("--title", required=True)
    c.add_argument("--content", required=True, help="storage-format XHTML body")
    c.add_argument("--parent", help="parent page id (omit for top-level)")
    c.add_argument("--type", choices=["page", "blogpost"], default="page")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    u = sub.add_parser("update", help="update a page (auto version-bump)")
    u.add_argument("id")
    u.add_argument("--title")
    u.add_argument("--content", help="storage-format XHTML body")
    add_common_args(u)
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("delete", help="trash (or purge) a page")
    d.add_argument("id")
    d.add_argument("--purge", action="store_true",
                   help="permanently delete already-trashed content")
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    ch = sub.add_parser("children", help="list direct child pages")
    ch.add_argument("id")
    ch.add_argument("--limit", type=int, default=100)
    add_common_args(ch)
    ch.set_defaults(func=cmd_children)

    an = sub.add_parser("ancestors", help="list parent chain (root -> immediate parent)")
    an.add_argument("id")
    add_common_args(an)
    an.set_defaults(func=cmd_ancestors)

    h = sub.add_parser("history", help="list all versions of a page")
    h.add_argument("id")
    h.add_argument("--limit", type=int, default=50)
    add_common_args(h)
    h.set_defaults(func=cmd_history)

    e = sub.add_parser("export", help="print export URL (PDF/Word, browser-only in DC)")
    e.add_argument("id")
    e.add_argument("--format", choices=["pdf", "word"], default="pdf")
    add_common_args(e)
    e.set_defaults(func=cmd_export)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
