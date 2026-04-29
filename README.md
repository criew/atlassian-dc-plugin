# Atlassian DC Plugin

Skills for Jira, Confluence, and Bitbucket Data Center deployments — packaged
as a single plugin. Multi-instance support via aliased credentials, per-instance
markdown rules, and CLI scripts that survive being driven by weak LLMs.

This file describes the architecture, the separation between **distributable
plugin** and **local development setup**, and the rationale behind key design
decisions. It is the entry point for understanding the codebase.

## Quick Start

For end users (consuming the plugin):
- See `atlassian-dc-plugin/README.md` for setup of `instances.json` and rules.
- Pre-built skill scripts run via `uv run` or plain `python`.

For developers (working in this repo):
- `docker/docker-compose.yml` brings up local Jira / Confluence / Bitbucket DC.
- `atlassian-dc-plugin/tests/` is the reproducible test suite (`pytest`).
- The setup helper `setup_jira.py` wraps the wizard but **expects an admin
  username via `JIRA_ADMIN_USER` env var (default: `admin`)**. Pick anything
  you like; nothing else in the codebase hard-codes a specific admin name.

## Three Layers

The project is split into three layers with sharply different lifecycles and
distribution scopes:

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1 — PLUGIN (distributed, versioned, shared with users)    │
│  Path: atlassian-dc-plugin/                                       │
│  Contains: SKILL.md files, Python scripts, shared library,        │
│            plugin manifest, README, examples, tests of the code.  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Layer 2 — USER CONFIG (per-user, never in repo)                 │
│  Path: ~/.config/atlassian/  (Linux/macOS)                       │
│        %APPDATA%\atlassian\  (Windows)                           │
│        $ATLASSIAN_CONFIG_DIR (override)                           │
│  Contains: instances.json (credentials),                          │
│            rules/<alias>.md (per-instance business rules).        │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Layer 3 — DEV-ONLY (this repo, NOT shipped with the plugin)     │
│  Path: docker/, setup_jira.py, setup_jira_http.py,                │
│        atlassian-dc-plugin/tests/                                 │
│  Contains: docker-compose for a local Jira DC, helper scripts to  │
│            seed the wizard, automated tests for the plugin code.  │
└──────────────────────────────────────────────────────────────────┘
```

The plugin (Layer 1) is the only thing a user installs. Layer 2 is something
they hand-author (or generate once via setup script). Layer 3 only exists in
this repo — it is the development environment we use to build and verify
Layer 1 against a real Jira instance.

## Layer 1: Plugin Structure

```
atlassian-dc-plugin/
├── .claude-plugin/
│   └── plugin.json                  # Claude Code plugin manifest
├── README.md                        # User-facing setup guide
├── pyproject.toml                   # uv-runnable, declares deps
├── instances.json.example           # template for user config
├── rules.example.md                 # template for per-instance rules
├── shared/
│   └── _common.py                   # AtlassianClient, multi-instance loader,
│                                    # CLI helpers, error mapping, rules loader
├── skills/
│   └── jira-dc/
│       ├── SKILL.md                 # thin Skill manifest — when to trigger,
│       │                            # script inventory, common flags
│       └── scripts/
│           ├── core/                # main CRUD: issue, search, project, version
│           ├── workflow/            # transitions, comments
│           └── utility/             # whoami, fields, rules
└── tests/                           # unit + CLI tests for the scripts above
```

### Why three sub-folders inside `scripts/`?

Inspired by `netresearch/jira-skill`. Splitting `core/workflow/utility` reduces
visual noise inside any one folder and helps the LLM pick the right script by
intent rather than by flat name. `scripts/core/` is what the LLM reaches for
first; the others are specializations.

### Why a `shared/` library at the plugin root?

When we add `confluence-dc/` and `bitbucket-dc/` skills, they will share the
same `AtlassianClient`, the same instance loader, and the same CLI conventions.
Having `shared/` at the plugin root (not inside any skill) makes that future
ergonomic. Today only `jira-dc` consumes it, but the structure is ready.

### Why thin SKILL.md?

We deliberately keep SKILL.md short (~80 lines for jira-dc). The full reference
lives in each script's `--help`, in `editmeta`/`createmeta` discovery, and in
the user's `rules/<alias>.md`. This matters for weak LLMs: they should not
swallow 700 lines of context every time the skill is loaded. They load SKILL.md
to know **when** to act, then call scripts to **act**, then read script output
to **decide next steps**.

## Layer 2: User Config

### `instances.json`

Single file, server-centric structure. One entry per "instance" (logical
deployment), with sub-entries for each Atlassian product on that server.

```json
{
  "default": "prod",
  "instances": {
    "prod": {
      "jira":       {"url": "...", "token": "...", "ssl_verify": true},
      "confluence": {"url": "...", "token": "..."},
      "bitbucket":  {"url": "...", "token": "..."}
    },
    "staging": { ... }
  }
}
```

Resolution order for the active alias (in `_common.load_instance()`):
1. `--instance ALIAS` CLI arg (explicit)
2. `ATLASSIAN_INSTANCE` env var
3. `default` field of the file

File location resolution:
1. `$ATLASSIAN_INSTANCES_FILE` env var (override)
2. `~/.config/atlassian/instances.json` (Linux/macOS, Git Bash, WSL)
3. `%APPDATA%\atlassian\instances.json` (native Windows)

### `rules/<alias>.md`

One markdown file per instance alias. Plain prose plus structured headings:
`## Global` for cross-project rules, `## Project <KEY>` for project-specific
ones. The `jira_rules.py show [--project KEY]` script reads these; SKILL.md
instructs the LLM to call it before any write op.

Why markdown, not JSON? Because rules are written and read by humans, not
parsed strictly. Free-form prose lets the user explain *why* a rule exists,
and the LLM can interpret nuance. JSON would force a schema we cannot fully
specify in advance.

Why one file per instance (instead of per project)? At <20 projects, a single
file per instance keeps everything in one place and is easy to grep/edit.
Splitting per project becomes worthwhile only when a single file gets unwieldy.

### Why is user config separated?

- The plugin is in version control and shared across machines / users / orgs.
  Credentials and house rules are not.
- A future plugin update should never overwrite a user's tweaks.
- A user can switch their `default` alias without touching plugin files.
- `$ATLASSIAN_CONFIG_DIR` lets a power user (or automation) point at an
  arbitrary location, e.g. an encrypted Vault mount.

## Layer 3: Dev-Only Bits

### `docker/docker-compose.yml`

Spins up Jira Software Data Center 9.12 + Postgres on `localhost:8080`. Dev
loop: `docker compose up -d` → wait for wizard → run setup script (or click
through manually) → exercise the skill scripts against the live instance.

### `setup_jira.py` (Playwright) and `setup_jira_http.py` (HTTP)

Helper scripts to seed the Jira setup wizard for an unattended dev loop.
Status today: partially working — Jira's wizard has JS-rendered fields and
strict XSRF that make full automation brittle. Realistic dev workflow is to
click the wizard once manually (about 60 seconds), then run a small login +
PAT-creation script (`/tmp/get_pat.py` style). The setup scripts are
intentionally **not** part of the plugin — they exist for our own dev loop.

### `atlassian-dc-plugin/tests/`

Pytest suite. Three layers of tests:

1. **`test_config_loader.py`** — unit tests for instance/rules resolution.
   Covers missing files, bad JSON, alias precedence, project-filtered rules.

2. **`test_client_errors.py`** — HTTP error mapping. Uses `responses` to mock
   Jira; verifies that 401/403/404/400/500 turn into the right exception class
   with a clear, actionable message. Critically: tests that the PAT never
   leaks into stringified errors.

3. **`test_cli_error_visibility.py`** — subprocess tests. Calls the actual
   scripts as a weak LLM would, asserts:
   - failures use exit code ≠ 0 and put errors on stderr
   - stdout never looks like a "silent success" on failure
   - `--dry-run` always emits its marker, **even with `--quiet`**
   - unknown alias lists available aliases (not silent dead end)
   - JSON dry-run payload includes `"executed": false`

These tests run with **no real Jira required**; they are about code-level
robustness. The container is for end-to-end exploratory testing.

**Tests are NOT shipped with the plugin.** They live inside the plugin
directory only because pytest's discovery is path-relative; production
distribution would carry only the runtime files.

## Key Design Decisions, Recorded

### PAT-only auth, DC-only

We deliberately reject Cloud and Basic Auth code paths.
- **Why:** the user's deployment target is exclusively DC. Cloud-aware code
  (auto-detect API v2/v3, basic auth fallback) carries dead code that
  confuses weak LLMs. `_common.py` is leaner because of this.
- **How to apply:** `JiraClient` uses `Authorization: Bearer <PAT>` always;
  it does not negotiate.

### Multi-instance via alias, not multi-config

Variant 1 (the curl-style skill) had per-product files
(`jira-instances.json`, `confluence-instances.json`, …). We chose a single
unified file with server-centric aliases instead.
- **Why:** in practice, a "company" has Jira + Confluence + Bitbucket on
  related servers. One alias = one set of credentials covering all three.
- **How to apply:** when you add `confluence-dc`, the same `local` alias
  picks up `confluence` sub-entry automatically.

### Thin SKILL.md + Subcommand-style scripts

Borrowed from `netresearch/jira-skill`. SKILL.md describes triggers and
inventories scripts; it does **not** duplicate per-call argument schemas
(those live in `--help`). Subcommand pattern (`jira_issue.py get|create|update|delete`)
keeps the script count low and groups related operations.
- **Why:** weak LLMs make better choices among 7 scripts than among 25.
  Each script's `--help` is short and self-contained.

### Universal CLI flags

`--instance --json --quiet --debug --dry-run` on every script.
- **Why:** consistency across scripts means an LLM that learned them on one
  script transfers the knowledge to all others. Reduces failure modes.
- **`--dry-run` is non-negotiable for write ops:** even with `--quiet`, the
  marker is emitted to stderr. A test enforces this.

### Field discovery via three endpoints

`jira_fields.py` exposes `list` (global), `editmeta KEY` (per-issue), and
`createmeta --project --type` (per-create-context). The `editmeta`/`createmeta`
calls return REQ flags and allowed values — which is what the LLM needs when
the user asks "create an issue with high priority" and we need to know if
"high" is the local label or if it's "Hoch".

### Server-side rules live in user config, not in code

Rules are markdown files in `~/.config/atlassian/rules/<alias>.md`. The plugin
exposes them via `jira_rules.py show`; SKILL.md tells the LLM to consult
them before write ops. Hard validation in scripts is intentionally **not**
implemented as default — it would require duplicating each rule both in
markdown (for the LLM) and in Python (for hard checks). We can add hard checks
selectively for unrecoverable cases, but the baseline is markdown-only.

### Errors are Loud

Every error path in `_common.py` raises a typed `SkillError` subclass
(`ConfigError`, `AuthError`, `NotFoundError`, `ValidationError`, `APIError`)
with its own `exit_code`. `run()` catches them, writes a clear `error: ...`
line to stderr, and exits with the right code. **The token is never in the
error message.** Tests pin this.

## Distribution Plan

What gets shipped in the plugin (Layer 1):
- `atlassian-dc-plugin/.claude-plugin/plugin.json`
- `atlassian-dc-plugin/README.md`, `pyproject.toml`
- `atlassian-dc-plugin/instances.json.example`, `rules.example.md`
- `atlassian-dc-plugin/shared/`
- `atlassian-dc-plugin/skills/jira-dc/`

What stays in this repo for development only:
- `docker/`
- `setup_jira.py`, `setup_jira_http.py`, `setup-screenshots/`
- `atlassian-dc-plugin/tests/`
- This `DESIGN.md`

When packaging, exclude `tests/` and the dev helpers. The plugin manifest
points at `skills/jira-dc/` and `shared/`; nothing else needs to ship.

## Future Work / Roadmap

Tracked outside this doc, but for orientation:
- `confluence-dc/` and `bitbucket-dc/` skills following the same pattern.
- More Jira ops: worklog, attachments, sprints/boards, watchers, issue links.
- Hard validation of selected rules in scripts (Ebene 3 in earlier discussion).
- Plugin manifests for OpenCode and Codex, alongside the Claude Code one.
