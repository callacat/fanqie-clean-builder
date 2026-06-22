#!/usr/bin/env python3
"""Overlay modded-smali files onto official, copying by class-name match.

Strategy
--------
Lancet AOP modifies both hook targets AND every call site across 26 dexes.
The only reliable transplant is to overlay the exact changed files from the
modded tree onto the official tree (match by .class directive, not path).

The patch-report.json (from smali_diff_harvester) lists every file pair:

    "class_name": "zo4.b"
    "diff_type": "logical_change"
    "files": ["smali_classes18/zo4/b.smali", "smali_classes24/zo4/b.smali"]
               ↑ official path            ↑ modded path

We copy modded → official for every logical_change (1 422 files),
and append new modded-only files (900 files) to smali_classes29.
"""

from __future__ import annotations

import argparse, json, shutil, re, sys
from pathlib import Path

# Files added by the modder that are SAFE to include (signature spoofing core).
SAFE_NEW = frozenset({
    "com/pandora/core/CreatorProxy.smali",
    "com/pandora/core/AppFactory$DATA.smali",
})

# Files we NEVER want (potential tracking / C2).
BLOCKLIST = frozenset({
    "com/pandora/core/AppFactory.smali",
    "com/pandora/core/Copyright.smali",  # just a credit file, harmless but useless
    "com/pandora/core/ۧۤۤ.smali",       # obfuscated helper — unknown behavior
})

RE_CLASS = re.compile(
    r'^\.class\s+(?:public\s+|final\s+|abstract\s+|static\s+)*L([\w/$-]+);',
    re.MULTILINE,
)


def find_in_tree(root: Path, class_name: str) -> Path | None:
    """Scan *root* smali dirs for a file whose .class matches *class_name*."""
    # Internal JVM name uses '/' not '.'
    jvm_name = class_name.replace(".", "/")
    for smali_dir in sorted(root.glob("smali*")):
        if not smali_dir.is_dir():
            continue
        for f in smali_dir.rglob("*.smali"):
            head = f.read_bytes()[:2000]
            m = RE_CLASS.search(head.decode("utf-8", errors="replace"))
            if m and m.group(1) == jvm_name:
                return f
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--official", required=True)
    ap.add_argument("--modded", required=True)
    ap.add_argument("--report", default="patch-report.json")
    ap.add_argument("--new-dex", default="smali_classes29",
                    help="Dex directory for new (modded-only) files")
    args = ap.parse_args()

    official = Path(args.official).resolve()
    modded = Path(args.modded).resolve()
    report = json.loads(Path(args.report).read_text())
    new_dex = official / args.new_dex

    copied = skipped = added = blocked = 0

    for p in report.get("patches", []):
        dt = p["diff_type"]
        cls = p["class_name"]
        files = p.get("files", [])  # [official_rel, modded_rel] or [modded_rel]
        cat = p.get("category", "uncategorized")

        if dt == "metadata_only":
            continue  # debug noise

        # ── logical_change: copy modded path → target in official tree ──
        if dt == "logical_change" and len(files) >= 2:
            mod_rel = files[1]
            src = modded / mod_rel
            if not src.is_file():
                # fallback: find by class name in modded
                src = find_in_tree(modded, cls)
            if not src:
                print(f"  SKIP {cls}: modded source not found")
                skipped += 1
                continue

            # Find target in official tree (by class name)
            dst = find_in_tree(official, cls)
            if not dst:
                # Class was deleted in official? Shouldn't happen for
                # logical_change (it exists in both). Fallback:
                dst = official / mod_rel
                dst.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(src, dst)
            copied += 1

        # ── new file (modded-only) ───────────────────────────────────
        elif dt == "added" and files:
            mod_rel = files[0]

            # Blocklist check
            if mod_rel in BLOCKLIST:
                blocked += 1
                continue

            # Only include safe new files by default
            if cat == "uncategorized" and mod_rel not in SAFE_NEW:
                blocked += 1
                continue

            src = modded / mod_rel
            if not src.is_file():
                src = find_in_tree(modded, cls)
            if not src:
                print(f"  SKIP-ADD {cls}: source not found")
                skipped += 1
                continue

            dst = new_dex / mod_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            added += 1

    print(f"Overlay: {copied} overwritten, {added} new, {blocked} blocked, {skipped} skipped")
    print(f"Total smali in output: {sum(1 for _ in official.rglob('*.smali'))}")


if __name__ == "__main__":
    main()
