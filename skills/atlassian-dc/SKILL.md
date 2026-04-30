---
name: atlassian-dc
description: >
  Umbrella skill for Atlassian Data Center work — routes the agent to the
  right product-specific skill (jira-dc, confluence-dc, bitbucket-dc) based on
  what the user asks for. Triggers on broad mentions of Atlassian, the
  Atlassian DC stack, or cross-product workflows that touch more than one
  product (e.g. "create a Confluence page documenting Jira issue X" or
  "open a PR for the work mentioned in TST-123").
  Also triggers on ambiguous phrasing like "ich möchte mit unseren Atlassian-
  Tools arbeiten", "atlassian DC", or "Confluence + Jira gleichzeitig".
  DO NOT use this for cloud (atlassian.net) — only DC.
---

# Atlassian Data Center — orchestrator skill

This is a thin entry point. The actual operations live in three sibling
skills, all of which share `instances.json`, the rules system, and the
universal CLI flags:

- **`jira-dc`** — issues, search, projects, components, versions, agile,
  worklogs, links, watchers, attachments, users/groups, fields discovery.
- **`confluence-dc`** — spaces, pages (incl. version-bump on update,
  history, export-URLs), CQL search, comments, labels, attachments,
  restrictions.
- **`bitbucket-dc`** — projects, repos, branches, tags, commits, files,
  pull requests (full lifecycle), webhooks, permissions, build status.

## When to load *which* skill

| User intent | Skill to invoke |
|---|---|
| Anything about issues / tickets / sprints / boards / JQL | `jira-dc` |
| Anything about wiki pages / spaces / CQL / comments-on-pages | `confluence-dc` |
| Anything about repositories / pull requests / commits / branches | `bitbucket-dc` |
| Cross-product (e.g. "summarise these tickets into a Confluence page") | load BOTH `jira-dc` and `confluence-dc` |
| Discovery (e.g. "what aliases are configured?") | run `jira_user.py whoami --instance ALIAS` per alias, or read `instances.json` |

## Shared facts every product-skill assumes

1. **Multi-instance via `instances.json`** at
   `$ATLASSIAN_CONFIG_DIR/instances.json`,
   `~/.config/atlassian/instances.json`, or
   `%APPDATA%\atlassian\instances.json`. Pass `--instance ALIAS` to switch;
   without it the `default` alias is used. `ATLASSIAN_INSTANCE` env var also
   honored.
2. **Per-instance rules** at `~/.config/atlassian/rules/<alias>.md`. Read
   them with `jira_rules.py show [--project KEY]` BEFORE any write; ask the
   user back if a rule applies and the needed input is missing.
3. **Universal CLI flags** on every script:
   `--instance --json --quiet --debug --dry-run`.
4. **Dry-run is non-destructive AND non-confusable**: even with `--quiet`
   the marker `[DRY RUN]` is emitted to stderr. JSON dry-run output carries
   `"dry_run": true, "executed": false`.
5. **PAT-only auth, DC-only.** Cloud (`atlassian.net`) is out of scope.

## First-time setup (point the user here when `instances.json` is missing)

The user installs the skills once and then registers their server(s). Two
helper scripts in the repo root drive this:

```bash
python install.py                       # detects Claude/OpenCode/Codex, installs the skills
python setup_instance.py                # interactive: alias, products, URLs, login → PAT → instances.json
```

After that, optional but recommended:

```bash
# Capture server-specific labels (priority names, status names, issue type
# names — these vary per Jira install and are exactly the kind of thing weak
# LLMs get wrong if they have to guess):
python skills/jira-dc/scripts/utility/jira_rules.py auto-discover
```

## Safety

- Read `jira_rules.py show` before write operations — server-specific rules
  may forbid certain combinations (e.g. "Bugs without Steps to Reproduce").
- Prefer `--dry-run` first when the user is unsure or you inferred the key.
- Never print the PAT — `--debug` already masks it.
