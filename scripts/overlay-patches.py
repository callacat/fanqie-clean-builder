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

We copy modded → official for every logical_change (1 422 files),
and append new modded-only files (900 files) to smali_classes29.
"""

from __future__ import annotations

import argparse, json, shutil, re, sys
from pathlib import Path

SAFE_NEW = frozenset({
    "com/pandora/core/CreatorProxy.smali",
    "com/pandora/core/AppFactory$DATA.smali",
})

BLOCKLIST = frozenset({
    "com/pandora/core/AppFactory.smali",
    "com/pandora/core/Copyright.smali",
    "com/pandora/core/ۧۤۤ.smali",
})

RE_CLASS = re.compile(
    r'^\.class\s+(?:public\s+|final\s+|abstract\s+|static\s+)*L([\w/$-]+);',
    re.MULTILINE,
)


def build_class_index(root: Path) -> dict[str, Path]:
    """Scan all smali dirs once and return {class_name: file_path}."""
    idx: dict[str, Path] = {}
    for smali_dir in root.glob("smali*"):
        if not smali_dir.is_dir():
            continue
        for f in smali_dir.rglob("*.smali"):
            head = f.read_bytes()[:2000]
            m = RE_CLASS.search(head.decode("utf-8", errors="replace"))
            if m:
                idx[m.group(1)] = f
    return idx


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

    # Build class indices once (O(n) total, not O(n²))
    print("Building class index for official tree…")
    official_idx = build_class_index(official)
    print(f"  {len(official_idx)} classes indexed")
    print("Building class index for modded tree…")
    modded_idx = build_class_index(modded)
    print(f"  {len(modded_idx)} classes indexed")

    copied = skipped = added = blocked = 0

    for p in report.get("patches", []):
        dt = p["diff_type"]
        cls = p["class_name"]
        files = p.get("files", [])
        cat = p.get("category", "uncategorized")

        if dt == "metadata_only":
            continue

        jvm_name = cls.replace(".", "/")

        if dt == "logical_change" and len(files) >= 2:
            mod_rel = files[1]
            src = modded / mod_rel
            if not src.is_file():
                src = modded_idx.get(jvm_name)
            if not src:
                print(f"  SKIP {cls}: modded source not found")
                skipped += 1
                continue

            dst = official_idx.get(jvm_name)
            if not dst:
                dst = official / mod_rel
                dst.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(src, dst)
            copied += 1

        elif dt == "added" and files:
            mod_rel = files[0]

            if mod_rel in BLOCKLIST:
                blocked += 1
                continue

            if cat == "uncategorized" and mod_rel not in SAFE_NEW:
                blocked += 1
                continue

            src = modded / mod_rel
            if not src.is_file():
                src = modded_idx.get(jvm_name)
            if not src:
                print(f"  SKIP-ADD {cls}: source not found")
                skipped += 1
                continue

            dst = new_dex / mod_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            added += 1

    print(f"Overlay: {copied} overwritten, {added} new, {blocked} blocked, {skipped} skipped")


if __name__ == "__main__":
    main()
