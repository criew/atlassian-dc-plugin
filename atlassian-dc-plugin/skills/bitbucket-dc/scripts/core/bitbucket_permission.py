#!/usr/bin/env python3
"""Bitbucket permissions: project-level and repo-level user/group grants.

Permission strings:
  Project:  PROJECT_READ, PROJECT_WRITE, PROJECT_ADMIN
  Repo:     REPO_READ,    REPO_WRITE,    REPO_ADMIN
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    add_common_args, emit, emit_dry_run, run, ValidationError,
)
from _bitbucket import get_bitbucket  # noqa: E402

PROJECT_PERMS = ("PROJECT_READ", "PROJECT_WRITE", "PROJECT_ADMIN")
REPO_PERMS    = ("REPO_READ",    "REPO_WRITE",    "REPO_ADMIN")


def _scope_path(args, suffix: str) -> str:
    if args.repo:
        return f"projects/{args.project}/repos/{args.repo}/permissions{suffix}"
    return f"projects/{args.project}/permissions{suffix}"


def _allowed_perms(args) -> tuple:
    return REPO_PERMS if args.repo else PROJECT_PERMS


def cmd_list(args):
    client = get_bitbucket(args)
    users = client.paginate(_scope_path(args, "/users"), limit=args.limit)
    groups = client.paginate(_scope_path(args, "/groups"), limit=args.limit)
    out = {"users": users, "groups": groups,
           "scope": "repo" if args.repo else "project",
           "project": args.project, "repo": args.repo}
    if args.json:
        emit(out, args)
        return
    lines = ["# Users:"]
    for u in users:
        lines.append(f"  {u.get('user', {}).get('name'):<20} {u.get('permission')}")
    lines.append("")
    lines.append("# Groups:")
    for g in groups:
        lines.append(f"  {g.get('group', {}).get('name'):<20} {g.get('permission')}")
    emit(out, args, human="\n".join(lines))


def cmd_grant_user(args):
    if args.permission not in _allowed_perms(args):
        raise ValidationError(f"permission must be one of {_allowed_perms(args)}")
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT",
             "path": "/rest/api/1.0/" + _scope_path(args, "/users")
                     + f"?permission={args.permission}&name={args.user}"},
            args,
            human=f"would grant {args.user} {args.permission} on "
                  f"{'repo' if args.repo else 'project'} {args.project}{'/' + args.repo if args.repo else ''}",
        )
        return
    client = get_bitbucket(args)
    client.put(_scope_path(args, "/users") + f"?permission={args.permission}&name={args.user}")
    emit({"user": args.user, "permission": args.permission}, args,
         human=f"granted {args.user} -> {args.permission}")


def cmd_grant_group(args):
    if args.permission not in _allowed_perms(args):
        raise ValidationError(f"permission must be one of {_allowed_perms(args)}")
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT",
             "path": "/rest/api/1.0/" + _scope_path(args, "/groups")
                     + f"?permission={args.permission}&name={args.group}"},
            args,
            human=f"would grant group {args.group} {args.permission}",
        )
        return
    client = get_bitbucket(args)
    client.put(_scope_path(args, "/groups") + f"?permission={args.permission}&name={args.group}")
    emit({"group": args.group, "permission": args.permission}, args,
         human=f"granted group {args.group} -> {args.permission}")


def cmd_revoke_user(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": "/rest/api/1.0/" + _scope_path(args, f"/users?name={args.user}")},
            args,
            human=f"would revoke {args.user}",
        )
        return
    client = get_bitbucket(args)
    client.delete(_scope_path(args, f"/users?name={args.user}"))
    emit({"revoked": args.user}, args, human=f"revoked {args.user}")


def cmd_revoke_group(args):
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": "/rest/api/1.0/" + _scope_path(args, f"/groups?name={args.group}")},
            args,
            human=f"would revoke group {args.group}",
        )
        return
    client = get_bitbucket(args)
    client.delete(_scope_path(args, f"/groups?name={args.group}"))
    emit({"revoked_group": args.group}, args, human=f"revoked group {args.group}")


def main():
    p = argparse.ArgumentParser(
        description="Bitbucket permissions (project-level by default; pass --repo to scope to a repo)")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    def scope_args(parser):
        parser.add_argument("--project", required=True)
        parser.add_argument("--repo", help="if set, repo-level permissions instead of project-level")

    ls = sub.add_parser("list", help="list user + group permissions for a project or repo")
    scope_args(ls)
    ls.add_argument("--limit", type=int, default=200)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    gu = sub.add_parser("grant-user", help="grant a user permission")
    scope_args(gu)
    gu.add_argument("--user", required=True)
    gu.add_argument("--permission", required=True,
                    help=f"PROJECT_READ|WRITE|ADMIN (project) or REPO_READ|WRITE|ADMIN (repo)")
    add_common_args(gu)
    gu.set_defaults(func=cmd_grant_user)

    gg = sub.add_parser("grant-group", help="grant a group permission")
    scope_args(gg)
    gg.add_argument("--group", required=True)
    gg.add_argument("--permission", required=True)
    add_common_args(gg)
    gg.set_defaults(func=cmd_grant_group)

    ru = sub.add_parser("revoke-user", help="remove a user grant")
    scope_args(ru)
    ru.add_argument("--user", required=True)
    add_common_args(ru)
    ru.set_defaults(func=cmd_revoke_user)

    rg = sub.add_parser("revoke-group", help="remove a group grant")
    scope_args(rg)
    rg.add_argument("--group", required=True)
    add_common_args(rg)
    rg.set_defaults(func=cmd_revoke_group)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
