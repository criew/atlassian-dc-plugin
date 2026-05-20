#!/usr/bin/env python3
"""Bitbucket pull request operations.

Subcommands: list, get, create, update, decline, merge, diff,
add-comment, list-comments, approve, unapprove.
"""
import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import add_common_args, emit, emit_dry_run, run, ValidationError  # noqa: E402
from _bitbucket import get_bitbucket  # noqa: E402


def _ref(branch: str) -> str:
    """Normalize a branch name to a full ref."""
    if branch.startswith("refs/"):
        return branch
    return f"refs/heads/{branch}"


def _simplify_pr(pr: dict) -> dict:
    from_ref = pr.get("fromRef") or {}
    to_ref = pr.get("toRef") or {}
    author = (pr.get("author") or {}).get("user") or {}
    reviewers = []
    for rv in pr.get("reviewers", []) or []:
        u = rv.get("user") or {}
        reviewers.append({
            "name": u.get("name"),
            "approved": rv.get("approved"),
            "status": rv.get("status"),
        })
    to_repo = (to_ref.get("repository") or {})
    to_project = (to_repo.get("project") or {})
    result = {
        "id": pr.get("id"),
        "version": pr.get("version"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "open": pr.get("open"),
        "closed": pr.get("closed"),
        "fromRef": from_ref.get("displayId"),
        "toRef": to_ref.get("displayId"),
        "author": author.get("name"),
        "reviewers": reviewers,
        "createdDate": pr.get("createdDate"),
        "updatedDate": pr.get("updatedDate"),
    }
    if to_project.get("key"):
        result["project"] = to_project["key"]
    if to_repo.get("slug"):
        result["repo"] = to_repo["slug"]
    return result


def _pr_path(args, suffix: str = "") -> str:
    base = f"projects/{args.project}/repos/{args.repo}/pull-requests"
    if hasattr(args, "id") and args.id is not None:
        base = f"{base}/{args.id}"
    return base + (f"/{suffix}" if suffix else "")


def _dashboard_params(args):
    # type: (argparse.Namespace) -> dict
    params = {}
    if args.order:
        params["order"] = args.order
    if args.state and args.state != "ALL":
        params["state"] = args.state
    if getattr(args, "role", None):
        params["role"] = args.role
    if getattr(args, "participant_status", None):
        params["participantStatus"] = args.participant_status
    return params


def _pr_matches_scope(pr, project=None, repo=None):
    # type: (dict, Optional[str], Optional[str]) -> bool
    to_ref = pr.get("toRef") or {}
    to_repo = to_ref.get("repository") or {}
    to_proj = to_repo.get("project") or {}
    if project and (to_proj.get("key") or "").upper() != project.upper():
        return False
    if repo and (to_repo.get("slug") or "").lower() != repo.lower():
        return False
    return True


def _dashboard_filtered(client, params, limit, project=None, repo=None):
    # type: (...) -> list
    """Paginate dashboard/pull-requests, optionally filtering by project/repo."""
    if not project and not repo:
        return client.paginate("dashboard/pull-requests", params=params, limit=limit)
    collected = []
    page_params = dict(params)
    start = 0
    page_size = 50
    max_pages = 20
    for _ in range(max_pages):
        page_params["start"] = start
        page_params["limit"] = page_size
        data = client.get("dashboard/pull-requests", params=page_params)
        values = data.get("values", []) if isinstance(data, dict) else []
        if not values:
            break
        for pr in values:
            if _pr_matches_scope(pr, project, repo):
                collected.append(pr)
                if len(collected) >= limit:
                    return collected[:limit]
        if not isinstance(data, dict) or data.get("isLastPage", True):
            break
        next_start = data.get("nextPageStart")
        if next_start is None or next_start == start:
            break
        start = next_start
    return collected[:limit]


def cmd_list(args):
    client = get_bitbucket(args)
    show_repo = True

    if args.project and args.repo:
        # Single repo — try repo-scoped endpoint first
        show_repo = False
        params = {}
        if args.order:
            params["order"] = args.order
        if args.state:
            params["state"] = args.state
        if args.direction:
            params["direction"] = args.direction
        if args.at:
            params["at"] = args.at
        values = client.paginate(
            f"projects/{args.project}/repos/{args.repo}/pull-requests",
            params=params, limit=args.limit,
        )
        if not values:
            # Repo index may be broken — fall back to dashboard with filter
            if args.debug:
                import sys as _sys
                _sys.stderr.write("[debug] repo endpoint returned 0 results, "
                                  "falling back to dashboard\n")
            show_repo = True
            values = _dashboard_filtered(
                client, _dashboard_params(args), args.limit,
                project=args.project, repo=args.repo,
            )

    elif args.project:
        # Project-level — use dashboard with project filter
        values = _dashboard_filtered(
            client, _dashboard_params(args), args.limit,
            project=args.project,
        )

    else:
        # Global dashboard
        values = _dashboard_filtered(
            client, _dashboard_params(args), args.limit,
        )

    values = values[:args.limit]
    if args.json:
        emit({"size": len(values), "values": values}, args)
        return
    lines = []
    for pr in values:
        s = _simplify_pr(pr)
        prefix = f"{s.get('project', '?')}/{s.get('repo', '?')} " if show_repo else ""
        lines.append(f"{prefix}#{s['id']:<5} [{s['state']:<8}] {s['fromRef']} -> {s['toRef']} "
                     f"by {s['author']:<15} {s['title']}")
    emit([_simplify_pr(pr) for pr in values], args,
         human="\n".join(lines) + f"\n\n{len(values)} pull request(s)")


def cmd_get(args):
    client = get_bitbucket(args)
    data = client.get(f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}")
    s = _simplify_pr(data)
    emit(data, args,
         human=f"#{s['id']} v{s['version']} [{s['state']}] {s['fromRef']} -> {s['toRef']}: "
               f"{s['title']}")


def _fetch_default_reviewers(client, project, repo, from_ref, to_ref):
    """Fetch default reviewers configured for this source/target combination."""
    path = (f"/rest/default-reviewers/1.0/projects/{project}/repos/{repo}"
            f"/reviewers")
    params = {"sourceRefId": from_ref, "targetRefId": to_ref}
    try:
        data = client.get(path, params=params)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [entry.get("name") for entry in data if entry.get("name")]


def cmd_create(args):
    from_ref = _ref(args.from_branch)
    to_ref = _ref(args.to_branch)
    body = {
        "title": args.title,
        "fromRef": {
            "id": from_ref,
            "repository": {"slug": args.repo, "project": {"key": args.project}},
        },
        "toRef": {
            "id": to_ref,
            "repository": {"slug": args.repo, "project": {"key": args.project}},
        },
    }
    if args.description is not None:
        body["description"] = args.description

    explicit = list(args.reviewer or [])

    if not args.dry_run:
        client = get_bitbucket(args)
        default_names = _fetch_default_reviewers(
            client, args.project, args.repo, from_ref, to_ref)
        all_names = list(dict.fromkeys(explicit + default_names))
        if all_names:
            body["reviewers"] = [{"user": {"name": n}} for n in all_names]
        data = client.post(
            f"projects/{args.project}/repos/{args.repo}/pull-requests", body)
        emit(data, args,
             human=f"created PR #{data.get('id')} on {args.project}/{args.repo}")
        return

    if explicit:
        body["reviewers"] = [{"user": {"name": r}} for r in explicit]
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests"
    emit_dry_run(
        {"method": "POST", "path": f"/rest/api/1.0/{path}", "body": body},
        args,
        human=f"would create PR {args.from_branch} -> {args.to_branch} "
              f"on {args.project}/{args.repo}: {args.title!r}",
    )


def cmd_update(args):
    body: dict = {"version": args.version}
    if args.title is not None:
        body["title"] = args.title
    if args.description is not None:
        body["description"] = args.description
    if args.to_branch:
        body["toRef"] = {"id": _ref(args.to_branch)}
    if args.reviewer is not None:
        body["reviewers"] = [{"user": {"name": r}} for r in args.reviewer]
    if len(body) == 1:
        raise ValidationError("no field given to update")
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}"
    if args.dry_run:
        emit_dry_run(
            {"method": "PUT", "path": f"/rest/api/1.0/{path}", "body": body},
            args,
            human=f"would update PR #{args.id} fields: "
                  f"{', '.join(k for k in body if k != 'version')}",
        )
        return
    client = get_bitbucket(args)
    data = client.put(path, body)
    emit(data, args, human=f"updated PR #{args.id} (now v{data.get('version')})")


def cmd_decline(args):
    body = {"version": args.version}
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}/decline"
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/1.0/{path}", "body": body},
            args,
            human=f"would decline PR #{args.id} on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    data = client.post(path, body)
    emit(data, args, human=f"declined PR #{args.id}")


def cmd_merge(args):
    body: dict = {"version": args.version}
    if args.message:
        body["message"] = args.message
    if args.strategy:
        body["strategyId"] = args.strategy
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}/merge"
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/1.0/{path}", "body": body},
            args,
            human=f"would merge PR #{args.id} on {args.project}/{args.repo}"
                  + (f" using {args.strategy}" if args.strategy else ""),
        )
        return
    client = get_bitbucket(args)
    data = client.post(path, body)
    emit(data, args, human=f"merged PR #{args.id}")


def cmd_diff(args):
    client = get_bitbucket(args)
    params: dict = {}
    if args.context_lines is not None:
        params["contextLines"] = args.context_lines
    if args.whitespace:
        params["whitespace"] = args.whitespace
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}/diff"
    data = client.get(path, params=params)
    if args.json:
        emit(data, args)
        return
    if isinstance(data, str):
        sys.stdout.write(data)
    else:
        emit(data, args)


def cmd_add_comment(args):
    body: dict = {"text": args.text}
    if args.parent:
        body["parent"] = {"id": int(args.parent)}
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}/comments"
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/1.0/{path}", "body": body},
            args,
            human=f"would add comment to PR #{args.id}: {args.text[:60]!r}",
        )
        return
    client = get_bitbucket(args)
    data = client.post(path, body)
    emit(data, args,
         human=f"added comment id={data.get('id')} to PR #{args.id}")


def cmd_list_comments(args):
    client = get_bitbucket(args)
    # Bitbucket exposes comments via the activities feed for general PR comments.
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}/activities"
    values = client.paginate(path, limit=args.limit)
    comments = []
    for act in values:
        if act.get("action") == "COMMENTED" and act.get("comment"):
            c = act["comment"]
            author = (c.get("author") or {})
            comments.append({
                "id": c.get("id"),
                "version": c.get("version"),
                "author": author.get("name"),
                "text": c.get("text"),
                "createdDate": c.get("createdDate"),
                "updatedDate": c.get("updatedDate"),
            })
    if args.json:
        emit({"size": len(comments), "values": comments}, args)
        return
    lines = [f"#{c['id']:<6} {c['author'] or '?':<15} {(c['text'] or '')[:80]}"
             for c in comments]
    emit(comments, args,
         human="\n".join(lines) + f"\n\n{len(comments)} comment(s) on PR #{args.id}")


def cmd_approve(args):
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}/approve"
    if args.dry_run:
        emit_dry_run(
            {"method": "POST", "path": f"/rest/api/1.0/{path}"},
            args,
            human=f"would approve PR #{args.id} on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    data = client.post(path, None)
    emit(data, args, human=f"approved PR #{args.id}")


def cmd_unapprove(args):
    path = f"projects/{args.project}/repos/{args.repo}/pull-requests/{args.id}/approve"
    if args.dry_run:
        emit_dry_run(
            {"method": "DELETE", "path": f"/rest/api/1.0/{path}"},
            args,
            human=f"would unapprove PR #{args.id} on {args.project}/{args.repo}",
        )
        return
    client = get_bitbucket(args)
    client.delete(path)
    emit({"unapproved": args.id}, args, human=f"unapproved PR #{args.id}")


def _add_pr_locator(p: argparse.ArgumentParser, with_id: bool = True) -> None:
    p.add_argument("--project", required=True)
    p.add_argument("--repo", required=True)
    if with_id:
        p.add_argument("--id", required=True, type=int, help="pull request id")


def main():
    p = argparse.ArgumentParser(description="Bitbucket pull requests")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    ls = sub.add_parser("list", help="list pull requests (global or per-repo)")
    ls.add_argument("--project", help="project key (omit for global dashboard view)")
    ls.add_argument("--repo", help="repository slug (required with --project)")
    ls.add_argument("--state", default="ALL",
                    choices=["OPEN", "MERGED", "DECLINED", "ALL"])
    ls.add_argument("--role", choices=["AUTHOR", "REVIEWER", "PARTICIPANT"],
                    help="filter by your role (global mode only)")
    ls.add_argument("--participant-status",
                    choices=["UNAPPROVED", "NEEDS_WORK", "APPROVED"],
                    help="filter by your review status (global mode only)")
    ls.add_argument("--direction", choices=["INCOMING", "OUTGOING"],
                    help="filter direction (repo-scoped mode only)")
    ls.add_argument("--at", help="filter to PRs targeting this branch ref (repo-scoped only)")
    ls.add_argument("--order", choices=["NEWEST", "OLDEST"],
                    help="sort order (omitted by default for max compatibility)")
    ls.add_argument("--limit", type=int, default=25)
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get", help="get a pull request")
    _add_pr_locator(g)
    add_common_args(g)
    g.set_defaults(func=cmd_get)

    c = sub.add_parser("create", help="create a pull request")
    _add_pr_locator(c, with_id=False)
    c.add_argument("--title", required=True)
    c.add_argument("--from-branch", required=True, help="source branch (refs/heads/ added if missing)")
    c.add_argument("--to-branch", required=True, help="target branch")
    c.add_argument("--description")
    c.add_argument("--reviewer", action="append", default=[],
                   help="reviewer username (repeat for multiple)")
    add_common_args(c)
    c.set_defaults(func=cmd_create)

    u = sub.add_parser("update", help="update a pull request (requires --version)")
    _add_pr_locator(u)
    u.add_argument("--version", required=True, type=int,
                   help="current PR version (optimistic locking)")
    u.add_argument("--title")
    u.add_argument("--description")
    u.add_argument("--to-branch", help="retarget the PR")
    u.add_argument("--reviewer", action="append",
                   help="REPLACES the reviewer list (repeat); pass once with empty to clear")
    add_common_args(u)
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("decline", help="decline a pull request")
    _add_pr_locator(d)
    d.add_argument("--version", required=True, type=int)
    add_common_args(d)
    d.set_defaults(func=cmd_decline)

    m = sub.add_parser("merge", help="merge a pull request")
    _add_pr_locator(m)
    m.add_argument("--version", required=True, type=int)
    m.add_argument("--message")
    m.add_argument("--strategy", choices=["merge-commit", "squash", "fast-forward",
                                          "no-ff", "ff", "ff-only"])
    add_common_args(m)
    m.set_defaults(func=cmd_merge)

    diff = sub.add_parser("diff", help="get the unified diff of a PR")
    _add_pr_locator(diff)
    diff.add_argument("--context-lines", type=int)
    diff.add_argument("--whitespace", choices=["show", "ignore-all"])
    add_common_args(diff)
    diff.set_defaults(func=cmd_diff)

    ac = sub.add_parser("add-comment", help="add a comment to a PR")
    _add_pr_locator(ac)
    ac.add_argument("--text", required=True)
    ac.add_argument("--parent", help="parent comment id (for replies)")
    add_common_args(ac)
    ac.set_defaults(func=cmd_add_comment)

    lc = sub.add_parser("list-comments", help="list comments on a PR")
    _add_pr_locator(lc)
    lc.add_argument("--limit", type=int, default=100)
    add_common_args(lc)
    lc.set_defaults(func=cmd_list_comments)

    ap = sub.add_parser("approve", help="approve a PR (as the PAT owner)")
    _add_pr_locator(ap)
    add_common_args(ap)
    ap.set_defaults(func=cmd_approve)

    un = sub.add_parser("unapprove", help="remove your approval from a PR")
    _add_pr_locator(un)
    add_common_args(un)
    un.set_defaults(func=cmd_unapprove)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
