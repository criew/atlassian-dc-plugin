#!/usr/bin/env python3
"""JQL search with automatic pagination."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import add_common_args, emit, emit_list, run  # noqa: E402
from _jira import get_jira, simplify_issue  # noqa: E402

def main():
    p = argparse.ArgumentParser(description="Search Jira issues with JQL")
    p.add_argument("jql", help="JQL query, e.g. 'project = TEST AND status = Open'")
    p.add_argument("--fields", default="summary,status,issuetype,priority,assignee,labels")
    p.add_argument("--limit", type=int, default=50, help="max results across pages")
    p.add_argument("--start-at", type=int, default=0, help="initial pagination offset")
    p.add_argument("--page-size", type=int, default=50)
    add_common_args(p)
    args = p.parse_args()

    client = get_jira(args)
    collected = []
    start_at = args.start_at
    total = 0
    while len(collected) < args.limit:
        page_size = min(args.page_size, args.limit - len(collected))
        data = client.get("search", params={
            "jql": args.jql,
            "fields": args.fields,
            "startAt": start_at,
            "maxResults": page_size,
        })
        issues = data.get("issues", [])
        collected.extend(issues)
        total = data.get("total", 0)
        if not issues or start_at + len(issues) >= total:
            break
        start_at += len(issues)

    returned = len(collected)
    next_start = args.start_at + returned
    hint = f"rerun with --limit {total} (or --start-at {next_start}) to fetch the rest"

    if not collected:
        emit({"returned": 0, "total": total, "truncated": False, "issues": []},
             args, human="no issues found")
        return

    lines = []
    for raw in collected:
        s = simplify_issue(raw)
        lines.append(f"{s['key']:<14} [{s['status']:<12}] {s['issuetype']:<8} {s['summary']}")
    emit_list(
        collected, args, lines,
        total=total, next_hint=hint, item_name="issue", key="issues",
    )


if __name__ == "__main__":
    run(main)
