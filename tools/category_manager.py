#!/usr/bin/env python3
"""Manage the category tree in seed/categories.yaml (add / update / delete / list).

The file is the single source of truth for the seed category tree (docs/SPEC.md 3.8);
the database loader (promptvault.services.seed.sync_categories) applies it on boot.

Examples:
  python tools/category_manager.py list
  python tools/category_manager.py add --slug ai-tools --name "AI Tools" --group technical
  python tools/category_manager.py update --slug ai-tools --name "AI & Automation"
  python tools/category_manager.py delete --slug ai-tools
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

CAT_FILE = Path(__file__).resolve().parent.parent / "seed" / "categories.yaml"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _load() -> dict:
    return yaml.safe_load(CAT_FILE.read_text(encoding="utf-8")) or {}


def _dump(data: dict) -> None:
    """Write categories.yaml back, one flow mapping per line, groups first."""
    lines = [
        "# Category tree for the seed library (docs/SPEC.md section 3.8). Categories are data, not code.",
        "# Existing categories in a user's database are never renamed or moved by the loader.",
    ]
    if data.get("min_per_category") is not None:
        lines.append(
            "# min_per_category: the CI linter fails when any category listed below has fewer prompts."
        )
        lines.append(
            f"# It is {data['min_per_category']} now that every category is filled (M2e); the library was written in M2b-e with a 0 minimum."
        )
        lines.append(
            f"\nmin_per_category: {data['min_per_category']}"
        )
    lines.append("\ngroups:")
    for g in data.get("groups") or []:
        lines.append(f"  - {{ slug: {g['slug']}, name: \"{g['name']}\" }}")
    lines.append("\ncategories:")
    current_group = None
    for c in data.get("categories") or []:
        if c.get("group") != current_group:
            current_group = c.get("group")
            if current_group:
                lines.append(f"  # {current_group.title()}")
        entry = f"  - {{ slug: {c['slug']}, name: \"{c['name']}\""
        if c.get("group"):
            entry += f", group: {c['group']}"
        entry += " }"
        lines.append(entry)
    CAT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _check_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise SystemExit(f"Invalid slug '{slug}' (must be lowercase a-z, 0-9, hyphens)")


def list_categories(data: dict) -> None:
    print("Groups:")
    for g in data.get("groups") or []:
        print(f"  {g['slug']:<24} {g['name']}")
    print("Categories:")
    for c in data.get("categories") or []:
        parent = f" (under {c['group']})" if c.get("group") else ""
        print(f"  {c['slug']:<24} {c['name']}{parent}")


def add_category(slug: str, name: str, group: str | None) -> None:
    data = _load()
    _check_slug(slug)
    if group and not any(g["slug"] == group for g in data.get("groups") or []):
        raise SystemExit(f"Group '{group}' does not exist. Add it first or use an existing one.")
    existing_slugs = {g["slug"] for g in data.get("groups") or []} | {
        c["slug"] for c in data.get("categories") or []
    }
    if slug in existing_slugs:
        raise SystemExit(f"Category '{slug}' already exists")
    if group:
        data.setdefault("categories", []).append({"slug": slug, "name": name, "group": group})
    else:
        data.setdefault("groups", []).append({"slug": slug, "name": name})
    _dump(data)
    print(f"Added {'group' if not group else 'category'} '{name}' ({slug})")


def update_category(slug: str, new_name: str | None, new_group: str | None) -> None:
    data = _load()
    target = None
    for g in data.get("groups") or []:
        if g["slug"] == slug:
            target = g
            break
    if target is None:
        for c in data.get("categories") or []:
            if c["slug"] == slug:
                target = c
                break
    if target is None:
        raise SystemExit(f"Category '{slug}' not found")
    if new_name:
        target["name"] = new_name
    if new_group is not None:
        if "group" not in target and new_group:
            raise SystemExit(f"'{slug}' is a top-level group and cannot be nested")
        target["group"] = new_group or None
        if new_group is not None and "group" in target and target["group"] is None:
            del target["group"]
    _dump(data)
    print(f"Updated '{slug}'")


def delete_category(slug: str) -> None:
    data = _load()
    before_groups = len(data.get("groups") or [])
    before_cats = len(data.get("categories") or [])
    data["groups"] = [g for g in data.get("groups") or [] if g["slug"] != slug]
    data["categories"] = [c for c in data.get("categories") or [] if c["slug"] != slug]
    # children of a deleted group become top-level categories
    for c in data.get("categories") or []:
        if c.get("group") == slug:
            del c["group"]
    if len(data.get("groups") or []) == before_groups and len(data.get("categories") or []) == before_cats:
        raise SystemExit(f"Category '{slug}' not found")
    _dump(data)
    print(f"Deleted '{slug}'")


def main() -> int:
    p = argparse.ArgumentParser(description="Manage seed/categories.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("--slug", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--group", default=None, help="Parent group slug (omit to create a top-level group)")
    u = sub.add_parser("update")
    u.add_argument("--slug", required=True)
    u.add_argument("--name", default=None)
    u.add_argument("--group", default=None, help="New parent group, or '' to un-nest")
    d = sub.add_parser("delete")
    d.add_argument("--slug", required=True)
    args = p.parse_args()
    data = _load()
    if args.cmd == "list":
        list_categories(data)
    elif args.cmd == "add":
        add_category(args.slug, args.name, args.group)
    elif args.cmd == "update":
        update_category(args.slug, args.name, args.group if args.group is not None else None)
    elif args.cmd == "delete":
        delete_category(args.slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
