#!/usr/bin/env python3
"""
smali_diff_harvester.py — Compare official vs modded smali directories
using 3-level content hashing, class-name pairing, and Lancet/DPatch
classification.

Given two apktool d output directories (official & modded), finds every
logical code change by pairing classes on their .class directive rather
than file path, filters out debug-metadata noise, and writes reusable
unified-diff patches to a structured output tree.

Usage:
    python smali_diff_harvester.py \\
        --official /path/to/official/smali \\
        --modded /path/to/modded/smali \\
        --output ./patches \\
        --report ./patch-report.json
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── regex patterns ──────────────────────────────────────────────────────

# Extract fully qualified internal class name from .class directive
# Example: ".class public Lzo4/b;"  ->  "zo4.b"
RE_CLASS = re.compile(
    r"^\.class\s+(?:public\s+|final\s+|abstract\s+|static\s+|strict\s+)*"
    r"L([\w/$-]+);",
    re.MULTILINE,
)

# Debug-metadata lines that carry no execution semantics.
RE_STRIP: List[re.Pattern] = [
    re.compile(r"^\.prologue$"),
    re.compile(r"^\.line\s+\d+$"),
    re.compile(r'^\.source\s+"[^"]*"$'),
    re.compile(r"^\.local\s+\d+,"),  # debug local var (has var name after comma)
    re.compile(r"^\.end local$"),
    re.compile(r"^\.restart local\s+\d+$"),
    re.compile(r'^\.param\s+\w+(?:,\s*"[^"]*")?$'),  # debug param info
]

# Lancet framework patterns
RE_LANCET = re.compile(r"Lancet|@Proxy|\.LANNET\.", re.IGNORECASE)
RE_CREATOR_PROXY = re.compile(
    r"invoke-static\s*\{.*?\},\s*Lcom/pandora/core/CreatorProxy",
    re.IGNORECASE,
)

# DPatch / pandora-related package prefixes (modded-only additions)
DPATCH_PREFIXES: List[str] = [
    "com/pandora/core",
    "com/bytedance/shadowhook",
    "com/bytedance/fix",
]

# smali file extensions we care about
SMALI_GLOB = "*.smali"


# ── helpers ─────────────────────────────────────────────────────────────


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_debug_metadata(content: str) -> str:
    """Remove debug-metadata lines, keeping all logic-significant lines."""
    out: List[str] = []
    for line in content.splitlines(keepends=False):
        stripped = line.strip()
        if not stripped:
            continue
        skip = False
        for pat in RE_STRIP:
            if pat.match(stripped):
                skip = True
                break
        if not skip:
            out.append(line.rstrip("\n"))
    return "\n".join(out) + "\n"


def extract_class_name(content: str) -> Optional[str]:
    """Parse the .class directive and return the fully qualified class name."""
    m = RE_CLASS.search(content)
    if m:
        # Internal JVM name uses / as separator; convert to dots for key
        return m.group(1).replace("/", ".")
    return None


def extract_class_name_from_file(path: Path) -> Optional[str]:
    """Read only the first dozen lines to find the .class directive."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for _ in range(50):
            line = fh.readline()
            if not line:
                break
            m = RE_CLASS.match(line)
            if m:
                return m.group(1).replace("/", ".")
    return None


def is_lancet_file(content: str) -> bool:
    """Return True when content references the Lancet AOP framework."""
    return bool(RE_LANCET.search(content)) or bool(RE_CREATOR_PROXY.search(content))


def is_dpatch_path(rel_path: str) -> bool:
    """Return True when rel_path falls under a known DPatch/pandora package."""
    return any(rel_path.startswith(p) for p in DPATCH_PREFIXES)


# ── classification ──────────────────────────────────────────────────────


def classify_logical_path(rel_path: str, content: str, lancet: bool) -> str:
    """Pick a semantic subdirectory for a logically-changed file."""
    if lancet:
        return "lancet-hooks"
    if is_dpatch_path(rel_path):
        return "pandora-core"
    name = rel_path.lower()
    if "sign" in name or "check" in name:
        return "sign-checks"
    if "device" in name or "spoof" in name or "param" in name:
        return "device-spoof"
    return "uncategorized"


def classify_only_modded(rel_path: str, content: str) -> str:
    """Classify a file that only exists in the modded tree."""
    if is_dpatch_path(rel_path):
        return "pandora-core"
    if is_lancet_file(content):
        return "lancet-hooks"
    return "uncategorized"


# ── file scanning ───────────────────────────────────────────────────────


def scan_smali_files(root: Path, label: str) -> Dict[str, List[Tuple[str, Path]]]:
    """
    Walk *root* and build  class_name → [(rel_path, abs_path), …]  mapping.

    Streaming reader — only the first ~50 lines of each file are parsed in
    this pass.  Returns a dict so callers can handle duplicates (a class
    appearing in multiple dex directories, which is rare but possible).
    """
    mapping: Dict[str, List[Tuple[str, Path]]] = {}
    count = 0
    no_class_count = 0

    for smali_file in sorted(root.rglob(SMALI_GLOB)):
        rel_path = smali_file.relative_to(root).as_posix()
        class_name = extract_class_name_from_file(smali_file)

        if class_name:
            mapping.setdefault(class_name, []).append((rel_path, smali_file))
        else:
            no_class_count += 1

        count += 1
        if count % 100_000 == 0:
            print(f"  Scanning {label}: {count} files scanned...")

    print(
        f"  Scanning {label}: done — {count} files,"
        f" {len(mapping)} unique classes"
        f" ({no_class_count} without .class directive)"
    )
    return mapping


# ── patch writing ───────────────────────────────────────────────────────


def make_patch_header(
    class_name: str,
    off_rel: str,
    mod_rel: str,
    diff_type: str,
    status: str,
) -> str:
    return (
        f"# Patch: {class_name}\n"
        f"# Official: {off_rel}\n"
        f"# Modded:  {mod_rel}\n"
        f"# Diff type: {diff_type}\n"
        f"# Status: {status}\n"
    )


def write_patch(
    patches_dir: Path,
    category: str,
    class_name: str,
    header: str,
    diff_lines: List[str],
    suffix: str = "",
) -> None:
    """Write a .patch file under patches_dir/{category}/.

    The output filename mirrors the class hierarchy, e.g.
    ``com/example/Foo.smali.patch`` — with an optional suffix to
    distinguish multiple variants of the same class.
    """
    rel_patch = class_name.replace(".", "/") + suffix + ".smali.patch"
    target = patches_dir / category / rel_patch
    os.makedirs(target.parent, exist_ok=True)
    target.write_text(header + "".join(diff_lines), encoding="utf-8")


# ── main ────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare official vs modded smali directories"
        " via 3-level content hashing"
    )
    parser.add_argument(
        "--official", required=True, help="apktool d output for the official APK"
    )
    parser.add_argument(
        "--modded", required=True, help="apktool d output for the modded APK"
    )
    parser.add_argument(
        "--output",
        default="./patches",
        help="patch output directory (default: ./patches)",
    )
    parser.add_argument(
        "--report",
        default="./patch-report.json",
        help="diff summary JSON path (default: ./patch-report.json)",
    )
    args = parser.parse_args()

    official_root = Path(args.official).resolve()
    modded_root = Path(args.modded).resolve()
    patches_dir = Path(args.output).resolve()
    report_path = Path(args.report).resolve()

    if not official_root.is_dir():
        print(f"ERROR: official directory not found: {official_root}", file=sys.stderr)
        sys.exit(1)
    if not modded_root.is_dir():
        print(f"ERROR: modded directory not found: {modded_root}", file=sys.stderr)
        sys.exit(1)

    print(f"Official: {official_root}")
    print(f"Modded:   {modded_root}")
    print(f"Patches:  {patches_dir}")
    print(f"Report:   {report_path}")
    print()

    # ── Phase 1: Scan both trees ─────────────────────────────────────
    print("[Phase 1] Scanning official tree…")
    official_map = scan_smali_files(official_root, "official")
    print()

    print("[Phase 1] Scanning modded tree…")
    modded_map = scan_smali_files(modded_root, "modded")
    print()

    off_classes = set(official_map.keys())
    mod_classes = set(modded_map.keys())
    common = off_classes & mod_classes
    only_off = off_classes - mod_classes
    only_mod = mod_classes - off_classes

    print(f"  Common classes:    {len(common):,}")
    print(f"  Only in official:  {len(only_off):,}")
    print(f"  Only in modded:    {len(only_mod):,}")
    print()

    # ── Phase 2: 3-level comparison ──────────────────────────────────
    print("[Phase 2] 3-level comparison of common classes…")

    # Ensure all output directories exist up front
    for cat_dir in (
        "manifest",
        "smali/metadata",
        "smali/lancet-hooks",
        "smali/pandora-core",
        "smali/sign-checks",
        "smali/device-spoof",
        "smali/uncategorized",
    ):
        os.makedirs(patches_dir / cat_dir, exist_ok=True)

    stats = {
        "exact_match": 0,
        "metadata_only": 0,
        "logical_change": 0,
        "only_official": len(only_off),
        "only_modded": len(only_mod),
    }

    patches: List[dict] = []
    lancet_hooks: set[str] = set()
    dpatch_files: set[str] = set()

    processed = 0
    n_common = len(common)

    for class_name in sorted(common):
        processed += 1
        if processed % 10_000 == 0:
            print(f"  Progress: {processed:,} / {n_common:,} classes")

        off_rel, off_path = official_map[class_name][0]
        mod_rel, mod_path = modded_map[class_name][0]

        off_raw = off_path.read_bytes()
        mod_raw = mod_path.read_bytes()

        # ── Level 1: full-content SHA256 ─────────────────────────
        if sha256_bytes(off_raw) == sha256_bytes(mod_raw):
            stats["exact_match"] += 1
            continue

        off_text = off_raw.decode("utf-8", errors="replace")
        mod_text = mod_raw.decode("utf-8", errors="replace")

        off_stripped = strip_debug_metadata(off_text)
        mod_stripped = strip_debug_metadata(mod_text)

        # ── Level 2: stripped-content SHA256 ─────────────────────
        if sha256_str(off_stripped) == sha256_str(mod_stripped):
            stats["metadata_only"] += 1
            # Skip writing — metadata-only files are not useful patches.
            continue

        # ── Level 3: logical change — diff stripped content ──────
        stats["logical_change"] += 1

        lancet = is_lancet_file(mod_text) or is_lancet_file(off_text)
        if lancet:
            lancet_hooks.add(class_name)

        if is_dpatch_path(mod_rel):
            dpatch_files.add(mod_rel)

        category = classify_logical_path(mod_rel, mod_text, lancet)
        status = "keep"

        header = make_patch_header(
            class_name, off_rel, mod_rel, "logical_change", status
        )
        diff = list(
            difflib.unified_diff(
                off_stripped.splitlines(keepends=True),
                mod_stripped.splitlines(keepends=True),
                fromfile=off_rel,
                tofile=mod_rel,
                n=3,
            )
        )
        write_patch(patches_dir, f"smali/{category}", class_name, header, diff)

        patches.append(
            {
                "class_name": class_name,
                "diff_type": "logical_change",
                "with_lancet": lancet,
                "files": sorted([off_rel, mod_rel]),
                "category": category,
            }
        )

    print(f"  Done — {processed:,} classes compared")
    print()

    # ── Phase 3: Only-modded files ───────────────────────────────────
    print(f"[Phase 3] Processing {len(only_mod):,} modded-only classes…")

    mod_only_processed = 0
    for class_name in sorted(only_mod):
        mod_rel, mod_path = modded_map[class_name][0]
        mod_text = mod_path.read_text(encoding="utf-8", errors="replace")
        mod_stripped = strip_debug_metadata(mod_text)
        lancet = is_lancet_file(mod_text)

        if lancet:
            lancet_hooks.add(class_name)

        category = classify_only_modded(mod_rel, mod_text)
        if category == "pandora-core":
            dpatch_files.add(mod_rel)

        header = make_patch_header(
            class_name, "(none)", mod_rel, "added", "keep"
        )
        diff = list(
            difflib.unified_diff(
                [],
                mod_stripped.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=mod_rel,
                n=3,
            )
        )
        write_patch(patches_dir, f"smali/{category}", class_name, header, diff)

        patches.append(
            {
                "class_name": class_name,
                "diff_type": "added",
                "with_lancet": lancet,
                "files": [mod_rel],
                "category": category,
            }
        )

        mod_only_processed += 1
        if mod_only_processed % 10_000 == 0:
            print(f"  Progress: {mod_only_processed:,} / {len(only_mod):,}")

    print(f"  Done — {mod_only_processed:,} modded-only files processed")
    print()

    # ── Phase 4: Write report (compact — omit metadata_only) ───────
    print("[Phase 4] Writing report…")

    # Only include logical changes and added files in the report
    meaningful = [p for p in patches if p.get("diff_type") != "metadata_only"]
    print(f"  {len(patches)} total patches; writing {len(meaningful)} meaningful entries")

    uncategorized = [p["class_name"] for p in patches if p.get("category") == "uncategorized"]

    report = {
        "stats": stats,
        "patches": meaningful,        # exclude 170K metadata entries
        "lancet_hooks": sorted(lancet_hooks),
        "dpatch_files": sorted(dpatch_files),
        "uncategorized": sorted(uncategorized),
    }

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Report size: {report_path.stat().st_size / 1024:.0f} KB")

    # ── Summary ───────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  Summary")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k:>20s}: {v:>8,}")
    print(f"  {'Lancet hooks':>20s}: {len(lancet_hooks):>8,}")
    print(f"  {'DPatch files':>20s}: {len(dpatch_files):>8,}")
    print(f"  {'Patches dir':>20s}: {patches_dir}")
    print(f"  {'Report':>20s}: {report_path}")
    print()


if __name__ == "__main__":
    main()
