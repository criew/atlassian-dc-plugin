#!/usr/bin/env python3
"""Install the Atlassian DC plugin into your agent harness.

Detects Claude Code / OpenCode / Codex and links (or copies) the plugin into
the right place. Idempotent — running it again updates the link.

Usage:
    python install.py                       # auto-detect harness, user scope, symlink
    python install.py --harness claude --scope project
    python install.py --harness opencode --scope user --mode copy
    python install.py --target /custom/path

Options:
    --harness   claude | opencode | codex | auto  (default: auto)
    --scope     user | project                    (default: user)
    --mode      link | copy                       (default: link on POSIX,
                                                            copy on Windows)
    --target    explicit destination path; overrides --harness/--scope
    --yes       non-interactive (skip confirmation prompt)
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = REPO_ROOT / "atlassian-dc-plugin"
PLUGIN_NAME = "atlassian-dc"


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def _appdata() -> Path | None:
    a = os.environ.get("APPDATA")
    return Path(a) if a else None


# Per-harness install destinations. Project scope is always relative to cwd.
HARNESS_PATHS = {
    "claude":   {"user_dir":  Path.home() / ".claude" / "skills",
                 "project_dir": Path(".claude") / "skills"},
    "opencode": {"user_dir":  _xdg_config_home() / "opencode" / "skills",
                 "project_dir": Path(".opencode") / "skills"},
    "codex":    {"user_dir":  Path.home() / ".codex" / "skills",
                 "project_dir": Path(".agents") / "skills"},
}


def detect_harness() -> str | None:
    """Best-effort auto-detect."""
    # Honor an explicit env hint first.
    if os.environ.get("ATLASSIAN_DC_HARNESS"):
        return os.environ["ATLASSIAN_DC_HARNESS"]

    candidates = []
    if shutil.which("claude") or (Path.home() / ".claude").exists():
        candidates.append("claude")
    if shutil.which("opencode") or (_xdg_config_home() / "opencode").exists():
        candidates.append("opencode")
    if shutil.which("codex"):
        candidates.append("codex")

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        print(f"detected multiple harnesses: {candidates} — pick one with --harness")
        return None
    return None


def resolve_target(args) -> Path:
    if args.target:
        return Path(args.target).expanduser().resolve() / PLUGIN_NAME

    harness = args.harness
    if harness == "auto":
        harness = detect_harness()
        if not harness:
            sys.exit("error: could not auto-detect harness; pass --harness "
                     "claude|opencode|codex (or --target PATH)")
    if harness not in HARNESS_PATHS:
        sys.exit(f"error: unknown harness {harness!r}")

    paths = HARNESS_PATHS[harness]
    if args.scope == "project":
        base = Path.cwd() / paths["project_dir"]
    else:
        base = paths["user_dir"]
    return (base / PLUGIN_NAME).resolve()


def install(target: Path, mode: str, force: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    # Existing target? Remove (or skip if pointing at us already).
    if target.exists() or target.is_symlink():
        if target.is_symlink():
            try:
                if Path(os.readlink(target)).resolve() == PLUGIN_DIR:
                    print(f"[install] already pointing at {PLUGIN_DIR} (no-op)")
                    return
            except OSError:
                pass
        if not force:
            sys.exit(f"error: {target} exists; pass --yes to overwrite")
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()

    if mode == "link":
        try:
            target.symlink_to(PLUGIN_DIR, target_is_directory=True)
            print(f"[install] symlink {target} -> {PLUGIN_DIR}")
            return
        except (OSError, NotImplementedError) as e:
            print(f"[install] symlink failed ({e}); falling back to copy")
    # Copy mode (also fallback)
    shutil.copytree(PLUGIN_DIR, target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                  ".pytest_cache", "tests"))
    print(f"[install] copied {PLUGIN_DIR} -> {target}")
    print("[install] note: future plugin updates won't auto-propagate; "
          "re-run install.py to refresh, or use --mode link on a system that "
          "supports symlinks (Linux/macOS or Windows with developer mode).")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--harness", choices=["auto", "claude", "opencode", "codex"],
                   default="auto")
    p.add_argument("--scope", choices=["user", "project"], default="user")
    default_mode = "copy" if platform.system() == "Windows" else "link"
    p.add_argument("--mode", choices=["link", "copy"], default=default_mode)
    p.add_argument("--target", help="explicit install dir (parent of the plugin folder)")
    p.add_argument("--yes", "-y", action="store_true",
                   help="overwrite an existing target without prompting")
    args = p.parse_args()

    if not PLUGIN_DIR.exists():
        sys.exit(f"error: plugin folder missing at {PLUGIN_DIR}")

    target = resolve_target(args)
    print(f"[install] plugin source: {PLUGIN_DIR}")
    print(f"[install] target:        {target}")
    print(f"[install] mode:          {args.mode}")
    if not args.yes and target.exists():
        ans = input(f"target {target} exists — overwrite? [y/N] ").strip().lower()
        if ans != "y":
            sys.exit("aborted")
        force = True
    else:
        force = args.yes

    install(target, args.mode, force)

    # Show next steps.
    print()
    print("Next steps:")
    print("  1. python setup_instance.py     # interactive instance + PAT setup")
    print("  2. (or) copy atlassian-dc-plugin/instances.json.example to")
    print("       ~/.config/atlassian/instances.json (Linux/macOS) or")
    print("       %APPDATA%\\atlassian\\instances.json (Windows) and fill in your PATs.")
    print()


if __name__ == "__main__":
    main()
