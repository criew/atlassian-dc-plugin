#!/usr/bin/env python3
"""Bitbucket repository operations: list, get, create, fork, delete."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, emit, emit_dry_run, run  # noqa: E402
from _bitbucket import get_bitbucket  # noqa: E402


def _summary(repo: dict) -> dict:
    project = repo.get("project") or {}
    return {
        "slug": repo.get("slug"),
        "name": repo.get("name"),
        "id": repo.get("id"),
        "project_key": project.get("key"),
        "project_name": project.get("name"),
        "state": repo.get("state"),
        "forkable": repo.get("forkable"),
        "public": repo.get("public"),
    }


def cmd_list(args):
    client = get_bitbucket(args)
    params = {}
    if args.name:
        params["name"] = args.name
    if args.project:
        path = f"projects/{args.project}/repos"
    else:
        path = "repos"
        if args.name:
            # /repos uses 'projectname' for project filter, leave 'name' as repo name filter
            pass
    values = client.paginate(path, params=params, limit=args.limit)
    if args.json:
        emit({"size": len(values), "values": values}, args)
        return
    lines = [
        f"{(r.get('project') or {}).get('key', ''):<10} "
        f"{r.get('slug', ''):<30} {r.get('name', '')}"
        for r in values
    ]
    emit([_summary(r) for r in values], args,
         human="\n".join(lines) + f"\n\n{len(values)} repo(s)")


def cmd_get(args):
    client = get_bitbucket(args)
    data = client.get(f"projects/{args.project}/repos/{args.repo}")
    emit(data, args,
         human=f"{(data.get('project') or {}).get('key')}/{data.get('slug')}: "
               f"{data.get('name')} (id={data.get('id')}, state={data.get('state')})")


def cmd_create(args):
    body = {"name": args.name, "scmId": "git"}
    if args.description:
        body["description"] = args.description
    if args.default_branch:
        body["defaultBranch"] = args.default_branch
    if args.forkable is not None:
        body["forkable"] = args.forkable
    path = f"projects/{args.project}/repos"
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/1.0/{path}", "body": body},
            args,
            human=f"would create repo {args.project}/{args.name}",
        )
        return
    client = get_bitbucket(args)
    data = client.post(path, body)
    emit(data, args,
         human=f"created repo {(data.get('project') or {}).get('key')}/{data.get('slug')}")


def cmd_fork(args):
    body: dict = {}
    if args.name:
        body["name"] = args.name
    if args.target_project:
        body["project"] = {"key": args.target_project}
    path = f"projects/{args.project}/repos/{args.repo}"
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/1.0/{path}", "body": body},
            args,
            human=f"would fork {args.project}/{args.repo}"
                  + (f" -> {args.target_project}" if args.target_project else "")
                  + (f"/{args.name}" if args.name else ""),
        )
        return
    client = get_bitbucket(args)
    data = client.post(path, body)
    emit(data, args,
         human=f"forked to {(data.get('project') or {}).get('key')}/{data.get('slug')}")


def cmd_delete(args):
    path = f"projects/{args.project}/repos/{args.repo}"
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/1.0/{path}"},
            args,
            human=f"would delete repo {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    client.delete(path)
    emit({"deleted": f"{args.project}/{args.repo}"}, args,
         human=f"deleted (or scheduled deletion of) {args.project}/{args.repo}")


def main():
    p = argparse.ArgumentParser(description="Bitbucket repositories")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list repos (in a project or globally)")
    ls.add_argument("--project", help="project key (omit to list across all projects)")
    ls.add_argument("--name", help="filter by repo name")
    ls.add_argument("--limit", type=int, default=100)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="get a repository")
    g.add_argument("--project", required=True)
    g.add_argument("--repo", required=True, help="repo slug")
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create a new repository")
    c.add_argument("--project", required=True)
    c.add_argument("--name", required=True, help="repo name (slug is derived)")
    c.add_argument("--description")
    c.add_argument("--default-branch", help="e.g. main")
    fork_group = c.add_mutually_exclusive_group()
    fork_group.add_argument("--forkable", dest="forkable", action="store_true", default=None)
    fork_group.add_argument("--no-forkable", dest="forkable", action="store_false")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    f = sub.add_parser("fork", help="fork a repository")
    f.add_argument("--project", required=True, help="source project key")
    f.add_argument("--repo", required=True, help="source repo slug")
    f.add_argument("--target-project",
                   help="target project key (e.g. ~jsmith for personal)")
    f.add_argument("--name", help="new fork name")
    add_common_args(f)
    f.set_defaults(func=cmd_fork)

    d = sub.add_parser("delete", help="delete a repository")
    d.add_argument("--project", required=True)
    d.add_argument("--repo", required=True)
    add_common_args(d)
    d.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
