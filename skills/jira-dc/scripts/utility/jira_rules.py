#!/usr/bin/env python3
"""Server-specific rules for the active Jira instance.

Rules live in user config (NOT in the plugin) at:
  $ATLASSIAN_CONFIG_DIR/rules/<alias>.md           (override)
  ~/.config/atlassian/rules/<alias>.md             (Linux/macOS)
  %APPDATA%\\atlassian\\rules\\<alias>.md          (Windows)

The file is plain markdown. Conventional sections:
  # Rules for "<alias>"
  ## Global              — rules that apply to every project
  ## Discovered defaults — auto-written by `auto-discover`; safe to keep
  ## Project <KEY>       — rules for that specific project

Subcommands:
  show           print existing rules
  init           create a starter rules/<alias>.md (won't overwrite an existing one
                 unless --force)
  auto-discover  query the live Jira and append a 'Discovered defaults' section
                 with the actual priority/status/issuetype names this server uses
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import (  # noqa: E402
    add_common_args,
    load_rules,
    load_instance,
    emit,
    run,
    ValidationError,
)
from _jira import get_jira  # noqa: E402


# ---------------------------------------------------------------------------
# Path resolution (mirrors _common._rules_paths but exposes the FIRST writable)
# ---------------------------------------------------------------------------

def _target_rules_path(alias: str) -> Path:
    explicit = os.environ.get("ATLASSIAN_CONFIG_DIR")
    if explicit:
        return Path(explicit) / "rules" / f"{alias}.md"
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "atlassian" / "rules" / f"{alias}.md"
    return Path.home() / ".config" / "atlassian" / "rules" / f"{alias}.md"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

STARTER_TEMPLATE = """# Rules for "{alias}"

> Edit this file freely — it is read by the LLM via `jira_rules.py show`
> before every write operation. Sections starting with `## Project <KEY>`
> apply only when that project is involved; `## Global` always applies.

## Global

- Kein Issue ohne Assignee anlegen — bei fehlendem Assignee zurückfragen.
- Bei JQL-Suchen niemals ohne `project = ...`-Filter laufen; sonst Confirm anfragen.
- Vor `delete` / `transition`-Operationen nochmal die Konsequenz nennen.

## Project <KEY>

<!-- Replace <KEY> with a real project key. Add per-project rules here.
Example:
- Stories brauchen Epic-Link (Custom Field). Frage vor dem Erstellen nach dem Epic-Key.
- Bug-Tickets brauchen "Steps to Reproduce" in der Beschreibung.
- Erlaubte Issue-Types: Story, Bug, Task. Keine Sub-tasks ohne Parent.
-->
"""


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_show(args):
    inst = load_instance("jira", args.instance)
    rules = load_rules(inst.alias, project=args.project)

    if args.json:
        emit(rules, args)
        return

    if not rules["found"]:
        searched = "\n  ".join(rules.get("searched", []))
        msg = (
            f"NO RULES FILE for instance '{inst.alias}'.\n"
            f"Searched:\n  {searched}\n"
            f"Run `jira_rules.py init --instance {inst.alias}` to create a starter "
            f"file, then `jira_rules.py auto-discover --instance {inst.alias}` to "
            f"capture priority/status/issuetype names this server uses."
        )
        emit(rules, args, human=msg)
        return

    proj_part = f" (filtered to project {args.project})" if args.project else ""
    header = f"# Rules for '{inst.alias}'{proj_part}\n# Source: {rules['path']}\n"
    emit(rules, args, human=header + rules["content"])


def cmd_init(args):
    inst = load_instance("jira", args.instance)
    target = _target_rules_path(inst.alias)
    if target.exists() and not args.force:
        emit({"path": str(target), "created": False, "reason": "exists"}, args,
             human=f"rules/{inst.alias}.md already exists at {target}\n"
                   f"Pass --force to overwrite, or edit it directly.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(STARTER_TEMPLATE.format(alias=inst.alias), encoding="utf-8")
    emit({"path": str(target), "created": True}, args,
         human=f"created starter rules at {target}\n"
               f"Next: `jira_rules.py auto-discover --instance {inst.alias}` "
               f"to add server-specific defaults.")


def _discover(client) -> dict:
    """Query Jira for the canonical names actually used on this server."""
    out = {}
    try:
        prios = [p.get("name") for p in client.get("priority")]
        out["priorities"] = [p for p in prios if p]
    except Exception as e:
        out["priorities_error"] = str(e)
    try:
        statuses = [s.get("name") for s in client.get("status")]
        out["statuses"] = sorted({s for s in statuses if s})
    except Exception as e:
        out["statuses_error"] = str(e)
    try:
        types = client.get("issuetype")
        out["issuetypes"] = [t.get("name") for t in types if t.get("name")]
        out["subtask_types"] = [t.get("name") for t in types
                                if t.get("subtask") and t.get("name")]
    except Exception as e:
        out["issuetypes_error"] = str(e)
    try:
        out["projects"] = [{"key": p.get("key"), "name": p.get("name")}
                           for p in client.get("project")]
    except Exception as e:
        out["projects_error"] = str(e)
    try:
        # Try common Epic Link customfield discovery
        for f in client.get("field"):
            if f.get("name") == "Epic Link":
                out["epic_link_field"] = f.get("id")
                break
    except Exception:
        pass
    return out


def _format_discovery(data: dict) -> str:
    lines = [
        "## Discovered defaults",
        "",
        "<!-- Auto-written by `jira_rules.py auto-discover`. Edit freely;",
        "     the next auto-discover run will replace ONLY this section. -->",
        "",
    ]
    if data.get("priorities"):
        lines.append(f"- Valid `priority` names on this server: "
                     f"{', '.join(repr(x) for x in data['priorities'])}.")
    if data.get("statuses"):
        lines.append(f"- Status names returned by JQL: "
                     f"{', '.join(repr(x) for x in data['statuses'])}.")
    if data.get("issuetypes"):
        lines.append(f"- Issue types: {', '.join(repr(x) for x in data['issuetypes'])}.")
    if data.get("subtask_types"):
        lines.append(f"- Subtask issue types: "
                     f"{', '.join(repr(x) for x in data['subtask_types'])} "
                     f"(use one of these with `--parent KEY`).")
    if data.get("epic_link_field"):
        lines.append(f"- Epic Link customfield: `{data['epic_link_field']}`.")
    if data.get("projects"):
        keys = ", ".join(p["key"] for p in data["projects"])
        lines.append(f"- Known projects: {keys}.")
    lines.append("")
    return "\n".join(lines)


def _splice_section(existing: str, section_name: str, new_block: str) -> str:
    """Replace an existing `## <section_name>` block, or append at the end."""
    import re
    pattern = re.compile(
        rf"(?ms)^##\s+{re.escape(section_name)}\s*$.*?(?=^##\s|\Z)"
    )
    if pattern.search(existing):
        return pattern.sub(new_block.rstrip() + "\n\n", existing).rstrip() + "\n"
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    return existing + sep + new_block


def cmd_auto_discover(args):
    inst = load_instance("jira", args.instance)
    client = get_jira(args)
    data = _discover(client)

    if args.json:
        emit({"instance": inst.alias, "discovered": data}, args)

    target = _target_rules_path(inst.alias)
    block = _format_discovery(data)

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        starter = STARTER_TEMPLATE.format(alias=inst.alias)
        new_content = _splice_section(starter, "Discovered defaults", block)
        action = "created with starter + Discovered defaults"
    else:
        existing = target.read_text(encoding="utf-8")
        new_content = _splice_section(existing, "Discovered defaults", block)
        action = "updated"
    target.write_text(new_content, encoding="utf-8")

    if args.json:
        return  # already emitted JSON
    summary = (
        f"{action}: {target}\n\n"
        f"--- Discovered ---\n{block}"
    )
    emit({"path": str(target), "discovered": data}, args, human=summary)


def main():
    p = argparse.ArgumentParser(description="Server-specific rules")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    s = sub.add_parser("show", help="print rules for an instance (optionally a project)")
    s.add_argument("--project", "-p", help="filter to Global + matching project section")
    add_common_args(s)
    s.set_defaults(func=cmd_show)

    i = sub.add_parser("init", help="write a starter rules/<alias>.md")
    i.add_argument("--force", action="store_true",
                   help="overwrite an existing file")
    add_common_args(i)
    i.set_defaults(func=cmd_init)

    d = sub.add_parser("auto-discover",
                       help="query Jira for priorities/statuses/issuetypes/projects "
                            "and write them into rules/<alias>.md")
    add_common_args(d)
    d.set_defaults(func=cmd_auto_discover)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
