#!/usr/bin/env python3
"""Bitbucket file operations: get-content, list-dir, search."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import add_common_args, emit, run, ValidationError  # noqa: E402
from _bitbucket import get_bitbucket  # noqa: E402


def cmd_get_content(args):
    client = get_bitbucket(args)
    if args.raw:
        path = f"projects/{args.project}/repos/{args.repo}/raw/{args.path}"
        params = {}
        if args.at:
            params["at"] = args.at
        resp = client.get_raw(path, params=params)
        if args.json:
            emit({"path": args.path, "at": args.at, "content": resp.text,
                  "size": len(resp.content)}, args)
        else:
            # write content to stdout verbatim
            sys.stdout.write(resp.text)
        return

    # JSON browse: stitch lines together (handles paginated response)
    path = f"projects/{args.project}/repos/{args.repo}/browse/{args.path}"
    all_lines = []
    start = 0
    page_size = 500
    last_page_meta: dict = {}
    while True:
        params = {"start": start, "limit": page_size}
        if args.at:
            params["at"] = args.at
        data = client.get(path, params=params)
        if not isinstance(data, dict):
            break
        last_page_meta = data
        for ln in data.get("lines", []) or []:
            all_lines.append(ln.get("text", ""))
        if data.get("isLastPage", True):
            break
        nxt = data.get("nextPageStart")
        if nxt is None or nxt == start:
            break
        start = nxt

    content = "\n".join(all_lines)
    result = {
        "path": args.path,
        "at": args.at,
        "content": content,
        "size": last_page_meta.get("size") if last_page_meta else None,
        "lines": len(all_lines),
    }
    if args.json:
        emit(result, args)
    else:
        emit(result, args, human=content)


def cmd_list_dir(args):
    client = get_bitbucket(args)
    path = f"projects/{args.project}/repos/{args.repo}/browse/{args.path or ''}"
    params = {}
    if args.at:
        params["at"] = args.at
    params["limit"] = args.limit
    data = client.get(path, params=params)
    if not isinstance(data, dict):
        emit(data, args)
        return
    children = (data.get("children") or {}).get("values") or []
    if args.json:
        emit(data, args)
        return
    if not children:
        # might be a file rather than a directory — surface that
        if data.get("lines") is not None:
            emit(data, args, human=f"{args.path} appears to be a file, not a directory")
            return
        emit(data, args, human=f"no entries in {args.path or '/'}")
        return
    lines = []
    for c in children:
        ctype = c.get("type", "?")
        path_part = (c.get("path") or {}).get("toString", "?")
        lines.append(f"{ctype:<6} {path_part}")
    emit(children, args,
         human="\n".join(lines) + f"\n\n{len(children)} entry(ies)")


def cmd_search(args):
    valid = {"code", "file", "repository", "commit"}
    if args.type not in valid:
        raise ValidationError(f"--type must be one of: {', '.join(sorted(valid))}")

    # Bitbucket DC search API expects POST with nested entities structure.
    client = get_bitbucket(args)
    entity_params = {"start": 0, "limit": min(args.limit, 100)}
    if args.project:
        entity_params["projectKey"] = args.project
    if args.repo:
        entity_params["repoSlug"] = args.repo
    body = {
        "query": args.query,
        "entities": {
            args.type: entity_params,
        },
    }
    data = client.post("/rest/search/1.0/search", body=body)
    if args.json:
        emit(data, args)
        return
    values = []
    if isinstance(data, dict):
        # Response nests results under the entity type key.
        entity_result = data.get(args.type)
        if isinstance(entity_result, dict) and "values" in entity_result:
            values = entity_result.get("values") or []
        elif "values" in data:
            values = data.get("values") or []
    emit(data, args, human=f"{len(values)} hit(s) for {args.query!r}")


def main():
    p = argparse.ArgumentParser(description="Bitbucket files & search")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    gc = sub.add_parser("get-content", help="get file content")
    gc.add_argument("--project", required=True)
    gc.add_argument("--repo", required=True)
    gc.add_argument("--path", required=True)
    gc.add_argument("--at", help="ref or commit (default: default branch)")
    gc.add_argument("--raw", action="store_true",
                    help="use /raw/ endpoint (returns raw text/binary)")
    add_common_args(gc)
    gc.set_defaults(func=cmd_get_content)

    ld = sub.add_parser("list-dir", help="list files/dirs at a path")
    ld.add_argument("--project", required=True)
    ld.add_argument("--repo", required=True)
    ld.add_argument("--path", default="", help="directory path (empty = repo root)")
    ld.add_argument("--at")
    ld.add_argument("--limit", type=int, default=500)
    add_common_args(ld)
    ld.set_defaults(func=cmd_list_dir)

    s = sub.add_parser("search", help="search code/files via /rest/search/1.0")
    s.add_argument("query")
    s.add_argument("--type", default="code", choices=["code", "file", "repository", "commit"])
    s.add_argument("--project", help="restrict to this project key")
    s.add_argument("--repo", help="restrict to this repo slug (requires --project)")
    s.add_argument("--limit", type=int, default=25)
    add_common_args(s)
    s.set_defaults(func=cmd_search)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
