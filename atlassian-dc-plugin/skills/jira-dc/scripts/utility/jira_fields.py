#!/usr/bin/env python3
"""Discover Jira fields — globally, for a specific issue, or for a create context.

Subcommands:
  list                                 # all fields (incl. customfield_*)
  editmeta KEY                         # fields editable on this concrete issue
  createmeta --project P --type Bug    # fields creatable for project+type, with
                                       # required flag and allowed values
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared"))

from _common import add_common_args, get_jira, emit, run  # noqa: E402


def cmd_list(args):
    client = get_jira(args)
    fields = client.get("field")
    if args.keyword:
        kw = args.keyword.lower()
        fields = [f for f in fields if kw in f.get("name", "").lower() or kw in f.get("id", "").lower()]
    if args.json:
        emit(fields, args)
        return
    lines = [f"{f.get('id'):<25} {f.get('name')}" for f in fields]
    emit(fields, args, human="\n".join(lines) + f"\n\n{len(fields)} field(s)")


def _flatten_meta_fields(meta_fields: dict) -> list[dict]:
    """Convert createmeta/editmeta field dict into a flat list."""
    out = []
    for fid, fdef in meta_fields.items():
        entry = {
            "id": fid,
            "name": fdef.get("name"),
            "required": fdef.get("required", False),
            "schema_type": (fdef.get("schema") or {}).get("type"),
            "schema_custom": (fdef.get("schema") or {}).get("custom"),
            "has_default": "defaultValue" in fdef,
            "operations": fdef.get("operations", []),
        }
        allowed = fdef.get("allowedValues")
        if allowed is not None:
            entry["allowed_values"] = [
                v.get("name") or v.get("value") or v.get("key") or str(v)
                for v in allowed
            ]
        out.append(entry)
    return out


def cmd_editmeta(args):
    client = get_jira(args)
    data = client.get(f"issue/{args.key}/editmeta")
    fields = _flatten_meta_fields(data.get("fields", {}))
    if args.json:
        emit({"key": args.key, "fields": fields}, args)
        return
    if not fields:
        emit({"key": args.key, "fields": []}, args, human=f"no editable fields on {args.key}")
        return
    lines = [f"{'REQ' if f['required'] else '   '} {f['id']:<25} {f['name']}" for f in fields]
    emit({"key": args.key, "fields": fields}, args,
         human=f"editable fields on {args.key} ({len(fields)}):\n" + "\n".join(lines))


def _createmeta_v9(client, project: str, type_filter: str | None) -> list[dict]:
    """Jira 9.x split endpoint: list issue types per project, then fields per type."""
    types_data = client.get(f"issue/createmeta/{project}/issuetypes")
    types = types_data.get("values", types_data) if isinstance(types_data, dict) else types_data
    out = []
    for it in types:
        if type_filter and it.get("name") != type_filter:
            continue
        type_id = it.get("id")
        fields_data = client.get(f"issue/createmeta/{project}/issuetypes/{type_id}")
        raw_fields = fields_data.get("values", fields_data) if isinstance(fields_data, dict) else fields_data
        # The v9 endpoint returns a list of {fieldId, name, required, schema, ...}.
        flat = []
        for f in raw_fields:
            entry = {
                "id": f.get("fieldId"),
                "name": f.get("name"),
                "required": f.get("required", False),
                "schema_type": (f.get("schema") or {}).get("type"),
                "schema_custom": (f.get("schema") or {}).get("custom"),
                "has_default": "defaultValue" in f,
                "operations": f.get("operations", []),
            }
            allowed = f.get("allowedValues")
            if allowed is not None:
                entry["allowed_values"] = [
                    v.get("name") or v.get("value") or v.get("key") or str(v)
                    for v in allowed
                ]
            flat.append(entry)
        out.append({
            "project": project,
            "issuetype": it.get("name"),
            "subtask": it.get("subtask", False),
            "fields": flat,
        })
    return out


def cmd_createmeta(args):
    client = get_jira(args)
    # Try v9 split endpoint first; fall back to legacy for older Jira.
    try:
        out = _createmeta_v9(client, args.project, args.type)
    except Exception:
        params = {"projectKeys": args.project, "expand": "projects.issuetypes.fields"}
        if args.type:
            params["issuetypeNames"] = args.type
        data = client.get("issue/createmeta", params=params)
        out = []
        for p in data.get("projects", []):
            for it in p.get("issuetypes", []):
                out.append({
                    "project": p.get("key"),
                    "issuetype": it.get("name"),
                    "subtask": it.get("subtask", False),
                    "fields": _flatten_meta_fields(it.get("fields", {})),
                })

    if not out:
        emit({"project": args.project, "issuetypes": []}, args,
             human=f"no createmeta for project {args.project}"
                   + (f" / type {args.type}" if args.type else "")
                   + " (does it exist? do you have permission?)")
        return

    if args.json:
        emit(out, args)
        return

    lines = []
    for entry in out:
        lines.append(f"\n# {entry['project']} / {entry['issuetype']}"
                     f"{' (subtask)' if entry['subtask'] else ''}")
        for f in entry["fields"]:
            req = "REQ" if f["required"] else "   "
            extra = ""
            if "allowed_values" in f:
                vals = f["allowed_values"]
                preview = ", ".join(vals[:5]) + ("..." if len(vals) > 5 else "")
                extra = f"  [{preview}]"
            lines.append(f"{req} {f['id']:<25} {f['name']}{extra}")
    emit(out, args, human="\n".join(lines))


def main():
    p = argparse.ArgumentParser(description="Discover Jira fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list all global fields (incl. customfield_*)")
    ls.add_argument("--keyword", help="filter by name/id substring")
    add_common_args(ls)
    ls.set_defaults(func=cmd_list)

    em = sub.add_parser("editmeta", help="fields editable on a specific issue")
    em.add_argument("key")
    add_common_args(em)
    em.set_defaults(func=cmd_editmeta)

    cm = sub.add_parser("createmeta", help="fields available for creating in project[+type]")
    cm.add_argument("--project", required=True)
    cm.add_argument("--type", help="issue type name (filters to one)")
    add_common_args(cm)
    cm.set_defaults(func=cmd_createmeta)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    run(main)
