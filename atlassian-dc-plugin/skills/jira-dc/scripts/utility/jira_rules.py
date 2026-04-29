#!/usr/bin/env python3
"""Show server-specific rules for the active Jira instance.

Rules live in user config (NOT in the plugin) at:
  $ATLASSIAN_CONFIG_DIR/rules/<alias>.md           (override)
  ~/.config/atlassian/rules/<alias>.md             (Linux/macOS)
  %APPDATA%\\atlassian\\rules\\<alias>.md          (Windows)

The file is plain markdown. Conventional sections:
  # Rules for "<alias>"
  ## Global
  - rules that apply to every project
  ## Project <KEY>
  - rules for that specific project

Usage:
  jira_rules.py show                       # all rules for the default instance
  jira_rules.py show --instance prod       # all rules for "prod"
  jira_rules.py show --project HALLO       # only Global + Project HALLO sections
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import (  # noqa: E402
    add_common_args, load_rules, load_instance, emit, run,
)


def cmd_show(args):
    # Resolve alias the same way other scripts do.
    inst = load_instance("jira", args.instance)
    rules = load_rules(inst.alias, project=args.project)

    if args.json:
        emit(rules, args)
        return

    if not rules["found"]:
        # Important: this is NOT an error. We tell the LLM clearly so it can
        # decide to proceed without rules, OR ask the user to add some.
        searched = "\n  ".join(rules.get("searched", []))
        msg = (
            f"NO RULES FILE for instance '{inst.alias}'.\n"
            f"Searched:\n  {searched}\n"
            f"This means there are no server-specific rules. Proceed with care, "
            f"or ask the user to populate rules/{inst.alias}.md."
        )
        emit(rules, args, human=msg)
        return

    proj_part = f" (filtered to project {args.project})" if args.project else ""
    header = f"# Rules for '{inst.alias}'{proj_part}\n# Source: {rules['path']}\n"
    emit(rules, args, human=header + rules["content"])


def main():
    p = argparse.ArgumentParser(description="Show rules for the active Jira instance")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show", help="print rules for an instance (optionally a project)")
    s.add_argument("--project", "-p", help="filter to Global + matching project section")
    add_common_args(s)
    s.set_defaults(func=cmd_show)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
