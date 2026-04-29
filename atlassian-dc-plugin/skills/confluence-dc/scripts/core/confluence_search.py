#!/usr/bin/env python3
"""CQL search with automatic pagination via _links.next."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, run  # noqa: E402
from _confluence import get_confluence  # noqa: E402


_CQL_OPS = ("=", "~", "!=", " AND ", " OR ", " NOT ")


def _looks_like_cql(q: str) -> bool:
    upper = q.upper()
    if any(op.strip() in (q if op in ("=", "~", "!=") else upper) for op in _CQL_OPS):
        return True
    return False


def _simplify_result(r: dict) -> dict:
    content = r.get("content") or r
    return {
        "id": content.get("id"),
        "title": content.get("title", r.get("title", "")),
        "type": content.get("type"),
        "space_key": (content.get("space") or {}).get("key"),
        "url": ((r.get("_links") or {}).get("webui")
                or ((content.get("_links") or {}).get("webui"))
                or r.get("url", "")),
        "excerpt": r.get("excerpt", ""),
        "lastModified": r.get("lastModified", ""),
    }


def main():
    p = argparse.ArgumentParser(description="Search Confluence content with CQL")
    p.add_argument("query", help="CQL string, or free text (auto-wrapped as title/text ~ ...)")
    p.add_argument("--limit", type=int, default=25, help="max results across pages")
    p.add_argument("--start", type=int, default=0, help="initial pagination offset")
    p.add_argument("--page-size", type=int, default=25)
    p.add_argument("--expand", help="comma-separated expand list, e.g. body.storage,version")
    add_common_args(p)
    args = p.parse_args()

    cql = args.query if _looks_like_cql(args.query) \
        else f'text ~ "{args.query}" OR title ~ "{args.query}"'

    client = get_confluence(args)

    collected: list[dict] = []
    next_path = "content/search"
    next_params: dict | None = {
        "cql": cql,
        "start": args.start,
        "limit": min(args.page_size, args.limit),
    }
    if args.expand:
        next_params["expand"] = args.expand
    total: int | None = None

    while next_path is not None and len(collected) < args.limit:
        if next_params is not None:
            next_params["limit"] = min(args.page_size, args.limit - len(collected))
        data = client.get(next_path, params=next_params)
        results = (data or {}).get("results", [])
        if total is None:
            total = data.get("totalSize") if isinstance(data, dict) else None
        if not results:
            break
        collected.extend(results)
        links = (data.get("_links") or {}) if isinstance(data, dict) else {}
        nxt = links.get("next")
        if nxt:
            next_path = nxt
            next_params = None
        else:
            size = data.get("size", len(results)) if isinstance(data, dict) else len(results)
            page_limit = (next_params or {}).get("limit") if next_params else args.page_size
            if size < (page_limit or args.page_size):
                break
            current_start = (next_params or {}).get("start", args.start) if next_params else args.start
            next_params = {
                "cql": cql,
                "start": current_start + size,
                "limit": min(args.page_size, args.limit - len(collected)),
            }
            if args.expand:
                next_params["expand"] = args.expand

    collected = collected[:args.limit]
    simplified = [_simplify_result(r) for r in collected]

    if args.json:
        emit({"total": total if total is not None else len(simplified),
              "results": collected}, args)
        return

    if not simplified:
        emit({"total": 0, "results": []}, args, human="no results found")
        return

    lines = [f"{s['id'] or '?':<10} [{s['type'] or '?':<8}] {s['space_key'] or '?':<8} {s['title']}"
             for s in simplified]
    emit({"total": total if total is not None else len(simplified), "results": simplified},
         args, human="\n".join(lines) + f"\n\n{len(simplified)} result(s)")


if __name__ == "__main__":
    run(main)
