#!/usr/bin/env python3
"""JQL search with automatic pagination."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, get_jira, emit, run, simplify_issue  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Search Jira issues with JQL")
    p.add_argument("jql", help="JQL query, e.g. 'project = TEST AND status = Open'")
    p.add_argument("--fields", default="summary,status,issuetype,priority,assignee,labels")
    p.add_argument("--limit", type=int, default=50, help="max results across pages")
    p.add_argument("--page-size", type=int, default=50)
    add_common_args(p)
    args = p.parse_args()

    client = get_jira(args)
    collected = []
    start_at = 0
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

    if args.json:
        emit({"total": len(collected), "issues": collected}, args)
        return

    if not collected:
        emit({"total": 0, "issues": []}, args, human="no issues found")
        return

    lines = []
    for raw in collected:
        s = simplify_issue(raw)
        lines.append(f"{s['key']:<14} [{s['status']:<12}] {s['issuetype']:<8} {s['summary']}")
    emit(
        {"total": len(collected), "issues": [simplify_issue(i) for i in collected]},
        args,
        human="\n".join(lines) + f"\n\n{len(collected)} issue(s)",
    )


if __name__ == "__main__":
    run(main)
