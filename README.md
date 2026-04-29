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
│  Path: docker/, dev/, atlassian-dc-plugin/tests/                  │
│  Contains: docker-compose for the full Jira/Confluence/Bitbucket  │
│            DC stack, auto-setup pipeline (license fetch + wizard  │
│            walk + PAT bootstrap), automated tests for the skills. │
└──────────────────────────────────────────────────────────────────┘
```

The plugin (Layer 1) is the only thing a user installs. Layer 2 is something
they hand-author (or generate once via the setup pipeline). Layer 3 only
exists in this repo — it is the development environment we use to build and
verify Layer 1 against real Jira / Confluence / Bitbucket instances.

## Layer 1: Plugin Structure

```
atlassian-dc-plugin/
├── .claude-plugin/
│   └── plugin.json                  # Claude Code plugin manifest (lists all 3 skills)
├── README.md                        # user-facing setup guide
├── pyproject.toml                   # uv-runnable, declares deps
├── instances.json.example           # template for user config
├── rules.example.md                 # template for per-instance rules
├── shared/
│   ├── _common.py                   # config + rules loader, errors, CLI helpers,
│   │                                # JiraClient
│   ├── _confluence.py               # ConfluenceClient + paginate() (_links.next)
│   └── _bitbucket.py                # BitbucketClient + paginate() (isLastPage)
├── skills/
│   ├── jira-dc/                     # 16 scripts — issue, search, project,
│   │                                # version, component, agile, attachment,
│   │                                # transition, comment, worklog, link,
│   │                                # watcher, user, group, fields, rules
│   ├── confluence-dc/               # 8 scripts — space, page (with auto
│   │                                # version-bump, history, export-url),
│   │                                # search (CQL), comment, label,
│   │                                # attachment, restriction, user
│   └── bitbucket-dc/                # 11 scripts — project, repo, branch,
│                                    # tag, commit, file (incl. code search),
│                                    # pr (full lifecycle), webhook,
│                                    # permission, build (build-status), user
└── tests/                           # 172 pytest cases across 8 test files
```

### Why three sub-folders inside `scripts/`?

Inspired by `netresearch/jira-skill`. Splitting `core/workflow/utility` reduces
visual noise inside any one folder and helps the LLM pick the right script by
intent rather than by flat name. `scripts/core/` is what the LLM reaches for
first; the others are specializations.

### `shared/` library at the plugin root

All three skills (`jira-dc`, `confluence-dc`, `bitbucket-dc`) share:
- `_common.py` — generic helpers: instance + rules loader, error classes,
  argparse helpers, `emit()` / `emit_dry_run()` output helpers, the universal
  CLI flag block, the `JiraClient` HTTP wrapper.
- `_confluence.py` — `ConfluenceClient` + `paginate()` helper for `_links.next`.
- `_bitbucket.py` — `BitbucketClient` + `paginate()` for `start`/`limit` /
  `isLastPage`.

Each product client class has the same interface (`get`/`post`/`put`/`delete`,
PAT-only Bearer auth, identical error mapping). Putting clients next to each
other in `shared/` lets us add a `seed_data.py` or other dev tooling without
duplicating client code.

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

Spins up the full Atlassian DC stack on a shared Postgres:

| Product | Port | DB | Captcha-Disable JVM Arg (preloaded) |
|---|---|---|---|
| Jira Software 9.12 | 8080 | `jiradb` | `-Djira.maximum.authentication.attempts.allowed=99999` |
| Confluence 8.5 | 8090 | `confluencedb` | `-Dconfluence.security.captcha.threshold=99999` |
| Bitbucket 8.19 | 7990 / 7999 | `bitbucketdb` | `-Dauth.captcha.threshold=0` |

The captcha JVM args matter — without them, Jira/Confluence start blocking the
admin user after a handful of login attempts and the auto-setup runs into
"username/password incorrect" even when the credentials are correct.

`postgres-init.sh` creates per-product database roles + databases on first
boot. Drop volumes with `docker compose down -v` to fully reset.

### Auto-Setup Pipeline (`dev/`)

The full bring-up — wizard click-through, license input, admin account, PAT
creation, `instances.json` write — works **end-to-end without user interaction**
for all three products. This took some iteration; documenting the moving
parts so future-you can debug it quickly.

#### `dev/auto_setup.py` — primary entry point

```bash
python dev/auto_setup.py jira       --base-url http://localhost:8080
python dev/auto_setup.py confluence --base-url http://localhost:8090
python dev/auto_setup.py bitbucket  --base-url http://localhost:7990
```

For each product the script:
1. Detects whether the wizard is up or already past it (skips if past).
2. Walks the install wizard via plain HTTP POSTs (no Playwright on the happy
   path). Each product has its own quirks captured in dedicated functions.
3. Fetches a 3-hour Time-Bomb license via `dev/fetch_license.py` and feeds it
   into the right form field (each product names it differently — see below).
4. Logs in (`/login.jsp` for Jira, `/dologin.action` for Confluence,
   `/j_atl_security_check` for Bitbucket) and creates a Personal Access Token
   via the product's REST endpoint.
5. Writes the token into `instances.json` under `instances.local.<product>`
   and verifies with a real API call.

Admin credentials default to `admin` / `admin123` and are overridable via
`JIRA_ADMIN_USER`/`JIRA_ADMIN_PASS` etc. The script never hard-codes a
specific admin name.

#### `dev/fetch_license.py` — auto-license

Scrapes the public
[Atlassian Time-Bomb licenses page](https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/)
and prints (or copies to clipboard with `--copy`) the right key for the
requested product. Three-hour validity, no Atlassian.com login required.

#### `dev/get_pat.py` — PAT-only mode

Standalone version of step 4–5 above. Use it when a product's wizard was
already completed (manually in the browser, or via `auto_setup.py` once and
you only want a fresh token):

```bash
JIRA_PASS=secret python dev/get_pat.py jira       --user admin --base-url http://localhost:8080
CONF_PASS=secret python dev/get_pat.py confluence --user admin --base-url http://localhost:8090
BB_PASS=secret   python dev/get_pat.py bitbucket  --user admin --base-url http://localhost:7990
```

Has a basic-auth fallback so it works even if the cookie-based login route
breaks again on a future Atlassian update.

#### Recording tools — `dev/watch_setup.py` and `dev/watch_pat.py`

If Atlassian changes the wizard forms or the PAT UI in a future release,
these two scripts open a real Chromium window, log in for you, then **record
every navigation, every POST/PUT body, and full DOM snapshots of every visible
form** to `dev/watch-logs/` while you click through manually. The captured
form-action URLs and field names are exactly what `auto_setup.py` /
`get_pat_browser.py` need to be patched with.

Both scripts also snap session cookies, so they double as a one-shot
"semi-automatic" setup if `auto_setup.py` fails for a yet-unsupported version.

#### Hard-won lessons (left here so we do not relearn them)

- **Captcha is the silent killer.** Without the JVM args above, Jira blocks
  the admin user after 3 wrong attempts and the symptom looks like "wrong
  password" — not "captcha required". Two hours of wizard reverse-engineering
  before we found this.
- **Confluence's wizard is state-fragile.** Going back to `base + "/"` after a
  successful POST sometimes bounces the wizard back to a stale page; the
  walker must follow `r2.url` (the redirect target the POST landed on)
  instead. Also, the cluster step needs **all 19 form fields** present even
  when most are empty (`newCluster=skipCluster` alone does not work).
- **Field names differ per product.** Jira uses `setupLicenseKey`, Confluence
  uses `confLicenseString`. Jira admin form has `next=Next`, Confluence
  has `setup-next-button=Next`. Bitbucket combines the admin form and the
  Jira-integration choice on a single page (post `skipJira=Go to Bitbucket`).
- **Bitbucket's PAT REST endpoint is `PUT /rest/access-tokens/latest/users/{slug}`,
  not POST.**
- The fully-headless raw-HTTP path was abandoned for the Confluence wizard
  *once* (because the cluster page kept rejecting our submits) — the recovery
  recipe was: spin up `dev/watch_setup.py confluence`, click through manually,
  read the recorded form bodies out of `dev/watch-logs/confluence-*.log`,
  paste the field names into `auto_setup.py`. The whole thing took ~20 minutes
  end-to-end and the script has worked unattended on every fresh container
  reset since.

### `atlassian-dc-plugin/tests/` — 172 reproducible pytest cases

The suite has eight files; **no real Atlassian server is required**, errors are
mocked via `responses`. The conftest's `script_runner` fixture invokes scripts
as a weak LLM would — via subprocess — so exit codes, stderr text, and
stdout-vs-stderr separation are all asserted.

| File | What it covers |
|---|---|
| `test_config_loader.py` | instance + rules resolution: missing files, bad JSON, alias precedence (CLI > env > default), project-filtered rules |
| `test_client_errors.py` | `JiraClient` HTTP error mapping — 401/403/404/400/500 → typed exceptions with clear messages; **PAT never leaks into stringified errors** |
| `test_confluence_client.py` | `ConfluenceClient` URL joining (no `/2`), error mapping, empty 204, unparseable error body, PAT non-leakage |
| `test_bitbucket_client.py` | `BitbucketClient` paginate() with `isLastPage`/`nextPageStart`, limit cap, error mapping |
| `test_cli_error_visibility.py` | scripts: failures exit ≠0 with stderr; `--dry-run` always emits its marker, **even with `--quiet`**; unknown alias lists what IS available; JSON dry-run carries `"executed": false` |
| `test_new_scripts_cli.py` | jira worklog/link/watcher/agile/attachment/version + jira_user create + jira_issue parent/fix-version + fields editmeta/createmeta |
| `test_confluence_scripts_cli.py` | spaces, pages (with auto version-bump in dry-run), CQL search, comment replies, label payload shape, multipart attachment validation, blogpost type, `--purge=trashed` |
| `test_bitbucket_scripts_cli.py` | projects, repos (incl. fork/delete), branches, tags, commits, files (code search), full PR lifecycle, user search |
| `test_extras_cli.py` | jira components, groups, user update/delete/assignable, bulk-create from JSON; confluence restrictions + history + export-URL; bitbucket webhooks, permissions (project- vs repo-scope), build statuses |

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
