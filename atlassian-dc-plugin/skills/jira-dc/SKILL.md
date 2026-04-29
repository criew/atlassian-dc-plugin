---
name: jira-dc
description: >
  Use this skill for any operation against a Jira Server / Data Center instance (v9.x+).
  Covers issues (create, read, update, delete, transition, comment), JQL search, projects,
  fields, and users. Triggers on mentions of Jira, JIRA, issue tracker, ticket, JQL, sprint,
  board, transition, epic, story, subtask, or workflow — and on instructions like
  "auf Staging" or "on prod" that name a configured instance.
  DO NOT use for Jira Cloud (atlassian.net) — this skill targets on-premise DC only.
---

# Jira Data Center Skill

Invoke pre-built Python scripts via Bash. The scripts handle authentication, pagination,
error handling, and output formatting. You only choose the script and arguments.

## Configuration

Credentials live in `instances.json` — see plugin README for setup. Each instance has an
alias; pass `--instance ALIAS` to switch, otherwise the default is used.

## Universal CLI flags (every script supports these)

| Flag | Effect |
|---|---|
| `--instance ALIAS` (`-i`) | Pick instance from `instances.json` |
| `--json` | Raw JSON output |
| `--quiet` (`-q`) | Errors only |
| `--debug` | Verbose request logging on stderr |
| `--dry-run` | Print intended request without sending (write ops only) |

## Scripts

Run with `uv run <script> <subcommand> [args]` from the plugin root, or directly with
`python <script>` if `requests` is on the path.

### scripts/core/jira_issue.py
Subcommands:
- `get KEY` — fetch an issue
- `create --project KEY --type Bug --summary "..." [--description ...] [--priority High] [--assignee NAME] [--label X --label Y]`
- `update KEY [--summary ...] [--description ...] [--priority ...] [--assignee ...]`
- `delete KEY`

### scripts/core/jira_search.py
- `jira_search.py "JQL string" [--fields summary,status] [--limit 50]`
- Pagination is handled automatically up to `--limit`.

### scripts/core/jira_project.py
Subcommands:
- `list` — all projects
- `get KEY` — project details
- `create --key KEY --name NAME --lead USERNAME [--type software|business] [--template ...]`

### scripts/workflow/jira_transition.py
Subcommands:
- `list KEY` — available transitions for an issue
- `do KEY --to "Done" [--comment "..."]` — execute transition by name or id

### scripts/workflow/jira_comment.py
- `add KEY --body "..."`
- `list KEY`

### scripts/workflow/jira_worklog.py
- `list KEY`
- `add KEY --time-spent "1h 30m" [--comment ...] [--started ISO8601]`
- `update KEY ID [--time-spent ...] [--comment ...]`
- `delete KEY ID`

### scripts/workflow/jira_watcher.py
- `list KEY`
- `add KEY [--user NAME]` (default: yourself, i.e. the PAT owner)
- `remove KEY [--user NAME]`

### scripts/workflow/jira_link.py
- `types` — list available issue link types
- `add --type Blocks --outward KEY --inward KEY [--comment ...]`
- `remove ID` — remove a link by id
- `link-epic KEY --epic EPICKEY [--epic-field customfield_X]`
- `unlink-epic KEY [--epic-field customfield_X]`

### scripts/core/jira_version.py
- `list --project KEY`
- `create --project KEY --name "1.0" [--description ...] [--release-date YYYY-MM-DD]`
- `release ID [--release-date YYYY-MM-DD]`

### scripts/core/jira_agile.py
Boards: `boards [--project KEY] [--type scrum|kanban]` · `board ID` · `board-issues ID [--jql ...]`
Sprints: `sprints --board ID [--state future|active|closed]` · `sprint ID` · `sprint-issues ID`
       · `sprint-create --board ID --name N [--start-date ...] [--end-date ...] [--goal ...]`
       · `sprint-update ID [--state ...] [--name ...] [--start-date ...] [--end-date ...]`
       · `sprint-move ID --issue KEY [--issue KEY ...]` (move into sprint)
       · `backlog-move --issue KEY [--issue KEY ...]` (out of any sprint)
Epics:  `epic-issues EPICKEY [--jql ...]`

### scripts/core/jira_attachment.py
- `list KEY`
- `add KEY --file path/to/file`
- `get ID` — metadata
- `delete ID`

### scripts/utility/jira_fields.py
- `list [--keyword X]` — discover field IDs (incl. customfield_*)
- `editmeta KEY` — fields editable on this concrete issue, with REQ flag and allowed values
- `createmeta --project KEY [--type NAME]` — fields available for creation, per issue type

### scripts/utility/jira_user.py
- `whoami` — verify the PAT and show current user
- `search QUERY` — find users
- `create --username U --password P --email E --display-name "..."` (admin)

## When generating code for the user

If the user wants a standalone script (not a one-off call), prefer importing from
`shared/_common.py` (`load_instance`, `JiraClient`) so the multi-instance logic is reused.
Never inline tokens or URLs.

## Safety

- For destructive operations (`delete`, `transition`), prefer `--dry-run` first when the
  user is uncertain or the issue key was inferred rather than explicitly given.
- Never print the PAT — `--debug` already masks it.
