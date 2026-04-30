---
name: bitbucket-dc
description: >
  Use this skill for any operation against a Bitbucket Server / Data Center instance
  (v7.x+ / v8.x+). Covers projects, repositories, branches, tags, commits, file
  browsing, and pull requests (create, update, decline, merge, comment, approve).
  Triggers on mentions of Bitbucket, Stash, repo, repository, pull request, PR,
  branch, tag, commit, fork, code review — and on instructions like "auf Staging"
  or "on prod" that name a configured instance.
  DO NOT use for Bitbucket Cloud (bitbucket.org) — this skill targets on-premise DC only.
---

# Bitbucket Data Center Skill

Invoke pre-built Python scripts via Bash. The scripts handle authentication, pagination,
error handling, and output formatting. You only choose the script and arguments.

## Configuration

Credentials live in `instances.json` — see README for setup. Each instance has an
alias; pass `--instance ALIAS` to switch, otherwise the default is used. The Bitbucket
PAT lives under `instances.<alias>.bitbucket` (separate from `jira` / `confluence`).

## Universal CLI flags (every script supports these)

| Flag | Effect |
|---|---|
| `--instance ALIAS` (`-i`) | Pick instance from `instances.json` |
| `--json` | Raw JSON output |
| `--quiet` (`-q`) | Errors only |
| `--debug` | Verbose request logging on stderr |
| `--dry-run` | Print intended request without sending (write ops only) |

## Project keys

Personal repositories use `~username` as the project key (e.g. `~jsmith`). Pass that
directly as `--project ~jsmith` when forking into your personal area or browsing your
own repos.

## Scripts

Run with `uv run <script> <subcommand> [args]` from the repo root, or directly with
`python <script>` if `requests` is on the path.

### scripts/core/bitbucket_project.py
Subcommands:
- `list [--name FILTER] [--limit N]`
- `get KEY`
- `create --key KEY --name NAME [--description ...]`

### scripts/core/bitbucket_repo.py
Subcommands:
- `list [--project KEY] [--name FILTER] [--limit N]` — without `--project` lists across all projects
- `get --project KEY --repo SLUG`
- `create --project KEY --name NAME [--description ...] [--default-branch main] [--forkable] [--no-forkable]`
- `fork --project KEY --repo SLUG [--target-project ~jsmith] [--name NAME]`
- `delete --project KEY --repo SLUG`

### scripts/core/bitbucket_branch.py
Subcommands:
- `list --project KEY --repo SLUG [--filter TEXT] [--order ALPHABETICAL|MODIFICATION] [--details] [--limit N]`
- `get-default --project KEY --repo SLUG`
- `create --project KEY --repo SLUG --name NAME [--start-point refs/heads/main] [--message ...]`
- `delete --project KEY --repo SLUG --name NAME`

### scripts/core/bitbucket_tag.py
Subcommands:
- `list --project KEY --repo SLUG [--filter TEXT] [--limit N]`
- `create --project KEY --repo SLUG --name v1.0.0 [--start-point ...] [--message ...]`
- `delete --project KEY --repo SLUG --name v1.0.0`

### scripts/core/bitbucket_commit.py
Subcommands:
- `list --project KEY --repo SLUG [--branch NAME|--until REF] [--since REF] [--path FILE] [--merges include|exclude|only] [--limit N]`
- `get --project KEY --repo SLUG --id COMMITHASH`

### scripts/core/bitbucket_file.py
Subcommands:
- `get-content --project KEY --repo SLUG --path FILE [--at refs/heads/main] [--raw]`
- `list-dir --project KEY --repo SLUG --path DIR [--at REF] [--limit N]`
- `search QUERY [--type code|file|repository|commit] [--project KEY] [--repo SLUG] [--limit N]`

### scripts/core/bitbucket_pr.py
Subcommands:
- `list --project KEY --repo SLUG [--state OPEN|MERGED|DECLINED|ALL] [--direction INCOMING|OUTGOING] [--at refs/heads/main] [--limit N]`
- `get --project KEY --repo SLUG --id PR_ID`
- `create --project KEY --repo SLUG --title "..." --from-branch SRC --to-branch DST [--description ...] [--reviewer NAME --reviewer NAME]`
- `update --project KEY --repo SLUG --id PR_ID --version V [--title ...] [--description ...] [--to-branch ...] [--reviewer NAME --reviewer NAME]`
- `decline --project KEY --repo SLUG --id PR_ID --version V`
- `merge --project KEY --repo SLUG --id PR_ID --version V [--message ...] [--strategy merge-commit|squash|fast-forward]`
- `diff --project KEY --repo SLUG --id PR_ID [--context-lines N] [--whitespace show|ignore-all]`
- `add-comment --project KEY --repo SLUG --id PR_ID --text "..." [--parent COMMENT_ID]`
- `list-comments --project KEY --repo SLUG --id PR_ID [--limit N]`
- `approve --project KEY --repo SLUG --id PR_ID`
- `unapprove --project KEY --repo SLUG --id PR_ID`

### scripts/utility/bitbucket_user.py
- `whoami` — verify the PAT and show the current user
- `search QUERY [--limit N]`

### scripts/core/bitbucket_webhook.py
Webhooks are scoped to a single repository.
- `list --project KEY --repo SLUG [--limit N]`
- `get --project KEY --repo SLUG ID`
- `create --project KEY --repo SLUG --name N --url URL --event repo:refs_changed --event pr:opened [--secret S] [--active true|false]`
- `update --project KEY --repo SLUG ID --name N --url URL --event ... [--secret] [--active]`
- `delete --project KEY --repo SLUG ID`
- `test --project KEY --repo SLUG [--url override]`

Common events: `repo:refs_changed`, `pr:opened`, `pr:merged`, `pr:declined`,
`pr:comment:added`, `pr:reviewer:approved`.

### scripts/core/bitbucket_permission.py
Project-level by default; pass `--repo` to scope to a single repository.
- `list --project KEY [--repo SLUG] [--limit N]`
- `grant-user --project KEY [--repo SLUG] --user U --permission PROJECT_READ|PROJECT_WRITE|PROJECT_ADMIN`
  (or `REPO_READ|REPO_WRITE|REPO_ADMIN` when `--repo` is given)
- `grant-group --project KEY [--repo SLUG] --group G --permission ...`
- `revoke-user --project KEY [--repo SLUG] --user U`
- `revoke-group --project KEY [--repo SLUG] --group G`

**Bitbucket PATs cannot grant global admin permissions** (`SYS_ADMIN`,
`PROJECT_CREATE`). Creating new projects therefore needs basic auth — see
`dev/auto_setup.py` which seeds a default test project on first install.

### scripts/core/bitbucket_build.py
Build statuses live on commits, served from a separate API
(`/rest/build-status/1.0/`).
- `list COMMIT_SHA [--limit N]`
- `post COMMIT_SHA --state SUCCESSFUL|INPROGRESS|FAILED|CANCELLED --key MY-CI-42 --name "Build #42" --url https://ci.example/42 [--description …]`

## When generating code for the user

If the user wants a standalone script (not a one-off call), prefer importing from
`_bitbucket.py` (`BitbucketClient`, `get_bitbucket`) and `_common.py`
(`load_instance`) from this skill's `scripts/` directory so the multi-instance logic and PAT handling are reused. Never
inline tokens or URLs.

## Safety

- For destructive operations (`delete`, `decline`, `merge`), prefer `--dry-run` first
  when the user is uncertain or the repo/PR id was inferred rather than explicitly given.
- Bitbucket merge / decline / update / delete-comment requires the current `version`
  (optimistic locking) — fetch the PR first if you don't have it.
- Never print the PAT — `--debug` already masks it.
