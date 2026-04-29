# Atlassian Data Center Plugin

Skills for Jira, Confluence, and Bitbucket Data Center deployments. Multi-instance support via a single `instances.json` config.

## Setup

1. Install [`uv`](https://docs.astral.sh/uv/) (fast Python runner — replaces pip + venv).
2. Copy `instances.json.example` to one of:
   - Linux/macOS: `~/.config/atlassian/instances.json`
   - Windows: `%APPDATA%\atlassian\instances.json`
   - Or set `ATLASSIAN_INSTANCES_FILE=/path/to/file.json`
3. Add your Personal Access Tokens (created in each product under *Profile → Personal Access Tokens*).
4. Drop the `skills/` content where your tool expects it (Claude Code: `.claude/skills/`, OpenCode: `.opencode/skills/`, Codex: `.agents/skills/`).

## Local Test Environment

To exercise the skill against a real Jira DC, run the bundled `docker-compose.yml`
under `docker/`. The wizard requires a license key — for short-lived tests, get a
free 3-hour Time-Bomb license here (no Atlassian account needed):

**https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/**

Pick „Jira Software (Data Center)", paste the generated key into the wizard's
license field. For longer evaluation, use the regular 30-day trial via
my.atlassian.com.

## Multi-Instance

Each script accepts `--instance <alias>`. Without it, the `default` instance from `instances.json` is used. The `ATLASSIAN_INSTANCE` env var is also honored.

## Common CLI Flags

All scripts support these flags consistently:

| Flag | Effect |
|---|---|
| `--instance ALIAS` | Pick an instance from `instances.json` |
| `--json` | Raw JSON output (default is compact human-readable) |
| `--quiet` | Errors only |
| `--debug` | Verbose request/response logging (token masked) |
| `--dry-run` | Print the request that *would* be sent for write ops, do not execute |
