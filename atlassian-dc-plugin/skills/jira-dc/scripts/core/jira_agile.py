#!/usr/bin/env python3
"""Jira Agile (Boards & Sprints).

Uses /rest/agile/1.0 (the Greenhopper-derived API), not /rest/api/2.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    add_common_args, get_jira, emit, emit_dry_run, run, simplify_issue,
    ValidationError,
)


def _agile(client, path: str, params=None):
    """GET against /rest/agile/1.0/<path>."""
    return client.get(f"/rest/agile/1.0/{path.lstrip('/')}", params=params)


# -----------------------------------------------------------------------------
# Boards
# -----------------------------------------------------------------------------

def cmd_boards_list(args):
    client = get_jira(args)
    params = {}
    if args.project:
        params["projectKeyOrId"] = args.project
    if args.type:
        params["type"] = args.type
    data = _agile(client, "board", params=params)
    values = data.get("values", [])
    if args.json:
        emit(data, args)
        return
    lines = [f"{b.get('id'):<6} {b.get('type'):<8} {b.get('name')}" for b in values]
    emit(values, args, human="\n".join(lines) + f"\n\n{len(values)} board(s)")


def cmd_boards_get(args):
    client = get_jira(args)
    data = _agile(client, f"board/{args.id}")
    emit(data, args,
         human=f"board {data.get('id')} {data.get('name')} (type={data.get('type')})")


def cmd_board_issues(args):
    client = get_jira(args)
    params = {"maxResults": args.limit}
    if args.jql:
        params["jql"] = args.jql
    if args.fields:
        params["fields"] = args.fields
    data = _agile(client, f"board/{args.id}/issue", params=params)
    issues = data.get("issues", [])
    if args.json:
        emit({"total": data.get("total", len(issues)), "issues": issues}, args)
        return
    lines = []
    for raw in issues:
        s = simplify_issue(raw)
        lines.append(f"{s['key']:<14} [{s['status'] or '?':<12}] {s['summary']}")
    emit({"total": data.get("total", len(issues)), "issues": [simplify_issue(i) for i in issues]},
         args, human="\n".join(lines) + f"\n\n{len(issues)} issue(s) on board {args.id}")


# -----------------------------------------------------------------------------
# Sprints
# -----------------------------------------------------------------------------

def cmd_sprints_list(args):
    client = get_jira(args)
    params = {"maxResults": args.limit}
    if args.state:
        params["state"] = args.state
    data = _agile(client, f"board/{args.board}/sprint", params=params)
    values = data.get("values", [])
    if args.json:
        emit(data, args)
        return
    lines = [f"{s.get('id'):<6} {s.get('state'):<8} {s.get('name')}" for s in values]
    emit(values, args, human="\n".join(lines) + f"\n\n{len(values)} sprint(s)")


def cmd_sprints_get(args):
    client = get_jira(args)
    data = _agile(client, f"sprint/{args.id}")
    emit(data, args,
         human=f"sprint {data.get('id')} {data.get('name')} state={data.get('state')}")


def cmd_sprint_issues(args):
    client = get_jira(args)
    params = {"maxResults": args.limit}
    if args.jql:
        params["jql"] = args.jql
    data = _agile(client, f"sprint/{args.id}/issue", params=params)
    issues = data.get("issues", [])
    if args.json:
        emit({"total": data.get("total", len(issues)), "issues": issues}, args)
        return
    lines = []
    for raw in issues:
        s = simplify_issue(raw)
        lines.append(f"{s['key']:<14} [{s['status'] or '?':<12}] {s['summary']}")
    emit({"total": data.get("total", len(issues)), "issues": [simplify_issue(i) for i in issues]},
         args, human="\n".join(lines) + f"\n\n{len(issues)} issue(s) in sprint {args.id}")


def cmd_sprint_create(args):
    body = {"name": args.name, "originBoardId": int(args.board)}
    if args.start_date:
        body["startDate"] = args.start_date
    if args.end_date:
        body["endDate"] = args.end_date
    if args.goal:
        body["goal"] = args.goal
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/agile/1.0/sprint", "body": body},
            args,
            human=f"would create sprint {args.name!r} on board {args.board}",
        )
        return
    client = get_jira(args)
    data = client.post("/rest/agile/1.0/sprint", body)
    emit(data, args, human=f"created sprint {data.get('name')} (id={data.get('id')})")


def cmd_sprint_update(args):
    body: dict = {}
    if args.name is not None:
        body["name"] = args.name
    if args.start_date is not None:
        body["startDate"] = args.start_date
    if args.end_date is not None:
        body["endDate"] = args.end_date
    if args.goal is not None:
        body["goal"] = args.goal
    if args.state is not None:
        body["state"] = args.state
    if not body:
        raise ValidationError("no field to update")
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/agile/1.0/sprint/{args.id}", "body": body},
            args,
            human=f"would update sprint {args.id} fields: {', '.join(body.keys())}",
        )
        return
    client = get_jira(args)
    data = client.post(f"/rest/agile/1.0/sprint/{args.id}", body)
    emit(data, args, human=f"updated sprint {args.id}")


def cmd_sprint_move(args):
    """Move issues into a sprint."""
    body = {"issues": args.issue}
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/agile/1.0/sprint/{args.id}/issue", "body": body},
            args,
            human=f"would move {len(args.issue)} issue(s) to sprint {args.id}",
        )
        return
    client = get_jira(args)
    client.post(f"/rest/agile/1.0/sprint/{args.id}/issue", body)
    emit({"sprint": args.id, "moved": args.issue}, args,
         human=f"moved {len(args.issue)} issue(s) to sprint {args.id}")


def cmd_backlog_move(args):
    """Move issues to backlog (remove from current sprint)."""
    body = {"issues": args.issue}
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": "/rest/agile/1.0/backlog/issue", "body": body},
            args,
            human=f"would move {len(args.issue)} issue(s) to backlog",
        )
        return
    client = get_jira(args)
    client.post("/rest/agile/1.0/backlog/issue", body)
    emit({"backlog_moved": args.issue}, args,
         human=f"moved {len(args.issue)} issue(s) to backlog")


# -----------------------------------------------------------------------------
# Epic
# -----------------------------------------------------------------------------

def cmd_epic_issues(args):
    client = get_jira(args)
    params = {"maxResults": args.limit}
    if args.jql:
        params["jql"] = args.jql
    data = _agile(client, f"epic/{args.id}/issue", params=params)
    issues = data.get("issues", [])
    if args.json:
        emit({"total": data.get("total", len(issues)), "issues": issues}, args)
        return
    lines = []
    for raw in issues:
        s = simplify_issue(raw)
        lines.append(f"{s['key']:<14} [{s['status'] or '?':<12}] {s['summary']}")
    emit({"total": data.get("total", len(issues)), "issues": [simplify_issue(i) for i in issues]},
         args, human="\n".join(lines) + f"\n\n{len(issues)} issue(s) under epic {args.id}")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Jira Agile: boards, sprints, epics")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    # Boards
    bls = sub.add_parser("boards", help="list boards")
    bls.add_argument("--project", help="filter by project key")
    bls.add_argument("--type", choices=["scrum", "kanban"], help="filter by board type")
    add_common_args(bls)
    bls.set_defaults(func=cmd_boards_list)

    bg = sub.add_parser("board", help="get board details")
    bg.add_argument("id")
    add_common_args(bg)
    bg.set_defaults(func=cmd_boards_get)

    bi = sub.add_parser("board-issues", help="list issues on a board")
    bi.add_argument("id", help="board id")
    bi.add_argument("--jql", help="extra JQL filter")
    bi.add_argument("--fields", help="comma-separated field list")
    bi.add_argument("--limit", type=int, default=50)
    add_common_args(bi)
    bi.set_defaults(func=cmd_board_issues)

    # Sprints
    sl = sub.add_parser("sprints", help="list sprints of a board")
    sl.add_argument("--board", required=True)
    sl.add_argument("--state", choices=["future", "active", "closed"])
    sl.add_argument("--limit", type=int, default=50)
    add_common_args(sl)
    sl.set_defaults(func=cmd_sprints_list)

    sg = sub.add_parser("sprint", help="get sprint details")
    sg.add_argument("id")
    add_common_args(sg)
    sg.set_defaults(func=cmd_sprints_get)

    si = sub.add_parser("sprint-issues", help="list issues in a sprint")
    si.add_argument("id", help="sprint id")
    si.add_argument("--jql", help="extra JQL filter")
    si.add_argument("--limit", type=int, default=50)
    add_common_args(si)
    si.set_defaults(func=cmd_sprint_issues)

    sc = sub.add_parser("sprint-create", help="create a sprint")
    sc.add_argument("--board", required=True)
    sc.add_argument("--name", required=True)
    sc.add_argument("--start-date", help="ISO 8601, e.g. 2026-04-29T08:00:00.000Z")
    sc.add_argument("--end-date", help="ISO 8601")
    sc.add_argument("--goal")
    add_common_args(sc)
    sc.set_defaults(func=cmd_sprint_create)

    su = sub.add_parser("sprint-update", help="update a sprint (incl. start/close)")
    su.add_argument("id")
    su.add_argument("--name")
    su.add_argument("--start-date")
    su.add_argument("--end-date")
    su.add_argument("--goal")
    su.add_argument("--state", choices=["future", "active", "closed"])
    add_common_args(su)
    su.set_defaults(func=cmd_sprint_update)

    sm = sub.add_parser("sprint-move", help="move issues into a sprint")
    sm.add_argument("id", help="target sprint id")
    sm.add_argument("--issue", action="append", required=True,
                    help="issue key (repeat for multiple)")
    add_common_args(sm)
    sm.set_defaults(func=cmd_sprint_move)

    bm = sub.add_parser("backlog-move", help="move issues out of any sprint into backlog")
    bm.add_argument("--issue", action="append", required=True)
    add_common_args(bm)
    bm.set_defaults(func=cmd_backlog_move)

    # Epic
    ei = sub.add_parser("epic-issues", help="list issues under an epic")
    ei.add_argument("id", help="epic id or key")
    ei.add_argument("--jql")
    ei.add_argument("--limit", type=int, default=50)
    add_common_args(ei)
    ei.set_defaults(func=cmd_epic_issues)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
