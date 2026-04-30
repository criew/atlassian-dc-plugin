---
name: confluence-dc
description: >
  Use this skill for any operation against a Confluence Server / Data Center instance.
  Covers spaces, pages (CRUD, children, ancestors), CQL search, comments, labels,
  attachments, and users. Triggers on mentions of Confluence, wiki, page, space,
  CQL, blogpost, attachment, label — and on instructions like "auf Staging" or
  "on prod" that name a configured instance.
  DO NOT use for Confluence Cloud (atlassian.net) — this skill targets on-premise DC only.
---

# Confluence Data Center Skill

Invoke pre-built Python scripts via Bash. The scripts handle authentication, pagination,
version bumps, error handling, and output formatting. You only choose the script and arguments.

## Configuration

Credentials live in `instances.json` — see plugin README for setup. Each instance has an
alias; pass `--instance ALIAS` to switch, otherwise the default is used. Each instance
needs a `confluence` block (`url` and `token` — Personal Access Token, PAT-only).

## Universal CLI flags (every script supports these)

| Flag | Effect |
|---|---|
| `--instance ALIAS` (`-i`) | Pick instance from `instances.json` |
| `--json` | Raw JSON output |
| `--quiet` (`-q`) | Errors only |
| `--debug` | Verbose request logging on stderr |
| `--dry-run` | Print intended request without sending (write ops only) |

## Page body format

Confluence stores page bodies in **storage format** — XHTML such as
`<p>...</p>`, `<h2>...</h2>`, `<ac:structured-macro ...>...</ac:structured-macro>`.
All `--content` / `--body` arguments expect storage-format markup, not Markdown.
For ready-to-use page templates see `variant1/confluence-server-api/templates/page-templates.md`.

## Page updates and versioning

`confluence_page.py update` is **transparent**: you supply the fields you want to change,
the script fetches the current `version.number`, increments it by 1, and PUTs the
required envelope `{type, title, body, version: {number: N+1}}`. You never have to do
the bump yourself.

## Scripts

Run with `uv run <script> <subcommand> [args]` from the plugin root, or directly with
`python <script>` if `requests` is on the path.

### scripts/core/confluence_space.py
Subcommands:
- `list [--type global|personal] [--limit N]`
- `get KEY` — space metadata
- `create --key KEY --name NAME [--description ...] [--type global|personal]`

### scripts/core/confluence_page.py
Subcommands:
- `get --id ID` *or* `get --title "..." --space KEY` — fetch a page (with body in storage format)
- `create --space KEY --title "..." --content "<p>...</p>" [--parent ID] [--type page|blogpost]`
- `update ID [--title ...] [--content ...]` — version bump is automatic
- `delete ID` (moves to trash; pass `--purge` to permanently delete trashed content)
- `children ID [--limit N]` — direct child pages
- `ancestors ID` — parent chain
- `history ID [--limit N]` — list all versions of a page (number, when, author, message)
- `export ID [--format pdf|word]` — print the export URL. **Confluence DC's
  export endpoints are servlets, not REST — open the URL in a logged-in
  browser, or curl with the same session cookies.**

### scripts/core/confluence_search.py
- `confluence_search.py "CQL or text" [--limit N] [--start N] [--expand body.storage,version]`
- If your query has no CQL operators (`=`, `~`, `AND`, `OR`, `NOT`), it is wrapped as
  `text ~ "..." OR title ~ "..."` automatically.
- Pagination handled automatically up to `--limit` via `_links.next`.

### scripts/workflow/confluence_comment.py
- `list ID [--depth all|root]` — comments on a page
- `add ID --body "<p>...</p>" [--parent COMMENT_ID]`
- `delete COMMENT_ID`

### scripts/workflow/confluence_label.py
- `list ID`
- `add ID --label NAME [--label NAME ...] [--prefix global|my|team]`
- `remove ID --label NAME`

### scripts/workflow/confluence_attachment.py
- `list ID [--filename NAME]`
- `add ID --file path/to/file [--comment "..."]`
- `get ATTACHMENT_ID` — metadata
- `delete ATTACHMENT_ID`

Multipart uploads use the documented `X-Atlassian-Token: no-check` header and let
`requests` pick the multipart boundary itself (no manual `Content-Type`).

### scripts/workflow/confluence_restriction.py
Page-level read/edit permissions. Operations are `read` or `update`.
- `get ID` — show current users + groups granted each operation
- `set ID --operation read|update [--user U ...] [--group G ...]` — replaces the
  given operation's grants entirely; pass at least one `--user` or `--group`
- `clear ID [--operation read|update]` — remove restrictions (omit
  `--operation` to wipe both)

### scripts/utility/confluence_user.py
- `whoami` — verify the PAT and show current user
- `search QUERY [--limit N]` — find users by username/email

## When generating code for the user

If the user wants a standalone script (not a one-off call), prefer importing from
`_confluence.py` (`ConfluenceClient`) and `_common.py` (`load_instance`) from this skill's `scripts/` directory
so the multi-instance logic is reused. Never inline tokens or URLs.

## Safety

- For destructive operations (`delete`), prefer `--dry-run` first when the user is
  uncertain or the page id was inferred rather than explicitly given.
- Never print the PAT — `--debug` already masks it.
- Confluence requires unique page titles **within a space** — `create` will fail
  with a clear ValidationError if a duplicate is detected.
