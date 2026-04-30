#!/usr/bin/env python3
"""Install Atlassian DC skills into your agent harness.

Detects Claude Code / OpenCode / Codex and links (or copies) each skill
directory into the right place. Idempotent — running it again updates.

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

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = REPO_ROOT / "skills"
SKILL_NAMES = ["atlassian-dc", "jira-dc", "bitbucket-dc", "confluence-dc"]


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def _appdata() -> Optional[Path]:
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


def detect_harness() -> Optional[str]:
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
    return base.resolve()


def install_skill(src: Path, dest: Path, mode: str, force: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() or dest.is_symlink():
        if dest.is_symlink():
            try:
                if Path(os.readlink(dest)).resolve() == src:
                    print(f"  {dest.name}: already linked (no-op)")
                    return
            except OSError:
                pass
        if not force:
            sys.exit(f"error: {dest} exists; pass --yes to overwrite")
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()

    if mode == "link":
        try:
            dest.symlink_to(src, target_is_directory=True)
            print(f"  {dest.name}: symlink -> {src}")
            return
        except (OSError, NotImplementedError) as e:
            print(f"  {dest.name}: symlink failed ({e}); falling back to copy")
    shutil.copytree(src, dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                  ".pytest_cache"))
    print(f"  {dest.name}: copied")


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

    if not SKILLS_DIR.exists():
        sys.exit(f"error: skills folder missing at {SKILLS_DIR}")

    target = resolve_target(args)
    print(f"[install] skills source: {SKILLS_DIR}")
    print(f"[install] target:        {target}")
    print(f"[install] mode:          {args.mode}")

    force = args.yes
    if not args.yes:
        existing = [n for n in SKILL_NAMES if (target / n).exists()]
        if existing:
            ans = input(f"skills {existing} already exist in {target} — overwrite? [y/N] ").strip().lower()
            if ans != "y":
                sys.exit("aborted")
            force = True

    used_copy = False
    for name in SKILL_NAMES:
        src = SKILLS_DIR / name
        if not src.exists():
            print(f"  {name}: skipped (not found)")
            continue
        install_skill(src, target / name, args.mode, force)
        if (target / name).exists() and not (target / name).is_symlink():
            used_copy = True

    if used_copy:
        print()
        print("[install] note: copied skills won't auto-update; "
              "re-run install.py to refresh, or use --mode link on a system "
              "that supports symlinks.")

    print()
    print("Next steps:")
    print("  1. python setup_instance.py     # interactive instance + PAT setup")
    print("  2. (or) copy instances.json.example to")
    print("       ~/.config/atlassian/instances.json (Linux/macOS) or")
    print("       %APPDATA%\\atlassian\\instances.json (Windows) and fill in your PATs.")
    print()


if __name__ == "__main__":
    main()
